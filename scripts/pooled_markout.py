"""Pooled one-sided markout across every capture, with a sign test and a CI.

FINDINGS 6h left the sign of one-sided markout UNRESOLVED at n=14: the median
sat near zero, the mean was dominated by a single -$1.75 observation, and the
two disagreed by a factor of twenty. The stated fix was "wait for n".

Waiting turned out to be the wrong instrument. Widening the universe from 40
markets to 150 made the sample grow *slower*, not faster -- ranking by
`reward/target` selects for thin books by construction, so the markets we add
are quieter than the ones we had. The fill rate fell rather than rose.

What settles it instead is a test that does not need a large n and is not
hostage to one outlier:

  1. A **sign test** on each horizon. It asks only whether fills are negative
     more often than a coin would say, so a -$1.75 observation counts exactly
     as much as a -$0.001 one. This is the right tool when the mean is the
     unstable statistic.
  2. A **bootstrap CI on the mean**, because P&L is paid in dollars, not in
     signs. If that interval excludes zero the drag is not merely signed, it is
     bounded, and it can go into the economics.

Both run on the two captures POOLED. They are separate slates -- 40 markets at
15s and 150 markets at 60s -- and the overlap between them is measured and
reported rather than assumed to be zero, because a shared market is a shared
sample and would inflate n without adding evidence.

Fill detection, queue position and the YES-frame reduction are imported from
`markout.py` rather than reimplemented. That file is the authority on how a
trade becomes a fill, and a second copy of that logic would be a second thing
to get wrong (BUGFIXES: the pooled-median bug came from exactly this).

    python -B scripts/pooled_markout.py
    python -B scripts/pooled_markout.py --policy inside
"""

from __future__ import annotations

import argparse
import math
import random
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from markout import (  # noqa: E402
    HORIZONS,
    first_fill,
    load_books,
    load_trades,
    mid_at,
    quote,
)

# Reward per day by size, from `sizing.py` and recorded in FINDINGS 9. It is
# NOT recomputed here: sizing replays the reward formula over books with our
# order inserted and applies the two-sided rule and the $1.00 minimum, which is
# a different measurement from this one. Keeping the seam explicit means a
# change to sizing does not silently move a number in this table.
REWARD_PER_DAY = {5.0: 4.68, 25.0: 23.89, 100.0: 37.43}

# Markets surviving sizing.py's three guards (crowded, sub-day period, under
# 10% period coverage). Drag is charged only against markets we would actually
# quote, so this must match sizing's surviving set, not the captured universe.
QUOTED_MARKETS = 10

BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_SEED = 20260817


def binomial_sign_test(negative: int, positive: int) -> float:
    """Exact two-sided binomial p-value against p=0.5. Ties are dropped.

    Written out rather than imported: scipy is not a dependency of this project
    and adding one for a closed-form expression would be the wrong trade.
    """

    n = negative + positive
    if n == 0:
        return 1.0
    k = min(negative, positive)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


