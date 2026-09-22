"""Sampled per-program estimates, never payable cash or trading authority."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from .quoting import Program, Quote, program_plans
from .ranking import seconds
from .values import InvalidData, decimal, identity, integer, utc


ZERO = Decimal(0)


@dataclass(frozen=True)
class RewardSample:
    at: datetime
    valid_until: datetime
    rate: Decimal | None
    continuity: tuple
    qualified: bool
    reason: str


@dataclass
class RewardRecord:
    program: Program
    first_at: datetime
    last_at: datetime
    estimate: Decimal = ZERO
    observed_seconds: Decimal = ZERO
    qualifying_seconds: Decimal = ZERO
    unknown_seconds: Decimal = ZERO
    conflict: bool = False
    sample: RewardSample | None = None


@dataclass(frozen=True)
class RewardProgress:
    program_id: str
    ticker: str
    sampled_gross_usd: Decimal
    qualifying_seconds: Decimal
    observed_seconds: Decimal
    unknown_seconds: Decimal
    unobserved_before_tracking_seconds: Decimal
    current_hourly_usd: Decimal | None
    seconds_to_minimum: Decimal | None
    safe_seconds_remaining: Decimal
    minimum_reachable_at_current_rate: bool | None
    state: str
    reason: str
    paid_usd: None = None
    payout_confirmed: bool = False
    authorized: bool = False


class RewardTracker:
    def __init__(self, *, scope, capacity=4096):
        self.scope = identity(scope)
        self.capacity = integer(capacity, 1, 4096)
        self.records = {}
        self._by_market = {}
        self.revision = 0

    def record(self, program, *, at, valid_until, rate, continuity=(), qualified=False,
               reason='source_unverified'):
        """Normalized observation boundary. Rate is an estimate, not venue credit."""
        at, until = utc(at), utc(valid_until)
        if not isinstance(program, Program):
            raise InvalidData('validated reward program required')
        if type(continuity) is not tuple or len(continuity) > 12:
            raise InvalidData('bounded source continuity required')
        for value in continuity:
            if isinstance(value, str): identity(value)
            else: integer(value, 0, 2**63-1)
        if reason not in {'observed_orders', 'no_owned_orders', 'source_unverified',
                          'reflection_unverified', 'source_lost', 'unsupported_terms'}:
            raise InvalidData('static reward reason required')
        if type(qualified) is not bool or not at <= until <= at+timedelta(seconds=5):
            raise InvalidData('bounded reward sample freshness required')
        if rate is not None:
            rate = decimal(rate)
            with localcontext() as ctx:
                ctx.prec = 40
                maximum = Decimal(program.pool_centicents)/10000/seconds(program.end-program.start)
            if rate < 0 or rate > maximum or (rate and not qualified) or not continuity:
                raise InvalidData('invalid estimated reward rate or continuity')
        elif qualified:
            raise InvalidData('unknown reward cannot qualify')
        existing = self.records.get(program.program_id)
        if existing is None:
            if len(self.records) >= self.capacity:
                raise InvalidData('reward history capacity exhausted; no automatic eviction')
            existing = RewardRecord(program, at, at)
            self.records[program.program_id] = existing
            self._by_market.setdefault(program.ticker, set()).add(program.program_id)
        if at < existing.last_at:
            existing.sample = None
            self.revision += 1
            raise InvalidData('reward observation clock regressed')
        # A program identity is never silently rebound to edited terms or ticker.
        if program != existing.program:
            existing.conflict = True
        previous = existing.sample
        start, end = max(existing.last_at, existing.program.start), min(at, existing.program.end)
        elapsed = max(ZERO, seconds(end-start))
        with localcontext() as ctx:
            ctx.prec = 40
            covered = (not existing.conflict and previous is not None
                and previous.rate is not None and rate is not None
                and previous.continuity == continuity
                and at <= previous.valid_until and at-previous.at <= timedelta(seconds=5))
            if covered:
                existing.observed_seconds += elapsed
                if previous.qualified and qualified:
                    existing.qualifying_seconds += elapsed
                    existing.estimate += min(previous.rate, rate)*elapsed
            else:
                existing.unknown_seconds += elapsed
        existing.last_at = at
        existing.sample = RewardSample(at, until, None if existing.conflict else rate,
                                      continuity, qualified and not existing.conflict, reason)
        self.revision += 1

    def observe(self, program, *, book, bands, quotes, reflected_known, at, valid_until,
                continuity, market_open=True):
        """Score actual owned quantities exactly once in a proven reflected book.

        Reflection/continuity evidence belongs to the caller. A public ladder
        merely containing enough quantity does not establish that evidence.
        """
        self.observe_many((program,),book=book,bands=bands,quotes=quotes,
            reflected_known=reflected_known,at=at,valid_until=valid_until,
            continuity=continuity,market_open=market_open)

    def observe_many(self, programs, *, book, bands, quotes, reflected_known, at,
                     valid_until, continuity, market_open=True):
        """Share book validation across at most sixteen independent programs."""
        if (type(programs) is not tuple or not 1 <= len(programs) <= 16
                or any(not isinstance(p,Program) for p in programs)
                or len({p.program_id for p in programs}) != len(programs)):
            raise InvalidData('bounded unique reward programs required')
        try:
            self._observe_many(programs,book=book,bands=bands,quotes=quotes,
                reflected_known=reflected_known,at=at,valid_until=valid_until,
                continuity=continuity,market_open=market_open)
        except InvalidData:
            for ticker in {p.ticker for p in programs}: self.invalidate(ticker)
            raise

    def _observe_many(self, programs, *, book, bands, quotes, reflected_known, at,
                      valid_until, continuity, market_open):
        if (any(p.ticker != book.ticker for p in programs)
                or type(quotes) is not tuple or len(quotes) > 30
                or any(not isinstance(q, Quote) for q in quotes)
                or type(reflected_known) is not bool or type(market_open) is not bool):
            raise InvalidData('bounded actual quotes and explicit evidence required')
        active = tuple(p for p in programs if reflected_known and quotes and market_open
            and not p.paid_out and p.max_reward_centicents is None and p.start <= utc(at) < p.end)
        scores = dict(zip((p.program_id for p in active),program_plans(book,active,bands,
            now=at,market_open=market_open,reflected=quotes,proposed=quotes))) if active else {}
        for program in programs:
            rate, qualified, reason = None, False, 'reflection_unverified'
            if reflected_known:
                if not quotes:
                    rate, reason = ZERO, 'no_owned_orders'
                elif program.max_reward_centicents is not None:
                    reason = 'unsupported_terms'
                elif program.program_id in scores:
                    share = scores[program.program_id].snapshot_share
                    with localcontext() as ctx:
                        ctx.prec = 40
                        rate = Decimal(program.pool_centicents)/10000*share/seconds(program.end-program.start)
                    qualified, reason = share > 0, 'observed_orders'
                else:
                    rate, reason = ZERO, 'observed_orders'
            self.record(program, at=at, valid_until=valid_until, rate=rate,
                        continuity=continuity, qualified=qualified, reason=reason)

    def invalidate(self, ticker):
        for key in self._by_market.get(ticker, ()):
            self.records[key].sample = None
        self.revision += 1

    def progress(self, program_id, *, now, exit_at, source_current=True):
        record = self.records[program_id]
        now, exit_at = utc(now), utc(exit_at)
        p, sample = record.program, record.sample
        if now < record.last_at:
            raise InvalidData('reward report clock regressed')
        # No extrapolated time is silently booked just by viewing a report.
        end = min(now, p.end)
        unknown = record.unknown_seconds+max(ZERO, seconds(end-max(record.last_at,p.start)))
        remaining = max(ZERO,seconds(min(p.end,exit_at)-now))
        rate = (sample.rate if source_current is True and sample is not None
                and sample.at <= now < sample.valid_until and not record.conflict
                and p.start <= now < p.end and not p.paid_out else None)
        eta = reachable = None
        with localcontext() as ctx:
            ctx.prec = 40
            if rate is not None:
                eta = (ZERO if record.estimate >= 1 else (1-record.estimate)/rate if rate else None)
                reachable = record.estimate >= 1 or (eta is not None and eta <= remaining)
            hourly = None if rate is None else rate*3600
        state = ('TERMS_CHANGED' if record.conflict else 'ENDED' if now >= p.end
                 else 'UNKNOWN' if rate is None else 'ESTIMATED_MINIMUM_REACHED'
                 if record.estimate >= 1 else 'ESTIMATING' if rate else 'NOT_SCORING')
        return RewardProgress(p.program_id,p.ticker,record.estimate,record.qualifying_seconds,
            record.observed_seconds,unknown,max(ZERO,seconds(min(record.first_at,p.end)-p.start)),
            hourly,eta,remaining,reachable,state,
            sample.reason if sample is not None else 'source_lost')

    def checkpoint(self):
        """Bounded primitive copy; source samples are deliberately not persisted."""
        rows = []
        for key in sorted(self.records):
            r = self.records[key]
            p = r.program
            rows.append(dict(program=dict(program_id=p.program_id,ticker=p.ticker,
                start=p.start.isoformat(),end=p.end.isoformat(),target=str(p.target),
                discount_bps=p.discount_bps,pool_centicents=p.pool_centicents,paid_out=p.paid_out,
                max_reward_centicents=p.max_reward_centicents), first_at=r.first_at.isoformat(),
                last_at=r.last_at.isoformat(),estimate=str(r.estimate),
                observed_seconds=str(r.observed_seconds),qualifying_seconds=str(r.qualifying_seconds),
                unknown_seconds=str(r.unknown_seconds), conflict=r.conflict))
        return dict(schema=1,scope=self.scope,records=rows)

    def restore(self, data):
        if self.records:
            raise InvalidData('restore requires an unused reward tracker')
        try:
            if (type(data) is not dict or set(data) != {'schema','scope','records'}
                    or type(data['schema']) is not int or data['schema'] != 1 or data['scope'] != self.scope
                    or type(data['records']) is not list or len(data['records']) > self.capacity):
                raise InvalidData('unsupported reward checkpoint scope or bounds')
            restored = {}
            for row in data['records']:
                if set(row) != {'program','first_at','last_at','estimate','observed_seconds',
                                'qualifying_seconds','unknown_seconds','conflict'}:
                    raise InvalidData('invalid reward checkpoint fields')
                raw = dict(row['program'])
                raw['start'],raw['end'] = (datetime.fromisoformat(raw[k]) for k in ('start','end'))
                p = Program(**raw)
                first,last = (utc(datetime.fromisoformat(row[k])) for k in ('first_at','last_at'))
                numbers = ('estimate','observed_seconds','qualifying_seconds','unknown_seconds')
                if any(type(row[k]) is not str or len(row[k]) > 100 for k in numbers):
                    raise InvalidData('invalid checkpoint decimal encoding')
                estimate,observed,qualified,unknown = (decimal(Decimal(row[k])) for k in numbers)
                duration = max(ZERO, seconds(min(last,p.end)-max(first,p.start)))
                if (p.program_id in restored or first > last or min(estimate,observed,qualified,unknown) < 0
                        or qualified > observed or observed+unknown != duration
                        or estimate > Decimal(p.pool_centicents)/10000
                        or type(row['conflict']) is not bool):
                    raise InvalidData('inconsistent reward checkpoint')
                restored[p.program_id] = RewardRecord(p,first,last,estimate,observed,qualified,
                                                     unknown,row['conflict'])
        except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation) as exc:
            raise InvalidData('invalid reward checkpoint; preserve for investigation') from exc
        self.records = restored
        self._by_market = {}
        for key, record in restored.items():
            self._by_market.setdefault(record.program.ticker,set()).add(key)
        self.revision += 1
