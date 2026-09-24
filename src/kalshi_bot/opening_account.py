"""Bounded opening-account and cash evidence. Never grants entry authority."""
import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from .rest import PageSet
from .values import InvalidData, count, decimal, identity, integer, utc


def _nonnegative(value, label):
    result = decimal(value)
    if result < 0:
        raise InvalidData(f'negative {label}')
    return result


def _time(value, label):
    if not isinstance(value, str) or len(value) > 64:
        raise InvalidData(f'invalid {label}')
    try:
        return utc(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except ValueError as exc:
        raise InvalidData(f'invalid {label}') from exc


@dataclass(frozen=True, slots=True)
class ExchangeBalance:
    exchange_index: int
    available: Decimal

    def __post_init__(self):
        integer(self.exchange_index, 0, 2**31-1)
        object.__setattr__(self, 'available', _nonnegative(self.available, 'exchange balance'))


@dataclass(frozen=True, slots=True)
class CashObservation:
    subaccount: int
    available: Decimal
    portfolio_value: Decimal
    updated_ts: int
    exchange_balances: tuple[ExchangeBalance, ...]
    legacy_balance_cents: int

    def __post_init__(self):
        integer(self.subaccount, 0, 63)
        object.__setattr__(self, 'available', _nonnegative(self.available, 'available balance'))
        object.__setattr__(self, 'portfolio_value',
                           _nonnegative(self.portfolio_value, 'portfolio value'))
        integer(self.updated_ts, 0, 2**63-1)
        integer(self.legacy_balance_cents, 0, 2**63-1)
        # The published contract does not specify the legacy cent rounding.
        # Preserve subcent differences; never round away the precise balance.
        if abs(Decimal(self.legacy_balance_cents)/100-self.available) >= Decimal('0.01'):
            raise InvalidData('legacy and fixed-point balances conflict')
        if type(self.exchange_balances) is not tuple or len(self.exchange_balances) > 256:
            raise InvalidData('invalid exchange balance breakdown')
        if any(not isinstance(row, ExchangeBalance) for row in self.exchange_balances):
            raise InvalidData('invalid exchange balance breakdown')
        indexes = [row.exchange_index for row in self.exchange_balances]
        if len(indexes) != len(set(indexes)):
            raise InvalidData('duplicate exchange balance')
        if self.exchange_balances and sum((row.available for row in self.exchange_balances),
                                          Decimal(0)) != self.available:
            raise InvalidData('exchange balances do not sum to available balance')


@dataclass(frozen=True, slots=True)
class SettlementObservation:
    ticker: str
    exchange_index: int
    event_ticker: str
    result: str
    yes_count: Decimal
    yes_cost: Decimal
    no_count: Decimal
    no_cost: Decimal
    revenue_cents: int
    fee: Decimal
    value_cents: int | None
    settled_at: datetime

    def __post_init__(self):
        identity(self.ticker); identity(self.event_ticker)
        integer(self.exchange_index, 0, 2**31-1)
        if self.result not in {'yes', 'no', 'scalar'}:
            raise InvalidData('unsupported settlement result')
        object.__setattr__(self, 'yes_count', count(self.yes_count, zero=True))
        object.__setattr__(self, 'no_count', count(self.no_count, zero=True))
        object.__setattr__(self, 'yes_cost', _nonnegative(self.yes_cost, 'yes settlement cost'))
        object.__setattr__(self, 'no_cost', _nonnegative(self.no_cost, 'no settlement cost'))
        integer(self.revenue_cents, 0, 2**63-1)
        object.__setattr__(self, 'fee', _nonnegative(self.fee, 'settlement fee'))
        if self.value_cents is not None:
            integer(self.value_cents, 0, 100)
        object.__setattr__(self, 'settled_at', utc(self.settled_at))

    @property
    def key(self):
        return (self.ticker, self.exchange_index, self.settled_at)


@dataclass(frozen=True, slots=True)
class SubaccountTransfer:
    transfer_id: str
    from_subaccount: int
    to_subaccount: int
    amount_cents: int
    created_ts: int
    exchange_index: int

    def __post_init__(self):
        identity(self.transfer_id)
        integer(self.from_subaccount, 0, 63); integer(self.to_subaccount, 0, 63)
        if self.from_subaccount == self.to_subaccount:
            raise InvalidData('subaccount transfer has identical endpoints')
        integer(self.amount_cents, 1, 2**63-1)
        integer(self.created_ts, 0, 2**63-1)
        integer(self.exchange_index, 0, 2**31-1)


@dataclass(frozen=True, slots=True)
class IntraExchangeTransfer:
    transfer_id: str
    source: str
    destination: str
    source_exchange_index: int
    destination_exchange_index: int
    amount: Decimal
    status: str
    created_ts: int

    def __post_init__(self):
        for value in (self.transfer_id, self.source, self.destination, self.status):
            identity(value)
        if self.source not in {'event_contract', 'margined'} or self.destination not in {
                'event_contract', 'margined'} or self.status not in {'pending', 'complete'}:
            raise InvalidData('invalid intra-exchange transfer enum')
        integer(self.source_exchange_index, 0, 2**31-1)
        integer(self.destination_exchange_index, 0, 2**31-1)
        object.__setattr__(self, 'amount', _nonnegative(self.amount, 'intra-exchange transfer'))
        if not self.amount:
            raise InvalidData('zero intra-exchange transfer')
        integer(self.created_ts, 0, 2**63-1)


@dataclass(frozen=True, slots=True)
class FundingObservation:
    kind: str
    record_id: str
    status: str
    method: str
    amount_cents: int
    fee_cents: int
    created_ts: int
    finalized_ts: int | None

    def __post_init__(self):
        if self.kind not in {'deposit', 'withdrawal'}:
            raise InvalidData('invalid funding kind')
        for value in (self.record_id, self.status, self.method):
            identity(value)
        if (self.status not in {'pending', 'applied', 'failed', 'returned'}
                or self.method not in {'ach', 'wire', 'crypto', 'debit', 'apm'}):
            raise InvalidData('invalid funding enum')
        integer(self.amount_cents, 0, 2**63-1)
        integer(self.fee_cents, 0, 2**63-1)
        integer(self.created_ts, 0, 2**63-1)
        if self.finalized_ts is not None:
            integer(self.finalized_ts, self.created_ts, 2**63-1)


@dataclass(frozen=True, slots=True)
class SourcePageEvidence:
    name: str
    pages: int
    rows: int
    wire_bytes: int
    query: tuple[tuple[str, object], ...] = ()

    def __post_init__(self):
        identity(self.name)
        integer(self.pages, 1, 100); integer(self.rows, 0, 10000)
        integer(self.wire_bytes, 0, 16777216)
        if type(self.query) is not tuple or len(self.query) > 16:
            raise InvalidData('invalid source query evidence')
        for item in self.query:
            if (type(item) is not tuple or len(item) != 2
                    or not isinstance(item[0], str)):
                raise InvalidData('invalid source query evidence')


@dataclass(frozen=True, slots=True)
class OpeningAccountEvidence:
    subaccount: int
    proposed_boundary: datetime
    observed_at: datetime
    writer_epoch: str
    writer_revision: int
    cash: CashObservation
    settlements: tuple[SettlementObservation, ...]
    subaccount_transfers: tuple[SubaccountTransfer, ...]
    intra_exchange_transfers: tuple[IntraExchangeTransfer, ...]
    funding: tuple[FundingObservation, ...]
    sources: tuple[SourcePageEvidence, ...]
    blockers: tuple[str, ...]
    snapshot_observed_at: datetime
    # Complete cursor-exhausted funding source, including fully finalized
    # pre-boundary rows. It proves lifecycle enrichment but grants no authority.
    funding_history: tuple[FundingObservation, ...] = ()
    approved: bool = False
    ready_for_entry: bool = False

    def __post_init__(self):
        integer(self.subaccount, 0, 63)
        object.__setattr__(self, 'proposed_boundary', utc(self.proposed_boundary))
        object.__setattr__(self, 'observed_at', utc(self.observed_at))
        object.__setattr__(self, 'snapshot_observed_at', utc(self.snapshot_observed_at))
        if not self.proposed_boundary <= self.snapshot_observed_at <= self.observed_at:
            raise InvalidData('invalid opening evidence time order')
        identity(self.writer_epoch); integer(self.writer_revision, 0, 2**63-1)
        if self.cash.subaccount != self.subaccount:
            raise InvalidData('cash scope differs from opening evidence')
        for values, cls, limit in (
                (self.settlements, SettlementObservation, 10000),
                (self.subaccount_transfers, SubaccountTransfer, 10000),
                (self.intra_exchange_transfers, IntraExchangeTransfer, 10000),
                (self.funding, FundingObservation, 20000),
                (self.funding_history, FundingObservation, 20000),
                (self.sources, SourcePageEvidence, 8)):
            if (type(values) is not tuple or len(values) > limit
                    or any(not isinstance(value, cls) for value in values)):
                raise InvalidData('invalid bounded opening evidence')
        if self.approved or self.ready_for_entry or not self.blockers:
            raise InvalidData('opening evidence cannot grant authority')


@dataclass(frozen=True, slots=True)
class OpeningAccountingAssessment:
    """Local opening diagnostics; never an installed balance or risk basis."""
    subaccount: int
    proposed_boundary: datetime
    writer_epoch: str
    writer_revision: int
    local_flat_candidate: bool
    cash_snapshot_agrees: bool
    settlement_rows: int
    cash_activity_rows: int
    observed_settlement_reconciliation_required: bool
    blockers: tuple[str, ...]
    approved: bool = False
    ready_for_entry: bool = False

    def __post_init__(self):
        integer(self.subaccount, 0, 63)
        object.__setattr__(self, 'proposed_boundary', utc(self.proposed_boundary))
        identity(self.writer_epoch)
        integer(self.writer_revision, 0, 2**63-1)
        if (type(self.local_flat_candidate) is not bool
                or type(self.cash_snapshot_agrees) is not bool):
            raise InvalidData('boolean opening diagnostics required')
        integer(self.settlement_rows, 0, 10000)
        integer(self.cash_activity_rows, 0, 40000)
        if (type(self.observed_settlement_reconciliation_required) is not bool
                or self.observed_settlement_reconciliation_required != (self.settlement_rows > 0)):
            raise InvalidData('settlement reconciliation marker must match evidence')
        if (type(self.blockers) is not tuple or not self.blockers
                or self.approved or self.ready_for_entry):
            raise InvalidData('opening assessment cannot grant authority')


def cash_snapshot_agrees(cash, snapshot):
    """Compare economics across sequential balance reads.

    Kalshi advances ``updated_ts`` on an otherwise unchanged balance response.
    The opening inspection necessarily follows the account snapshot, so a
    later timestamp is acceptable only when available cash is unchanged. A
    regressed timestamp or changed amount remains a failed bracket.
    """
    return (cash.available == snapshot.available_balance
            and cash.updated_ts >= snapshot.balance_updated_ts)


def assess_opening_accounting(evidence: OpeningAccountEvidence, report):
    """Classify exact local flat/cash observations without promoting them.

    No database, network, settlement arithmetic or cash-flow attribution.
    This remains non-authorizing even for an apparently empty account.
    """
    from .account import ReconciliationReport
    if (not isinstance(evidence, OpeningAccountEvidence)
            or not isinstance(report, ReconciliationReport)
            or report.audit is None):
        raise InvalidData('typed opening evidence and account audit required')
    if ((report.snapshot.subaccount, report.audit.writer_epoch,
         report.audit.writer_revision, utc(report.observed_at)) !=
            (evidence.subaccount, evidence.writer_epoch,
             evidence.writer_revision, evidence.snapshot_observed_at)):
        raise InvalidData('opening assessment source revision or scope changed')
    audit = report.audit
    if (report.positions_match != audit.positions_match
            or report.unresolved_intents != audit.unresolved_intents):
        raise InvalidData('opening assessment report and audit disagree')
    flat = (evidence.subaccount == 0 and report.positions_match
            and audit.consistent and report.unresolved_intents == 0
            and audit.pending_fills == 0
            and not report.snapshot.orders
            and not any(row.quantity != 0 for row in report.snapshot.positions))
    cash_agrees = cash_snapshot_agrees(evidence.cash, report.snapshot)
    blockers = list(evidence.blockers)
    if not flat:
        blockers.append('local_flat_candidate_unproven')
    if not cash_agrees:
        blockers.append('cash_changed_since_account_snapshot')
    # D-066: this is a conservative observation, not bot-ownership proof.
    # The proposed boundary is unapproved and the result cannot clear a hold.
    needs_settlement_reconciliation = bool(evidence.settlements)
    if needs_settlement_reconciliation:
        blockers.append('observed_settlement_requires_reconciliation')
    return OpeningAccountingAssessment(evidence.subaccount,
        evidence.proposed_boundary, evidence.writer_epoch,
        evidence.writer_revision, flat, cash_agrees, len(evidence.settlements),
        len(evidence.subaccount_transfers) + len(evidence.intra_exchange_transfers)
        + len(evidence.funding), needs_settlement_reconciliation,
        tuple(dict.fromkeys(blockers)))


def parse_cash(document, *, subaccount):
    try:
        breakdown = []
        raw_breakdown = document.get('balance_breakdown', ())
        if not isinstance(raw_breakdown, (list, tuple)) or len(raw_breakdown) > 256:
            raise InvalidData('invalid exchange balance breakdown')
        for row in raw_breakdown:
            breakdown.append(ExchangeBalance(row['exchange_index'], row['balance']))
        # The API exposes portfolio_value in cents, unlike balance_dollars.
        legacy = integer(document['balance'], 0, 2**63-1)
        available = decimal(document['balance_dollars'])
        portfolio = Decimal(integer(document['portfolio_value'], 0, 2**63-1))/100
        return CashObservation(integer(subaccount, 0, 63), available,
                               portfolio, document['updated_ts'], tuple(breakdown), legacy)
    except (KeyError, TypeError) as exc:
        raise InvalidData('incomplete cash observation') from exc


def _unique(rows, key, label):
    result = {}
    for row in rows:
        identity_key = key(row)
        prior = result.get(identity_key)
        if prior is not None and prior != row:
            raise InvalidData(f'conflicting duplicate {label}')
        result[identity_key] = row
    return tuple(result[k] for k in sorted(result))


def parse_settlements(rows, *, boundary, observed_at=None):
    boundary = utc(boundary)
    upper = utc(observed_at) if observed_at is not None else None
    values = []
    try:
        for row in rows:
            settled = _time(row['settled_time'], 'settlement time')
            if settled < boundary:
                continue
            if upper is not None and settled > upper:
                raise InvalidData('settlement is later than account snapshot')
            values.append(SettlementObservation(row['ticker'], row['exchange_index'],
                row['event_ticker'], row['market_result'], row['yes_count_fp'],
                row['yes_total_cost_dollars'], row['no_count_fp'],
                row['no_total_cost_dollars'], row['revenue'], row['fee_cost'],
                row.get('value'), settled))
    except (KeyError, TypeError) as exc:
        raise InvalidData('incomplete settlement observation') from exc
    return _unique(values, lambda row: row.key, 'settlement')


def parse_subaccount_transfers(rows, *, subaccount, boundary, observed_at=None):
    scope, minimum = integer(subaccount, 0, 63), int(utc(boundary).timestamp())
    maximum = int(utc(observed_at).timestamp()) if observed_at is not None else None
    values = []
    try:
        for row in rows:
            item = SubaccountTransfer(row['transfer_id'], row['from_subaccount'],
                row['to_subaccount'], row['amount_cents'], row['created_ts'],
                row['exchange_index'])
            if maximum is not None and item.created_ts > maximum:
                raise InvalidData('subaccount transfer is later than account snapshot')
            if item.created_ts >= minimum and scope in (item.from_subaccount, item.to_subaccount):
                values.append(item)
    except (KeyError, TypeError) as exc:
        raise InvalidData('incomplete subaccount transfer') from exc
    return _unique(values, lambda row: row.transfer_id, 'subaccount transfer')


def parse_intra_exchange_transfers(rows, *, boundary, observed_at=None):
    minimum, values = int(utc(boundary).timestamp()), []
    maximum = int(utc(observed_at).timestamp()) if observed_at is not None else None
    try:
        for row in rows:
            item = IntraExchangeTransfer(row['transfer_id'], row['source'], row['destination'],
                row['source_exchange_shard'], row['destination_exchange_shard'],
                row['amount'], row['status'], row['created_ts'])
            if maximum is not None and item.created_ts > maximum:
                raise InvalidData('intra-exchange transfer is later than account snapshot')
            # No completion timestamp is published. Even an older "complete"
            # row may have completed after the proposed boundary.
            values.append(item)
    except (KeyError, TypeError) as exc:
        raise InvalidData('incomplete intra-exchange transfer') from exc
    return _unique(values, lambda row: row.transfer_id, 'intra-exchange transfer')


def parse_funding_history(rows, *, kind, boundary, observed_at=None):
    """Normalize the complete funding source without assigning relevance."""
    utc(boundary)
    values = []
    maximum = int(utc(observed_at).timestamp()) if observed_at is not None else None
    try:
        for row in rows:
            item = FundingObservation(kind, row['id'], row['status'], row['type'],
                row['amount_cents'], row['fee_cents'], row['created_ts'],
                row.get('finalized_ts'))
            if (maximum is not None and (item.created_ts > maximum
                    or (item.finalized_ts is not None and item.finalized_ts > maximum))):
                raise InvalidData('funding observation is later than account snapshot')
            values.append(item)
    except (KeyError, TypeError) as exc:
        raise InvalidData('incomplete funding observation') from exc
    return _unique(values, lambda row: (row.kind, row.record_id), 'funding observation')


def parse_funding(rows, *, kind, boundary, observed_at=None):
    """Return only funding whose completion can affect the opening boundary."""
    minimum = int(utc(boundary).timestamp())
    return tuple(item for item in parse_funding_history(rows, kind=kind,
        boundary=boundary, observed_at=observed_at)
        if (item.created_ts >= minimum or item.status == 'pending'
            or item.finalized_ts is None or item.finalized_ts >= minimum))


def _prepare_opening_evidence(*, report, continuity, proposed_boundary, subaccount,
                           writer_epoch, writer_revision, cash_document,
                           settlements, subaccount_transfers,
                           intra_exchange_transfers, deposits, withdrawals,
                           observed_at=None):
    """Validate original source metadata before any normalization, on either path."""
    scope, boundary = integer(subaccount, 0, 63), utc(proposed_boundary)
    if report is None or report.audit is None or continuity is None:
        raise InvalidData('current report and continuity assessment required')
    if (report.snapshot.subaccount != scope
            or (report.audit.writer_epoch, report.audit.writer_revision) !=
               (writer_epoch, writer_revision)
            or (continuity.subaccount, continuity.writer_epoch,
                continuity.writer_revision) != (scope, writer_epoch, writer_revision)
            or boundary > utc(report.observed_at)):
        raise InvalidData('opening evidence source revision or scope changed')
    page_sets = (('settlements', settlements),
                 ('subaccount_transfers', subaccount_transfers),
                 ('intra_exchange_transfers', intra_exchange_transfers),
                 ('deposits', deposits), ('withdrawals', withdrawals))
    if any(not isinstance(value, PageSet) or value.source != name or not value.exhausted
           for name, value in page_sets):
        raise InvalidData('cursor-exhausted source pages required')
    sources = []
    for name, value in page_sets:
        if type(value.rows) is not tuple or len(value.rows) > 10000:
            raise InvalidData('invalid bounded source rows')
        sources.append(SourcePageEvidence(name, value.pages, len(value.rows),
                                           value.wire_bytes, value.query))
        query = dict(value.query)
        allowed = {'limit', 'subaccount', 'min_ts'} if name == 'settlements' else {'limit'}
        if len(query) != len(value.query) or set(query)-allowed:
            raise InvalidData('source query narrows opening evidence')
        if 'limit' in query:
            integer(query['limit'], 1, 1000)
        if name == 'settlements':
            if integer(query.get('subaccount'), 0, 63) != scope:
                raise InvalidData('settlement enumeration lacks exact account scope')
            if 'min_ts' in query:
                integer(query['min_ts'], 0, max(0, int(boundary.timestamp())-1))
    observed = utc(observed_at) if observed_at is not None else utc(report.observed_at)
    if observed < utc(report.observed_at):
        raise InvalidData('opening observation clock regressed')
    cash = parse_cash(cash_document, subaccount=scope)
    if cash.updated_ts > int(observed.timestamp()):
        raise InvalidData('cash observation is later than inspection')
    blockers = list(report.blockers) + list(continuity.blockers)
    blockers.extend(('venue_history_stream_handoff_unproven',
                     'cash_snapshot_not_atomic',
                     'operator_boundary_not_approved',
                     'primary_account_flat_start_not_verified',
                     'opening_basis_not_installed'))
    if scope != 0:
        blockers.append('primary_account_required')
    if any(row.quantity != 0 for row in report.snapshot.positions):
        blockers.append('opening_inventory_present')
    if report.snapshot.orders:
        blockers.append('opening_resting_orders_present')
    if Decimal(cash.legacy_balance_cents)/100 != cash.available:
        blockers.append('legacy_balance_precision_unverified')
    if not cash_snapshot_agrees(cash, report.snapshot):
        blockers.append('cash_changed_since_account_snapshot')
    base = OpeningAccountEvidence(scope, boundary, observed, writer_epoch,
        writer_revision, cash, (), (), (), (), tuple(sources),
        tuple(dict.fromkeys(blockers)), report.observed_at)
    options = dict(boundary=boundary, observed_at=observed)
    # Jobs retain the original PageSet rows. Batch size never changes the raw
    # enumeration's source, query, pages, byte count, or row-count evidence.
    jobs = (
        (parse_settlements, settlements.rows, options,
         lambda row: row.key, 'settlement'),
        (parse_subaccount_transfers, subaccount_transfers.rows,
         options | dict(subaccount=scope), lambda row: row.transfer_id, 'subaccount transfer'),
        (parse_intra_exchange_transfers, intra_exchange_transfers.rows, options,
         lambda row: row.transfer_id, 'intra-exchange transfer'),
        (parse_funding, deposits.rows, options | dict(kind='deposit'),
         lambda row: (row.kind, row.record_id), 'funding observation'),
        (parse_funding, withdrawals.rows, options | dict(kind='withdrawal'),
         lambda row: (row.kind, row.record_id), 'funding observation'),
        (parse_funding_history, deposits.rows, options | dict(kind='deposit'),
         lambda row: (row.kind, row.record_id), 'funding history'),
        (parse_funding_history, withdrawals.rows, options | dict(kind='withdrawal'),
         lambda row: (row.kind, row.record_id), 'funding history'))
    return base, jobs


def _assemble_opening_evidence(base, normalized):
    (settlement_rows, scoped_transfers, shard_transfers, deposits, withdrawals,
     deposit_history, withdrawal_history) = normalized
    funding = deposits + withdrawals
    blockers = list(base.blockers)
    if scoped_transfers or shard_transfers or funding:
        blockers.append('cash_activity_requires_operator_attribution')
    if settlement_rows:
        blockers.append('settlement_history_requires_ledger_contract')
    if funding:
        blockers.append('member_funding_not_subaccount_scoped')
        if any(row.status == 'pending' or row.finalized_ts is None for row in funding):
            blockers.append('funding_completion_time_unproven')
    if shard_transfers:
        blockers.append('intra_exchange_transfer_subaccount_unproven')
        blockers.append('intra_exchange_transfer_completion_time_unproven')
    return replace(base, settlements=settlement_rows,
        subaccount_transfers=scoped_transfers, intra_exchange_transfers=shard_transfers,
        funding=funding, funding_history=deposit_history+withdrawal_history,
        blockers=tuple(dict.fromkeys(blockers)))


def build_opening_evidence(*, report, continuity, proposed_boundary, subaccount,
                           writer_epoch, writer_revision, cash_document,
                           settlements, subaccount_transfers,
                           intra_exchange_transfers, deposits, withdrawals,
                           observed_at=None):
    """Normalize complete injected/read results into non-authorizing evidence."""
    base, jobs = _prepare_opening_evidence(report=report, continuity=continuity,
        proposed_boundary=proposed_boundary, subaccount=subaccount,
        writer_epoch=writer_epoch, writer_revision=writer_revision,
        cash_document=cash_document, settlements=settlements,
        subaccount_transfers=subaccount_transfers,
        intra_exchange_transfers=intra_exchange_transfers,
        deposits=deposits, withdrawals=withdrawals, observed_at=observed_at)
    normalized = tuple(parser(rows, **options) for parser, rows, options, _, _ in jobs)
    return _assemble_opening_evidence(base, normalized)


async def build_opening_evidence_async(**kwargs):
    """Sequential 512-row worker batches; caller owns this coroutine's lifetime.

    AccountCoordinator retains and shields the whole inspection across consumer
    cancellation. Global duplicate checks and final assembly also stay off-loop.
    """
    base, jobs = _prepare_opening_evidence(**kwargs)
    normalized = []
    for parser, rows, options, key, label in jobs:
        values = []
        for start in range(0, len(rows), 512):
            values.extend(await asyncio.to_thread(parser, rows[start:start+512], **options))
        # A duplicate can straddle batches. Never use per-batch exhaustion or
        # per-batch deduplication as evidence of global source consistency.
        normalized.append(await asyncio.to_thread(_unique, values, key, label))
    return await asyncio.to_thread(_assemble_opening_evidence, base, normalized)
