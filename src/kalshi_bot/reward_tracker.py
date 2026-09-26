"""Sampled per-program estimates, never payable cash or trading authority."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from . import quoting
from .quoting import Program, Quote, program_plans
from .ranking import seconds
from .values import InvalidData, decimal, identity, integer, utc


ZERO = Decimal(0)
# D-137: counterfactual own-size multipliers scored on the same live books.
WHATIF_MULTIPLIERS = (2, 3)


@dataclass(frozen=True)
class RewardSample:
    at: datetime
    valid_until: datetime
    rate: Decimal | None
    continuity: tuple
    qualified: bool
    reason: str
    whatif: tuple = ()


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
        # D-137: process-local measurement since start; never checkpointed and
        # never used for trading. Explains unknown time and scores the same
        # books with larger own quantities (what-if, not a forecast of fills).
        self.session_started = None
        self.session_estimate = ZERO
        self.session_whatif = [ZERO for _ in WHATIF_MULTIPLIERS]
        self.session_observed = ZERO
        self.session_qualifying = ZERO
        self.session_unknown = {}
        self.session_markets = {}

    def record(self, program, *, at, valid_until, rate, continuity=(), qualified=False,
               reason='source_unverified', whatif=()):
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
        if whatif:
            if (type(whatif) is not tuple or len(whatif) != len(WHATIF_MULTIPLIERS)
                    or rate is None or not qualified):
                raise InvalidData('what-if rates require a qualified observed rate')
            whatif = tuple(decimal(value) for value in whatif)
            with localcontext() as ctx:
                ctx.prec = 40
                maximum = Decimal(program.pool_centicents)/10000/seconds(program.end-program.start)
            if any(value < 0 or value > maximum for value in whatif):
                raise InvalidData('invalid what-if reward rate')
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
            if self.session_started is None:
                self.session_started = at
            market = self.session_markets.setdefault(program.ticker,
                [ZERO, [ZERO for _ in WHATIF_MULTIPLIERS], ZERO])
            if covered:
                existing.observed_seconds += elapsed
                self.session_observed += elapsed
                if previous.qualified and qualified:
                    existing.qualifying_seconds += elapsed
                    earned = min(previous.rate, rate)*elapsed
                    existing.estimate += earned
                    self.session_estimate += earned
                    self.session_qualifying += elapsed
                    market[0] += earned
                    market[2] += elapsed
                    if previous.whatif and whatif:
                        for i, (old, new) in enumerate(zip(previous.whatif, whatif)):
                            extra = min(old, new)*elapsed
                            self.session_whatif[i] += extra
                            market[1][i] += extra
            else:
                existing.unknown_seconds += elapsed
                if elapsed:
                    label = self._unknown_reason(existing, previous, rate, reason,
                                                 continuity, elapsed)
                    self.session_unknown[label] = self.session_unknown.get(label, ZERO)+elapsed
        existing.last_at = at
        existing.sample = RewardSample(at, until, None if existing.conflict else rate,
                                      continuity, qualified and not existing.conflict, reason,
                                      whatif if not existing.conflict else ())
        self.revision += 1

    @staticmethod
    def _unknown_reason(existing, previous, rate, reason, continuity, elapsed):
        """Fixed label for why an interval could not be credited (D-137)."""
        if existing.conflict:
            return 'terms_changed'
        if elapsed > 60:
            return 'not_running_or_long_gap'  # e.g. stopped or restarting
        if previous is None:
            return 'no_prior_sample'
        if rate is None:
            return reason
        if previous.rate is None:
            return previous.reason
        if previous.continuity != continuity:
            return 'continuity_changed'
        return 'stale_gap'

    def session_status(self, *, limit=30):
        """Process-local reward measurement since start (D-137); estimate only."""
        with localcontext() as ctx:
            ctx.prec = 40
            base = self.session_estimate
            whatif = {f'{k}x': dict(usd=str(v), uplift=(str(v/base) if base else None))
                      for k, v in zip(WHATIF_MULTIPLIERS, self.session_whatif)}
            unknown = sum(self.session_unknown.values(), ZERO)
            covered = self.session_observed+unknown
            markets = sorted(self.session_markets.items(), key=lambda item: -item[1][0])[:limit]
            return dict(started_at=self.session_started.isoformat() if self.session_started else None,
                estimate_usd=str(base), whatif=whatif,
                observed_seconds=str(self.session_observed),
                qualifying_seconds=str(self.session_qualifying),
                unknown_seconds=str(unknown),
                observed_fraction=(str(self.session_observed/covered) if covered else None),
                unknown_by_reason={k: str(v) for k, v in sorted(
                    self.session_unknown.items(), key=lambda item: -item[1])},
                markets=[dict(ticker=t, estimate_usd=str(m[0]), qualifying_seconds=str(m[2]),
                              **{f'whatif_{k}x_usd': str(v) for k, v in zip(WHATIF_MULTIPLIERS, m[1])})
                         for t, m in markets],
                estimate_only=True, authorized=False)

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
        # D-137: the same book with our own quantities scaled; other makers'
        # depth is unchanged, so this is a share counterfactual, not a fill model.
        whatifs = {}
        if active:
            base = quoting._base(book, bands, quotes)  # One validation for all variants.
            for multiple in WHATIF_MULTIPLIERS:
                scaled = tuple(replace(q, quantity=q.quantity*multiple) for q in quotes)
                for p in active:
                    levels = {s: dict(rows) for s, rows in base.items()}
                    with localcontext() as ctx:
                        ctx.prec = 40
                        share = quoting._snapshot_from_base(levels, p, bands, scaled)[2]
                    whatifs.setdefault(p.program_id, []).append(share)
        for program in programs:
            rate, qualified, reason, whatif = None, False, 'reflection_unverified', ()
            if reflected_known:
                if not quotes:
                    rate, reason = ZERO, 'no_owned_orders'
                elif program.max_reward_centicents is not None:
                    reason = 'unsupported_terms'
                elif program.program_id in scores:
                    share = scores[program.program_id].snapshot_share
                    with localcontext() as ctx:
                        ctx.prec = 40
                        per_share = Decimal(program.pool_centicents)/10000/seconds(program.end-program.start)
                        rate = per_share*share
                        whatif = (tuple(per_share*s for s in whatifs[program.program_id])
                                  if share > 0 else ())
                    qualified, reason = share > 0, 'observed_orders'
                else:
                    rate, reason = ZERO, 'observed_orders'
            self.record(program, at=at, valid_until=valid_until, rate=rate,
                        continuity=continuity, qualified=qualified, reason=reason,
                        whatif=whatif)

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
