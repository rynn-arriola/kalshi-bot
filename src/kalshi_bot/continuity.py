"""Pure, evidence-only account continuity assessment. Never grants entry authority."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .values import InvalidData, identity, integer, utc

REQUIRED_PRIVATE_CHANNELS = frozenset({'user_orders', 'fill', 'market_positions', 'order_group_updates'})


@dataclass(frozen=True)
class PrivateEpoch:
    epoch_id: str
    subaccount: int
    generation: int
    writer_epoch: str
    ack_channels: tuple[str, ...]
    opened_at: datetime
    closed_at: datetime | None = None
    ingress_count: int = 0
    durable_fill_count: int = 0
    terminal_reason: str | None = None
    clean_local_delivery: bool = False

    def __post_init__(self):
        identity(self.epoch_id)
        integer(self.subaccount, 0, 63)
        integer(self.generation, 1, 2**63-1)
        identity(self.writer_epoch)
        if (type(self.ack_channels) is not tuple or not self.ack_channels
                or len(self.ack_channels) > 8 or len(set(self.ack_channels)) != len(self.ack_channels)):
            raise InvalidData('invalid private subscription channels')
        for channel in self.ack_channels:
            identity(channel)
        opened = utc(self.opened_at)
        object.__setattr__(self, 'opened_at', opened)
        if self.closed_at is not None:
            closed = utc(self.closed_at)
            if closed < opened:
                raise InvalidData('private epoch clock regressed')
            object.__setattr__(self, 'closed_at', closed)
        integer(self.ingress_count, 0, 2**63-1)
        integer(self.durable_fill_count, 0, 2**63-1)
        # A staged fill can outnumber queue admissions when admission fails.
        if self.closed_at is None:
            if self.terminal_reason is not None or self.clean_local_delivery:
                raise InvalidData('open private epoch cannot claim delivery')
        elif (self.terminal_reason not in {'stopped', 'reader_error', 'cancelled',
                                          'undrained', 'scope_ambiguous', 'writer_failure',
                                          'engine_failure'}
              or (self.clean_local_delivery and self.terminal_reason != 'stopped')):
            raise InvalidData('invalid private epoch terminal state')


@dataclass(frozen=True)
class StartingAccountCandidate:
    subaccount: int
    proposed_boundary: datetime
    snapshot_observed_at: datetime
    writer_epoch: str
    writer_revision: int
    resting_order_ids: tuple[str, ...]
    foreign_order_ids: tuple[str, ...]
    unresolved_order_ids: tuple[str, ...]
    pending_fill_count: int
    positions: tuple[tuple[str, Decimal], ...]
    unresolved_basis_tickers: tuple[str, ...]
    blockers: tuple[str, ...]
    continuity_blockers: tuple[str, ...]
    approved: bool = False


@dataclass(frozen=True)
class ContinuityAssessment:
    subaccount: int
    generation: int
    writer_epoch: str
    writer_revision: int
    receipt_ids: tuple[str, ...]
    interval_gaps: tuple[tuple[int, int], ...]
    stream_epoch_id: str | None
    stream_span_state: str
    local_evidence_consistent: bool
    venue_handoff_proven: bool
    blockers: tuple[str, ...]


def starting_candidate(report, *, proposed_boundary, subaccount, writer_epoch, writer_revision,
                       continuity=None):
    """An explicit operator-review proposal from an already current scoped report."""
    if report is None or report.audit is None:
        raise InvalidData('current scoped account report required for candidate')
    scope = integer(subaccount, 0, 63)
    if (report.snapshot.subaccount != scope or report.audit.writer_epoch != writer_epoch
            or report.audit.writer_revision != writer_revision):
        raise InvalidData('candidate source revision or scope changed')
    boundary = utc(proposed_boundary)
    if boundary > utc(report.observed_at):
        raise InvalidData('candidate boundary is later than observed snapshot')
    positions = tuple((p.ticker, p.quantity) for p in report.snapshot.positions)
    return StartingAccountCandidate(scope, boundary, report.observed_at, writer_epoch,
        writer_revision, tuple(o.order_id for o in report.snapshot.orders),
        report.audit.foreign_order_ids,
        tuple(sorted(set(report.audit.missing_order_ids + report.audit.mismatched_order_ids))),
        report.audit.pending_fills, positions,
        tuple(ticker for ticker, qty in positions if qty), report.blockers,
        continuity.blockers if continuity is not None else ('continuity_assessment_missing',))


def assess_continuity(*, subaccount, generation, writer_epoch, writer_revision,
                      report=None, recovery=None, coverage=None, epoch=None,
                      history_ingress_revision=None, ingress_revision=0,
                      persisted_gap_count=None, epoch_ambiguous=False):
    """Only validates local, source-bound observations; venue proof is always false."""
    scope = integer(subaccount, 0, 63)
    blockers = []
    if report is None or report.audit is None:
        blockers.append('current_account_snapshot_missing')
    else:
        if report.snapshot.subaccount != scope:
            blockers.append('account_scope_conflict')
        if (report.audit.writer_epoch, report.audit.writer_revision) != (writer_epoch, writer_revision):
            blockers.append('account_writer_revision_changed')
        blockers.extend(report.audit.blockers)
    if recovery is None or recovery.enumeration is None:
        blockers.append('current_history_pass_missing')
        receipt_ids = ()
    else:
        receipt = recovery.enumeration
        receipt_ids = (receipt.receipt_id,)
        if ((recovery.generation, recovery.subaccount) != (generation, scope)
                or receipt.generation != generation or receipt.subaccount != scope
                or receipt.writer_epoch != writer_epoch
                or history_ingress_revision != ingress_revision):
            blockers.append('history_source_changed')
        if recovery.missing_fill_keys:
            blockers.append('unbound_fills_not_imported')
        if receipt.omitted_rows:
            blockers.append('previously_observed_fills_omitted')
    gaps = ()
    if coverage is not None:
        if coverage.subaccount != scope:
            blockers.append('history_inspection_scope_changed')
        else:
            gaps = coverage.gaps
            if gaps:
                blockers.append('history_enumeration_gaps')
            if coverage.omission_receipts:
                blockers.append('previously_observed_fills_omitted')
            receipt_ids = coverage.receipt_ids
    if epoch is None:
        span_state, epoch_id = 'unobserved', None
        blockers.append('private_epoch_unobserved')
    else:
        epoch_id = epoch.epoch_id
        span_state = ('open' if epoch.closed_at is None else
                      ('clean_local' if epoch.clean_local_delivery else 'invalid_local'))
        if frozenset(epoch.ack_channels) != REQUIRED_PRIVATE_CHANNELS:
            blockers.append('private_epoch_channels_incomplete')
        if ((epoch.subaccount, epoch.generation, epoch.writer_epoch) !=
                (scope, generation, writer_epoch)):
            blockers.append('private_epoch_source_changed')
        if epoch.closed_at is not None and not epoch.clean_local_delivery:
            blockers.append('private_epoch_invalid')
    if persisted_gap_count is None:
        blockers.append('private_epoch_history_unchecked')
    elif persisted_gap_count:
        blockers.append('persisted_private_epoch_gap')
    if epoch_ambiguous:
        blockers.append('private_epoch_scope_ambiguous')
    local = not blockers
    blockers.append('venue_history_stream_handoff_unproven')
    return ContinuityAssessment(scope, generation, writer_epoch, writer_revision,
        receipt_ids, gaps, epoch_id, span_state, local, False,
        tuple(dict.fromkeys(blockers)))
