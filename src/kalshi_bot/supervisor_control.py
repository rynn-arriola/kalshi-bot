"""Serialized S2A fixture control. No account, network or trading operations."""
import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from queue import Queue
from threading import Thread
import time

from .supervision import (AttentionReason, EventKind, SupervisorEvent,
                          SupervisorPolicy)
from .supervisor_store import SupervisorStore
from .values import InvalidData, identity, integer
from .windows import (WindowsControlMutex, WindowsStopLatch, current_user_sid)


@dataclass(frozen=True)
class ScopeSpec:
    environment: str
    account_scope: str
    approved_user_sid: str
    control_root: Path

    def __post_init__(self):
        identity(self.environment)
        identity(self.account_scope)
        if not self.account_scope.startswith("test-"):
            raise InvalidData("S2A permits only test account scopes")
        if not isinstance(self.approved_user_sid, str) or not self.approved_user_sid.startswith("S-"):
            raise InvalidData("approved Windows SID required")
        root = Path(self.control_root)
        if not root.is_absolute() or str(root).startswith("\\\\"):
            raise InvalidData("absolute local control root required")
        absolute = root.absolute()
        resolved = root.resolve(strict=True)
        if "onedrive" in str(resolved).casefold():
            raise InvalidData("OneDrive control roots are not allowed")
        if resolved != absolute:
            raise InvalidData("redirected control root is not allowed")
        object.__setattr__(self, "control_root", resolved)
        if current_user_sid() != self.approved_user_sid:
            raise InvalidData("current Windows user does not own this fixture scope")

    @property
    def scope_id(self):
        return identity(f"{self.environment}-{self.account_scope}")

    @property
    def digest(self):
        return hashlib.sha256(self.scope_id.casefold().encode()).hexdigest()

    @property
    def store_path(self):
        return self.control_root / "supervisor-control.db"


@dataclass(frozen=True)
class ControlReceipt:
    revision: int
    decision: object = None
    state: object = None
    native: object = None
    value: object = None

    def __post_init__(self):
        integer(self.revision, 0, 2**63-1)


