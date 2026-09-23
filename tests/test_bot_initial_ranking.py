"""Synthetic startup barrier/dispatch tests; no venue, credentials or live DB."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from kalshi_bot.account import normalize_snapshot
from kalshi_bot.dispatch import ENTRY_PAIR, SAFETY_CANCEL
from kalshi_bot.initial_ranking import InitialRankingCheckpoint
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_engine import NOW, program, snapshot
from test_bot_selection import terms
import test_bot_live_runtime as live_fixture


async def noop(*args):
    pass


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.mono = 100.
        self.gate = InitialRankingCheckpoint({'A':'book-0', 'B':'book-1'},
                                             clock=lambda:self.mono)

    def test_not_started_does_not_time_out_from_construction(self):
        self.mono += 1000
        self.assertFalse(self.gate.ready())
        self.assertEqual(self.gate.status()['state'], 'not_started')

    def test_wait_for_both_shards_and_deduplicate_observations(self):
        g = self.gate
        g.start()
        for _ in range(20): g.observe('A')
        self.assertFalse(g.ready())
        self.assertEqual(g.status()['evaluated_markets'], 1)
        g.observe('B')
        self.assertTrue(g.ready())
        self.assertEqual(g.status()['state'], 'coverage_complete')
        self.assertEqual(g.status()['shards']['book-1']['evaluated'], 1)

    def test_exact_timeout_releases_partial_without_fabricating_coverage(self):
        g = self.gate
        g.start()
        g.observe('A')
        self.mono += 119.999
        self.assertFalse(g.ready())
        self.mono = 220.
        self.assertTrue(g.ready())
        status = g.status()
        self.assertEqual(status['state'], 'timeout_partial')
        self.assertEqual(status['missing_samples'], ['B'])
        self.assertFalse(status['grants_order_authority'])
        g.observe('B')
        self.assertEqual(g.status()['missing_markets'], 1)  # frozen release record

    def test_epoch_change_discards_coverage_without_extending_deadline(self):
        g = self.gate
        g.start()
        g.sync((1,1))
        g.observe('A')
        self.mono += 100
        g.sync((1,2))
        g.observe('B')
        self.assertFalse(g.ready())
        self.assertEqual(g.status()['missing_samples'], ['A'])
        self.mono += 20
        self.assertTrue(g.ready())
        self.assertEqual(g.status()['state'], 'timeout_partial')

    def test_release_does_not_rearm_or_restart_timer(self):
        g = self.gate
        g.start()
        g.observe('A'); g.observe('B')
        self.assertTrue(g.ready())
        g.sync((8,8))
        self.mono += 500
        g.start()
        self.assertTrue(g.ready())
        self.assertEqual(g.status()['elapsed_seconds'], 0)

    def test_invalid_limits_scope_clock_and_observation_fail_closed(self):
        for timeout in (0,301,True,1.5):
            with self.assertRaises(InvalidData):
                InitialRankingCheckpoint({'A':'book-0'},clock=lambda:0.,timeout=timeout)
        for scope in ({}, {str(i):'book-0' for i in range(1025)}):
            with self.assertRaises(InvalidData):
                InitialRankingCheckpoint(scope,clock=lambda:0.)
        with self.assertRaises(InvalidData): self.gate.observe('outside')
        self.gate.start()
        self.mono = 99.
        with self.assertRaises(InvalidData): self.gate.ready()
        self.mono = float('nan')
        with self.assertRaises(InvalidData): self.gate.ready()

    def test_full_scope_is_bounded_and_status_samples_small(self):
        g = InitialRankingCheckpoint({str(i):f'book-{i%2}' for i in range(1024)},
                                     clock=lambda:self.mono)
        g.start()
        self.assertEqual(len(g.status()['missing_samples']), 8)
        for i in range(1024): g.observe(str(i))
        self.assertTrue(g.ready())
        self.assertEqual(len(g.evaluated), 1024)


class CombinedRankingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'fixture.db').start()
        self.now, self.mono = NOW, 100.
        self.r = RecoveryRuntime(self.writer,None,None,tickers=('A','C'),subaccount=0,
            history_start=NOW-timedelta(hours=1),now=lambda:self.now,clock=lambda:self.mono,
            evaluate=noop,deadline_handler=noop,lifecycle_handler=noop,broad_discovery=True)
        self.s = self.r.attach_selection(offline_fixture=True)
        self.s.start()
        self.r.account.connect_generation()
        self.r.engine.begin_private_epoch()
        self.window = await self.writer.observe(NOW)
        snap = normalize_snapshot((),(),dict(balance_dollars='500',updated_ts=1),subaccount=0)
        await self.r.account.finish_reconciliation(self.r.account.begin_reconciliation(NOW),snap,NOW)
        self.sequences = {}
        for name in self.r.engine.shards:
            self.r.engine.begin_book_epoch(name)
            self.sequences[name] = 0

    async def asyncTearDown(self):
        self.r.dispatch_supervisor = None
        self.r.engine.stop()
        await self.writer.close()
        self.temp.cleanup()

    async def publish(self, ticker, *, metadata=True, pool=5000000):
        self.s.set_programs(ticker,(program(ticker=ticker,pool_centicents=pool),),
            observed_at=self.now,valid_until=self.now+timedelta(minutes=5))
        if metadata: self.r.management.set_terms(terms(ticker))
        name = self.r.engine.market_shard[ticker]
        self.sequences[name] += 1
        self.r.engine.submit_book(name,snapshot(ticker,self.sequences[name]),
                                 generation=self.r.engine.shards[name].generation)
        while any(self.r.engine.public.values()) or self.r.engine.dirty.pending:
            await self.r.engine.step()

    async def proposal(self):
        return await self.s.propose(window=self.window,free_cash=D(500))

    async def test_later_priority_market_beats_early_fallback_after_combined_coverage(self):
        self.assertEqual(len(self.r.engine.shards), 2)
        await self.publish('A',pool=3000000)
        first = await self.proposal()
        self.assertEqual(first.blockers, ('initial_ranking_pending',))
        self.assertFalse(first.additions)
        await self.publish('C',pool=5000000)
        result = await self.proposal()
        self.assertEqual([row.ticker for row in result.additions], ['C','A'])
        self.assertGreaterEqual(result.additions[0].gross_remaining_usd,D(2))
        self.assertTrue(D(1) <= result.additions[1].gross_remaining_usd < D(2))
        self.assertEqual(self.s.status()['initial_ranking']['state'], 'coverage_complete')
        self.assertEqual(self.s.status()['last_proposal']['priority_additions'],1)
        self.assertFalse(await self.writer.mutations())

    async def test_books_alone_do_not_complete_metadata_coverage(self):
        await self.publish('A')
        await self.publish('C',metadata=False)
        self.assertIn('initial_ranking_pending',(await self.proposal()).blockers)
        self.assertEqual(self.s.initial_ranking.status()['evaluated_markets'],1)
        self.r.management.set_terms(terms('C'))
        await self.r.engine.step()
        self.assertEqual(len((await self.proposal()).additions),2)

    async def test_rejected_economic_market_counts_as_evaluated_not_eligible(self):
        await self.publish('A')
        await self.publish('C',pool=1)
        self.assertEqual([row.ticker for row in (await self.proposal()).additions],['A'])
        self.assertEqual(self.s.initial_ranking.status()['state'],'coverage_complete')

    async def test_timeout_uses_only_fresh_candidates_and_leaves_missing_explicit(self):
        await self.publish('A')
        self.mono += 120
        self.now += timedelta(seconds=120)
        # Old evidence cannot become eligible simply because the timer elapsed.
        result = await self.proposal()
        self.assertFalse(result.additions)
        self.assertEqual(self.s.initial_ranking.status()['state'],'timeout_partial')
        snap = normalize_snapshot((),(),dict(balance_dollars='500',updated_ts=1),subaccount=0)
        self.window = await self.writer.observe(self.now)
        await self.r.account.finish_reconciliation(self.r.account.begin_reconciliation(self.now),snap,self.now)
        await self.publish('A')
        result = await self.proposal()
        self.assertEqual([row.ticker for row in result.additions],['A'])
        self.assertEqual(self.s.initial_ranking.status()['missing_samples'],['C'])

    async def test_reconnect_before_release_discards_old_coverage(self):
        await self.publish('A')
        name = self.r.engine.market_shard['A']
        self.r.engine.begin_book_epoch(name)
        self.sequences[name] = 0
        await self.publish('C')
        self.assertIn('initial_ranking_pending',(await self.proposal()).blockers)
        await self.publish('A')
        self.assertEqual(len((await self.proposal()).additions),2)

    async def test_missing_catalog_is_not_a_completed_no_reward_check(self):
        from types import SimpleNamespace as NS
        self.r.incentives = NS(current=lambda:None)
        self.s.refresh('A')
        self.s.refresh('C')
        self.assertEqual(self.s.initial_ranking.status()['evaluated_markets'],0)
        catalog = NS(observations={},generation=1,observed_mono=100.)
        self.r.incentives.current = lambda:catalog
        self.s.refresh('A')
        self.s.refresh('C')
        self.assertTrue(self.s.initial_ranking_ready())
        self.assertFalse((await self.proposal()).additions)

    async def test_metadata_epoch_change_requires_new_coverage(self):
        from types import SimpleNamespace as NS
        self.r.market_inputs = NS(generation=1)
        await self.publish('A')
        self.r.market_inputs.generation = 2
        await self.publish('C')
        self.assertIn('initial_ranking_pending',(await self.proposal()).blockers)
        await self.publish('A')
        self.assertEqual(len((await self.proposal()).additions),2)

    async def test_wait_keeps_entry_dirty_and_does_not_await_a_feed(self):
        await self.publish('A')
        self.r._entry_dirty = True
        self.r.dispatch_supervisor = AsyncMock()
        await self.r._ranked_entry_turn()
        self.assertTrue(self.r._entry_dirty)
        self.r.dispatch_supervisor.request.assert_not_called()
        self.assertFalse(self.r.stop_requested.is_set())

    async def test_inventory_dispatch_is_independent_of_initial_checkpoint(self):
        from types import SimpleNamespace as NS
        calls = []
        self.r.dispatch_supervisor = NS(request=lambda *args:calls.append(args))
        plan = NS(exit=NS(mode='cancel_before_ioc'), passive=NS(cancel_ids=('owned',)))
        with patch.object(self.r.management,'current',return_value=plan):
            self.r._request_inventory_dispatch('A')
        self.assertEqual(calls,[('A',SAFETY_CANCEL)])
        self.assertFalse(self.s.initial_ranking_ready())


class DispatchCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_entry_dispatch_cannot_bypass_checkpoint(self):
        f = live_fixture.LiveEntryTests()
        await f.asyncSetUp()
        try:
            f.runtime.market_inputs.generation = 1
            gate = InitialRankingCheckpoint({'A':'book-0','B':'book-1'},clock=lambda:f.f.tick)
            f.selection.initial_ranking = gate
            f.selection.start()
            f.dispatcher.submit('A',ENTRY_PAIR)
            result = await f.dispatcher.run_one()
            self.assertEqual(result.state,'BLOCKED')
            self.assertFalse(f.calls)
            self.assertFalse(await f.f.writer.mutations())
            gate.observe('B')
            f.dispatcher.submit('A',ENTRY_PAIR)
            result = await f.dispatcher.run_one()
            self.assertEqual(result.state,'ACK',result.blockers)
            self.assertEqual(len(f.calls),1)
        finally:
            await f.asyncTearDown()
