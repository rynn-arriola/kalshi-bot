"""Account-proof lifecycle for the recovery runtime (review #1, 2026-09-26).

Routine renewal, own-order renewal (D-134/D-136/D-147/D-148), steady-scope
scheduling and their proof records, moved verbatim out of ``runtime.py``.
``RecoveryRuntime`` inherits ``AccountProofMixin``; the methods still operate on
the runtime's own state and never grant authority by themselves.
"""
import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .quota import QuotaUnavailable
from .values import InvalidData, utc


@dataclass(frozen=True)
class _SteadyAccountScope:
    """Exact full-cap/flat snapshot allowed to suppress optional discovery work.

    This is scheduling evidence only.  It never substitutes for a current
    account report, accounting lease, selection proof or dispatch authority.
    """
    account_generation: int
    account_revision: int
    writer_epoch: str
    writer_revision: int
    ingress_revision: int
    window_end: datetime
    snapshot_signature: tuple
    tickers: frozenset[str]


@dataclass(frozen=True)
class _RoutineAccountProof:
    """Historical renewal anchor, never a current entry/accounting lease."""
    source: tuple
    snapshot_signature: tuple
    receipt_ids: tuple[str, ...]
    end_us: int
    window_end: datetime


class RecoveryReads:
    """One pass shares a repair-count budget as well as underlying REST tokens."""
    def __init__(self, reads):
        self.reads, self.order_lookups = reads, 0

    async def read(self, name, **kwargs):
        if name == "order":
            if self.order_lookups >= 32:
                raise InvalidData("recovery order-lookup budget exhausted")
            self.order_lookups += 1
        return await self.reads.read(name, **kwargs)

    async def collect(self, name, **kwargs):
        return await self.reads.collect(name, **kwargs)


