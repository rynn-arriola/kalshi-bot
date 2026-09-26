"""D-145 Layer 1: Kalshi order groups cap entry fills on the venue side."""
import asyncio
import json
from decimal import Decimal as D
from types import SimpleNamespace
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_bot.dispatch import ENTRY_PAIR, EntryPairCandidate
from kalshi_bot.execution import validate_request
from kalshi_bot.live_session import LiveSession
from kalshi_bot.mutation_transport import OrderMutationTransport
from kalshi_bot.order_groups import (OrderGroups, group_contracts_limit,
                                     validate_group_request)
from kalshi_bot.rest import WireResponse
from kalshi_bot.transport import MutationSigner
from kalshi_bot.values import InvalidData
from kalshi_bot.write_budget import GROUP_CREATE, GROUP_RESET, _operation
import test_bot_entry_dispatch as entry_fixture
from test_bot_command_handoff import request
import test_bot_write_budget as budget_fixture


def create(**changes):
    return dict(dict(subaccount=0, exchange_index=1, contracts_limit=group_contracts_limit()),
                **changes)


class RequestShapeTests(unittest.TestCase):
    def test_limit_is_one_entry_plus_one_contract(self):
        self.assertEqual(group_contracts_limit(), 11)  # Reference profile: 10-contract entries.

    def test_group_requests_are_exact(self):
        validate_group_request('group_create', create())
        validate_group_request('group_reset', dict(order_group_id='og-1', subaccount=0,
                                                   exchange_index=1))
        for kind, value in (('group_create', create(extra=1)),
                            ('group_create', {'subaccount': 0, 'exchange_index': 1}),
                            ('group_reset', dict(order_group_id='og', subaccount=0)),
                            ('group_trigger', create()), ('group_create', [])):
            with self.subTest(kind=kind, value=value), self.assertRaises(InvalidData):
                validate_group_request(kind, value)

    def test_only_passive_entries_may_join_a_group(self):
        entry = request('entry') | {'order_group_id': 'og-1'}
        validate_request('create', entry)
        ioc = request('exit') | dict(order_group_id='og-1', time_in_force='immediate_or_cancel',
                                     post_only=False, reduce_only=True)
        ioc.pop('expiration_time', None)
        with self.assertRaisesRegex(InvalidData, 'passive entries only'):
            validate_request('create', ioc)

    def test_budget_models_exactly_create_and_reset(self):
        self.assertEqual(_operation('POST', GROUP_CREATE)[1], GROUP_CREATE)
        self.assertEqual(_operation('PUT', '/portfolio/order_groups/og-1/reset')[1], GROUP_RESET)
        for method, path in (('PUT', '/portfolio/order_groups/og-1/trigger'),
                             ('DELETE', '/portfolio/order_groups/og-1'),
                             ('PUT', '/portfolio/order_groups/a/b/reset'),
                             ('POST', '/portfolio/order_groups/og-1/reset')):
            with self.subTest(method=method, path=path), self.assertRaises(InvalidData):
                _operation(method, path)


class LiveSessionGroupTests(unittest.TestCase):
    def setUp(self):
        self.session = LiveSession(run_id='groups', tickers=('A',))
        self.session.bind(SimpleNamespace(failed=False))

    def test_group_scope_and_limit_are_checked(self):
        self.session.check('group_create', create())
        self.session.check('group_reset', dict(order_group_id='og', subaccount=0, exchange_index=1))
        for bad in (create(subaccount=1), create(contracts_limit=10), create(contracts_limit=1)):
            with self.subTest(bad=bad), self.assertRaises(InvalidData):
                self.session.check('group_create', bad)

    def test_exits_and_reducers_never_join_a_group(self):
        with self.assertRaisesRegex(InvalidData, 'never join an order group'):
            self.session.check('create', request('exit') | {'order_group_id': 'og'})


class TransportGroupTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.signer = MutationSigner('fixture-key', key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    def transport(self, response):
        calls = []
        def wire(url, method, headers, body, max_bytes, timeout):
            calls.append((url, method, headers, body))
            return response
        return OrderMutationTransport(self.signer, wire=wire, offline_fixture=True), calls

    async def test_create_posts_exact_body_to_create_path(self):
        transport, calls = self.transport(WireResponse(201, b'{"order_group_id":"og-9","subaccount":0}'))
        result = await transport.order_group('group_create', create())
        url, method, headers, body = calls[0]
        self.assertTrue(url.endswith('/portfolio/order_groups/create'))
        self.assertEqual((method, json.loads(body)), ('POST', create()))
        self.assertIn('KALSHI-ACCESS-SIGNATURE', headers)
        self.assertEqual(result['order_group_id'], 'og-9')

    async def test_reset_puts_to_exact_group_with_scope_query_and_empty_reply(self):
        transport, calls = self.transport(WireResponse(200, b''))
        result = await transport.order_group('group_reset',
            dict(order_group_id='og-9', subaccount=0, exchange_index=1))
        url, method, _, body = calls[0]
        self.assertIn('/portfolio/order_groups/og-9/reset?', url)
        self.assertIn('exchange_index=1', url)
        self.assertEqual((method, body, result), ('PUT', b'', {}))

    def test_signer_allows_only_group_create_and_reset(self):
        self.signer.headers('POST', '/trade-api/v2/portfolio/order_groups/create')
        self.signer.headers('PUT', '/trade-api/v2/portfolio/order_groups/og/reset?subaccount=0')
        for method, path in (('PUT', '/trade-api/v2/portfolio/order_groups/og/trigger'),
                             ('DELETE', '/trade-api/v2/portfolio/order_groups/og'),
                             ('PUT', '/trade-api/v2/portfolio/order_groups/og/limit'),
                             ('POST', '/trade-api/v2/portfolio/order_groups/og/reset'),
                             ('PUT', '/trade-api/v2/portfolio/order_groups//reset'),
                             ('PUT', '/trade-api/v2/portfolio/order_groups/a/b/reset')):
            with self.subTest(method=method, path=path), self.assertRaises(InvalidData):
                self.signer.headers(method, path)


class FakeTransport:
    def __init__(self):
        self.calls, self.fail, self.ids = [], None, iter(f'og-{n}' for n in range(100))

    async def order_group(self, kind, request):
        self.calls.append((kind, request))
        if self.fail is not None:
            raise self.fail
        return {'order_group_id': next(self.ids), 'subaccount': 0} if kind == 'group_create' else {}


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mono = 1000.0
        self.events, self.recoveries = [], []
        self.plans = {}
        self.report = SimpleNamespace(positions_match=True, audit=SimpleNamespace(blockers=()),
                                      snapshot=SimpleNamespace(positions=()))
        budget = budget_fixture.budget(budget_fixture.snapshot(rate=1000, capacity=1000), shards=(0, 1))
        dispatcher = SimpleNamespace(budget=budget, clock_pair=lambda: budget_fixture.now(1))
        self.r = SimpleNamespace(
            clock=lambda: self.mono, now=lambda: None, stop_requested=asyncio.Event(),
            account=SimpleNamespace(generation=1, subaccount=0, connected=True,
                                    current_report=lambda _now: self.report),
            diagnostics=SimpleNamespace(emit=lambda name, **kw: self.events.append(name)),
            request_recovery=self.recoveries.append, entry_allowed=True,
            dispatch_supervisor=SimpleNamespace(dispatcher=dispatcher),
            management=SimpleNamespace(current=lambda t, require_market=False: self.plans.get(t)))
        self.t = FakeTransport()
        self.g = OrderGroups(self.r, self.t, shards=(0, 1))

    async def trigger(self, shard=1):
        await self.g.tick()
        group = self.g.group_for(shard)
        self.g.on_update(dict(event_type='triggered', order_group_id=group, ts_ms=1))
        return group

    async def test_creates_one_group_per_shard_then_entries_may_join(self):
        self.assertIsNone(self.g.group_for(1))  # Fail closed before creation.
        await self.g.tick()
        self.assertEqual([k for k, _ in self.t.calls], ['group_create']*2)
        self.assertEqual({self.g.group_for(0), self.g.group_for(1)}, {'og-0', 'og-1'})
        self.assertEqual(self.t.calls[0][1]['contracts_limit'], group_contracts_limit())
        await self.g.tick()
        self.assertEqual(len(self.t.calls), 2)  # Never re-created while active.

    async def test_create_failure_fails_closed_and_retries_on_schedule(self):
        self.t.fail = OSError('down')
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))
        self.t.fail = None
        self.mono += 29
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))
        self.mono += 1
        await self.g.tick()
        self.assertIsNotNone(self.g.group_for(1))
        self.assertIn('order_group_failed', self.events)

    async def test_retry_schedule_backs_off_to_five_minutes(self):
        self.t.fail = OSError('down')
        waits = []
        for _ in range(5):
            await self.g.tick()
            waits.append(self.g.groups[1].next_attempt-self.mono)
            self.mono = self.g.groups[1].next_attempt
        self.assertEqual(waits, [30, 60, 120, 300, 300])

    async def test_busy_write_budget_is_not_a_failure(self):
        self.r.dispatch_supervisor.dispatcher.budget = SimpleNamespace(
            try_reserve=lambda *a, **k: None)
        await self.g.tick()
        self.assertEqual((self.t.calls, self.g.failures), ([], 0))

    async def test_trigger_blocks_entries_and_requests_recovery(self):
        await self.trigger()
        self.assertIsNone(self.g.group_for(1))
        self.assertIsNotNone(self.g.group_for(0))  # Other shard keeps trading.
        self.assertEqual(self.recoveries, ['order_group_triggered'])
        self.assertIn('order_group_triggered', self.events)

    async def test_reset_waits_for_settle_recovery_and_exit_plans(self):
        group = await self.trigger()
        self.mono += 60
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))  # No full recovery since the trigger.
        self.r.last_full_recovery_mono = self.mono
        self.plans['X'] = SimpleNamespace(exit=SimpleNamespace(mode='blocked'))
        self.report.snapshot.positions = (SimpleNamespace(ticker='X', quantity=D(30)),)
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))  # A position without a usable exit plan.
        self.plans['X'] = SimpleNamespace(exit=SimpleNamespace(mode='passive'))
        self.r.entry_allowed = False
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))
        self.r.entry_allowed = True
        await self.g.tick()
        self.assertEqual(self.g.group_for(1), group)
        self.assertEqual(self.t.calls[-1], ('group_reset', dict(order_group_id=group,
                                                               subaccount=0, exchange_index=1)))

    async def test_reset_never_before_the_settle_period(self):
        await self.trigger()
        self.r.last_full_recovery_mono = self.mono+1
        self.mono += 59
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))
        self.mono += 1
        await self.g.tick()
        self.assertIsNotNone(self.g.group_for(1))

    async def test_a_recovery_before_the_trigger_does_not_count(self):
        self.r.last_full_recovery_mono = self.mono
        await self.trigger()
        self.mono += 120
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))

    async def test_new_private_stream_generation_abandons_and_recreates(self):
        await self.g.tick()
        old = self.g.group_for(1)
        self.r.account.generation = 2
        self.assertIsNone(self.g.group_for(1))  # Missed updates: never trust the old group.
        await self.g.tick()
        self.assertNotIn(self.g.group_for(1), (None, old))

    async def test_unknown_or_malformed_updates_change_nothing(self):
        await self.g.tick()
        for msg in (dict(event_type='triggered', order_group_id='someone-else'),
                    dict(event_type='exploded', order_group_id=self.g.group_for(1)),
                    dict(order_group_id=self.g.group_for(1)), {}):
            self.g.on_update(msg)
        self.assertIsNotNone(self.g.group_for(1))
        self.assertEqual(self.g.unknown_updates, 4)

    async def test_deleted_group_is_recreated(self):
        await self.g.tick()
        self.g.on_update(dict(event_type='deleted', order_group_id=self.g.group_for(1)))
        self.assertIsNone(self.g.group_for(1))
        await self.g.tick()
        self.assertIsNotNone(self.g.group_for(1))

    async def test_group_created_during_stream_change_is_not_used(self):
        async def racing(kind, request):
            self.r.account.generation += 1
            return {'order_group_id': 'og-race', 'subaccount': 0}
        self.t.order_group = racing
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))
        self.assertEqual((self.g.groups[1].state, self.g.creates), ('missing', 0))

    async def test_group_outside_account_scope_is_rejected(self):
        async def foreign(kind, request):
            return {'order_group_id': 'og-x', 'subaccount': 3}
        self.t.order_group = foreign
        await self.g.tick()
        self.assertIsNone(self.g.group_for(1))
        self.assertGreaterEqual(self.g.failures, 1)


class PrivateStreamRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_group_updates_reach_the_manager(self):
        from kalshi_bot.runtime import RecoveryRuntime
        seen = []
        async def on_event(event, **_):
            return None
        runtime = SimpleNamespace(account_lock=asyncio.Lock(),
            account=SimpleNamespace(generation=1, connected=True, on_event=on_event),
            order_groups=SimpleNamespace(on_update=seen.append),
            now=lambda: None, _resume_risk_drain=lambda: None)
        msg = dict(event_type='triggered', order_group_id='og-1', ts_ms=1)
        await RecoveryRuntime._private(runtime, dict(type='order_group_updates', sid=1, seq=1,
                                                     msg=msg), 1)
        self.assertEqual(seen, [msg])


class EntryJoinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = entry_fixture.EntrySourceTests('test_ranked_market_becomes_exact_source_bound_pair')
        await self.f.asyncSetUp()

    async def asyncTearDown(self):
        await self.f.asyncTearDown()

    async def test_entries_join_the_shard_group_or_are_not_placed(self):
        self.f.runtime.order_groups = SimpleNamespace(group_for=lambda shard: None)
        self.assertIsNone(await self.f.source.refresh('A', ENTRY_PAIR))
        self.assertEqual(self.f.source.last_entry_block['reason'], 'entry_order_group_unavailable')
        self.f.runtime.order_groups = SimpleNamespace(
            group_for=lambda shard: f'og-shard-{shard}')
        candidate = await self.f.source.refresh('A', ENTRY_PAIR)
        self.assertIsInstance(candidate, EntryPairCandidate)
        self.assertEqual({r['order_group_id'] for r in candidate.requests}, {'og-shard-1'})
        prepared = await self.f.writer.reserve_entry_pair(candidate.requests,
            batch_id=candidate.batch_id, view=candidate.view,
            config=entry_fixture.BotConfig(), now=entry_fixture.NOW, free_cash=candidate.free_cash,
            account_known=True, offline_fixture=True,
            fee_per_contract_bound=candidate.fee_per_contract_bound)
        self.assertTrue(prepared.reserved, prepared.blockers)
        await self.f.writer.abort_batch(prepared.batch)


if __name__ == '__main__':
    unittest.main()
