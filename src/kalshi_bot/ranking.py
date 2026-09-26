"""Bounded market ranking views, not automatic market selection or profit claims.

Ranks gross *unchanged-book* arithmetic. Each program keeps its own reference
quotes and dates; incompatible overlapping programs are never added together.
This ranking layer does not itself invent loss, fee, payout or entry authority;
the accepted $1 new-entry projection gate is applied by ``MarketSelector``.
"""
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext

from .quoting import Program, Quote, program_plans
from .values import InvalidData, count, decimal, identity, integer, utc


def seconds(delta):
    return Decimal(delta.days*86400+delta.seconds)+Decimal(delta.microseconds)/1000000


@dataclass(frozen=True)
class RankedMarket:
    ticker: str
    program_id: str
    quotes: tuple[Quote, ...]
    observed_at: datetime
    valid_until: datetime
    program_end: datetime
    gross_hourly_usd: Decimal | None
    gross_remaining_usd: Decimal | None
    capital_usd: Decimal | None
    gross_hourly_per_capital: Decimal | None
    snapshot_share: Decimal
    blockers: tuple[str, ...]
    net_profit_usd: None = None
    trade_ready: bool = False
    earning_until: datetime | None = None
    quote_statuses: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    bid_reference: Decimal | None = None
    ask_reference: Decimal | None = None
    bid_cutoff: Decimal | None = None
    ask_cutoff: Decimal | None = None
    quote_basis: str = 'hypothetical_reference'


def quote_status(quote, score, program):
    if score is None or score.cutoff is None:
        return 'insufficient_depth'
    bid = quote.side == 'bid'
    if (quote.yes_price < score.cutoff if bid else quote.yes_price > score.cutoff):
        return 'outside_reward_cutoff'
    worse = quote.yes_price < score.reference if bid else quote.yes_price > score.reference
    if worse and program.discount_bps == 0:
        return 'zero_price_weight'
    return 'discounted' if worse and program.discount_bps < 10000 else 'full_price_weight'


def payout_warnings(remaining):
    return ('remaining_projection_below_program_minimum_accrual_unknown',) if remaining < 1 else ()


