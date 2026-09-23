"""Characterize current breadth bottlenecks, not a production readiness gate.

Read-only source inspection and synthetic fixtures; no venue or live-ledger I/O.
Expected limitations must be revised when repaired, not preserved as policy.
Run explicitly: python -B scripts/diagnose_selection_breadth.py
"""
import ast
import asyncio
from datetime import timedelta
from decimal import Decimal
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests'))
import test_bot_selection as selection_fixture
import test_bot_admission as admission_fixture
import test_bot_incentive_discovery as incentive_fixture
from kalshi_bot import live
from kalshi_bot.writer import LedgerWriter
from kalshi_bot.discovery_candidates import CandidateDiscovery
from kalshi_bot.incentive_discovery import IncentiveCatalog
from kalshi_bot.selection_runtime import ProgramObservation
from kalshi_bot.admission import MarketAdmission


def evidence(name, **values):
    print(json.dumps(dict(check=name, **values), sort_keys=True), flush=True)


class BreadthDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_cursor_can_skip_candidates_after_partial_admission(self):
        """Characterization, NOT desired behavior: remove after repairing coverage.

        Real discovery and admission selection arithmetic; immediate successful
        synthetic joins replace account/metadata/transport checks. Frozen inputs
        isolate coverage from freshness, venue activity and economic filtering.
        """
        from test_bot_discovery_candidates import catalog, NOW
        data = catalog(1024)
        discovery = CandidateDiscovery()
        tickers = sorted(data.observations)
        protected = tuple(tickers[:14])
        engine = SimpleNamespace(
            shards={name: SimpleNamespace(tickers=frozenset(tickers[start:start+64]))
                    for name, start in (('b0', 0), ('b1', 64))},
            market_shard={t: 'b'+str(i//64) for i, t in enumerate(tickers[:128])})

        async def choose():
            return discovery.choose(data, now=NOW, budget=128, protected=protected)

        runtime = SimpleNamespace(engine=engine,
            selection=SimpleNamespace(discovery_candidates=choose),
            writer=SimpleNamespace(market_capacity=128),
            reader_states={'b0': 'subscribed', 'b1': 'subscribed'},
            reader_failures={'b0': 0, 'b1': 0}, attempt_limit=3,
            metadata_scheduler=None)
        admission = object.__new__(MarketAdmission)
        admission.runtime = runtime
        admission.cursor = admission.completed = admission.deferred = 0
        admission.pending = None
        admission._ready = lambda: True

        async def removable(change):
            return True

        admission.removable = removable
        seen = set(engine.market_shard)

        def joined():
            change = admission.pending
            self.assertLessEqual(len(set(change.after)-change.before), 16)
            engine.shards[change.name].tickers = frozenset(change.after)
            engine.market_shard = {t: n for n, shard in engine.shards.items()
                                   for t in shard.tickers}
            self.assertTrue(set(protected) <= set(engine.market_shard))
            seen.update(engine.market_shard)
            change.result.set_result(True)

        admission.signals = {n: SimpleNamespace(set=joined) for n in engine.shards}
        states = {}
        for cycle in range(1001):
            state = (discovery.cursor, admission.cursor,
                     tuple((n, tuple(sorted(s.tickers))) for n, s in engine.shards.items()))
            if state in states:
                break
            states[state] = cycle
            await admission._cycle()
        else:
            self.fail('expected a repeated frozen-input exploration state')
        missing = set(tickers)-seen
        self.assertEqual(len(missing), 332)
        self.assertEqual(len(seen), 692)
        evidence('partial_admission_coverage_cycle', synthetic_candidates=1024,
            protected_markets=14, distinct_admitted=len(seen), never_admitted=len(missing),
            repeated_state_at_cycle=cycle, first_seen_at_cycle=states[state],
            venue_requests=0, production_cause_proven=False)

    async def test_catalog_timeouts_remove_selection_source_and_exhaust(self):
        f = incentive_fixture.DiscoveryTests()
        await f.asyncSetUp()
        try:
            await f.refresh()
            await f.r.engine.step()
            self.assertEqual(len((await f.s.propose(
                window=f.f.w, free_cash=500)).additions), 1)
            async def timed_out(*args, **kwargs):
                raise TimeoutError('synthetic catalog deadline')
            f.advance(300)
            with patch.object(f.reads, 'collect', side_effect=timed_out):
                for attempt in range(1, 4):
                    await f.refresh()
                    self.assertEqual(f.d.failures, attempt)
                    self.assertIsNone(f.d.current())
                    self.assertFalse(f.s.current('A'))
                    f.advance(2**(attempt-1))
            self.assertTrue(f.d.exhausted)
            started = f.d.started
            f.d.step()
            self.assertIsNone(f.d.active)
            self.assertEqual(f.d.started, started)
            self.assertFalse(await f.r.writer.mutations())
            evidence('catalog_timeout', injected_timeouts=3,
                current_catalog=False, exhausted=True, further_automatic_retry=False,
                venue_requests=0)
        finally:
            await f.asyncTearDown()

    async def test_quiet_book_after_delayed_metadata_blocks_otherwise_eligible_pair(self):
        f = selection_fixture.RuntimeSelectionTests()
        await f.asyncSetUp()
        try:
            initial = await f.s.propose(window=f.w, free_cash=Decimal(500))
            self.assertEqual(len(initial.additions), 1)
            # Keep account, risk, reward and metadata fresh; age ONLY the book.
            f.now += timedelta(seconds=6)
            f.mono += 6
            f.w = await f.writer.observe(f.now)
            snap = selection_fixture.normalize_snapshot((), (),
                dict(balance_dollars='500', updated_ts=1), subaccount=0)
            await f.r.account.finish_reconciliation(
                f.r.account.begin_reconciliation(f.now), snap, f.now)
            f.r.management.set_terms(selection_fixture.terms(
                observed_at=f.now, valid_until=f.now+timedelta(seconds=60)))
            f.publish()
            await f.r.engine.step()
            quiet = await f.s.propose(window=f.w, free_cash=Decimal(500))
            self.assertIsNotNone(f.r.account.current_report(f.now))
            self.assertIsNone(f.r.management._book('A')[1])
            self.assertFalse(quiet.additions)
            self.assertFalse(quiet.blockers)
            await f.book_event()  # Synthetic fresh snapshot, unchanged prices/depth.
            restored = await f.s.propose(window=f.w, free_cash=Decimal(500))
            self.assertEqual(len(restored.additions), 1)
            self.assertFalse(await f.writer.mutations())
            evidence('quiet_book', fresh_additions=len(initial.additions),
                same_book_age_6s_additions=len(quiet.additions),
                refreshed_same_book_additions=len(restored.additions),
                exclusions=quiet.exclusions, venue_requests=0)
        finally:
            await f.asyncTearDown()

    async def test_actual_admission_adds_at_most_sixteen_per_catalog_interval(self):
        f = admission_fixture.AdmissionTests()
        await f.asyncSetUp()
        try:
            await f.prepare(tuple(f'M{i:03d}' for i in range(64)))
            self.assertTrue(await f.cycle())
            self.assertEqual(len(f.r.engine.market_shard), 16)
            self.assertEqual(f.a.interval, 300)
            # Exercise the real run loop's next-at assignment without waiting 5m.
            async def accepted():
                f.a.state = 'awaiting_snapshots'
                f.a.stopping = True
                f.a.wake.set()
                return True
            with patch.object(f.a, 'cycle', side_effect=accepted):
                await asyncio.wait_for(f.a.run(), 1)
            self.assertEqual(f.a.next_at-f.r.clock(), 300)
            evidence('admission_cadence', admitted_per_cycle=16,
                next_successful_cycle_seconds=300, catalog_markets=64)
        finally:
            await f.asyncTearDown()

    async def test_live_constructor_and_catalog_working_set(self):
        tree = ast.parse(inspect.getsource(live.run))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'LedgerWriter']
        self.assertEqual(len(calls), 1)
        self.assertNotIn('market_capacity', {k.arg for k in calls[0].keywords})
        capacity = inspect.signature(LedgerWriter).parameters['market_capacity'].default
        self.assertEqual(capacity, 128)
        now = selection_fixture.NOW
        observations = {f'M{i:04d}': ProgramObservation((selection_fixture.program(
            ticker=f'M{i:04d}', program_id=f'p{i}', pool_centicents=5000000),),
            now, now+timedelta(minutes=10)) for i in range(1024)}
        catalog = IncentiveCatalog(1, observations, frozenset(), now,
            now+timedelta(minutes=10), 0, 600, 11, 1024, 0)
        slate = CandidateDiscovery().choose(catalog, now=now, budget=capacity)
        self.assertEqual(len(slate.tickers), 128)
        self.assertEqual(slate.deferred, 896)
        evidence('working_set', reviewed_synthetic_markets=1024,
            production_capacity=capacity, discovery_selected=len(slate.tickers),
            deferred=slate.deferred)

    async def test_ranking_can_select_thirty_orders_with_sufficient_fresh_candidates(self):
        f = selection_fixture.SelectionTests()
        f.setUp()
        for i in range(40):
            f.add(f'M{i:03d}')
        result = f.choose()
        self.assertEqual(len(result.additions), 15)
        self.assertEqual(sum(len(r.quotes) for r in result.additions), 30)
        evidence('ranking_capacity', eligible_fixture_markets=40,
            selected_markets=len(result.additions), selected_orders=30,
            estimated_capital=str(result.estimated_capital))


if __name__ == '__main__':
    unittest.main(verbosity=2)
