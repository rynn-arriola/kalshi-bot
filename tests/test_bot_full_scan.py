"""D-158: score every rewarded market; discovery watches the best-scoring ones."""
import asyncio
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace as NS
import json
import time
import unittest
from unittest.mock import patch

from kalshi_bot.config import BotConfig, activate
from kalshi_bot.discovery_candidates import CandidateDiscovery
from kalshi_bot.full_scan import (FullMarketScan, LAUNCH_FRESH_SECONDS, load_scan,
    parse_book, save_scan, score_markets)
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


class RemainingTests(unittest.TestCase):
    def setUp(self):
        import kalshi_bot.config as bot_config
        self.addCleanup(setattr, bot_config, '_ACTIVE', bot_config._ACTIVE)
        activate(BotConfig.load(ROOT/'config'/'bot.json'))

    def test_a_long_program_outranks_a_short_one_with_a_higher_hourly_rate(self):
        """Finding (2026-09-27 scan): hour-long matches show high $/hour but little left."""
        from kalshi_bot.ranking import RankingBoard
        short = program(ticker='S', program_id='p-S', start=NOW-timedelta(minutes=50),
                        end=NOW+timedelta(minutes=10), pool_centicents=800000)
        long = program(ticker='L', program_id='p-L', start=NOW-timedelta(days=1),
                       end=NOW+timedelta(days=3), pool_centicents=20000000)
        books = {t: parse_book(t, levels()) for t in ('S', 'L')}
        scores = score_markets({'S': (short,), 'L': (long,)}, {'S': BANDS, 'L': BANDS}, books, NOW)
        board = RankingBoard(4)
        for t, p in (('S', short), ('L', long)):
            board.update(books[t], (p,), BANDS, now=NOW, valid_until=NOW+timedelta(minutes=5), market_open=True)
        hourly = {t: board.markets[t][0].gross_hourly_usd for t in ('S', 'L')}
        self.assertGreater(hourly['S'], hourly['L'])  # The short one looks juicier per hour...
        self.assertGreater(scores['L'], scores['S'])  # ...but the long one has more left to earn.
        self.assertEqual(scores['L'], board.markets['L'][0].gross_remaining_usd)

    def test_a_blocked_row_scores_zero(self):
        thin = parse_book('T', dict(yes_dollars=[['0.50', '100']], no_dollars=[['0.40', '100']]))
        scores = score_markets({'T': (program(ticker='T', program_id='p-T'),)}, {'T': BANDS}, {'T': thin}, NOW)
        self.assertEqual(scores, {'T': D(0)})


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

    async def test_a_batch_overlapping_a_quota_refresh_is_retried(self):
        from kalshi_bot.quota import QuotaUnavailable
        real = self.r.reads.read
        refreshes = ['orderbooks']
        async def read(name, **params):
            if name in refreshes:
                refreshes.remove(name)
                raise QuotaUnavailable('quota_revision_changed')
            return await real(name, **params)
        self.r.reads = NS(read=read)
        self.scan.READ_PAUSE_SECONDS = 0
        scores = await self.scan.scan_once()
        self.assertEqual(set(scores), {'A', 'B'})

    async def test_a_persistent_quota_problem_fails_the_pass_after_bounded_tries(self):
        from kalshi_bot.quota import QuotaUnavailable
        calls = []
        async def read(name, **params):
            calls.append(name)
            raise QuotaUnavailable('quota_revision_changed')
        self.r.reads = NS(read=read)
        self.scan.READ_PAUSE_SECONDS = 0
        with self.assertRaises(QuotaUnavailable):
            await self.scan.scan_once()
        self.assertEqual(len(calls), self.scan.READ_ATTEMPTS)

    async def test_a_failed_pass_retries_soon_and_a_good_one_waits_the_interval(self):
        runs = []
        async def once():
            runs.append(len(runs))
            if len(runs) == 1:
                raise InvalidData('first pass fails')
            return {}
        self.scan.scan_once = once
        self.scan.FIRST_DELAY_SECONDS, self.scan.RETRY_SECONDS, self.scan.INTERVAL_SECONDS = .01, .01, 999
        task = asyncio.create_task(self.scan.run())
        await asyncio.sleep(.2)
        self.r.stop_requested.set()
        await asyncio.wait_for(task, 2)
        self.assertEqual(runs, [0, 1])  # Retried quickly once, then waits the long interval.

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


