"""Reward and fills in ONE simulation, so the two stop contradicting each other.

`sizing.py` computes reward as if we rest continuously and never read the trade
tape at all. `markout.py` computes fill cost as if fills happen. Adding the two
numbers together -- which is what FINDINGS 9 and 6i do -- double-counts our
presence: the reward line assumes we are quoting during exactly the moments the
drag line says we are filled and flattening.

This runs one clock over each market and lets a fill actually interrupt the
reward integral, which is the mechanism section 2 warns about:

    "Snapshots will be excluded if there is not two-sided liquidity"

so pulling our quotes after a fill zeroes our score on BOTH sides, not just the
filled one. That cost appears in neither existing script.

State machine per market, stepped at every book snapshot:

  RESTING     quote both sides under the policy; accrue reward share; watch the
              tape between this snapshot and the next for a fill
  FLATTENING  we were filled and hold a position: quotes are down, reward
              accrues ZERO, for `--flatten-seconds`, then we re-quote

Two things this models that `markout.py` deliberately did not:

1. **Queue position persists.** markout.py treats every snapshot as an
   independent experiment and puts us at the back each time. Here we hold our
   place while our price is still the one the policy wants, and volume that
   trades through us eats the queue ahead. We only go to the back when the book
   moves and we reprice. That is what a real quoter does, and it raises the
   fill rate -- which makes the answer worse, not better.
2. **Partial fills**, under `--fill-model partial`. Requiring the whole order
   made markout.py's fill rate FALL with size (0.0435 at 5 contracts, 0.0328 at
   100), which is backwards: a bigger quote fills partially more often, not
   less. Partial mode fills whatever volume reaches us and marks out that.

`--flatten-seconds` is swept rather than fixed because it is unmeasured. It is
the difference between a fill costing 0.6% of a market's daily reward and 15%
of it, and no order has ever been placed to find out which.

    python -B scripts/net_sizing.py --size 25
    python -B scripts/net_sizing.py --size 25 --fill-model partial
"""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_capture import qualifying, share_with_order  # noqa: E402
from markout import DEFAULT_TICK, best_level, infer_tick, parse_ts  # noqa: E402

REWARD_SCALE = 10000.0
MINIMUM_PAYOUT = 1.00


def load_programs(connection: sqlite3.Connection) -> dict[str, dict]:
    programs: dict[str, dict] = {}
    for (raw,) in connection.execute(
            "SELECT raw_json FROM programs ORDER BY fetched_at"):
        row = json.loads(raw)
        if row.get("market_ticker"):
            programs[row["market_ticker"]] = row
    return programs


def load_series(
    connection: sqlite3.Connection, programs: dict[str, dict],
) -> dict[str, tuple[list[dict], float]]:
    """Per market, snapshots carrying BOTH representations, plus the tick.

    The full ladders drive reward scoring (each side is a walk down from its own
    best bid); the reduced YES frame drives fills and markout. `sizing.py` keeps
    only the first and `markout.py` only the second, which is why neither could
    answer this question alone.
    """

    series: dict[str, list[dict]] = defaultdict(list)
    prices: dict[str, set[float]] = defaultdict(set)
    for ticker, fetched_at, raw in connection.execute(
            "SELECT market_ticker, fetched_at, raw_json FROM books"
            " WHERE raw_json IS NOT NULL ORDER BY fetched_at"):
        if ticker not in programs:
            continue
        book = (json.loads(raw) or {}).get("orderbook_fp") or {}
        ladders = {
            name: [(float(p), float(s))
                   for p, s in (book.get(f"{name}_dollars") or [])]
            for name in ("yes", "no")}
        if not (ladders["yes"] and ladders["no"]):
            continue
        yes_best, no_best = best_level(ladders["yes"]), best_level(ladders["no"])
        if yes_best is None or no_best is None:
            continue
        prices[ticker].update(p for p, _ in ladders["yes"])
        prices[ticker].update(round(1.0 - p, 4) for p, _ in ladders["no"])
        series[ticker].append({
            "ts": parse_ts(fetched_at),
            "ladders": ladders,
            "bid": yes_best[0], "bid_size": yes_best[1],
            "offer": round(1.0 - no_best[0], 4), "offer_size": no_best[1],
        })
    out = {}
    for ticker, rows in series.items():
        rows.sort(key=lambda r: r["ts"])
        out[ticker] = (rows, infer_tick(prices[ticker]))
    return out


