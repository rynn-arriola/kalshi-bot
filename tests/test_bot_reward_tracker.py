"""Exact synthetic estimates and explicit fixture proofs; no venue/account I/O."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D, localcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from kalshi_bot.reward_tracker import RewardTracker
from kalshi_bot.reward_checkpoint import RewardCheckpoint
from kalshi_bot.quoting import Quote, snapshot_score
from kalshi_bot.values import InvalidData
from test_bot_engine import NOW, BANDS, book, program
import test_bot_selection as runtime_fixtures


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.t = RewardTracker(scope='fixture-account-0')
        self.p = program(pool_centicents=72000000)  # $1/s total pool over two hours.

    def sample(self, offset, rate='0.25', **changes):
        args = dict(at=NOW+timedelta(seconds=offset),valid_until=NOW+timedelta(seconds=offset+5),
            rate=None if rate is None else D(rate),continuity=('epoch',1),qualified=rate not in (None,'0'),
            reason='observed_orders')
        args.update(changes)
        self.t.record(self.p,**args)

    def report(self, offset=0, **changes):
        args = dict(now=NOW+timedelta(seconds=offset),exit_at=NOW+timedelta(seconds=30))
        args.update(changes)
        return self.t.progress('P',**args)

    def test_four_seconds_not_four_book_messages_reach_estimated_dollar(self):
        self.sample(0)
        for _ in range(10): self.sample(0)
        self.assertEqual(self.report().sampled_gross_usd, 0)
        self.sample(4)
        r = self.report(4)
        self.assertEqual((r.sampled_gross_usd,r.qualifying_seconds), (D(1),D(4)))
        self.assertEqual(r.state,'ESTIMATED_MINIMUM_REACHED')
        self.assertFalse(r.payout_confirmed or r.authorized)
        self.assertIsNone(r.paid_usd)

    def test_changing_rate_uses_lesser_endpoint(self):
        self.sample(0,'0.5')
        self.sample(2,'0.1')
        self.sample(4,'0.4')
        self.assertEqual(self.report(4).sampled_gross_usd,D('.4'))

    def test_unknown_gap_is_not_credit_or_known_zero(self):
        self.sample(0)
        self.sample(2,None)
        self.sample(4)
        self.sample(6)
        r = self.report(6)
        self.assertEqual((r.sampled_gross_usd,r.unknown_seconds,r.observed_seconds),(D('.5'),D(4),D(2)))

    def test_zero_scoring_intervals_are_observed_not_unknown(self):
        self.sample(0,'0')
        self.sample(4,'0')
        r = self.report(4)
        self.assertEqual((r.observed_seconds,r.unknown_seconds,r.qualifying_seconds),(D(4),D(0),D(0)))
        self.assertEqual(r.state,'NOT_SCORING')
        self.assertFalse(r.minimum_reachable_at_current_rate)

    def test_stale_sample_gap_has_no_assumed_five_seconds_credit(self):
        self.sample(0)
        self.sample(6)
        self.assertEqual(self.report(6).sampled_gross_usd,0)
        self.assertEqual(self.report(6).unknown_seconds,6)

    def test_ownership_or_generation_change_breaks_interval(self):
        self.sample(0)
        self.sample(2,continuity=('epoch',2))
        self.assertEqual(self.report(2).unknown_seconds,2)

    def test_report_does_not_book_unobserved_future_time(self):
        self.sample(0)
        before = self.t.checkpoint()
        self.assertEqual(self.report(3).sampled_gross_usd,0)
        self.assertEqual(self.report(3).unknown_seconds,3)
        self.assertEqual(self.t.checkpoint(),before)
        self.assertIsNone(self.report(5).current_hourly_usd)

    def test_exit_horizon_controls_reachability_not_accrual(self):
        self.sample(0)
        r = self.report(exit_at=NOW+timedelta(seconds=3))
        self.assertEqual(r.seconds_to_minimum,4)
        self.assertFalse(r.minimum_reachable_at_current_rate)
        self.assertEqual(r.safe_seconds_remaining,3)

    def test_regressed_clock_revokes_rate_without_resetting_total(self):
        self.sample(0)
        self.sample(4)
        with self.assertRaises(InvalidData): self.sample(3)
        self.assertIsNone(self.report(4).current_hourly_usd)
        self.assertEqual(self.report(4).sampled_gross_usd,1)
        self.sample(5)
        self.assertEqual(self.report(5).sampled_gross_usd,1)

    def test_program_term_change_is_sticky_and_retains_prior_estimate(self):
        self.sample(0)
        self.sample(4)
        self.p = replace(self.p,discount_bps=4000)
        self.sample(5)
        self.assertEqual(self.report(5).state,'TERMS_CHANGED')
        self.assertEqual(self.report(5).sampled_gross_usd,1)
        self.p = replace(self.p,discount_bps=5000)
        self.sample(6)
        self.assertEqual(self.report(6).state,'TERMS_CHANGED')

    def test_different_programs_never_combine_to_reach_minimum(self):
        self.sample(0)
        self.sample(2)
        self.p = replace(self.p,program_id='P2')
        self.sample(2)
        self.sample(4)
        self.assertEqual(self.t.records['P'].estimate,D('.5'))
        self.assertEqual(self.t.records['P2'].estimate,D('.5'))

    def test_invalidation_preserves_totals_and_marks_gap(self):
        self.sample(0)
        self.sample(2)
        self.t.invalidate('A')
        self.sample(4)
        self.assertEqual((self.report(4).sampled_gross_usd,self.report(4).unknown_seconds),(D('.5'),D(2)))

    def test_full_capacity_never_evicts_old_earnings(self):
        self.t = RewardTracker(scope='fixture',capacity=1)
        self.sample(0)
        self.sample(2)
        self.p = replace(self.p,program_id='P2')
        with self.assertRaises(InvalidData): self.sample(4)
        self.assertEqual(self.t.records['P'].estimate,D('.5'))

    def test_report_excludes_time_before_and_after_program(self):
        self.p = replace(self.p,start=NOW,end=NOW+timedelta(seconds=3))
        self.sample(-2)
        self.sample(2)
        self.sample(4)
        r = self.report(8)
        self.assertEqual(r.observed_seconds,3)
        self.assertEqual(r.unknown_seconds,0)
        self.assertEqual(r.state,'ENDED')

    def test_actual_quotes_reflected_exactly_once(self):
        quotes = (Quote('bid',D('.5'),D(10)),Quote('ask',D('.6'),D(10)))
        b = book()
        share = snapshot_score(b,self.p,BANDS,quotes,reflected=quotes)[2]
        for offset in (0,2):
            self.t.observe(self.p,book=b,bands=BANDS,quotes=quotes,reflected_known=True,
                at=NOW+timedelta(seconds=offset),valid_until=NOW+timedelta(seconds=offset+5),
                continuity=('epoch',1))
        with localcontext() as ctx:
            ctx.prec = 40
            self.assertEqual(self.report(2).sampled_gross_usd,share*2)

    def test_missing_reflection_never_uses_hypothetical_reference_quote(self):
        for offset in (0,2):
            self.t.observe(self.p,book=book(),bands=BANDS,quotes=(Quote('bid',D('.5'),D(10)),),
                reflected_known=False,at=NOW+timedelta(seconds=offset),
                valid_until=NOW+timedelta(seconds=offset+5),continuity=('epoch',1))
        r = self.report(2)
        self.assertEqual(r.sampled_gross_usd,0)
        self.assertEqual(r.state,'UNKNOWN')
        self.assertEqual(r.unknown_seconds,2)

    def test_partial_quantity_and_insufficient_depth(self):
        for qty, ladder, expected in ((D(3),book(),True),(D(10),book(bids=(('.5','10'),)),False)):
            t = RewardTracker(scope='fixture')
            q = (Quote('bid',D('.5'),qty),)
            for offset in (0,2):
                t.observe(self.p,book=ladder,bands=BANDS,quotes=q,reflected_known=True,
                    at=NOW+timedelta(seconds=offset),valid_until=NOW+timedelta(seconds=offset+5),
                    continuity=('epoch',1))
            self.assertEqual(t.records['P'].estimate > 0,expected)

    def test_round_trip_loses_live_sample_and_downtime_is_unknown(self):
        self.sample(0)
        self.sample(4)
        state = self.t.checkpoint()
        fresh = RewardTracker(scope=self.t.scope)
        fresh.restore(state)
        self.t = fresh
        self.assertIsNone(self.report(4).current_hourly_usd)
        self.sample(14)
        self.assertEqual((self.report(14).sampled_gross_usd,self.report(14).unknown_seconds),(D(1),D(10)))

    def test_checkpoint_preserves_long_decimal_precision(self):
        self.sample(0,'0.123456789012345678901234567890123456789')
        self.sample(2,'0.123456789012345678901234567890123456789')
        other = RewardTracker(scope=self.t.scope)
        other.restore(self.t.checkpoint())
        self.assertEqual(other.records['P'].estimate,self.t.records['P'].estimate)

    def test_bad_checkpoint_is_atomic_and_cannot_change_scope(self):
        self.sample(0)
        state = self.t.checkpoint()
        for change in ('scope','duplicate','negative','coverage','fields'):
            data = deepcopy(state)
            if change == 'scope': data['scope'] = 'different-account'
            if change == 'duplicate': data['records'] *= 2
            if change == 'negative': data['records'][0]['estimate'] = '-1'
            if change == 'coverage': data['records'][0]['observed_seconds'] = '100'
            if change == 'fields': data['records'][0]['paid_usd'] = '1'
            other = RewardTracker(scope=self.t.scope)
            with self.assertRaises(InvalidData): other.restore(data)
            self.assertFalse(other.records)

    def test_invalid_quote_sample_revokes_previous_rate(self):
        self.sample(0)
        with self.assertRaises(InvalidData):
            self.t.observe(self.p,book=book(),bands=BANDS,quotes=[],reflected_known=True,
                at=NOW,valid_until=NOW+timedelta(seconds=5),continuity=('epoch',1))
        self.assertIsNone(self.report().current_hourly_usd)

    def test_account_capped_program_is_unknown_not_uncapped_income(self):
        self.p = replace(self.p,max_reward_centicents=10000)
        self.t.observe(self.p,book=book(),bands=BANDS,
            quotes=(Quote('bid',D('.5'),D(10)),),reflected_known=True,
            at=NOW,valid_until=NOW+timedelta(seconds=5),continuity=('epoch',1))
        self.assertEqual(self.report().reason,'unsupported_terms')
        self.assertIsNone(self.report().current_hourly_usd)

    def test_overlapping_programs_share_validation_but_not_own_quantities(self):
        import kalshi_bot.quoting as quoting
        programs = tuple(replace(self.p,program_id=f'p{i}') for i in range(16))
        quotes = (Quote('bid',D('.5'),D(10)),Quote('ask',D('.6'),D(10)))
        b = book()
        expected = snapshot_score(b,self.p,BANDS,quotes,reflected=quotes)[2]
        with patch.object(quoting,'_base',wraps=quoting._base) as base:
            for offset in (0,1):
                self.t.observe_many(programs,book=b,bands=BANDS,quotes=quotes,reflected_known=True,
                    at=NOW+timedelta(seconds=offset),valid_until=NOW+timedelta(seconds=5),
                    continuity=('epoch',1))
            self.assertEqual(base.call_count,2)
        self.assertTrue(all(r.estimate == expected for r in self.t.records.values()))


class CheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'rewards.json'
        self.store = RewardCheckpoint(self.path)
        self.t = RewardTracker(scope='fixture')
        self.t.record(program(),at=NOW,valid_until=NOW,rate=None)

    async def asyncTearDown(self): self.temp.cleanup()

    async def test_atomic_round_trip_and_explicit_io_only(self):
        self.assertFalse(self.path.exists())
        await self.store.save(self.t)
        other = RewardTracker(scope='fixture')
        await self.store.load(other)
        self.assertEqual(other.checkpoint(),self.t.checkpoint())
        self.assertEqual(list(self.path.parent.glob('.reward-*')),[])

    async def test_existing_unrelated_or_corrupt_json_is_not_overwritten(self):
        # Test fixture file creation, not a production/configuration write.
        self.path.write_text('{"unrelated":true}')
        before = self.path.read_bytes()
        with self.assertRaises(InvalidData): await self.store.save(self.t)
        self.assertEqual(self.path.read_bytes(),before)

    async def test_cannot_overwrite_retained_program_with_empty_tracker(self):
        await self.store.save(self.t)
        before = self.path.read_bytes()
        with self.assertRaises(InvalidData): await self.store.save(RewardTracker(scope='fixture'))
        self.assertEqual(self.path.read_bytes(),before)

    async def test_failed_replace_preserves_previous_and_cleans_temp(self):
        await self.store.save(self.t)
        before = self.path.read_bytes()
        with patch('kalshi_bot.reward_checkpoint.os.replace',side_effect=OSError('fixture')):
            with self.assertRaises(OSError): await self.store.save(self.t)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(list(self.path.parent.glob('.reward-*')))

    async def test_stale_other_store_cannot_overwrite_newer_evidence(self):
        await self.store.save(self.t)
        stale = RewardTracker(scope='fixture')
        await self.store.load(stale)
        self.t.record(program(),at=NOW+timedelta(seconds=2),
                      valid_until=NOW+timedelta(seconds=2),rate=None)
        await self.store.save(self.t)
        before = self.path.read_bytes()
        with self.assertRaises(InvalidData):
            await RewardCheckpoint(self.path).save(stale)
        self.assertEqual(self.path.read_bytes(),before)

    async def test_oversized_or_duplicate_key_checkpoint_cannot_load(self):
        self.path.write_text('{"schema":1,"schema":1}')
        with self.assertRaises(InvalidData):
            await self.store.load(RewardTracker(scope='fixture'))
        with patch('kalshi_bot.reward_checkpoint.MAX_BYTES',8):
            with self.assertRaises(InvalidData):
                await self.store.load(RewardTracker(scope='fixture'))

    async def test_load_cannot_replace_observation_received_during_read(self):
        import kalshi_bot.reward_checkpoint as module
        await self.store.save(self.t)
        other = RewardTracker(scope='fixture')
        entered,release = Event(),Event()
        original = module._read
        def held(*args):
            entered.set()
            release.wait(3)
            return original(*args)
        with patch.object(module,'_read',side_effect=held):
            task = asyncio.create_task(self.store.load(other))
            try:
                while not entered.is_set(): await asyncio.sleep(.001)
                other.record(program(),at=NOW+timedelta(seconds=1),
                             valid_until=NOW+timedelta(seconds=1),rate=None)
            finally:
                release.set()
                with self.assertRaises(InvalidData): await task
        self.assertEqual(other.records['P'].first_at,NOW+timedelta(seconds=1))

    async def test_cancellation_keeps_io_owned_until_thread_finishes(self):
        import kalshi_bot.reward_checkpoint as module
        entered,release = Event(),Event()
        original = module._write
        def held(*args):
            entered.set()
            release.wait(3)
            original(*args)
        with patch.object(module,'_write',side_effect=held):
            task = asyncio.create_task(self.store.save(self.t))
            try:
                while not entered.is_set(): await asyncio.sleep(.001)
                task.cancel()
                await asyncio.sleep(.01)
                task.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(task.done())
                with self.assertRaises(InvalidData): await self.store.save(self.t)
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(self.path.exists())


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = runtime_fixtures.RuntimeSelectionTests()
        await self.f.asyncSetUp()
        self.r = self.f.r
        self.rewards = self.r.attach_rewards(scope='fixture',offline_fixture=True)

    async def asyncTearDown(self): await self.f.asyncTearDown()

    async def owned(self):
        # Existing regression constructs real disposable writer/order/report state.
        await self.f.test_owned_order_retained_with_reflection_unknown()

    async def test_candidates_without_orders_never_accrue(self):
        await self.r._evaluate('A',None,0)
        self.assertFalse(self.rewards.tracker.records)
        self.assertFalse(self.rewards.status()['authorized'])

    async def test_actual_owned_orders_remain_unknown_without_reflection(self):
        await self.owned()
        self.rewards.refresh('A')
        row = self.rewards.progress('P')
        self.assertEqual(row.state,'UNKNOWN')
        self.assertEqual(row.sampled_gross_usd,0)
        self.assertEqual(row.reason,'reflection_unverified')

    async def test_bound_fixture_reflection_allows_estimate_then_revokes(self):
        await self.owned()
        self.rewards.confirm_reflection_fixture('A',offline_fixture=True)
        self.rewards.refresh('A')
        self.f.now += timedelta(seconds=1)
        self.f.mono += 1
        self.rewards.refresh('A')
        row = self.rewards.progress('P')
        self.assertGreater(row.sampled_gross_usd,0)
        self.r._revoke()
        self.assertIsNone(self.rewards.progress('P').current_hourly_usd)
        self.assertGreater(self.rewards.progress('P').sampled_gross_usd,0)

    async def test_structurally_equal_new_plan_is_not_same_source(self):
        await self.owned()
        self.rewards.confirm_reflection_fixture('A',offline_fixture=True)
        old = self.r.management._plans['A']
        self.r.management._plans['A'] = replace(old)
        self.rewards.refresh('A')
        self.assertIsNone(self.rewards.progress('P').current_hourly_usd)

    async def test_no_production_proof_or_duplicate_attachment(self):
        with self.assertRaises(InvalidData): self.rewards.confirm_reflection_fixture('A')
        with self.assertRaises(InvalidData): self.r.attach_rewards(scope='fixture',offline_fixture=True)

    async def test_program_publication_change_revokes_current_rate(self):
        await self.owned()
        self.rewards.confirm_reflection_fixture('A',offline_fixture=True)
        self.rewards.refresh('A')
        self.f.publish()
        self.assertIsNone(self.rewards.progress('P').current_hourly_usd)
        self.assertIsNone(self.rewards.tracker.records['P'].sample)

    async def test_catalog_refresh_gap_is_not_bridged_by_identical_terms(self):
        await self.owned()
        self.rewards.confirm_reflection_fixture('A',offline_fixture=True)
        self.rewards.refresh('A')
        self.f.now += timedelta(seconds=1)
        self.f.mono += 1
        self.f.publish()
        self.rewards.confirm_reflection_fixture('A',offline_fixture=True)
        self.rewards.refresh('A')
        self.assertEqual(self.rewards.progress('P').sampled_gross_usd,0)
        self.assertEqual(self.rewards.progress('P').unknown_seconds,1)

    async def test_capacity_fault_disables_telemetry_without_stopping_management(self):
        await self.owned()
        self.rewards.confirm_reflection_fixture('A',offline_fixture=True)
        self.rewards.refresh('A')
        before = self.rewards.tracker.checkpoint()
        with patch.object(self.rewards.tracker,'record',side_effect=InvalidData('fixture capacity')):
            await self.r._evaluate('A',None,0)
        self.assertEqual(self.rewards.status()['blocker'],'reward_observation_rejected')
        self.assertEqual(self.rewards.tracker.checkpoint(),before)
        self.assertIsNone(self.rewards.progress('P').current_hourly_usd)
        self.assertIsNotNone(self.r.management.current('A'))
        self.assertFalse(self.r.stop_requested.is_set())


if __name__ == '__main__': unittest.main()
