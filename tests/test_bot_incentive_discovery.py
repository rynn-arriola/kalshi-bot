"""Synthetic shared reads, actual runtime/selection, disposable ledger only."""
import asyncio
from datetime import timedelta
import json
from threading import Event
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from kalshi_bot.incentive_discovery import QUERY
from kalshi_bot.rest import PageSet, RestReads, TokenBudget, WireResponse
from kalshi_bot.values import InvalidData
import test_bot_selection as fixtures


def row(ticker='A', pid='p', **changes):
    result = dict(id=pid, market_ticker=ticker, incentive_type='liquidity',
        start_date=(fixtures.NOW-timedelta(hours=1)).isoformat(),
        end_date=(fixtures.NOW+timedelta(hours=1)).isoformat(),
        target_size_fp='1000', discount_factor_bps=5000, period_reward=5000000, paid_out=False)
    result.update(changes)
    return result


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.001)


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = fixtures.RuntimeSelectionTests()
        await self.f.asyncSetUp()
        self.r, self.s = self.f.r, self.f.s
        self.pages = [dict(incentive_programs=[row()], next_cursor='')]
        self.calls = []
        def wire(url, headers, size):
            self.calls.append((url, dict(headers)))
            query = parse_qs(urlparse(url).query)
            index = int(query.get('cursor', ['0'])[0])
            return WireResponse(200, json.dumps(self.pages[index]).encode())
        self.reads = RestReads(TokenBudget(rate=10000, capacity=10000, default_cost=1,
                               clock=self.r.clock), wire=wire)
        self.r.reads = self.reads
        self.d = self.r.attach_incentives(offline_fixture=True)
        self.tasks = []
        self.release = Event()

    async def asyncTearDown(self):
        self.release.set()
        self.r.stop()
        await self.d.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.reads.close()
        await self.f.asyncTearDown()

    def advance(self, seconds):
        self.f.mono += seconds
        self.f.now += timedelta(seconds=seconds)

    async def refresh(self):
        self.d.step()
        self.assertIsNotNone(self.d.active)
        await asyncio.wait((self.d.active,))
        self.d.step()

    async def test_complete_catalog_reaches_actual_engine_selection(self):
        self.assertFalse(self.s.current('A'))
        await self.refresh()
        await self.r.engine.step()
        self.assertTrue(self.s.current('A'))
        self.assertTrue((await self.s.propose(window=self.f.w, free_cash=500)).additions)
        query = parse_qs(urlparse(self.calls[0][0]).query)
        self.assertEqual(query, dict(limit=['1000'], status=['active'], type=['liquidity']))
        self.assertFalse(any('ACCESS' in key for _, headers in self.calls for key in headers))
        self.assertEqual(self.reads.budget.spent, 1)
        self.assertFalse(self.d.status()['authorized'])
        self.assertFalse(self.s.programs)
        with self.assertRaises(InvalidData): self.f.publish()

    async def test_two_pages_all_markets_and_immutable_observations(self):
        self.pages = [dict(incentive_programs=[row()], next_cursor='1'),
                      dict(incentive_programs=[row('B','p2')])]
        await self.refresh()
        value = self.d.current()
        self.assertEqual(set(value.observations), {'A','B'})
        self.assertEqual((value.pages,value.rows,len(self.calls)), (2,2,2))
        with self.assertRaises(TypeError): value.observations['C'] = None
        self.assertEqual(set(self.r.engine.market_shard), {'A'})  # No subscription mutation.

    async def test_five_thousand_rows_use_five_bounded_pages(self):
        self.pages = [dict(incentive_programs=[row(f'M{i}', f'p{i}')
            for i in range(offset, offset+1000)],
            next_cursor=str(offset//1000+1) if offset < 4000 else '')
            for offset in range(0, 5000, 1000)]
        await self.refresh()
        self.assertEqual((self.d.current().rows, self.d.current().pages), (5000, 5))
        self.assertEqual(len(self.calls), 5)
        self.assertTrue(all(parse_qs(urlparse(url).query)['limit'] == ['1000']
                            for url, _ in self.calls))
        self.assertTrue(all(len(json.dumps(page).encode()) < self.reads.max_bytes
                            for page in self.pages))

    async def test_enlarged_page_still_rejects_response_byte_overflow(self):
        self.pages[0]['padding'] = 'x' * (2*1024*1024)
        await self.refresh()
        self.assertIsNone(self.d.current())
        self.assertEqual(self.d.failures, 1)

    async def test_empty_complete_refresh_revokes_prior_catalog_and_scores(self):
        await self.refresh()
        await self.r.engine.step()
        self.pages = [dict(incentive_programs=[])]
        self.d.request()
        self.assertFalse(self.s.current('A'))
        self.advance(1)
        await self.refresh()
        self.assertEqual(self.d.completed, 2)
        self.assertFalse(self.d.current().observations)

    async def test_partial_pagination_never_publishes(self):
        self.pages = [dict(incentive_programs=[row()], next_cursor='1'),
                      dict(incentive_programs=[row('B','p2')], next_cursor='1')]
        await self.refresh()
        self.assertIsNone(self.d.current())
        self.assertEqual(self.d.failures, 1)

    async def test_duplicate_identity_even_identical_rejects_enumeration(self):
        self.pages[0]['incentive_programs'] = [row(), row()]
        await self.refresh()
        self.assertEqual(self.d.failures, 1)
        self.assertIsNone(self.d.current())

    async def test_scope_conflict_or_missing_identity_rejects_catalog(self):
        for bad in (row(incentive_type='volume'), row(market_ticker=''), row(id=None)):
            self.pages[0]['incentive_programs'] = [row('B','b'), bad]
            self.d.request(retry=True)
            self.advance(10)
            await self.refresh()
            self.assertIsNone(self.d.current())

    async def test_unsupported_program_excludes_whole_market_not_good_peers(self):
        self.pages[0]['incentive_programs'] = [row('A','a1'), row('A','a2',target_size_fp=None),
                                              row('A','a3'), row('B','b')]
        await self.refresh()
        value = self.d.current()
        self.assertEqual(set(value.observations), {'B'})
        self.assertEqual(value.excluded, {'A'})
        self.assertFalse(self.s.current('A'))

    async def test_program_bound_excludes_without_truncating_market(self):
        self.pages[0]['incentive_programs'] = [row(pid=str(i)) for i in range(17)]+[row('B','b')]
        await self.refresh()
        self.assertEqual(set(self.d.current().observations), {'B'})
        self.assertEqual(self.d.current().excluded, {'A'})

    async def test_inactive_and_paid_programs_do_not_enter_selection(self):
        self.pages[0]['incentive_programs'] = [row('A','paid',paid_out=True),
            row('B','future', start_date=(fixtures.NOW+timedelta(minutes=1)).isoformat()),
            row('C','ended',end_date=fixtures.NOW.isoformat())]
        await self.refresh()
        self.assertFalse(self.d.current().observations)

    async def test_age_starts_before_read_and_exact_expiry_revokes(self):
        original = self.reads.collect
        async def slow(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.advance(20)
            return result
        with patch.object(self.reads,'collect',side_effect=slow): await self.refresh()
        self.assertEqual(self.d.current().observed_at, fixtures.NOW)
        self.advance(280)
        self.assertIsNone(self.d.current())
        self.assertFalse(self.s.status()['current_markets'])

    async def test_generation_change_during_read_and_after_completion(self):
        original = self.reads.collect
        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.d.request()
            return result
        with patch.object(self.reads,'collect',side_effect=changed): await self.refresh()
        self.assertIsNone(self.d.current())
        self.advance(1)
        self.d.step()
        await asyncio.wait((self.d.active,))
        self.d.request()
        self.d.step()
        self.assertIsNone(self.d.current())

    async def test_expiry_before_result_consumption_does_not_publish(self):
        self.d.step()
        await asyncio.wait((self.d.active,))
        self.advance(300)
        self.d.step()
        self.assertIsNone(self.d.current())
        self.assertEqual(self.d.completed, 0)

    async def test_bounded_retry_exhaustion_and_explicit_retry_keep_cooldown(self):
        self.pages[0]['incentive_programs'] = [row(id=None)]
        for _ in range(3):
            await self.refresh()
            self.advance(2)
        self.assertTrue(self.d.exhausted)
        self.assertFalse(self.d.request())
        self.pages[0]['incentive_programs'] = [row()]
        self.d.request(retry=True)
        self.d.step()
        self.assertIsNone(self.d.active)
        self.advance(2)
        await self.refresh()
        self.assertIsNotNone(self.d.current())

    async def test_exhaustion_heals_after_the_cooldown(self):
        """Finding 218: a burst of failures pauses the catalog; it never ends
        entries until a restart."""
        self.pages[0]['incentive_programs'] = [row(id=None)]
        for _ in range(3):
            await self.refresh()
            self.advance(2)
        self.assertTrue(self.d.exhausted)
        self.pages[0]['incentive_programs'] = [row()]
        self.advance(self.d.EXHAUSTED_COOLDOWN_SECONDS-10)
        self.d.step()
        self.assertTrue(self.d.exhausted)
        self.assertIsNone(self.d.active)
        self.advance(10)
        await self.refresh()
        self.assertFalse(self.d.exhausted)
        self.assertIsNotNone(self.d.current())
        self.assertEqual(self.d.status()['cooldown_retries'], 1)

    async def test_a_second_exhaustion_waits_another_full_cooldown(self):
        self.pages[0]['incentive_programs'] = [row(id=None)]
        for _ in range(3):
            await self.refresh()
            self.advance(2)
        self.advance(self.d.EXHAUSTED_COOLDOWN_SECONDS)
        for _ in range(3):
            await self.refresh()
            self.advance(2)
        self.assertTrue(self.d.exhausted)
        self.advance(self.d.EXHAUSTED_COOLDOWN_SECONDS-10)
        self.d.step()
        self.assertTrue(self.d.exhausted)
        self.assertEqual(self.d.cooldown_retries, 1)

    async def test_quota_hold_does_not_spend_retry_budget(self):
        from kalshi_bot.quota import QuotaUnavailable
        with patch.object(self.reads,'collect',side_effect=QuotaUnavailable('fixture')):
            await self.refresh()
        self.assertEqual(self.d.failures, 0)
        self.assertIsNone(self.d.current())

    async def test_each_attempt_uses_a_new_wire_observation_scope(self):
        original = self.reads.collect
        scopes = []
        async def record(*args, **kwargs):
            scopes.append(kwargs.get('coalesce_scope'))
            return await original(*args, **kwargs)
        with patch.object(self.reads,'collect',side_effect=record):
            await self.refresh()
            self.d.request()
            self.advance(1)
            await self.refresh()
        self.assertIsNotNone(scopes[0])
        self.assertIsNot(scopes[0], scopes[1])

    async def test_content_digest_changes_only_with_program_semantics(self):
        self.pages[0]['incentive_programs'] = [row('A','a'), row('B','b')]
        await self.refresh()
        first = self.d.current()
        self.pages[0]['incentive_programs'].reverse()
        self.d.request()
        self.advance(1)
        await self.refresh()
        second = self.d.current()
        self.assertEqual(first.content_digest, second.content_digest)
        self.assertEqual(first.market_digests, second.market_digests)
        self.assertNotEqual(first.observed_mono, second.observed_mono)
        self.pages[0]['incentive_programs'] = [row('A','a',period_reward=5000001),
                                               row('B','b')]
        self.d.request()
        self.advance(1)
        await self.refresh()
        self.assertNotEqual(second.content_digest, self.d.current().content_digest)
        self.assertNotEqual(second.market_digests['A'], self.d.current().market_digests['A'])
        self.assertEqual(second.market_digests['B'], self.d.current().market_digests['B'])

    async def test_quota_loss_before_publication_or_consumption_revokes(self):
        class Guard:
            fresh = True
            def poll(self): return self.fresh
        guard = Guard()
        self.d.quota = guard
        self.d.step()
        await asyncio.wait((self.d.active,))
        guard.fresh = False
        self.d.step()
        self.assertIsNone(self.d.current())
        self.assertEqual(self.d.completed, 0)
        guard.fresh = True
        self.advance(1)
        await self.refresh()
        self.assertIsNotNone(self.d.current())
        guard.fresh = False
        self.assertIsNone(self.d.current())

    async def test_refresh_invalidates_only_selection_not_inventory_or_risk(self):
        await self.refresh()
        await self.r.engine.step()
        plan = self.r.management.current('A')
        revision = self.r.writer.revision
        self.d.request()
        self.assertIs(self.r.management.current('A'), plan)
        self.assertEqual(self.r.writer.revision, revision)
        self.assertFalse(self.s.current('A'))

    async def test_account_recovery_defers_and_requests_coalesce(self):
        self.r.recovery_state = 'recovering'
        for _ in range(100): self.d.request()
        self.d.step()
        self.assertEqual(self.d.started, 0)
        self.r.recovery_state = 'idle'
        await self.refresh()
        self.assertEqual(self.d.started, 1)
        for _ in range(10): self.d.step()
        self.assertEqual(len(self.calls), 1)

    async def test_clock_discontinuity_is_sticky_and_revokes(self):
        await self.refresh()
        self.f.now += timedelta(seconds=10)
        self.assertIsNone(self.d.current())
        self.assertTrue(self.d.failed)
        self.assertFalse(self.d.request(retry=True))
        with self.assertRaises(InvalidData): self.d.step()

    async def test_validation_of_complete_enumeration_provenance_and_bounds(self):
        invalid = [PageSet((row(),),1,100,'wrong',QUERY,True),
            PageSet((row(),),1,100,'incentives',(),True),
            PageSet((row(),),1,100,'incentives',QUERY,False),
            PageSet((row(),),101,100,'incentives',QUERY,True),
            PageSet((row(),),1,8388609,'incentives',QUERY,True),
            PageSet((row(),)*10001,1,100,'incentives',QUERY,True)]
        for pages in invalid:
            with patch.object(self.reads,'collect',return_value=pages):
                self.d.request(retry=True)
                self.advance(30)
                await self.refresh()
                self.assertIsNone(self.d.current())

    async def test_attachment_guards_and_no_construction_io(self):
        self.assertFalse(self.calls)
        with self.assertRaises(InvalidData): self.r.attach_incentives(offline_fixture=True)
        from kalshi_bot.incentive_discovery import IncentiveDiscovery
        with self.assertRaises(InvalidData): IncentiveDiscovery(self.r)

    async def test_stop_keeps_shared_wire_ownership_and_blocks_late_publication(self):
        entered = Event()
        def held(*args):
            entered.set()
            self.release.wait(3)
            return WireResponse(200,json.dumps(self.pages[0]).encode())
        self.reads.wire = held
        self.d.step()
        await until(entered.is_set)
        self.d.stop()
        await self.d.close()
        self.assertIsNone(self.d.current())
        self.assertTrue(self.reads.inflight)  # The shared owner retains its wire call.
        close = asyncio.create_task(self.reads.close())
        self.tasks.append(close)
        await asyncio.sleep(.02)
        self.assertFalse(close.done())
        self.release.set()
        await close
        self.assertFalse(self.reads.inflight)

    async def test_unexpected_error_escapes_service_and_revokes(self):
        with patch.object(self.reads,'collect',side_effect=RuntimeError('synthetic')):
            task = asyncio.create_task(self.d.run())
            self.tasks.append(task)
            with self.assertRaises(RuntimeError): await task
        self.assertTrue(self.d.failed)
        self.assertFalse(self.d.running)
        self.assertIsNone(self.d.current())

    async def start_runtime(self):
        async def parked(*args): await asyncio.Event().wait()
        self.r._recover = self.r._connection = parked
        task = asyncio.create_task(self.r.run())
        self.tasks.append(task)
        await until(lambda: self.d.completed or task.done())
        if task.done(): task.result()
        return task

    async def test_runtime_owns_service_start_stop_and_no_reuse(self):
        task = await self.start_runtime()
        self.assertTrue(self.d.running)
        self.r.stop()
        await task
        self.assertFalse(self.d.running)
        self.assertIsNone(self.d.active)
        self.assertIsNone(self.d.current())
        with self.assertRaises(InvalidData): await self.d.run()

    async def test_unexpected_service_exit_fails_runtime(self):
        task = await self.start_runtime()
        self.d.stop()
        with self.assertRaisesRegex(InvalidData,'ended without runtime stop'): await task
        self.assertFalse(self.r.running)

    async def test_catalog_change_during_portfolio_await_invalidates_candidate(self):
        await self.refresh()
        await self.r.engine.step()
        original = self.r.risk_view
        async def changed():
            result = await original()
            self.d.request()
            return result
        self.r.risk_view = changed
        self.assertFalse((await self.s.propose(window=self.f.w,free_cash=500)).additions)


if __name__ == '__main__': unittest.main()
