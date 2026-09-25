"""Opt-in bounded JSONL diagnostics. No credentials, payloads or exception text.

Start/close outside the event loop (or via to_thread). Producers enqueue bounded
records; a single worker owns rotation and disk I/O. Never a financial journal.
"""
from collections import deque
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread
import time
from uuid import uuid4

from .values import InvalidData, integer
from .windows import WindowsLease

# Static event names are also the error codes. Never interpolate message text.
EVENTS = {
    'fill_risk_withdrawal': ('INFO', 'inventory'),
    'supervisor_started': ('INFO', 'supervisor'),
    'supervisor_stopped': ('INFO', 'supervisor'),
    'supervisor_failed': ('ERROR', 'supervisor'),
    'supervisor_control_failed': ('ERROR', 'supervisor'),
    'supervisor_child_started': ('INFO', 'supervisor'),
    'supervisor_child_stopped': ('INFO', 'supervisor'),
    'supervisor_child_exited': ('INFO', 'supervisor'),
    'supervisor_child_failed': ('ERROR', 'supervisor'),
    'log_started': ('INFO', 'logging'), 'log_stopped': ('INFO', 'logging'),
    'runtime_started': ('INFO', 'runtime'), 'runtime_stopped': ('INFO', 'runtime'),
    'runtime_failed': ('ERROR', 'runtime'), 'runtime_cancelled': ('INFO', 'runtime'),
    'reader_connecting': ('INFO', 'stream'), 'reader_subscribed': ('INFO', 'stream'),
    'reader_failed': ('WARNING', 'stream'), 'reader_exhausted': ('ERROR', 'stream'),
    'reader_retry_wait': ('WARNING', 'stream'),
    'recovery_started': ('INFO', 'recovery'), 'recovery_failed': ('WARNING', 'recovery'),
    'recovery_incomplete': ('WARNING', 'recovery'), 'recovery_repaired': ('INFO', 'recovery'),
    'recovery_progressed': ('INFO', 'recovery'),
    'safety_recovery_rearmed': ('INFO', 'recovery'),
    'recovery_retry_wait': ('WARNING', 'recovery'),
    'recovery_exhausted': ('ERROR', 'recovery'),
    'book_proof_lost': ('WARNING', 'engine'), 'private_ingress_failed': ('ERROR', 'engine'),
    'engine_failed': ('ERROR', 'engine'), 'engine_cancelled': ('INFO', 'engine'),
    'rest_retry': ('WARNING', 'rest'), 'rest_failed': ('ERROR', 'rest'),
    'rest_transport_failed': ('ERROR', 'rest'),
    'rest_close_failed': ('ERROR', 'rest'),
    'writer_failed': ('ERROR', 'writer'), 'writer_overflow': ('ERROR', 'writer'),
    'mutation_prepared': ('INFO', 'execution'), 'mutation_sending': ('INFO', 'execution'),
    'mutation_ack': ('INFO', 'execution'), 'mutation_rejected': ('WARNING', 'execution'),
    'mutation_unknown': ('ERROR', 'execution'),
    'mutation_not_submitted': ('INFO', 'execution'),
    'mutation_failed': ('ERROR', 'execution'), 'inventory_plan_changed': ('INFO', 'inventory'),
    'selection_inputs_rejected': ('WARNING', 'selection'),
    'reward_reflection_failed': ('WARNING', 'rewards'),
    'candidate_scope_prepared': ('INFO', 'selection'),
    'incentives_retry': ('WARNING', 'selection'),
    'incentives_exhausted': ('ERROR', 'selection'),
    'incentives_failed': ('ERROR', 'selection'),
    'cli_failed': ('ERROR', 'cli'), 'preflight_blocked': ('WARNING', 'cli'),
    'exit_inputs_published': ('INFO','metadata'), 'exit_inputs_failed': ('ERROR','metadata'),
    'exit_inputs_superseded': ('INFO', 'metadata'),
    'exit_inputs_deferred': ('INFO', 'metadata'),
    'history_enumerated': ('INFO', 'recovery'),
    'history_omission': ('WARNING', 'recovery'),
    'metadata_retry': ('WARNING', 'metadata'), 'metadata_exhausted': ('ERROR', 'metadata'),
    'metadata_scheduler_failed': ('ERROR', 'metadata'),
    'metadata_dependency_failed': ('ERROR', 'metadata'),
    'read_budget_updated': ('INFO', 'rest'), 'read_budget_failed': ('ERROR', 'rest'),
    'quota_refresh_started': ('INFO', 'rest'), 'quota_fresh': ('INFO', 'rest'),
    'quota_stale': ('WARNING', 'rest'), 'quota_retry': ('WARNING', 'rest'),
    'quota_exhausted': ('ERROR', 'rest'), 'quota_clock_fault': ('ERROR', 'rest'),
    'quota_stopped': ('INFO', 'rest'),
    'quota_rollover_deferred': ('INFO', 'rest'),
}
NUMBERS = frozenset(('attempt', 'generation', 'revision', 'backlog', 'http_status', 'blocker_count', 'elapsed_ms',
                     'reviewed_markets', 'initial_websocket_markets', 'incentive_rows',
                     'market_rows', 'milestone_rows', 'exit_code'))
