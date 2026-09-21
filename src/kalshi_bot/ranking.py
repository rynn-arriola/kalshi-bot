"""Bounded market ranking views, not automatic market selection or profit claims.

Ranks gross *unchanged-book* arithmetic. Each program keeps its own reference
quotes and dates; incompatible overlapping programs are never added together.
No loss estimate, fee assumption, payout entitlement or $1 eligibility is invented.
"""
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext

from .quoting import Program, Quote, reference_plan
from .values import InvalidData, decimal, identity, integer, utc


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


class RankingBoard:
    def __init__(self, capacity=128):
        self.capacity = integer(capacity, 1, 1024)
        self.markets = {}

    def invalidate(self, ticker):
        """Call on a book gap, metadata revocation, fill or changed account proof."""
        identity(ticker)
        self.markets.pop(ticker, None)

    def update(self, book, programs: tuple[Program, ...], bands, *, now, valid_until,
               market_open: bool, position=Decimal(0), reflected=()):
        now, valid_until = utc(now), utc(valid_until)
        ticker = identity(book.ticker)
        # Validation failures must revoke the previous version too.
        self.markets.pop(ticker, None)
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
        for program in programs:
            plan = reference_plan(book, program, bands, now=now, market_open=market_open, reflected=reflected)
            blockers = plan.blockers + (("open_inventory_no_new_entries",) if position else ())
            if program.max_reward_centicents is not None:
                blockers += ("account_reward_cap_needs_accrual_and_ordering_proof",)
            gross_hourly = capital = efficiency = remaining = None
            if not blockers:
                with localcontext() as ctx:
                    ctx.prec = 40
                    pool = Decimal(program.pool_centicents)/10000
                    rate = pool*plan.snapshot_share/seconds(program.end-program.start)
                    gross_hourly = rate*3600
                    remaining = rate*seconds(program.end-now)
                    capital = sum((q.quantity*(q.yes_price if q.side == "bid" else 1-q.yes_price)
                                   for q in plan.quotes), Decimal(0))
                    efficiency = gross_hourly/capital
            rows.append(RankedMarket(ticker, program.program_id, plan.quotes if not blockers else (), now,
                                     min(valid_until, program.end), program.end, gross_hourly, remaining,
                                     capital, efficiency, plan.snapshot_share, blockers))
        self.markets[ticker] = tuple(rows)

    def ranked(self, *, now, by: str) -> tuple[RankedMarket, ...]:
        """One best program per market, explicit view; never an order allocation."""
        fields = {"remaining_reward": "gross_remaining_usd", "reward_rate": "gross_hourly_usd",
                  "capital_efficiency": "gross_hourly_per_capital"}
        if by not in fields:
            raise InvalidData("unknown ranking view")
        now = utc(now)
        chosen = []
        def key(row):
            value = getattr(row, fields[by])
            return (bool(row.blockers), -(value if value is not None else Decimal(0)), row.ticker, row.program_id)
        for rows in self.markets.values():
            candidates = []
            for row in rows:
                if now < row.observed_at or now >= row.valid_until:
                    candidates.append(replace(row, quotes=(), gross_hourly_usd=None, gross_remaining_usd=None,
                                              gross_hourly_per_capital=None, blockers=row.blockers+("ranking_evidence_expired",)))
                elif not row.blockers:
                    with localcontext() as ctx:
                        ctx.prec = 40
                        candidates.append(replace(row, gross_remaining_usd=row.gross_hourly_usd*seconds(row.program_end-now)/3600))
                else:
                    candidates.append(row)
            chosen.append(min(candidates, key=key))
        return tuple(sorted(chosen, key=key))
