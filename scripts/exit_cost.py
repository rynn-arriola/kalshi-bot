"""What it actually costs to get flat after a fill.

Every economics number in this project so far charges a fill its **markout** --
where the mid went afterwards. That is a proxy for adverse selection, not a
realised cost. `net_sizing.py` takes our quotes down for `--flatten-seconds`
and then assumes we are flat, at no exit cost whatsoever.

The reference implementation says that omission is the whole story. Measured
over 66 of its markets (`docs/REFERENCE_CRITIQUE.md` 4e):

    exit crossed (TAKER)   55 markets   -85.19   median -1.21
    exit passive (MAKER)   11 markets    -9.67   median -0.31

A crossed exit loses four times what a passive one does and there are five
times as many, and that alone turned a +$17.24 day into -$7.33.

Kalshi makes crossing worse. The taker fee at 50c is 1.75c against a 1c tick,
so crossing costs about 2.75c -- roughly 3x the naive spread (FINDINGS 6c).
Against that, our books are quiet: 64% of hours see no trade at all, which is
what makes a passive exit hard to complete. **Rare fills that are expensive to
exit is not obviously better than frequent fills that are cheap to exit**, and
`docs/REFERENCE_CRITIQUE.md` calls that the sharpest open question we have.
This script answers it.

Two exit paths are simulated for every fill:

  PASSIVE   rest a reducing order and wait up to `--exit-deadline`. Priced by
            the reference's `exit_quote_price` rule: step one tick inside the
            touch, but only while the improved price still does not lose money.
            Queue position is behind the displayed depth, as for any join.
  CROSSED   walk the opposite ladder for our whole size and pay the taker fee
            on the volume-weighted price. This is what happens when the
            deadline expires, and it is the path the reference ends up on 73%
            of the time.

Both are charged against the entry price, so the output is a realised P&L per
exit rather than a markout.

    python -B scripts/exit_cost.py --size 25
    python -B scripts/exit_cost.py --size 25 --exit-deadline 1800
"""

from __future__ import annotations

import argparse
import bisect
import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from net_sizing import (  # noqa: E402
    load_programs, load_series, load_tape, target_quote,
)

TAKER_RATE = 0.07


def taker_fee(contracts: float, price: float) -> float:
    """Kalshi's taker fee, proven against two real fills (FINDINGS 6e).

        fee = ceil(0.07 x C x P x (1-P) x 10_000) / 10_000

    The ceiling is at four decimal places -- one hundredth of a cent -- not at
    whole cents. An earlier note in FINDINGS said whole cents and was wrong in
    the pessimistic direction. The curve peaks at P=0.50 and falls toward the
    tails, so a tail-priced market is fee-advantaged; charging a representative
    0.50 here would overstate cost about 6x (BUGFIXES, the fee-pricing bug).
    """

    if contracts <= 0:
        return 0.0
    price = min(max(price, 0.0), 1.0)
    return math.ceil(TAKER_RATE * contracts * price * (1.0 - price)
                     * 10_000.0) / 10_000.0


def walk_for_size(levels: list[tuple[float, float]], size: float,
                  descending: bool) -> tuple[float, float] | None:
    """Volume-weighted price to trade `size` against a ladder, and how much.

    Returns (vwap, filled). `filled` is less than `size` when the book is too
    thin to absorb us -- which is not an edge case on these markets, it is the
    thing most likely to make an exit expensive, so it is reported rather than
    treated as a full fill.
    """

    ordered = sorted(levels, key=lambda level: -level[0] if descending
                     else level[0])
    remaining = size
    notional = 0.0
    for price, available in ordered:
        take = min(remaining, available)
        if take <= 0:
            continue
        notional += take * price
        remaining -= take
        if remaining <= 1e-9:
            break
    filled = size - remaining
    if filled <= 1e-9:
        return None
    return notional / filled, filled


def crossed_exit(snapshot: dict, direction: float, size: float,
                 ) -> tuple[float, float, float] | None:
    """Cost of crossing out now. Returns (vwap, filled, fee).

    Long YES exits by SELLING yes -- hitting the yes bid ladder from the top
    down. Short YES exits by BUYING yes, which on Kalshi is executed against
    the no bids: a no bid at 0.95 is an offer to sell yes at 0.05, so the yes
    ask ladder is `1 - no_bid`, ascending. Never derive this from a side field
    (FINDINGS 6f).
    """

    ladders = snapshot["ladders"]
    if direction > 0:
        result = walk_for_size(ladders["yes"], size, descending=True)
    else:
        asks = [(round(1.0 - price, 4), sz) for price, sz in ladders["no"]]
        result = walk_for_size(asks, size, descending=False)
    if result is None:
        return None
    vwap, filled = result
    return vwap, filled, taker_fee(filled, vwap)


def exit_quote_price(snapshot: dict, direction: float, entry: float,
                     tick: float) -> float:
    """Where a reducing order rests.

    The reference's rule, added after measuring that exits ending in a taker
    cross were -$30.22 across 28 markets, about 76% of all its real recorded
    losses: step one tick inside the touch, but only while the improved price
    still does not lose money against entry. Crossing costs ~3x more here, so
    the rule is worth more on Kalshi, not less.
    """

    if direction > 0:                      # long: we are selling, rest at ask
        touch = snapshot["offer"]
        improved = round(touch - tick, 6)
        return improved if improved > entry else touch
    touch = snapshot["bid"]                # short: we are buying, rest at bid
    improved = round(touch + tick, 6)
    return improved if improved < entry else touch


