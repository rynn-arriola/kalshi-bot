"""Durable completed enumeration receipts, NEVER complete trading-history proof.

Only the serial ledger owner calls the database functions. Receipt data cannot
authorize entries, restore a private generation, or move an accounting boundary.
"""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from .orders import timestamp_us
from .values import InvalidData, identity, integer, utc


MAX_RECEIPTS = 4096


@dataclass(frozen=True)
class EnumerationReceipt:
    receipt_id: str
    subaccount: int
    start_us: int
    end_us: int
    cutoff_us: int
    read_started_us: int
    observed_us: int
    writer_epoch: str
    generation: int | None
    source_revision: int | None
    pages: int
    excluded_other_accounts: int
    row_count: int
    remembered_count: int
    digest: str

    def __post_init__(self):
        identity(self.receipt_id)
        identity(self.writer_epoch)
        integer(self.subaccount, 0, 63)
        integer(self.start_us, 0, 2**63-1)
        integer(self.end_us, self.start_us+1, 2**63-1)
        for stamp in (self.cutoff_us, self.read_started_us, self.observed_us):
            integer(stamp, 0, 2**63-1)
        if self.observed_us < self.read_started_us:
            raise InvalidData('history observation clock regressed')
        if (self.generation is None) != (self.source_revision is None):
            raise InvalidData('partial history source provenance')
        if self.generation is not None:
            integer(self.generation, 1, 2**63-1)
            integer(self.source_revision, 0, 2**63-1)
        integer(self.pages, 1, 200)
        integer(self.excluded_other_accounts, 0, 10000)
        integer(self.row_count, 0, 10000)
        integer(self.remembered_count, self.row_count, 10000)
        if (type(self.digest) is not str or len(self.digest) != 64
                or any(c not in '0123456789abcdef' for c in self.digest)):
            raise InvalidData('invalid history digest')

    @property
    def omitted_rows(self):
        return self.remembered_count - self.row_count

    @property
    def eligible_end_us(self):
        # Even an exhausted request extending into the future cannot enumerate it.
        return max(self.start_us, min(self.end_us, self.read_started_us))


@dataclass(frozen=True)
class EnumerationCoverage:
    subaccount: int
    start_us: int
    end_us: int
    intervals: tuple[tuple[int, int], ...]
    gaps: tuple[tuple[int, int], ...]
    receipt_ids: tuple[str, ...]
    omission_receipts: int
    latest_observed_us: int | None

    @property
    def blockers(self):
        blockers = ['history_enumeration_not_atomic_proof', 'launch_boundary_not_established',
                    'private_stream_continuity_not_proven', 'starting_basis_not_proven',
                    'settlement_and_correction_reconciliation_not_complete']
        if self.gaps:
            blockers.append('history_enumeration_gaps')
        if self.omission_receipts:
            blockers.append('previously_observed_fills_omitted')
        return tuple(blockers)

    @property
    def ready_for_entry(self):
        return False


