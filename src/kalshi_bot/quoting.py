"""Exact current-rule snapshot arithmetic, not income forecasts or trade authority.

Only uniform price grids are supported: the venue's reward tick interpretation
across variable bands is still unconfirmed. Book prices use the YES convention.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext

from .adapters import PriceBand, validate_tick
from .books import Book
from .values import InvalidData, count, identity, integer, price, utc

ZERO = Decimal(0)


@dataclass(frozen=True)
class Program:
    program_id: str
    ticker: str
    start: datetime
    end: datetime
    target: Decimal
    discount_bps: int
    pool_centicents: int
    paid_out: bool
    max_reward_centicents: int | None = None

    def __post_init__(self):
        identity(self.program_id)
        identity(self.ticker)
        for name in ("start", "end"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        object.__setattr__(self, "target", count(self.target))
        if not 100 < self.target < 20000 or self.end <= self.start:
            raise InvalidData("unsupported program target or dates")
        integer(self.discount_bps, 0, 10000)
        integer(self.pool_centicents, 0, 2**63-1)
        if self.max_reward_centicents is not None:
            integer(self.max_reward_centicents, 0, 2**63-1)
        if type(self.paid_out) is not bool:
            raise InvalidData("program payout flag must be boolean")


def parse_program(row: dict) -> Program:
    try:
        if row["incentive_type"] != "liquidity":
            raise InvalidData("not a liquidity incentive")
        return Program(row["id"], row["market_ticker"],
                       datetime.fromisoformat(row["start_date"].replace("Z", "+00:00")),
                       datetime.fromisoformat(row["end_date"].replace("Z", "+00:00")),
                       row["target_size_fp"], row["discount_factor_bps"],
                       row["period_reward"], row["paid_out"], row.get("max_reward_per_account"))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise InvalidData("incomplete or unsupported liquidity program") from exc


@dataclass(frozen=True)
class Quote:
    side: str
    yes_price: Decimal
    quantity: Decimal

    def __post_init__(self):
        if self.side not in {"bid", "ask"}:
            raise InvalidData("invalid quote side")
        object.__setattr__(self, "yes_price", price(self.yes_price))
        object.__setattr__(self, "quantity", count(self.quantity))


@dataclass(frozen=True)
class SideScore:
    reference: Decimal | None
    cutoff: Decimal | None
    total: Decimal
    own: Decimal

    @property
    def share(self):
        with localcontext() as ctx:
            ctx.prec = 40
            return self.own/self.total if self.total else ZERO


@dataclass(frozen=True)
class QuotePlan:
    quotes: tuple[Quote, ...]
    bid: SideScore | None
    ask: SideScore | None
    snapshot_share: Decimal
    blockers: tuple[str, ...]


def _grid(bands):
    if type(bands) is not tuple or len(bands) != 1 or not isinstance(bands[0], PriceBand):
        raise InvalidData("variable-band reward ticks require venue confirmation")
    # Bound exponent/iteration work, including fine-grid underflow. Unsupported
    # finer grids fail closed; this is an engineering limit, not a venue claim.
    if (bands[0].end-bands[0].start)/bands[0].step > 10000:
        raise InvalidData("reward grid exceeds supported tick capacity")
    return bands[0].step


def _base(book, bands, reflected):
    _grid(bands)
    if not isinstance(book, Book) or not book.valid:
        raise InvalidData("valid stream book required")
    if len(reflected) > 4096 or any(not isinstance(q, Quote) for q in reflected):
        raise InvalidData("invalid bounded reflected-order set")
    base = {"bid": dict(book.bids.levels), "ask": dict(book.asks.levels)}
    for levels in base.values():
        if len(levels) > 4096:
            raise InvalidData("quote book exceeds supported capacity")
        for p, q in levels.items():
            price(p)
            band = bands[0]
            if not band.start <= p < band.end or (p-band.start) % band.step:
                raise InvalidData("price outside supported reward grid")
            count(q)
    if base["bid"] and base["ask"] and max(base["bid"]) >= min(base["ask"]):
        raise InvalidData("crossed quote book")
    # Caller must prove these orders are reflected in THIS public-book version.
    # Private order receipt alone does not prove public-stream synchronization.
    for quote in reflected:
        levels = base[quote.side]
        remaining = levels.get(quote.yes_price, ZERO)-quote.quantity
        if remaining < 0:
            raise InvalidData("own-order/public-book agreement missing")
        if remaining:
            levels[quote.yes_price] = remaining
        else:
            levels.pop(quote.yes_price, None)
    return base


def _reference(levels, target, side):
    cumulative = ZERO
    for p in sorted(levels, reverse=side == "bid"):
        cumulative += levels[p]
        if cumulative >= target/5:
            return p
    return None


def _score(levels, own, target, discount, step, side):
    ref = _reference(levels, target, side)
    if ref is None:
        return SideScore(None, None, ZERO, ZERO)
    cumulative, total, mine = ZERO, ZERO, ZERO
    for p in sorted(levels, reverse=side == "bid"):
        ticks = max(ZERO, (ref-p if side == "bid" else p-ref)/step)
        if ticks != ticks.to_integral_value():
            raise InvalidData("non-integral reward tick distance")
        weight = Decimal(1) if ticks == 0 else discount**int(ticks)
        total += levels[p]*weight
        mine += own.get(p, ZERO)*weight
        cumulative += levels[p]
        if cumulative >= target:
            # Entire cutoff price level counts, not just its first target units.
            return SideScore(ref, p, total, mine)
    return SideScore(ref, None, ZERO, ZERO)


def snapshot_score(book: Book, program: Program, bands: tuple[PriceBand, ...],
                   proposed: tuple[Quote, ...], *, reflected: tuple[Quote, ...] = ()):
    """Replace proven reflected own orders, then score hypothetical resting ones.

    Pure arithmetic only. Does not infer market/program freshness or eligibility.
    """
    if book.ticker != program.ticker or len(proposed) > 30:
        raise InvalidData("quote/program scope or proposal capacity mismatch")
    levels = _base(book, bands, reflected)
    return _snapshot_from_base(levels, program, bands, proposed)


def _snapshot_from_base(levels, program, bands, proposed):
    own = {"bid": {}, "ask": {}}
    for quote in proposed:
        if not isinstance(quote, Quote):
            raise InvalidData("validated quote required")
        validate_tick(quote.yes_price, bands)
        p, side, q = quote.yes_price, quote.side, quote.quantity
        levels[side][p] = levels[side].get(p, ZERO)+q
        own[side][p] = own[side].get(p, ZERO)+q
    if levels["bid"] and levels["ask"] and max(levels["bid"]) >= min(levels["ask"]):
        raise InvalidData("proposed quote would cross or lock the book")
    with localcontext() as ctx:
        ctx.prec = 40
        bid, ask = (_score(levels[s], own[s], program.target,
                           Decimal(program.discount_bps)/10000, bands[0].step, s)
                    for s in ("bid", "ask"))
        share = (bid.share+ask.share)/2 if bid.cutoff is not None and ask.cutoff is not None else ZERO
        return bid, ask, share


def reference_plan(book: Book, program: Program, bands: tuple[PriceBand, ...], *,
                   now: datetime, market_open: bool, reflected: tuple[Quote, ...] = ()) -> QuotePlan:
    return program_plans(book, (program,), bands, now=now, market_open=market_open,
                         reflected=reflected)[0]


def program_plans(book, programs, bands, *, now, market_open, reflected=(), proposed=None):
    """Validate a shared book once for a bounded set of independent programs.

    Each scoring pass gets its own ladder copy. Never accumulate hypothetical
    orders across competing programs or change the caller's actual book.
    """
    now = utc(now)
    if (type(programs) is not tuple or not 1 <= len(programs) <= 16
            or any(not isinstance(p, Program) or p.ticker != book.ticker for p in programs)):
        raise InvalidData('bounded matching programs required')
    if proposed is not None and (type(proposed) is not tuple or not 1 <= len(proposed) <= 30
                                or any(not isinstance(q, Quote) for q in proposed)):
        raise InvalidData('bounded exact quotes required')
    base, results = None, []
    for program in programs:
        if market_open is not True or program.paid_out or not program.start <= now < program.end:
            results.append(QuotePlan((), None, None, ZERO, ('market_or_program_inactive',)))
            continue
        if base is None:
            base = _base(book, bands, reflected)
        levels = {s: dict(rows) for s, rows in base.items()}
        quotes = (proposed if proposed is not None else
                  tuple(Quote(s, p, Decimal(10)) for s in ('bid', 'ask')
                        if (p := _reference(levels[s], program.target, s)) is not None))
        bid, ask, share = _snapshot_from_base(levels, program, bands, quotes)
        if bid.cutoff is None or ask.cutoff is None or (proposed is None and len(quotes) != 2):
            results.append(QuotePlan(quotes if proposed is not None else (), bid, ask, ZERO,
                                     ('insufficient_two_sided_depth',)))
        else:
            results.append(QuotePlan(quotes, bid, ask, share, ()))
    return tuple(results)
