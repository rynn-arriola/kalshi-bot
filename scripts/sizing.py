"""Modeled reward-only payout from captured Kalshi books.

This is not paid reward and not net P&L. It replays a named filed rule, inserts
the hypothetical orders into each ladder, and applies excluded-snapshot pool
scaling, cent flooring, and the per-program $1 minimum. ``period_reward`` scale
is strongly corroborated but still awaits reconciliation to an actual payout.

Under the current July rule, Reference Price is the level where cumulative
size first reaches one fifth of Target Size; better prices receive full weight.
The normalized score on each side is our discounted score divided by all
qualifying score on that side.

Two consequences that drive the answer and are easy to miss:

1. Normalized shares on a side sum to 1.00 across all participants, so every
   counting snapshot contributes exactly 2.0 to the denominator -- one per
   side. **Our fraction of the pool is therefore the mean of our two side
   shares.** Quoting one side only halves it.
2. A snapshot excluded for one-sidedness leaves the score numerator and
   denominator, and under the current July rule also reduces the payable pool
   by the non-excluded fraction.

    python -B scripts/sizing.py --size 10 --policy polymarket-current
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_capture import qualifying, share_with_order  # noqa: E402
from reward_rules import (  # noqa: E402
    DEFAULT_RULE_MODE,
    MINIMUM_PAYOUT,
    RewardRuleMode,
    calculate_payout,
    rule_banner,
)
from strategy_policy import (  # noqa: E402
    policy_banner,
    polymarket_entry_quotes,
)
from program_timeline import ProgramTimeline  # noqa: E402
from reference_policy import (  # noqa: E402
    reference_order_prices, snapshot_tick, tick_sizes_from_market_meta,
)

REWARD_SCALE = 10000.0


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def time_aligned_portfolio(
    rows: list[dict], capture_start: datetime, capture_end: datetime,
    *, markets: int, capital: float,
) -> dict:
    """Integrate a hindsight-ranked portfolio on the actual capture clock.

    Program periods from different dates must never be added as if they were
    simultaneous.  At each start/end boundary, this groups overlapping reward
    programs by ticker (one quote can score in each), then funds the strongest
    current tickers subject to market and collateral limits.
    """
    boundaries = {capture_start, capture_end}
    eligible = []
    for row in rows:
        start = max(capture_start, row["start"])
        end = min(capture_end, row["end"])
        if start >= end or not row["paid"]:
            continue
        item = dict(row, active_start=start, active_end=end)
        eligible.append(item)
        boundaries.update((start, end))
    points = sorted(boundaries)
    reward_dollars = collateral_days = market_days = 0.0
    schedule = []
    for left, right in zip(points, points[1:]):
        days = (right - left).total_seconds() / 86400.0
        if days <= 0:
            continue
        by_ticker: dict[str, dict] = {}
        for row in eligible:
            if not (row["active_start"] <= left < row["active_end"]):
                continue
            item = by_ticker.setdefault(row["ticker"], {
                "ticker": row["ticker"], "per_day": 0.0,
                "collateral": row["collateral"], "programs": [],
            })
            item["per_day"] += row["per_day"]
            item["collateral"] = max(item["collateral"], row["collateral"])
            item["programs"].append({
                "id": row["program_id"],
                "target_size": row["target_size"],
                "discount_factor": row["discount_factor"],
            })
        for item in by_ticker.values():
            item["programs"].sort(key=lambda program: program["id"])
        ranked = sorted(
            by_ticker.values(),
            key=lambda item: (
                item["per_day"] / max(item["collateral"], 1e-9),
                item["per_day"],
            ),
            reverse=True,
        )
        selected, used = [], 0.0
        for item in ranked:
            if len(selected) >= markets:
                break
            if used + item["collateral"] > capital + 1e-9:
                continue
            selected.append(item)
            used += item["collateral"]
        reward_dollars += sum(item["per_day"] for item in selected) * days
        collateral_days += used * days
        market_days += len(selected) * days
        if selected:
            items = sorted(selected, key=lambda item: item["ticker"])
            tickers = [item["ticker"] for item in items]
            if schedule and schedule[-1]["items"] == items \
                    and schedule[-1]["end"] == left:
                schedule[-1]["end"] = right
            else:
                schedule.append({
                    "start": left, "end": right,
                    "tickers": tickers, "items": items,
                })
    capture_days = max((capture_end - capture_start).total_seconds() / 86400.0, 1e-9)
    return {
        "capture_days": capture_days,
        "reward": reward_dollars,
        "reward_per_day": reward_dollars / capture_days,
        "average_collateral": collateral_days / capture_days,
        "average_markets": market_days / capture_days,
        "schedule": schedule,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/capture.db")
    parser.add_argument("--size", type=float, default=5.0)
    parser.add_argument(
        "--reward-rule", choices=[mode.value for mode in RewardRuleMode],
        default=DEFAULT_RULE_MODE.value,
        help="versioned filed reward calculation; July is current")
    parser.add_argument(
        "--policy", choices=(
            "polymarket-current", "touch", "inside",
            "reference", "reference-minus-one"),
        default="polymarket-current",
        help="current Polymarket entry pricing is the transfer default")
    parser.add_argument("--markets", type=int, default=40,
                        help="how many markets we could quote at once")
    parser.add_argument("--capital", type=float, default=22.64,
                        help="account balance available, for the funded view")
    parser.add_argument("--crowded-threshold", type=float, default=0.25,
                        help="drop a market when our own size exceeds this"
                             " share of the qualifying score: there the static"
                             " book assumption fails and we are measuring"
                             " ourselves, not the market")
    parser.add_argument("--min-coverage", type=float, default=0.10,
                        help="drop a market unless we observed at least this"
                             " fraction of its program period")
    parser.add_argument("--min-snapshots-per-day", type=float, default=100.0,
                        help="drop sparse candidate-scan observations; held"
                             " markets sampled each minute are roughly 1440/day")
    parser.add_argument("--schedule-output",
                        help="optional JSON output for same-clock fill/exit replay")
    args = parser.parse_args()

    connection = sqlite3.connect(
        f"file:{Path(args.database).resolve()}?mode=ro", uri=True)
    capture_bounds = connection.execute(
        "SELECT MIN(fetched_at), MAX(fetched_at) FROM books"
    ).fetchone()
    capture_start, capture_end = map(parse_ts, capture_bounds)
    timeline = ProgramTimeline.from_connection(connection)
    metadata_ticks = tick_sizes_from_market_meta(connection)

    counted: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    shares: dict[str, list[float]] = defaultdict(list)
    collateral: dict[str, list[float]] = defaultdict(list)
    span: dict[str, list[datetime]] = defaultdict(list)
    terms_by_id = {}

    for ticker, fetched_at, raw in connection.execute(
            "SELECT market_ticker, fetched_at, raw_json FROM books"
            " WHERE raw_json IS NOT NULL ORDER BY fetched_at"):
        timestamp = parse_ts(fetched_at)
        active_programs = timeline.active_at(ticker, timestamp)
        if not active_programs:
            continue
        book = (json.loads(raw) or {}).get("orderbook_fp") or {}
        ladders = {
            name: [(float(p), float(s))
                   for p, s in (book.get(f"{name}_dollars") or [])]
            for name in ("yes", "no")}
        for program in active_programs:
            key = program.program_id
            terms_by_id[key] = program
            total[key] += 1
            span[key].append(timestamp)
        if not all(ladders[name] for name in ("yes", "no")):
            continue
        tick = metadata_ticks.get(ticker) or snapshot_tick(ladders)
        yes_touch = max(price for price, _ in ladders["yes"])
        no_touch = max(price for price, _ in ladders["no"])
        order_prices = None
        if args.policy == "polymarket-current":
            quotes = polymarket_entry_quotes(
                yes_touch, round(1.0 - no_touch, 6), tick)
            if quotes is None:
                continue
            order_prices = {
                "yes": quotes.yes_bid,
                "no": round(1.0 - quotes.yes_offer, 6),
            }
        elif args.policy in {"touch", "inside"}:
            order_prices = {}
            for name, touch in (("yes", yes_touch), ("no", no_touch)):
                candidate = (round(touch + tick, 6)
                             if args.policy == "inside" else touch)
                order_prices[name] = touch if candidate >= 1.0 else candidate

        for program in active_programs:
            key = program.program_id
            target = program.target_size
            discount = program.discount_factor
            if args.policy in {"reference", "reference-minus-one"}:
                order_prices = reference_order_prices(
                    ladders, target, discount, reward_rule=args.reward_rule,
                    tick=tick,
                    behind_ticks=1 if args.policy == "reference-minus-one" else 0)
                if order_prices is None:
                    continue
            assert order_prices is not None
            # Snapshot exclusion is evaluated after inserting our hypothetical
            # orders. Usually size 10 is far below Target Size, but near the
            # boundary it can be the quantity that makes a side count.
            if not all(qualifying(
                    ladders[name] + [(order_prices[name], args.size)],
                    target, discount, mode=args.reward_rule,
                    tick_size=tick)[2]
                       for name in ("yes", "no")):
                continue
            counted[key] += 1

            snapshot = []
            cost = 0.0
            for name in ("yes", "no"):
                price = order_prices[name]
                share = share_with_order(
                    ladders[name], target, discount, price, args.size,
                    mode=args.reward_rule, tick_size=tick)
                snapshot.append(share or 0.0)
                cost += price * args.size
            # SnapshotScore is the SUM of the two normalized shares and every
            # counting snapshot contributes 2.0 to the denominator, so our
            # fraction of the pool is their mean.
            shares[key].append(sum(snapshot) / 2.0)
            collateral[key].append(cost)

    rows = []
    for key, values in shares.items():
        if not values:
            continue
        program = terms_by_id[key]
        pool = program.period_reward / REWARD_SCALE
        days = max(program.duration_days, 1e-9)
        # Reward is a time integral.  The mean among counting snapshots and the
        # counted/total multiplier below preserve that clock.  The old median
        # was a descriptive statistic and understated right-skewed periods.
        fraction = statistics.mean(values)
        payout_result = calculate_payout(
            fraction, pool, counted[key], total[key],
            mode=args.reward_rule)
        raw_payout = float(payout_result.raw_payout)
        payable_payout = float(payout_result.payable_payout)
        observed = span[key]
        # How much of the program period we actually watched. A share measured
        # over twenty minutes says nothing about a 1.8-day period: it assumes
        # no competitor ever arrives, on a market that may have opened
        # moments ago. This is the term that made an earlier version of this
        # script report 308%/day.
        coverage = ((observed[-1] - observed[0]).total_seconds() / 86400.0
                    / days) if len(observed) > 1 else 0.0
        observed_days = max(
            (observed[-1] - observed[0]).total_seconds() / 86400.0, 1e-9)
        snapshots_per_day = total[key] / observed_days
        rows.append({
            "ticker": program.market_ticker,
            "program_id": program.program_id,
            "target_size": program.target_size,
            "discount_factor": program.discount_factor,
            "start": program.start,
            "end": program.end,
            "snaps": len(values),
            "two_sided": 100.0 * counted[key] / max(1, total[key]),
            "pool": pool,
            "days": days,
            "fraction": fraction,
            "payout": raw_payout,
            "payable": payable_payout,
            # Only meaningful for a program that lasts at least a day. A
            # one-hour index market has a $285 pool, which annualizes to
            # $7,105/day and is nonsense: the market does not exist for a day.
            "per_day": payable_payout / days if days >= 1.0 else None,
            "raw_per_day": raw_payout / days if days >= 1.0 else None,
            "paid": payout_result.clears_minimum,
            "collateral": statistics.median(collateral[key]),
            # Where our own size dominates the denominator we are not measuring
            # the market, we are measuring ourselves -- the same guard
            # analyze_capture.py applies, for the same reason.
            "crowded": fraction > args.crowded_threshold,
            "coverage": coverage,
            "snapshots_per_day": snapshots_per_day,
        })
    if not rows:
        print("no markets with both a program and a qualifying book")
        return 1
    short = [r for r in rows if r["per_day"] is None]
    crowded = [r for r in rows if r["per_day"] is not None and r["crowded"]]
    thin = [r for r in rows
            if r["per_day"] is not None and not r["crowded"]
            and r["coverage"] < args.min_coverage]
    sparse = [r for r in rows
              if r["per_day"] is not None and not r["crowded"]
              and r["coverage"] >= args.min_coverage
              and r["snapshots_per_day"] < args.min_snapshots_per_day]
    sustained = [r for r in rows
                 if r["per_day"] is not None and not r["crowded"]
                 and r["coverage"] >= args.min_coverage
                 and r["snapshots_per_day"] >= args.min_snapshots_per_day]
    sustained.sort(key=lambda r: -r["per_day"])

    print(rule_banner(args.reward_rule))
    if args.policy == "polymarket-current":
        print(policy_banner())
    print(f"policy {args.policy}   size {args.size:g}   "
          f"markets with usable data: {len(rows)}")
    print(f"temporal program matching: {timeline.stable_program_count} stable"
          f" programs; {len(timeline.unstable_ids)} edited programs and"
          f" {timeline.invalid_rows} invalid rows excluded")
    print(f"minimum payout {float(MINIMUM_PAYOUT):.2f} per program period, "
          "below which nothing is paid\n")

    print(f"excluded: {len(crowded)} crowded "
          f"(our {args.size:g} would be >{args.crowded_threshold:.0%} of the"
          f" score), {len(short)} shorter than a day,"
          f" {len(thin)} observed under {args.min_coverage:.0%} of their"
          f" period, {len(sparse)} under {args.min_snapshots_per_day:g}"
          f" snapshots/day\n")

    header = (f"{'ticker':<38s}{'snaps':>6s}{'/day':>6s}{'cov':>5s}{'pool$':>9s}"
              f"{'days':>7s}{'share':>8s}{'raw$':>9s}{'pay$':>9s}"
              f"{'$/day':>8s}{'paid':>6s}")
    print(header)
    print("-" * len(header))
    for row in sustained[:20]:
        print(f"{row['ticker'][:38]:<38s}{row['snaps']:6d}"
              f"{row['snapshots_per_day']:6.0f}"
              f"{100 * row['coverage']:4.0f}%{row['pool']:9.2f}{row['days']:7.1f}"
              f"{100 * row['fraction']:7.2f}%{row['payout']:9.2f}"
              f"{row['payable']:9.2f}{row['per_day']:8.3f}"
              f"{'yes' if row['paid'] else 'NO':>6s}")
    if len(sustained) > 20:
        print(f"... and {len(sustained) - 20} more")

    portfolio = time_aligned_portfolio(
        sustained, capture_start, capture_end,
        markets=args.markets, capital=args.capital)
    print(f"\n=== time-aligned hindsight portfolio ===")
    print(f"  capture window                    {capture_start.isoformat()} to")
    print(f"                                    {capture_end.isoformat()}")
    print(f"  capture duration                  {portfolio['capture_days']:.2f} days")
    print(f"  average funded markets            {portfolio['average_markets']:.1f}")
    print(f"  average collateral                ${portfolio['average_collateral']:.2f}")
    print(f"  modeled reward over capture       ${portfolio['reward']:.2f}")
    print(f"  modeled reward/day                ${portfolio['reward_per_day']:.3f}")
    if portfolio["average_collateral"] > 0:
        print(f"  reward / average collateral       "
              f"{100 * portfolio['reward_per_day'] / portfolio['average_collateral']:.2f}% / day")
    print("  selection                         hindsight-ranked; optimistic, not live P&L")
    if args.schedule_output:
        payload = {
            "database": str(Path(args.database).resolve()),
            "size": args.size,
            "policy": args.policy,
            "reward_rule": args.reward_rule,
            "min_coverage": args.min_coverage,
            "min_snapshots_per_day": args.min_snapshots_per_day,
            "modeled_reward": portfolio["reward"],
            "modeled_reward_per_day": portfolio["reward_per_day"],
            "capture_days": portfolio["capture_days"],
            "average_collateral": portfolio["average_collateral"],
            "schedule": [
                {"start": item["start"].isoformat(),
                 "end": item["end"].isoformat(),
                 "tickers": item["tickers"], "items": item["items"]}
                for item in portfolio["schedule"]
            ],
        }
        Path(args.schedule_output).write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  schedule                          {args.schedule_output}")
    if sustained:
        print(f"\n  median share per side pair        "
              f"{100 * statistics.median([r['fraction'] for r in sustained]):.2f}%")
        print(f"  median pool                       "
              f"${statistics.median([r['pool'] for r in sustained]):.2f}"
              f" over {statistics.median([r['days'] for r in sustained]):.1f} days")
        print(f"  median payout per period          "
              f"${statistics.median([r['payout'] for r in sustained]):.2f}"
              f"   ({sum(1 for r in sustained if r['paid'])} of"
              f" {len(sustained)} clear $1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
