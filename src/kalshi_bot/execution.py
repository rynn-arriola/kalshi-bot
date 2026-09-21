"""Durable offline-injected command lifecycle. NO authenticated write transport.

This is an engineering harness, not a live executor or an atomic risk admission
service. Production activation needs the integrated reservation/recovery contract.
Create/cancel acknowledgements never synthesize fills or terminal order proof.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json

from .values import InvalidData, count, identity, integer, price, utc
from .observability import NO_LOG


def validate_request(kind, request):
    if kind not in {"create", "cancel"} or not isinstance(request, dict):
        raise InvalidData("invalid command request")
    integer(request["subaccount"], 0, 63)
    integer(request["exchange_index"], 0, 2**31-1)
    if kind == "cancel":
        if set(request) != {"order_id", "subaccount", "exchange_index", "market_ticker"}:
            raise InvalidData("cancel requires exact ownership/routing scope")
        identity(request["order_id"])
        identity(request["market_ticker"])
        return
    required = {"ticker", "client_order_id", "side", "count", "price", "time_in_force",
                "self_trade_prevention_type", "post_only", "reduce_only", "cancel_order_on_pause",
                "subaccount", "exchange_index"}
    if not required <= set(request) or set(request)-required-{"expiration_time"}:
        raise InvalidData("unsupported create fields")
    identity(request["ticker"])
    identity(request["client_order_id"])
    q = count(request["count"])
    price(request["price"])
    passive = request["time_in_force"] == "good_till_canceled" and request["post_only"] is True
    ioc = (request["time_in_force"] == "immediate_or_cancel" and request["post_only"] is False
           and request["reduce_only"] is True and "expiration_time" not in request)
    if (request["side"] not in {"bid", "ask"} or not (passive or ioc)
            or request["cancel_order_on_pause"] is not True
            or type(request["reduce_only"]) is not bool
            or request["self_trade_prevention_type"] != "taker_at_cross"):
        raise InvalidData("only passive or exact reduce-only IOC mechanics supported")
    if not request["reduce_only"] and q != 10:
        raise InvalidData("entry quantity must be ten")
    if "expiration_time" in request:
        integer(request["expiration_time"], 1, 2**63-1)


def acknowledgement(kind, request, response):
    """Validate the V2 *flat* response without pretending it is a full Order."""
    if not isinstance(response, dict):
        raise InvalidData("invalid mutation response")
    try:
        result = {"order_id": identity(response["order_id"]),
                  "ts_ms": integer(response["ts_ms"], 0, (2**63-1)//1000)}
        client = response.get("client_order_id")
        if client is not None:
            result["client_order_id"] = identity(client)
        if kind == "create":
            if client is not None and client != request["client_order_id"]:
                raise InvalidData("create acknowledgement client mismatch")
            filled, remaining = count(response["fill_count"], zero=True), count(response["remaining_count"], zero=True)
            if filled+remaining > count(request["count"]):
                raise InvalidData("create acknowledgement quantity mismatch")
            result.update(fill_count=str(filled), remaining_count=str(remaining))
        else:
            if result["order_id"] != request["order_id"]:
                raise InvalidData("cancel acknowledgement order mismatch")
            result["reduced_by"] = str(count(response["reduced_by"], zero=True))
        return result
    except (KeyError, TypeError) as exc:
        raise InvalidData("incomplete V2 acknowledgement") from exc


def journal_mutation(ledger, operation, attempt_id, encoded, now):
    doc = json.loads(encoded)
    with ledger.transaction():
        row = ledger.connection.execute("SELECT * FROM mutation_attempts WHERE id=?", (attempt_id,)).fetchone()
        if operation.startswith("prepare_"):
            if row is not None:
                raise InvalidData("attempt already exists; never retry an ambiguous mutation")
            if ledger.connection.execute("SELECT COUNT(*) FROM mutation_attempts").fetchone()[0] >= 4096:
                raise InvalidData("mutation evidence capacity reached")
            kind = operation.removeprefix("prepare_")
            validate_request(kind, doc)
            if kind == "create":
                ledger.reserve_intent(doc["client_order_id"], doc, now)
            else:
                from .orders import settle_order
                receipt = settle_order(ledger, doc["order_id"])
                if (receipt is None or not receipt.owned or receipt.order.terminal or
                        (receipt.order.ticker, receipt.order.subaccount, receipt.order.exchange_index) !=
                        (doc["market_ticker"], doc["subaccount"], doc["exchange_index"])):
                    raise InvalidData("cancel target lacks durable working ownership proof")
                previous = ledger.connection.execute(
                    "SELECT 1 FROM mutation_attempts WHERE kind='cancel' AND json_extract(request,'$.order_id')=? LIMIT 1",
                    (doc["order_id"],)).fetchone()
                if previous:
                    raise InvalidData("cancel already attempted; recovery required before another attempt")
            ledger.connection.execute("INSERT INTO mutation_attempts VALUES (?,?,?,'PREPARED',NULL,?)",
                                      (attempt_id, kind, encoded, utc(now).isoformat()))
            return
        if row is None:
            raise InvalidData("mutation lacks durable preparation")
        request = json.loads(row["request"])
        if operation == "sending" and row["phase"] == "PREPARED":
            phase, response = "SENDING", None
            if row["kind"] == "create":
                ledger.transition_intent(request["client_order_id"], "SENDING")
        elif operation in {"unknown", "ack"} and row["phase"] == "SENDING":
            phase = "UNKNOWN" if operation == "unknown" else "ACK"
            response = None if operation == "unknown" else json.dumps(acknowledgement(row["kind"], request, doc), sort_keys=True)
            if row["kind"] == "create":
                # Full order evidence may already have arrived over the stream.
                state = ledger.connection.execute("SELECT state FROM intents WHERE client_id=?",
                                                   (request["client_order_id"],)).fetchone()[0]
                if state == "SENDING":
                    ledger.transition_intent(request["client_order_id"], "UNKNOWN")
        else:
            raise InvalidData("invalid mutation journal transition")
        ledger.connection.execute("UPDATE mutation_attempts SET phase=?,response=? WHERE id=?",
                                  (phase, response, attempt_id))


@dataclass(frozen=True)
class AttemptResult:
    attempt_id: str
    phase: str
    order_id: str | None
    reconciliation_required: bool = True


class InjectedExecutor:
    def __init__(self, writer, *, invoke, validate_proof, offline_fixture: bool,
                 now=lambda: datetime.now(timezone.utc), timeout=10, diagnostics=NO_LOG):
        self.diagnostics = diagnostics
        if offline_fixture is not True:
            raise InvalidData("live order transport is unavailable")
        if not 0 < timeout <= 30:
            raise InvalidData("bounded mutation timeout required")
        self.writer, self.invoke, self.validate_proof, self.now = writer, invoke, validate_proof, now
        self.timeout = timeout
        self.lock = asyncio.Lock()
        self.failed = False

    async def attempt(self, kind, attempt_id, request):
        self.diagnostics.ensure_healthy()
        # Reject rather than build an unbounded queue of competing mutation tasks.
        if self.lock.locked() or self.failed:
            raise InvalidData("mutation owner busy or requires recovery")
        identity(attempt_id)
        frozen = json.loads(json.dumps(request, allow_nan=False))
        validate_request(kind, frozen)
        async with self.lock:
            if self.validate_proof(kind, frozen) is not True:
                raise InvalidData("risk/account/book proof is not current")
            try:
                await self.writer.mutation("prepare_"+kind, attempt_id, frozen, self.now())
                self.diagnostics.emit('mutation_prepared', operation=attempt_id, market=frozen.get('ticker'))
                # The gate must recheck generation, risk and exposure after every
                # durability await. No production gate is provided in this build.
                if self.validate_proof(kind, frozen) is not True:
                    raise InvalidData("proof changed while preparing intent")
                await self.writer.mutation("sending", attempt_id, {}, self.now())
                self.diagnostics.emit('mutation_sending', operation=attempt_id)
                self.diagnostics.ensure_healthy()
                if self.validate_proof(kind, frozen) is not True:
                    raise InvalidData("proof changed before submission")
                try:
                    async with asyncio.timeout(self.timeout):
                        reply = await self.invoke(kind, dict(frozen))
                    ack = acknowledgement(kind, frozen, reply)
                except BaseException as exc:
                    self.diagnostics.emit('mutation_unknown', error=exc, operation=attempt_id)
                    await self.writer.mutation("unknown", attempt_id, {}, self.now())
                    raise
                await self.writer.mutation("ack", attempt_id, ack, self.now())
                self.diagnostics.emit('mutation_ack', operation=attempt_id, order=ack['order_id'])
                return AttemptResult(attempt_id, "ACK", ack["order_id"])
            except BaseException as exc:
                self.diagnostics.emit('mutation_failed', error=exc, operation=attempt_id)
                self.failed = True
                raise
