"""Fixed offline S2B runtime adapter; never loads execution authority.

The native supervisor may construct this adapter only for disposable ``test-*``
scopes.  All dependencies are local fixtures: a fresh ledger, deterministic GET
responses and in-memory readers.  There is no signer, socket, mutation client or
live activation path in this module.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import time

from .rest import PageSet, ReadFailure, ReadResult
from .recovery_fence import FenceCooldown, RecoveryFence
from .runtime import RecoveryRuntime
from .values import InvalidData, identity, integer
from .writer import LedgerWriter


class RuntimeRestrictions:
    """Fail-closed local copy loaded before any fixture read can start."""
    def __init__(self, *, clock=time.time):
        self.clock = clock
        self.applied = False
        self.fence_revision = 0
        self.holds = ()
        self.cooldowns = ()
        self.restored_tokens = 0

    def apply(self, fence, *, current_parent_session=None):
        if fence is not None and not isinstance(fence, RecoveryFence):
            raise InvalidData("typed recovery fence required")
        if current_parent_session is not None:
            identity(current_parent_session)
        self.fence_revision = 0 if fence is None else fence.fence_revision
        holds = () if fence is None else fence.component_holds
        clock_trusted = (fence is None or current_parent_session is None
                         or fence.parent_session == current_parent_session)
        if not clock_trusted:
            holds = tuple(dict.fromkeys(holds+("recovery_fence_clock_untrusted",)))
        self.holds = holds
        try:
            now = float(self.clock())
        except (TypeError, ValueError) as exc:
            raise InvalidData("invalid recovery-fence clock") from exc
        if not math.isfinite(now) or now < 0:
            raise InvalidData("invalid recovery-fence clock")
        self.cooldowns = (() if fence is None else tuple(
            item for item in fence.cooldowns
            if not clock_trusted or item.deadline_utc > now))
        self.restored_tokens = 0
        self.applied = True

    @property
    def blockers(self):
        return tuple(dict.fromkeys(self.holds+tuple(
            "cooldown_"+item.name for item in self.cooldowns)))


@dataclass(frozen=True)
class RuntimeContext:
    scope_id: str
    child_id: str
    child_generation: int
    execution_enabled: bool = False
    credentials_present: bool = False
    network_enabled: bool = False

    def __post_init__(self):
        identity(self.scope_id)
        identity(self.child_id)
        integer(self.child_generation, 0, 2**63-1)
        if not self.scope_id.startswith("fixture-test-"):
            raise InvalidData("S2B runtime requires a disposable fixture scope")
        if any(type(value) is not bool for value in (
                self.execution_enabled, self.credentials_present, self.network_enabled)):
            raise InvalidData("runtime authority flags must be boolean")
        if self.execution_enabled or self.credentials_present or self.network_enabled:
            raise InvalidData("S2B runtime context cannot contain execution authority")


@dataclass(frozen=True)
class HealthSnapshot:
    phase: str
    progress_sequence: int
    work_remaining_ms: int | None
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class CleanupEvidence:
    cleanup_complete: bool
    cleanup_failed: bool
    unresolved_work: bool
    retry_holds: tuple[str, ...]


class RuntimeAdapter:
    """Own one injected runtime and its writer through retained shutdown."""
    def __init__(self, runtime, writer, restrictions):
        if not isinstance(runtime, RecoveryRuntime) or not isinstance(writer, LedgerWriter):
            raise InvalidData("typed offline runtime dependencies required")
        if not isinstance(restrictions, RuntimeRestrictions):
            raise InvalidData("typed runtime restrictions required")
        self.runtime, self.writer, self.restrictions = runtime, writer, restrictions
        self.task = None
        self.context = None
        self.stop_reason = None
        self._progress = 0
        self._join_task = None

    async def start(self, context):
        if not isinstance(context, RuntimeContext) or self.task is not None:
            raise InvalidData("unused runtime adapter and typed context required")
        if not self.restrictions.applied:
            raise InvalidData("recovery fence must be applied before runtime start")
        self.context = context
        self.task = asyncio.create_task(self.runtime.run(), name="kalshi-s2b-runtime")
        await asyncio.sleep(0)
        return self

    def health_snapshot(self):
        if self.task is None:
            phase = "starting"
        elif self.task.done() and (self.task.cancelled()
                or self.task.exception() is not None):
            phase = "degraded"
        elif self.runtime.recovery_state in {"recovering", "not_started"}:
            phase = "recovering"
        else:
            phase = "degraded" if self.restrictions.blockers else "healthy"
        self._progress += 1  # A serviced event loop is useful progress even when quiet.
        blockers = tuple(dict.fromkeys(self.restrictions.blockers + (
            ("writer_failed",) if self.writer.failed else ())))
        return HealthSnapshot(phase, self._progress,
                              30000 if phase in {"starting", "recovering"} else None,
                              blockers)

    def request_stop(self, reason):
        self.stop_reason = identity(reason)
        self.runtime.stop()

    async def join(self):
        if self.task is None:
            raise InvalidData("runtime adapter was not started")
        if self._join_task is None:
            self._join_task = asyncio.create_task(self._join_owned())
        cancelled = False
        while not self._join_task.done():
            try:
                await asyncio.wait((self._join_task,))
            except asyncio.CancelledError:
                cancelled = True
        result = self._join_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _join_owned(self):
        failures = []
        try:
            await self.task
        except asyncio.CancelledError as exc:
            failures.append(exc)
        except BaseException as exc:
            failures.append(exc)
        try:
            await self.writer.close()
        except BaseException as exc:
            failures.append(exc)
        failed = bool(failures or self.writer.failed)
        holds = tuple(dict.fromkeys(self.restrictions.blockers + (
            ("runtime_cleanup_failed",) if failed else ())))
        return CleanupEvidence(not failed, failed, failed, holds)


class OfflineReads:
    """Deterministic local responses; the applied-fence assertion is observable."""
    def __init__(self, restrictions, *, now):
        self.restrictions, self.now = restrictions, now
        self.calls = 0

    def _check(self):
        if not self.restrictions.applied:
            raise InvalidData("fixture read attempted before recovery fence")
        self.calls += 1

    async def read(self, name, **kwargs):
        self._check()
        if name == "balance":
            return ReadResult({"balance_dollars": "0", "updated_ts": 1}, 1)
        if name == "order":
            raise ReadFailure(404)
        stamp = (self.now()-timedelta(days=1)).isoformat()
        return ReadResult({"trades_created_ts": stamp, "orders_updated_ts": stamp}, 1)

    async def collect(self, name, **kwargs):
        self._check()
        return PageSet((), 1, 1)


class OfflineReader:
    def __init__(self, spec):
        self.spec = spec
        self.queue = asyncio.Queue(maxsize=1)
        self.queued_bytes = 0
        self.closed = False

    async def run(self, consume):
        try:
            for sid, channel in enumerate(self.spec.channels, 1):
                await consume(self.spec.name, {"type": "subscribed", "id": 1,
                    "msg": {"channel": channel, "sid": sid}})
            await asyncio.Future()
        finally:
            self.closed = True


async def create_offline_runtime_adapter(ledger_path, restrictions, *, clock=time.time,
                                         market_count=1):
    """Create the one fixed S2B fixture graph in a fresh disposable ledger."""
    path = Path(ledger_path)
    if not path.is_absolute() or path.exists() or "onedrive" in str(path).casefold():
        raise InvalidData("S2B fixture ledger must be a fresh absolute local path")
    if not isinstance(restrictions, RuntimeRestrictions) or not restrictions.applied:
        raise InvalidData("S2B restrictions must be applied before ledger creation")
    count = integer(market_count, 1, 120)
    writer = await LedgerWriter(path, market_capacity=max(4, count)).start()
    now = lambda: datetime.fromtimestamp(float(clock()), timezone.utc)
    reads = OfflineReads(restrictions, now=now)

    async def nothing(*_):
        return None

    tickers = tuple("S2B-"+str(index).zfill(3) for index in range(count))
    try:
        runtime = RecoveryRuntime(writer, reads, OfflineReader, tickers=tickers,
            subaccount=0, history_start=now()-timedelta(seconds=1), now=now,
            evaluate=nothing, deadline_handler=nothing, lifecycle_handler=nothing,
            sleep=asyncio.sleep, jitter=lambda: 1, attempts=1)
        return RuntimeAdapter(runtime, writer, restrictions)
    except BaseException:
        await writer.close()
        raise