class ControlOwner:
    """One thread owns SQLite and the thread-affine Windows transaction mutex."""
    def __init__(self, scope: ScopeSpec, *, policy=SupervisorPolicy(),
                 clock=time.time, monotonic_clock=time.monotonic, boot_id=None):
        if not isinstance(scope, ScopeSpec):
            raise InvalidData("typed supervisor scope required")
        self.scope, self.policy = scope, policy
        self.clock, self.monotonic_clock, self.boot_id = clock, monotonic_clock, boot_id
        self.commands = Queue(maxsize=64)
        self.ready = Future()
        self.closed = False
        self.thread = Thread(target=self._run, name="kalshi-supervisor-control", daemon=False)
        self.thread.start()

    @classmethod
    def initialize_fixture(cls, scope, **clock_values):
        if not isinstance(scope, ScopeSpec):
            raise InvalidData("typed supervisor scope required")
        if any(scope.control_root.iterdir()):
            raise InvalidData("fixture control root must be empty")
        with SupervisorStore.initialize_fixture(scope.store_path,
                scope_id=scope.scope_id, **clock_values):
            pass

    def _run(self):
        store = None
        control_mutex = None
        try:
            store = SupervisorStore.open_existing(self.scope.store_path,
                scope_id=self.scope.scope_id, clock=self.clock,
                monotonic_clock=self.monotonic_clock, boot_id=self.boot_id)
            control_mutex = WindowsControlMutex(self.scope.scope_id,
                user_sid=self.scope.approved_user_sid, retain_handle=True)
            control_mutex.open()
            self.ready.set_result(None)
            while True:
                item = self.commands.get()
                if item is None:
                    break
                operation, args, future = item
                try:
                    with control_mutex as mutex:
                        if mutex.abandoned:
                            held = store.apply(SupervisorEvent(
                                EventKind.LOCAL_SAFETY_FAULT, self.clock(),
                                attention_reason=AttentionReason.CONTROL_ABANDONED),
                                self.policy)
                            if not (operation == "apply" and args[0].kind == EventKind.STOP):
                                result = ControlReceipt(store.revision(), held,
                                    held.state, store.read_native())
                                future.set_result(result)
                                continue
                        result = self._execute(store, operation, args)
                    future.set_result(result)
                except BaseException as exc:
                    future.set_exception(exc)
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)
            while not self.commands.empty():
                item = self.commands.get_nowait()
                if item is not None and not item[2].done():
                    item[2].set_exception(InvalidData("supervisor control owner stopped"))
        finally:
            if store is not None:
                store.close()
            if control_mutex is not None:
                control_mutex.close()

    def _execute(self, store, operation, args):
        if operation == "read":
            return ControlReceipt(store.revision(), state=store.read(),
                                  native=store.read_native())
        if operation == "apply":
            decision = store.apply(args[0], self.policy)
            return ControlReceipt(store.revision(), decision, decision.state,
                                  store.read_native())
        if operation == "session":
            decision = store.begin_parent_session(args[0], observed_utc=args[1],
                                                  policy=self.policy)
            return ControlReceipt(store.revision(), decision, store.read(),
                                  store.read_native())
        if operation == "reserve":
            decision = store.reserve_start(args[0], parent_session=args[1],
                                           policy=self.policy)
            return ControlReceipt(store.revision(), decision, decision.state,
                                  store.read_native())
        if operation == "stage":
            native = store.update_native_stage(**args[0])
            return ControlReceipt(store.revision(), state=store.read(), native=native)
        if operation == "spawn":
            event, session, factory = args
            factory.acquire_presence()
            try:
                decision = store.reserve_start(event, parent_session=session,
                                               policy=self.policy)
                if decision.stale:
                    factory.release_presence()
                    return ControlReceipt(store.revision(), decision, decision.state,
                                          store.read_native())
                try:
                    value = factory.spawn()
                except BaseException:
                    if not factory.created:
                        store.apply(SupervisorEvent(EventKind.SPAWN_FAILED,
                            self.clock(), expected_generation=event.expected_generation,
                            child_id=event.child_id), self.policy)
                        factory.release_presence()
                    raise
                native = store.update_native_stage(parent_session=session,
                    child_id=event.child_id,
                    child_generation=decision.state.child_generation,
                    stage="created", diagnostic_pid=value.process.pid)
                return ControlReceipt(store.revision(), decision, decision.state,
                                      native, value)
            except BaseException:
                if not factory.created:
                    factory.release_presence()
                raise
        raise InvalidData("unknown supervisor control operation")

    def _submit_future(self, operation, *args):
        if self.closed:
            raise InvalidData("supervisor control owner closed")
        self.ready.result(timeout=5)
        future = Future()
        try:
            self.commands.put_nowait((operation, args, future))
        except Exception as exc:
            raise InvalidData("supervisor control queue unavailable") from exc
        return future

    async def submit(self, operation, *args):
        wrapped = asyncio.wrap_future(self._submit_future(operation, *args))
        wrapped.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        return await asyncio.shield(wrapped)

    def submit_sync(self, operation, *args, timeout=10):
        return self._submit_future(operation, *args).result(timeout=timeout)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.commands.put(None)
        await asyncio.to_thread(self.thread.join, 10)
        if self.thread.is_alive():
            raise InvalidData("supervisor control owner did not stop")


class SupervisorController:
    """Fixture-only durable arm/stop/inspection; never spawns a process."""
    def __init__(self, scope, owner):
        if not isinstance(scope, ScopeSpec) or not isinstance(owner, ControlOwner):
            raise InvalidData("typed supervisor controller dependencies required")
        self.scope, self.owner = scope, owner

    async def inspect(self):
        return await self.owner.submit("read")

    async def arm(self, *, expected_generation, build_fingerprint,
                  config_fingerprint, observed_utc=None):
        event = SupervisorEvent(EventKind.ARM,
            time.time() if observed_utc is None else observed_utc,
            expected_generation=expected_generation,
            build_fingerprint=build_fingerprint,
            config_fingerprint=config_fingerprint)
        return await self.owner.submit("apply", event)

    async def stop(self, *, observed_utc=None):
        error = None
        receipt = None
        try:
            receipt = await self.owner.submit("apply", SupervisorEvent(
                EventKind.STOP, time.time() if observed_utc is None else observed_utc))
        except BaseException as exc:
            error = exc
        signaled = WindowsStopLatch.request(self.scope.scope_id,
            user_sid=self.scope.approved_user_sid)
        if error is not None:
            raise InvalidData("durable supervisor disarm unconfirmed") from error
        return receipt, signaled
