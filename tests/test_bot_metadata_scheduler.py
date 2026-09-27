"""D-036 injected clocks/reads; no credentials, real streams or orders."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalshi_bot.market_inputs import ExitInputService, FeeProfile, InputRefreshSuperseded
from kalshi_bot.metadata_scheduler import MetadataScheduler
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_market_inputs import NOW, Reads, review
from test_bot_recovery_runtime import AccountReads, FakeReader


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mono, self.wall = 0., NOW
        self.reads = Reads(('A','B'))
        self.published, self.revoked = {}, []
        self.service = ExitInputService(self.reads, ('A','B'), now=lambda:self.wall,
            clock=lambda:self.mono, ttl=10, timing_reviews=tuple(review(m) for m in self.reads.markets.values()),
            fee_profile=FeeProfile(D('.0001'), 'fixture', NOW+timedelta(hours=1)))
        def revoke(ticker):
            self.published.pop(ticker, None)
            self.revoked.append(ticker)
        self.service.bind(lambda terms:self.published.__setitem__(terms.ticker,terms), revoke)
        self.scheduler = MetadataScheduler(self.service)
        self.service.begin(1)
        self.seq = 0

    async def asyncTearDown(self):
        await self.scheduler.close()

    def advance(self, seconds):
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)

    def connect(self):
        self.service.subscribed(self.service.generation, 1)

    def event(self, ticker='A', event_type='deactivated', **fields):
        self.seq += 1
        self.service.ingest(dict(type='market_lifecycle_v2',sid=1,seq=self.seq,
            msg=dict(market_ticker=ticker,event_type=event_type,**fields)), generation=self.service.generation)

    async def drain(self, completed=None):
        for _ in range(200):
            self.scheduler.step()
            await asyncio.sleep(.001)
            if not self.scheduler.active and (completed is None or self.scheduler.completed>=completed):
                return
        self.fail('scheduler did not drain bounded fixture work')

    async def test_no_work_before_ack(self):
        await self.drain()
        self.assertEqual(self.reads.calls, [])
        self.assertFalse(self.scheduler.request('A'))

    async def test_priority_market_starts_before_fifo_discovery(self):
        self.scheduler.concurrency = 1
        self.scheduler.priority = lambda ticker:ticker == 'B'
        self.connect()
        self.scheduler.step()
        await asyncio.sleep(0)
        self.assertEqual(set(self.scheduler.active), {'B'})
        self.assertEqual(self.scheduler.status()['priority_active'], 1)
        await self.drain(2)

    async def test_owner_rank_starts_before_candidate_rank(self):
        self.scheduler.concurrency = 1
        self.scheduler.priority = lambda ticker:1 if ticker == 'A' else 2
        self.connect()
        self.scheduler.step()
        await asyncio.sleep(0)
        self.assertEqual(set(self.scheduler.active), {'B'})
        await self.drain(2)

    async def test_four_workers_are_supported_for_broad_discovery(self):
        self.scheduler.concurrency = 4
        self.assertEqual(self.scheduler.concurrency, 4)

    async def test_bootstrap_shares_dependencies_and_schedules_expiry(self):
        self.connect()
        await self.drain(2)
        self.assertEqual(len(self.reads.calls), 7)
        self.assertEqual(set(self.published), {'A','B'})
        self.assertEqual(len(self.scheduler.due), 2)
        self.assertEqual(self.scheduler.high_water, 2)
        self.assertFalse(self.scheduler.status()['live_authority'])

    async def test_advisory_request_keeps_fresh_terms_and_does_not_start_worker(self):
        self.connect()
        await self.drain(2)
        result = self.service.results['A']
        calls, started = len(self.reads.calls), self.scheduler.started
        self.advance(.1)
        for _ in range(20):
            self.scheduler.request('A')
            self.scheduler.step()
            await asyncio.sleep(0)
        self.assertIs(self.service.results.get('A'), result)
        self.assertIs(self.published.get('A'), result.terms)
        self.assertEqual(self.scheduler.started, started)
        self.assertEqual(len(self.reads.calls), calls)
        # Keeping a fresh result must not lose the later expiry wake.
        self.scheduler.defer = lambda: True
        self.advance(9.9)
        self.scheduler.step()
        self.assertNotIn('A', self.service.results)
        self.assertNotIn('A', self.published)

    async def test_requested_fresh_terms_survive_deferred_workers_not_real_change(self):
        self.connect()
        await self.drain(2)
        result = self.service.results['A']
        self.advance(.1)
        self.scheduler.defer = lambda: True
        self.scheduler.request('A')
        self.scheduler.step()
        self.assertIs(self.service.results.get('A'), result)
        self.event('A', event_type='deactivated')
        self.assertNotIn('A', self.service.results)
        self.assertNotIn('A', self.published)
        self.scheduler.defer = lambda: False
        await self.drain(3)
        self.assertFalse(self.published['A'].active)

    async def test_duplicate_ack_does_not_rebootstrap(self):
        self.connect()
        await self.drain(2)
        self.connect()
        await self.drain()
        self.assertEqual(self.scheduler.completed, 2)

    async def test_warm_stream_change_republishes_without_extra_rest(self):
        self.connect()
        await self.drain(2)
        calls = len(self.reads.calls)
        self.advance(.1)
        self.event()
        self.assertNotIn('A', self.published)
        await self.drain(3)
        self.assertFalse(self.published['A'].active)
        self.assertEqual(len(self.reads.calls), calls)

    async def test_fee_update_fanout_is_shared_and_stream_first(self):
        self.connect()
        await self.drain(2)
        self.advance(.1)
        self.service.ingest(dict(type='event_fee_update',sid=1,seq=1,
            msg=dict(event_ticker='E',fee_type_override='quadratic',fee_multiplier_override=D(2))),generation=1)
        self.assertFalse(self.published)
        await self.drain(4)
        self.assertEqual(len(self.reads.calls), 7)
        self.assertEqual(self.published['A'].taker_fee_per_contract_bound,D('.0451'))

    async def test_expiry_fetches_once_per_shared_dependency(self):
        self.connect()
        await self.drain(2)
        self.advance(10)
        await self.drain(4)
        self.assertEqual(len(self.reads.calls), 14)

    async def test_deferred_workers_still_revoke_expired_terms(self):
        self.connect()
        await self.drain(2)
        self.scheduler.defer = lambda:True
        self.advance(10)
        self.scheduler.step()
        self.assertFalse(self.published)
        self.assertEqual(len(self.scheduler.ready), 2)
        self.assertFalse(self.scheduler.active)
        self.scheduler.defer = lambda:False
        await self.drain(4)

    async def test_rebind_reservation_drains_workers_without_refilling_slots(self):
        gate = asyncio.Event()
        entered = asyncio.Event()
        async def slow(name):
            entered.set()
            await gate.wait()
        self.reads.before = slow
        self.connect()
        self.scheduler.step()
        await entered.wait()
        self.scheduler.request('A')  # Coalesced follow-up work must remain queued.
        self.assertTrue(self.scheduler.request_rebind(('B',)))
        self.assertTrue(self.scheduler.status()['rebind_reserved'])
        gate.set()
        await self.drain(2)
        self.assertFalse(self.scheduler.active)
        self.assertTrue(self.scheduler.ready or self.scheduler.due)
        self.assertTrue(self.scheduler.can_rebind(('B',)))
        self.assertFalse(self.scheduler.can_rebind(('A','B')))
        self.scheduler.rebind_scope(('B',))
        self.assertFalse(self.scheduler.status()['rebind_reserved'])
        self.assertEqual(self.service.tickers, {'B'})

    async def test_abandoned_rebind_reservation_expires_and_work_resumes(self):
        self.connect()
        self.assertTrue(self.scheduler.request_rebind(('B',)))
        self.scheduler.step()
        self.assertFalse(self.scheduler.active)
        self.assertEqual(set(self.scheduler.ready), {'A','B'})
        self.advance(self.scheduler.REBIND_HOLD)
        self.scheduler.step()
        self.assertTrue(self.scheduler.active)
        self.assertFalse(self.scheduler.status()['rebind_reserved'])
        await self.drain(2)

    async def test_burst_coalesces_and_bounds_heap(self):
        self.connect()
        await self.drain(2)
        self.advance(.1)
        for _ in range(1000):
            self.scheduler.request('A')
            self.scheduler.request('B')
        self.assertLessEqual(len(self.scheduler.heap), 4)
        await self.drain(2)
        self.assertEqual(self.scheduler.started, 2)
        self.assertEqual(len(self.reads.calls), 7)

    async def test_requests_while_busy_skip_redundant_followup_when_fresh(self):
        gate = asyncio.Event()
        async def slow(name): await gate.wait()
        self.reads.before = slow
        self.connect()
        self.scheduler.step()
        await asyncio.sleep(0)
        for _ in range(100): self.scheduler.request('A')
        gate.set()
        await self.drain(2)
        self.advance(.1)
        await self.drain(2)
        self.assertEqual(self.scheduler.started, 2)
        self.assertEqual(len(self.reads.calls), 7)

    async def test_unknown_universe_events_cannot_grow_work(self):
        self.connect()
        await self.drain(2)
        for i in range(100): self.event(ticker=f'OTHER{i}')
        self.assertEqual(len(self.scheduler.due), 2)
        self.assertEqual(self.scheduler.started, 2)
        with self.assertRaises(InvalidData): self.scheduler.request('OTHER')

    async def test_failures_back_off_and_exhaust_without_storm_reset(self):
        self.reads.markets['A'].pop('price_ranges')
        self.connect()
        await self.drain()
        self.assertEqual(self.scheduler.failures['A'], 1)
        for _ in range(100): self.event()
        await self.drain()
        self.assertEqual(self.scheduler.failures['A'], 1)
        self.advance(1)
        await self.drain()
        self.assertEqual(self.scheduler.failures['A'], 2)
        self.advance(2)
        await self.drain()
        self.assertIn('A', self.scheduler.exhausted)
        started = self.scheduler.started
        self.service.begin(2)
        self.connect()
        await self.drain()
        self.assertEqual(self.scheduler.started, started+1) # B only
        self.assertIn('A', self.scheduler.exhausted)

    async def test_an_exhausted_market_retries_after_the_cooldown(self):
        """Finding 218: exhaustion is a pause, not unselectable until restart."""
        price_ranges = self.reads.markets['A'].pop('price_ranges')
        self.advance(1000)  # the cooldown counts from exhaustion, not from clock zero
        self.connect()
        await self.drain()
        for step in (1, 2):
            self.advance(step)
            await self.drain()
        self.assertIn('A', self.scheduler.exhausted)
        self.reads.markets['A']['price_ranges'] = price_ranges
        self.advance(self.scheduler.EXHAUSTED_COOLDOWN_SECONDS-10)
        await self.drain()
        self.assertIn('A', self.scheduler.exhausted)
        self.assertNotIn('A', self.published)
        self.advance(10)
        await self.drain()
        self.advance(1)
        await self.drain()
        self.assertNotIn('A', self.scheduler.exhausted)
        self.assertIn('A', self.published)
        self.assertEqual(self.scheduler.status()['cooldown_retries'], 1)

    async def test_superseded_publication_retries_without_spending_failure_budget(self):
        events=[]
        class Log:
            def emit(self, name, **fields): events.append(name)
        self.service.diagnostics=Log()
        original=self.service.refresh
        overtaken=False
        async def refresh(ticker):
            nonlocal overtaken
            if ticker=='A' and not overtaken:
                overtaken=True
                self.service.diagnostics.emit('exit_inputs_superseded',market=ticker,generation=1)
                raise InputRefreshSuperseded('injected publication race')
            return await original(ticker)
        self.service.refresh=refresh
        self.connect()
        for _ in range(50):
            self.scheduler.step()
            await asyncio.sleep(.001)
            if overtaken and not self.scheduler.active:
                break
        self.advance(.1)
        await self.drain(2)
        self.assertEqual(set(self.published), {'A','B'})
        self.assertFalse(self.scheduler.failures)
        self.assertFalse(self.scheduler.exhausted)
        self.assertEqual(events.count('exit_inputs_superseded'), 1)

    async def test_explicit_retry_keeps_cooldown_and_missing_review_unapproved(self):
        self.reads.markets['A'].pop('price_ranges')
        self.connect()
        await self.drain()
        for interval in (1,2):
            self.advance(interval)
            await self.drain()
        self.reads.markets['A']['price_ranges'] = [dict(start='0',end='1',step='.01')]
        self.service.set_review('A',None)
        self.scheduler.request('A',retry=True)
        await self.drain()
        self.assertNotIn('A',self.published)
        self.advance(4)
        await self.drain()
        self.assertIn('timing_review_missing',self.service.results['A'].blockers)
        self.assertIsNone(self.published['A'].event_risk_at)

    async def test_disconnect_cancels_work_and_stale_reads_cannot_publish(self):
        gate = asyncio.Event()
        async def slow(name): await gate.wait()
        self.reads.before=slow
        self.connect()
        self.scheduler.step()
        await asyncio.sleep(.001)
        self.service.disconnect()
        gate.set()
        await self.drain()
        self.assertFalse(self.published)
        self.assertFalse(self.scheduler.due)
        self.assertFalse(self.scheduler.active)

    async def test_reconnect_rebuilds_and_never_accepts_old_epoch(self):
        self.connect()
        await self.drain(2)
        self.service.begin(2)
        self.connect()
        self.advance(.1)
        await self.drain(4)
        self.assertTrue(all(r.generation==2 for r in self.service.results.values()))
        self.assertFalse(self.service.ingest({},generation=1))

    async def test_reconnect_during_old_read_does_not_spend_current_retry(self):
        gate=asyncio.Event()
        entered=asyncio.Event()
        async def slow(name):
            if name=='market':
                entered.set()
                await gate.wait()
        self.reads.before=slow
        self.scheduler.attempt_limit=1
        self.connect()
        self.scheduler.step()
        await asyncio.wait_for(entered.wait(),1)
        self.service.begin(2)
        self.connect()
        self.advance(.1)
        try:
            for _ in range(10):
                self.scheduler.step()
                await asyncio.sleep(.001)
            gate.set()
            await self.drain(2)
            self.assertFalse(self.scheduler.failures)
            self.assertFalse(self.scheduler.exhausted)
            self.assertEqual(set(self.published),{'A','B'})
            self.assertTrue(all(r.generation==2 for r in self.service.results.values()))
        finally: gate.set()

    async def test_timeout_is_bounded_failure_not_hung_worker(self):
        self.scheduler.timeout=.01
        async def slow(name): await asyncio.Event().wait()
        self.reads.before=slow
        self.connect()
        await self.drain()
        self.assertEqual(self.scheduler.failures, {'A':1,'B':1})
        self.assertFalse(self.published)

    async def test_unexpected_exception_escapes_to_supervisor(self):
        async def broken(name): raise RuntimeError('injected')
        self.reads.before=broken
        self.connect()
        with self.assertRaises(RuntimeError): await self.drain()

    async def test_review_and_profile_updates_revoke_then_refresh_cached_inputs(self):
        self.connect()
        await self.drain(2)
        self.advance(.1)
        self.service.set_review('A',None)
        self.service.set_fee_profile(None)
        self.assertFalse(self.published)
        await self.drain(4)
        self.assertIn('timing_review_missing',self.service.results['A'].blockers)
        self.assertIn('fee_profile_missing',self.service.results['B'].blockers)
        self.assertEqual(len(self.reads.calls),7)

    async def test_fee_review_expiry_is_a_deadline_without_extra_rest(self):
        self.service.set_fee_profile(FeeProfile(D('.0001'),'fixture',NOW+timedelta(seconds=2)))
        self.connect()
        await self.drain(2)
        self.assertEqual(self.scheduler.due['A'][0],2)
        self.advance(2)
        await self.drain(4)
        self.assertIsNone(self.published['A'].taker_fee_per_contract_bound)
        self.assertEqual(len(self.reads.calls),7)

    async def test_market_open_is_a_deadline(self):
        self.reads.markets['A']['open_time']=(NOW+timedelta(seconds=2)).isoformat()
        self.connect()
        await self.drain(2)
        self.assertFalse(self.published['A'].active)
        self.assertEqual(self.scheduler.due['A'][0],2)
        self.advance(2)
        await self.drain(3)
        self.assertTrue(self.published['A'].active)

    async def test_clock_jump_fails_closed_in_running_owner(self):
        self.connect()
        task=asyncio.create_task(self.scheduler.run())
        try:
            async with asyncio.timeout(2):
                while not self.published: await asyncio.sleep(.001)
            self.wall += timedelta(seconds=3)
            self.scheduler.wake.set()
            with self.assertRaises(InvalidData): await task
            self.assertFalse(self.published)
            self.assertTrue(self.service.closed)
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    async def test_monotonic_regression_is_rejected(self):
        self.scheduler.step()
        self.mono=-1
        with self.assertRaises(InvalidData): self.scheduler.step()

    async def test_run_shutdown_drains_and_is_single_use(self):
        self.connect()
        task=asyncio.create_task(self.scheduler.run())
        async with asyncio.timeout(2):
            while self.scheduler.completed<2: await asyncio.sleep(.001)
        self.scheduler.stop()
        await task
        self.assertTrue(self.service.closed)
        self.assertFalse(self.scheduler.active)
        self.assertFalse(self.published)
        with self.assertRaises(InvalidData): await self.scheduler.run()

    async def test_failure_diagnostic_codes_are_specific(self):
        events=[]
        class Log:
            def emit(self, name, **fields): events.append(name)
        self.scheduler.diagnostics=Log()
        self.scheduler.attempt_limit=1
        self.reads.markets['A'].pop('price_ranges')
        self.connect()
        await self.drain()
        self.assertIn('metadata_exhausted',events)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_does_not_defer_metadata_but_private_work_does(self):
        reads = Reads(('A','B'))
        service = ExitInputService(reads, ('A','B'), now=lambda:NOW, clock=lambda:0, ttl=10)
        async def noop(*args): pass
        with TemporaryDirectory() as folder:
            async with LedgerWriter(Path(folder)/'fixture.db') as writer:
                runtime = RecoveryRuntime(writer, reads, FakeReader, tickers=('A','B'),
                    subaccount=0, history_start=NOW-timedelta(hours=1), now=lambda:NOW,
                    clock=lambda:0, evaluate=noop, deadline_handler=noop,
                    lifecycle_handler=noop, market_inputs=service, broad_discovery=True)
                runtime.recovery_state = 'recovering'
                scheduler = runtime.metadata_scheduler
                service.begin(1)
                service.subscribed(1,1)
                runtime.account._processing = True
                scheduler.step()
                self.assertFalse(scheduler.active)
                runtime.account._processing = False
                scheduler.step()
                self.assertEqual(set(scheduler.active), {'A','B'})
                self.assertEqual(scheduler.concurrency, 4)
                await scheduler.close()

    async def test_runtime_owns_scheduler_bootstrap_and_shutdown(self):
        metadata, account = Reads(('A','B')), AccountReads()
        class Combined:
            async def read(self,name,**kw):
                owner=metadata if name in {'market','event','series','series_fees','milestone'} else account
                return await owner.read(name,**kw)
            async def collect(self,name,**kw):
                return await (metadata if name=='event_fees' else account).collect(name,**kw)
        reads=Combined()
        service=ExitInputService(reads,('A','B'),now=lambda:NOW,clock=lambda:0,ttl=10)
        async def noop(*args): pass
        with TemporaryDirectory() as folder:
            async with LedgerWriter(Path(folder)/'fixture.db') as writer:
                runtime=RecoveryRuntime(writer,reads,FakeReader,tickers=('A','B'),subaccount=0,
                    history_start=NOW-timedelta(hours=1),now=lambda:NOW,clock=lambda:0,
                    evaluate=noop,deadline_handler=noop,lifecycle_handler=noop,market_inputs=service)
                task=asyncio.create_task(runtime.run())
                try:
                    async with asyncio.timeout(3):
                        while len(runtime.management.terms)<2:
                            if task.done(): await task
                            await asyncio.sleep(.001)
                    self.assertTrue(runtime.status()['metadata']['running'])
                    self.assertFalse(runtime.entry_allowed)
                    with self.assertRaises(InvalidData): await runtime.refresh_exit_inputs('A')
                    self.assertTrue(runtime.request_exit_input_refresh('A'))
                finally:
                    runtime.stop()
                    await task
                self.assertTrue(service.closed)
                self.assertFalse(runtime.management.terms)
