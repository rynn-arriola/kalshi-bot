"""Bounded durable evidence inbox. Receipt here is NOT realized accounting."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json

from .ledger import Fill
from .values import InvalidData, identity, integer, utc


@dataclass(frozen=True)
class PendingFill:
    fill: Fill
    owner: int
    scope: int | None
    exchange_index: int | None
    first_seen_at: datetime


def stage(ledger, fill, owner, scope, exchange_index, now):
    if not isinstance(fill, Fill):
        raise InvalidData("validated inbox fill required")
    integer(owner, 0, 63)
    if scope is not None and integer(scope, 0, 63) != owner:
        raise InvalidData("pending fill belongs to another account")
    if exchange_index is not None:
        integer(exchange_index, 0, 2**31-1)
    stamp = utc(now).isoformat()
    with ledger.transaction():
        old = ledger.connection.execute("SELECT * FROM pending_fills WHERE id=?", (fill.key,)).fetchone()
        if old:
            prior = Fill(**json.loads(old["payload"]))
            if (old["owner"] != owner or prior.payload != fill.payload
                    or (old["scope"] is not None and scope is not None and old["scope"] != scope)
                    or (old["exchange_index"] is not None and exchange_index is not None
                        and old["exchange_index"] != exchange_index)):
                raise InvalidData("pending fill identity/scope conflicts")
            coarse = max(prior.execution_precision_us, fill.execution_precision_us)
            if (prior.executed_us is not None and fill.executed_us is not None
                    and prior.executed_us//coarse != fill.executed_us//coarse):
                raise InvalidData("pending execution time conflicts")
            if prior.executed_us is not None and (fill.executed_us is None
                    or prior.execution_precision_us < fill.execution_precision_us):
                fill = replace(fill, executed_us=prior.executed_us,
                               execution_precision_us=prior.execution_precision_us)
            scope = old["scope"] if scope is None else scope
            exchange_index = old["exchange_index"] if exchange_index is None else exchange_index
            stamp = old["first_seen_at"]
        elif ledger.connection.execute("SELECT COUNT(*) FROM pending_fills").fetchone()[0] >= 256:
            raise InvalidData("pending fill inbox full; recovery required")
        encoded = json.dumps(asdict(fill), default=str, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > 4096:
            raise InvalidData("pending fill byte budget exceeded")
        ledger.connection.execute("INSERT INTO pending_fills VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,scope=excluded.scope,"
            "exchange_index=excluded.exchange_index", (fill.key, encoded, owner, scope, exchange_index, stamp))
    return fill.key


def pending(ledger, owner, order_id=None):
    integer(owner, 0, 63)
    clause = "" if order_id is None else " AND json_extract(payload,'$.order_id')=?"
    params = (owner,) if order_id is None else (owner, identity(order_id))
    rows = ledger.connection.execute("SELECT * FROM pending_fills WHERE owner=?"+clause+
                                     " ORDER BY rowid LIMIT 257", params).fetchall()
    if len(rows) > 256:
        raise InvalidData("pending inbox exceeds capacity")
    return tuple(PendingFill(Fill(**json.loads(r["payload"])), r["owner"], r["scope"],
                            r["exchange_index"], datetime.fromisoformat(r["first_seen_at"])) for r in rows)
