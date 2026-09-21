"""Venue cost for exit planning only. Never creates fills, lots or realized P&L."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from .orders import OrderUpdate
from .values import InvalidData, count, decimal, identity, integer, utc


@dataclass(frozen=True)
class VenueCost:
    ticker: str
    subaccount: int
    exchange_index: int
    quantity: Decimal
    cost: Decimal
    source: str

    def __post_init__(self):
        identity(self.ticker)
        integer(self.subaccount, 0, 63)
        integer(self.exchange_index, 0, 2**31-1)
        object.__setattr__(self, "quantity", decimal(self.quantity))
        object.__setattr__(self, "cost", decimal(self.cost))
        count(abs(self.quantity), zero=True)
        if self.cost < 0 or self.source not in {"rest", "websocket"}:
            raise InvalidData("invalid venue position cost/source")


@dataclass(frozen=True)
class ExitBasis:
    ticker: str
    quantity: Decimal
    yes_price: Decimal
    first_seen_at: datetime
    observed_at: datetime
    source: str
    exit_only: bool = True
    complete_fill_history: bool = False


def observe_cost(ledger, observation: VenueCost, now: datetime, *, capacity=128):
    observe_costs(ledger, (observation,), now, capacity=capacity)


def observe_costs(ledger, observations: tuple[VenueCost, ...], now: datetime, *, capacity=128):
    """A snapshot checks global active capacity once, within the same transaction."""
    if type(observations) is not tuple or len(observations) > capacity:
        raise InvalidData("bounded immutable venue observations required")
    with ledger.transaction():
        for observation in observations:
            _store_cost(ledger, observation, now)
        active = ledger.connection.execute("SELECT quantity FROM venue_costs").fetchall()
        if sum(Decimal(r[0]) != 0 for r in active) > capacity:
            raise InvalidData("venue positions exceed bounded owner capacity")


def _store_cost(ledger, observation: VenueCost, now: datetime):
    stamp = utc(now).isoformat()
    conn = ledger.connection
    with ledger.transaction():
        old = conn.execute("SELECT * FROM venue_costs WHERE subaccount=? AND ticker=?",
                           (observation.subaccount, observation.ticker)).fetchone()
        if old and (stamp < old["observed_at"] or old["exchange_index"] != observation.exchange_index):
            raise InvalidData("venue cost clock/shard conflicts")
        if old is None and conn.execute("SELECT COUNT(*) FROM venue_costs").fetchone()[0] >= 4096:
            raise InvalidData("venue cost retention capacity exceeded")
        first = stamp
        if old and Decimal(old["quantity"])*observation.quantity > 0:
            first = old["first_seen_at"]  # Partial reductions/additions cannot reset deadline.
        conn.execute("INSERT INTO venue_costs VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(subaccount,ticker) "
                     "DO UPDATE SET quantity=excluded.quantity,cost=excluded.cost,"
                     "first_seen_at=excluded.first_seen_at,observed_at=excluded.observed_at,source=excluded.source",
                     (observation.subaccount, observation.ticker, observation.exchange_index,
                      str(observation.quantity), str(observation.cost), first, stamp, observation.source))


def exit_basis(ledger, observation: VenueCost, now: datetime) -> ExitBasis | None:
    """Called only behind a current coordinator snapshot; prove owned quantity.

    Venue cost is not evidence of ownership. Exact cumulative quantities from
    durable owned orders must explain the fresh venue quantity independently.
    """
    now = utc(now)
    if observation.quantity == 0:
        return None
    conn = ledger.connection
    row = conn.execute("SELECT * FROM venue_costs WHERE subaccount=? AND ticker=?",
                       (observation.subaccount, observation.ticker)).fetchone()
    if row is None or (row["exchange_index"], Decimal(row["quantity"]), Decimal(row["cost"])) != (
            observation.exchange_index, observation.quantity, observation.cost):
        return None
    observed = datetime.fromisoformat(row["observed_at"])
    if not timedelta(0) <= now-observed <= timedelta(seconds=5):
        return None
    orders = conn.execute("SELECT payload FROM order_evidence WHERE json_extract(payload,'$.ticker')=? LIMIT 4097",
                          (observation.ticker,)).fetchall()
    if len(orders) > 4096:
        raise InvalidData("basis ownership evidence exceeds capacity")
    net = Decimal(0)
    for stored in orders:
        order = OrderUpdate.decode(stored[0])
        if (order.subaccount, order.exchange_index) != (observation.subaccount, observation.exchange_index):
            return None
        net += order.filled * (1 if order.side == "bid" else -1)
    if net != observation.quantity:
        return None
    ambiguous = conn.execute("SELECT 1 FROM intents WHERE state IN ('SENDING','UNKNOWN') "
                             "AND json_extract(payload,'$.ticker')=? LIMIT 1", (observation.ticker,)).fetchone()
    if ambiguous:
        return None
    lot = conn.execute("SELECT yes_price FROM lots WHERE ticker=?", (observation.ticker,)).fetchone()
    if lot is not None and ledger.position(observation.ticker) == observation.quantity:
        basis, source = Decimal(lot[0]), "local_fills"
    else:
        with localcontext() as ctx:
            ctx.prec = 40
            cost = observation.cost/abs(observation.quantity)
            if not 0 < cost < 1:
                return None
            basis = cost if observation.quantity > 0 else 1-cost
        source = "venue_cost_"+row["source"]
    return ExitBasis(observation.ticker, observation.quantity, basis,
                     datetime.fromisoformat(row["first_seen_at"]), observed, source)
