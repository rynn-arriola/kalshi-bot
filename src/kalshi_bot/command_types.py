"""Immutable local command handoff records. They never grant live authority."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json

from .values import InvalidData, decimal, identity, integer, utc


class MutationHTTPFailure(InvalidData):
    """Bounded mutation failure; never retains a raw venue response."""
    def __init__(self, status, error_code=None):
        self._status = integer(status, 300, 599)
        if error_code is not None:
            identity(error_code)
            if (len(error_code) > 100 or not error_code.isascii()
                    or any(not (character.isalnum() or character in '._-')
                           for character in error_code)):
                raise InvalidData('invalid mutation error code')
        self._error_code = error_code
        super().__init__('mutation_http_failure')

    @property
    def status(self):
        return self._status

    @property
    def error_code(self):
        return self._error_code


@dataclass(frozen=True)
class CapacityStatus:
    mutation_used: int
    mutation_held: int
    intent_used: int
    intent_held: int
    order_used: int
    order_held: int

    def __post_init__(self):
        for value in (self.mutation_used, self.mutation_held, self.intent_used,
                      self.intent_held, self.order_used, self.order_held):
            integer(value, 0, 2**31-1)


@dataclass(frozen=True)
class PreparedMutation:
    ledger_id: str
    writer_epoch: str
    writer_revision: int
    attempt_id: str
    authorization_id: str
    kind: str
    subject_id: str
    episode_id: str
    request_json: str
    proof_json: str
    prepared_at: datetime

    def __post_init__(self):
        for value in (self.ledger_id, self.writer_epoch, self.attempt_id,
                      self.authorization_id,
                      self.subject_id, self.episode_id):
            identity(value)
        integer(self.writer_revision, 0, 2**63-1)
        if self.kind not in {'create', 'cancel'}:
            raise InvalidData('invalid prepared mutation kind')
        if not isinstance(self.request_json, str) or len(self.request_json.encode()) > 16384:
            raise InvalidData('invalid prepared mutation request')
        try:
            value = json.loads(self.request_json)
            proof = json.loads(self.proof_json)
        except (TypeError, ValueError) as exc:
            raise InvalidData('invalid prepared mutation request') from exc
        if (not isinstance(value, dict) or not isinstance(proof, dict)
                or len(self.proof_json.encode()) > 16384):
            raise InvalidData('prepared mutation request must be an object')
        object.__setattr__(self, 'prepared_at', utc(self.prepared_at))

    @property
    def request(self):
        return json.loads(self.request_json)


@dataclass(frozen=True)
class PreparedBatch:
    """One atomic local preparation for an exact two-sided entry pair."""
    batch_id: str
    receipts: tuple[PreparedMutation, PreparedMutation]

    def __post_init__(self):
        identity(self.batch_id)
        if (type(self.receipts) is not tuple or len(self.receipts) != 2
                or any(not isinstance(row, PreparedMutation) for row in self.receipts)):
            raise InvalidData('entry batch requires two prepared mutations')
        requests = tuple(row.request for row in self.receipts)
        if (len({row.ledger_id for row in self.receipts}) != 1
                or len({row.writer_epoch for row in self.receipts}) != 1
                or len({row.writer_revision for row in self.receipts}) != 1
                or len({row.episode_id for row in self.receipts}) != 1
                or len({row.attempt_id for row in self.receipts}) != 2
                or len({row.subject_id for row in self.receipts}) != 2
                or any(row.kind != 'create' for row in self.receipts)
                or len({r['ticker'] for r in requests}) != 1
                or len({r['subaccount'] for r in requests}) != 1
                or len({r['exchange_index'] for r in requests}) != 1
                or {r['side'] for r in requests} != {'bid', 'ask'}
                or any(r['reduce_only'] is not False for r in requests)):
            raise InvalidData('prepared entry batch scope conflicts')

    @property
    def requests(self):
        return tuple(row.request for row in self.receipts)

    @property
    def writer_revision(self):
        return self.receipts[0].writer_revision


@dataclass(frozen=True)
class PairPreparationResult:
    batch: PreparedBatch | None
    blockers: tuple[str, ...]
    capacity: CapacityStatus
    batch_id: str
    live_authorized: bool = False

    @property
    def reserved(self):
        return self.batch is not None and not self.blockers


@dataclass(frozen=True)
class PreparationResult:
    receipt: PreparedMutation | None
    blockers: tuple[str, ...]
    capacity: CapacityStatus
    client_id: str
    live_authorized: bool = False

    @property
    def reserved(self):
        return self.receipt is not None and not self.blockers


@dataclass(frozen=True)
class SendResult:
    dispatch_allowed: bool
    blockers: tuple[str, ...]
    writer_revision: int

    def __post_init__(self):
        if type(self.dispatch_allowed) is not bool or type(self.blockers) is not tuple:
            raise InvalidData('invalid send result')
        integer(self.writer_revision, 0, 2**63-1)


@dataclass(frozen=True)
class CancelEvidence:
    writer_epoch: str
    writer_revision: int
    order_id: str
    ticker: str
    subaccount: int
    exchange_index: int

    def __post_init__(self):
        for value in (self.writer_epoch, self.order_id, self.ticker):
            identity(value)
        integer(self.writer_revision, 0, 2**63-1)
        integer(self.subaccount, 0, 63)
        integer(self.exchange_index, 0, 2**31-1)


@dataclass(frozen=True)
class ReductionEvidence:
    writer_epoch: str
    writer_revision: int
    episode_id: str
    ticker: str
    subaccount: int
    exchange_index: int
    position: Decimal
    request_json: str
    decision_json: str

    def __post_init__(self):
        for value in (self.writer_epoch, self.episode_id, self.ticker):
            identity(value)
        integer(self.writer_revision, 0, 2**63-1)
        integer(self.subaccount, 0, 63)
        integer(self.exchange_index, 0, 2**31-1)
        position = decimal(self.position)
        if not position:
            raise InvalidData('reduction evidence requires inventory')
        object.__setattr__(self, 'position', position)
        if not isinstance(self.request_json, str) or len(self.request_json.encode()) > 16384:
            raise InvalidData('invalid reduction evidence request')
        try:
            request = json.loads(self.request_json)
            decision = json.loads(self.decision_json)
        except (TypeError, ValueError) as exc:
            raise InvalidData('invalid reduction evidence request') from exc
        if (not isinstance(request, dict) or not isinstance(decision, dict)
                or len(self.decision_json.encode()) > 16384):
            raise InvalidData('reduction evidence request must be an object')


class CommandDenied(InvalidData):
    def __init__(self, blockers):
        self.blockers = tuple(blockers)
        super().__init__('command denied: '+','.join(self.blockers))
