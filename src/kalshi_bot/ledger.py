"""Single-owner durable ledger. No network, credentials or order submission.

D-024: weighted-average matched P&L, immediate actual fees, durable receipt
windows. Execution timestamps are reporting evidence, never the risk clock.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sqlite3

from .values import InvalidData, count, decimal, identity, integer, price, utc


@dataclass(frozen=True)
class Fill:
    trade_id: str
    order_id: str
    ticker: str
    book_side: str
    quantity: Decimal
    yes_price: Decimal
    fee: Decimal
    executed_us: int | None = None
    execution_precision_us: int = 1

    def __post_init__(self):
        for field in ("trade_id", "order_id", "ticker"):
            identity(getattr(self, field))
        if self.book_side not in {"bid", "ask"}:
            raise InvalidData("canonical book_side required")
        object.__setattr__(self, "quantity", count(self.quantity))
        object.__setattr__(self, "yes_price", price(self.yes_price))
        object.__setattr__(self, "fee", decimal(self.fee))
        if self.fee < 0:
            raise InvalidData("negative fee requires a separately specified rebate contract")
        integer(self.execution_precision_us, 1, 1000000)
        if self.execution_precision_us not in {1, 1000, 1000000}:
            raise InvalidData("unsupported execution timestamp precision")
        if self.executed_us is not None:
            integer(self.executed_us, 0, 2**63-1)
            if self.executed_us % self.execution_precision_us:
                raise InvalidData("execution timestamp differs from declared precision")

    @property
    def key(self) -> str:
        return json.dumps([self.order_id, self.trade_id], separators=(",", ":"))

    @property
    def payload(self) -> str:
        return json.dumps([self.ticker, self.book_side, str(self.quantity.normalize()),
                           str(self.yes_price.normalize()), str(self.fee.normalize())])


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fills (
  id TEXT PRIMARY KEY, payload TEXT NOT NULL, received_at TEXT NOT NULL,
  executed_us INTEGER, execution_precision_us INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS fills_order ON fills(json_extract(id,'$[0]'));
CREATE TABLE IF NOT EXISTS pending_fills (
  id TEXT PRIMARY KEY, payload TEXT NOT NULL, owner INTEGER NOT NULL,
  scope INTEGER, exchange_index INTEGER, first_seen_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS pending_order ON pending_fills(owner,json_extract(payload,'$.order_id'));
CREATE TABLE IF NOT EXISTS order_evidence (
  order_id TEXT PRIMARY KEY, client_id TEXT NOT NULL UNIQUE,
  payload TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recovery_fills (
  id TEXT PRIMARY KEY, payload TEXT NOT NULL, executed_us INTEGER NOT NULL,
  subaccount INTEGER NOT NULL, exchange_index INTEGER NOT NULL, observed_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS recovery_scope_time ON recovery_fills(subaccount,executed_us);
CREATE TABLE IF NOT EXISTS history_enumerations (
  id TEXT PRIMARY KEY, subaccount INTEGER NOT NULL, start_us INTEGER NOT NULL,
  end_us INTEGER NOT NULL, eligible_end_us INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS history_scope_interval ON history_enumerations(subaccount,start_us,end_us);
CREATE TABLE IF NOT EXISTS private_epochs (
  id TEXT PRIMARY KEY, subaccount INTEGER NOT NULL, writer_epoch TEXT NOT NULL,
  generation INTEGER NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT,
  payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS private_epochs_scope_time ON private_epochs(subaccount,opened_at);
CREATE TABLE IF NOT EXISTS lots (
  id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, direction INTEGER NOT NULL,
  quantity TEXT NOT NULL, yes_price TEXT NOT NULL, fee TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS lots_ticker ON lots(ticker,id);
CREATE UNIQUE INDEX IF NOT EXISTS position_ticker ON lots(ticker);
CREATE TABLE IF NOT EXISTS position_clocks (
  ticker TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL, last_fill_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS closes (
  id INTEGER PRIMARY KEY, fill_id TEXT NOT NULL, ticker TEXT NOT NULL,
  quantity TEXT NOT NULL, pnl TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS closes_time ON closes(received_at);
CREATE TABLE IF NOT EXISTS realized_events (
  fill_id TEXT PRIMARY KEY, gross_pnl TEXT NOT NULL, fee TEXT NOT NULL,
  pnl TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS realized_time ON realized_events(received_at);
CREATE TABLE IF NOT EXISTS realized_totals (
  start TEXT NOT NULL, end TEXT NOT NULL, through_rowid INTEGER NOT NULL,
  pnl TEXT NOT NULL, PRIMARY KEY(start,end));
CREATE TABLE IF NOT EXISTS venue_costs (
  subaccount INTEGER NOT NULL, ticker TEXT NOT NULL, exchange_index INTEGER NOT NULL,
  quantity TEXT NOT NULL, cost TEXT NOT NULL, first_seen_at TEXT NOT NULL,
  observed_at TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(subaccount,ticker));
CREATE TABLE IF NOT EXISTS intents (
  client_id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS intents_state_market ON intents(state,json_extract(payload,'$.ticker'));
CREATE INDEX IF NOT EXISTS pending_ticker ON pending_fills(json_extract(payload,'$.ticker'));
CREATE TABLE IF NOT EXISTS mutation_attempts (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, request TEXT NOT NULL,
  phase TEXT NOT NULL, response TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS mutations_market_time ON mutation_attempts(
  coalesce(json_extract(request,'$.ticker'),json_extract(request,'$.market_ticker')),created_at);
CREATE TABLE IF NOT EXISTS risk_windows (
  start TEXT PRIMARY KEY, end TEXT NOT NULL, entry_cap INTEGER NOT NULL,
  tripped INTEGER NOT NULL DEFAULT 0, released INTEGER NOT NULL DEFAULT 0);
"""