def passive_exit(series: list[dict], index: int, tape: list[tuple],
                 tape_ts: list[float], fill_ts: float, direction: float,
                 entry: float, size: float, tick: float, deadline: float,
                 ) -> tuple[float, float] | None:
    """Try to rest out of the position. Returns (exit_price, when) or None.

    A reducing order is filled by the opposite taker to the one that hit us,
    and it joins the back of whatever is displayed at its price.
    """

    snapshot = series[index]
    price = exit_quote_price(snapshot, direction, entry, tick)
    queue = (snapshot["offer_size"] if direction > 0 else snapshot["bid_size"])
    wants = "yes" if direction > 0 else "no"
    lo = bisect.bisect_right(tape_ts, fill_ts)
    hi = bisect.bisect_right(tape_ts, fill_ts + deadline)
    cumulative = 0.0
    for trade_ts, yes_price, traded, taker in tape[lo:hi]:
        if taker != wants:
            continue
        reaches = (yes_price >= price - 1e-9 if direction > 0
                   else yes_price <= price + 1e-9)
        if not reaches:
            continue
        cumulative += traded
        if cumulative >= queue + size - 1e-9:
            return price, trade_ts
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/capture.db")
    parser.add_argument("--size", type=float, default=25.0)
    parser.add_argument("--policy", choices=("touch", "inside"), default="touch")
    parser.add_argument("--exit-deadline", nargs="+", type=float,
                        default=[300.0, 900.0, 1800.0, 3600.0],
                        help="how long a passive reducer is given before we"
                             " cross out; swept because the inventory clock is"
                             " exactly what this measurement should set")
    args = parser.parse_args()

    connection = sqlite3.connect(
        f"file:{Path(args.database).resolve()}?mode=ro", uri=True)
    programs = load_programs(connection)
    series_by_market = load_series(connection, programs)
    tape_by_market = load_tape(connection)

    # Collect fills once; the exit policy is what varies across the sweep.
    fills = []
    for ticker, (series, tick) in series_by_market.items():
        tape = tape_by_market.get(ticker) or []
        tape_ts = [row[0] for row in tape]
        for index, snapshot in enumerate(series):
            if index + 1 >= len(series):
                break
            want_bid, bid_depth, want_offer, offer_depth = target_quote(
                args.policy, snapshot, tick)
            if want_offer - want_bid < 1e-9:
                continue
            lo = bisect.bisect_right(tape_ts, snapshot["ts"])
            hi = bisect.bisect_right(tape_ts, series[index + 1]["ts"])
            for trade_ts, yes_price, traded, taker in tape[lo:hi]:
                if taker == "no" and yes_price <= want_bid + 1e-9 \
                        and traded >= bid_depth + args.size:
                    fills.append((ticker, index, trade_ts, 1.0, want_bid, tick))
                    break
                if taker == "yes" and yes_price >= want_offer - 1e-9 \
                        and traded >= offer_depth + args.size:
                    fills.append((ticker, index, trade_ts, -1.0, want_offer, tick))
                    break

    print(f"size {args.size:g}   policy {args.policy}")
    print(f"simulated fills to exit: {len(fills)}\n")
    if not fills:
        print("no fills; nothing to measure")
        return 1

    header = (f"{'deadline':>9s}{'n':>6s}{'passive':>9s}{'crossed':>9s}"
              f"{'thin':>6s}{'passive $':>11s}{'crossed $':>11s}{'blended $':>11s}")
    print(header)
    print("-" * len(header))

    for deadline in args.exit_deadline:
        passive_pnl, crossed_pnl, blended = [], [], []
        thin = 0
        for ticker, index, fill_ts, direction, entry, tick in fills:
            series, _ = series_by_market[ticker]
            tape = tape_by_market.get(ticker) or []
            tape_ts = [row[0] for row in tape]
            rested = passive_exit(series, index, tape, tape_ts, fill_ts,
                                  direction, entry, args.size, tick, deadline)
            if rested is not None:
                price, _ = rested
                value = direction * (price - entry) * args.size
                passive_pnl.append(value)
                blended.append(value)
                continue
            # Deadline expired: cross out against the book as it stands.
            crossed = crossed_exit(series[index], direction, args.size)
            if crossed is None:
                continue
            vwap, filled, fee = crossed
            if filled < args.size - 1e-9:
                thin += 1
            value = direction * (vwap - entry) * filled - fee
            crossed_pnl.append(value)
            blended.append(value)

        total = len(passive_pnl) + len(crossed_pnl)
        if not total:
            continue
        print(f"{deadline:9.0f}{total:6d}"
              f"{100.0 * len(passive_pnl) / total:8.0f}%"
              f"{100.0 * len(crossed_pnl) / total:8.0f}%"
              f"{thin:6d}"
              f"{statistics.median(passive_pnl) if passive_pnl else 0.0:11.4f}"
              f"{statistics.median(crossed_pnl) if crossed_pnl else 0.0:11.4f}"
              f"{statistics.median(blended) if blended else 0.0:11.4f}")

    print()
    print("passive/crossed are the share of exits taking each path; $ columns are")
    print("MEDIAN realised P&L per exit, entry to exit, taker fee charged at the")
    print("actual VWAP. 'thin' counts exits where the book could not absorb our")
    print("whole size -- those are understated, since the remainder still has to")
    print("be worked and this charges it nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
