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

    def save(self, now):
        if self.path is None:
            return
        self._prune(now)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(programs={pid: dict(
            ticker=row['ticker'], end=row['end'].isoformat(), first_at=row['first_at'].isoformat(),
            earned=str(row['earned']), seconds=str(row['seconds']))
            for pid, row in self.programs.items()})), encoding='utf-8')
        os.replace(temp, self.path)

    def load(self):
        """Restore saved totals; a missing, oversized or corrupt file starts empty."""
        try:
            if self.path is None:
                return self
            if self.path.stat().st_size > self.BYTES_LIMIT:
                raise ValueError('LIP meter history exceeds size limit')
            raw = json.loads(self.path.read_text(encoding='utf-8'))['programs']
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
            estimate_only=True, authorized=False)
