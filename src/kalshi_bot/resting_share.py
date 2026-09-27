"""Per-market resting share: measurement for the $1 finish line (phase 3).

Kalshi pays nothing for a program that ends under $1, and the bot's reward
projection assumes it keeps resting until the program ends. This counter
measures, per market, the share of time since we first rested there that we
actually had entry orders resting: leg-seconds / 2 over elapsed seconds, the
same measure as the calibration report. Time without a verified account view
(or a gap longer than MAX_GAP_SECONDS, e.g. a restart) counts neither way.
Saved beside the ledger so restarts keep the history. Never order authority.
"""
import json
import math
import os


class RestingShare:
    SAMPLE_SECONDS = 5
    MAX_GAP_SECONDS = 30      # longer gaps (restart, stalls) are not counted
    SAVE_SECONDS = 300
    CAPACITY = 4096           # markets kept; least recently rested evicted
    BYTES_LIMIT = 4194304

    def __init__(self, path=None):
        self.path = path
        self.markets = {}     # ticker -> [elapsed_s, leg_s, last_rested_mono_or_order]
        self.last = None      # (mono, {ticker: legs}) of the previous verified sample
        self.samples = self.unknown = self.save_failures = 0
        self.serial = 0

    def sample(self, mono, rows):
        """One observation: rows are our resting entry orders (each has a
        ticker), or None when the account view is not verified."""
        if rows is None or type(mono) not in (int, float) or not math.isfinite(mono):
            self.unknown += 1
            self.last = None
            return
        legs = {}
        for row in rows:
            legs[row.ticker] = legs.get(row.ticker, 0)+1
        if self.last is not None:
            before, prior = self.last
            gap = mono-before
            if 0 < gap <= self.MAX_GAP_SECONDS:
                # The interval belongs to the state seen at its start.
                for ticker, state in self.markets.items():
                    state[0] += gap
                    state[1] += gap*min(2, prior.get(ticker, 0))
        for ticker in legs:
            self.serial += 1
            state = self.markets.setdefault(ticker, [0., 0., 0])
            state[2] = self.serial
        if len(self.markets) > self.CAPACITY:
            for ticker, _ in sorted(self.markets.items(), key=lambda item: item[1][2])[
                    :len(self.markets)-self.CAPACITY]:
                del self.markets[ticker]
        self.last = mono, legs
        self.samples += 1

    def share(self, ticker, minimum_seconds=600):
        """Measured share for one market, or None before enough time is seen."""
        state = self.markets.get(ticker)
        if state is None or state[0] < minimum_seconds:
            return None
        return state[1]/2/state[0]  # sample() and load() keep legs within 2 x elapsed

    def median_share(self, minimum_seconds=600):
        values = sorted(s for s in (self.share(t, minimum_seconds) for t in self.markets)
                        if s is not None)
        if not values:
            return None
        middle = len(values)//2
        return values[middle] if len(values) % 2 else (values[middle-1]+values[middle])/2

    def save(self):
        if self.path is None:
            return
        temp = self.path.with_suffix('.tmp')
        ordered = sorted(self.markets.items(), key=lambda item: item[1][2])  # oldest first
        temp.write_text(json.dumps(dict(markets={t: [round(s[0], 1), round(s[1], 1)]
                                                 for t, s in ordered})), encoding='utf-8')
        os.replace(temp, self.path)

    def load(self):
        """Restore saved history; a missing, oversized or corrupt file starts empty."""
        try:
            if self.path is None:
                return self
            if self.path.stat().st_size > self.BYTES_LIMIT:
                raise ValueError('resting share history exceeds size limit')
            raw = json.loads(self.path.read_text(encoding='utf-8'))['markets']
            markets = {}
            for order, (ticker, (elapsed, legs)) in enumerate(raw.items()):
                if (isinstance(ticker, str) and all(type(v) in (int, float) and math.isfinite(v)
                                                    and v >= 0 for v in (elapsed, legs))):
                    markets[ticker] = [float(elapsed), float(min(legs, 2*elapsed)), order]
            self.markets = dict(list(markets.items())[-self.CAPACITY:])
            self.serial = len(raw)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.markets = {}
        return self

    def status(self):
        median = self.median_share()
        return dict(markets=len(self.markets), samples=self.samples, unknown=self.unknown,
                    median_share=None if median is None else round(median, 3),
                    save_failures=self.save_failures)
