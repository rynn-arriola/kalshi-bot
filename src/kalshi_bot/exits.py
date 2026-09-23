"""Exact, bounded advisory exits. No venue I/O or execution authorization."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .adapters import PriceBand, create_payload, validate_tick
from .orders import InventoryPlan, inventory_plan
from .values import InvalidData, count, decimal, identity, integer, price, utc


@dataclass(frozen=True)
class ExitTerms:
    ticker: str
    bands: tuple[PriceBand, ...]
    observed_at: datetime
    valid_until: datetime
    close_at: datetime
    # Must be supplied by a verified event-rule producer; never inferred from expiry.
    event_risk_at: datetime | None = None
    flatten_at: datetime | None = None  # explicit maintenance/HARD deadline
    taker_fee_per_contract_bound: Decimal | None = None
    active: bool = True

    def __post_init__(self):
        identity(self.ticker)
        if type(self.active) is not bool or type(self.bands) is not tuple or not 1 <= len(self.bands) <= 64:
            raise InvalidData("bounded immutable exit terms required")
        for band in self.bands:
            if not isinstance(band, PriceBand): raise InvalidData("invalid exit tick band")
        if any(a.end != b.start for a, b in zip(self.bands, self.bands[1:])):
            raise InvalidData("exit bands must be ordered and contiguous")
        for field in ("observed_at", "valid_until", "close_at", "event_risk_at", "flatten_at"):
            value = getattr(self, field)
            if value is not None: object.__setattr__(self, field, utc(value))
        if not timedelta(0) < self.valid_until-self.observed_at <= timedelta(hours=1):
            raise InvalidData("invalid bounded exit terms lifetime")
        if self.taker_fee_per_contract_bound is not None:
            fee = decimal(self.taker_fee_per_contract_bound)
            if fee < 0: raise InvalidData("negative fee bound")
            object.__setattr__(self, "taker_fee_per_contract_bound", fee)

    @property
    def deadline(self):
        candidates = [self.close_at]
        if self.event_risk_at is not None: candidates.append(self.event_risk_at-timedelta(minutes=5))
        if self.flatten_at is not None: candidates.append(self.flatten_at)
        return min(candidates)


@dataclass(frozen=True)
class ExitJournal:
    attempts: int = 0
    started_at: datetime | None = None
    unresolved_ioc: bool = False
    cancel_ids: tuple[str, ...] = ()
    cancel_started_at: datetime | None = None

    def __post_init__(self):
        integer(self.attempts, 0, 4096)
        if type(self.unresolved_ioc) is not bool or type(self.cancel_ids) is not tuple or len(self.cancel_ids) > 4096:
            raise InvalidData("invalid bounded exit journal")
        for key in self.cancel_ids: identity(key)
        for field in ('started_at', 'cancel_started_at'):
            value=getattr(self, field)
            if value is not None: object.__setattr__(self, field, utc(value))


@dataclass(frozen=True)
class ExitPlan:
    passive: InventoryPlan
    mode: str
    limit_price: Decimal | None = None
    quantity: Decimal = Decimal(0)
    projected_pnl: Decimal | None = None
    blockers: tuple[str, ...] = ()
    next_at: datetime | None = None
    authorized: bool = False

    @property
    def passive_allowed(self):
        return ((self.mode == 'passive' and not self.blockers)
                or (self.mode == 'passive_deferred'
                    and self.blockers == ('ordinary_exit_depth_or_loss',)))


def adjacent_tick(touch, side, bands):
    """One valid grid level toward the other side, including band boundaries."""
    touch = validate_tick(touch, bands)
    candidates = []
    for band in bands:
        ratio = (touch-band.start)/band.step
        index = (ratio.to_integral_value(rounding=ROUND_FLOOR)+1 if side == "bid"
                 else ratio.to_integral_value(rounding=ROUND_CEILING)-1)
        if side == "bid": index = max(Decimal(0), index)
        else: index = min(index, ((band.end-band.start)/band.step).to_integral_value(rounding=ROUND_CEILING)-1)
        p = band.start+index*band.step
        if band.start <= p < band.end and 0 < p < 1 and ((side == "bid" and p > touch) or (side == "ask" and p < touch)):
            candidates.append(p)
    return (min(candidates) if side == "bid" else max(candidates)) if candidates else None


def passive_price(book, position, basis, bands):
    side = "ask" if position > 0 else "bid"
    touch = book.asks.best(bid=False) if side == "ask" else book.bids.best(bid=True)
    other = book.bids.best(bid=True) if side == "ask" else book.asks.best(bid=False)
    if touch is None: return None
    validate_tick(touch, bands)
    if basis is None or other is None: return touch
    improved = adjacent_tick(touch, side, bands)
    if improved is None: return touch
    if side == "ask" and improved >= basis and improved > other: return improved
    if side == "bid" and improved <= basis and improved < other: return improved
    return touch


def cross(book, position, basis, bands, fee_bound, haircut, *, excluded=()):
    """Walk at most the existing bounded ladder; no sort/copy of full universe."""
    qty = abs(position)
    ladder = book.bids if position > 0 else book.asks
    prices = reversed(ladder.prices) if position > 0 else iter(ladder.prices)
    remaining, gross, worst = qty, Decimal(0), None
    own = {}
    for quote in excluded:
        if quote.side == ('bid' if position > 0 else 'ask'):
            own[quote.yes_price] = own.get(quote.yes_price, Decimal(0))+quote.quantity
    for p in prices:
        validate_tick(p, bands)
        depth = ladder.levels[p]-own.get(p, Decimal(0))
        if depth < 0:
            raise InvalidData('excluded order depth exceeds current book')
        take = min(remaining, depth*haircut)
        gross += take*(p-basis)*(1 if position > 0 else -1)
        remaining -= take
        worst = p
        if not remaining: break
    return remaining == 0, worst, gross-qty*fee_bound


def plan_exit(*, ticker, position, basis, first_seen_at, orders, book, terms,
              journal, now, complete_scope):
    """Caller must bind account/book/terms/writer revisions; result stays advisory."""
    now, position = utc(now), decimal(position)
    count(abs(position), zero=True)
    touch = None
    if book is not None and book.valid:
        if book.ticker != ticker: raise InvalidData("exit book scope mismatch")
        touch = book.asks.best(bid=False) if position > 0 else book.bids.best(bid=True)
    passive = inventory_plan(position, orders, ticker=ticker, touch=touch, complete_scope=complete_scope)
    def result(mode, *blockers, **kwargs):
        if 'next_at' not in kwargs and terms is not None:
            future = [t for t in (terms.deadline, terms.valid_until) if t > now]
            if future: kwargs['next_at'] = min(future)
        return ExitPlan(passive, mode, blockers=tuple(blockers), **kwargs)
    if not position: return result("flat")
    # Pending mutation attention timers must run even while reconciliation is
    # incomplete. These branches cannot propose a new mutation.
    if journal is not None and journal.unresolved_ioc:
        limit = journal.started_at+timedelta(seconds=10) if journal.started_at else None
        return result("attention" if limit is None or now >= limit else "wait",
                      "ioc_terminal_fill_proof_pending", next_at=limit if limit and limit > now else None)
    if journal is not None and journal.cancel_ids:
        late = (journal.cancel_started_at is None or now < journal.cancel_started_at
                or now-journal.cancel_started_at > timedelta(seconds=5))
        return result("attention" if late else "wait", "cancel_confirmation_pending",
                      next_at=journal.cancel_started_at+timedelta(seconds=5, microseconds=1) if not late else None)
    if complete_scope is not True: return result("blocked", "incomplete_exit_scope")
    if first_seen_at is None or basis is None: return result("blocked", "inventory_basis_or_clock_unknown")
    first_seen_at, basis = utc(first_seen_at), price(basis)
    if first_seen_at > now: return result("blocked", "inventory_clock_regressed")
    age_at = first_seen_at+timedelta(seconds=900)
    if terms is None: return result("blocked", "exit_terms_missing", next_at=age_at if age_at > now else None)
    if terms.ticker != ticker: raise InvalidData("exit terms scope mismatch")
    if not terms.observed_at <= now < terms.valid_until: return result("blocked", "exit_terms_stale")
    if not terms.active or now >= terms.close_at: return result("attention", "market_not_tradable")
    if book is None or not book.valid: return result("blocked", "exit_book_unavailable")
    if journal is None: return result("blocked", "exit_journal_unknown")
    integer(journal.attempts, 0, 4096)
    preferred = passive_price(book, position, basis, terms.bands)
    # Preserve the existing exact touch reducer before considering improvement.
    if passive.keep_id is None:
        passive = inventory_plan(position, orders, ticker=ticker, touch=preferred, complete_scope=complete_scope)
    due = now >= age_at or now >= terms.deadline
    next_at = min(age_at, terms.deadline, terms.valid_until)
    if not due: return result("passive", limit_price=preferred, next_at=next_at)
    if terms.event_risk_at is None and terms.flatten_at is None:
        return result("blocked", "event_risk_time_unknown", limit_price=preferred)
    if terms.taker_fee_per_contract_bound is None:
        return result("blocked", "exit_fee_bound_unknown", limit_price=preferred)
    if journal.attempts >= 3: return result("attention", "ioc_attempt_limit")
    if journal.started_at is not None and (now < journal.started_at or now-journal.started_at >= timedelta(seconds=30)):
        return result("attention", "ioc_retry_window")
    forced = now >= terms.deadline
    complete, worst, pnl = cross(book, position, basis, terms.bands, terms.taker_fee_per_contract_bound, Decimal('.5'))
    if forced and not complete:
        complete, worst, pnl = cross(book, position, basis, terms.bands, terms.taker_fee_per_contract_bound, Decimal(1))
    if not forced and (not complete or pnl < -8):
        return result("passive_deferred", "ordinary_exit_depth_or_loss", limit_price=preferred, projected_pnl=pnl,
                      next_at=min(terms.deadline, terms.valid_until))
    working = [r for r in orders if r.owned and not r.order.terminal]
    if working:
        # One target at a time; building orders first. No absence/cancel-ACK proof.
        side = 'ask' if position > 0 else 'bid'
        target = min(working, key=lambda r: (r.reducing and r.order.side == side, r.order.order_id))
        passive = InventoryPlan((target.order.order_id,), None, None, Decimal(0),
                                ('await_terminal_cancellation_and_fill_proof',))
        return result("cancel_before_ioc")
    unsafe = tuple(b for b in passive.blockers if b != 'no_passive_touch')
    if unsafe: return result("blocked", *unsafe)
    if not complete or worst is None: return result("attention", "forced_exit_insufficient_depth")
    return result("ioc", limit_price=worst, quantity=abs(position), projected_pnl=pnl)


def ioc_payload(*, ticker, client_id, position, limit_price, bands):
    """Exact remaining inventory, reduce-only, price-capped, never expiring IOC."""
    position = decimal(position)
    if not position: raise InvalidData("cannot exit flat inventory")
    payload = create_payload(ticker=ticker, client_id=client_id,
        outcome='no' if position > 0 else 'yes',
        outcome_price=1-price(limit_price) if position > 0 else price(limit_price),
        quantity=abs(position), bands=bands, reducing=True, position=position)
    payload.update(time_in_force='immediate_or_cancel', post_only=False)
    return payload