REFERENCES = frozenset(('market', 'operation', 'order', 'reason'))
SAFE_CODES = frozenset(('venue_code',))
ENUMS = {'stream': frozenset(('account', 'lifecycle', 'book-0', 'book-1')),
         'command': frozenset(('close', 'fill', 'stage_fill', 'pending_fills', 'apply_pending', 'observe',
            'market_inventory', 'portfolio', 'reserve_entry', 'inventory', 'reconcile_snapshot', 'order',
            'orders', 'order_batch', 'fill_scope', 'order_evidence', 'recover_fills', 'venue_snapshot',
            'stream_cost', 'exit_basis', 'history', 'history_complete', 'history_coverage',
            'reserve', 'transition', 'mutation', 'mutations')),
         'endpoint': frozenset(('/portfolio/orders/{order_id}', '/portfolio/orders', '/portfolio/positions',
            '/portfolio/fills', '/historical/fills', '/historical/orders', '/historical/cutoff',
            '/portfolio/balance', '/account/limits', '/account/endpoint_costs', '/incentive_programs',
            '/markets', '/events', '/milestones', '/portfolio/orders/queue_positions',
            '/markets/{ticker}', '/events/{event_ticker}', '/series/{series_ticker}',
            '/milestones/{milestone_id}', '/events/fee_changes', '/series/fee_changes')),
         'mode': frozenset(('flat', 'wait', 'attention', 'blocked', 'passive', 'passive_deferred',
                            'cancel_before_ioc', 'ioc'))}
BLOCKERS = frozenset('''account_scope_conflict unbound_intent pending_fills exit_journal_scope_conflict
    incomplete_order_scope unowned_order_or_unaccounted_fills no_passive_touch
    await_terminal_cancellation_and_fill_proof live_authorization_missing inventory_age_unknown
    inventory_clock_regressed exit_terms_missing ioc_terminal_fill_proof_pending cancel_confirmation_pending
    incomplete_exit_scope inventory_basis_or_clock_unknown exit_terms_stale market_not_tradable
    exit_book_unavailable exit_journal_unknown event_risk_time_unknown exit_fee_bound_unknown
    ioc_attempt_limit ioc_retry_window ordinary_exit_depth_or_loss forced_exit_insufficient_depth
    timing_review_missing timing_review_conflict milestone_binding_conflict fee_profile_missing
    fee_model_unsupported identical_reduction_rejection_cooldown'''.split())