class SavedScanTests(unittest.TestCase):
    """D-159: each pass is saved beside the ledger; the next launch reads it."""
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'market_scan.json'

    def test_a_saved_pass_loads_back_with_only_scoring_markets(self):
        save_scan(self.path, NOW, {'A': D('2.5'), 'B': D(0), 'C': D('0.1')})
        observed, scores = load_scan(self.path, NOW+timedelta(hours=1))
        self.assertEqual(observed, NOW)
        self.assertEqual(scores, {'A': D('2.5'), 'C': D('0.1')})
        self.assertEqual(set(json.loads(self.path.read_text(encoding='utf-8'))['scores']), {'A', 'C'})
        self.assertFalse(self.path.with_suffix('.tmp').exists())

    def test_missing_stale_future_or_corrupt_files_fall_back(self):
        self.assertIsNone(load_scan(self.path, NOW))
        save_scan(self.path, NOW, {'A': D(1)})
        self.assertIsNone(load_scan(self.path, NOW+timedelta(seconds=LAUNCH_FRESH_SECONDS+1)))
        self.assertIsNone(load_scan(self.path, NOW-timedelta(minutes=5)))
        self.assertIsNotNone(load_scan(self.path, NOW+timedelta(seconds=LAUNCH_FRESH_SECONDS)))
        for text in ('{', '[]', '{"observed_at": "x", "scores": {}}',
                     json.dumps(dict(observed_at=NOW.isoformat(), scores=['A']))
                     , json.dumps(dict(observed_at=NOW.isoformat(), scores={'A': 'NaN'})),
                     json.dumps(dict(observed_at=NOW.isoformat(), scores={'A': 'Infinity'})),
                     json.dumps(dict(observed_at=NOW.isoformat(), scores={'A': 'bad'})),
                     json.dumps(dict(observed_at=NOW.isoformat(), scores={'A': '0'}))):
            self.path.write_text(text, encoding='utf-8')
            self.assertIsNone(load_scan(self.path, NOW), text)

    def test_an_oversized_file_is_ignored(self):
        save_scan(self.path, NOW, {'A': D(1)})
        with patch('kalshi_bot.full_scan.SAVED_BYTES_LIMIT', 10):
            self.assertIsNone(load_scan(self.path, NOW))


class SavedPassTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ScanTests.asyncSetUp

    async def run_one_pass(self):
        self.scan.FIRST_DELAY_SECONDS, self.scan.INTERVAL_SECONDS = .01, 999
        task = asyncio.create_task(self.scan.run())
        await asyncio.sleep(.2)
        self.r.stop_requested.set()
        await asyncio.wait_for(task, 2)

    async def test_each_good_pass_is_saved_for_the_next_launch(self):
        with TemporaryDirectory() as temp:
            self.scan.state_path = Path(temp)/'market_scan.json'
            await self.run_one_pass()
            observed, scores = load_scan(self.scan.state_path, NOW)
        expected = {t: v for t, v in self.scan.scores.items() if v > 0}
        self.assertTrue(expected)
        self.assertEqual((observed, scores), (NOW, expected))
        self.assertEqual((self.scan.failures, self.scan.save_failures), (0, 0))

    async def test_a_failed_save_is_counted_but_the_pass_still_counts(self):
        with TemporaryDirectory() as temp:
            self.scan.state_path = Path(temp)/'missing'/'market_scan.json'
            await self.run_one_pass()
        self.assertEqual((self.scan.runs, self.scan.failures), (1, 0))
        self.assertEqual(self.scan.status()['save_failures'], 1)
        self.assertIsNotNone(self.scan.fresh_scores())


class LaunchWiringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inputs = Path(self.temp.name)/'live-inputs.json'
        self.inputs.write_text(json.dumps(dict(fee_profile=dict(balance_quantum='.0001',
            review_reference='synthetic-direct', valid_until='2099-01-01T00:00:00Z'))),
            encoding='utf-8')
        self.scan_path = Path(self.temp.name)/'market_scan.json'
        self.projects_path = Path(self.temp.name)/'projects.json'

    async def prepared_with(self, now):
        from kalshi_bot import live
        seen = {}
        class Stop(Exception):
            pass
        async def prepare(reads, **params):
            seen.update(params)
            raise Stop
        with patch.object(live, 'prepare_candidates', prepare):
            with self.assertRaises(Stop):
                await live.refresh_candidate_inputs(self.inputs, now, None, scan_path=self.scan_path,
                                                    projects_path=self.projects_path)
        self.seen = seen
        return seen['scan_scores']

    async def test_launch_passes_a_fresh_saved_scan_and_falls_back_without_one(self):
        self.assertIsNone(await self.prepared_with(NOW))
        save_scan(self.scan_path, NOW, {'A': D(3)})
        self.assertEqual(await self.prepared_with(NOW+timedelta(minutes=40)), {'A': D(3)})
        self.assertIsNone(await self.prepared_with(NOW+timedelta(hours=4)))

    async def test_launch_keeps_saved_project_contracts_in_scope(self):
        """D-161: the saved project list is pinned into the launch scope."""
        await self.prepared_with(NOW)
        self.assertEqual(self.seen['pinned'], ())
        self.projects_path.write_text(json.dumps(dict(projects={
            'p1': dict(ticker='KXB', until=NOW.isoformat(), added_at=NOW.isoformat()),
            'p2': dict(ticker='KXA', until=NOW.isoformat(), added_at=NOW.isoformat())}, closed=[])),
            encoding='utf-8')
        await self.prepared_with(NOW)
        self.assertEqual(self.seen['pinned'], ('KXA', 'KXB'))

    def test_live_saves_the_scan_beside_the_ledger(self):
        source = (ROOT/'src'/'kalshi_bot'/'live.py').read_text(encoding='utf-8')
        self.assertIn("runtime.full_scan.state_path = Path(writer.path).with_name('market_scan.json')", source)
        self.assertIn("DATA/'market_scan.json'", source)