def bootstrap_mean_ci(
    values: list[float], resamples: int, seed: int,
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean.

    The mean is the statistic P&L actually depends on, and it is exactly the
    statistic one outlier destabilises. Resampling reports how unstable it is
    instead of hiding it behind a point estimate.
    """

    if len(values) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(resamples):
        means.append(statistics.fmean(rng.choices(values, k=n)))
    means.sort()
    low = means[int(0.025 * resamples)]
    high = means[min(resamples - 1, int(0.975 * resamples))]
    return (low, high)


def market_hours(books: dict[str, tuple[list[tuple], float]]) -> float:
    """Observed market-hours: per market, first to last snapshot."""

    total = 0.0
    for series, _ in books.values():
        if len(series) >= 2:
            total += (series[-1][0] - series[0][0]) / 3600.0
    return total


def collect(
    books: dict[str, tuple[list[tuple], float]],
    trades: dict[str, list[tuple]],
    policy: str,
    size: float,
    window: float,
    stride: float,
    tolerance: float,
) -> dict:
    """Replay a resting two-sided quote and return fills, markouts, pairs.

    This mirrors `markout.main`'s loop exactly. It is duplicated only because
    that function prints and returns an exit code; every decision inside it --
    fill predicate, queue, YES-frame markout -- is the imported one.
    """

    outcomes: dict[str, int] = defaultdict(int)
    pair_edge: list[float] = []
    per_horizon: dict[float, list[float]] = defaultdict(list)

    for ticker, (series, tick) in books.items():
        tape = trades.get(ticker) or []
        last_sample = None
        for ts, yes_bid, bid_size, yes_offer, offer_size in series:
            if last_sample is not None and ts - last_sample < stride:
                continue
            last_sample = ts
            outcomes["sampled"] += 1
            if yes_offer - yes_bid < 1e-9:
                continue
            outcomes["quotable"] += 1

            bid, bid_queue, offer, offer_queue, _ = quote(
                policy, yes_bid, bid_size, yes_offer, offer_size, tick)

            bid_fill = first_fill(
                tape, ts, window, bid, bid_queue, size, "bid")
            offer_fill = first_fill(
                tape, ts, window, offer, offer_queue, size, "offer")

            if bid_fill is not None and offer_fill is not None:
                outcomes["both"] += 1
                pair_edge.append((offer - bid) * size)
                continue
            if bid_fill is None and offer_fill is None:
                outcomes["neither"] += 1
                continue

            outcomes["one_sided"] += 1
            if bid_fill is not None:
                fill_ts, entry, direction = bid_fill, bid, 1.0
            else:
                fill_ts, entry, direction = offer_fill, offer, -1.0

            for horizon in HORIZONS:
                mid = mid_at(series, fill_ts + horizon, tolerance)
                if mid is None:
                    continue
                per_horizon[horizon].append(direction * (mid - entry) * size)

    return {
        "outcomes": outcomes,
        "pair_edge": pair_edge,
        "per_horizon": per_horizon,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--databases", nargs="+",
                        default=["data/capture.db", "data/capture_wide.db"])
    parser.add_argument("--policy", choices=("touch", "inside"), default="touch")
    parser.add_argument("--sizes", nargs="+", type=float,
                        default=[5.0, 25.0, 100.0])
    parser.add_argument("--window", type=float, default=3600.0)
    parser.add_argument("--stride", type=float, default=None)
    parser.add_argument("--tolerance", type=float, default=30.0)
    args = parser.parse_args()
    stride = args.stride if args.stride is not None else args.window

    loaded = []
    for database in args.databases:
        path = Path(database)
        if not path.exists():
            print(f"missing: {database}")
            continue
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        books = load_books(connection)
        trades = load_trades(connection)
        loaded.append((database, books, trades))
        print(f"{database:<28s} markets {len(books):<5d}"
              f" market-hours {market_hours(books):8.1f}")

    if not loaded:
        return 1

    # Overlap matters: a market captured in both databases is sampled twice and
    # its fills are not independent observations.
    if len(loaded) >= 2:
        shared = set(loaded[0][1]) & set(loaded[1][1])
        print(f"{'shared markets':<28s} {len(shared)}"
              f"   ({100.0 * len(shared) / max(1, len(loaded[1][1])):.1f}%"
              f" of the wider slate)")

    print()
    print(f"policy {args.policy}, window {args.window:g}s, stride {stride:g}s")

    for size in args.sizes:
        print()
        print("=" * 72)
        print(f"SIZE {size:g} CONTRACTS PER SIDE")
        print("=" * 72)

        pooled: dict[float, list[float]] = defaultdict(list)
        totals: dict[str, int] = defaultdict(int)
        pairs: list[float] = []
        hours = 0.0

        for database, books, trades in loaded:
            result = collect(books, trades, args.policy, size,
                             args.window, stride, args.tolerance)
            hours += market_hours(books)
            for key, value in result["outcomes"].items():
                totals[key] += value
            pairs.extend(result["pair_edge"])
            for horizon, values in result["per_horizon"].items():
                pooled[horizon].extend(values)

            one_sided = result["outcomes"]["one_sided"]
            both = result["outcomes"]["both"]
            quotable = max(1, result["outcomes"]["quotable"])
            print(f"  {Path(database).name:<22s}"
                  f" windows {result['outcomes']['quotable']:<6d}"
                  f" one-sided {one_sided:<4d} ({100.0*one_sided/quotable:4.1f}%)"
                  f" pairs {both}")

        quotable = max(1, totals["quotable"])
        print(f"  {'POOLED':<22s} windows {totals['quotable']:<6d}"
              f" one-sided {totals['one_sided']:<4d}"
              f" ({100.0*totals['one_sided']/quotable:4.1f}%)"
              f" pairs {totals['both']}")

        if pairs:
            print(f"  completed pairs: n={len(pairs)}"
                  f"  median ${statistics.median(pairs):+.4f}"
                  f"  positive {100.0*sum(1 for p in pairs if p > 0)/len(pairs):.0f}%")

        fills_per_market_hour = totals["one_sided"] / max(1e-9, hours)
        print(f"  one-sided fills per market-hour: {fills_per_market_hour:.4f}")

        print()
        print(f"  {'horizon':<9s}{'n':>5s}{'median':>11s}{'mean':>11s}"
              f"{'neg':>7s}{'sign p':>10s}{'95% CI on mean':>28s}")
        for horizon in HORIZONS:
            values = pooled[horizon]
            if not values:
                print(f"  {horizon:<9.0f}    no samples")
                continue
            negative = sum(1 for v in values if v < 0)
            positive = sum(1 for v in values if v > 0)
            p = binomial_sign_test(negative, positive)
            low, high = bootstrap_mean_ci(
                values, BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED)
            print(f"  {horizon:<9.0f}{len(values):>5d}"
                  f"{statistics.median(values):>+11.4f}"
                  f"{statistics.fmean(values):>+11.4f}"
                  f"{100.0*negative/len(values):>6.0f}%"
                  f"{p:>10.4f}"
                  f"      [{low:+.4f}, {high:+.4f}]")

        # Drag, and the net that follows. Charged at the 300s horizon: it is
        # long enough that the fill's information is in the price and short
        # enough to sit inside a realistic flatten, and 6h reported all three.
        values = pooled[300.0]
        if values and size in REWARD_PER_DAY:
            low, high = bootstrap_mean_ci(
                values, BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED)
            reward = REWARD_PER_DAY[size]
            print()
            print(f"  drag/day = 24h x {fills_per_market_hour:.4f} fills"
                  f" x markout x {QUOTED_MARKETS} markets")
            for label, markout_value in (
                    ("best  (CI high)", high),
                    ("central (mean)", statistics.fmean(values)),
                    ("worst (CI low)", low)):
                drag = (24.0 * fills_per_market_hour
                        * markout_value * QUOTED_MARKETS)
                print(f"    {label:<18s} markout ${markout_value:+.4f}"
                      f"   drag ${drag:+8.2f}/day"
                      f"   reward ${reward:6.2f}"
                      f"   net ${reward + drag:+8.2f}/day")

    print()
    print("GROSS of fees throughout. The maker fee rate is still unmeasured on")
    print("this account (FINDINGS 6e), so a fee-net figure would be invented.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