def safe_error(exc):
    """Bound chains/groups and stacks without formatting messages, source or locals."""
    pending, seen, result = deque([exc]), set(), []
    while pending and len(result) < 4:
        error = pending.popleft()
        if id(error) in seen:
            continue
        seen.add(id(error))
        kind = ('cancelled' if isinstance(error, BaseException) and type(error).__name__ == 'CancelledError'
                else 'timeout' if isinstance(error, TimeoutError)
                else 'validation' if isinstance(error, InvalidData)
                else 'io' if isinstance(error, OSError) else 'unexpected')
        frames = deque(maxlen=12)
        tb = error.__traceback__
        for _ in range(64):
            if tb is None:
                break
            code = tb.tb_frame.f_code
            # Module name, function, line only for our own code; no user paths.
            module = tb.tb_frame.f_globals.get('__name__', '')
            own = isinstance(module, str) and module.startswith('kalshi_bot.')
            frames.append({'module': module[:80] if own else 'external',
                           'function': code.co_name[:80] if own else 'external', 'line': tb.tb_lineno})
            tb = tb.tb_next
        error_type = type(error)
        trusted_type = (error_type.__module__ in {'builtins', 'sqlite3', 'asyncio.exceptions'}
                        or error_type.__module__.startswith(('kalshi_bot.', 'websockets.')))
        result.append({'category': kind, 'type': error_type.__name__[:80] if trusted_type else 'ExternalError',
                       'frames': list(frames)})
        if isinstance(error, OSError) and type(error.errno) is int:
            result[-1]['errno'] = error.errno
        if isinstance(error, BaseExceptionGroup):
            pending.extend(error.exceptions[:4])
        linked = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
        if linked is not None:
            pending.append(linked)
    return result


class NullDiagnostics:
    def emit(self, *args, **kwargs): return False
    def ensure_healthy(self): pass
    def status(self): return {'enabled': False, 'healthy': False}


NO_LOG = NullDiagnostics()


class StrictRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        # stdlib otherwise prints raw record/exception to stderr and suppresses it.
        # Propagate only to our worker, which stores safe type/errno/frames.
        raise


