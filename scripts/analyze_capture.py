"""Replay Kalshi's published reward formula over captured raw books.

Nothing here is inferred. Given a book and the program's `target_size_fp` and
`discount_factor_bps`, the CFTC filing of 2026-02-11 fully determines each
order's score, so this is arithmetic on recorded data rather than a model.

The one thing it cannot know is what our own resting order would have done to
other participants' behaviour. See `--size`: the counterfactual assumes the
rest of the book is unchanged, which is exactly the assumption that fails
hardest on the thinnest books. Markets where our size is a large share of the
denominator are reported separately for that reason.

    python -B scripts/analyze_capture.py --database data/capture.db --size 5
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path


def qualifying(ladder: list[tuple[float, float]], target: float,
               discount: float) -> tuple[float, float, bool]:
    """Return (reference_price, total_score, reached_target).

    Per the filing: the reference price is the highest bid. Walk down
    accumulating size; stop once cumulative size reaches the target. If the
    bids run out first, the whole side is cleared -- no order on it qualifies.
    """

    if not ladder:
        return 0.0, 0.0, False
    ladder = sorted(ladder, key=lambda level: -level[0])
    reference = ladder[0][0]
    cumulative = 0.0
    score = 0.0
    for price, size in ladder:
        cumulative += size
        ticks = round((reference - price) * 100)
        score += (discount ** ticks) * size
        if cumulative >= target:
            return reference, score, True
    return reference, score, False


def share_with_order(ladder: list[tuple[float, float]], target: float,
                     discount: float, price: float, size: float) -> float | None:
    """Our normalized share of a side after inserting our own resting order.

    Our size is added to the ladder before the walk, because it counts toward
    the target like anyone else's -- and because leaving it out makes the
    answer flip between 'worth placing' and 'worth keeping' on a book sitting
    near the boundary. liquidity-bot measured that as 1,817 place/cancel cycles
    in 5.7 hours at one price.
    """

    merged: dict[float, float] = defaultdict(float)
    for level_price, level_size in ladder:
        merged[round(level_price, 4)] += level_size
    merged[round(price, 4)] += size
    reference, total, reached = qualifying(
        list(merged.items()), target, discount)
    if not reached:
        return None
    ticks = round((reference - price) * 100)
    if ticks < 0:
        return None
    ours = (discount ** ticks) * size
    return ours / total if total > 0 else None


def load_programs(connection: sqlite3.Connection) -> dict[str, dict]:
    """Latest program row per ticker."""

    programs: dict[str, dict] = {}
    for (raw,) in connection.execute(
            "SELECT raw_json FROM programs ORDER BY fetched_at"):
        row = json.loads(raw)
        ticker = row.get("market_ticker")
        if ticker:
            programs[ticker] = row
    return programs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/capture.db")
    parser.add_argument("--size", type=float, default=5.0)
    parser.add_argument("--crowded-threshold", type=float, default=0.25,
                        help="flag a market untrusted when our size exceeds"
                             " this fraction of the denominator")
    args = parser.parse_args()

    connection = sqlite3.connect(
        f"file:{Path(args.database).resolve()}?mode=ro", uri=True)
    programs = load_programs(connection)

    snapshots = 0
    two_sided = 0
    # Keyed on (ticker, side). The two sides of one market routinely differ by
    # three orders of magnitude in denominator -- KXATPRETIRE-27DJO-Y measured
    # 1.1 on yes against ~990 on no -- so pooling them produces a median that
    # describes neither side and understates the crowding risk on the thin one.
    per_side: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"snaps": 0, "touch": [], "inside": [], "denominator": []})
    per_market_snaps: dict[str, int] = defaultdict(int)
    per_market_two: dict[str, int] = defaultdict(int)
    gains: list[float] = []

    for ticker, raw in connection.execute(
            "SELECT market_ticker, raw_json FROM books"
            " WHERE raw_json IS NOT NULL ORDER BY fetched_at"):
        program = programs.get(ticker)
        if not program:
            continue
        try:
            target = float(program["target_size_fp"])
            discount = float(program["discount_factor_bps"]) / 10000.0
        except (KeyError, TypeError, ValueError):
            continue
        book = json.loads(raw).get("orderbook_fp") or {}
        sides = {}
        for name in ("yes", "no"):
            sides[name] = [(float(p), float(s))
                           for p, s in (book.get(f"{name}_dollars") or [])]

        snapshots += 1
        per_market_snaps[ticker] += 1

        reached = {}
        for name, ladder in sides.items():
            _, _, ok = qualifying(ladder, target, discount)
            reached[name] = ok
        # The filing excludes the whole snapshot unless BOTH sides reach the
        # target. A side that qualifies alone earns nothing.
        if not (reached["yes"] and reached["no"]):
            continue
        two_sided += 1
        per_market_two[ticker] += 1

        for name, ladder in sides.items():
            if not ladder:
                continue
            stats = per_side[(ticker, name)]
            stats["snaps"] += 1
            touch = max(price for price, _ in ladder)
            _, denominator, _ = qualifying(ladder, target, discount)
            stats["denominator"].append(denominator)
            at_touch = share_with_order(
                ladder, target, discount, touch, args.size)
            inside = share_with_order(
                ladder, target, discount, round(touch + 0.01, 2), args.size)
            if at_touch:
                stats["touch"].append(at_touch)
            if inside:
                stats["inside"].append(inside)
            if at_touch and inside and at_touch > 0:
                gains.append(inside / at_touch)

    print(f"snapshots analysed      {snapshots}")
    if not snapshots:
        print("no usable snapshots")
        return 1
    print(f"two-sided (countable)   {two_sided}"
          f"  ({100.0 * two_sided / snapshots:.1f}%)")
    print(f"excluded, one-sided     {snapshots - two_sided}")
    if gains:
        print(f"\none-tick-inside gain    median {statistics.median(gains):.3f}x"
              f"   n={len(gains)}"
              f"   p10={statistics.quantiles(gains, n=10)[0]:.3f}"
              f"   p90={statistics.quantiles(gains, n=10)[-1]:.3f}"
              if len(gains) >= 10 else
              f"\none-tick-inside gain    median {statistics.median(gains):.3f}x  n={len(gains)}")

    print(f"\nper side (size={args.size:g}), ranked by share at the touch:")
    header = (f"{'ticker':32s}{'side':>5s}{'snaps':>6s}{'2side%':>8s}"
              f"{'denom':>10s}{'touch%':>8s}{'inside%':>9s}{'trust':>7s}")
    print(header)
    print("-" * len(header))
    rows = sorted(per_side.items(),
                  key=lambda kv: -(statistics.median(kv[1]["touch"])
                                   if kv[1]["touch"] else 0))
    untrusted = 0
    for (ticker, side), stats in rows:
        if not stats["touch"]:
            continue
        touch = statistics.median(stats["touch"]) * 100
        inside = (statistics.median(stats["inside"]) * 100
                  if stats["inside"] else float("nan"))
        denominator = statistics.median(stats["denominator"])
        two = 100.0 * per_market_two[ticker] / max(1, per_market_snaps[ticker])
        # Our own order dominating the denominator is precisely where the
        # static-book assumption fails, so say so rather than averaging it in.
        # The test is on the share we would hold, not on the raw denominator:
        # a side whose touch is one contract has a denominator near 1, and five
        # contracts there is not a measurement of anything but ourselves.
        crowded = (statistics.median(stats["touch"]) > args.crowded_threshold)
        if crowded:
            untrusted += 1
        print(f"{ticker[:32]:32s}{side:>5s}{stats['snaps']:6d}{two:7.0f}%"
              f"{denominator:10.1f}{touch:7.2f}%{inside:8.2f}%"
              f"{'NO' if crowded else 'ok':>7s}")
    if untrusted:
        print(f"\n{untrusted} side(s) marked NO: our {args.size:g} contracts would be"
              f" over {args.crowded_threshold:.0%} of the side. The static-book"
              f" assumption fails there -- we would BE the book, and the real"
              f" question becomes who trades against us, which this cannot see.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
