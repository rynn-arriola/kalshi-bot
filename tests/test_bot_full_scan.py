"""D-158: score every rewarded market; discovery watches the best-scoring ones."""
import asyncio
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace as NS
import time
import unittest

from kalshi_bot.config import BotConfig, activate
from kalshi_bot.discovery_candidates import CandidateDiscovery
from kalshi_bot.full_scan import FullMarketScan, score_markets, parse_book
from kalshi_bot.incentive_discovery import IncentiveCatalog
from kalshi_bot.rest import request_path
from kalshi_bot.selection_runtime import ProgramObservation
from kalshi_bot.values import InvalidData
from test_bot_engine import NOW, program, BANDS

ROOT = Path(__file__).resolve().parents[1]
UNIT = [dict(start='0.0000', end='1.0000', step='0.0100')]


def catalog(tickers, pools=None):
    observations = {}
    for i, ticker in enumerate(tickers):
        p = program(ticker=ticker, program_id=f'p-{ticker}',
                    pool_centicents=(pools or {}).get(ticker, 1000000-i))
        observations[ticker] = ProgramObservation((p,), NOW, NOW+timedelta(seconds=60))
    return IncentiveCatalog(1, MappingProxyType(observations), frozenset(), '0'*64, NOW,
                            NOW+timedelta(seconds=60), 100, 160, 1, len(tickers), 100)


def levels(bid='0.50', no='0.40'):
    """A REST book with real depth: YES bids and NO bids (NO p = YES ask 1-p)."""
    b, n = D(bid), D(no)
    return dict(yes_dollars=[[str(b), '100'], [str(b-D('.01')), '100'], [str(b-D('.02')), '1000']],
                no_dollars=[[str(n), '100'], [str(n-D('.01')), '100'], [str(n-D('.02')), '1000']])


class RequestTests(unittest.TestCase):
    def test_batch_books_use_repeated_validated_tickers(self):
        _, path = request_path('orderbooks', dict(tickers=('A-1', 'B.2')), 'scan')
        self.assertEqual(path, '/markets/orderbooks?tickers=A-1&tickers=B.2')
        for bad in ((), tuple(f'T{i}' for i in range(101)), ('bad ticker',), 'A-1', ('A&x=1',)):
            with self.subTest(bad=bad), self.assertRaises(InvalidData):
                request_path('orderbooks', dict(tickers=bad), 'scan')
        with self.assertRaises(InvalidData):
            request_path('orderbooks', dict(tickers=('A',)), 'candidate')  # Scan lane only.

    def test_market_details_take_a_long_ticker_list_but_nothing_else(self):
        tickers = ','.join(f'KXLONGTICKERNAMEFORTEST-26OCT07-T{i:03}' for i in range(60))
        self.assertLess(2048, len(tickers))
        _, path = request_path('markets', dict(tickers=tickers, limit=1000), 'scan')
        self.assertTrue(path.startswith('/markets?limit=1000&tickers='))
        for bad in ('A,B&status=open', 'x'*4097):
            with self.subTest(bad=bad[:20]), self.assertRaises(InvalidData):
                request_path('markets', dict(tickers=bad), 'scan')