class Diagnostics:
    def __init__(self, directory, *, capacity=1024, max_bytes=5*1024*1024, backups=4):
        self.directory = Path(directory).resolve()
        self.capacity = integer(capacity, 1, 8192)
        self.max_bytes = integer(max_bytes, 32768, 64*1024*1024)
        self.backups = integer(backups, 1, 16)
        self.run_id = uuid4().hex
        self._salt = uuid4().bytes
        self._queue = Queue(self.capacity)
        self._lock, self._ready, self._stop = Lock(), Event(), Event()
        self._thread = None
        self._failure = None
        self._failure_detail = None
        self._sequence = self._accepted = self._written = self._dropped = self._high_water = 0

    def start(self):
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                raise InvalidData('diagnostics cannot be reused')
            self._thread = Thread(target=self._run, name='kalshi-diagnostics', daemon=True)
            self._thread.start()
        if not self._ready.wait(5):
            self._fail('startup_timeout')
            self._stop.set()
        self.ensure_healthy()
        self.emit('log_started')
        return self

    def _fail(self, reason, error=None):
        with self._lock:
            if self._failure is None:
                self._failure = reason
                self._failure_detail = safe_error(error) if isinstance(error, BaseException) else None

    def ensure_healthy(self):
        with self._lock:
            healthy = self._ready.is_set() and not self._failure and not self._stop.is_set()
        if not healthy:
            raise InvalidData('diagnostics unavailable; inspect logging health')

    def status(self):
        with self._lock:
            return dict(enabled=True, run_id=self.run_id,
                        healthy=self._ready.is_set() and not self._failure and not self._stop.is_set(),
                        failure=self._failure, failure_detail=self._failure_detail,
                        max_bytes=self.max_bytes, backups=self.backups,
                        retention_bytes=self.max_bytes*(self.backups+1),
                        accepted=self._accepted, written=self._written,
                        dropped=self._dropped, backlog=self._queue.qsize(), high_water=self._high_water,
                        closed=self._stop.is_set(),
                        worker_alive=bool(self._thread and self._thread.is_alive()))

    def emit(self, event, *, error=None, **fields):
        # All unknown fields (including payloads/headers) are discarded, not repr'd.
        if type(event) is not str or event not in EVENTS:
            self._fail('invalid_event')
            with self._lock:
                self._dropped += 1
            return False
        with self._lock:
            if not self._ready.is_set() or self._failure or self._stop.is_set():
                self._dropped += 1
                return False
        try:
            context = {}
            for key in NUMBERS:
                value = fields.get(key)
                if type(value) is int and 0 <= value < 2**63:
                    context[key] = value
            for key, allowed in ENUMS.items():
                value = fields.get(key)
                if type(value) is str and value in allowed:
                    context[key] = value
            for key in REFERENCES:
                value = fields.get(key)
                if type(value) is str and len(value) <= 2048:
                    context[key+'_ref'] = hmac.new(self._salt, value.encode(), hashlib.sha256).hexdigest()[:24]
            for key in SAFE_CODES:
                value = fields.get(key)
                if (type(value) is str and len(value) <= 100 and value.isascii()
                        and all(character.isalnum() or character in '._-'
                                for character in value)):
                    context[key] = value
            blockers = fields.get('blockers')
            if type(blockers) in (tuple, list) and len(blockers) <= 64:
                context['blockers'] = [b for b in blockers if type(b) is str and b in BLOCKERS]
                context['unknown_blockers'] = len(blockers)-len(context['blockers'])
            severity, component = EVENTS[event]
            row = dict(schema=1, utc=datetime.now(timezone.utc).isoformat(), monotonic_ns=time.monotonic_ns(),
                       run_id=self.run_id, severity=severity, component=component, event=event, context=context)
            if isinstance(error, BaseException):
                row['errors'] = safe_error(error)
            with self._lock:
                if self._stop.is_set() or self._failure:
                    self._dropped += 1
                    return False
                self._sequence += 1
                row['sequence'] = self._sequence
                encoded = json.dumps(row, separators=(',', ':'), ensure_ascii=True)
                if len(encoded) > 16384:
                    self._failure = 'record_overflow'
                    self._dropped += 1
                    return False
                try:
                    self._queue.put_nowait(encoded)
                except Full:
                    self._failure = 'queue_overflow'
                    self._dropped += 1
                    return False
                self._accepted += 1
                self._high_water = max(self._high_water, self._queue.qsize())
            return True
        except Exception as exc:
            self._fail('encoding_failure', exc)
            with self._lock:
                self._dropped += 1
            return False

    def _run(self):
        handler = None
        try:
            # Exclusive native Windows ownership prevents overlapping rotation.
            with WindowsLease('diagnostics:'+str(self.directory)):
                self.directory.mkdir(parents=True, exist_ok=True)
                handler = StrictRotatingHandler(self.directory/'events.jsonl', maxBytes=self.max_bytes,
                                               backupCount=self.backups, encoding='utf-8')
                self._ready.set()
                while not self._stop.is_set() or not self._queue.empty():
                    try:
                        encoded = self._queue.get(timeout=.05)
                    except Empty:
                        continue
                    try:
                        handler.emit(logging.LogRecord('kalshi', logging.INFO, '', 0, encoded, (), None))
                        with self._lock:
                            self._written += 1
                    finally:
                        self._queue.task_done()
                handler.close()
                handler = None
        except BaseException as exc:
            self._fail('sink_failure', exc)
        finally:
            if handler is not None:
                try:
                    handler.close()
                except Exception as exc:
                    self._fail('sink_close_failure', exc)
            self._ready.set()

    def close(self, timeout=5):
        if not 0 < timeout <= 10:
            raise InvalidData('bounded diagnostic shutdown required')
        if not self._stop.is_set():
            self.emit('log_stopped')
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                self._fail('shutdown_timeout')

    def __enter__(self): return self.start()
    def __exit__(self, *_): self.close()