class Ledger:
    def __init__(self, path: Path | str):
        # Caller selects a private runtime location. Never auto-opens old captures.
        self.connection = sqlite3.connect(str(path), timeout=5)
        self.connection.row_factory = sqlite3.Row
        # Check before WAL/DDL. Never convert FIFO/deferred-fee databases in place.
        tables = {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if tables:
            version = (self.connection.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
                       if "meta" in tables else None)
            if version is None or version[0] != "2":
                self.close()
                raise InvalidData("incompatible ledger accounting schema; explicit migration required")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(SCHEMA)
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO meta VALUES ('schema','2')")

    def close(self):
        self.connection.close()

    @contextmanager
    def transaction(self):
        """Compose ledger/risk changes without an inner context committing early."""
        if self.connection.in_transaction:
            # A savepoint also makes a caught inner exception safe to roll back.
            self.connection.execute("SAVEPOINT ledger_nested")
            try:
                yield
            except BaseException:
                self.connection.execute("ROLLBACK TO ledger_nested")
                raise
            finally:
                self.connection.execute("RELEASE ledger_nested")
        else:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                yield

    def record_fill(self, fill: Fill, received_at: datetime) -> bool:
        stamp = utc(received_at).isoformat()
        with self.transaction(), localcontext() as ctx:
            ctx.prec = 40
            old = self.connection.execute(
                "SELECT payload,executed_us,execution_precision_us FROM fills WHERE id=?", (fill.key,)).fetchone()
            if old:
                if old[0] != fill.payload:
                    raise InvalidData("duplicate fill identity with conflicting economics")
                if fill.executed_us is not None:
                    coarse = max(old[2], fill.execution_precision_us)
                    if old[1] is not None and old[1]//coarse != fill.executed_us//coarse:
                        raise InvalidData("duplicate fill identity with conflicting execution time")
                    if old[1] is None or fill.execution_precision_us < old[2]:
                        self.connection.execute(
                            "UPDATE fills SET executed_us=?,execution_precision_us=? WHERE id=?",
                            (fill.executed_us, fill.execution_precision_us, fill.key))
                return False
            latest = self.connection.execute("SELECT value FROM meta WHERE key='fill_clock'").fetchone()
            if latest and stamp < latest[0]:
                raise InvalidData("receipt clock moved backwards; reconcile before continuing")
            direction = 1 if fill.book_side == "bid" else -1
            remaining, basis, gross = fill.quantity, fill.yes_price, Decimal(0)
            lot = self.connection.execute("SELECT * FROM lots WHERE ticker=?", (fill.ticker,)).fetchone()
            if lot:
                qty, old_basis = Decimal(lot["quantity"]), Decimal(lot["yes_price"])
                if lot["direction"] == direction:
                    remaining += qty
                    basis = (old_basis*qty + fill.yes_price*fill.quantity) / remaining
                else:
                    matched = min(remaining, qty)
                    gross = (fill.yes_price-old_basis) * matched * lot["direction"]
                    self.connection.execute(
                        "INSERT INTO closes(fill_id,ticker,quantity,pnl,received_at) VALUES (?,?,?,?,?)",
                        (fill.key, fill.ticker, str(matched), str(gross), stamp))
                    if qty > remaining:
                        remaining, direction, basis = qty-remaining, lot["direction"], old_basis
                    else:
                        remaining -= qty  # Flat or flipped: new side uses this fill's basis.
                self.connection.execute("DELETE FROM lots WHERE id=?", (lot["id"],))
            if remaining:
                self.connection.execute(
                    "INSERT INTO lots(ticker,direction,quantity,yes_price,fee) VALUES (?,?,?,?,?)",
                    (fill.ticker, direction, str(remaining), str(basis), "0"))
                if lot is None or lot["direction"] != direction:
                    self.connection.execute("INSERT OR REPLACE INTO position_clocks VALUES (?,?,?)",
                                            (fill.ticker, stamp, stamp))
                else:
                    # Missing old clock stays unknown; do not reset a deadline
                    # merely because an older schema-2 ledger is being observed.
                    self.connection.execute("UPDATE position_clocks SET last_fill_at=? WHERE ticker=?",
                                            (stamp, fill.ticker))
            else:
                self.connection.execute("DELETE FROM position_clocks WHERE ticker=?", (fill.ticker,))
            self.connection.execute("INSERT INTO realized_events VALUES (?,?,?,?,?)",
                                    (fill.key, str(gross), str(fill.fee), str(gross-fill.fee), stamp))
            self.connection.execute("INSERT INTO fills VALUES (?,?,?,?,?)",
                                    (fill.key, fill.payload, stamp, fill.executed_us, fill.execution_precision_us))
            self.connection.execute("INSERT OR REPLACE INTO meta VALUES ('fill_clock',?)", (stamp,))
        return True

    def position(self, ticker: str) -> Decimal:
        rows = self.connection.execute("SELECT direction,quantity FROM lots WHERE ticker=?", (ticker,))
        return sum((Decimal(row[1]) * row[0] for row in rows), Decimal(0))

    def filled_quantity(self, order_id: str) -> Decimal:
        identity(order_id)
        rows = self.connection.execute("SELECT payload FROM fills WHERE json_extract(id,'$[0]')=?", (order_id,))
        return sum((Decimal(json.loads(row[0])[2]) for row in rows), Decimal(0))

    def realized(self, start: datetime, end: datetime) -> Decimal:
        rows = self.connection.execute("SELECT pnl FROM realized_events WHERE received_at>=? AND received_at<?",
                                       (utc(start).isoformat(), utc(end).isoformat()))
        with localcontext() as ctx:
            ctx.prec = 40
            return sum((Decimal(row[0]) for row in rows), Decimal(0))

    def realized_incremental(self, start: datetime, end: datetime) -> Decimal:
        """Transactional derived total for the append-only receipt journal.

        Cold windows use the time index once; warm windows read only new rowids.
        The cursor and Decimal total commit/roll back with fills and risk caps.
        Never delete, rewrite or prune journal rows without invalidating these
        totals in the same transaction. Corrections require a separate design.
        """
        first, last = utc(start).isoformat(), utc(end).isoformat()
        if first >= last:
            raise InvalidData("invalid realized window")
        with self.transaction(), localcontext() as ctx:
            ctx.prec = 40
            cached = self.connection.execute(
                "SELECT through_rowid,pnl FROM realized_totals WHERE start=? AND end=?",
                (first, last)).fetchone()
            through = self.connection.execute(
                "SELECT COALESCE(MAX(rowid),0) FROM realized_events").fetchone()[0]
            if cached is None:
                total = Decimal(0)
                rows = self.connection.execute(
                    "SELECT pnl FROM realized_events WHERE received_at>=? AND received_at<? "
                    "ORDER BY received_at,rowid", (first, last))
            else:
                if cached[0] > through:
                    raise InvalidData("receipt journal shrank; derived totals invalid")
                total = Decimal(cached[1])
                rows = self.connection.execute(
                    "SELECT pnl FROM realized_events WHERE rowid>? AND rowid<=? "
                    "AND received_at>=? AND received_at<? ORDER BY rowid",
                    (cached[0], through, first, last))
            for row in rows:
                total += Decimal(row[0])
            self.connection.execute(
                "INSERT OR REPLACE INTO realized_totals VALUES (?,?,?,?)",
                (first, last, through, str(total)))
            return total

    def reserve_intent(self, client_id: str, payload: dict, now: datetime):
        identity(client_id)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.transaction():
            if self.connection.execute("SELECT 1 FROM intents WHERE client_id=?", (client_id,)).fetchone():
                raise InvalidData("intent identity already reserved; never retry an ambiguous create")
            self.connection.execute("INSERT INTO intents VALUES (?,?,?,?)",
                                    (client_id, encoded, "RESERVED", utc(now).isoformat()))

    def transition_intent(self, client_id: str, target: str):
        allowed = {"RESERVED": {"SENDING", "ABORTED"}, "SENDING": {"UNKNOWN", "ACKNOWLEDGED", "REJECTED"},
                   "UNKNOWN": {"ACKNOWLEDGED", "REJECTED"}, "ACKNOWLEDGED": {"TERMINAL"}}
        with self.transaction():
            row = self.connection.execute("SELECT state FROM intents WHERE client_id=?", (client_id,)).fetchone()
            if row is None or target not in allowed.get(row[0], set()):
                raise InvalidData("illegal intent transition; terminal venue proof is required")
            self.connection.execute("UPDATE intents SET state=? WHERE client_id=?", (target, client_id))

    def unresolved_intents(self) -> int:
        return self.connection.execute(
            "SELECT COUNT(*) FROM intents WHERE state IN ('RESERVED','SENDING','UNKNOWN','ACKNOWLEDGED')"
        ).fetchone()[0]
