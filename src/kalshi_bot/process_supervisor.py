"""Native Windows S2A supervisor for one fixed inert child only."""
import asyncio
from collections import deque
import hashlib
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
from .supervisor_fixture import (build_fingerprint, config_fingerprint,
                                 fixture_path, repository_root, source_path)
from .supervisor_protocol import (CHILD_KINDS, Envelope, MessageKind,
                                  SequenceTracker)
from .values import InvalidData, identity
from .windows import (WindowsPowerMonitor, WindowsRoleLease, WindowsStopLatch,
                      _close_handle, inheritable_parent_handle)
from .windows_ipc import PipeServer, supervisor_pipe_name


class OwnedChild:
    """Spawn preparation retained by the host even after uncertain failures."""
    def __init__(self, scope, stop_latch, *, parent_session, child_id,
                 child_generation, mode):
        self.scope, self.stop_latch = scope, stop_latch
        self.parent_session = identity(parent_session)
        self.child_id = identity(child_id)
        self.child_generation = child_generation
        self.mode = mode
        self.lease = WindowsRoleLease(scope.scope_id, "child",
                                      user_sid=scope.approved_user_sid)
        self.server = None
        self.endpoint = None
        self.process = None
        self.created = False
        self.result = None
        self.stop_hint_sent = False

    def acquire_presence(self):
        self.lease.__enter__()

    def release_presence(self):
        if self.created:
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
        nonce = uuid4().hex
        pipe = supervisor_pipe_name(self.scope.digest, nonce)
        self.server = PipeServer(pipe, user_sid=self.scope.approved_user_sid)
        lifetime = self.lease.duplicate_inheritable()
        stop = self.stop_latch.duplicate_inheritable()
        parent = inheritable_parent_handle()
        handles = (lifetime, stop, parent)
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
        try:
            self.process = subprocess.Popen(command, cwd=repository_root(),
                env=self._environment(venv_launcher), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                shell=False, close_fds=True, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.created = True
            return self
        finally:
            for handle in handles:
                _close_handle(handle)

    async def bind(self):
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
        if self.process is None or self.process.poll() is None:
            raise InvalidData("native child exit is not confirmed")
        if self.endpoint is not None:
            await asyncio.to_thread(self.endpoint.close_and_join)
            self.endpoint = None
        if self.server is not None:
            self.server.close()
            self.server = None
        if self.lease.handle is not None:
            self.created = False
            self.lease.__exit__()


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
        self.policy_latencies_ms = deque(maxlen=4096)

    @property
    def fingerprints(self):
        return build_fingerprint(), config_fingerprint(self.fixture_mode)

    async def _apply(self, event):
        began = time.perf_counter()
        receipt = await self.owner.submit("apply", event)
        self.policy_latencies_ms.append((time.perf_counter()-began)*1000)
        self.controller_state = receipt.state
        for action in (() if receipt.decision is None else receipt.decision.actions):
            if action == SupervisorAction.REQUEST_GRACEFUL_STOP and self.child is not None:
                self.child.request_stop()
        return receipt

    async def request_shutdown(self):
        self.shutdown_requested = True
        if self.owner is not None:
            await self._apply(SupervisorEvent(EventKind.STOP, time.time()))
        WindowsStopLatch.request(self.scope.scope_id,
            user_sid=self.scope.approved_user_sid)

    def _validate_common(self, envelope):
        if (envelope.scope_digest != self.scope.digest
                or envelope.parent_session != self.parent_session
                or self.child is None
                or envelope.child_id != self.child.child_id
                or envelope.child_generation != self.child.child_generation
                or envelope.kind not in CHILD_KINDS):
            raise InvalidData("supervisor child envelope identity mismatch")
        age = time.monotonic_ns()-envelope.sent_monotonic_ns
        if age < 0 or age > 4_000_000_000:
            raise InvalidData("stale supervisor child envelope")
        self._inbound.accept(envelope)

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
        build, config = self.fingerprints
        if (state.build_fingerprint != build
                or state.config_fingerprint != config):
            await self._apply(SupervisorEvent(EventKind.LOCAL_SAFETY_FAULT,
                time.time(), attention_reason=AttentionReason.IPC_FAILURE))
            return
        child_id = uuid4().hex
        factory = OwnedChild(self.scope, self._stop_latch,
            parent_session=self.parent_session, child_id=child_id,
            child_generation=state.generation, mode=self.fixture_mode)
        event = SupervisorEvent(EventKind.START_REQUESTED, time.time(),
            expected_generation=state.generation, child_id=child_id)
        self.child = factory
        try:
            receipt = await self.owner.submit("spawn", event, self.parent_session,
                                              factory)
        except BaseException:
            if not factory.created:
                self.child = None
            raise
        self.controller_state = receipt.state
        if receipt.decision.stale:
            self.child = None
            return
        self.child = receipt.value
        await self._apply(SupervisorEvent(EventKind.CHILD_STARTED, time.time(),
            expected_generation=self.child.child_generation,
            child_id=self.child.child_id))
        try:
            endpoint = await self.child.bind()
            hello = await asyncio.to_thread(endpoint.receive, 10)
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
            if (current.revision != bound.revision or current.state.stop_latched
                    or current.state.child_id != self.child.child_id
                    or current.native.stage != "bound"):
                raise InvalidData("native child admission was revoked")
            endpoint.send_control(self._outbound(MessageKind.ADMIT,
                dict(control_revision=current.revision)))
        except BaseException as exc:
            self.last_error = exc
            await self._apply(SupervisorEvent(EventKind.LOCAL_SAFETY_FAULT,
                time.time(), attention_reason=AttentionReason.IPC_FAILURE))
            self.child.request_stop()

    async def _message(self, message):
        self._validate_common(message)
        if message.kind == MessageKind.STATUS:
            phase = ChildPhase(message.payload["phase"])
            remaining = message.payload["work_remaining_ms"]
            work_deadline = None if remaining is None else time.time()+remaining/1000
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
            outcome = ChildOutcome.UNEXPECTED_DEATH
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
        await self._apply(SupervisorEvent(EventKind.CHILD_RESULT, time.time(),
            expected_generation=child.child_generation, child_id=child.child_id,
            outcome=outcome, process_exited=True,
            cleanup_complete=cleanup_complete, cleanup_failed=cleanup_failed,
            unresolved_work=unresolved_work, retry_holds=holds))
        self.child = None
        self._inbound = SequenceTracker()
        self._control_sequence = self._pulse_sequence = 0

    async def _loop(self, power):
        next_tick = next_pulse = 0.0
        while True:
            self.loop_wakes += 1
            now = time.monotonic()
            if power.changed.is_set():
                power.changed.clear()
                await self._apply(SupervisorEvent(EventKind.LOCAL_SAFETY_FAULT,
                    time.time(), attention_reason=AttentionReason.POWER_STATE_CHANGED))
                self._stop_latch.request_owned()
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
                                    self.last_error = exc
                                    await self._apply(SupervisorEvent(
                                        EventKind.LOCAL_SAFETY_FAULT, time.time(),
                                        attention_reason=AttentionReason.IPC_FAILURE))
                                    self.child.request_stop()
                            break
                        if message is None:
                            break
                        await self._message(message)
                    if now >= next_pulse and self.child.poll_exit() is None:
                        try:
                            revision = (await self.owner.submit("read")).revision
                            self.child.endpoint.publish_latest(self._outbound(
                                MessageKind.PULSE, dict(control_revision=revision),
                                coalesced=True))
                        except InvalidData as exc:
                            self.last_error = exc
                        next_pulse = now+2
                returncode = self.child.poll_exit()
                if returncode is not None:
                    await self._finish_child(returncode)
            if (self.shutdown_requested and self.child is None):
                return
            if (self._stop_latch.requested and self.child is None
                    and self.controller_state is not None
                    and self.controller_state.stop_latched):
                return
            delay = max(0.0, min(1.0, next_tick-time.monotonic()))
            if (self.child is not None and self.child.endpoint is not None
                    and self.child.endpoint.error is None):
                await asyncio.to_thread(self.child.endpoint.wait_activity, delay)
            else:
                await asyncio.sleep(delay)

    async def run(self):
        if self.owner is not None:
            raise InvalidData("supervisor host cannot be reused")
        self.owner = ControlOwner(self.scope, policy=self.policy)
        parent_lease = WindowsRoleLease(self.scope.scope_id, "parent",
                                        user_sid=self.scope.approved_user_sid)
        try:
            with parent_lease:
                before = await self.owner.submit("read")
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
                try:
                    power = WindowsPowerMonitor()
                    power.__enter__()
                except BaseException:
                    stop_owner.__exit__()
                    raise
                try:
                    stop_latch = stop_owner
                    self._stop_latch = stop_latch
                    receipt = await self.owner.submit("session", self.parent_session,
                                                      time.time())
                    self.controller_state = receipt.state
                    if receipt.state.child_id is not None:
                        stop_latch.request_owned()
                    self.started.set()
                    try:
                        await self._loop(power)
                    except asyncio.CancelledError:
                        self.shutdown_requested = True
                        await self._apply(SupervisorEvent(EventKind.STOP, time.time()))
                        self._stop_latch.request_owned()
                        await self._loop(power)
                        raise
                finally:
                    power.__exit__()
                    stop_owner.__exit__()
        finally:
            await self.owner.close()
            self.finished.set()


def fixture_fingerprints(mode="normal"):
    """Public helper for tests/controllers; never authorizes production launch."""
    return build_fingerprint(), config_fingerprint(mode)
