"""Production execution mode, exclusively synthetic inputs/wires/credentials."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import time
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_bot.config import BotConfig
from kalshi_bot.command_types import CommandDenied
from kalshi_bot.dispatch import ENTRY_PAIR, PASSIVE_REDUCER, SAFETY_CANCEL, DUE_IOC
from kalshi_bot.dispatch_sources import InventoryDispatchSource
from kalshi_bot.live import LaunchInputs, compose, initial_scope, verified_flat
from kalshi_bot.live_session import LiveSession, permits
from kalshi_bot.mutation_transport import OrderMutationTransport
from kalshi_bot.observability import NO_LOG
from kalshi_bot.rest import WireResponse
from kalshi_bot.rest import RestReads, TokenBudget
from kalshi_bot.quota import QuotaGuard, QuotaPolicy, ProbeConfig
from kalshi_bot.quota_supervisor import QuotaSupervisor
from kalshi_bot.risk import WindowState, window_bounds
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot import startup
from kalshi_bot.startup import read_text_shared, save_result
from kalshi_bot.transport import MutationSigner
from kalshi_bot.values import InvalidData
from kalshi_bot.write_budget import WriteBudget
from kalshi_bot.writer import LedgerWriter
import test_bot_account_release as accounting_fixture
import test_bot_dispatch_sources as exit_fixture
from test_bot_entry_dispatch import pair
from test_bot_selection import program, terms
from test_bot_write_budget import snapshot as quota_snapshot, now as quota_now


async def noop(*_):
    pass


class LiveEntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = LiveSession(run_id='synthetic-live', tickers=('A',))
        self.f = accounting_fixture.AccountReleaseTests()
        with patch.object(accounting_fixture, 'LedgerWriter',
                          lambda path: LedgerWriter(path, live_session=self.session)):
            await self.f.asyncSetUp()
        f = self.f
        self.runtime = RecoveryRuntime(f.writer, None, None, tickers=('A',),
            subaccount=0, history_start=accounting_fixture.BOUNDARY,
            now=lambda: f.now, clock=lambda: f.tick,
            evaluate=noop, deadline_handler=noop, lifecycle_handler=noop)
        self.runtime.account = f.account
        self.runtime.engine.begin_private_epoch()
        self.selection = self.runtime.attach_selection()
        current_terms = replace(terms(), observed_at=f.now,
            valid_until=f.now+timedelta(minutes=30), close_at=f.now+timedelta(hours=4),
            event_risk_at=f.now+timedelta(hours=2))
        self.runtime.management.set_terms(current_terms)
        self.selection.set_programs('A', (replace(program(pool_centicents=5000000),
            start=f.now-timedelta(hours=1), end=f.now+timedelta(hours=1)),),
            observed_at=f.now, valid_until=f.now+timedelta(minutes=5))
        name = next(iter(self.runtime.engine.shards))
        generation = self.runtime.engine.begin_book_epoch(name)
        self.runtime.engine.submit_book(name, dict(type='orderbook_snapshot', sid=1, seq=1,
            msg=dict(market_ticker='A', yes_dollars_fp=[['.5','1000']],
                     no_dollars_fp=[['.6','1000']])), generation=generation)
        await self.runtime.engine.step()
        market = SimpleNamespace(value=SimpleNamespace(exchange=1))
        self.runtime.market_inputs = SimpleNamespace(values={('market','A'):market},
            results={'A':SimpleNamespace(terms=current_terms)}, _fresh=lambda row: row is market)
        self.runtime.accounting_result = await f.ready()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signer = MutationSigner('synthetic', key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.calls = []
        def wire(url, method, headers, body, *_):
            rows = json.loads(body)['orders']
            self.calls.append((method, rows))
            return WireResponse(201, json.dumps({'orders':[dict(order_id='order-'+r['side'],
                client_order_id=r['client_order_id'], fill_count='0', remaining_count='10',
                ts_ms=1) for r in rows]}).encode())
        self.transport = OrderMutationTransport(signer, wire=wire, activation=self.session)
        self.source = InventoryDispatchSource(self.runtime)
        self.budget = WriteBudget(quota_snapshot(rate=100, capacity=100), shards=(0,1),
            now=quota_now(), live_session=self.session)
        self.dispatcher = self.source.dispatcher(self.budget, invoke=self.transport,
                                                 clock_pair=lambda: quota_now(1))
        self.service = self.runtime.attach_dispatch(self.source, self.dispatcher)

    async def asyncTearDown(self):
        await self.service.close()
        self.session.close()
        await self.f.asyncTearDown()

    async def test_nonfixture_ranked_pair_uses_real_accounting_and_transport(self):
        self.assertTrue(self.runtime.entry_allowed)
        self.dispatcher.submit('A', ENTRY_PAIR)
        result = await self.dispatcher.run_one()
        self.assertEqual(result.state, 'ACK', result.blockers)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual({r['side'] for r in self.calls[0][1]}, {'bid','ask'})
        self.assertTrue(all(D(r['count'])==10 and r['post_only'] for r in self.calls[0][1]))
        self.assertTrue(all(r['expiration_time'] == int(
            (self.f.now+timedelta(hours=1)).timestamp()) for r in self.calls[0][1]))
        self.assertEqual({r['phase'] for r in await self.f.writer.mutations()}, {'ACK'})
        evidence = self.selection.status()['dispatch_selection_evidence']
        self.assertEqual(len(evidence),1)
        self.assertEqual((evidence[0]['ticker'],evidence[0]['state'],evidence[0]['tier']),
                         ('A','ACK','priority'))
        self.assertEqual(set(evidence[0]['order_ids']),set(result.order_ids))
        self.assertEqual(len(evidence[0]['client_order_ids']),2)
        self.assertFalse(self.runtime.entry_allowed)  # outcome revokes account lease

    async def test_reward_revocation_after_reservation_never_reaches_transport(self):
        original = self.f.writer.reserve_entry_pair
        async def revoke_after_reservation(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.selection.set_programs('A', (), observed_at=self.f.now,
                valid_until=self.f.now+timedelta(minutes=5))
            return result
        self.f.writer.reserve_entry_pair = revoke_after_reservation
        self.dispatcher.submit('A', ENTRY_PAIR)
        result = await self.dispatcher.run_one()
        self.assertEqual(result.state, 'BLOCKED')
        self.assertFalse(self.calls)
        self.assertEqual({row['phase'] for row in await self.f.writer.mutations()},
                         {'NOT_SENT'})
        self.assertFalse(self.selection.status()['dispatch_selection_evidence'])

    async def test_reward_revocation_after_sending_never_reaches_transport(self):
        original = self.f.writer.begin_batch_send
        async def revoke_after_sending(batch):
            result = await original(batch)
            self.selection.set_programs('A', (), observed_at=self.f.now,
                valid_until=self.f.now+timedelta(minutes=5))
            return result
        self.f.writer.begin_batch_send = revoke_after_sending
        self.dispatcher.submit('A', ENTRY_PAIR)
        result = await self.dispatcher.run_one()
        self.assertEqual((result.state, result.blockers),
                         ('BLOCKED', ('proof_changed_before_submission',)))
        self.assertFalse(self.calls)
        self.assertEqual({row['phase'] for row in await self.f.writer.mutations()},
                         {'NOT_SENT'})

    async def test_entry_selection_expiry_after_reservation_never_reaches_transport(self):
        original = self.f.writer.reserve_entry_pair
        async def expire_after_reservation(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.f.now += timedelta(seconds=5)
            self.f.tick += 5
            return result
        self.f.writer.reserve_entry_pair = expire_after_reservation
        self.dispatcher.submit('A', ENTRY_PAIR)
        result = await self.dispatcher.run_one()
        self.assertEqual(result.state, 'BLOCKED')
        self.assertFalse(self.calls)

    async def test_session_does_not_replace_accounting_lease(self):
        self.f.account.revoke_accounting()
        self.dispatcher.submit('A', ENTRY_PAIR)
        self.assertEqual((await self.dispatcher.run_one()).state, 'BLOCKED')
        self.assertFalse(self.calls)

    async def test_explicit_metadata_blocker_cannot_be_dropped_by_dispatch(self):
        self.runtime.market_inputs.results['A'].blockers = ('timing_review_conflict',)
        self.dispatcher.submit('A', ENTRY_PAIR)
        self.assertEqual((await self.dispatcher.run_one()).state, 'BLOCKED')
        self.assertFalse(self.calls)

    async def test_startup_scope_keeps_later_admitted_durable_owner(self):
        import test_bot_market_inputs as metadata
        self.session.tickers = frozenset(('A','B','C'))
        reviews = tuple(metadata.review(metadata.market(t)) for t in ('A','B','C'))
        inputs = LaunchInputs(reviews, None, (0,1), ('A',))
        self.assertEqual(await initial_scope(self.f.writer, inputs, self.f.now), ('A',))
        request = pair()[0] | {'ticker':'B'}
        await self.f.writer.reserve_intent(request['client_order_id'], request, self.f.now)
        self.assertEqual(await initial_scope(self.f.writer, inputs, self.f.now), ('A','B'))
        await self.f.writer.transition_intent(request['client_order_id'], 'SENDING')
        # The ambiguous send remains a protected owner and blocks entry through
        # portfolio state; it does not require every reviewed candidate book.
        self.assertEqual(await initial_scope(self.f.writer, inputs, self.f.now), ('A','B'))
        self.session.tickers = frozenset(('A',))
        with self.assertRaises(InvalidData):
            await initial_scope(self.f.writer, LaunchInputs(reviews[:1], None, (0,1)), self.f.now)

    async def test_startup_scope_drops_optional_seed_for_rotated_owner(self):
        import test_bot_market_inputs as metadata
        tickers = tuple(f'M{i:03}' for i in range(129))
        self.session.tickers = frozenset(tickers)
        self.f.writer.market_capacity = 128
        reviews = tuple(metadata.review(metadata.market(t)) for t in tickers)
        inputs = LaunchInputs(reviews, None, (0,1), tickers[:128])
        request = pair()[0] | {'ticker':tickers[-1]}
        await self.f.writer.reserve_intent(request['client_order_id'], request, self.f.now)
        scope = await initial_scope(self.f.writer, inputs, self.f.now)
        self.assertEqual(len(scope), 128)
        self.assertIn(tickers[-1], scope)
        self.assertNotIn(tickers[127], scope)
        await self.f.writer.transition_intent(request['client_order_id'], 'SENDING')
        self.assertEqual(await initial_scope(self.f.writer, inputs, self.f.now), scope)

    async def test_release_keeps_original_account_age_and_rebases_only_own_audit(self):
        report = self.f.account.current_report(self.f.now)
        self.assertIsNotNone(report)
        self.assertEqual(report.observed_at, self.f.report.observed_at)
        self.assertEqual(report.audit.writer_revision, self.f.writer.revision)
        self.assertIs(report.audit, self.runtime.accounting_result.audit)
        self.f.tick += 6
        self.f.now += timedelta(seconds=6)
        self.assertIsNone(self.f.account.current_report(self.f.now))
        self.assertFalse(self.runtime.entry_allowed)

    async def test_flat_proof_rejects_writer_change_during_await(self):
        self.runtime.last_reports = ('synthetic-complete-history',)
        self.assertTrue(await verified_flat(self.runtime))
        original = self.f.writer.inventory
        async def changed():
            value = await original()
            await self.f.writer.observe(self.f.now)
            return value
        with patch.object(self.f.writer, 'inventory', changed):
            self.assertFalse(await verified_flat(self.runtime))

    async def test_flat_proof_waits_for_queued_and_inflight_recovery(self):
        self.runtime.last_reports = ('synthetic-complete-history',)
        self.runtime.recovery_requested.set()
        self.assertFalse(await verified_flat(self.runtime))
        self.runtime.recovery_requested.clear()
        async with self.runtime.recovery_lock:
            self.assertFalse(await verified_flat(self.runtime))
        self.assertTrue(await verified_flat(self.runtime))

    async def test_flat_proof_rejects_stale_or_missing_account_evidence(self):
        self.assertFalse(await verified_flat(self.runtime))
        self.runtime.last_reports = ('synthetic-complete-history',)
        self.f.tick += 6
        self.f.now += timedelta(seconds=6)
        self.assertFalse(await verified_flat(self.runtime))

    async def test_periodic_refresh_does_not_revoke_an_active_dispatch(self):
        runtime = self.runtime
        runtime.account_subscribed = True
        runtime.recovery_state = 'repaired_entries_blocked'
        runtime.recovery_requested.clear()
        self.f.account.report = None
        task = None
        try:
            with patch.object(self.dispatcher, 'status',
                              return_value=SimpleNamespace(active=('A', ENTRY_PAIR))):
                task = asyncio.create_task(runtime._live_refresh())
                await asyncio.sleep(.01)
                self.assertFalse(runtime.recovery_requested.is_set())
            async with asyncio.timeout(2):
                await runtime.recovery_requested.wait()
        finally:
            runtime.stop_requested.set()
            if task is not None: await task

    async def test_pause_and_closed_session_cannot_submit(self):
        self.session.entries_paused = True
        self.dispatcher.submit('A', ENTRY_PAIR)
        self.assertEqual((await self.dispatcher.run_one()).state, 'BLOCKED')
        self.session.close()
        self.assertFalse(permits(self.session, self.f.writer))
        with self.assertRaises(InvalidData):
            await self.transport.batch(pair())
        self.assertFalse(self.calls)

    async def test_writer_requires_accounting_even_when_caller_claims_cash(self):
        self.f.account.revoke_accounting()
        value = await self.f.writer.reserve_entry_pair(pair(), batch_id='no-proof',
            view=await self.f.writer.portfolio(subaccount=0, now=self.f.now),
            config=BotConfig(), now=self.f.now, free_cash=D(100000), account_known=True,
            offline_fixture=False, fee_per_contract_bound=D('.02'))
        self.assertFalse(value.reserved)

    async def test_live_transport_rejects_unscoped_single_entries(self):
        with self.assertRaises(InvalidData):
            await self.transport('create', pair()[0])
        with self.assertRaises(InvalidData):
            await self.transport.batch(tuple(row | {'ticker':'OTHER'} for row in pair()))
        self.assertFalse(self.calls)


class RuntimeExitHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = exit_fixture.DispatchSourceTests()
        await self.f.asyncSetUp()
        self.service = self.f.runtime.attach_dispatch(self.f.source, self.f.dispatcher,
                                                      offline_fixture=True)

    async def asyncTearDown(self):
        await self.service.close()
        await self.f.asyncTearDown()

    async def test_book_evaluation_automatically_queues_exact_partial_fill_exit(self):
        await self.f.ready(filled='4')
        await self.f.runtime._evaluate('A', None, 0)
        self.assertEqual(self.f.dispatcher.status().queued, ((PASSIVE_REDUCER,'A'),))
        result = await self.f.dispatcher.run_one()
        self.assertEqual(result.state, 'ACK')
        self.assertEqual(D(self.f.calls[0][1]['count']), 4)
        self.assertFalse(self.f.calls[0][1]['reduce_only'])

    async def test_due_timer_automatically_queues_ioc(self):
        await self.f.ready()
        await self.f.due()
        await self.f.runtime._deadline('A')
        self.assertEqual(self.f.dispatcher.status().queued, ((DUE_IOC,'A'),))
        self.assertEqual((await self.f.dispatcher.run_one()).state, 'ACK')
        self.assertNotIn('expiration_time', self.f.calls[0][1])

    async def test_due_inventory_rearms_one_exhausted_recovery_before_ioc(self):
        await self.f.ready()
        await self.f.due()
        self.f.runtime.recovery_state = 'blocked_retry_exhausted'
        self.f.runtime._revoke()
        self.f.runtime.recovery_requested.clear()
        await self.f.runtime._deadline('A')
        self.assertTrue(self.f.runtime.recovery_requested.is_set())
        self.assertEqual(self.f.dispatcher.status().queued, ())
        self.f.runtime.recovery_requested.clear()
        await self.f.runtime._deadline('A')
        self.assertFalse(self.f.runtime.recovery_requested.is_set())

    async def test_partial_fill_cancels_old_entry_before_reducer(self):
        await self.f.ready(filled='4', remaining='6')
        await self.f.runtime._evaluate('A', None, 0)
        self.assertEqual(self.f.dispatcher.status().queued, ((SAFETY_CANCEL,'A'),))
        self.assertEqual((await self.f.dispatcher.run_one()).state, 'ACK')
        self.assertEqual(self.f.calls[0][0], 'cancel')

    async def test_drain_queues_flat_entry_cancel_not_new_position(self):
        await self.f.ready(filled='0', remaining='10')
        session = LiveSession(run_id='drain', tickers=('A','B'))
        session.bind(self.f.writer)
        self.f.runtime.live_session = session
        session.entries_paused = True
        await self.f.runtime._evaluate('A', None, 0)
        self.assertEqual(self.f.dispatcher.status().queued, ((SAFETY_CANCEL,'A'),))
        self.assertEqual((await self.f.dispatcher.run_one()).state, 'ACK')
        self.assertEqual(self.f.calls[0][0], 'cancel')

    async def test_hard_loss_hold_queues_flat_entry_cancel(self):
        await self.f.ready(filled='0', remaining='10')
        held = WindowState(*window_bounds(self.f.now), D(-25), 0, True, self.f.now)
        self.f.runtime.accounting_result = SimpleNamespace(released=True, window=held)
        self.assertTrue(self.f.runtime.entry_pause_active)
        await self.f.runtime._evaluate('A', None, 0)
        self.assertEqual(self.f.dispatcher.status().queued, ((SAFETY_CANCEL, 'A'),))
        self.assertEqual((await self.f.dispatcher.run_one()).state, 'ACK')
        self.assertEqual(self.f.calls[0][0], 'cancel')

    async def test_paused_entry_cancel_does_not_require_recent_book_price(self):
        await self.f.ready(filled='0', remaining='10')
        self.f.runtime.live_session = SimpleNamespace(entries_paused=True)
        self.f.runtime.management.revoke_terms('A')
        self.f.mono += 6
        await self.f.runtime._evaluate('A', None, 0)
        self.assertEqual(self.f.dispatcher.status().queued, ((SAFETY_CANCEL, 'A'),))
        self.assertEqual((await self.f.dispatcher.run_one()).state, 'ACK')
        self.assertEqual(self.f.calls[0][0], 'cancel')

    async def test_paused_dispatch_service_drains_two_entries_without_rest_recovery(self):
        first = await self.f.opening(filled='0', remaining='10', side='bid',
                                     client='first', order_id='first-order')
        second = await self.f.opening(filled='0', remaining='10', side='ask',
                                      client='second', order_id='second-order')
        await self.f.report('0', (first, second))
        self.f.runtime.live_session = SimpleNamespace(entries_paused=True)
        task = asyncio.create_task(self.service.run())
        self.assertTrue(self.service.request('A', SAFETY_CANCEL))
        for _ in range(100):
            if len(self.f.calls) == 2:
                break
            await asyncio.sleep(.01)
        self.assertEqual({row[1]['order_id'] for row in self.f.calls},
                         {'first-order', 'second-order'})
        self.assertIsNone(self.f.runtime.last_reports)
        self.service.stop()
        await task

    async def test_observation_runtime_cannot_attach_dispatch_even_as_fixture(self):
        self.f.runtime.observation_only = True
        with self.assertRaises(InvalidData):
            InventoryDispatchSource(self.f.runtime, offline_fixture=True)


class LaunchInputTests(unittest.TestCase):
    def test_candidate_authority_can_exceed_subscription_capacity(self):
        reviews = tuple(SimpleNamespace(ticker=f'M{i}') for i in range(129))
        session = LiveSession(run_id='broad-candidates',
                              tickers=tuple(r.ticker for r in reviews))
        self.assertEqual(len(session.tickers), 129)
        session.close()

    def test_seed_scope_is_separate_from_reviewed_candidate_universe(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'inputs.json'
            doc = self.document()
            doc['timing_reviews'].append(doc['timing_reviews'][0] | {'ticker':'B'})
            doc['initial_tickers'] = ['A']
            save_result(path, doc)
            inputs = LaunchInputs.load(path, datetime.now(timezone.utc))
            self.assertEqual(inputs.tickers, ('A','B'))
            self.assertEqual(inputs.seed_tickers, ('A',))
            for seeds in ([], ['C'], ['A','A'], 'A', [123]):
                save_result(path, doc | {'initial_tickers':seeds})
                with self.assertRaises(InvalidData):
                    LaunchInputs.load(path, datetime.now(timezone.utc))

    def test_failed_final_status_save_never_claims_no_trading_or_success(self):
        from kalshi_bot import live
        with TemporaryDirectory() as directory:
            with (patch.object(live, 'DATA', Path(directory)),
                  patch.object(live, 'WindowsLease'), patch.object(live, 'WindowsStopEvent'),
                  patch.object(live, 'refresh_candidate_inputs', new=AsyncMock(
                      return_value={'state':'CANDIDATES_PREPARED'})),
                  patch.object(live.LaunchInputs, 'load', return_value=SimpleNamespace(tickers=('A',))),
                  patch.object(live, 'run', new=AsyncMock(return_value={'state':'STOPPED_FLAT'})),
                  patch.object(live, 'save_result', side_effect=OSError('synthetic disk failure')),
                  patch('builtins.print') as output):
                self.assertEqual(live.main(['run','--live','--initialize']), 2)
            result = json.loads(output.call_args.args[0])
            self.assertEqual(result['state'], 'NEEDS_ATTENTION')
            self.assertTrue(result['trading_may_have_started'])
            self.assertFalse(result['flat_verified'])

    def document(self):
        return dict(exchange_indices=[0,1], fee_profile=dict(balance_quantum='.0001',
            review_reference='synthetic-direct', valid_until='2099-01-01T00:00:00Z'),
            timing_reviews=[dict(ticker='A',event='E',milestone_id='M',milestone_type='sports_game',
                rules_hash='a'*64,review_reference='synthetic-rules',
                valid_until='2099-01-01T00:00:00Z',early_close_reviewed=False)])

    def test_inputs_are_explicit_and_cannot_auto_approve_expired_scope(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'inputs.json'
            save_result(path, self.document())
            value = LaunchInputs.load(path, datetime.now(timezone.utc))
            self.assertEqual(value.tickers, ('A',))
            document = self.document()
            document['timing_reviews'][0]['valid_until'] = '2000-01-01T00:00:00Z'
            save_result(path, document)
            with self.assertRaises(InvalidData):
                LaunchInputs.load(path, datetime.now(timezone.utc))

    def test_legacy_automatic_scope_cannot_claim_early_close_review(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'inputs.json'
            document = self.document()
            document['timing_reviews'][0].update(
                review_reference='automatic-primary-milestone-v1',
                early_close_reviewed=True)
            save_result(path, document)
            with self.assertRaisesRegex(InvalidData, 'incomplete launch scope'):
                LaunchInputs.load(path, datetime.now(timezone.utc))

    def test_atomic_status_contains_last_whole_result(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'
            save_result(path, {'state':'RUNNING'})
            save_result(path, {'state':'BLOCKED'})
            self.assertEqual(json.loads(path.read_text())['state'], 'BLOCKED')
            self.assertFalse(path.with_suffix('.json.tmp').exists())

    def test_status_publish_retries_transient_replace_denial(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'
            save_result(path, {'state':'OLD'})
            actual_replace = os.replace
            attempts = 0
            def replace(source, target):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError(13, 'synthetic sharing violation')
                actual_replace(source, target)
            with patch.object(startup.os, 'replace', side_effect=replace), patch.object(
                    startup.time, 'sleep'):
                save_result(path, {'state':'CURRENT'})
            self.assertEqual(attempts, 3)
            self.assertEqual(json.loads(path.read_text())['state'], 'CURRENT')

    def test_permanent_replace_denial_preserves_previous_whole_status(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'
            save_result(path, {'state':'OLD'})
            with patch.object(startup.os, 'replace', side_effect=PermissionError(
                    13, 'synthetic permanent denial')):
                with self.assertRaises(PermissionError):
                    save_result(path, {'state':'MUST_NOT_APPEAR'}, replace_timeout=0)
            self.assertEqual(json.loads(path.read_text())['state'], 'OLD')
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    @unittest.skipUnless(os.name == 'nt', 'native Windows sharing semantics')
    def test_real_windows_reader_contention_is_bounded_and_recovers(self):
        import ctypes
        from ctypes import wintypes
        with TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'
            save_result(path, {'state':'OLD'})
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                wintypes.HANDLE]
            api.CreateFileW.restype = wintypes.HANDLE
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle.restype = wintypes.BOOL
            # Share reads/writes but deliberately deny delete/rename.
            handle = api.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
            self.assertNotIn(handle, (None, 0, wintypes.HANDLE(-1).value))
            closer = threading.Timer(.1, api.CloseHandle, args=(handle,))
            closer.start()
            try:
                save_result(path, {'state':'CURRENT'}, replace_timeout=1)
            finally:
                closer.join()
            self.assertEqual(json.loads(read_text_shared(path))['state'], 'CURRENT')


class CompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_original_graph_bootstraps_and_dispatches_without_fixture_switches(self):
        await self.run_graph()

    async def test_discovered_market_reaches_fresh_metadata_ranking_and_pair_ack(self):
        await self.run_graph(discover=True)

    async def test_discovered_unsupported_fee_model_never_dispatches(self):
        await self.run_graph(discover=True, unsupported=True)

    async def run_graph(self, *, discover=False, unsupported=False):
        import test_bot_market_inputs as metadata
        from test_bot_incentive_discovery import row as reward_row
        from test_bot_opening_account import balance
        from test_bot_quota import LIMITS, COSTS, Signer
        base, start = metadata.NOW, time.monotonic()
        now = lambda: base+timedelta(seconds=time.monotonic()-start)
        closed, calls = [], []
        market = metadata.market()
        docs = {
            '/account/limits': LIMITS, '/account/endpoint_costs': COSTS,
            '/portfolio/balance': balance(), '/portfolio/orders': {'orders':[], 'cursor':''},
            '/portfolio/positions': {'market_positions':[], 'cursor':''},
            '/portfolio/fills': {'fills':[], 'cursor':''},
            '/portfolio/settlements': {'settlements':[], 'cursor':''},
            '/portfolio/subaccounts/transfers': {'transfers':[]},
            '/portfolio/intra_exchange_instance_transfers': {'transfers':[]},
            '/portfolio/deposits': {'deposits':[]}, '/portfolio/withdrawals': {'withdrawals':[]},
            '/historical/cutoff': {'trades_created_ts':(base-timedelta(days=1)).isoformat()},
            '/markets/A': {'market':market}, '/events/E': {'event':metadata.Reads().event},
            '/series/S': {'series':metadata.Reads().series},
            '/events/fee_changes': {'event_fee_changes':[], 'cursor':''},
            '/series/fee_changes': {'series_fee_change_arr':[]},
            '/milestones/M': {'milestone':metadata.Reads().milestone},
            '/incentive_programs': {'incentive_programs':[reward_row()], 'next_cursor':''},
        }
        if discover:
            docs['/markets/B'] = {'market':metadata.market('B')}
            docs['/incentive_programs']['incentive_programs'] = [
                reward_row('B', 'reward-b'), reward_row('UNREVIEWED', 'reward-u')]
        if unsupported:
            docs['/series/S']['series']['fee_type'] = 'flat'
        docs['/events'] = {'events':[{**metadata.Reads().event,
            'markets':[market]+([metadata.market('B')] if discover else [])}],
            'milestones':[metadata.Reads().milestone], 'cursor':''}
        def wire(url, *_):
            path = urlparse(url).path.removeprefix('/trade-api/v2')
            return WireResponse(200, json.dumps(docs[path], default=str).encode())
        class Reader:
            def __init__(self, spec): self.spec = spec
            async def run(self, consume):
                try:
                    for sid, channel in enumerate(self.spec.channels, 1):
                        await consume(self.spec.name, dict(type='subscribed', id=1,
                            msg=dict(channel=channel,sid=sid)))
                    seq = 0
                    while True:
                        if self.spec.name.startswith('book-') and seq == 0:
                            for ticker in self.spec.tickers:
                                seq += 1
                                await consume(self.spec.name, dict(type='orderbook_snapshot', sid=1,seq=seq,
                                    msg=dict(market_ticker=ticker,yes_dollars_fp=[['.5','1000']],
                                             no_dollars_fp=[['.6','1000']])))
                        await asyncio.sleep(.1)
                finally: closed.append(self.spec.name)
        class Wire:
            async def __call__(self, *_): raise AssertionError('unexpected single command')
            async def batch(self, requests):
                session.check('batch_create', requests)
                calls.append(requests)
                return {'orders':[dict(order_id='mock-'+r['side'],
                    client_order_id=r['client_order_id'],fill_count='0',remaining_count='10',ts_ms=1)
                    for r in requests]}
        with TemporaryDirectory() as directory:
            session = LiveSession(run_id='composed-synthetic', tickers=('A','B') if discover else ('A',))
            writer = await LedgerWriter(Path(directory)/'account.db', live_session=session).start()
            reads = RestReads(TokenBudget(rate=10000,capacity=10000,default_cost=10,
                clock=time.monotonic), Signer(), wire=wire)
            guard = QuotaGuard(QuotaPolicy(ProbeConfig(10000,10000,10,10)),
                clock=time.monotonic, now=now)
            reads.attach_quota(guard)
            quota = QuotaSupervisor(reads)
            runtime = task = None
            try:
                reviews = ((metadata.review(market),metadata.review(metadata.market('B')))
                           if discover else (metadata.review(market),))
                inputs = LaunchInputs(reviews,
                    metadata.FeeProfile(D('.0001'),'synthetic',base+timedelta(hours=2)), (0,1), ('A',))
                runtime = await compose(writer, reads, Reader, Wire(), inputs=inputs,
                    boundary=base-timedelta(seconds=1), now=now, clock=time.monotonic,
                    diagnostics=NO_LOG, quota=quota, initialize=True)
                self.assertEqual(len(guard.listeners), 5)
                self.assertFalse(runtime.observation_only)
                self.assertFalse(runtime.dispatch_supervisor.dispatcher.offline_fixture)
                self.assertIsNone(runtime.admission)
                self.assertTrue(runtime.broad_discovery)
                self.assertEqual(runtime.metadata_scheduler.concurrency, 4)
                self.assertIsNotNone(runtime.market_inputs.bulk)
                self.assertEqual(set(runtime.engine.market_shard), {'A','B'} if discover else {'A'})
                task = asyncio.create_task(runtime.run())
                async with asyncio.timeout(10):
                    while not calls and not (unsupported and 'B' in runtime.market_inputs.results):
                        if task.done(): task.result()
                        await asyncio.sleep(.01)
                if discover:
                    self.assertNotIn('UNREVIEWED', runtime.engine.market_shard)
                    self.assertIn('B', runtime.market_inputs.reviews)
                if unsupported:
                    await asyncio.sleep(.1)
                    self.assertEqual(runtime.market_inputs.results['B'].blockers, ('fee_model_unsupported',))
                    self.assertFalse(calls)
                    self.assertFalse(await writer.mutations())
                    return
                self.assertEqual(len(calls), 1)
                self.assertEqual({row['ticker'] for row in calls[0]}, {'B' if discover else 'A'})
                self.assertTrue(all(D(row['count']) == 10 for row in calls[0]))
                async with asyncio.timeout(2):
                    while sum(r['phase'] == 'ACK' for r in await writer.mutations()) != 2:
                        if task.done(): task.result()
                        await asyncio.sleep(.01)
                self.assertTrue(runtime._metadata_priority('B' if discover else 'A'))
                self.assertLessEqual({r['phase'] for r in await writer.mutations()}, {'ACK', 'NOT_SENT'})
                self.assertFalse(await verified_flat(runtime))
            finally:
                if runtime is not None: runtime.stop()
                try:
                    if task is not None: await task
                finally:
                    try:
                        await quota.close()
                    finally:
                        try:
                            await reads.close()
                        finally:
                            await writer.close()
            self.assertEqual(set(closed), {'book-0','account','lifecycle'})
            self.assertTrue(session.closed)


if __name__ == '__main__':
    unittest.main()