def complete_enumeration(ledger, evidence, *, receipt_id, writer_epoch, read_started_at,
                         observed_at, generation=None, source_revision=None):
    """Commit after all staging ACKs; revalidate rows in the owner transaction.

    No trading writes, ownership classification, pruning or implicit adoption.
    A receipt describes enumeration even if accounting/import later fails.
    """
    from .recovery import HistoryEvidence
    if not isinstance(evidence, HistoryEvidence):
        raise InvalidData('validated bounded history evidence required')
    digest = sha256(b'kalshi-history-v1\0')
    with ledger.transaction():
        # One indexed range read instead of one SQLite call per returned fill.
        # Retained staging is capped globally at 10,000; detect corruption/overflow.
        rows = ledger.connection.execute(
            'SELECT id,payload,executed_us,subaccount,exchange_index FROM recovery_fills '
            'WHERE subaccount=? AND executed_us>=? AND executed_us<? LIMIT 10001',
            (evidence.subaccount, evidence.start_us, evidence.end_us)).fetchall()
        if len(rows) > 10000:
            raise InvalidData('history staging exceeds inspection bound')
        staged = {row[0]: tuple(row)[1:] for row in rows}
        for key, record in sorted((r.fill.key, r) for r in evidence.records):
            fill = record.fill
            expected = (fill.payload, record.executed_us, record.subaccount, record.exchange_index)
            if staged.get(key) != expected:
                raise InvalidData('cannot complete unstaged or conflicting history')
            key_bytes, payload_bytes = key.encode('utf-8'), expected[0].encode('utf-8')
            encoded = (len(key_bytes).to_bytes(4, 'big') + key_bytes
                + len(payload_bytes).to_bytes(4, 'big') + payload_bytes
                + record.executed_us.to_bytes(8, 'big') + record.subaccount.to_bytes(1, 'big')
                + record.exchange_index.to_bytes(4, 'big'))
            digest.update(encoded)
        remembered = len(staged)
        receipt = EnumerationReceipt(receipt_id, evidence.subaccount, evidence.start_us, evidence.end_us,
            evidence.cutoff_us, timestamp_us(utc(read_started_at).isoformat()),
            timestamp_us(utc(observed_at).isoformat()), writer_epoch, generation, source_revision,
            evidence.pages, evidence.excluded_other_accounts, len(evidence.records), remembered, digest.hexdigest())
        encoded = json.dumps(asdict(receipt), sort_keys=True, separators=(',', ':'))
        old = ledger.connection.execute('SELECT payload FROM history_enumerations WHERE id=?',
                                        (receipt_id,)).fetchone()
        if old is not None:
            if old[0] != encoded:
                raise InvalidData('immutable enumeration receipt conflict')
            return receipt
        if ledger.connection.execute('SELECT COUNT(*) FROM history_enumerations').fetchone()[0] >= MAX_RECEIPTS:
            raise InvalidData('history receipt capacity reached; explicit archival required')
        ledger.connection.execute('INSERT INTO history_enumerations VALUES (?,?,?,?,?,?)',
            (receipt_id, evidence.subaccount, evidence.start_us, evidence.end_us, receipt.eligible_end_us, encoded))
    return receipt


def enumeration_coverage(ledger, *, subaccount, start_us, end_us):
    """Bounded historical inspection. Interval union is NOT a venue watermark."""
    integer(subaccount, 0, 63)
    integer(start_us, 0, 2**63-1)
    integer(end_us, start_us+1, 2**63-1)
    rows = ledger.connection.execute(
        'SELECT * FROM history_enumerations WHERE subaccount=? AND start_us<? AND end_us>? '
        'ORDER BY start_us,end_us,id LIMIT ?', (subaccount, end_us, start_us, MAX_RECEIPTS+1)).fetchall()
    if len(rows) > MAX_RECEIPTS:
        raise InvalidData('history inspection exceeds receipt capacity')
    spans, receipts, omissions, latest = [], [], 0, None
    for row in rows:
        receipt = EnumerationReceipt(**json.loads(row['payload']))
        if (receipt.receipt_id, receipt.subaccount, receipt.start_us, receipt.end_us, receipt.eligible_end_us) != (
                row['id'], row['subaccount'], row['start_us'], row['end_us'], row['eligible_end_us']):
            raise InvalidData('history receipt index conflicts with immutable data')
        receipts.append(receipt.receipt_id)
        latest = receipt.observed_us if latest is None else max(latest, receipt.observed_us)
        omissions += int(receipt.omitted_rows > 0)
        left, right = max(start_us, receipt.start_us), min(end_us, receipt.eligible_end_us)
        if not receipt.omitted_rows and left < right:
            if spans and left <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(spans[-1][1], right))
            else:
                spans.append((left, right))
    gaps, cursor = [], start_us
    for left, right in spans:
        if cursor < left:
            gaps.append((cursor, left))
        cursor = right
    if cursor < end_us:
        gaps.append((cursor, end_us))
    return EnumerationCoverage(subaccount, start_us, end_us, tuple(spans), tuple(gaps),
                               tuple(receipts), omissions, latest)
