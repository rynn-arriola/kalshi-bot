"""Actual reader/runtime handoff with disposable ledgers and synthetic frames."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kalshi_bot.admission import ScopeChange
from kalshi_bot.books import BookConnection
from kalshi_bot.engine import EventEngine
from kalshi_bot.scheduler import DirtyScheduler
from kalshi_bot.values import InvalidData
import test_bot_incentive_discovery as fixtures
from test_bot_selection import terms
import test_bot_metadata_scheduler as metadata_fixtures


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate(): await asyncio.sleep(.001)


class Reader:
    def __init__(self, spec, owner):
        self.spec,self.owner = spec,owner
        self.closed = False
        self.on_close = None

    async def run(self, consume):
        try:
            await consume(self.spec.name,dict(id=1,type='subscribed',
                msg=dict(channel='orderbook_delta',sid=1)))
            for seq,ticker in enumerate(self.spec.tickers,1):
                await consume(self.spec.name,dict(type='orderbook_snapshot',sid=1,seq=seq,
                    msg=dict(market_ticker=ticker,yes_dollars_fp=[['.5','1000']],
                             no_dollars_fp=[['.6','1000']])))
            await asyncio.Event().wait()
        finally:
            if self.on_close is not None: await self.on_close()
            self.closed = True


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = fixtures.DiscoveryTests()
        await self.f.asyncSetUp()
        self.r = self.f.r
        self.a = self.r.attach_admission(offline_fixture=True)
        self.readers,self.tasks = [],[]
        def factory(spec):
            reader = Reader(spec,self)
            self.readers.append(reader)
            return reader
        self.r.reader_factory = factory
        self.name = next(iter(self.r.engine.shards))

    async def asyncTearDown(self):
        self.r.stop()
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        await self.f.asyncTearDown()

    async def prepare(self, tickers=('B',)):
        self.f.pages[0]['incentive_programs'] = [fixtures.row(t,t.lower()) for t in tickers]
        await self.f.refresh()
        task = asyncio.create_task(self.a.book_loop(next(s for s in self.r.specs if s.name==self.name)))
        self.tasks.append(task)
        await until(lambda:self.r.reader_states[self.name]=='subscribed')
        await self.r.engine.step()

    async def cycle(self):
        async with asyncio.timeout(3): return await self.a.cycle()

    async def test_new_scope_gets_fresh_book_then_existing_slot_limited_ranking(self):
        await self.prepare()
        old_generation = self.r.engine.shards[self.name].generation
        writer_revision = self.r.writer.revision
        self.assertTrue(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard),{'B'})
        self.assertTrue(self.readers[0].closed)
        self.assertFalse(self.r.selection.current('B'))
        self.assertFalse(self.r.engine.submit_book(self.name,{},generation=old_generation))
        await until(lambda:len(self.readers)==2 and self.r.reader_states[self.name]=='subscribed')
        self.r.management.set_terms(replace(terms(),ticker='B'))
        await self.r.engine.step()
        result = await self.r.selection.propose(window=self.f.f.w,free_cash=500)
        self.assertEqual(tuple(x.ticker for x in result.additions),('B',))
        self.assertEqual(sum(len(x.quotes) for x in result.additions),2)
        self.assertFalse(result.authorized or self.r.entry_allowed)
        self.assertEqual(self.r.writer.revision,writer_revision)
        self.assertFalse(await self.r.writer.mutations())
        self.assertEqual(self.r.account.generation,1)
        capped = await self.r.selection.propose(window=replace(self.f.f.w,cap=1),free_cash=500)
        self.assertFalse(capped.additions)  # Subscription space cannot override order slots.

    async def test_missing_account_evidence_keeps_scope(self):
        await self.prepare()
        self.r.account._invalidate()
        self.assertFalse(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard),{'A'})
        self.assertEqual(len(self.readers),1)

    async def test_paused_live_entries_do_not_rotate_readers(self):
        await self.prepare()
        self.r.live_session = SimpleNamespace(entries_paused=True)
        self.assertFalse(await self.cycle())
        self.r.live_session = None
        self.assertEqual(len(self.readers), 1)

    async def test_active_dispatch_defers_rotation(self):
        await self.prepare()
        self.r.dispatch_supervisor = SimpleNamespace(dispatcher=SimpleNamespace(
            status=lambda: SimpleNamespace(active=('A', 1))))
        try:
            self.assertFalse(await self.cycle())
            self.assertEqual(len(self.readers), 1)
        finally:
            self.r.dispatch_supervisor = None

    async def test_new_candidate_binding_revoked_during_join_retains_old_scope(self):
        await self.prepare()
        valid = True
        self.r.selection.candidate_inputs = SimpleNamespace(
            eligible=lambda catalog, now: frozenset(('B',)),
            blockers=lambda ticker, now: () if valid else ('timing_review_missing',))
        async def revoke():
            nonlocal valid
            valid = False
        self.readers[0].on_close = revoke
        self.assertFalse(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard), {'A'})
        await until(lambda:len(self.readers)==2)
        self.r.selection.candidate_inputs = None

    async def test_account_change_during_reader_join_restores_old_scope(self):
        await self.prepare()
        async def revoke(): self.r._revoke()
        self.readers[0].on_close = revoke
        self.assertFalse(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard),{'A'})
        await until(lambda:len(self.readers)==2)
        self.assertEqual(self.readers[1].spec.tickers,('A',))

    async def test_catalog_replacement_during_join_rejects_late_commit(self):
        await self.prepare()
        async def revoke(): self.f.d.request()
        self.readers[0].on_close = revoke
        self.assertFalse(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard),{'A'})

    async def test_owned_resting_order_cannot_be_removed(self):
        await self.prepare(('A','B'))
        await self.f.f.test_owned_order_retained_with_reflection_unknown()
        self.f.pages[0]['incentive_programs'] = [fixtures.row('B','b')]
        self.f.d.request()
        self.f.advance(1)
        await self.f.refresh()
        await self.cycle()
        self.assertIn('A',self.r.engine.market_shard)
        self.assertIn('A',self.readers[-1].spec.tickers)

    async def test_exact_inventory_blockers_prevent_removal_even_when_aggregate_flat(self):
        await self.prepare()
        original = self.r.writer.market_inventory
        async def blocked(*args,**kwargs):
            return replace(await original(*args,**kwargs),blockers=('unbound_intent',))
        with patch.object(self.r.writer,'market_inventory',side_effect=blocked):
            self.assertFalse(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard),{'A'})

    async def test_writer_revision_change_during_inventory_await_blocks(self):
        await self.prepare()
        original = self.r.writer.market_inventory
        async def changed(*args,**kwargs):
            row = await original(*args,**kwargs)
            await self.r.writer.observe(self.r.now())
            return row
        with patch.object(self.r.writer,'market_inventory',side_effect=changed):
            self.assertFalse(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard),{'A'})

    async def test_unresolved_exit_and_nonzero_position_each_retain_scope(self):
        await self.prepare()
        original = self.r.writer.market_inventory
        for field in ('position','exit'):
            async def blocked(*args,**kwargs):
                row = await original(*args,**kwargs)
                return (replace(row,position=Decimal(10)) if field=='position' else
                        replace(row,exit_journal=replace(row.exit_journal,unresolved_ioc=True)))
            with patch.object(self.r.writer,'market_inventory',side_effect=blocked):
                self.assertFalse(await self.cycle())
        self.assertFalse(self.readers[0].closed)

    async def test_expired_account_report_after_join_keeps_old_scope(self):
        await self.prepare()
        async def expire(): self.f.advance(6)
        self.readers[0].on_close = expire
        self.assertFalse(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard),{'A'})

    async def test_metadata_activity_defers_before_reader_teardown(self):
        await self.prepare()
        class Busy:
            def can_rebind(self, scope): return False
        with patch.object(self.r,'metadata_scheduler',Busy()):
            self.assertFalse(await self.cycle())
        self.assertFalse(self.readers[0].closed)

    async def test_metadata_handoff_is_reserved_then_retried_after_workers_drain(self):
        await self.prepare()
        class Busy:
            def __init__(self):
                self.busy = True
                self.target = None
            def request_rebind(self, scope):
                self.target = frozenset(scope)
                return True
            def can_rebind(self, scope):
                return not self.busy and frozenset(scope) == self.target
            def rebind_scope(self, scope):
                if not self.can_rebind(scope): raise InvalidData('still busy')
                self.target = None
            def cancel_rebind(self, scope=None): self.target = None
        scheduler = Busy()
        with patch.object(self.r,'metadata_scheduler',scheduler):
            self.assertFalse(await self.cycle())
            self.assertEqual(scheduler.target, frozenset(('B',)))
            self.assertFalse(self.readers[0].closed)
            scheduler.busy = False
            self.assertTrue(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard), {'B'})

    async def test_due_safety_deadline_and_engine_step_take_priority(self):
        await self.prepare()
        self.r.engine.running_step = True
        try: self.assertFalse(await self.cycle())
        finally: self.r.engine.running_step = False
        self.r.engine.schedule('A',self.r.clock()+.5)
        self.assertFalse(await self.cycle())
        self.assertFalse(self.readers[0].closed)

    async def test_removed_timer_and_caches_do_not_follow_new_scope(self):
        await self.prepare()
        self.r.engine.schedule('A',self.r.clock()+100)
        self.r.selection._rejected['A'] = ('fixture',)
        self.assertTrue(await self.cycle())
        self.assertNotIn('A',self.r.engine.deadlines.managed)
        self.assertIsNone(self.r.engine.deadlines.next_deadline())
        self.assertNotIn('A',self.r.management.terms)
        self.assertNotIn('A',self.r.selection._rejected)

    async def test_empty_catalog_keeps_one_anchor_not_unfiltered_subscribe(self):
        await self.prepare(())
        self.assertFalse(await self.cycle())
        self.assertEqual(set(self.r.engine.market_shard),{'A'})
        self.assertFalse((await self.r.selection.propose(window=self.f.f.w,free_cash=500)).additions)

    async def test_scope_capacity_and_batch_bound(self):
        await self.prepare(tuple(f'M{i}' for i in range(40)))
        self.r.writer.market_capacity = 20
        self.assertTrue(await self.cycle())
        self.assertLessEqual(len(self.r.engine.market_shard),16)
        self.assertFalse(self.a.status()['authorized'])

    async def test_stop_while_reader_closes_prevents_new_scope_and_joins(self):
        await self.prepare()
        entered,release = asyncio.Event(),asyncio.Event()
        async def held():
            entered.set()
            await release.wait()
        self.readers[0].on_close = held
        task = asyncio.create_task(self.a.cycle())
        self.tasks.append(task)
        await entered.wait()
        self.a.stop()
        release.set()
        await task
        await until(lambda:self.readers[0].closed)
        self.assertEqual(set(self.r.engine.market_shard),{'A'})
        self.assertEqual(len(self.readers),1)

    async def test_cancel_cycle_cannot_commit_after_join(self):
        await self.prepare()
        entered,release = asyncio.Event(),asyncio.Event()
        async def held():
            entered.set()
            await release.wait()
        self.readers[0].on_close = held
        task = asyncio.create_task(self.a.cycle())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        release.set()
        await until(lambda:len(self.readers)==2)
        self.assertEqual(set(self.r.engine.market_shard),{'A'})

    async def test_cancel_during_final_writer_proof_cannot_commit_later(self):
        await self.prepare()
        entered,release = asyncio.Event(),asyncio.Event()
        original = self.r.writer.market_inventory
        calls = 0
        async def held(*args,**kwargs):
            nonlocal calls
            row = await original(*args,**kwargs)
            calls += 1
            if calls == 2:
                entered.set()
                await release.wait()
            return row
        with patch.object(self.r.writer,'market_inventory',side_effect=held):
            task = asyncio.create_task(self.a.cycle())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            release.set()
            await until(lambda:len(self.readers)==2)
        self.assertEqual(set(self.r.engine.market_shard),{'A'})

    async def test_retry_exhaustion_cannot_be_reset_by_rotation(self):
        await self.prepare()
        self.r.reader_failures[self.name] = self.r.attempt_limit
        self.assertFalse(await self.cycle())
        self.assertEqual(len(self.readers),1)

    async def test_concurrent_cycle_rejected_before_discovery_await_completes(self):
        await self.prepare()
        entered,release = asyncio.Event(),asyncio.Event()
        original = self.r.selection.discovery_candidates
        async def held():
            entered.set()
            await release.wait()
            return await original()
        with patch.object(self.r.selection,'discovery_candidates',side_effect=held):
            task = asyncio.create_task(self.a.cycle())
            self.tasks.append(task)
            await entered.wait()
            with self.assertRaises(InvalidData): await self.a.cycle()
            release.set()
            await task

    async def test_actual_failed_reader_budget_survives_successful_rotation(self):
        base_factory = self.r.reader_factory
        count = 0
        def factory(spec):
            nonlocal count
            count += 1
            reader = base_factory(spec)
            if count == 1:
                async def failed(consume):
                    reader.closed = True
                    raise InvalidData('fixture disconnect')
                reader.run = failed
            return reader
        self.r.reader_factory = factory
        async def sleep(_): await asyncio.sleep(0)
        self.r.sleep = sleep
        await self.prepare()
        self.assertEqual(self.r.reader_failures[self.name],1)
        self.assertTrue(await self.cycle())
        await until(lambda:len(self.readers)==3)
        self.assertEqual(self.r.reader_failures[self.name],1)
        self.assertTrue(self.readers[1].closed)

    async def test_repeated_book_owner_cancellation_joins_held_teardown(self):
        await self.prepare()
        entered,release = asyncio.Event(),asyncio.Event()
        async def held():
            entered.set()
            await release.wait()
        self.readers[0].on_close = held
        owner = self.tasks[0]
        owner.cancel()
        await entered.wait()
        owner.cancel()
        await asyncio.sleep(.01)
        self.assertFalse(owner.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError): await owner
        self.assertTrue(self.readers[0].closed)

    async def test_admission_run_schedules_handoff_without_manual_cycle(self):
        await self.prepare()
        task = asyncio.create_task(self.a.run())
        self.tasks.append(task)
        await until(lambda:self.a.completed==1)
        self.a.stop()
        await task
        self.assertEqual(set(self.r.engine.market_shard),{'B'})
        self.assertFalse(self.a.running)

    async def test_transient_removal_deferral_retries_without_catalog_refresh(self):
        await self.prepare()
        original = self.a.removable
        checks = 0
        async def busy_once(change):
            nonlocal checks
            checks += 1
            return False if checks == 1 else await original(change)
        with patch.object(self.a, 'removable', side_effect=busy_once):
            self.assertFalse(await self.a.cycle())
            self.assertEqual(self.a.state, 'deferred')
            task = asyncio.create_task(self.a.run())
            self.tasks.append(task)
            await until(lambda:self.a.completed==1)
            self.a.stop()
            await task
        self.assertEqual(set(self.r.engine.market_shard), {'B'})

    async def test_runtime_owns_admission_and_book_tasks_until_stop(self):
        self.f.pages[0]['incentive_programs'] = [fixtures.row('B','b')]
        await self.f.refresh()
        original = self.r._connection
        async def connection(spec, **kwargs):
            if spec.name in self.r.engine.shards:
                return await original(spec,**kwargs)
            await self.r.stop_requested.wait()  # Account/lifecycle are synthetic existing sources.
        async def recovery(): await self.r.stop_requested.wait()
        # The manual fixture already owns current account proof; no fake account
        # HTTP routes or production requests are introduced for this wiring test.
        with patch.object(self.r,'_connection',side_effect=connection), \
             patch.object(self.r,'_recover',side_effect=recovery):
            task = asyncio.create_task(self.r.run())
            self.tasks.append(task)
            await until(lambda:self.r.reader_states[self.name]=='subscribed')
            self.f.advance(2)
            self.a.request()
            # A source/engine race may correctly defer once. The injected clock
            # must reach its one-second retry deadline instead of freezing at 102
            # while the real-time test timeout advances. Do not change policy.
            async with asyncio.timeout(3):
                while self.a.completed != 1:
                    await asyncio.sleep(.001)
                    delay = self.a.next_at-self.r.clock()
                    if 0 < delay <= 1:
                        self.f.advance(delay)
            self.r.stop()
            await task
        self.assertFalse(self.r.running or self.a.running)
        self.assertTrue(all(reader.closed for reader in self.readers))

    async def test_runtime_ownership_wait_advances_one_deferred_retry(self):
        self.a.next_at = 102
        original = self.a.cycle
        deferred = False
        async def cycle():
            nonlocal deferred
            if not deferred:
                deferred = True
                self.a.state = 'deferred'
                return False
            return await original()
        with patch.object(self.a, 'cycle', side_effect=cycle):
            await self.test_runtime_owns_admission_and_book_tasks_until_stop()
        self.assertTrue(deferred)

    async def test_explicit_attachment_and_duplicate_rejected(self):
        with self.assertRaises(InvalidData): self.r.attach_admission(offline_fixture=True)
        from kalshi_bot.admission import MarketAdmission
        with self.assertRaises(InvalidData): MarketAdmission(self.r)


class ScopeTests(unittest.TestCase):
    def test_unregister_removes_dirty_due_and_readd_has_no_old_deadline(self):
        s = DirtyScheduler(2)
        s.register('A'); s.mark('A'); s.schedule('A',1)
        s.unregister('A'); s.register('A')
        self.assertEqual(s.take(2),[])
        self.assertIsNone(s.next_deadline())

    def test_scope_replacement_rejects_overlap_and_running_step(self):
        async def noop(*args): pass
        e = EventEngine({'a':BookConnection(('A',)), 'b':BookConnection(('B',))},
                        private_handler=noop,evaluate=noop,deadline_handler=noop)
        with self.assertRaises(InvalidData): e.replace_book_scope('a',('B',),capacity=2)
        self.assertEqual(set(e.market_shard),{'A','B'})
        e.running_step = True
        with self.assertRaises(InvalidData): e.replace_book_scope('a',('C',),capacity=2)

    def test_second_shard_and_its_safety_timers_are_untouched(self):
        async def noop(*args): pass
        e = EventEngine({'a':BookConnection(('A',)), 'b':BookConnection(('B',))},
                        private_handler=noop,evaluate=noop,deadline_handler=noop)
        other = e.shards['b']
        e.begin_book_epoch('b')
        e.schedule('B',1000)
        e.replace_book_scope('a',('C',),capacity=2)
        self.assertIs(e.shards['b'],other)
        self.assertEqual(other.generation,1)
        self.assertEqual(e.deadlines.due_for('B'),1000)


class MetadataScopeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = metadata_fixtures.SchedulerTests()
        await self.f.asyncSetUp()

    async def asyncTearDown(self): await self.f.asyncTearDown()

    async def test_prune_removed_market_without_copying_review_to_new_one(self):
        self.f.connect()
        await self.f.drain(2)
        scheduler,service = self.f.scheduler,self.f.service
        self.assertTrue(scheduler.can_rebind(('B','C')))
        scheduler.rebind_scope(('B','C'))
        self.assertEqual(service.tickers,{'B','C'})
        self.assertNotIn('A',service.results)
        self.assertNotIn(('market','A'),service.values)
        self.assertNotIn('A',scheduler.due)
        self.assertNotIn('C',service.reviews)
        self.assertIn('B',service.reviews)
        self.assertIn('C',scheduler.due)
        self.assertTrue(all(t!='A' for _,_,t in scheduler.heap))

    async def test_readding_market_preserves_exhaustion_and_cooldown(self):
        scheduler = self.f.scheduler
        scheduler.failures['A'] = 3
        scheduler.exhausted.add('A')
        scheduler.not_before['A'] = 1000
        scheduler.rebind_scope(('B',))
        self.assertIn('A',scheduler.retired)
        scheduler.rebind_scope(('A','B'))
        self.assertEqual(scheduler.failures['A'],3)
        self.assertIn('A',scheduler.exhausted)
        self.assertEqual(scheduler.not_before['A'],1000)
        self.assertFalse(scheduler.request('A'))

    async def test_retention_saturation_keeps_original_scope(self):
        scheduler = self.f.scheduler
        scheduler.retired = {f'M{i}':(1,False,0) for i in range(1024)}
        scheduler.failures['A'] = 1
        self.assertFalse(scheduler.can_rebind(('B',)))
        with self.assertRaises(InvalidData): scheduler.rebind_scope(('B',))
        self.assertEqual(self.f.service.tickers,{'A','B'})

    async def test_dependency_inflight_and_refreshing_block_rebind(self):
        self.f.service.refreshing.add('A')
        self.assertFalse(self.f.scheduler.can_rebind(('B',)))
        with self.assertRaises(InvalidData): self.f.service.rebind_scope(('B',))
        self.f.service.refreshing.clear()


if __name__ == '__main__': unittest.main()