class ScoreTests(unittest.TestCase):
    def setUp(self):
        import kalshi_bot.config as bot_config  # Never leak the live size into other tests.
        self.addCleanup(setattr, bot_config, '_ACTIVE', bot_config._ACTIVE)
        activate(BotConfig.load(ROOT/'config'/'bot.json'))

    def test_rest_no_bids_become_yes_asks(self):
        book = parse_book('A', dict(yes_dollars=[['0.50', '100']], no_dollars=[['0.46', '20'], ['0.40', '5']]))
        self.assertEqual((book.bids.best(bid=True), book.asks.best(bid=False)), (D('0.50'), D('0.54')))
        self.assertEqual(book.asks.levels, {D('0.54'): D(20), D('0.60'): D(5)})

    def test_a_scoring_market_gets_the_boards_reward_estimate(self):
        from test_bot_engine import book
        engine_book = book()  # bids .50/.49/.48, asks .60/.61/.62: the same book as levels()
        rest_book = parse_book('A', levels())
        self.assertEqual((dict(rest_book.bids.levels), dict(rest_book.asks.levels)),
                         (dict(engine_book.bids.levels), dict(engine_book.asks.levels)))
        scores = score_markets({'A': (program(ticker='A', program_id='p-A'),)}, {'A': BANDS},
                               {'A': rest_book}, NOW)
        self.assertGreater(scores['A'], 0)

    def test_scores_are_the_ranking_boards_estimate_per_market(self):
        programs = {t: (program(ticker=t, program_id=f'p-{t}'),) for t in ('A', 'B', 'C')}
        books = {'A': parse_book('A', levels()), 'B': parse_book('B', levels('0.30', '0.60'))}  # B: .30 / .40
        scores = score_markets(programs, {t: BANDS for t in ('A', 'B', 'C')}, books, NOW)
        self.assertEqual(set(scores), {'A', 'B'})  # C has no book: not scored, not guessed.
        self.assertTrue(all(isinstance(v, D) and v >= 0 for v in scores.values()))

    def test_more_markets_than_one_board_holds_are_all_scored(self):
        tickers = [f'M{i:04}' for i in range(1030)]
        programs = {t: (program(ticker=t, program_id=f'p-{t}'),) for t in tickers}
        books = {t: parse_book(t, levels()) for t in tickers}
        scores = score_markets(programs, {t: BANDS for t in tickers}, books, NOW)
        self.assertEqual(len(scores), 1030)


class ScanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import kalshi_bot.config as bot_config  # Never leak the live size into other tests.
        self.addCleanup(setattr, bot_config, '_ACTIVE', bot_config._ACTIVE)
        activate(BotConfig.load(ROOT/'config'/'bot.json'))
        self.calls = []
        tickers = ['A', 'B', 'C']
        cat = catalog(tickers)
        mono = [100.0]
        async def read(name, *, reason, **params):
            self.calls.append((name, reason, params))
            if name == 'markets':
                return NS(payload=dict(markets=[dict(ticker=t, status='active' if t != 'C' else 'closed',
                    price_ranges=UNIT) for t in params['tickers'].split(',')]))
            return NS(payload=dict(orderbooks=[dict(ticker=t, orderbook_fp=levels())
                                               for t in params['tickers']]))
        self.r = NS(incentives=NS(current=lambda: cat), reads=NS(read=read), now=lambda: NOW,
                    clock=lambda: mono[0], stop_requested=asyncio.Event(), research=None)
        self.mono = mono
        self.scan = FullMarketScan(self.r)

    async def test_one_scan_reads_in_batches_and_scores_active_markets(self):
        self.scan.MARKET_BATCH, self.scan.BOOK_BATCH = 2, 1
        scores = await self.scan.scan_once()
        self.assertEqual(set(scores), {'A', 'B'})  # C is closed.
        names = [(n, r) for n, r, _ in self.calls]
        self.assertEqual(names.count(('markets', 'scan')), 2)
        self.assertEqual(names.count(('orderbooks', 'scan')), 2)
        self.assertEqual(self.scan.status()['markets'], 3)
        self.assertIs(self.scan.fresh_scores(), scores)

    async def test_only_live_unpaid_programs_are_scanned(self):
        from dataclasses import replace
        cat = catalog(['A', 'B', 'C'])
        obs = dict(cat.observations)
        obs['B'] = replace(obs['B'], programs=tuple(replace(p, end=NOW-timedelta(minutes=1),
            start=NOW-timedelta(hours=2)) for p in obs['B'].programs))
        obs['C'] = replace(obs['C'], programs=tuple(replace(p, paid_out=True) for p in obs['C'].programs))
        self.r.incentives = NS(current=lambda: replace(cat, observations=MappingProxyType(obs)))
        scores = await self.scan.scan_once()
        self.assertEqual(set(scores), {'A'})
        self.assertEqual(self.scan.markets, 1)

    async def test_scores_expire_back_to_the_pool_hint(self):
        await self.scan.scan_once()
        self.mono[0] += self.scan.FRESH_SECONDS+1
        self.assertIsNone(self.scan.fresh_scores())

    async def test_a_failing_scan_is_counted_and_retried_later(self):
        self.r.incentives = NS(current=lambda: None)
        self.scan.FIRST_DELAY_SECONDS = .01
        task = asyncio.create_task(self.scan.run())
        await asyncio.sleep(.05)
        self.r.stop_requested.set()
        await asyncio.wait_for(task, 2)
        self.assertEqual(self.scan.failures, 1)
        self.assertIn('catalog unavailable', self.scan.last_error)
        self.assertIsNone(self.scan.fresh_scores())

    async def test_top_markets_go_to_research(self):
        from kalshi_bot.research import ResearchStore
        with TemporaryDirectory() as temp:
            store = ResearchStore(Path(temp)/'research.db').start()
            self.r.research = store
            self.r._research_safely = lambda fn, *a: fn(*a)
            self.scan.FIRST_DELAY_SECONDS, self.scan.INTERVAL_SECONDS = .01, 999
            task = asyncio.create_task(self.scan.run())
            await asyncio.sleep(.2)
            self.r.stop_requested.set()
            await asyncio.wait_for(task, 2)
            store.close()
            import sqlite3, json
            from contextlib import closing
            with closing(sqlite3.connect(Path(temp)/'research.db')) as conn:
                [(key, payload)] = conn.execute("SELECT key,payload FROM candidates").fetchall()
            row = json.loads(payload)
            self.assertTrue(key.startswith('scan@'))
            self.assertEqual((row['source'], row['markets']), ('full_scan', 3))


