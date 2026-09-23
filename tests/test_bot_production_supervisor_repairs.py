import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace as NS
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from kalshi_bot import live
from kalshi_bot import supervised_live_child as child
from kalshi_bot.live_session import LiveSession
from kalshi_bot.observability import NO_LOG
from kalshi_bot.process_supervisor import SupervisorHost
from kalshi_bot.quota_supervisor import QuotaSupervisor
from kalshi_bot.recovery_fence import FenceCooldown, RecoveryFence
from kalshi_bot.rest import TokenBudget
from kalshi_bot.restriction_journal import RestrictionJournal
from kalshi_bot.supervised_runtime import RuntimeRestrictions
from kalshi_bot.supervision import ChildOutcome
from kalshi_bot.supervisor_launch import ProductionLaunchProfile
from kalshi_bot.values import InvalidData
from kalshi_bot.windows import WindowsLease


class Endpoint:
    def __init__(self, receive=None):
        self.callback = receive
        self.receives = 0
        self.statuses = []

    def receive(self, timeout=0):
        self.receives += 1
        if self.callback is not None:
            return self.callback()
        time.sleep(min(timeout, .002))
        return None

    def publish_latest(self, message):
        self.statuses.append(message)


def arguments():
    return NS(initialize_approved=False, recovery_only=False,
        explicit_retry=True,
        parent_handle=1, stop_handle=2, scope_digest='a'*64,
        parent_session='parent', child_id='child', child_generation=1,
        store_path='ignored')


class ProductionRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_lease_is_retained_until_exception_drain_joins(self):
        with TemporaryDirectory() as folder, ExitStack() as stack:
            data = Path(folder)
            (data/'account.db').touch()
            identity = 'repair-synthetic-'+uuid4().hex
            started = Event()
            acquired = []

            async def runtime(_args, _inputs, _session, _diagnostics, stop, **_kwargs):
                started.set()
                while not stop.requested:
                    await asyncio.sleep(.001)
                try:
                    with WindowsLease(identity):
                        acquired.append(True)
                except InvalidData:
                    acquired.append(False)
                return {'state':'STOPPED_FLAT'}

            def receive():
                if started.is_set():
                    raise InvalidData('synthetic IPC loss')
                return None

            class Mutex:
                abandoned = False
                def __enter__(self): return self
                def __exit__(self, *_args): return None
            mutex = Mutex()
            stack.enter_context(patch.object(child, 'DATA', data))
            stack.enter_context(patch.object(child, 'WindowsLease',
                                             lambda _value:WindowsLease(identity)))
            stack.enter_context(patch.object(child, 'WindowsControlMutex',
                                             return_value=mutex))
            stack.enter_context(patch.object(child.BotConfig, 'load'))
            stack.enter_context(patch.object(child.SupervisorStore,
                                             'read_only_recovery_fence', return_value=None))
            stack.enter_context(patch.object(child.LaunchInputs, 'load',
                                             return_value=NS(tickers=('A',))))
            stack.enter_context(patch.object(child, 'wait_handle', return_value=False))
            prepared = stack.enter_context(patch.object(child, '_prepare_candidates',
                new=AsyncMock(return_value={'state':'CANDIDATES_PREPARED'})))
            stack.enter_context(patch.object(child, 'run_live', runtime))
            stack.enter_context(patch.object(child, '_publish_fence', new=AsyncMock()))
            sent = stack.enter_context(patch.object(child, '_send_result', new=AsyncMock()))
            scope = NS(scope_id='production-kalshi-primary-account',
                       approved_user_sid='sid')
            code = await asyncio.wait_for(child._run_live(arguments(), scope,
                Endpoint(receive), None, lambda _message:True,
                NS(changed=Event()), NO_LOG), 2)
            self.assertEqual(code, 27)
            prepared.assert_awaited_once()
            self.assertEqual(acquired, [False])
            with WindowsLease(identity):
                pass
            self.assertEqual(sent.call_args.kwargs['outcome'], 'unexpected_death')

    async def test_slow_preparation_services_ipc_and_stop_cancels_it(self):
        cleaned = Event()

        async def refresh(*_args):
            try:
                await asyncio.sleep(5)
            finally:
                cleaned.set()

        messages = iter((None, NS(kind=child.MessageKind.STOP_HINT)))
        endpoint = Endpoint(lambda:next(messages, None))
        stop = NS(requested=False)
        stop.request = lambda:setattr(stop, 'requested', True)
        args = arguments()
        with patch.object(child, 'refresh_candidate_inputs', refresh), \
             patch.object(child, 'wait_handle', return_value=False):
            result = await asyncio.wait_for(child._prepare_candidates(args,
                endpoint, lambda _message:True, stop, [time.monotonic()], NO_LOG,
                NS(inputs=Path('ignored')), [0]), 2)
        self.assertIsNone(result)
        self.assertGreater(endpoint.receives, 0)
        self.assertTrue(cleaned.is_set())

    async def test_recovery_only_does_not_expand_candidate_scope(self):
        mode = child.production_child_mode(initialize_approved=False,
            ledger_exists=True, recovery_only=True)
        self.assertTrue(mode.recovery_only)
        self.assertFalse(mode.initialize)

    async def test_inherited_cooldown_wait_remains_supervised(self):
        restrictions = RuntimeRestrictions()
        restrictions.apply(RecoveryFence('parent', 'old-child', 1, 1, (),
            (FenceCooldown('quota_refresh', time.time()+.12),), False),
            current_parent_session='parent')
        endpoint = Endpoint()
        stop = NS(requested=False, request=lambda:None)
        with patch.object(child, 'wait_handle', return_value=False):
            started = time.monotonic()
            self.assertTrue(await child._wait_cooldowns(arguments(), endpoint,
                lambda _message:True, stop, [time.monotonic()], restrictions, [0]))
        self.assertGreaterEqual(time.monotonic()-started, .08)
        self.assertGreater(endpoint.receives, 0)
        self.assertGreater(len(endpoint.statuses), 0)

    async def test_pre_runtime_stop_with_existing_ledger_is_never_clean(self):
        with TemporaryDirectory() as folder:
            ledger = Path(folder)/'account.db'
            ledger.touch()
            with patch.object(child, '_send_result', new=AsyncMock()) as sent:
                code = await child._send_early_stop(arguments(), Endpoint(),
                    NO_LOG, [1], ledger)
            self.assertEqual(code, 31)
            self.assertEqual(sent.call_args.kwargs['outcome'], 'unknown_failure')
            self.assertTrue(sent.call_args.kwargs['unresolved_work'])

    def test_temporary_runtime_blockers_are_not_retry_holds(self):
        phase, holds = child._status_projection(dict(entries_paused=False,
            risk_blockers=['book_stale'],
            accounting_blockers=['accounting_not_released']), False)
        self.assertEqual(phase, 'degraded')
        self.assertEqual(holds, ())

    def test_expired_unowned_review_is_removed_but_expired_owner_refuses(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'inputs.json'
            document = dict(exchange_indices=[0], initial_tickers=['A'],
                fee_profile=dict(balance_quantum='.0001', review_reference='test',
                    valid_until='2099-01-01T00:00:00Z'), timing_reviews=[
                    dict(ticker=ticker, event='E', milestone_id='M',
                         milestone_type='sports_game', rules_hash='a'*64,
                         review_reference='test', early_close_reviewed=False,
                         valid_until=expiry) for ticker,expiry in (
                            ('A','2099-01-01T00:00:00Z'),
                            ('UNOWNED','2000-01-01T00:00:00Z'))])
            path.write_text(json.dumps(document), encoding='utf-8')
            now = datetime.now(timezone.utc)
            value = live.LaunchInputs.load_recovery(path, now, {'A'})
            self.assertEqual(value.tickers, ('A',))
            with self.assertRaisesRegex(InvalidData, 'owner review'):
                live.LaunchInputs.load_recovery(path, now, {'UNOWNED'})

    async def test_exit_27_without_result_is_unexpected_death(self):
        factory = NS(endpoint=None, result=None, cleanup_error=None,
            child_generation=1, child_id='child', fence_revision=1,
            terminal_fence_revision=0, component_holds=(), cooldowns=(),
            close_after_exit=AsyncMock())
        host = SupervisorHost.__new__(SupervisorHost)
        host.child = factory
        host.launch_profile = ProductionLaunchProfile()
        host.fixture_mode = 'production_live'
        host._apply = AsyncMock()
        host.child_exits = host.validated_results = 0
        await host._finish_child(27)
        event = host._apply.call_args.args[0]
        self.assertEqual(event.outcome, ChildOutcome.UNEXPECTED_DEATH)

    def test_restrictions_are_durable_at_component_transition(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'restrictions.json'
            journal = RestrictionJournal(path, clock=lambda:1000.)
            budget = TokenBudget(rate=1, capacity=10, default_cost=1,
                clock=lambda:0., restriction_sink=journal.cooldown)
            budget.throttle(30)
            holds, cooldowns = RestrictionJournal(path, clock=lambda:1000.).snapshot()
            self.assertEqual(holds, ())
            self.assertEqual(cooldowns[0].name, 'read_shared_429')
            self.assertEqual(cooldowns[0].deadline_utc, 1030.)

            quota = QuotaSupervisor.__new__(QuotaSupervisor)
            quota.failures = 0
            quota.guard = NS(policy=NS(attempts=1, cooldown=60), clock=lambda:0.)
            quota.jitter = lambda:0
            quota.requested = True
            quota.diagnostics = NO_LOG
            quota.restriction_sink = lambda name,seconds,hold: (
                journal.hold(name, seconds) if hold
                else journal.cooldown(name, seconds))
            quota._failed(InvalidData('synthetic exhaustion'))
            holds, cooldowns = RestrictionJournal(path, clock=lambda:1000.).snapshot()
            self.assertIn('quota_refresh_exhausted', holds)
            self.assertIn('quota_refresh', {item.name for item in cooldowns})

    async def test_terminal_flat_status_is_saved_only_after_cleanup(self):
        with TemporaryDirectory() as folder, ExitStack() as stack:
            data = Path(folder)
            (data/'account.db').touch()
            key = data/'key'
            key.write_bytes(b'not-a-real-key')
            state = NS(writer=False, reads=False, quota=False)

            class Writer:
                def __init__(self, *_args, **_kwargs): pass
                async def start(self): return self
                async def accounting_status(self):
                    return NS(proposed_boundary=datetime.now(timezone.utc), blockers=())
                async def close(self): state.writer = True

            class Reads:
                def __init__(self, *_args, **_kwargs):
                    self.budget = NS(blocked_until=0., throttle=lambda _seconds:None)
                def attach_quota(self, _guard): pass
                async def close(self): state.reads = True

            class Quota:
                def __init__(self, *_args, **_kwargs): pass
                async def close(self): state.quota = True

            budget = NS(restriction_sink=None,
                pause_429=lambda **_kwargs:None)
            runtime = NS(dispatch_supervisor=NS(dispatcher=NS(
                budget=budget, clock_pair=lambda:(0.,0.))))
            saves = []
            def save(_path, value):
                self.assertTrue(state.writer and state.reads and state.quota)
                saves.append(value)

            stack.enter_context(patch.object(live, 'DATA', data))
            stack.enter_context(patch.object(live, 'load_signer',
                                             return_value=NS(_key_id='id')))
            stack.enter_context(patch.object(live, 'MutationSigner', return_value=object()))
            stack.enter_context(patch.object(live, 'LedgerWriter', Writer))
            stack.enter_context(patch.object(live, 'RestReads', Reads))
            stack.enter_context(patch.object(live, 'TokenBudget', return_value=object()))
            stack.enter_context(patch.object(live, 'QuotaGuard', return_value=object()))
            stack.enter_context(patch.object(live, 'QuotaPolicy', return_value=object()))
            stack.enter_context(patch.object(live, 'ProbeConfig', return_value=object()))
            stack.enter_context(patch.object(live, 'QuotaSupervisor', Quota))
            stack.enter_context(patch.object(live, 'readonly_reader_factory', return_value=object()))
            stack.enter_context(patch.object(live, 'OrderMutationTransport', return_value=object()))
            stack.enter_context(patch.object(live, 'compose', new=AsyncMock(return_value=runtime)))
            stack.enter_context(patch.object(live, 'supervise', new=AsyncMock(
                return_value={'state':'STOPPED_FLAT'})))
            stack.enter_context(patch.object(live, 'save_result', side_effect=save))
            args = NS(initialize=False, key_id_file=key, private_key_file=key)
            session = LiveSession(run_id='terminal-save', tickers=('A',))
            result = await live.run(args, NS(exchange_indices=(0,)), session,
                NO_LOG, NS(requested=True),
                restriction_journal=RestrictionJournal(data/'restrictions.json'))
            self.assertEqual(result['state'], 'STOPPED_FLAT')
            self.assertEqual(saves[-1]['state'], 'STOPPED_FLAT')


if __name__ == '__main__':
    unittest.main()
