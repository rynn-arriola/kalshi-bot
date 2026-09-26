"""Disposable Windows diagnostic/fault tests; no network or account access."""
import asyncio
import ast
from contextlib import redirect_stdout
from datetime import timedelta
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from kalshi_bot.cli import main
from kalshi_bot.command_types import CommandDenied
from kalshi_bot.config import BotConfig
from kalshi_bot.execution import InjectedExecutor
from kalshi_bot.observability import Diagnostics, StrictRotatingHandler, safe_error, EVENTS
from kalshi_bot.rest import RestReads, TokenBudget, WireResponse, ReadFailure
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.supervised_live_child import (PRODUCTION_LOG_BACKUPS,
                                               PRODUCTION_LOG_MAX_BYTES)
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_engine import NOW, request
from test_bot_recovery_runtime import AccountReads, FakeReader

SECRET = 'SENTINEL_DO_NOT_LOG_this_private_key_or_response'


def rows(directory, pattern='*.jsonl*'):
    # D-149: events.jsonl plus the separate routine telemetry.jsonl.
    return [json.loads(line) for path in sorted(Path(directory).glob(pattern))
            for line in path.read_text(encoding='utf-8').splitlines()]


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.directory = Path(self.temp.name)/'logs'
        self.log = None

    def tearDown(self):
        if self.log:
            self.log.close()
        self.temp.cleanup()

    def start(self, **kwargs):
        self.log = Diagnostics(self.directory, **kwargs).start()
        return self.log

    def test_construction_has_no_files_or_thread(self):
        self.log = Diagnostics(self.directory)
        self.assertFalse(self.directory.exists())
        self.assertFalse(self.log.status()['worker_alive'])

    def test_status_reports_configured_production_retention_bound(self):
        self.log = Diagnostics(self.directory, max_bytes=PRODUCTION_LOG_MAX_BYTES,
                               backups=PRODUCTION_LOG_BACKUPS)
        status = self.log.status()
        self.assertEqual(status['max_bytes'], 12*1024*1024)
        self.assertEqual(status['backups'], 7)
        self.assertEqual(status['retention_bytes'], 96*1024*1024)

    def test_json_schema_order_correlation_and_drain(self):
        log = self.start()
        for _ in range(3):
            self.assertTrue(log.emit('reader_failed', stream='account', generation=2, operation='same'))
        log.close()
        data = rows(self.directory)
        self.assertEqual([r['sequence'] for r in data], list(range(1, 6)))
        self.assertEqual(len({r['run_id'] for r in data}), 1)
        self.assertEqual(len({r['context']['operation_ref'] for r in data[1:4]}), 1)
        self.assertEqual(data[1]['severity'], 'WARNING')
        self.assertEqual(data[1]['context']['generation'], 2)
        self.assertTrue(data[1]['utc'].endswith('+00:00'))
        self.assertEqual(log.status()['accepted'], log.status()['written'])

    def test_candidate_preparation_event_is_registered_and_keeps_log_healthy(self):
        log = self.start()
        self.assertTrue(log.emit('candidate_scope_prepared', reviewed_markets=1024,
                                 initial_websocket_markets=128, incentive_rows=4759,
                                 market_rows=4753, milestone_rows=3228))
        log.ensure_healthy()
        log.close()
        event = next(row for row in rows(self.directory)
                     if row['event'] == 'candidate_scope_prepared')
        self.assertEqual(event['context']['reviewed_markets'], 1024)

    def test_fill_risk_samples_and_ack_use_safe_correlated_fields(self):
        log = self.start()
        log.emit('fill_risk_sample', market=SECRET, order=SECRET, risk_state='threat',
                 ahead_hundredths=100, queue_hundredths=500, depth_hundredths=100,
                 depletion_hundredths=200, queue_age_ms=300, horizon_ms=7000, eta_ms=500)
        log.emit('fill_risk_cancel_ack', market=SECRET, order=SECRET, elapsed_ms=250)
        log.emit('cancel_submit_attempt', order=SECRET, operation=SECRET)
        log.emit('risk_cancel_deferred', market=SECRET, count=2,
                 blockers=('current_candidate_missing', SECRET), blocker_count=2)
        log.emit('fill_risk_observation_gap', risk_state='queue_expired', count=8)
        log.emit('fill_risk_observation_gap', risk_state=SECRET, unknown_field=SECRET)
        log.ensure_healthy()
        log.close()
        data = rows(self.directory)
        self.assertNotIn(SECRET, json.dumps(data))
        sample = next(r['context'] for r in data if r['event'] == 'fill_risk_sample')
        ack = next(r['context'] for r in data if r['event'] == 'fill_risk_cancel_ack')
        self.assertEqual(sample['order_ref'], ack['order_ref'])
        self.assertEqual(sample['eta_ms'], 500)
        self.assertEqual(sample['risk_state'], 'threat')
        retry = next(r['context'] for r in data if r['event'] == 'risk_cancel_deferred')
        self.assertEqual(retry['blockers'], ['current_candidate_missing'])
        self.assertEqual(retry['unknown_blockers'], 1)

    def test_native_exit_code_is_recorded_without_exception_text(self):
        log = self.start()
        log.emit('supervisor_child_exited', operation='child-test', generation=4,
                 exit_code=0xC0000005)
        log.close()
        event = next(row for row in rows(self.directory)
                     if row['event'] == 'supervisor_child_exited')
        self.assertEqual(event['context']['exit_code'], 0xC0000005)
        self.assertEqual(event['context']['generation'], 4)

    def test_four_shards_and_recovery_reasons_are_readable_and_allowlisted(self):
        log = self.start()
        for stream in ('book-0', 'book-1', 'book-2', 'book-3'):
            log.emit('reader_failed', stream=stream)
        log.emit('recovery_failed', cause='routine_refresh_failed', phase='accounting_release',
                 elapsed_ms=125, error=OSError(SECRET))
        log.emit('recovery_failed', cause=SECRET, phase=SECRET, outcome=SECRET)
        log.emit('entry_dispatch_blocked', market=SECRET, count=8,
                 blockers=('entry_send_proof_changed', 'book_queue_pending', SECRET))
        log.close()
        data = rows(self.directory)
        self.assertEqual([r['context']['stream'] for r in data if r['event']=='reader_failed'],
                         ['book-0', 'book-1', 'book-2', 'book-3'])
        failed = [r for r in data if r['event']=='recovery_failed']
        self.assertEqual(failed[0]['context'], dict(cause='routine_refresh_failed',
            phase='accounting_release', elapsed_ms=125))
        self.assertEqual(failed[1]['context'], {})
        entry = next(r for r in data if r['event']=='entry_dispatch_blocked')
        self.assertEqual(entry['context']['unknown_blockers'], 1)
        self.assertEqual(entry['context']['count'], 8)
        self.assertNotIn(SECRET, json.dumps(data))

    def test_every_literal_diagnostic_event_is_registered(self):
        package = Path(__file__).resolve().parents[1]/'src'/'kalshi_bot'
        missing = []
        for path in package.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'emit' and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                        and node.args[0].value not in EVENTS):
                    missing.append((path.name, node.lineno, node.args[0].value))
        self.assertEqual(missing, [])

    def test_every_literal_emitted_field_and_entry_reason_is_retained(self):
        # D-130: fields the sink silently discarded hid batch outcomes and
        # entry-block reasons (Finding 194). Every literal must be allowlisted.
        from kalshi_bot import observability as o
        allowed = (set(o.NUMBERS) | set(o.ENUMS) | set(o.REFERENCES)
                   | set(o.SAFE_CODES) | {'blockers', 'error'})
        package = Path(__file__).resolve().parents[1]/'src'/'kalshi_bot'
        dropped = []
        for path in package.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'emit'):
                    dropped.extend((path.name, node.lineno, k.arg) for k in node.keywords
                                   if k.arg is not None and k.arg not in allowed)
        self.assertEqual(dropped, [])
        source = (package/'dispatch_sources.py').read_text(encoding='utf-8')
        reasons = set(__import__('re').findall(
            r"(?:blocked\(|details\.append\(|reasons\.append\()'([a-z_]+)'", source))
        self.assertEqual(reasons-o.BLOCKERS, set())
        self.assertIn('rejected_count', o.NUMBERS)

    def test_secrets_and_unknown_objects_are_never_formatted(self):
        class Poison:
            def __str__(self): raise AssertionError('formatted')
            def __repr__(self): raise AssertionError('formatted')
        log = self.start()
        try:
            raise OSError(5, SECRET, SECRET)
        except OSError as exc:
            log.emit('rest_transport_failed', error=exc, headers={'Authorization': SECRET},
                     payload=Poison(), market=SECRET, endpoint=SECRET, stream=SECRET,
                     operation=SECRET, http_status=SECRET)
        log.close()
        raw = json.dumps(rows(self.directory))
        self.assertNotIn(SECRET, raw)
        self.assertNotIn('Authorization', raw)
        self.assertIn('OSError', raw)
        self.assertIn('frames', raw)

    def test_group_chain_and_trace_are_bounded(self):
        cause = ValueError(SECRET)
        outer = ExceptionGroup(SECRET, [cause]*100)
        outer.__cause__ = outer
        data = safe_error(outer)
        self.assertLessEqual(len(data), 4)
        self.assertNotIn(SECRET, json.dumps(data))
        self.assertTrue(all(len(item['frames']) <= 12 for item in data))

    def test_owned_source_location_retained_without_message(self):
        try:
            request()['price'] = SECRET
            from kalshi_bot.values import price
            price(SECRET)
        except Exception as exc:
            data = safe_error(exc)
        self.assertTrue(any(f['module']=='kalshi_bot.values' for e in data for f in e['frames']))
        self.assertNotIn(SECRET, json.dumps(data))

    def test_rotation_is_bounded(self):
        log = self.start(max_bytes=32768, backups=2, capacity=8192)
        for i in range(700):
            log.emit('reader_failed', attempt=i, operation='operation-'+str(i))
        log.close()
        paths = list(self.directory.glob('events.jsonl*'))
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(p.stat().st_size <= 32768 for p in paths))
        self.assertIsNone(log.status()['failure'])
        self.assertTrue(rows(self.directory))

    def test_routine_telemetry_rotates_separately_from_events(self):
        # D-149: a telemetry flood cannot rotate warnings/errors out of events.jsonl.
        log = self.start(max_bytes=32768, backups=2, capacity=8192,
                         telemetry_max_bytes=32768, telemetry_backups=1)
        log.emit('reader_failed', attempt=1, operation='kept')
        for i in range(700):
            log.emit('fill_risk_sample', market='A', order='o-'+str(i), risk_state='observed',
                     ahead_hundredths=i)
            log.emit('inventory_plan_changed', market='A', mode='flat', revision=i)
        log.emit('recovery_exhausted', attempt=3)
        log.close()
        events = rows(self.directory, 'events.jsonl*')
        names = [r['event'] for r in events]
        self.assertIn('reader_failed', names)
        self.assertIn('recovery_exhausted', names)
        self.assertNotIn('fill_risk_sample', names)
        self.assertNotIn('inventory_plan_changed', names)
        telemetry = rows(self.directory, 'telemetry.jsonl*')
        self.assertTrue(telemetry)
        self.assertEqual({r['event'] for r in telemetry},
                         {'fill_risk_sample', 'inventory_plan_changed'})
        self.assertEqual(len(list(self.directory.glob('telemetry.jsonl*'))), 2)  # Bounded.
        self.assertEqual(log.status()['telemetry_retention_bytes'], 32768*2)
        # One global sequence across both files keeps the run's order recoverable.
        sequences = sorted(r['sequence'] for r in events+telemetry)
        self.assertEqual(len(sequences), len(set(sequences)))

    def test_telemetry_events_are_routine_info_only(self):
        from kalshi_bot.observability import EVENTS, TELEMETRY_EVENTS
        # Warnings/errors must never be routed out of events.jsonl.
        self.assertEqual({EVENTS[name][0] for name in TELEMETRY_EVENTS}, {'INFO'})

    def test_restart_has_new_run_and_private_reference_salt(self):
        first = self.start()
        first.emit('mutation_prepared', operation='same')
        first.close()
        self.log = Diagnostics(self.directory).start()
        self.log.emit('mutation_prepared', operation='same')
        self.log.close()
        data = [r for r in rows(self.directory) if r['event']=='mutation_prepared']
        self.assertNotEqual(data[0]['run_id'], data[1]['run_id'])
        self.assertNotEqual(data[0]['context']['operation_ref'], data[1]['context']['operation_ref'])

    def test_second_owner_cannot_rotate_same_directory(self):
        self.start()
        other = Diagnostics(self.directory)
        try:
            with self.assertRaises(InvalidData): other.start()
            self.assertEqual(other.status()['failure'], 'sink_failure')
        finally:
            other.close()
        self.log.ensure_healthy()

    def test_sink_failure_is_latched_and_no_raw_stderr(self):
        log = self.start()
        with patch.object(StrictRotatingHandler, 'emit', side_effect=OSError(SECRET)):
            log.emit('runtime_started')
            deadline = time.monotonic()+2
            while not log.status()['failure'] and time.monotonic()<deadline:
                time.sleep(.001)
        self.assertEqual(log.status()['failure'], 'sink_failure')
        with self.assertRaises(InvalidData): log.ensure_healthy()

    def test_saturation_never_blocks_producer_and_is_visible(self):
        entered, release = Event(), Event()
        original = StrictRotatingHandler.emit
        def slow(handler, record):
            entered.set()
            release.wait(2)
            return original(handler, record)
        with patch.object(StrictRotatingHandler, 'emit', slow):
            try:
                log = self.start(capacity=1)
                self.assertTrue(entered.wait(1))
                self.assertTrue(log.emit('runtime_started'))
                start = time.perf_counter()
                self.assertFalse(log.emit('runtime_started'))
                self.assertLess(time.perf_counter()-start, .1)
                self.assertEqual(log.status()['failure'], 'queue_overflow')
                self.assertEqual(log.status()['dropped'], 1)
                with self.assertRaises(InvalidData): log.ensure_healthy()
            finally:
                release.set()
                if self.log: self.log.close()

    def test_shutdown_timeout_latches_without_hanging(self):
        entered, release = Event(), Event()
        original = StrictRotatingHandler.emit
        def slow(handler, record):
            entered.set()
            release.wait(2)
            return original(handler, record)
        with patch.object(StrictRotatingHandler, 'emit', slow):
            try:
                log = self.start()
                self.assertTrue(entered.wait(1))
                log.close(timeout=.01)
                self.assertEqual(log.status()['failure'], 'shutdown_timeout')
            finally:
                release.set()
                if self.log: self.log.close()

    def test_multithread_sequence_is_unique(self):
        log = self.start(capacity=8192)
        threads = [Thread(target=lambda: [log.emit('runtime_started') for _ in range(100)]) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        log.close()
        data = rows(self.directory)
        self.assertEqual(len(data), 402)
        self.assertEqual([r['sequence'] for r in data], list(range(1, 403)))

    def test_invalid_event_fails_closed_without_logging_text(self):
        log = self.start()
        self.assertFalse(log.emit(SECRET))
        self.assertEqual(log.status()['failure'], 'invalid_event')

    def test_allowlisted_context_is_readable_and_unknown_values_hidden(self):
        log = self.start()
        log.emit('inventory_plan_changed', blockers=('exit_terms_missing', SECRET),
                 command='inventory', endpoint='/markets/{ticker}', mode='blocked')
        log.close()
        data = next(r for r in rows(self.directory) if r['event']=='inventory_plan_changed')
        self.assertEqual(data['context']['blockers'], ['exit_terms_missing'])
        self.assertEqual(data['context']['unknown_blockers'], 1)
        self.assertEqual(data['context']['command'], 'inventory')
        self.assertEqual(data['context']['endpoint'], '/markets/{ticker}')
        self.assertNotIn(SECRET, json.dumps(data))

    def test_bounded_venue_error_code_is_readable_but_text_is_discarded(self):
        log = self.start()
        log.emit('mutation_rejected', http_status=400,
                 venue_code='invalid_order', message=SECRET)
        log.close()
        data = next(r for r in rows(self.directory)
                    if r['event'] == 'mutation_rejected')
        self.assertEqual(data['context']['venue_code'], 'invalid_order')
        self.assertNotIn(SECRET, json.dumps(data))

    def test_startup_permission_failure_is_visible(self):
        self.log = Diagnostics(self.directory)
        with patch('kalshi_bot.observability.StrictRotatingHandler', side_effect=PermissionError(SECRET)):
            with self.assertRaises(InvalidData): self.log.start()
        self.assertEqual(self.log.status()['failure'], 'sink_failure')
        self.assertEqual(self.log.status()['failure_detail'][0]['type'], 'PermissionError')
        self.assertNotIn(SECRET, json.dumps(self.log.status()))

    def test_rotation_io_error_is_not_swallowed_by_stdlib_handler(self):
        log = self.start()
        with patch.object(StrictRotatingHandler, 'shouldRollover', side_effect=OSError(SECRET)):
            log.emit('runtime_started')
            deadline = time.monotonic()+2
            while not log.status()['failure'] and time.monotonic()<deadline:
                time.sleep(.001)
        self.assertEqual(log.status()['failure'], 'sink_failure')

    def test_cannot_reuse_closed_service(self):
        log = self.start()
        log.close()
        with self.assertRaises(InvalidData): log.start()
        self.assertFalse(log.emit('runtime_started'))

    def test_cli_preflight_opt_in_writes_only_diagnostics(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(['preflight', '--log-dir', str(self.directory)])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(data['live_ready'])
        self.assertFalse(data['credentials_accessed'])
        self.assertTrue(data['creates_files'])
        self.assertIsNone(data['logging']['failure'])
        self.assertIn('preflight_blocked', [r['event'] for r in rows(self.directory)])

    def test_cli_exception_output_does_not_echo_config_or_path(self):
        out = io.StringIO()
        with patch('kalshi_bot.cli.BotConfig.load', side_effect=ValueError(SECRET)), redirect_stdout(out):
            code = main(['policy', '--log-dir', str(self.directory)])
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET, out.getvalue()+json.dumps(rows(self.directory)))
        self.assertEqual(json.loads(out.getvalue())['error'], 'cli_failed')


class LoggingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.log = await asyncio.to_thread(Diagnostics(self.path/'logs').start)
        self.writer = await LedgerWriter(self.path/'ledger.db', diagnostics=self.log).start()
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.writer.close()
        await asyncio.to_thread(self.log.close)
        self.temp.cleanup()

    async def data(self):
        await asyncio.to_thread(self.log.close)
        return rows(self.path/'logs')

    def runtime(self, factory=None):
        async def noop(*args): pass
        return RecoveryRuntime(self.writer, AccountReads(), factory or FakeReader, tickers=('A',),
            subaccount=0, history_start=NOW-timedelta(hours=1), now=lambda: NOW, evaluate=noop,
            deadline_handler=noop, lifecycle_handler=noop, diagnostics=self.log,
            sleep=lambda _: asyncio.sleep(.001), attempts=2)

    async def test_writer_preserves_failure_context_and_poison(self):
        with patch.object(LedgerWriter, '_execute', side_effect=RuntimeError(SECRET)):
            with self.assertRaises(InvalidData): await self.writer.inventory()
        self.assertTrue(self.writer.failed)
        data = await self.data()
        errors = [r for r in data if r['event']=='writer_failed']
        self.assertTrue(errors)
        self.assertEqual(errors[0]['context']['command'], 'inventory')
        self.assertNotIn(SECRET, json.dumps(data))

    async def test_health_summary_is_bounded_and_missing_snapshot_is_not_zero_orders(self):
        runtime = self.runtime()
        for reason in ('snapshot_freshness', 'mutation_persisted', 'snapshot_freshness', SECRET):
            runtime.request_recovery(reason)
        runtime._diagnostic_summary()
        data = await self.data()
        row = next(r for r in data if r['event']=='runtime_health')
        self.assertEqual(row['context']['recovery_requests'], 4)
        self.assertNotIn('resting_orders', row['context'])
        self.assertEqual(runtime.recovery_request_counts,
                         {'snapshot_freshness': 2, 'mutation_persisted': 1, 'unknown': 1})
        self.assertNotIn(SECRET, json.dumps(data))

    async def test_recovery_failure_retains_stage_and_readable_trigger(self):
        runtime = self.runtime()
        runtime.account_subscribed = True
        runtime.account.connected = True
        async def failure(*args, **kwargs):
            raise TimeoutError(SECRET)
        async def quit_retry(_):
            runtime.stop_requested.set()
        runtime.sleep = quit_retry
        runtime.request_recovery('snapshot_freshness')
        with patch.object(runtime.account, 'reconcile', side_effect=failure):
            await runtime._recover()
        data = await self.data()
        failed = next(r for r in data if r['event']=='recovery_failed')
        self.assertEqual(failed['context']['cause'], 'snapshot_freshness')
        self.assertEqual(failed['context']['phase'], 'first_snapshot')
        self.assertEqual(runtime.recovery_phase, 'idle')
        self.assertEqual(runtime.recovery_attempt_counts, {'snapshot_freshness': 1})
        self.assertNotIn(SECRET, json.dumps(data))

    async def test_rest_status_retries_are_logged_without_queries(self):
        responses = iter([WireResponse(503, b''), WireResponse(200, b'{}')])
        async def sleep(_): pass
        reads = RestReads(TokenBudget(rate=100, capacity=100, default_cost=1, sleep=sleep),
                          wire=lambda *_: next(responses), diagnostics=self.log)
        await reads.read('market', ticker='A', reason='metadata')
        await reads.close()
        events = await self.data()
        retry = next(r for r in events if r['event']=='rest_retry')
        self.assertEqual(retry['context']['http_status'], 503)
        self.assertEqual(retry['context']['attempt'], 1)

    async def test_rest_auth_rejection_is_not_retried(self):
        calls = []
        def wire(*_):
            calls.append(1)
            return WireResponse(401, SECRET.encode())
        reads = RestReads(TokenBudget(rate=100, capacity=100, default_cost=1), wire=wire, diagnostics=self.log)
        with self.assertRaises(ReadFailure): await reads.read('market', ticker='A', reason='metadata')
        await reads.close()
        self.assertEqual(len(calls), 1)
        self.assertNotIn(SECRET, json.dumps(await self.data()))

    async def test_transport_cause_is_logged_before_sanitized_exception(self):
        def wire(*_): raise OSError(SECRET)
        reads = RestReads(TokenBudget(rate=100, capacity=100, default_cost=1), wire=wire, diagnostics=self.log)
        with self.assertRaisesRegex(InvalidData, 'read transport failed'):
            await reads.read('market', ticker='A', reason='metadata')
        await reads.close()
        data = await self.data()
        self.assertTrue(any(r['event']=='rest_transport_failed' for r in data))
        self.assertNotIn(SECRET, json.dumps(data))

    async def test_ambiguous_mutation_not_retried_and_correlation_retained(self):
        calls = []
        async def invoke(*_):
            calls.append(1)
            raise TimeoutError(SECRET)
        executor = InjectedExecutor(self.writer, invoke=invoke, validate_proof=lambda *_: True,
            offline_fixture=True, now=lambda: NOW, diagnostics=self.log)
        prepared = await self.writer.reserve_entry(request(), attempt_id='attempt-a',
            view=await self.writer.portfolio(subaccount=0, now=NOW), config=BotConfig(),
            now=NOW, free_cash='500', account_known=True, offline_fixture=True)
        self.assertTrue(prepared.reserved, prepared.blockers)
        with self.assertRaises(TimeoutError):
            await executor.execute_prepared(prepared.receipt)
        with self.assertRaises(CommandDenied):
            await executor.execute_prepared(prepared.receipt)
        self.assertEqual(len(calls), 1)
        self.assertEqual((await self.writer.mutations())[0]['phase'], 'UNKNOWN')
        data = [r for r in await self.data() if r['component']=='execution']
        self.assertIn('mutation_unknown', [r['event'] for r in data])
        self.assertEqual(len({r['context']['operation_ref'] for r in data}), 1)

    async def test_unexpected_runtime_fault_stops_peers_and_propagates(self):
        def factory(_): raise RuntimeError(SECRET)
        runtime = self.runtime(factory)
        with self.assertRaises(RuntimeError): await runtime.run()
        self.assertFalse(runtime.running)
        self.assertTrue(runtime.engine.stopped)
        self.assertFalse(runtime.account.connected)
        self.assertTrue(any(r['event']=='runtime_failed' for r in await self.data()))

    async def test_logging_failure_stops_idle_runtime(self):
        runtime = self.runtime()
        task = asyncio.create_task(runtime.run())
        self.tasks.append(task)
        await asyncio.sleep(.02)
        self.log._fail('sink_failure')
        with self.assertRaises(InvalidData): await asyncio.wait_for(asyncio.shield(task), 1)
        self.assertTrue(runtime.engine.stopped)
        self.assertFalse(runtime.account.connected)
        self.assertEqual(runtime.status()['logging']['failure'], 'sink_failure')

    async def test_cancellation_is_recorded_as_control_not_runtime_error(self):
        runtime = self.runtime()
        task = asyncio.create_task(runtime.run())
        self.tasks.append(task)
        await asyncio.sleep(.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        codes = [r['event'] for r in await self.data()]
        self.assertIn('runtime_cancelled', codes)
        self.assertNotIn('runtime_failed', codes)

    async def test_engine_callback_failure_invalidates_book_and_reports_location(self):
        runtime = self.runtime()
        async def crash(*_): raise RuntimeError(SECRET)
        runtime.engine.deadline_handler = crash
        runtime.engine.schedule('A', runtime.clock())
        with self.assertRaises(RuntimeError): await runtime.engine.step()
        self.assertTrue(runtime.engine.failed)
        self.assertTrue(all(s.failed for s in runtime.engine.shards.values()))
        data = await self.data()
        self.assertTrue(any(r['event']=='engine_failed' for r in data))
        self.assertNotIn(SECRET, json.dumps(data))

    async def test_reader_exhaustion_records_bounded_attempts(self):
        class BrokenReader:
            def __init__(self, spec): pass
            async def run(self, consume): raise OSError(SECRET)
        runtime = self.runtime(BrokenReader)
        spec = next(s for s in runtime.specs if s.name=='account')
        await runtime._connection_round(spec)
        self.assertEqual(runtime.reader_states['account'], 'retry_exhausted')
        self.assertFalse(runtime.account.connected)
        data = await self.data()
        self.assertEqual(len([r for r in data if r['event']=='reader_failed']), 2)
        self.assertEqual(len([r for r in data if r['event']=='reader_exhausted']), 1)
