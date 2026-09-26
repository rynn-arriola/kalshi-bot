"""Pure exposure admission and restart-persistent six-hour loss ratchet."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .config import BotConfig
from .ledger import Ledger
from .values import InvalidData, count, decimal, integer, price, utc


def window_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = utc(now).astimezone(ZoneInfo("America/New_York"))
    start = datetime.combine(local.date(), time(local.hour//6*6), tzinfo=local.tzinfo)
    return utc(start), utc(start + timedelta(hours=6))


# D-138: resting entry-order cap (was 30). The six-hour loss ratchet keeps its
# $5 steps and $25 stop, scaled to the same fractions of the cap (6/6 .. 2/6, 0).
MAX_RESTING_ENTRIES = 50


def entry_cap(loss: Decimal) -> int:
    loss = max(Decimal(0), decimal(loss))
    for threshold, sixths in ((25, 0), (20, 2), (15, 3), (10, 4), (5, 5)):
        if loss >= threshold:
            return MAX_RESTING_ENTRIES*sixths//6
    return MAX_RESTING_ENTRIES


@dataclass(frozen=True)
class WindowState:
    start: datetime
    end: datetime
    realized_pnl: Decimal
    cap: int
    held: bool
    observed_at: datetime


class WindowRisk:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def observe(self, now: datetime) -> WindowState:
        now = utc(now)
        start, end = window_bounds(now)
        conn = self.ledger.connection
        with self.ledger.transaction():
            clock = conn.execute("SELECT value FROM meta WHERE key='risk_clock'").fetchone()
            if clock and now.isoformat() < clock[0]:
                raise InvalidData("risk clock moved backwards")
            last_fill = conn.execute("SELECT value FROM meta WHERE key='fill_clock'").fetchone()
            if last_fill and last_fill[0] > now.isoformat():
                raise InvalidData("future fill observation; risk state is not coherent")
            pnl = self.ledger.realized_incremental(start, end)
            conn.execute("INSERT OR IGNORE INTO risk_windows(start,end,entry_cap) VALUES (?,?,?)",
                         (start.isoformat(), end.isoformat(), MAX_RESTING_ENTRIES))
            row = conn.execute("SELECT * FROM risk_windows WHERE start=?", (start.isoformat(),)).fetchone()
            cap = min(row["entry_cap"], entry_cap(-pnl))
            conn.execute("UPDATE risk_windows SET entry_cap=?,tripped=? WHERE start=?",
                         (cap, int(bool(row["tripped"]) or cap == 0), start.isoformat()))
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('risk_clock',?)", (now.isoformat(),))
            held = conn.execute("SELECT 1 FROM risk_windows WHERE tripped=1 AND released=0 LIMIT 1").fetchone() is not None
        return WindowState(start, end, pnl, 0 if held else cap, held, now)

    def release_previous(self, now: datetime, *, account_observed_at: datetime,
                         orders: int, positions: int, unknowns: int, complete: bool) -> WindowState:
        now, observed = utc(now), utc(account_observed_at)
        start, _ = window_bounds(now)
        for value in (orders, positions, unknowns):
            integer(value, 0, 1000000)
        # A strict candidate five-second freshness gate; not a live-approved SLA.
        if complete is not True or any((orders, positions, unknowns)) or not start <= observed <= now:
            raise InvalidData("fresh complete next-window flat proof required")
        if now - observed > timedelta(seconds=5) or self.ledger.unresolved_intents():
            raise InvalidData("proof stale or durable ownership unresolved")
        if self.ledger.connection.execute("SELECT 1 FROM lots LIMIT 1").fetchone():
            raise InvalidData("ledger inventory conflicts with flat proof")
        self.observe(now)
        with self.ledger.connection:
            self.ledger.connection.execute(
                "UPDATE risk_windows SET released=1 WHERE tripped=1 AND end<=?", (start.isoformat(),))
        return self.observe(now)


@dataclass(frozen=True)
class OrderExposure:
    identity: str
    ticker: str
    side: str
    price: Decimal
    remaining: Decimal
    terminal: bool = False

    def worst_loss(self) -> Decimal:
        if self.side not in {"bid", "ask"} or type(self.terminal) is not bool:
            raise InvalidData("invalid order exposure")
        p, q = price(self.price), count(self.remaining, zero=True)
        return Decimal(0) if self.terminal else q * (p if self.side == "bid" else 1-p)


def exposure_total(position_risk: dict[str, Decimal], orders: list[OrderExposure]) -> dict[str, Decimal]:
    totals = {ticker: decimal(value) for ticker, value in position_risk.items()}
    if any(value < 0 for value in totals.values()):
        raise InvalidData("negative inventory exposure")
    seen = {}
    for order in orders:
        if not order.identity or not order.ticker:
            raise InvalidData("order exposure requires identity and ticker")
        if order.identity in seen:
            if order != seen[order.identity]:
                raise InvalidData("conflicting reservation identity")
            continue
        seen[order.identity] = order
        totals[order.ticker] = totals.get(order.ticker, Decimal(0)) + order.worst_loss()
    return totals


def admit_entry(config: BotConfig, *, window: WindowState, ticker: str,
                current_position: Decimal, resting_entries: int, candidate_loss: Decimal,
                exposure: dict[str, Decimal], free_capital: Decimal,
                account_known: bool, now: datetime) -> tuple[str, ...]:
    """Candidate risk gate, not execution authorization; caller must reserve atomically."""
    failures = []
    now = utc(now)
    if not window.start <= now < window.end or not window.observed_at <= now:
        failures.append("invalid_risk_window")
    elif now-window.observed_at > timedelta(seconds=5):
        failures.append("stale_risk_window")
    integer(resting_entries, 0, 1000000)
    risk = decimal(candidate_loss)
    free = decimal(free_capital)
    if risk <= 0 or free < 0:
        raise InvalidData("invalid capital inputs")
    totals = {key: decimal(value) for key, value in exposure.items()}
    if any(value < 0 for value in totals.values()):
        raise InvalidData("negative exposure")
    if account_known is not True:
        failures.append("unknown_account")
    if decimal(current_position) != 0:
        failures.append("position_is_reduce_only")
    if window.held or resting_entries >= window.cap:
        failures.append("entry_cap")
    portfolio = config.portfolio_exposure_usd
    if portfolio is None:
        failures.append("market_capacity_undecided")
    if totals.get(ticker, Decimal(0)) + risk > config.market_exposure_usd:
        failures.append("market_exposure")
    total = sum(totals.values(), Decimal(0)) + risk
    if portfolio is not None and total > portfolio:
        failures.append("portfolio_exposure")
    if risk > free or total > config.capital_usd:
        failures.append("capital")
    return tuple(failures)
