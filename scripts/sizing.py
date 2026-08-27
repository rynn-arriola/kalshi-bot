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

REWARD_SCALE = 10000.0


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_programs(connection: sqlite3.Connection) -> dict[str, dict]:
    programs: dict[str, dict] = {}
    for (raw,) in connection.execute(
            "SELECT raw_json FROM programs ORDER BY fetched_at"):
        row = json.loads(raw)
        if row.get("market_ticker"):
            programs[row["market_ticker"]] = row
    return programs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/capture.db")
    parser.add_argument("--size", type=float, default=5.0)
    parser.add_argument(
        "--reward-rule", choices=[mode.value for mode in RewardRuleMode],
        default=DEFAULT_RULE_MODE.value,
        help="versioned filed reward calculation; July is current")
    parser.add_argument(
        "--policy", choices=("polymarket-current", "touch", "inside"),
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
    args = parser.parse_args()

    connection = sqlite3.connect(
        f"file:{Path(args.database).resolve()}?mode=ro", uri=True)
    programs = load_programs(connection)

    counted: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    shares: dict[str, list[float]] = defaultdict(list)
    collateral: dict[str, list[float]] = defaultdict(list)
    span: dict[str, list[datetime]] = defaultdict(list)

    for ticker, fetched_at, raw in connection.execute(
            "SELECT market_ticker, fetched_at, raw_json FROM books"
            " WHERE raw_json IS NOT NULL ORDER BY fetched_at"):
        program = programs.get(ticker)
        if not program:
            continue
        try:
            target = float(program["target_size_fp"])
            discount = float(program["discount_factor_bps"]) / 10000.0
        except (KeyError, TypeError, ValueError):
            continue
        book = (json.loads(raw) or {}).get("orderbook_fp") or {}
        ladders = {
            name: [(float(p), float(s))
                   for p, s in (book.get(f"{name}_dollars") or [])]
            for name in ("yes", "no")}
        total[ticker] += 1
        if not all(ladders[name] for name in ("yes", "no")):
            continue
        yes_touch = max(price for price, _ in ladders["yes"])
        no_touch = max(price for price, _ in ladders["no"])
        if args.policy == "polymarket-current":
            quotes = polymarket_entry_quotes(
                yes_touch, round(1.0 - no_touch, 6), 0.01)
            if quotes is None:
                continue
            order_prices = {
                "yes": quotes.yes_bid,
                "no": round(1.0 - quotes.yes_offer, 6),
            }
        else:
            order_prices = {}
            for name, touch in (("yes", yes_touch), ("no", no_touch)):
                candidate = (round(touch + 0.01, 2)
                             if args.policy == "inside" else touch)
                order_prices[name] = touch if candidate >= 1.0 else candidate

        # Snapshot exclusion is evaluated after inserting our hypothetical
        # orders. Usually size 10 is far below Target Size, but near the
        # boundary it can be the quantity that makes a side count.
        if not all(qualifying(
                ladders[name] + [(order_prices[name], args.size)],
                target, discount, mode=args.reward_rule)[2]
                   for name in ("yes", "no")):
            continue
        counted[ticker] += 1

        snapshot = []
        cost = 0.0
        for name in ("yes", "no"):
            price = order_prices[name]
            share = share_with_order(
                ladders[name], target, discount, price, args.size,
                mode=args.reward_rule)
            snapshot.append(share or 0.0)
            cost += price * args.size
        # SnapshotScore is the SUM of the two normalized shares and every
        # counting snapshot contributes 2.0 to the denominator, so our
        # fraction of the pool is their mean.
        shares[ticker].append(sum(snapshot) / 2.0)
        collateral[ticker].append(cost)
        span[ticker].append(parse_ts(fetched_at))

    rows = []
    for ticker, values in shares.items():
        if not values:
            continue
        program = programs[ticker]
        pool = float(program["period_reward"]) / REWARD_SCALE
        days = max(
            (parse_ts(program["end_date"])
             - parse_ts(program["start_date"])).total_seconds() / 86400.0,
            1e-9)
        fraction = statistics.median(values)
        payout_result = calculate_payout(
            fraction, pool, counted[ticker], total[ticker],
            mode=args.reward_rule)
        raw_payout = float(payout_result.raw_payout)
        payable_payout = float(payout_result.payable_payout)
        observed = span[ticker]
        # How much of the program period we actually watched. A share measured
        # over twenty minutes says nothing about a 1.8-day period: it assumes
        # no competitor ever arrives, on a market that may have opened
        # moments ago. This is the term that made an earlier version of this
        # script report 308%/day.
        coverage = ((observed[-1] - observed[0]).total_seconds() / 86400.0
                    / days) if len(observed) > 1 else 0.0
        rows.append({
            "ticker": ticker,
            "snaps": len(values),
            "two_sided": 100.0 * counted[ticker] / max(1, total[ticker]),
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
            "collateral": statistics.median(collateral[ticker]),
            # Where our own size dominates the denominator we are not measuring
            # the market, we are measuring ourselves -- the same guard
            # analyze_capture.py applies, for the same reason.
            "crowded": fraction > args.crowded_threshold,
            "coverage": coverage,
        })
    if not rows:
        print("no markets with both a program and a qualifying book")
        return 1
    short = [r for r in rows if r["per_day"] is None]
    crowded = [r for r in rows if r["per_day"] is not None and r["crowded"]]
    thin = [r for r in rows
            if r["per_day"] is not None and not r["crowded"]
            and r["coverage"] < args.min_coverage]
    sustained = [r for r in rows
                 if r["per_day"] is not None and not r["crowded"]
                 and r["coverage"] >= args.min_coverage]
    sustained.sort(key=lambda r: -r["per_day"])

    print(rule_banner(args.reward_rule))
    if args.policy == "polymarket-current":
        print(policy_banner())
    print(f"policy {args.policy}   size {args.size:g}   "
          f"markets with usable data: {len(rows)}")
    print(f"minimum payout {float(MINIMUM_PAYOUT):.2f} per program period, "
          "below which nothing is paid\n")

    print(f"excluded: {len(crowded)} crowded "
          f"(our {args.size:g} would be >{args.crowded_threshold:.0%} of the"
          f" score), {len(short)} shorter than a day,"
          f" {len(thin)} observed under {args.min_coverage:.0%} of their"
          f" period\n")

    header = (f"{'ticker':<38s}{'snaps':>6s}{'cov':>5s}{'pool$':>9s}"
              f"{'days':>7s}{'share':>8s}{'raw$':>9s}{'pay$':>9s}"
              f"{'$/day':>8s}{'paid':>6s}")
    print(header)
    print("-" * len(header))
    for row in sustained[:20]:
        print(f"{row['ticker'][:38]:<38s}{row['snaps']:6d}"
              f"{100 * row['coverage']:4.0f}%{row['pool']:9.2f}{row['days']:7.1f}"
              f"{100 * row['fraction']:7.2f}%{row['payout']:9.2f}"
              f"{row['payable']:9.2f}{row['per_day']:8.3f}"
              f"{'yes' if row['paid'] else 'NO':>6s}")
    if len(sustained) > 20:
        print(f"... and {len(sustained) - 20} more")

    top = sustained[:args.markets]
    top_paid = [r for r in top if r["paid"]]

    print(f"\n=== if we quoted the best {min(args.markets, len(sustained))}"
          f" trustworthy markets ===")
    print(f"  markets clearing the $1 minimum   {len(top_paid)} of {len(top)}")
    print(f"  modeled reward/day before minimum "
          f"${sum(r['raw_per_day'] for r in top):.3f}")
    print(f"  reward per day, after $1 minimum  "
          f"${sum(r['per_day'] for r in top_paid):.3f}")
    print(f"  collateral required               "
          f"${sum(r['collateral'] for r in top):.2f}")
    funded = used = 0.0
    count = 0
    for row in top_paid:
        if used + row["collateral"] > args.capital:
            continue
        used += row["collateral"]
        funded += row["per_day"]
        count += 1
    print(f"\n=== what ${args.capital:.2f} actually funds ===")
    print(f"  markets                           {count}")
    print(f"  collateral deployed               ${used:.2f}")
    print(f"  reward per day                    ${funded:.3f}")
    if used > 0:
        print(f"  return on deployed capital        "
              f"{100.0 * funded / used:.2f}% / day")
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
