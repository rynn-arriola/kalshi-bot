"""Shared REST owner, fake clocks/wire/signer only; never account access."""
import asyncio
from copy import deepcopy
import json
from threading import Event
import unittest

from kalshi_bot.quota import QuotaUnavailable, QuotaRolloverPending
from kalshi_bot.quota_supervisor import QuotaSupervisor
from kalshi_bot.rest import WireResponse, ReadFailure
from kalshi_bot.values import InvalidData
from kalshi_bot.write_budget import ORDERS, WriteQuotaSnapshot
from kalshi_bot.write_quota_source import WriteQuotaSource
from test_bot_quota import setup, LIMITS, BASE, candidate, eventually, Signer


class WriteQuotaSourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.limits = deepcopy(LIMITS)
        self.costs = dict(default_cost=11, endpoint_costs=[
            dict(method='GET', path=ORDERS, cost=7),
            dict(method='POST', path=ORDERS, cost=17),
            dict(method='DELETE', path=ORDERS+'/{order_id}', cost=3)])
        self.calls = []
        self.failure = False
        self.entered, self.release = Event(), Event()
        self.hold = False
        def wire(url, *_):
            self.calls.append(url.rsplit('/', 1)[-1])
            if self.hold and url.endswith('endpoint_costs'):
                self.entered.set()
                if not self.release.wait(3):
                    raise TimeoutError('fixture wire was not released')
            if self.failure and url.endswith('/limits'):
                return WireResponse(401, b'{}')
            return WireResponse(200, json.dumps(self.costs if url.endswith('endpoint_costs')
                                                else self.limits).encode())
        self.clock, self.reads, self.guard = setup(wire=wire)
        self.source = WriteQuotaSource(self.reads, shards=(0, 1), offline_fixture=True)

    async def asyncTearDown(self):
        self.release.set()
        await self.reads.close()

    async def bootstrap(self):
        result = await self.reads.refresh_budget()
        self.assertFalse(result['write_enabled'])
        budget = self.source.budget
        self.clock.t += 1
        return budget

    def reserve(self, budget, method='POST', route=ORDERS, shard=0):
        permit = budget.try_reserve(method, route, shard=shard, now=self.source.clock_pair())
        self.assertIsNotNone(permit)
        return permit

    async def test_explicit_fixture_single_unused_guarded_owner(self):
        with self.assertRaises(InvalidData):
            WriteQuotaSource(self.reads, shards=(0,), offline_fixture=True)
        clock, reads, guard = setup()
        try:
            for flag in (False, 1, None):
                with self.assertRaises(InvalidData):
                    WriteQuotaSource(reads, shards=(0,), offline_fixture=flag)
            for shards in ((), (0, 0), (-1,), (True,), tuple(range(129))):
                with self.assertRaises(InvalidData):
                    WriteQuotaSource(reads, shards=shards, offline_fixture=True)
            await reads.refresh_budget()
            with self.assertRaises(InvalidData):
                WriteQuotaSource(reads, shards=(0,), offline_fixture=True)
        finally:
            await reads.close()

    async def test_initially_blocked_then_exact_full_method_costs_and_zero_tokens(self):
        with self.assertRaises(QuotaUnavailable):
            self.source.budget
        await self.reads.refresh_budget()
        budget = self.source.budget
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))
        self.clock.t += 1
        post = self.reserve(budget)
        cancel = self.reserve(budget, 'DELETE', ORDERS+'/order')
        self.assertEqual((post.cost, cancel.cost), (17, 3))
        self.assertEqual(self.reads.budget.costs[ORDERS], 7)
        self.assertEqual(self.calls, ['endpoint_costs', 'limits'])
        self.assertFalse(self.source.status()['live_ready'])

    async def test_omitted_method_uses_observed_default_not_read_cost(self):
        self.costs['endpoint_costs'] = self.costs['endpoint_costs'][:1]
        self.assertEqual(self.reserve(await self.bootstrap()).cost, 11)

    async def test_coalesced_pair_not_one_read_per_market(self):
        self.hold = True
        tasks = [asyncio.create_task(self.reads.refresh_budget()) for _ in range(30)]
        await eventually(self.entered.is_set)
        self.release.set()
        await asyncio.gather(*tasks)
        self.assertEqual(self.calls, ['endpoint_costs', 'limits'])
        self.assertEqual(self.source.status()['sequence'], 1)

    async def test_refresh_reuses_budget_zeroes_tokens_preserves_pause_revokes_permits(self):
        budget = await self.bootstrap()
        old = self.reserve(budget)
        budget.pause_429(shard=1, seconds=10, now=self.source.clock_pair())
        self.costs['endpoint_costs'][1]['cost'] = 23
        await self.reads.refresh_budget()
        self.assertIs(self.source.budget, budget)
        self.assertEqual(budget.status(now=self.source.clock_pair()).outstanding, 0)
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))
        with self.assertRaises(InvalidData):
            budget.consume(old, 'POST', ORDERS, shard=0, now=self.source.clock_pair())
        self.clock.t += 1
        self.assertEqual(self.reserve(budget).cost, 23)
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=1, now=self.source.clock_pair()))

    async def test_partial_refresh_revokes_old_permit_before_network_finishes(self):
        budget = await self.bootstrap()
        old = self.reserve(budget)
        self.hold = True
        task = asyncio.create_task(self.reads.refresh_budget())
        await eventually(self.entered.is_set)
        with self.assertRaises(QuotaUnavailable):
            budget.consume(old, 'POST', ORDERS, shard=0, now=self.source.clock_pair())
        self.release.set()
        await task
        self.assertEqual(budget.status(now=self.source.clock_pair()).outstanding, 0)

    async def test_failed_pair_cannot_restore_old_write_evidence(self):
        budget = await self.bootstrap()
        self.failure = True
        with self.assertRaises(ReadFailure):
            await self.reads.refresh_budget()
        self.assertFalse(self.source.status()['available'])
        self.clock.t += 1
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))
        self.failure = False
        await self.reads.refresh_budget()
        self.assertTrue(self.source.status()['available'])

    async def test_malformed_write_route_prevents_both_installations(self):
        await self.bootstrap()
        revision = self.guard.revision
        self.costs['endpoint_costs'][1]['path'] = '/portfolio/../orders'
        with self.assertRaises(InvalidData):
            await self.reads.refresh_budget()
        self.assertEqual(self.guard.revision, revision)
        self.assertFalse(self.source.status()['available'])

    async def test_duplicate_normalized_method_route_rejected(self):
        self.costs['endpoint_costs'].append(dict(method='POST',
            path='/trade-api/v2'+ORDERS, cost=17))
        with self.assertRaises(InvalidData):
            await self.reads.refresh_budget()
        self.assertIsNone(self.source._budget)

    async def test_caller_mutation_cannot_change_installed_costs(self):
        budget = await self.bootstrap()
        self.costs['endpoint_costs'][1]['cost'] = 1
        self.limits['write']['refill_rate'] = 100000
        self.assertEqual(self.reserve(budget).cost, 17)
        self.assertEqual(budget._snapshot.rate, 100)

    async def test_ttl_and_guard_margin_revoke_even_with_cached_caller_clock(self):
        self.limits['grants'] = [dict(exchange_instance='event_contract', level='fixture',
            source='manual', expires_ts=int(BASE.timestamp()+200))]
        budget = await self.bootstrap()
        old_now = self.source.clock_pair()
        permit = self.reserve(budget)
        self.clock.t = 195
        with self.assertRaises(QuotaUnavailable):
            budget.consume(permit, 'POST', ORDERS, shard=0, now=old_now)
        self.assertFalse(self.source.status()['available'])

    async def test_future_caller_clock_cannot_mint_tokens(self):
        await self.reads.refresh_budget()
        budget = self.source.budget
        now = self.source.clock_pair()
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0,
            now=(now[0]+100, now[1]+100)))

    async def test_clock_fault_never_releases_stale_permit(self):
        budget = await self.bootstrap()
        permit = self.reserve(budget)
        self.clock.offset += 3
        with self.assertRaises(QuotaUnavailable):
            budget.consume(permit, 'POST', ORDERS, shard=0, now=self.source.clock_pair())
        self.assertEqual(self.guard.state, 'clock_fault')

    async def test_near_grant_rollover_blocks_write_until_a_new_accepted_pair(self):
        budget = await self.bootstrap()
        self.limits['grants'] = [dict(exchange_instance='event_contract', level='fixture',
            source='manual', expires_ts=int(BASE.timestamp()+60))]
        with self.assertRaises(QuotaRolloverPending):
            await self.reads.refresh_budget()
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))

    async def test_manual_read_lease_install_cannot_forge_write_publication(self):
        budget = await self.bootstrap()
        self.guard.install(candidate(self.guard))
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))

    async def test_public_budget_refresh_cannot_bypass_source(self):
        budget = await self.bootstrap()
        snapshot = WriteQuotaSnapshot(self.limits, self.costs, scope=self.guard.scope,
            epoch=self.guard.epoch, sequence=100, start=self.source.clock_pair(),
            end=self.source.clock_pair(), ttl=300)
        with self.assertRaises(InvalidData):
            budget.refresh(snapshot, now=self.source.clock_pair())

    async def test_replaced_pair_owner_revokes_existing_budget(self):
        budget = await self.bootstrap()
        self.reads.write_quota_source = None
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))
        self.reads.write_quota_source = self.source
        self.assertFalse(self.source.status()['available'])

    async def test_signer_change_is_sticky_stop_even_if_restored(self):
        budget = await self.bootstrap()
        signer = self.reads.signer
        self.reads.signer = Signer()
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))
        self.reads.signer = signer
        with self.assertRaises(QuotaUnavailable):
            await self.reads.refresh_budget()

    async def test_stop_during_pair_never_publishes(self):
        self.hold = True
        task = asyncio.create_task(self.reads.refresh_budget())
        await eventually(self.entered.is_set)
        self.source.stop()
        self.release.set()
        with self.assertRaises(QuotaUnavailable):
            await task
        self.assertFalse(self.source.status()['available'])

    async def test_stop_between_read_install_and_write_publication_blocks(self):
        self.guard.listen(self.source.stop)
        with self.assertRaises(QuotaUnavailable):
            await self.reads.refresh_budget()
        self.assertIsNone(self.source._budget)

    async def test_read_health_failure_revokes_acquired_permit(self):
        budget = await self.bootstrap()
        permit = self.reserve(budget)
        self.reads._health_error = RuntimeError('synthetic health fault')
        with self.assertRaises(QuotaUnavailable):
            budget.consume(permit, 'POST', ORDERS, shard=0, now=self.source.clock_pair())
        self.assertEqual(budget.status(now=self.source.clock_pair()).outstanding, 0)

    async def test_stale_ttl_requires_new_pair_not_clock_relabeling(self):
        budget = await self.bootstrap()
        self.clock.t += 301
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))
        await self.reads.refresh_budget()
        self.assertIs(self.source.budget, budget)
        self.assertIsNone(budget.try_reserve('POST', ORDERS, shard=0, now=self.source.clock_pair()))

    async def test_cancelled_consumer_does_not_detach_pair_from_read_owner(self):
        self.hold = True
        task = asyncio.create_task(self.reads.refresh_budget())
        await eventually(self.entered.is_set)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        owned = self.reads.budget_refresh
        self.assertIsNotNone(owned)
        self.assertFalse(owned.done())
        self.release.set()
        await owned
        self.assertTrue(self.source.status()['available'])
        self.assertEqual(len(self.calls), 2)

    async def test_close_revokes_already_acquired_budget(self):
        budget = await self.bootstrap()
        permit = self.reserve(budget)
        await self.reads.close()
        with self.assertRaises(QuotaUnavailable):
            budget.consume(permit, 'POST', ORDERS, shard=0, now=self.source.clock_pair())

    async def test_existing_supervisor_owns_refresh_without_second_scheduler(self):
        supervisor = QuotaSupervisor(self.reads, jitter=lambda: 0)
        supervisor.step()
        await supervisor.active
        supervisor.step()
        self.assertTrue(self.source.status()['available'])
        self.assertEqual(len(self.calls), 2)
        await supervisor.close()
        self.assertFalse(self.source.status()['available'])


class ObservedDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import test_bot_dispatch_sources as fixtures
        self.fixture = fixtures.DispatchSourceTests()
        await self.fixture.asyncSetUp()
        self.clock, self.reads, self.guard = setup()
        self.source = WriteQuotaSource(self.reads, shards=(0, 1), offline_fixture=True)
        await self.reads.refresh_budget()
        self.clock.t += 1
        self.fixture.dispatcher.budget = self.source.budget
        self.fixture.dispatcher.clock_pair = self.source.clock_pair
        self.fixture.dispatcher.executor.invoke.budget = self.source.budget
        self.fixture.dispatcher.executor.invoke.clock_pair = self.source.clock_pair
        await self.fixture.ready()

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()
        await self.reads.close()

    async def test_observed_quota_reaches_durable_injected_dispatch(self):
        result = await self.fixture.run_priority()
        self.assertEqual(result.state, 'ACK')
        self.assertEqual(len(self.fixture.calls), 1)
        self.assertFalse(result.live_ready)

    async def test_late_429_after_new_pair_pauses_shared_owner_without_more_reads(self):
        from kalshi_bot.mutation_outcomes import MutationHTTPFailure
        budget = self.source.budget
        async def failure(*args):
            await self.reads.refresh_budget()
            raise MutationHTTPFailure(429)
        self.fixture.dispatcher.executor.invoke.invoke = failure
        with self.assertRaises(MutationHTTPFailure):
            await self.fixture.run_priority()
        self.assertIs(self.source.budget, budget)
        self.assertGreater(budget.status(now=self.source.clock_pair()).buckets[0][-1], 0)
        self.assertEqual((await self.fixture.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertTrue(self.fixture.runtime.recovery_requested.is_set())

    async def test_429_pause_ignores_future_caller_time(self):
        budget = self.source.budget
        mono, wall = self.source.clock_pair()
        budget.pause_429(shard=0, seconds=1, now=(mono+100, wall+100))
        self.assertEqual(budget.status(now=self.source.clock_pair()).buckets[0][-1], 1)

    async def test_owner_expiry_during_sending_never_invokes_transport(self):
        original = self.fixture.writer.begin_send
        async def expired(receipt):
            result = await original(receipt)
            self.clock.t += 301
            return result
        self.fixture.writer.begin_send = expired
        with self.assertRaises(QuotaUnavailable):
            await self.fixture.run_priority()
        self.assertFalse(self.fixture.calls)
        self.assertEqual((await self.fixture.writer.mutations())[-1]['phase'], 'UNKNOWN')

    async def test_refresh_during_sending_revokes_old_permit_without_replacing_owner(self):
        original = self.fixture.writer.begin_send
        budget = self.source.budget
        async def refreshed(receipt):
            result = await original(receipt)
            await self.reads.refresh_budget()
            return result
        self.fixture.writer.begin_send = refreshed
        with self.assertRaises(InvalidData):
            await self.fixture.run_priority()
        self.assertIs(self.source.budget, budget)
        self.assertFalse(self.fixture.calls)
        self.assertEqual((await self.fixture.writer.mutations())[-1]['phase'], 'UNKNOWN')
