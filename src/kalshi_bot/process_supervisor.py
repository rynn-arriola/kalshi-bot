"""Native Windows S2A supervisor for one fixed inert child only."""
import asyncio
from collections import deque
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from .supervision import (AttentionReason, ChildOutcome, ChildPhase, EventKind,
                          SupervisorAction, SupervisorEvent, SupervisorPolicy,
                          SupervisorState)
from .supervisor_control import ControlOwner, ScopeSpec
from .supervisor_control import retain
from .observability import Diagnostics, safe_error
from .supervisor_fixture import (build_fingerprint, config_fingerprint,
                                 fixture_path, repository_root, source_path)
from .supervisor_protocol import (CHILD_KINDS, Envelope, MessageKind,
                                  SequenceTracker, validate_peer)
from .values import InvalidData, identity
from .windows import (WindowsPowerMonitor, WindowsRoleLease, WindowsStopLatch,
                      _close_handle, inheritable_parent_handle)
from .windows_ipc import PipeServer, supervisor_pipe_name


class OwnedChild:
    """Spawn preparation retained by the host even after uncertain failures."""
    def __init__(self, scope, stop_latch, *, parent_session, child_id,
                 child_generation, mode, launch_guard=None):
        self.scope, self.stop_latch = scope, stop_latch
        self.parent_session = identity(parent_session)
        self.child_id = identity(child_id)
        self.child_generation = child_generation
        self.mode = mode
        self.launch_guard = launch_guard
        self.lease = WindowsRoleLease(scope.scope_id, "child",
                                      user_sid=scope.approved_user_sid)
        self.server = None
        self.endpoint = None
        self.process = None
        self.created = False
        self.creation_attempted = False
        self.result = None
        self.stop_hint_sent = False
        self._bind_task = None
        self._close_task = None
        self.cleanup_error = None

    def validate_launch(self, state):
        if (self.stop_latch.requested or not state.desired_armed or state.stop_latched
                or state.build_fingerprint != build_fingerprint()
                or state.config_fingerprint != config_fingerprint(self.mode)):
            raise InvalidData("native launch authority revoked")
        if self.launch_guard is not None:
            self.launch_guard()

    def acquire_presence(self):
        self.lease.__enter__()

    def release_presence(self):
        if self.created or self.creation_attempted:
            return
        if self.server is not None:
            self.server.close()
            self.server = None
        if self.lease.handle is not None:
            self.lease.__exit__()

    def _environment(self, venv_launcher):
        allowed = {}
        for key in ("SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC"):
            value = os.environ.get(key)
            if value:
                allowed[key] = value
        allowed.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                       __PYVENV_LAUNCHER__=str(venv_launcher))
        return allowed

    def spawn(self):
        handles = []
        try:
            return self._spawn_owned(handles)
        finally:
            # Protect partial setup too: every successful acquisition is tracked.
            error = None
            for handle in reversed(handles):
                try:
                    _close_handle(handle)
                except BaseException as exc:
                    error = error or exc
            if error is not None:
                raise error

    def _spawn_owned(self, handles):
        nonce = uuid4().hex
        pipe = supervisor_pipe_name(self.scope.digest, nonce)
        self.server = PipeServer(pipe, user_sid=self.scope.approved_user_sid)
        lifetime = self.lease.duplicate_inheritable()
        handles.append(lifetime)
        stop = self.stop_latch.duplicate_inheritable()
        handles.append(stop)
        parent = inheritable_parent_handle()
        handles.append(parent)
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": list(handles)}
        venv_launcher = Path(sys.executable).resolve(strict=True)
        base_executable = Path(sys._base_executable).resolve(strict=True)
        command = [str(base_executable), "-B", str(fixture_path()),
            "--pipe-name", pipe,
            "--scope-digest", self.scope.digest,
            "--scope-id", self.scope.scope_id,
            "--parent-session", self.parent_session,
            "--child-id", self.child_id,
            "--child-generation", str(self.child_generation),
            "--store-path", str(self.scope.store_path),
            "--control-root", str(self.scope.control_root),
            "--environment", self.scope.environment,
            "--account-scope", self.scope.account_scope,
            "--approved-user-sid", self.scope.approved_user_sid,
            "--source-path", str(source_path()),
            "--mode", self.mode,
            "--lifetime-handle", str(lifetime),
            "--stop-handle", str(stop),
            "--parent-handle", str(parent)]
        if self.launch_guard is not None:
            self.launch_guard()
        if self.stop_latch.requested:
            raise InvalidData("native launch stopped during setup")
        self.creation_attempted = True
        self.process = subprocess.Popen(command, cwd=repository_root(),
                env=self._environment(venv_launcher), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                shell=False, close_fds=True, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW)
        self.created = True
        return self

    async def bind(self):
        if self._bind_task is None:
            self._bind_task = asyncio.create_task(self._bind_owned())
        return await retain(self._bind_task)

    async def _bind_owned(self):
        if not self.created or self.process.poll() is not None:
            raise InvalidData("native child exited before IPC binding")
        self.endpoint = await asyncio.to_thread(self.server.accept, timeout=10,
                                                expected_pid=self.process.pid)
        self.server = None
        if self.process.poll() is not None:
            raise InvalidData("native child exited during IPC binding")
        return self.endpoint

    def poll_exit(self):
        return self.process.poll() if self.process is not None else None

    def request_stop(self):
        self.stop_latch.request_owned()

    async def close_after_exit(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_owned())
        await retain(self._close_task)

    async def _close_owned(self):
        if self.process is None or self.process.poll() is None:
            raise InvalidData("native child exit is not confirmed")
        if self.endpoint is not None:
            while not self.endpoint.closed:
                try:
                    await asyncio.to_thread(self.endpoint.close_and_join, 1)
                except InvalidData:
                    self.cleanup_error = [{"category": "ipc", "type": "ClosePending", "frames": []}]
                    await asyncio.sleep(.1)
            self.endpoint = None
        if self.server is not None:
            await self._retry_close(self.server.close)
            self.server = None
        if self.lease.handle is not None:
            await self._retry_close(self.lease.__exit__)
            self.created = False

    async def _retry_close(self, operation):
        while True:
            try:
                operation()
                return
            except BaseException as exc:
                self.cleanup_error = safe_error(exc)
                await asyncio.sleep(1)