class DiscoveryTests(unittest.TestCase):
    def test_fresh_scores_put_the_best_measured_markets_first(self):
        tickers = [f'M{i:03}' for i in range(40)]
        # Pool hint prefers M000..; the scan says M030 and M020 earn most, M010 earns 0.
        scores = {'M030': D('0.50'), 'M020': D('0.20'), 'M010': D(0), 'M005': D('0.01')}
        result = CandidateDiscovery().choose(catalog(tickers), now=NOW, budget=10, scores=scores)
        self.assertEqual(result.tickers[:3], ('M030', 'M020', 'M005'))
        # Half the free slots follow the scores; the rest keep the old order after them.
        self.assertEqual(len(result.tickers), 10)
        self.assertIn('M000', result.tickers)

    def test_the_scored_half_stays_watched_across_rotations(self):
        tickers = [f'M{i:03}' for i in range(40)]
        scores = {f'M0{n}': D(n)/100 for n in range(30, 36)}  # six scored markets
        d = CandidateDiscovery()
        first = d.choose(catalog(tickers), now=NOW, budget=10, scores=scores)
        second = d.choose(catalog(tickers), now=NOW, budget=10, scores=scores, subscribed=first.tickers)
        best_five = ('M035', 'M034', 'M033', 'M032', 'M031')
        self.assertEqual(first.tickers[:5], best_five)
        self.assertEqual(second.tickers[:5], best_five)  # Not rotated out by the exploration tail.

    def test_no_scores_keeps_the_existing_pool_hint_order(self):
        tickers = [f'M{i:03}' for i in range(40)]
        old = CandidateDiscovery().choose(catalog(tickers), now=NOW, budget=10)
        new = CandidateDiscovery().choose(catalog(tickers), now=NOW, budget=10, scores=None)
        self.assertEqual(old.tickers, new.tickers)
        self.assertEqual(old.tickers[:2], ('M000', 'M001'))

    def test_owned_markets_stay_first_whatever_the_scores(self):
        tickers = [f'M{i:03}' for i in range(40)]
        result = CandidateDiscovery().choose(catalog(tickers), now=NOW, budget=10,
                                             protected=('M039',), scores={'M001': D(1)})
        self.assertEqual(result.tickers[:2], ('M039', 'M001'))


if __name__ == '__main__':
    unittest.main()