def load_tape(connection: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Per market tape as (ts, yes_price, size, taker_side), time ordered.

    Direction comes from the price pair, never from a book-side field
    (FINDINGS 6f). A row whose two prices do not sum to one is dropped rather
    than reinterpreted.
    """

    tape: dict[str, list[tuple]] = defaultdict(list)
    for ticker, raw in connection.execute(
            "SELECT market_ticker, raw_json FROM trades"):
        row = json.loads(raw)
        try:
            yes_price = float(row["yes_price_dollars"])
            no_price = float(row["no_price_dollars"])
            size = float(row["count_fp"])
            taker = str(row["taker_side"]).strip().lower()
            ts = parse_ts(row["created_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(yes_price + no_price - 1.0) > 1e-6 or taker not in {"yes", "no"}:
            continue
        tape[ticker].append((ts, yes_price, size, taker))
    for rows in tape.values():
        rows.sort()
    return tape


def target_quote(
    policy: str, snapshot: dict, tick: float,
) -> tuple[float, float, float, float]:
    """Prices the policy wants now, and the depth resting at each.

    Stepping inside needs three ticks of spread so a tick still separates our
    own two orders. With no room the side joins the touch, which is what makes
    this a policy and not a filter (FINDINGS 6h: room exists 21.4% of the time).
    """

    bid, offer = snapshot["bid"], snapshot["offer"]
    if policy == "inside" and (offer - bid) >= 3 * tick - 1e-9:
        return (round(bid + tick, 6), 0.0, round(offer - tick, 6), 0.0)
    return bid, snapshot["bid_size"], offer, snapshot["offer_size"]


def mid_after(series: list[dict], index: int, target: float,
              tolerance: float) -> float | None:
    """Mid from the snapshot nearest `target`, or None if the gap is too wide.

    Captures have holes. Marking out against a book from hours later would
    manufacture a number, so those fills leave the sample instead.
    """

    lo = bisect.bisect_left([r["ts"] for r in series[index:]], target) + index
    best = None
    for j in (lo - 1, lo, lo + 1):
        if index <= j < len(series):
            gap = abs(series[j]["ts"] - target)
            if best is None or gap < best[0]:
                best = (gap, series[j])
    if best is None or best[0] > tolerance:
        return None
    return (best[1]["bid"] + best[1]["offer"]) / 2.0


def _top_decile_share(values: list[float]) -> float:
    """Fraction of the total carried by the largest tenth of observations."""

    if not values:
        return 0.0
    total = sum(values)
    if total <= 0:
        return 0.0
    ordered = sorted(values, reverse=True)
    return sum(ordered[:max(1, len(ordered) // 10)]) / total


def simulate(
    series: list[dict], tick: float, tape: list[tuple], tape_ts: list[float],
    target_size: float, discount: float, args: argparse.Namespace,
    flatten: float,
) -> dict:
    """One clock: reward accrues only while we are actually resting."""

    numerator = 0.0        # sum of our snapshot scores (yes share + no share)
    counting = 0           # snapshots the filing would count, present or not
    resting_counted = 0    # of those, ones where we were actually quoting
    per_snapshot: list[float] = []   # for the mean-vs-median comparison
    markouts: list[float] = []
    fill_count = 0
    flatten_until = -1.0
    # Our live quote, carried across snapshots so queue position can persist.
    live = None            # (bid_px, bid_queue, offer_px, offer_queue)

    for index, snapshot in enumerate(series):
        ts = snapshot["ts"]
        ladders = snapshot["ladders"]

        # The two-sided gate is a property of the book, not of our order: at 25
        # contracts against a target of 1000 we cannot rescue a short side.
        two_sided = all(
            qualifying(ladders[name], target_size, discount)[2]
            for name in ("yes", "no"))
        if two_sided:
            counting += 1

        if ts < flatten_until:
            # Position open, quotes down. This snapshot pays us nothing and
            # still counts in the denominator -- that is the cost the two
            # separate scripts both miss.
            live = None
            continue

        want_bid, bid_depth, want_offer, offer_depth = target_quote(
            args.policy, snapshot, tick)
        if want_offer - want_bid < 1e-9:
            live = None
            continue

        # Reprice only when the policy's price moved. Holding a price keeps our
        # queue position; repricing sends us to the back of the new level.
        if live is None:
            live = [want_bid, bid_depth, want_offer, offer_depth]
        else:
            if abs(live[0] - want_bid) > 1e-9:
                live[0], live[1] = want_bid, bid_depth
            if abs(live[2] - want_offer) > 1e-9:
                live[2], live[3] = want_offer, offer_depth

        if two_sided:
            resting_counted += 1
            score = 0.0
            for name, price in (("yes", live[0]), ("no", round(1.0 - live[2], 6))):
                share = share_with_order(
                    ladders[name], target_size, discount, price, args.size)
                score += share or 0.0
            # Every counting snapshot contributes 2.0 to the global
            # denominator, one per side, so our pool fraction is the mean of
            # the two shares (FINDINGS 9).
            numerator += score / 2.0
            per_snapshot.append(score / 2.0)

        # Walk the tape to the next snapshot and see whether we get hit.
        next_ts = series[index + 1]["ts"] if index + 1 < len(series) else ts
        if next_ts <= ts:
            continue
        lo = bisect.bisect_right(tape_ts, ts)
        hi = bisect.bisect_right(tape_ts, next_ts)
        hit = None
        for trade_ts, yes_price, traded, taker in tape[lo:hi]:
            # A resting YES bid is filled by a taker buying NO, and vice versa.
            for side in ("bid", "offer"):
                px = live[0] if side == "bid" else live[2]
                queue_index = 1 if side == "bid" else 3
                wants = "no" if side == "bid" else "yes"
                if taker != wants:
                    continue
                reaches = (yes_price <= px + 1e-9 if side == "bid"
                           else yes_price >= px - 1e-9)
                if not reaches:
                    continue
                remaining = traded
                eaten = min(live[queue_index], remaining)
                live[queue_index] -= eaten
                remaining -= eaten
                if remaining <= 1e-9:
                    continue
                if args.fill_model == "partial":
                    filled = min(args.size, remaining)
                else:
                    filled = args.size if remaining >= args.size - 1e-9 else 0.0
                if filled > 1e-9:
                    hit = (trade_ts, side, px, filled)
                    break
            if hit:
                break

        if hit is None:
            continue

        fill_ts, side, entry, filled = hit
        fill_count += 1
        direction = 1.0 if side == "bid" else -1.0
        mid = mid_after(series, index, fill_ts + args.markout_horizon,
                        args.tolerance)
        if mid is not None:
            markouts.append(direction * (mid - entry) * filled)
        flatten_until = fill_ts + flatten
        live = None

    return {
        "counting": counting,
        "resting": resting_counted,
        # Reward is a TIME INTEGRAL, so the mean over counting snapshots is
        # the correct statistic. sizing.py used the median, which is lower
        # whenever the share distribution is right-skewed -- and it is, because
        # a thin touch yields an enormous share (FINDINGS 4). Both are reported
        # so the gap is visible rather than absorbed silently.
        "fraction": numerator / counting if counting else 0.0,
        "fraction_median": (statistics.median(per_snapshot) * len(per_snapshot)
                            / counting) if per_snapshot and counting else 0.0,
        # What share of our whole reward score comes from our best 10% of
        # snapshots. A uniform market gives 10%. High values mean the mean is
        # carried by a handful of thin-touch snapshots -- exactly the books
        # where the static-book counterfactual is least trustworthy
        # (FINDINGS 4), and exactly the ones ranking-by-mean selects for.
        "concentration": _top_decile_share(per_snapshot),
        "fills": fill_count,
        "markouts": markouts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/capture.db")
    parser.add_argument("--size", type=float, default=25.0)
    parser.add_argument("--policy", choices=("touch", "inside"), default="touch")
    parser.add_argument("--fill-model", choices=("whole", "partial"),
                        default="whole",
                        help="'whole' matches markout.py for comparability;"
                             " 'partial' fills whatever volume reaches us,"
                             " which is what actually happens")
    parser.add_argument("--flatten-seconds", nargs="+", type=float,
                        default=[0.0, 300.0, 900.0, 3600.0],
                        help="how long quotes stay down after a fill; swept"
                             " because it is unmeasured")
    parser.add_argument("--markout-horizon", type=float, default=300.0)
    parser.add_argument("--tolerance", type=float, default=30.0)
    parser.add_argument("--capital", type=float, default=300.0)
    parser.add_argument("--crowded-threshold", type=float, default=0.25)
    parser.add_argument("--min-coverage", type=float, default=0.10)
    parser.add_argument("--max-concentration", type=float, default=0.30,
                        help="drop a market when its best 10%% of snapshots"
                             " carry more than this share of its total reward"
                             " score (uniform would be 0.10)")
    parser.add_argument("--statistic", choices=("mean", "median"),
                        default="mean",
                        help="how to reduce per-snapshot share to a period"
                             " fraction. 'mean' is correct for a time integral;"
                             " 'median' reproduces sizing.py and is lower")
    args = parser.parse_args()

    connection = sqlite3.connect(
        f"file:{Path(args.database).resolve()}?mode=ro", uri=True)
    programs = load_programs(connection)
    series = load_series(connection, programs)
    tape = load_tape(connection)
    print(f"markets with books and a program: {len(series)}")
    print(f"statistic {args.statistic}")
    print(f"size {args.size:g}   policy {args.policy}"
          f"   fill model {args.fill_model}"
          f"   markout +{args.markout_horizon:g}s\n")

    header = (f"{'flatten':>8s}{'markets':>9s}{'uptime':>8s}{'fills/day':>11s}"
              f"{'reward$':>10s}{'drag$':>9s}{'net$':>9s}{'collat$':>9s}"
              f"{'%/day':>8s}")
    print(header)
    print("-" * len(header))

    for flatten in args.flatten_seconds:
        rows = []
        for ticker, (snapshots, tick) in series.items():
            program = programs[ticker]
            try:
                target_size = float(program["target_size_fp"])
                discount = float(program["discount_factor_bps"]) / 10000.0
                pool = float(program["period_reward"]) / REWARD_SCALE
                start = parse_ts(program["start_date"])
                end = parse_ts(program["end_date"])
            except (KeyError, TypeError, ValueError):
                continue
            days = max((end - start) / 86400.0, 1e-9)
            if days < 1.0:          # a 1h program does not exist for a day
                continue
            observed = (snapshots[-1]["ts"] - snapshots[0]["ts"]) / 86400.0
            if observed / days < args.min_coverage:
                continue

            result = simulate(
                snapshots, tick, tape.get(ticker) or [],
                [t[0] for t in (tape.get(ticker) or [])],
                target_size, discount, args, flatten)
            if not result["counting"]:
                continue
            if result["fraction_median"] > args.crowded_threshold:
                continue        # we would BE the book; not a measurement
            # Ranking markets by their MEAN share systematically prefers the
            # ones whose mean is inflated by a minority of snapshots. Measured:
            # a typical market runs 16% in its top decile, but markets like
            # KXBILZERIANCONCEDE-SEP01 run 42% and carry a 5.2x mean/median
            # gap. Without this the selection picks its own outliers -- the
            # same failure that made sizing.py's first version report
            # $2,175/day.
            if result["concentration"] > args.max_concentration:
                continue

            payout = result[
                "fraction_median" if args.statistic == "median"
                else "fraction"] * pool
            if payout < MINIMUM_PAYOUT:
                continue        # forfeited, not deferred
            hours = (snapshots[-1]["ts"] - snapshots[0]["ts"]) / 3600.0
            rows.append({
                "ticker": ticker,
                "per_day": payout / days,
                "uptime": result["resting"] / result["counting"],
                "fills_per_day": (result["fills"] / hours * 24.0
                                  if hours > 0 else 0.0),
                "markout_per_fill": (statistics.fmean(result["markouts"])
                                     if result["markouts"] else 0.0),
                "collateral": args.size * 1.0,
            })

        if not rows:
            print(f"{flatten:8.0f}   no markets survive")
            continue

        rows.sort(key=lambda r: -r["per_day"])
        funded, used = [], 0.0
        for row in rows:
            if used + row["collateral"] > args.capital:
                continue
            used += row["collateral"]
            funded.append(row)

        reward = sum(r["per_day"] for r in funded)
        drag = sum(r["fills_per_day"] * r["markout_per_fill"] for r in funded)
        uptime = statistics.fmean([r["uptime"] for r in funded])
        fills = sum(r["fills_per_day"] for r in funded)
        print(f"{flatten:8.0f}{len(funded):9d}{100 * uptime:7.1f}%"
              f"{fills:11.1f}{reward:10.2f}{drag:9.2f}"
              f"{reward + drag:9.2f}{used:9.2f}"
              f"{100 * (reward + drag) / used if used else 0:7.2f}%")

    print()
    print("Reward and drag now come from ONE pass: a fill takes our quotes down")
    print("and the reward integral stops, so they can no longer be added under")
    print("contradictory assumptions. Still GROSS of fees (maker rate unmeasured,")
    print("FINDINGS 6e), still a static book, and shares are still extrapolated")
    print("from partial period coverage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