class SupervisorHost:
    """One native parent loop. It can launch only the fixed inert S2A fixture."""
    def __init__(self, scope: ScopeSpec, *, fixture_mode="normal",
                 policy=SupervisorPolicy()):
        if not isinstance(scope, ScopeSpec):
            raise InvalidData("typed supervisor scope required")
        config_fingerprint(fixture_mode)
        self.scope, self.fixture_mode, self.policy = scope, fixture_mode, policy
        self.parent_session = uuid4().hex
        self.owner = None
        self.controller_state = None
        self.child = None
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.shutdown_requested = False
        self.last_error = None
        self._control_sequence = 0
        self._pulse_sequence = 0
        self._inbound = SequenceTracker()
        self.loop_wakes = 0
        self.max_incoming_backlog = 0
        self.child_exits = 0
        self.validated_results = 0
        self.policy_latencies_ms = deque(maxlen=4096)
        self.diagnostics = Diagnostics(scope.control_root / "parent-logs",
                                       max_bytes=262144, backups=2)
        self._power = None
        self._stop_latch = None
        self._run_task = None

    def _guard(self):
        self.diagnostics.ensure_healthy()
        if self.shutdown_requested or (self._power and self._power.changed.is_set()):
            raise InvalidData("supervisor authority invalidated")

    def _record_fault(self, exc):
        if self.last_error is None:
            self.last_error = safe_error(exc)
            self.diagnostics.emit("supervisor_failed", error=exc,
                                  operation=self.parent_session)

    def _signal_stop(self):
        if self._stop_latch is not None:
            self._stop_latch.request_owned()

    @property
    def fingerprints(self):
        return build_fingerprint(), config_fingerprint(self.fixture_mode)

    async def _apply(self, event):
        began = time.perf_counter()
        receipt = await self.owner.submit("apply", event)
        self.policy_latencies_ms.append((time.perf_counter()-began)*1000)
        self.controller_state = receipt.state
        for action in (() if receipt.decision is None else receipt.decision.actions):
            if action == SupervisorAction.REQUEST_GRACEFUL_STOP:
                self._signal_stop()
        return receipt

    async def request_shutdown(self):
        self.shutdown_requested = True
        try:
            if self.owner is not None and not self.owner.closed:
                await self._apply(SupervisorEvent(EventKind.STOP, time.time()))
        finally:
            WindowsStopLatch.request(self.scope.scope_id,
                user_sid=self.scope.approved_user_sid)

    def _validate_common(self, envelope):
        if self.child is None:
            raise InvalidData("supervisor child envelope identity mismatch")
        return validate_peer(envelope, scope_digest=self.scope.digest,
            parent_session=self.parent_session, child_id=self.child.child_id,
            child_generation=self.child.child_generation, allowed=CHILD_KINDS,
            tracker=self._inbound, now_ns=time.monotonic_ns())

    def _outbound(self, kind, payload, *, coalesced=False):
        if coalesced:
            self._pulse_sequence += 1
            sequence = self._pulse_sequence
        else:
            self._control_sequence += 1
            sequence = self._control_sequence
        return Envelope(self.scope.digest, self.parent_session,
            self.child.child_id, self.child.child_generation, kind, sequence,
            time.monotonic_ns(), payload)

    async def _spawn(self, state):
        self._guard()
        build, config = self.fingerprints
        if (state.build_fingerprint != build
                or state.config_fingerprint != config):
            await self._apply(SupervisorEvent(EventKind.LOCAL_SAFETY_FAULT,
                time.time(), attention_reason=AttentionReason.IPC_FAILURE))
            return
        child_id = uuid4().hex
        factory = OwnedChild(self.scope, self._stop_latch,
            parent_session=self.parent_session, child_id=child_id,
            child_generation=state.generation, mode=self.fixture_mode,
            launch_guard=self._guard)
        event = SupervisorEvent(EventKind.START_REQUESTED, time.time(),
            expected_generation=state.generation, child_id=child_id)
        self.child = factory
        try:
            receipt = await self.owner.submit("spawn", event, self.parent_session,
                                              factory)
        except BaseException:
            if not factory.created and not factory.creation_attempted:
                self.child = None
            raise
        self.controller_state = receipt.state
        if not receipt.spawned:
            self.child = None
            if receipt.state.stop_latched:
                self._signal_stop()
            return
        self.child = receipt.value
        await self._apply(SupervisorEvent(EventKind.CHILD_STARTED, time.time(),
            expected_generation=self.child.child_generation,
            child_id=self.child.child_id))
        try:
            endpoint = await self.child.bind()
            self._guard()
            hello = await asyncio.to_thread(endpoint.receive, 10)
            self._guard()
            if hello is None:
                raise InvalidData("native child HELLO timed out")
            self._validate_common(hello)
            if hello.kind != MessageKind.HELLO:
                raise InvalidData("native child did not send HELLO first")
            build, config = self.fingerprints
            if hello.payload != dict(build_fingerprint=build,
                    config_fingerprint=config, fixture_mode=self.fixture_mode):
                raise InvalidData("native child fingerprint mismatch")
            bound = await self.owner.submit("stage", dict(
                parent_session=self.parent_session, child_id=self.child.child_id,
                child_generation=self.child.child_generation, stage="bound",
                diagnostic_pid=self.child.process.pid))
            current = await self.owner.submit("read")
            self._guard()
            if (current.revision != bound.revision or current.state.stop_latched
                    or current.state.child_id != self.child.child_id
                    or current.native.stage != "bound"):
                raise InvalidData("native child admission was revoked")
            endpoint.send_control(self._outbound(MessageKind.ADMIT,
                dict(control_revision=current.revision)))
        except BaseException as exc:
            self._record_fault(exc)
            await self._apply(SupervisorEvent(EventKind.LOCAL_SAFETY_FAULT,
                time.time(), attention_reason=AttentionReason.IPC_FAILURE))
            self.child.request_stop()

    async def _message(self, message):
        age = self._validate_common(message)
        if message.kind == MessageKind.STATUS:
            if self._power and self._power.changed.is_set():
                raise InvalidData("supervisor power state invalidated")
            if self.child.result is not None:
                raise InvalidData("supervisor status after result")
            phase = ChildPhase(message.payload["phase"])
            remaining = message.payload["work_remaining_ms"]
            work_deadline = None if remaining is None else time.time()+remaining/1000-age
            await self._apply(SupervisorEvent(EventKind.CHILD_STATUS, time.time(),
                expected_generation=self.child.child_generation,
                child_id=self.child.child_id, child_phase=phase,
                progress_sequence=message.payload["progress_sequence"],
                work_deadline_utc=work_deadline,
                retry_holds=tuple(message.payload["blockers"])))
        elif message.kind == MessageKind.RESULT:
            if self.child.result is not None:
                raise InvalidData("duplicate native child result")
            self.child.result = message.payload
        else:
            raise InvalidData("unexpected native child message")

    async def _finish_child(self, returncode):
        child = self.child
        if child.endpoint is not None:
            deadline = time.monotonic()+.25
            while time.monotonic() < deadline:
                try:
                    message = await asyncio.to_thread(child.endpoint.receive, .02)
                except InvalidData:
                    break
                if message is not None:
                    await self._message(message)
                    if message.kind == MessageKind.RESULT:
                        break
        payload = child.result
        if payload is None:
            # The fixed fixture reserves 20..30 for local validation/safety
            # refusal. Inert crash mode uses 7; never retry known safety faults.
            outcome = (ChildOutcome.STARTUP_REFUSED if 20 <= returncode <= 30
                       else ChildOutcome.UNEXPECTED_DEATH)
            cleanup_complete = cleanup_failed = False
            unresolved_work = True
            holds = ()
        else:
            outcome = ChildOutcome(payload["outcome"])
            cleanup_complete = payload["cleanup_complete"]
            cleanup_failed = payload["cleanup_failed"]
            unresolved_work = payload["unresolved_work"]
            holds = tuple(payload["retry_holds"])
            if ((outcome == ChildOutcome.CLEAN and returncode != 0)
                    or (outcome != ChildOutcome.CLEAN and returncode == 0)):
                outcome = ChildOutcome.INTEGRITY_FAILURE
                cleanup_complete = False
                unresolved_work = True
        await child.close_after_exit()
        if child.cleanup_error:
            self._record_fault(InvalidData("native child cleanup encountered a fault"))
        await self._apply(SupervisorEvent(EventKind.CHILD_RESULT, time.time(),
            expected_generation=child.child_generation, child_id=child.child_id,
            outcome=outcome, process_exited=True,
            cleanup_complete=cleanup_complete, cleanup_failed=cleanup_failed,
            unresolved_work=unresolved_work, retry_holds=holds))
        self.child_exits += 1
        self.validated_results += int(payload is not None)
        self.child = None
        self._inbound = SequenceTracker()
        self._control_sequence = self._pulse_sequence = 0

    async def _loop(self, power):
        next_tick = next_pulse = 0.0
        while True:
            self.loop_wakes += 1
            now = time.monotonic()
            if power.changed.is_set():
                await self._apply(SupervisorEvent(EventKind.LOCAL_SAFETY_FAULT,
                    time.time(), attention_reason=AttentionReason.POWER_STATE_CHANGED))
                self._stop_latch.request_owned()
                return
            self.diagnostics.ensure_healthy()
            if self.shutdown_requested:
                return
            if now >= next_tick:
                receipt = await self._apply(SupervisorEvent(EventKind.TICK, time.time()))
                if SupervisorAction.START_DUE in receipt.decision.actions and self.child is None:
                    await self._spawn(receipt.state)
                if self.child is None and receipt.state.child_id is not None:
                    # Cold parents never adopt by PID.  The account-scoped lease
                    # is the only exclusion receipt accepted for orphan release.
                    probe = WindowsRoleLease(self.scope.scope_id, "child",
                                             user_sid=self.scope.approved_user_sid)
                    try:
                        probe.__enter__()
                    except InvalidData:
                        self._stop_latch.request_owned()
                    else:
                        try:
                            await self._apply(SupervisorEvent(
                                EventKind.ORPHAN_RELEASED, time.time(),
                                expected_generation=receipt.state.child_generation,
                                child_id=receipt.state.child_id))
                        finally:
                            probe.__exit__()
                next_tick = now+1
            if self.child is not None:
                if self._stop_latch.requested and not self.controller_state.stop_latched:
                    await self._apply(SupervisorEvent(EventKind.STOP, time.time()))
                if self.controller_state.stop_latched and not self.child.stop_hint_sent:
                    try:
                        self.child.endpoint.send_control(self._outbound(
                            MessageKind.STOP_HINT, dict(reason="durable_stop")))
                    except (AttributeError, InvalidData):
                        pass
                    self.child.stop_hint_sent = True
                    self.child.request_stop()
                if self.child.endpoint is not None:
                    self.max_incoming_backlog = max(
                        self.max_incoming_backlog,
                        self.child.endpoint.incoming.qsize())
                    while True:
                        try:
                            message = self.child.endpoint.receive(timeout=0)
                        except InvalidData as exc:
                            if (self.child.poll_exit() is None
                                    and self.child.result is None):
                                try:
                                    await asyncio.to_thread(
                                        self.child.process.wait, timeout=.25)
                                except subprocess.TimeoutExpired:
                                    self._record_fault(exc)
                                    await self._apply(SupervisorEvent(
                                        EventKind.LOCAL_SAFETY_FAULT, time.time(),
                                        attention_reason=AttentionReason.IPC_FAILURE))
                                    self.child.request_stop()
                            break
                        if message is None:
                            break
                        await self._message(message)
                    if (now >= next_pulse and self.child.poll_exit() is None
                            and self.child.result is None
                            and self.child.endpoint.error is None
                            and not self.controller_state.stop_latched):
                        try:
                            revision = (await self.owner.submit("read")).revision
                            self._guard()
                            self.child.endpoint.publish_latest(self._outbound(
                                MessageKind.PULSE, dict(control_revision=revision),
                                coalesced=True))
                        except InvalidData as exc:
                            # Pipe closure can precede the process-handle signal.
                            # Bound the exact owned process wait as on receive.
                            try:
                                await asyncio.to_thread(self.child.process.wait, timeout=.25)
                            except subprocess.TimeoutExpired:
                                raise exc
                        next_pulse = now+2
                returncode = self.child.poll_exit()
                if returncode is not None:
                    await self._finish_child(returncode)
            if (self.shutdown_requested and self.child is None
                    and self.controller_state.child_id is None):
                return
            if (self._stop_latch.requested and self.child is None
                    and self.controller_state is not None
                    and self.controller_state.child_id is None
                    and self.controller_state.stop_latched):
                return
            delay = max(0.0, min(1.0, next_tick-time.monotonic()))
            if (self.child is not None and self.child.endpoint is not None
                    and self.child.endpoint.error is None):
                await asyncio.to_thread(self.child.endpoint.wait_activity, delay)
            else:
                await asyncio.sleep(delay)

    async def run(self):
        if self._run_task is not None:
            raise InvalidData("supervisor host cannot be reused")
        self._run_task = asyncio.create_task(self._run_owned())
        cancelled = False
        while not self._run_task.done():
            try:
                await asyncio.wait((self._run_task,))
            except asyncio.CancelledError:
                cancelled = True
                self.shutdown_requested = True
                try:
                    self._signal_stop()
                except BaseException as exc:
                    self._record_fault(exc)
        result = self._run_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _run_owned(self):
        self.owner = ControlOwner(self.scope, policy=self.policy,
                                  diagnostics=self.diagnostics)
        parent_lease = WindowsRoleLease(self.scope.scope_id, "parent",
                                        user_sid=self.scope.approved_user_sid)
        acquired = False
        stop_owner = power = None
        try:
            parent_lease.__enter__()
            acquired = True
            await asyncio.to_thread(self.diagnostics.start)
            self.diagnostics.emit("supervisor_started", operation=self.parent_session)
            before = await self.owner.submit("read")
            self.controller_state = before.state
            try:
                stop_owner = WindowsStopLatch(self.scope.scope_id,
                    user_sid=self.scope.approved_user_sid)
                stop_owner.__enter__()
            except InvalidData as exc:
                if ("already exists" not in str(exc)
                        or before.state.child_id is None):
                    raise
                stop_owner = WindowsStopLatch(self.scope.scope_id,
                    user_sid=self.scope.approved_user_sid, create=False)
                stop_owner.__enter__()
            self._stop_latch = stop_owner
            power = WindowsPowerMonitor()
            power.__enter__()
            self._power = power
            receipt = await self.owner.submit("session", self.parent_session, time.time())
            self.controller_state = receipt.state
            if receipt.state.child_id is not None:
                stop_owner.request_owned()
            self.started.set()
            await self._loop(power)
        except BaseException as exc:
            if not acquired:
                raise
            self._record_fault(exc)
        finally:
            if acquired and self._stop_latch is not None:
                while True:
                    try:
                        await self._finalize()
                        break
                    except BaseException as exc:
                        self._record_fault(exc)
                        await asyncio.sleep(1)
            await self.owner.close()
            if self.owner.failure and self.last_error is None:
                self.last_error = self.owner.failure
            if acquired:
                self.diagnostics.emit("supervisor_stopped", operation=self.parent_session)
            await self._close_diagnostics()
            if power is not None:
                await self._close_native(power.__exit__)
            if stop_owner is not None:
                await self._close_native(stop_owner.__exit__)
                self._stop_latch = None
            if acquired:
                await self._close_native(parent_lease.__exit__)
            self.finished.set()
        if self.last_error is not None:
            raise InvalidData("supervisor stopped after fault; inspect diagnostics")

    async def _close_native(self, close):
        while True:
            try:
                close()
                return
            except BaseException as exc:
                self._record_fault(exc)
                await asyncio.sleep(1)

    async def _close_diagnostics(self):
        await asyncio.to_thread(self.diagnostics.close, 1)
        while self.diagnostics.status()["worker_alive"]:
            await asyncio.to_thread(self.diagnostics.close, 1)
        if self.diagnostics.status()["failure"] is not None and self.last_error is None:
            self.last_error = self.diagnostics.status()["failure_detail"] or [
                {"category": "logging", "type": "DiagnosticFailure", "frames": []}]

    async def _finalize(self):
        """Never cancelled: owns child, orphan observation, IPC and final commits."""
        self.shutdown_requested = True
        try:
            power_changed = self._power is not None and self._power.changed.is_set()
            reason = (AttentionReason.POWER_STATE_CHANGED if power_changed
                      else AttentionReason.IPC_FAILURE)
            if self.last_error or power_changed:
                await self._apply(SupervisorEvent(EventKind.LOCAL_SAFETY_FAULT,
                    time.time(), attention_reason=reason))
            elif self.controller_state is None or not self.controller_state.stop_latched:
                await self._apply(SupervisorEvent(EventKind.STOP, time.time()))
        except BaseException as exc:
            self._record_fault(exc)
        finally:
            try:
                self._signal_stop()
            except BaseException as exc:
                self._record_fault(exc)
        if (self.child is not None and not self.child.created
                and not self.child.creation_attempted):
            self.child.release_presence()
            self.child = None
        while self.child is not None:
            if self.child.poll_exit() is not None:
                try:
                    await self._finish_child(self.child.poll_exit())
                except BaseException as exc:
                    self._record_fault(exc)
                    # Faulty protocol/store evidence cannot abandon native cleanup.
                    await self.child.close_after_exit()
                    self.child = None
                break
            try:
                await self._apply(SupervisorEvent(EventKind.TICK, time.time()))
            except BaseException as exc:
                self._record_fault(exc)
            await asyncio.sleep(.25)
        # A cold parent's lack of a Popen is not proof the old child is gone.
        while self.controller_state is not None and self.controller_state.child_id is not None:
            probe = WindowsRoleLease(self.scope.scope_id, "child",
                                     user_sid=self.scope.approved_user_sid)
            try:
                probe.__enter__()
            except InvalidData:
                await asyncio.sleep(1)
                continue
            try:
                state = (await self.owner.submit("read")).state
                self.controller_state = state
                if state.child_id is not None:
                    await self._apply(SupervisorEvent(EventKind.ORPHAN_RELEASED,
                        time.time(), expected_generation=state.child_generation,
                        child_id=state.child_id))
            except BaseException as exc:
                self._record_fault(exc)
                await asyncio.sleep(1)
            finally:
                probe.__exit__()


def fixture_fingerprints(mode="normal"):
    """Public helper for tests/controllers; never authorizes production launch."""
    return build_fingerprint(), config_fingerprint(mode)
