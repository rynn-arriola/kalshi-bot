"""Synthetic startup barrier/dispatch tests; no venue, credentials or live DB."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from kalshi_bot.account import normalize_snapshot
from kalshi_bot.dispatch import ENTRY_PAIR, SAFETY_CANCEL
from kalshi_bot.initial_ranking import InitialRankingCheckpoint
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.selection_runtime import PriorityCandidateHint
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

    def test_exact_timeout_stays_closed_without_fabricating_coverage(self):
        g = self.gate
        g.start()
        g.observe('A')
        self.mono += 119.999
        self.assertFalse(g.ready())
        self.mono = 220.
        self.assertFalse(g.ready())
        status = g.status()
        self.assertEqual(status['state'], 'timeout_incomplete')
        self.assertTrue(status['timed_out'])
        self.assertEqual(status['missing_samples'], ['B'])
        self.assertFalse(status['grants_order_authority'])
        g.observe('B')
        self.assertTrue(g.ready())
        self.assertEqual(g.status()['state'], 'coverage_complete')

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
        self.assertFalse(g.ready())
        self.assertEqual(g.status()['state'], 'timeout_incomplete')
        g.observe('A')
        self.assertTrue(g.ready())
        self.assertEqual(g.status()['state'], 'coverage_complete')

    def test_current_priority_capacity_can_release_before_full_coverage(self):
        self.gate.start()
        self.gate.observe('A')
        self.assertTrue(self.gate.release_for_priority_capacity(candidates=15,required=15))
        status = self.gate.status()
        self.assertEqual(status['state'], 'priority_capacity_met')
        self.assertEqual(status['release_reason'], 'priority_capacity_met')
        self.assertEqual(status['missing_samples'], ['B'])
        self.gate.observe('B')
        self.assertTrue(self.gate.ready())
        self.assertEqual(self.gate.status()['state'], 'coverage_complete')
        self.assertEqual(self.gate.status()['release_reason'], 'priority_capacity_met')

    def test_partial_priority_capacity_does_not_release(self):
        self.gate.start()
        self.assertFalse(self.gate.release_for_priority_capacity(candidates=14,required=15))
        self.assertEqual(self.gate.status()['state'], 'waiting')

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

    async def test_identical_catalog_refresh_preserves_initial_coverage(self):
        catalog = NS(content_digest='a'*64,market_digests={'A':'a','C':'c'})
        self.r.incentives = NS(current=lambda: catalog)
        self.s._initial_progress('A')
        catalog = NS(content_digest='a'*64,market_digests={'A':'a','C':'c'})
        self.s._initial_progress()
        self.assertEqual(self.s.initial_ranking.status()['evaluated_markets'], 1)
        self.assertEqual(self.s.initial_ranking.status()['source_resets'], 0)
        catalog = NS(content_digest='b'*64,market_digests={'A':'a','C':'changed'})
        self.s._initial_progress()
        self.assertEqual(self.s.initial_ranking.status()['source_resets'], 1)
        self.assertEqual(self.s.initial_ranking.status()['evaluated_markets'], 1)
        catalog = NS(content_digest='c'*64,market_digests={'A':'changed','C':'changed'})
        self.s._initial_progress()
        self.assertEqual(self.s.initial_ranking.status()['source_resets'], 2)
        self.assertEqual(self.s.initial_ranking.status()['evaluated_markets'], 0)
        self.r.incentives = None

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
        priority = result.additions[0]
        self.assertIsNotNone(self.s.capture_dispatch_proof(
            priority.ticker,priority.program_id,priority.valid_until))
        self.assertFalse(self.s.status()['dispatch_selection_evidence'])
        self.assertFalse(await self.writer.mutations())

    async def test_current_priority_candidate_fills_available_slot_before_full_coverage(self):
        self.window = replace(self.window,cap=2)
        await self.publish('A',pool=5000000)
        result = await self.proposal()
        self.assertEqual([row.ticker for row in result.additions],['A'])
        self.assertEqual(self.s.initial_ranking.status()['state'],'priority_capacity_met')
        self.assertEqual(self.s.initial_ranking.status()['missing_samples'],['C'])
        await self.publish('C',pool=1)
        self.assertTrue(self.s.initial_ranking_ready())
        self.assertEqual(self.s.initial_ranking.status()['state'],'coverage_complete')
        self.assertEqual(self.s.initial_ranking.status()['release_reason'],'priority_capacity_met')

    async def test_pending_gate_revalidates_remembered_priority_candidates(self):
        await self.publish('A',pool=3000000)
        self.s._priority_hints['C'] = PriorityCandidateHint(
            'C','PROGRAM',self.now,self.now+timedelta(hours=1),D(3),())
        result = await self.proposal()
        self.assertEqual(result.blockers,('initial_ranking_pending',))
        self.assertEqual(self.s.status()['priority_revalidation_pending'],1)
        self.assertTrue(self.r._metadata_priority('C'))
        self.assertFalse(await self.writer.mutations())

    async def test_invalidated_priority_is_revalidated_before_fallback(self):
        await self.publish('A',pool=3000000)
        await self.publish('C',pool=5000000)
        self.assertEqual([row.ticker for row in (await self.proposal()).additions],['C','A'])
        # Account-wide revocation removes every current selector row. A fallback
        # may recover first, but the remembered priority candidate must not be lost.
        self.s.invalidate('A')
        self.s.invalidate('C')
        await self.publish('A',pool=3000000)
        result = await self.proposal()
        self.assertFalse(result.additions)
        self.assertIn('priority_revalidation_pending',result.blockers)
        status = self.s.status()
        self.assertEqual(status['priority_candidate_memory'],1)
        self.assertEqual(status['priority_revalidation_samples'],['C'])
        self.assertTrue(self.r._metadata_priority('C'))
        self.assertFalse(self.r._metadata_priority('A'))
        self.assertFalse(await self.writer.mutations())
        await self.publish('C',pool=5000000)
        self.assertEqual([row.ticker for row in (await self.proposal()).additions],['C','A'])

    async def test_fresh_lower_reward_retires_priority_hint_and_allows_fallback(self):
        await self.publish('A',pool=3000000)
        await self.publish('C',pool=5000000)
        self.s.invalidate('C')
        self.assertIn('priority_revalidation_pending',(await self.proposal()).blockers)
        await self.publish('C',pool=1)
        result = await self.proposal()
        self.assertEqual([row.ticker for row in result.additions],['A'])
        self.assertEqual(self.s.status()['priority_candidate_memory'],0)
        self.assertEqual(self.s.status()['last_proposal']['fallback_reason'],
                         'priority_candidates_resolved')

    async def test_fresh_inactive_market_retires_hint_and_allows_fallback(self):
        from types import SimpleNamespace as NS
        await self.publish('A',pool=3000000)
        await self.publish('C',pool=5000000)
        self.r.management.set_terms(replace(terms('C'),active=False))
        await self.r.management.refresh('C')
        self.s.candidate_inputs = NS(blockers=lambda ticker, now:
            ('market_inactive',) if ticker == 'C' else (), status=lambda:{})
        self.s.refresh('C')
        result = await self.proposal()
        self.assertEqual([row.ticker for row in result.additions],['A'])
        self.assertNotIn('C',self.s._priority_hints)
        self.assertNotIn('priority_revalidation_pending',result.blockers)

    async def test_retry_exhaustion_keeps_priority_hint_pending(self):
        from types import SimpleNamespace as NS
        await self.publish('A',pool=3000000)
        await self.publish('C',pool=5000000)
        self.s.candidate_inputs = NS(blockers=lambda ticker, now:
            ('metadata_retry_exhausted',) if ticker == 'C' else (), status=lambda:{})
        self.s.refresh('C')
        result = await self.proposal()
        self.assertFalse(result.additions)
        self.assertIn('C',self.s._priority_hints)
        self.assertIn('priority_revalidation_pending',result.blockers)

    async def test_actual_entry_turn_can_release_current_priority_capacity(self):
        from types import SimpleNamespace as NS
        self.window = replace(self.window,cap=2)
        await self.publish('A',pool=5000000)
        calls = []
        dispatcher = NS(status=lambda:NS(active=None,queued=(),stopping=False,failed=False))
        self.r.dispatch_supervisor = NS(dispatcher=dispatcher,
                                        request=lambda *args:calls.append(args))
        self.r.accounting_result = NS(released=True,window=self.window)
        self.r._entry_dirty = True
        with patch.object(RecoveryRuntime,'entry_allowed',property(lambda _:True)):
            await self.r._ranked_entry_turn()
        self.assertEqual(calls,[('A',ENTRY_PAIR)])
        self.assertEqual(self.s.initial_ranking.status()['state'],'priority_capacity_met')

    async def test_priority_refresh_uses_bounded_batches_and_advances(self):
        shard = self.r.engine.market_shard['A']
        tickers = [f'P{i:02d}' for i in range(40)]
        for ticker in tickers:
            self.r.engine.market_shard[ticker] = shard
            self.s._priority_hints[ticker] = PriorityCandidateHint(
                ticker, 'PROGRAM', self.now, self.now+timedelta(hours=1), D(3), ())
        self.assertTrue(self.s._request_priority_revalidation(
            now=self.now,available_pairs=15,protected=()))
        first = set(self.s._priority_refresh)
        self.assertEqual(len(first),30)
        stalled = min(first)
        for ticker in first-{stalled}:
            self.s._forget_priority(ticker)
        self.assertTrue(self.s._request_priority_revalidation(
            now=self.now,available_pairs=15,protected=()))
        self.assertEqual(set(self.s._priority_refresh),{stalled}|(set(tickers)-first))

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

    async def test_timeout_remains_closed_until_missing_market_is_evaluated(self):
        await self.publish('A')
        self.mono += 120
        self.now += timedelta(seconds=120)
        # Old evidence cannot become eligible simply because the timer elapsed.
        result = await self.proposal()
        self.assertFalse(result.additions)
        self.assertEqual(self.s.initial_ranking.status()['state'],'timeout_incomplete')
        snap = normalize_snapshot((),(),dict(balance_dollars='500',updated_ts=1),subaccount=0)
        self.window = await self.writer.observe(self.now)
        await self.r.account.finish_reconciliation(self.r.account.begin_reconciliation(self.now),snap,self.now)
        await self.publish('A')
        result = await self.proposal()
        self.assertFalse(result.additions)
        self.assertIn('initial_ranking_pending',result.blockers)
        self.assertEqual(self.s.initial_ranking.status()['missing_samples'],['C'])
        await self.publish('C')
        self.assertEqual([row.ticker for row in (await self.proposal()).additions],['A','C'])

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
        catalog = NS(observations={},generation=1,observed_mono=100.,
                     content_digest='0'*64)
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

    async def test_wait_consumes_dirty_until_a_new_source_event(self):
        from types import SimpleNamespace as NS
        await self.publish('A')
        self.r._entry_dirty = True
        calls = []
        dispatcher = NS(status=lambda:NS(active=None,queued=(),stopping=False,failed=False))
        self.r.dispatch_supervisor = NS(dispatcher=dispatcher,
                                        request=lambda *args:calls.append(args))
        self.r.accounting_result = NS(released=True,window=self.window)
        with patch.object(RecoveryRuntime,'entry_allowed',property(lambda _:True)):
            await self.r._ranked_entry_turn()
        self.assertFalse(self.r._entry_dirty)
        self.assertFalse(calls)
        self.assertFalse(self.r.stop_requested.is_set())

    async def test_unrewarded_evaluation_rearms_entry_turn_for_coverage(self):
        await self.publish('A')
        self.r._entry_dirty = False
        self.r.dispatch_supervisor = AsyncMock()
        await self.publish('C',pool=1)
        self.assertTrue(self.r._entry_dirty)
        self.assertTrue(self.s.initial_ranking_ready())

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
