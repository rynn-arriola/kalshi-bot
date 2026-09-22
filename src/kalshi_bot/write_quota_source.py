"""Observe the existing shared GET pair; never create reads or write transport."""
from .quota import QuotaUnavailable
from .rest import RestReads
from .values import InvalidData, integer
from .write_budget import WriteBudget, WriteQuotaSnapshot


class _ObservedWriteBudget(WriteBudget):
    def __init__(self, source, snapshot, now):
        self._source = source
        super().__init__(snapshot, shards=source.shards, now=now,
            offline_fixture=source.offline_fixture, live_session=source.live_session)

    def _poll(self, now):
        reason = self._source.check()
        if reason is not None:
            self._clear()
            return reason
        # Authority and refill share the reader owner's clock domain, never a
        # caller's cached/future timestamp. No new clock or task is introduced.
        return super()._poll(self._source.guard.last)

    def refresh(self, snapshot, *, now):
        raise InvalidData('observed write budget requires its quota-pair owner')

    def _install(self, snapshot, now):
        super().refresh(snapshot, now=now)

    def pause_429(self, *, shard, seconds, now):
        # A late failure still pauses the current bucket, even if its quota
        # document expired. Like refill, time comes from the sole read owner.
        super().pause_429(shard=shard, seconds=seconds, now=self._source.clock_pair())


class WriteQuotaSource:
    """One opt-in offline budget per unused guarded RestReads owner.

    Attach before use, await reads.refresh_budget(), then use source.budget
    and source.clock_pair with the injected dispatcher. The existing quota
    supervisor owns refresh timing/retries/close; this class owns no worker.
    """
    def __init__(self, reads, *, shards, offline_fixture=False, live_session=None):
        from .live_session import permits
        if ((offline_fixture is not True and not permits(live_session))
                or not isinstance(reads, RestReads)
                or reads.used or reads.closed or reads.quota is None
                or reads.write_quota_source is not None):
            raise InvalidData('unused guarded reads and literal offline_fixture=True required')
        if type(shards) not in (tuple, list) or not 1 <= len(shards) <= 128:
            raise InvalidData('bounded explicit exchange shards required')
        checked = tuple(integer(shard, 0, 2**31-1) for shard in shards)
        if len(set(checked)) != len(checked):
            raise InvalidData('duplicate exchange shard')
        self.reads, self.guard, self.shards = reads, reads.quota, checked
        self.offline_fixture, self.live_session = offline_fixture is True, live_session
        self._scope, self._epoch = self.guard.scope, self.guard.epoch
        self._signer = reads.signer  # Identity only, never read or log credentials.
        self._budget = self._candidate = self._pending = None
        self._reason = 'write_quota_uninitialized'
        self._stopped = False
        reads.write_quota_source = self

    def clock_pair(self):
        return self.guard._sample()

    def invalidate(self, reason):
        self._pending = None
        if self._reason != reason and self._budget is not None:
            self._budget._revision += 1
            self._budget._clear()
        self._reason = reason

    def stop(self):
        self._stopped = True
        self.invalidate('write_quota_stopped')

    def _owns_pair(self):
        return (self.reads.quota is self.guard and self.reads.write_quota_source is self
                and self.reads.signer is self._signer and self.guard.scope is self._scope
                and self.guard.epoch == self._epoch)

    def check(self):
        if self._stopped or self.reads.closed:
            self.invalidate('write_quota_stopped')
        elif not self._owns_pair():
            self.stop()
        elif self.reads._health_error is not None:
            self.invalidate('write_quota_health_failed')
        elif not self.guard.poll():
            self.invalidate('write_'+str(self.guard.reason))
        elif self._candidate is not None and self.guard.lease.candidate is not self._candidate:
            self.invalidate('write_quota_pair_changed')
        return self._reason

    @property
    def budget(self):
        reason = self.check()
        if reason is not None or self._budget is None:
            raise QuotaUnavailable(reason or 'write_quota_uninitialized')
        return self._budget

    def prepare(self, limits, costs, candidate):
        if (self._stopped or self.reads.closed or not self._owns_pair()
                or candidate.scope is not self._scope
                or candidate.epoch != self._epoch or candidate.sequence != self.guard.sequence):
            raise QuotaUnavailable('write_quota_source_changed')
        snapshot = WriteQuotaSnapshot(limits, costs, scope=candidate.scope,
            epoch=candidate.epoch, sequence=candidate.sequence,
            start=(candidate.start_mono, candidate.start_wall),
            end=(candidate.end_mono, candidate.end_wall), ttl=self.guard.policy.maximum_age)
        self._pending = (snapshot, candidate)
        return snapshot

    def install(self, snapshot, candidate):
        if (self._pending is None or self._pending[0] is not snapshot
                or self._pending[1] is not candidate or self._stopped or self.reads.closed
                or not self._owns_pair() or not self.guard.poll()
                or self.guard.lease.candidate is not candidate):
            self.invalidate('write_quota_publication_changed')
            raise QuotaUnavailable('write_quota_publication_changed')
        if self._budget is None:
            self._budget = _ObservedWriteBudget(self, snapshot, self.guard.last)
        else:
            self._budget._install(snapshot, self.guard.last)
        self._candidate, self._pending, self._reason = candidate, None, None

    def status(self):
        reason = self.check()
        return dict(available=reason is None and self._budget is not None,
                    reason=reason, live_ready=False,
                    sequence=None if self._candidate is None else self._candidate.sequence)
