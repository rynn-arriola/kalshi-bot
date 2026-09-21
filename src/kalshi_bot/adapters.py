"""Pure Kalshi wire normalization. Builds payloads; never sends orders."""
from dataclasses import dataclass
from decimal import Decimal

from .ledger import Fill
from .values import InvalidData, count, decimal, identity, integer, price


@dataclass(frozen=True)
class PriceBand:
    start: Decimal
    end: Decimal
    step: Decimal

    def __post_init__(self):
        for name in ("start", "end", "step"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if not 0 <= self.start < self.end <= 1 or self.step <= 0 or self.step > self.end-self.start:
            raise InvalidData("invalid market price band")


def validate_tick(value: Decimal, bands: tuple[PriceBand, ...]) -> Decimal:
    p = price(value)
    matches = [band for band in bands if band.start <= p < band.end]
    if len(matches) != 1 or (p-matches[0].start) % matches[0].step:
        raise InvalidData("price outside unique market tick grid")
    return p


def create_payload(*, ticker: str, client_id: str, outcome: str, outcome_price: Decimal,
                   quantity: Decimal, bands: tuple[PriceBand, ...], reducing: bool = False,
                   position: Decimal = Decimal(0), expiration_time: int | None = None) -> dict:
    identity(ticker)
    identity(client_id)
    if outcome not in {"yes", "no"} or type(reducing) is not bool:
        raise InvalidData("invalid order direction")
    q, p = count(quantity), price(outcome_price)
    yes = validate_tick(p if outcome == "yes" else 1-p, bands)
    side = "bid" if outcome == "yes" else "ask"
    pos = decimal(position)
    if reducing:
        if pos == 0 or q > abs(pos) or side != ("ask" if pos > 0 else "bid"):
            raise InvalidData("reducer must strictly reduce known exact inventory")
    elif q != 10 or pos != 0:
        raise InvalidData("entries require size 10 and flat inventory")
    payload = dict(ticker=ticker, client_order_id=client_id, side=side,
                   count=format(q, ".2f"), price=format(yes, "f"),
                   time_in_force="good_till_canceled", self_trade_prevention_type="taker_at_cross",
                   post_only=True, reduce_only=reducing, cancel_order_on_pause=True)
    if expiration_time is not None:
        payload["expiration_time"] = integer(expiration_time, 1, 2**63-1)
    return payload


def parse_fill(event: dict) -> Fill:
    try:
        if event["type"] != "fill":
            raise InvalidData("not a fill event")
        msg = event["msg"]
        executed_us, precision = None, 1
        if "ts" in msg:
            executed_us = integer(msg["ts"], 0, (2**63-1)//1000000)*1000000
            precision = 1000000
        if "ts_ms" in msg:
            millis = integer(msg["ts_ms"], 0, (2**63-1)//1000)*1000
            if executed_us is not None and executed_us//1000000 != millis//1000000:
                raise InvalidData("conflicting fill execution timestamps")
            executed_us, precision = millis, 1000
        # Never guess canonical direction from ambiguous legacy side/action.
        return Fill(msg["trade_id"], msg["order_id"], msg["market_ticker"], msg["book_side"],
                    count(msg["count_fp"]), price(msg["yes_price_dollars"]), decimal(msg["fee_cost"]),
                    executed_us, precision)
    except (KeyError, TypeError) as exc:
        raise InvalidData("incomplete canonical fill") from exc