def audit_detail_fields(audit, now):
    """D-153: which order terms differed and how old our evidence was (log only)."""
    try:
        if audit is None or not audit.details:
            return {}
        now_us = int(utc(now).timestamp()*1_000_000)
        out = {}
        for kind in ('mismatch', 'missing'):
            rows = [row for row in audit.details if row[0] == kind]
            if not rows:
                continue
            ages = [max(0, (now_us-version)//1000) for _, _, version in rows if type(version) is int]
            out[f'{kind}_count'] = len(rows)
            if ages:
                out[f'{kind}_age_min_ms'], out[f'{kind}_age_max_ms'] = min(ages), max(ages)
        kinds = sorted({label for row in audit.details for label in row[1]})
        if kinds:
            out['mismatch_kinds'] = kinds
        return out
    except Exception:
        return {}  # Diagnostics never change the renewal outcome.


LAG_EVIDENCE_SECONDS = 10


def snapshot_lag_only(audit, now):
    """D-155: the audit failed only because Kalshi still lists orders we just
    saw end (``terminal_but_resting``, our evidence under 10 s old)."""
    try:
        if (audit is None or set(audit.blockers) != {'owned_order_terms_mismatch'}
                or not audit.details):
            return False
        now_us = int(utc(now).timestamp()*1_000_000)
        return all(kind == 'mismatch' and labels == ('terminal_but_resting',)
                   and type(version) is int and 0 <= now_us-version <= LAG_EVIDENCE_SECONDS*1_000_000
                   for kind, labels, version in audit.details)
    except Exception:
        return False


class AccountProofMixin:
    @staticmethod
    def _snapshot_signature(report):
        snapshot = report.snapshot
        return (snapshot.positions, snapshot.orders, snapshot.available_balance,
                snapshot.subaccount)

    def _routine_source(self):
        return (self.account.generation, self.account.revision, self.writer.epoch,
                self.writer.revision, self.ingress_revision,
                self._epoch.epoch_id if self._epoch is not None else None)

    def _record_routine_proof(self, receipt_ids, history):
        self._routine_account_proof = None
        report = self.account.current_report(self.now())
        result = self.accounting_result
        lease = self.writer._accounting_lease
        if (report is None or result is None or not result.released
                or result.window is None or result.window.held
                or lease is None or not lease.fence.current()
                or self.recovery_requested.is_set() or self.stop_requested.is_set()
                or history is None or history.enumeration is None
                or history.enumeration.omitted_rows or not receipt_ids
                or len(receipt_ids) >= 128):
            return
        self._routine_account_proof = _RoutineAccountProof(self._routine_source(),
            self._snapshot_signature(report), tuple(receipt_ids),
            history.enumeration.eligible_end_us, result.window.end)
        self._last_proof = (self._routine_account_proof, self.account.history_floor)

    # D-134: bound the carried receipt chain well below the 128-receipt proof
    # cap; beyond it, full recovery re-proves from the opening boundary.
    CHAIN_RECEIPT_LIMIT = 100
    # Let the venue's own order updates for an acknowledged command arrive
    # before renewing, instead of racing them.
    OWN_ORDER_SETTLE_SECONDS = .3
    OWN_ORDER_RETRIES = 3

    def _chain_anchor(self):
        """D-134: the last released proof, while nothing economic happened since.

        Valid only in the same account connection, writer epoch and private
        stream epoch, with an unchanged history floor. Fills, positions,
        foreign or unsettled orders, reconnects and every other invalidation
        move the floor and end reuse.
        """
        last = self._last_proof
        if last is None:
            return None
        proof, floor = last
        source = self._routine_source()
        if (floor != self.account.history_floor or self._epoch_ambiguous
                or (proof.source[0], proof.source[2], proof.source[5]) !=
                   (source[0], source[2], source[5])
                or len(proof.receipt_ids) >= self.CHAIN_RECEIPT_LIMIT):
            return None
        return proof

    def _current_own_order_anchor(self):
        proof = self._chain_anchor()
        owner = self.dispatch_supervisor
        state = owner.dispatcher.status() if owner is not None else None
        if (proof is None or self._routine_account_proof is not None
                or utc(self.now()) >= proof.window_end
                or not self.account_subscribed or not self.account.connected
                or self.engine.private or self.account._processing
                or self.writer.failed or self.engine.failed or self.engine.stopped
                or self.stop_requested.is_set() or self.recovery_requested.is_set()
                or (state is not None and (state.active is not None or state.queued
                    or state.stopping or state.failed))):
            return None
        return proof

    def own_order_acknowledged(self):
        """An acknowledged own command: renew instead of full recovery if possible."""
        self._account_ingress_at = self.clock()
        return (self._chain_anchor() is not None and not self.recovery_requested.is_set()
                and not self.recovery_lock.locked())

    # D-136: the only audit blockers a just-acknowledged own order can cause
    # before the venue's REST enumeration lists it. Bounded retry, then full
    # recovery; every other blocker is evidence and escalates at once.
    OWN_ORDER_PENDING_BLOCKERS = frozenset(('owned_working_order_missing',
                                            'unbound_order_intents'))

    def _own_order_unexplained(self, report, proof):
        """None when only the bot's own working orders (and cash with them) changed."""
        signature = self._snapshot_signature(report)
        positions, orders, balance, subaccount = proof.snapshot_signature
        audit = report.audit
        if signature[0] != positions or signature[3] != subaccount:
            return 'position_changed'
        if signature[2] != balance and signature[1] == orders:
            return 'cash_changed'
        if not report.positions_match:
            return 'position_mismatch'
        if audit is None:
            return 'audit_blocked'
        if audit.consistent:
            return None
        if set(audit.blockers) <= self.OWN_ORDER_PENDING_BLOCKERS:
            return 'order_not_visible'
        return 'audit_blocked'

    def _snapshot_explained(self, report, proof, *, own_orders):
        if not own_orders:
            return self._snapshot_signature(report) == proof.snapshot_signature
        return self._own_order_unexplained(report, proof) is None

    def _raced_by_private(self, proof, history):
        """D-148: a clean tail, and only private account ingress moved the source.

        Same connection, writer epoch and private stream epoch, and the account
        revision advanced (a private event arrived mid-read). A write with no
        private event, a slow read, a reconnect or any tail evidence is not.
        """
        source = self._routine_source()
        clean = (not history.enumeration.omitted_rows if history is not None
                 else getattr(self.account, 'tail_fetched_empty', None) is True)
        return (clean
                and source[0] == proof.source[0] and source[1] != proof.source[1]
                and source[2] == proof.source[2] and source[5] == proof.source[5])

    def _current_routine_proof(self):
        proof = self._routine_account_proof
        owner = self.dispatch_supervisor
        state = owner.dispatcher.status() if owner is not None else None
        if (proof is None or proof.source != self._routine_source()
                or utc(self.now()) >= proof.window_end
                or not self.account_subscribed or not self.account.connected
                or self.engine.private or self.account._processing or self._epoch_ambiguous
                or self.writer.failed or self.engine.failed or self.engine.stopped
                or self.stop_requested.is_set() or self.recovery_requested.is_set()
                or (state is not None and (state.active is not None or state.queued
                    or state.stopping or state.failed))):
            return None
        return proof

    async def _refresh_routine_account(self, anchor=None):
        """Renew through existing release checks; never replay full startup work.

        A bounded receipt chain preserves the complete original interval. Every
        tail is empty, omission-free and checked by the writer at release.
        Fresh cash/funding/settlement enumeration remains mandatory: unchanged
        balance alone cannot establish unchanged economics.

        D-134: with ``anchor`` (the last released proof, still valid under the
        history floor) the same renewal runs after the bot's own acknowledged
        orders: positions must be unchanged, only working orders (and cash
        with them) may differ, the writer audit must be consistent and the
        elapsed history tail must be empty.
        """
        own = anchor is not None
        proof = anchor if own else self._current_routine_proof()
        if proof is None or self.recovery_lock.locked():
            return False
        start_source = self._routine_source()
        writer_source = (start_source[2], start_source[3]) if own else (proof.source[2], proof.source[3])
        started = self.clock()
        self.routine_refresh_phase_ms = {}
        if own:
            self.own_order_renewal['attempts'] += 1
        else:
            self.routine_refresh_attempts += 1
        succeeded = False
        failure = None
        released = None
        unexplained = False
        audit_blockers = ()  # D-146: which audit check blocked an own renewal.
        failed_audit = None  # D-153: the audit behind an unexplained own renewal.
        raced = False  # D-148: clean evidence, only the source moved mid-read.
        async with self.recovery_lock:
            try:
                async with asyncio.timeout(20):
                    self.routine_refresh_phase = 'snapshot_and_tail'
                    end = utc(self.now())
                    start = datetime.fromtimestamp(proof.end_us//1_000_000,
                        tz=timezone.utc).replace(microsecond=proof.end_us%1_000_000)
                    if end <= start:
                        return False
                    reads = RecoveryReads(self.reads)
                    # Join both requests even if one fails; no orphaned read
                    # may race the fallback recovery owner.
                    history, reconciled = await asyncio.gather(
                        self.account.extend_empty_history(reads, start=start, end=end, now=self.now),
                        self.account.reconcile(reads, now=self.now,
                            expected_writer_source=writer_source,
                            prepare_accounting_boundary=self.accounting_boundary),
                        return_exceptions=True)
                    self.routine_refresh_phase_ms['snapshot_and_tail'] = max(
                        0, int((self.clock()-started)*1000))
                    for value in (history, reconciled):
                        if isinstance(value, BaseException):
                            raise value
                    if reconciled is None:
                        # The snapshot was superseded mid-read (source or
                        # writer moved); with a clean tail that is a race.
                        raced = not own and self._raced_by_private(proof, history)
                        return False
                    report, prepared = reconciled
                    expected = start_source if own else proof.source
                    unexplained = (report is not None and self.account.current_report(self.now()) is report
                                   and not self._snapshot_explained(report, proof, own_orders=own))
                    if unexplained and own:
                        unexplained = self._own_order_unexplained(report, proof)
                        if unexplained == 'audit_blocked' and report.audit is not None:
                            audit_blockers = tuple(report.audit.blockers)
                        if unexplained in ('audit_blocked', 'order_not_visible'):
                            failed_audit = report.audit
                    raced = (not own and report is not None and not unexplained
                             and self._raced_by_private(proof, history))
                    if (history is None or report is None
                            or history.enumeration.omitted_rows
                            or (self._chain_anchor() if own else self._routine_account_proof) is not proof
                            or self.recovery_requested.is_set()
                            or self._routine_source()[:3]+self._routine_source()[4:] !=
                               expected[:3]+expected[4:]
                            or self.account.current_report(self.now()) is not report
                            or not self._snapshot_explained(report, proof, own_orders=own)):
                        return False
                    self.last_reports = (history, report)
                    self.history_ingress_revision = self.ingress_revision
                    ids = proof.receipt_ids+(history.enumeration.receipt_id,)
                    continuity = replace(self._refresh_continuity(operational=True), receipt_ids=ids)
                    self.routine_refresh_phase = 'accounting_release'
                    release_started = self.clock()
                    self.accounting_result = await self.account.release_prepared_accounting(
                        prepared, continuity=continuity, now=self.now)
                    released = self.accounting_result.released
                    self.routine_refresh_phase_ms['accounting_release'] = max(
                        0, int((self.clock()-release_started)*1000))
                    # Release advances writer revision itself. The account owner
                    # supplies its new audit; never rebase an earlier snapshot.
                    if (not self.accounting_result.released
                            or self.recovery_requested.is_set()
                            or self.account.current_report(self.now()) is None
                            or self.writer._accounting_lease is None
                            or not self.writer._accounting_lease.fence.current()):
                        return False
                    self._record_routine_proof(ids, history)
                    report = self.account.current_report(self.now())
                    scope = self._record_steady_account_scope(report)
                    self._schedule_account_refresh(scope)
                    if self.rewards is not None:
                        self.rewards.request_reflection()
                    if own:
                        self.own_order_renewal['completed'] += 1
                        self._own_renewal_retries = 0
                    else:
                        self.routine_refresh_completed += 1
                    succeeded = True
                    return True
            except (InvalidData, QuotaUnavailable, TimeoutError, OSError) as exc:
                failure = exc
                return False
            finally:
                self.routine_refresh_elapsed_ms = max(0, int((self.clock()-started)*1000))
                failed_phase = self.routine_refresh_phase
                self.routine_refresh_phase = 'idle'
                if not succeeded:
                    self.account.revoke_accounting()
                    cause = 'own_order_renewal_failed' if own else 'routine_refresh_failed'
                    if own and released is False:
                        self._last_proof = None  # Release rejected the chain itself.
                    if (own and failure is None and released is None
                            and (unexplained in (False, 'order_not_visible')
                                 or snapshot_lag_only(failed_audit, self.now()))
                            and self._own_renewal_retries < self.OWN_ORDER_RETRIES
                            and self._chain_anchor() is not None):
                        # A non-economic source change raced this attempt (for
                        # example the venue's own order update arriving). Retry
                        # the same bounded renewal instead of a full recovery.
                        self._own_renewal_retries += 1
                        self.own_order_renewal['retries'] += 1
                    elif (raced and failure is None and released is None
                          and self._chain_anchor() is not None):
                        # D-148: a routine renewal whose tail was empty and whose
                        # snapshot matched, overtaken only by a source change
                        # (typically the bot's own order update) while nothing
                        # economic happened since the last released proof.
                        # Hand over to the own-order renewal, which
                        # re-verifies positions, cash and audit from a fresh
                        # snapshot and escalates to full recovery itself.
                        self._routine_account_proof = None
                        self._account_ingress_at = self.clock()
                        self.routine_own_fallbacks = self.routine_own_fallbacks+1
                    else:
                        self._own_renewal_retries = 0
                        if own:
                            self.own_order_renewal['escalations'] += 1
                        else:
                            self.routine_refresh_escalations += 1
                        self.request_recovery(cause)
                    self.diagnostics.emit('account_refresh_failed', error=failure,
                        cause=cause, phase=failed_phase, blockers=audit_blockers,
                        **audit_detail_fields(failed_audit, self.now()),
                        elapsed_ms=self.routine_refresh_elapsed_ms,
                        outcome=('quota_wait' if isinstance(failure, QuotaUnavailable)
                            else 'timeout' if isinstance(failure, TimeoutError)
                            else 'io' if isinstance(failure, OSError)
                            else 'invalid_data' if failure is not None
                            else unexplained if isinstance(unexplained, str)
                            else 'source_changed'))

    def _schedule_account_refresh(self, scope):
        # A just-canceled owner can be flat and absent from inventory repair.
        # Reevaluate its exact terminal/fill proof before broad catalog work;
        # priority is scheduling only, never ACK-based capacity release.
        cycle = self.maintenance.cycle if self.maintenance is not None else None
        if cycle is not None:
            self.engine.dirty.mark(cycle.ticker, priority=True)
        for ticker in getattr(self.maintenance, 'risk_latched', ()):
            if ticker in self.engine.market_shard:
                self.engine.dirty.mark(ticker, priority=True)
        for ticker in scope or self.engine.market_shard:
            self.engine.dirty.mark(ticker)
        self.engine.wake.set()

    def _current_steady_account_scope(self):
        """Return an exact scheduling scope, never live/account authority."""
        value = self._steady_account_scope
        if value is None:
            return None
        gate = self.selection.initial_ranking if self.selection is not None else None
        now = utc(self.now())
        if (not self.broad_discovery or gate is None or gate.reason != 'coverage_complete'
                or not self.account.connected or self.engine.stopped or self.engine.failed
                or self.writer.failed or self.stop_requested.is_set()
                or now >= value.window_end
                or (self.account.generation, self.account.revision) !=
                   (value.account_generation, value.account_revision)
                or (self.writer.epoch, self.writer.revision) !=
                   (value.writer_epoch, value.writer_revision)
                or self.ingress_revision != value.ingress_revision):
            self._steady_account_scope = None
            return None
        return value.tickers

    def _record_steady_account_scope(self, report, *, expected_signature=None):
        """Remember exact full-cap/flat state only to bound optional CPU work."""
        self._steady_account_scope = None
        gate = self.selection.initial_ranking if self.selection is not None else None
        window = getattr(self.accounting_result, 'window', None)
        now = utc(self.now())
        dispatcher = self.dispatch_supervisor.dispatcher.status() if self.dispatch_supervisor else None
        signature = self._snapshot_signature(report)
        rows = self.current_entry_orders()
        if (not self.broad_discovery or gate is None or gate.reason != 'coverage_complete'
                or report is not self.account.current_report(now)
                or not self.account.connected or self.engine.stopped or self.engine.failed
                or self.writer.failed or self.stop_requested.is_set()
                or report.audit is None or report.audit.blockers or not report.audit.consistent
                or not report.positions_match
                or report.snapshot.positions or rows is None
                or len(rows) != len(report.snapshot.orders)
                or window is None or window.held or not window.start <= now < window.end
                or window.cap <= 0 or len(rows) != window.cap
                or (expected_signature is not None and signature != expected_signature)
                or (dispatcher is not None and (dispatcher.active is not None or dispatcher.queued
                    or dispatcher.stopping or dispatcher.failed))):
            return None
        value = _SteadyAccountScope(self.account.generation, self.account.revision,
            self.writer.epoch, self.writer.revision, self.ingress_revision, window.end,
            signature, frozenset(row.ticker for row in rows))
        self._steady_account_scope = value
        return value.tickers

    async def _refresh_steady_account(self):
        """Refresh a proven full-cap/flat snapshot without a full history pass.

        The account REST enumeration remains exact and source-fenced.  Any
        changed economic/account state or concurrent full-recovery request drops
        this optimization and queues the ordinary recovery owner.
        """
        scope = self._current_steady_account_scope()
        if scope is None or self.recovery_requested.is_set() or self.recovery_lock.locked():
            return False
        owner = self.dispatch_supervisor
        if owner is not None:
            state = owner.dispatcher.status()
            if state.active is not None or state.queued or state.stopping or state.failed:
                return False
        async with self.recovery_lock:
            scope = self._current_steady_account_scope()
            if scope is None or self.recovery_requested.is_set():
                return False
            prior = self._steady_account_scope
            self.steady_refresh_attempts += 1
            failure = None
            try:
                async with asyncio.timeout(20):
                    report = await self.account.reconcile(RecoveryReads(self.reads), now=self.now)
            except (InvalidData, QuotaUnavailable, TimeoutError, OSError) as exc:
                failure = exc
                report = None
            if (report is None or self.recovery_requested.is_set()
                    or (self.account.generation, self.account.revision, self.ingress_revision) !=
                       (prior.account_generation, prior.account_revision, prior.ingress_revision)):
                self.steady_refresh_escalations += 1
                self.request_recovery('steady_refresh_failed')
                self.diagnostics.emit('account_refresh_failed', error=failure,
                    cause='steady_refresh_failed', phase='first_snapshot', outcome='source_changed')
                return False
            refreshed = self._record_steady_account_scope(
                report, expected_signature=prior.snapshot_signature)
            if refreshed != scope:
                self.steady_refresh_escalations += 1
                self.request_recovery('steady_refresh_failed')
                self.diagnostics.emit('account_refresh_failed', cause='steady_refresh_failed',
                    phase='first_snapshot', outcome='source_changed')
                return False
            if self.last_reports is not None:
                self.last_reports = (self.last_reports[0], report)
            self._refresh_continuity()
            for ticker in sorted(scope):
                await self.management.refresh(ticker)
                self._request_inventory_dispatch(ticker)
                if self.selection is not None:
                    self.selection.refresh(ticker)
                if self.rewards is not None:
                    self.rewards.refresh(ticker)
                if self.maintenance is not None:
                    self.maintenance.refresh(ticker)
                    self._request_quote_dispatch(ticker)
            if self.rewards is not None:
                self.rewards.request_reflection()
            self.steady_refresh_completed += 1
            return True
