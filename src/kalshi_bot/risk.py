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


# D-138: resting entry-order cap (was 30).
MAX_RESTING_ENTRIES = 50
# D-162 (operator, 2026-09-30): "no time frame stop loss ... just a 24 hr stop
# loss of 60 max". Replaces the six-hour $25 window with $5 step-downs, whose
# tripped windows were never released (Finding 225). Entries stop while the
# realized trading loss of the last 24 hours is $60 or more and resume by
# themselves once older losses age out; exits and protection never stop.
DAILY_LOSS_LIMIT = Decimal(60)
LOSS_LOOKBACK = timedelta(hours=24)


def entry_cap(loss: Decimal) -> int:
    """Full cap below the rolling 24-hour limit, none at or above it."""
    return 0 if decimal(loss) >= DAILY_LOSS_LIMIT else MAX_RESTING_ENTRIES


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
            # D-162: rolling 24-hour realized result; the six-hour bounds remain
            # only as the proof/refresh lifetime other owners already use.
            pnl = self.ledger.realized_since(now-LOSS_LOOKBACK, now)
            cap = entry_cap(-pnl)
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('risk_clock',?)", (now.isoformat(),))
        return WindowState(start, end, pnl, cap, cap == 0, now)


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
