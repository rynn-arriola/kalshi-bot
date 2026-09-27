"""D-158: score every rewarded Kalshi market for our size, every 30 minutes.

The book feeds watch at most 1,024 markets at a time (the engine's capacity),
chosen before this scan by a cheap pool-per-contract hint, so better markets
could sit unseen. This background owner reads every live liquidity program's
market details (50 per request) and order book (100 per request, the
authenticated batch endpoint) on the low-priority read lane, scores them with
the same ``RankingBoard`` the bot trades with, and publishes the estimated
reward still earnable per market before its program ends. Discovery uses fresh scores to choose which
markets to watch; entries still pass every live check. Never order authority.
"""
import asyncio
from datetime import timedelta
from decimal import Decimal

from .books import Book, Ladder
from .market_inputs import tick_bands
from .ranking import RankingBoard
from .values import InvalidData, utc


def score_markets(programs, bands, books, now):
    """Best estimated reward still earnable per market before its program ends
    (0 when it does not score). Total left, not $/hour: an hour-long match can
    show a high rate yet leave well under the bot's $1 entry minimum."""
    scores = {}
    board = RankingBoard(1024)
    for ticker in sorted(programs):
        if ticker not in bands or ticker not in books:
            continue
        if len(board.markets) >= 1024:
            board = RankingBoard(1024)
        try:
            board.update(books[ticker], programs[ticker], bands[ticker], now=now,
                         valid_until=now+timedelta(minutes=30), market_open=True)
        except InvalidData:
            continue
        rows = board.markets.get(ticker, ())
        scores[ticker] = max((r.gross_remaining_usd for r in rows
                              if r.gross_remaining_usd and not r.blockers), default=Decimal(0))
    return scores


def parse_book(ticker, levels):
    """A REST order book as the bot's Book: YES bids as bids, and each NO bid
    at price p as a YES ask at 1 - p (REST returns NO bids at NO prices; the
    live book path already receives asks in YES terms)."""
    book = Book(ticker, Ladder(4096), Ladder(4096))
    for price, size in levels.get('yes_dollars') or ():
        book.bids.set(Decimal(price), Decimal(size))
    for price, size in levels.get('no_dollars') or ():
        book.asks.set(1-Decimal(price), Decimal(size))
    book.valid = True
    return book


class FullMarketScan:
    INTERVAL_SECONDS = 1800
    FIRST_DELAY_SECONDS = 120   # let startup finish first
    FRESH_SECONDS = 2700        # older scores fall back to the pool hint
    MARKET_BATCH = 50
    BOOK_BATCH = 100

    def __init__(self, runtime):
        self.runtime = runtime
        self.scores = {}
        self.scored_mono = None
        self.observed_at = None
        self.runs = self.failures = 0
        self.markets = self.scoring = 0
        self.last_error = None

    def fresh_scores(self):
        mono = self.scored_mono
        if mono is None or self.runtime.clock()-mono > self.FRESH_SECONDS:
            return None
        return self.scores

    async def scan_once(self):
        r = self.runtime
        catalog = r.incentives.current() if r.incentives is not None else None
        if catalog is None:
            raise InvalidData('incentive catalog unavailable')
        now = utc(r.now())
        programs = {}
        for ticker, observation in catalog.observations.items():
            live = tuple(p for p in observation.programs
                         if p.start <= now < p.end and not p.paid_out)[:16]
            if live:
                programs[ticker] = live
        tickers = sorted(programs)
        bands = {}
        for i in range(0, len(tickers), self.MARKET_BATCH):
            chunk = tickers[i:i+self.MARKET_BATCH]
            result = await r.reads.read('markets', reason='scan', tickers=','.join(chunk), limit=1000)
            for market in result.payload.get('markets') or ():
                try:
                    if market.get('status') == 'active' and market.get('ticker') in programs:
                        bands[market['ticker']] = tick_bands(market['price_ranges'])
                except (InvalidData, KeyError, TypeError):
                    continue
            await asyncio.sleep(0)
        books = {}
        active = sorted(bands)
        for i in range(0, len(active), self.BOOK_BATCH):
            chunk = tuple(active[i:i+self.BOOK_BATCH])
            result = await r.reads.read('orderbooks', reason='scan', tickers=chunk)
            for row in result.payload.get('orderbooks') or ():
                try:
                    books[row['ticker']] = parse_book(row['ticker'], row.get('orderbook_fp') or {})
                except (InvalidData, KeyError, TypeError, ArithmeticError):
                    continue
            await asyncio.sleep(0)
        # Scoring is pure arithmetic over thousands of books: keep it off the loop.
        scores = await asyncio.to_thread(score_markets, programs, bands, books, now)
        self.scores, self.scored_mono, self.observed_at = scores, r.clock(), now
        self.markets, self.scoring = len(programs), sum(1 for v in scores.values() if v > 0)
        self.runs += 1
        return scores

    async def run(self):
        r = self.runtime
        delay = self.FIRST_DELAY_SECONDS
        while not r.stop_requested.is_set():
            try:
                await asyncio.wait_for(r.stop_requested.wait(), delay)
                return
            except TimeoutError:
                pass
            try:
                scores = await self.scan_once()
                if getattr(r, 'research', None) is not None:
                    r._research_safely(self._record, scores)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.failures += 1
                self.last_error = f'{type(exc).__name__}: {str(exc)[:160]}'
            delay = self.INTERVAL_SECONDS

    def _record(self, scores):
        """D-156/D-158: the scan's top markets, for the report and a later ranker."""
        stamp = self.observed_at.replace(second=0, microsecond=0).isoformat()
        top = sorted(((v, t) for t, v in scores.items() if v > 0), reverse=True)[:200]
        self.runtime.research.record('candidates', f'scan@{stamp}', source='full_scan',
            markets=self.markets, scoring=self.scoring,
            rows=[dict(rank=i+1, ticker=t, remaining=v) for i, (v, t) in enumerate(top)])

    def status(self):
        age = None if self.scored_mono is None else round(self.runtime.clock()-self.scored_mono, 1)
        return dict(runs=self.runs, failures=self.failures, last_error=self.last_error,
                    markets=self.markets, scoring=self.scoring, age_seconds=age,
                    fresh=self.fresh_scores() is not None)
