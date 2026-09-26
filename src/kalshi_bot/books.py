"""Bounded incremental books, explicit YES-price convention, connection epochs."""
from bisect import bisect_left, insort
from dataclasses import dataclass, field
from decimal import Decimal

from .values import InvalidData, count, decimal, identity, integer, price


class ProofLost(InvalidData):
    pass


class Ladder:
    def __init__(self, capacity: int):
        self.capacity = integer(capacity, 1, 10000)
        self.levels: dict[Decimal, Decimal] = {}
        self.prices: list[Decimal] = []
        # D-145: cumulative size removed per price by other participants since
        # this ladder's snapshot (trades or cancels; never netted by joins).
        self.decreased: dict[Decimal, Decimal] = {}

    def record_decrease(self, p: Decimal, q: Decimal):
        if q > 0:
            self.decreased[p] = self.decreased.get(p, Decimal(0))+q

    def set(self, p: Decimal, q: Decimal):
        p, q = price(p), count(q, zero=True)
        self._set_validated(p, q)

    def _set_validated(self, p: Decimal, q: Decimal):
        """Internal only: callers must already have validated both exact values."""
        existed = p in self.levels
        if q == 0:
            if existed:
                del self.levels[p]
                self.prices.pop(bisect_left(self.prices, p))
            return
        if not existed:
            if len(self.levels) >= self.capacity:
                raise ProofLost("book level capacity exceeded")
            insort(self.prices, p)
        self.levels[p] = q

    def best(self, *, bid: bool) -> Decimal | None:
        return (self.prices[-1] if bid else self.prices[0]) if self.prices else None


@dataclass
class Book:
    ticker: str
    bids: Ladder
    asks: Ladder
    valid: bool = False
    revision: int = 0
    # D-145: identity of one sequence-continuous history of this market's book.
    # A refresh snapshot inside the same proven sequence keeps it (and the
    # removal tallies); a new connection or first snapshot starts a new one.
    lineage: object = field(default_factory=object)


class BookConnection:
    """Sequence scope is subscription-wide, NOT independently per market.

    Any detected discontinuity invalidates this connection's entire proof.
    Recovery currently requires a new connection epoch and fresh snapshots.
    """
    def __init__(self, tickers: tuple[str, ...], *, max_levels: int = 4096):
        if not tickers or len(set(tickers)) != len(tickers) or len(tickers) > 1024:
            raise InvalidData("invalid bounded market scope")
        for ticker in tickers:
            identity(ticker)
        self.tickers = frozenset(tickers)
        self.max_levels = integer(max_levels, 1, 10000)
        self.generation = 0
        self.sequences: dict[int, int] = {}
        self.books: dict[str, Book] = {}
        self.owners: dict[str, int] = {}
        self.failed = True

    def reconnect(self) -> int:
        self.generation += 1
        self.sequences.clear()
        self.books.clear()
        self.owners.clear()
        self.failed = False
        return self.generation

    def invalidate(self):
        self.failed = True
        for book in self.books.values():
            book.valid = False

    def apply(self, event: dict, *, generation: int) -> str | None:
        if generation != self.generation:
            return None  # An old connection never overwrites the new generation.
        if self.failed:
            raise ProofLost("connection requires resynchronization")
        try:
            kind = event.get("type")
            if kind == "error":
                raise ProofLost("subscription error")
            if "seq" in event:
                sid = integer(event.get("sid"), 1, 2**63-1)
                seq = integer(event["seq"], 0, 2**63-1)
                prior = self.sequences.get(sid)
                if prior is not None and seq != prior + 1:
                    raise ProofLost("subscription sequence gap or replay")
                if prior is None and kind != "orderbook_snapshot":
                    raise ProofLost("sequence begins without a snapshot")
                if sid not in self.sequences and len(self.sequences) >= len(self.tickers):
                    raise ProofLost("subscription capacity exceeded")
                self.sequences[sid] = seq
            if kind not in {"orderbook_snapshot", "orderbook_delta"}:
                return None
            if "seq" not in event:
                raise ProofLost("book event missing sequence")
            msg = event["msg"]
            ticker = identity(msg["market_ticker"])
            if ticker not in self.tickers:
                raise ProofLost("book event outside subscribed scope")
            if ticker in self.owners and self.owners[ticker] != sid:
                raise ProofLost("market changed subscription without a new generation")
            self.owners[ticker] = sid
            if kind == "orderbook_snapshot":
                book = Book(ticker, Ladder(self.max_levels), Ladder(self.max_levels))
                for key, ladder in (("yes_dollars_fp", book.bids), ("no_dollars_fp", book.asks)):
                    rows = msg.get(key, [])
                    if not isinstance(rows, list) or len(rows) > self.max_levels:
                        raise ProofLost("invalid snapshot ladder")
                    for row in rows:
                        if not isinstance(row, list) or len(row) != 2:
                            raise ProofLost("invalid snapshot level")
                        p, q = price(row[0]), count(row[1])
                        if p in ladder.levels:
                            raise ProofLost("duplicate snapshot price")
                        ladder._set_validated(p, q)
                book.valid = True
                old = self.books.get(ticker)
                if old is not None and old.valid:
                    # Same connection and sequence (any gap raised above), so
                    # every delta since the last snapshot was counted.
                    book.lineage = old.lineage
                    book.bids.decreased, book.asks.decreased = old.bids.decreased, old.asks.decreased
                self.books[ticker] = book
            else:
                book = self.books.get(ticker)
                if book is None or not book.valid:
                    raise ProofLost("delta before market snapshot")
                side = msg["side"]
                if side not in {"yes", "no"}:
                    raise ProofLost("unknown book side")
                ladder = book.bids if side == "yes" else book.asks
                p, change = price(msg["price_dollars"]), decimal(msg["delta_fp"])
                if change % Decimal("0.01"):
                    raise ProofLost("delta quantity off grid")
                ladder.set(p, ladder.levels.get(p, Decimal(0)) + change)
                if change < 0 and not msg.get("client_order_id"):
                    # Deltas we caused carry our client id; they never move us.
                    ladder.record_decrease(p, -change)
            bid, ask = book.bids.best(bid=True), book.asks.best(bid=False)
            book.revision = seq
            if bid is not None and ask is not None and bid >= ask:
                raise ProofLost("crossed/locked book: no safe quote proof")
            return ticker
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            self.invalidate()
            raise ProofLost("book proof invalid; reconnect and resnapshot") from exc
