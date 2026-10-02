"""D-161 step 1: real-time liquidity-incentive (LIP) meter per contract.

Kalshi pays a program only if it earns at least $1 for that contract (market
ticker), not per event. The older reward tracker samples a market only when
its book changes and credits only strictly proven intervals, so it covered
about 1% of the time and Kalshi paid 3.9x its estimate. This meter samples
every contract with our orders resting on a fixed clock, scores our resting
orders in the live book with the bot's own Kalshi scoring (``program_plans``:
our qualifying size against everyone's, weighted by distance from the best
price, within the target size, two-sided), and integrates the program's
reward rate over time. Measurement only: never order authority; validated
against payouts before phase 3 relies on it (WATCHLIST B9).
"""
import json
import math
import os
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from .quoting import program_plans
from .ranking import seconds
from .values import InvalidData, utc

ZERO = Decimal(0)
MINIMUM_PAYOUT = Decimal(1)   # Kalshi pays nothing for a program under $1


def payout_after_floor(earned):
    """What Kalshi pays for one program: all of it at $1 or more, else nothing."""
    return earned if earned >= MINIMUM_PAYOUT else ZERO


class LipMeter:
    SAMPLE_SECONDS = 5
    MAX_GAP_SECONDS = 15        # a longer gap (restart, stall) is not credited
    SAVE_SECONDS = 300
    CAPACITY = 4096
    KEEP_DAYS = 14              # ended programs are kept for payout matching
    BYTES_LIMIT = 4194304

    def __init__(self, path=None):
        self.path = path
        self.programs = {}      # program_id -> dict(ticker, end, first_at, earned, seconds)
        self.rates = {}         # program_id -> reward rate ($/s) at the previous sample
        self.last_mono = None
        self.samples = self.unknown = self.unscored = self.errors = 0
        self.gaps = self.save_failures = 0
        self.payouts = []       # D-173: credits matched to just-ended programs

    def sample(self, mono, now, markets):
        """One observation. ``markets`` lists (ticker, book, bands, programs,
        quotes) for every contract with our orders resting, or None when our
        order view or the program catalog is unknown (the next interval is
        then not credited). Each interval earns the rate seen at its start."""
        if markets is None or type(mono) not in (int, float) or not math.isfinite(mono):
            self.unknown += 1
            self.last_mono = None
            return
        now = utc(now)
        if self.last_mono is not None:
            gap = mono-self.last_mono
            if 0 < gap <= self.MAX_GAP_SECONDS:
                elapsed = Decimal(str(gap))
                for pid, rate in self.rates.items():
                    row = self.programs.get(pid)
                    if row is not None:
                        row['earned'] += rate*elapsed
                        row['seconds'] += elapsed
            elif gap > self.MAX_GAP_SECONDS:
                self.gaps += 1
        rates = {}
        for ticker, book, bands, programs, quotes in markets:
            if not programs or not quotes:
                continue
            if book is None or bands is None:
                self.unscored += 1
                continue
            try:
                plans = program_plans(book, programs, bands, now=now, market_open=True,
                                      reflected=quotes, proposed=quotes)
            except (InvalidData, ArithmeticError):
                self.errors += 1
                continue
            for program, plan in zip(programs, plans):
                with localcontext() as ctx:
                    ctx.prec = 40
                    rate = (Decimal(program.pool_centicents)/10000
                            / seconds(program.end-program.start))*plan.snapshot_share
                row = self.programs.get(program.program_id)
                if row is None:
                    if len(self.programs) >= self.CAPACITY:
                        self._prune(now)
                        if len(self.programs) >= self.CAPACITY:
                            self.errors += 1
                            continue
                    row = self.programs[program.program_id] = dict(
                        ticker=ticker, end=program.end, first_at=now, earned=ZERO, seconds=ZERO)
                rates[program.program_id] = rate
        self.rates, self.last_mono = rates, mono
        self.samples += 1

    def _prune(self, now):
        cutoff = utc(now)-timedelta(days=self.KEEP_DAYS)
        for pid in [p for p, row in self.programs.items() if row['end'] < cutoff]:
            del self.programs[pid]
            self.rates.pop(pid, None)

    PAYOUTS_KEPT = 50
    MATCH_HOURS = 36            # credits so far arrived 6-18 h after a program ended
    MATCH_FLOOR = Decimal('0.75')   # estimates may sit a little under the paid $1

    def ending_soon(self, now, *, hours=96, minimum=Decimal('0.05')):
        """D-173: programs ending within ``hours`` with at least ``minimum``
        earned, soonest first: what will pay, and what will end under $1."""
        now = utc(now)
        rows = [row for row in self.programs.values()
                if now < row['end'] <= now+timedelta(hours=hours) and row['earned'] >= minimum]
        return [dict(ticker=row['ticker'], ends=row['end'].isoformat(),
                     hours_left=round(float(seconds(row['end']-now))/3600, 1),
                     earned_usd=str(round(row['earned'], 4)),
                     pays=row['earned'] >= MINIMUM_PAYOUT)
                for row in sorted(rows, key=lambda r: (r['end'], -r['earned']))]

    def match_credit(self, amount, now):
        """D-173: name the just-ended program a reward credit most likely paid
        (closest estimate among programs ended in the last MATCH_HOURS with at
        least MATCH_FLOOR earned). An estimate, never accounting."""
        now, amount = utc(now), Decimal(amount)
        ended = [(pid, row) for pid, row in self.programs.items()
                 if now-timedelta(hours=self.MATCH_HOURS) <= row['end'] <= now
                 and row['earned'] >= self.MATCH_FLOOR]
        ended.sort(key=lambda item: (abs(item[1]['earned']-amount), item[1]['end']))
        match = dict(at=now.isoformat(), amount=str(amount),
                     best=(dict(ticker=ended[0][1]['ticker'], estimated_usd=str(round(ended[0][1]['earned'], 4)),
                                ended=ended[0][1]['end'].isoformat()) if ended else None),
                     candidates=[dict(ticker=row['ticker'], estimated_usd=str(round(row['earned'], 4)))
                                 for _, row in ended[:5]])
        self.payouts.append(match)
        del self.payouts[:-self.PAYOUTS_KEPT]
        return match

    def save(self, now):
        if self.path is None:
            return
        self._prune(now)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(programs={pid: dict(
            ticker=row['ticker'], end=row['end'].isoformat(), first_at=row['first_at'].isoformat(),
            earned=str(row['earned']), seconds=str(row['seconds']))
            for pid, row in self.programs.items()}, payouts=self.payouts)), encoding='utf-8')
        os.replace(temp, self.path)

    def load(self):
        """Restore saved totals; a missing, oversized or corrupt file starts empty."""
        try:
            if self.path is None:
                return self
            if self.path.stat().st_size > self.BYTES_LIMIT:
                raise ValueError('LIP meter history exceeds size limit')
            document = json.loads(self.path.read_text(encoding='utf-8'))
            raw = document['programs']
            payouts = document.get('payouts', [])
            if type(payouts) is not list:
                raise ValueError('invalid payout matches')
            programs = {}
            for pid, row in raw.items():
                earned, spent = Decimal(row['earned']), Decimal(row['seconds'])
                if (not isinstance(pid, str) or not isinstance(row['ticker'], str)
                        or not earned.is_finite() or not spent.is_finite()
                        or earned < 0 or spent < 0):
                    raise ValueError('invalid LIP meter row')
                programs[pid] = dict(ticker=row['ticker'], end=utc(datetime.fromisoformat(row['end'])),
                                     first_at=utc(datetime.fromisoformat(row['first_at'])),
                                     earned=earned, seconds=spent)
            self.programs = dict(list(programs.items())[:self.CAPACITY])
            self.payouts = payouts[-self.PAYOUTS_KEPT:]
        except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation, InvalidData):
            self.programs = {}
        return self

    def status(self, now, *, limit=15):
        now = utc(now)
        live = [(pid, row) for pid, row in self.programs.items() if row['end'] > now]
        top = sorted(live, key=lambda item: -item[1]['earned'])[:limit]
        return dict(programs=len(self.programs), live=len(live), samples=self.samples,
            unknown=self.unknown, unscored=self.unscored, errors=self.errors, gaps=self.gaps,
            save_failures=self.save_failures,
            earned_live_usd=str(round(sum((r['earned'] for _, r in live), ZERO), 4)),
            cleared_live=sum(1 for _, r in live if r['earned'] >= MINIMUM_PAYOUT),
            payable_live_usd=str(round(sum((payout_after_floor(r['earned']) for _, r in live), ZERO), 4)),
            top=[dict(ticker=r['ticker'], earned_usd=str(round(r['earned'], 4)),
                      hours_left=round(seconds(r['end']-now)/3600, 1),
                      cleared=r['earned'] >= MINIMUM_PAYOUT) for _, r in top],
            ending_soon=self.ending_soon(now)[:40], payouts=self.payouts[-10:],
            estimate_only=True, authorized=False)
