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


def evidence(name, **values):
    print(json.dumps(dict(check=name, **values), sort_keys=True), flush=True)


class BreadthDiagnostics(unittest.IsolatedAsyncioTestCase):
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
