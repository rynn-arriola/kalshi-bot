"""One bounded quota refresh owner; no credentials, writes or automatic arming."""
import asyncio
from dataclasses import dataclass
import math
import random

from .quota import QuotaRolloverPending, QuotaUnavailable
from .rest import ReadFailure
from .values import InvalidData


@dataclass(frozen=True)
class RolloverBoundary:
    """Only scheduling provenance; never retain a caught response traceback."""
    scope: object
    epoch: int
    sequence: int
    expiry_wall: int
    expiry_mono: float


class QuotaSupervisor:
    def __init__(self, reads, *, jitter=random.random, restriction_sink=None):
        if reads.quota is None or reads.quota_supervisor is not None or reads.used:
            raise InvalidData('supervisor requires unused guarded reads')
        self.reads, self.guard, self.jitter = reads, reads.quota, jitter
        self.diagnostics = self.guard.diagnostics
        self.active = None
        self.wake = asyncio.Event()
        self.changed = asyncio.Event()
        self.requested = True
        self.running = self.used = self.stopping = False
        self.exhausted = False
        self.failures = self.started = self.completed = self.wakes = 0
        self.not_before = 0.
        self.rollover = None
        self.rollover_after = 0.
        self.rollover_used = False
        if restriction_sink is not None and not callable(restriction_sink):
            raise InvalidData('restriction sink must be callable')
        self.restriction_sink = restriction_sink
        self.guard.listen(self._changed)
        reads.quota_supervisor = self

    def _changed(self):
        old, self.changed = self.changed, asyncio.Event()
        old.set()
        self.wake.set()

    def request_refresh(self, *, retry=False):
        if type(retry) is not bool:
            raise InvalidData('invalid quota retry request')
        if self.stopping or self.guard.state in ('stopped', 'clock_fault'):
            return False
        if self.exhausted:
            if not retry:
                return False
            self.exhausted = False
            self.failures = 0  # Cooldown and shared 429 pause are NOT reset.
        if self.active is None and self.rollover is None:
            self.requested = True
        self._changed()
        return True

    async def refresh(self):
        if not self.running or not self.request_refresh():
            raise QuotaUnavailable('quota_refresh_unavailable')
        while True:
            self.guard.poll()
            if (self.stopping or self.exhausted or not self.running or self.reads.closed
                    or self.guard.state in ('stopped', 'clock_fault')):
                raise QuotaUnavailable('quota_refresh_unavailable')
            if self.active is not None:
                task = self.active
                break
            if self.rollover is not None:
                raise QuotaUnavailable('quota_rollover_pending')
            changed = self.changed
            await changed.wait()
        await asyncio.wait((task,))
        return task.result()

    async def bootstrap(self):
        """One owned pair before runtime construction needs the write bucket."""
        if self.used or self.running or self.stopping or self.active is not None or self.started:
            raise QuotaUnavailable('quota_bootstrap_unavailable')
        self.step()
        task = self.active
        if task is None:
            raise QuotaUnavailable('quota_bootstrap_unavailable')
        try:
            await asyncio.shield(task)
        finally:
            if task.done():
                self._finished()
        if not self.guard.poll():
            raise QuotaUnavailable('quota_bootstrap_unavailable')

    def _finished(self):
        if self.active is None or not self.active.done():
            return
        task, self.active = self.active, None
        try:
            task.result()
        except asyncio.CancelledError:
            if not self.stopping:
                raise
        except QuotaRolloverPending as exc:
            if self.stopping:
                self._changed()
                return
            if (not self.rollover_used and exc.scope is self.guard.scope
                    and exc.epoch == self.guard.epoch and exc.sequence == self.guard.sequence):
                self.rollover = RolloverBoundary(exc.scope, exc.epoch, exc.sequence,
                                                 exc.expiry_wall, exc.expiry_mono)
                self.rollover_after = self.guard.clock()+5
                self.rollover_used = True
                self.requested = False
                self.diagnostics.emit('quota_rollover_deferred', attempt=self.started)
                self._changed()
                return
            exc = QuotaUnavailable('quota_candidate_expired')
            self._failed(exc)
        except (InvalidData, TimeoutError, OSError) as exc:
            if not self.stopping:
                self._failed(exc)
        else:
            if not self.stopping:
                self.failures = 0
                self.completed += 1
                self.rollover = None
                self.rollover_used = False
        self._changed()

    def _failed(self, exc):
        self.failures += 1
        auth = isinstance(exc, ReadFailure) and exc.status in (401, 403)
        self.exhausted = auth or self.failures >= self.guard.policy.attempts
        jitter = self.jitter()
        if type(jitter) not in (int, float) or not math.isfinite(jitter) or not 0 <= jitter <= 1:
            raise InvalidData('invalid quota jitter')
        delay = self.guard.policy.cooldown if self.exhausted else (5 if self.failures == 1 else 15)*(1+.2*jitter)
        self.not_before = self.guard.clock()+delay
        self.requested = not self.exhausted
        if self.restriction_sink is not None:
            if self.exhausted:
                self.restriction_sink('quota_refresh_exhausted', delay, True)
            else:
                self.restriction_sink('quota_refresh', delay, False)
        self.diagnostics.emit('quota_exhausted' if self.exhausted else 'quota_retry',
                              attempt=self.failures, error=exc)

    def step(self):
        if self.reads._health_error is not None:
            raise InvalidData('quota clock supervision failed') from None
        self.guard.poll()
        self._finished()  # Unexpected exceptions propagate to runtime supervision.
        now = self.guard.clock()
        if self.stopping or self.guard.state in ('stopped', 'clock_fault'):
            return 1.
        due = now
        if self.rollover is not None:
            boundary = self.rollover
            due = max(boundary.expiry_mono, now+max(0., boundary.expiry_wall-self.guard.last[1]),
                      self.rollover_after)
        elif self.guard.state == 'fresh':
            due = self.guard.lease.deadline_mono-self.guard.policy.refresh_lead
        if (self.active is None and not self.exhausted and now >= self.not_before
                and ((self.rollover is None and self.requested) or now >= due)):
            self.requested = False
            self.rollover = None
            self.active = asyncio.create_task(self.reads._refresh_budget_owned(), name='kalshi-quota-refresh')
            self.active.add_done_callback(lambda _: self._changed())
            self.started += 1
            self._changed()
        deadlines = [now+1]
        if self.guard.state == 'fresh':
            deadlines.append(self.guard.lease.deadline_mono)
        if self.active is None and not self.exhausted:
            deadlines.append(max(self.not_before, now if self.requested and self.rollover is None else due))
        return max(.000001, min(deadlines)-now)

    def stop(self):
        if not self.stopping:
            self.stopping = True
            self.rollover = None
            self.guard.stop()
            self._changed()

    async def close(self):
        self.stop()
        if self.active is not None:
            # Consumer cancellation must not abandon the REST-owned pair.
            await asyncio.wait((self.active,))
            self._finished()
        if self.reads.budget_refresh is not None:
            await asyncio.wait((self.reads.budget_refresh,))

    async def run(self):
        if self.used or self.stopping:
            raise InvalidData('quota supervisor cannot be reused')
        self.used = self.running = True
        try:
            while not self.stopping:
                self.wake.clear()
                self.wakes += 1
                delay = self.step()
                try:
                    await asyncio.wait_for(self.wake.wait(), delay)
                except TimeoutError:
                    pass
        finally:
            self.stop()
            try:
                await self.close()
            finally:
                self.running = False
                self._changed()

    def status(self):
        self.guard.poll()
        pending = self.rollover
        return dict(**self.guard.status(), running=self.running,
                    refreshing=self.active is not None, exhausted=self.exhausted,
                    failures=self.failures, started=self.started, completed=self.completed,
                    not_before=self.not_before, wakes=self.wakes, live_authority=False,
                    rollover_pending=pending is not None, rollover_used=self.rollover_used,
                    rollover_due_seconds=(None if pending is None else max(0.,
                        max(pending.expiry_mono-self.guard.last[0],
                            pending.expiry_wall-self.guard.last[1],
                            self.rollover_after-self.guard.last[0]))))
