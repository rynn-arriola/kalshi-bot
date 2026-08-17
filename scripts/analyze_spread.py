"""The two-sided economics: what a filled pair is actually worth.

On Kalshi a YES contract and a NO contract on the same market always settle to
exactly $1.00 between them -- one wins, one loses. So a maker resting a bid on
both sides and getting both filled has bought a guaranteed dollar for
`yes_bid + no_bid`, and the difference is locked profit before any reward:

    pair edge = 1.00 - (yes_bid + no_bid) - fees

This is the market-making trade. The liquidity incentive is a bonus on top of
it, not the whole thesis -- which matters, because it means the strategy has a
second source of return that does not depend on the unresolved `period_reward`
scale.

The catch is the same one liquidity-bot documents: only one side filling leaves
directional risk. This script measures the edge that is available, not the
probability of capturing it. Fill rates come from trades, elsewhere.

    python -B scripts/analyze_spread.py --database data/capture.db
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path


def taker_fee(contracts: float, price: float) -> float:
    """Confirmed against two real fills on 2026-08-16.

    ceil at four decimal places -- one hundredth of a cent -- not whole cents.
    """

    return math.ceil(0.07 * contracts * price * (1.0 - price) * 10000) / 10000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/capture.db")
    parser.add_argument("--size", type=float, default=5.0)
    parser.add_argument("--maker-fee-fraction", type=float, default=0.25,
                        help="maker fee as a fraction of taker. UNVERIFIED:"
                             " both account fills were is_taker=true.")
    args = parser.parse_args()

    connection = sqlite3.connect(
        f"file:{Path(args.database).resolve()}?mode=ro", uri=True)

    per_market: dict[str, list[float]] = defaultdict(list)
    all_edges: list[float] = []
    net_edges: list[float] = []
    crossed = 0
    one_sided = 0
    total = 0

    for ticker, raw in connection.execute(
            "SELECT market_ticker, raw_json FROM books"
            " WHERE raw_json IS NOT NULL ORDER BY fetched_at"):
        book = json.loads(raw).get("orderbook_fp") or {}
        yes = [(float(p), float(s)) for p, s in (book.get("yes_dollars") or [])]
        no = [(float(p), float(s)) for p, s in (book.get("no_dollars") or [])]
        total += 1
        if not yes or not no:
            one_sided += 1
            continue
        yes_touch = max(price for price, _ in yes)
        no_touch = max(price for price, _ in no)
        edge = 1.0 - (yes_touch + no_touch)
        # A negative edge means the two best bids sum past a dollar, which is
        # an arbitrage against us and in practice means stale or crossed data
        # rather than free money. Counted, not averaged in.
        if edge < 0:
            crossed += 1
            continue
        per_market[ticker].append(edge)
        all_edges.append(edge)
        # Fees priced at the ACTUAL touch of each leg. The curve is
        # 0.07*P*(1-P), maximal at 0.50 and near zero in the tails, and these
        # markets are mostly tail-priced -- so charging both legs at 0.50
        # overstates the cost by several times and made the pair trade look
        # like it barely cleared its own fees.
        net_edges.append(
            edge * args.size
            - args.maker_fee_fraction * taker_fee(args.size, yes_touch)
            - args.maker_fee_fraction * taker_fee(args.size, no_touch))

    print(f"snapshots            {total}")
    print(f"  one-sided          {one_sided}")
    print(f"  crossed (edge<0)   {crossed}")
    print(f"  usable             {len(all_edges)}")
    if not all_edges:
        return 1

    quantiles = statistics.quantiles(all_edges, n=10)
    print(f"\npair edge at the touch, per contract:")
    print(f"  median   {statistics.median(all_edges):.4f}")
    print(f"  p10      {quantiles[0]:.4f}")
    print(f"  p90      {quantiles[-1]:.4f}")

    # Stepping one tick inside on BOTH sides doubles the reward share on each
    # (FINDINGS: gain is 1/DiscountFactor, DF=0.50), and costs exactly two
    # cents of pair edge -- one per side.
    survives = sum(1 for edge in all_edges if edge > 0.02)
    print(f"\n  edge > 0.02 (room to step inside BOTH sides):"
          f" {survives}/{len(all_edges)} = {100.0*survives/len(all_edges):.1f}%")

    size = args.size
    net_q = statistics.quantiles(net_edges, n=10)
    positive = sum(1 for value in net_edges if value > 0)
    print(f"\nfor {size:g} contracts a side, BOTH legs filled at the touch,")
    print(f"fees charged at each leg's own price (maker rate UNVERIFIED):")
    print(f"  gross pair edge    ${statistics.median(all_edges) * size:.4f}")
    print(f"  net, median        ${statistics.median(net_edges):.4f}")
    print(f"  net, p10           ${net_q[0]:.4f}")
    print(f"  net, p90           ${net_q[-1]:.4f}")
    print(f"  net > 0            {positive}/{len(net_edges)}"
          f" = {100.0 * positive / len(net_edges):.1f}% of snapshots")

    print(f"\nper market, median pair edge (top 20 by edge):")
    header = f"{'ticker':34s}{'snaps':>7s}{'median':>9s}{'p10':>9s}{'>2c%':>7s}"
    print(header)
    print("-" * len(header))
    rows = sorted(per_market.items(),
                  key=lambda kv: -statistics.median(kv[1]))
    for ticker, edges in rows[:20]:
        wide = 100.0 * sum(1 for e in edges if e > 0.02) / len(edges)
        p10 = statistics.quantiles(edges, n=10)[0] if len(edges) >= 10 else min(edges)
        print(f"{ticker[:34]:34s}{len(edges):7d}"
              f"{statistics.median(edges):9.4f}{p10:9.4f}{wide:6.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