class RankingBoard:
    def __init__(self, capacity=128, quantity=None):
        from .config import active
        self.capacity = integer(capacity, 1, 1024)
        # D-142: hypothetical reference pairs use the approved entry size.
        self.quantity = active().entry_contracts if quantity is None else count(quantity)
        self.markets = {}

    def invalidate(self, ticker):
        """Call on a book gap, metadata revocation, fill or changed account proof."""
        identity(ticker)
        self.markets.pop(ticker, None)

    def update(self, book, programs: tuple[Program, ...], bands, *, now, valid_until,
               market_open: bool, position=Decimal(0), reflected=(), proposed=None,
               entry_until=None, blockers=()):
        now, valid_until = utc(now), utc(valid_until)
        ticker = identity(book.ticker)
        # Validation failures must revoke the previous version too.
        self.markets.pop(ticker, None)
        if (type(blockers) is not tuple or len(blockers) > 32
                or any(not isinstance(b, str) or not b or len(b) > 200 for b in blockers)):
            raise InvalidData('bounded blocker codes required')
        if proposed is not None and (type(proposed) is not tuple or not 1 <= len(proposed) <= 30
                                    or any(not isinstance(q, Quote) for q in proposed)):
            raise InvalidData('bounded exact quote set required')
        entry_until = utc(entry_until) if entry_until is not None else None
        if valid_until <= now:
            raise InvalidData("ranking requires explicit future freshness boundary")
        if ticker not in self.markets and len(self.markets) >= self.capacity:
            raise InvalidData("ranking market capacity exceeded")
        if (type(programs) is not tuple or not 1 <= len(programs) <= 16
                or any(not isinstance(p, Program) or p.ticker != ticker for p in programs)
                or len({p.program_id for p in programs}) != len(programs)):
            raise InvalidData("bounded unique per-market incentive programs required")
        position = decimal(position)
        # Never retain an old optimistic ranking when new evidence cannot parse.
        rows = []
        plans = program_plans(book, programs, bands, now=now, market_open=market_open,
                              reflected=reflected, proposed=proposed, quantity=self.quantity)
        for program, plan in zip(programs, plans):
            statuses = tuple(quote_status(q, plan.bid if q.side == 'bid' else plan.ask, program)
                             for q in plan.quotes)
            row_blockers = blockers + plan.blockers + (("open_inventory_no_new_entries",) if position else ())
            if any(s in {'outside_reward_cutoff', 'zero_price_weight', 'insufficient_depth'} for s in statuses):
                row_blockers += ('proposed_quote_not_scoring',)
            end = min(program.end, entry_until) if entry_until is not None else program.end
            if end <= now:
                row_blockers += ('entry_horizon_ended',)
            if program.max_reward_centicents is not None:
                row_blockers += ("account_reward_cap_needs_accrual_and_ordering_proof",)
            gross_hourly = capital = efficiency = remaining = None
            warnings = ('discounted_quote',) if 'discounted' in statuses else ()
            if not row_blockers:
                with localcontext() as ctx:
                    ctx.prec = 40
                    pool = Decimal(program.pool_centicents)/10000
                    rate = pool*plan.snapshot_share/seconds(program.end-program.start)
                    gross_hourly = rate*3600
                    remaining = rate*seconds(end-now)
                    capital = sum((q.quantity*(q.yes_price if q.side == "bid" else 1-q.yes_price)
                                   for q in plan.quotes), Decimal(0))
                    efficiency = gross_hourly/capital
                    warnings += payout_warnings(remaining)
            rows.append(RankedMarket(ticker, program.program_id, plan.quotes if not row_blockers else (), now,
                min(valid_until, end), program.end, gross_hourly, remaining, capital, efficiency,
                plan.snapshot_share, tuple(dict.fromkeys(row_blockers)), earning_until=end,
                quote_statuses=statuses, warnings=warnings,
                bid_reference=plan.bid.reference if plan.bid else None,
                ask_reference=plan.ask.reference if plan.ask else None,
                bid_cutoff=plan.bid.cutoff if plan.bid else None,
                ask_cutoff=plan.ask.cutoff if plan.ask else None,
                quote_basis='explicit_quotes' if proposed is not None else 'hypothetical_reference'))
        self.markets[ticker] = tuple(rows)

    def _ranked(self, *, now, by: str, per_program: bool) -> tuple[RankedMarket, ...]:
        fields = {"remaining_reward": "gross_remaining_usd", "reward_rate": "gross_hourly_usd",
                  "capital_efficiency": "gross_hourly_per_capital", "selection": "gross_hourly_usd"}
        if by not in fields:
            raise InvalidData("unknown ranking view")
        now = utc(now)
        chosen = []
        def key(row):
            value = getattr(row, fields[by])
            efficiency = row.gross_hourly_per_capital if by == 'selection' else None
            return (bool(row.blockers), -(value if value is not None else Decimal(0)),
                    -(efficiency if efficiency is not None else Decimal(0)), row.ticker, row.program_id)
        for rows in self.markets.values():
            candidates = []
            for row in rows:
                if now < row.observed_at or now >= row.valid_until:
                    candidates.append(replace(row, quotes=(), gross_hourly_usd=None, gross_remaining_usd=None,
                                              gross_hourly_per_capital=None, blockers=row.blockers+("ranking_evidence_expired",)))
                elif not row.blockers:
                    with localcontext() as ctx:
                        ctx.prec = 40
                        remaining = row.gross_hourly_usd*seconds((row.earning_until or row.program_end)-now)/3600
                        warnings = tuple(w for w in row.warnings if w != 'remaining_projection_below_program_minimum_accrual_unknown')
                        candidates.append(replace(row, gross_remaining_usd=remaining,
                                                  warnings=warnings+payout_warnings(remaining)))
                else:
                    candidates.append(row)
            chosen.extend(candidates if per_program else (min(candidates, key=key),))
        return tuple(sorted(chosen, key=key))

    def ranked(self, *, now, by: str) -> tuple[RankedMarket, ...]:
        """One best program per market, explicit view; never an order allocation."""
        return self._ranked(now=now, by=by, per_program=False)

    def ranked_programs(self, *, now, by: str) -> tuple[RankedMarket, ...]:
        """All programs for qualification before one-per-market selection."""
        return self._ranked(now=now, by=by, per_program=True)
