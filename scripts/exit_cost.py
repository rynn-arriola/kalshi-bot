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
This script answers it using the first usable book *at or after* the intended
exit time.  An earlier implementation accidentally crossed against the entry
book after waiting, which erased the intervening adverse price move.

Four terminal outcomes are reported for every simulated fill:

  PASSIVE   rest a reducing order and wait up to `--exit-deadline`. Priced by
            the reference's `exit_quote_price` rule: step one tick inside the
            touch, but only while the improved price still does not lose money.
            Queue position is behind the displayed depth, as for any join.
  CROSSED   walk the opposite ladder for our whole size and pay the taker fee
            on the volume-weighted price. This is what happens when the
            deadline expires, and it is the path the reference ends up on 73%
            of the time.
  SETTLED   use a recorded YES/NO result when no complete book exit is priced.
  UNKNOWN   later book missing/stale/too thin and no settlement recorded.

Both are charged against the entry price, so the output is a realised P&L per
exit rather than a markout. A missing or insufficient later book is reported as
UNKNOWN exposure; it is never priced at zero. A recorded settlement outcome is
used only when no complete book exit can be priced.

    python -B scripts/exit_cost.py --size 10
    python -B scripts/exit_cost.py --size 10 --exit-deadline 900
"""

from __future__ import annotations

import argparse
import bisect
import json
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
from strategy_policy import policy_banner  # noqa: E402

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
    raw_units = TAKER_RATE * contracts * price * (1.0 - price) * 10_000.0
    return math.ceil(raw_units - 1e-12) / 10_000.0


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


def book_at_or_after(
    series: list[dict], index: int, target: float, tolerance: float,
) -> tuple[int, dict] | None:
    """First captured book no earlier than ``target``, within ``tolerance``.

    A pre-deadline book cannot represent a timed exit. Restricting the lookup to
    later books also makes the direction of any capture gap explicit.
    """

    if tolerance < 0:
        raise ValueError("book tolerance cannot be negative")
    timestamps = [row["ts"] for row in series]
    found = bisect.bisect_left(timestamps, target, lo=max(index, 0))
    if found >= len(series):
        return None
    snapshot = series[found]
    if snapshot["ts"] - target > tolerance + 1e-9:
        return None
    return found, snapshot


def load_settlements(connection: sqlite3.Connection) -> dict[str, float]:
    """Latest recorded YES settlement value by market ticker."""

    settlements: dict[str, float] = {}
    try:
        rows = connection.execute(
            "SELECT raw_json FROM market_meta ORDER BY fetched_at")
    except sqlite3.OperationalError:
        return settlements
    for (raw,) in rows:
        try:
            market = (json.loads(raw) or {}).get("market") or {}
            ticker = str(market["ticker"])
            result = str(market.get("result") or "").strip().lower()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if result == "yes":
            settlements[ticker] = 1.0
        elif result == "no":
            settlements[ticker] = 0.0
    return settlements


def settlement_pnl(
    yes_settlement: float, direction: float, entry: float, size: float,
) -> float:
    """Signed YES-equivalent P&L for holding a position to settlement."""

    if yes_settlement not in (0.0, 1.0):
        raise ValueError("YES settlement must be zero or one")
    return direction * (yes_settlement - entry) * size


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
    touch = snapshot["offer"] if direction > 0 else snapshot["bid"]
    touch_size = (snapshot["offer_size"] if direction > 0
                  else snapshot["bid_size"])
    # Improving the touch creates a new price level, so there is no displayed
    # queue ahead. Joining the touch goes behind all displayed size.
    queue = touch_size if abs(price - touch) <= 1e-9 else 0.0
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
    parser.add_argument(
        "--policy", choices=("polymarket-current", "touch", "inside"),
        default="polymarket-current")
    parser.add_argument("--exit-deadline", nargs="+", type=float,
                        default=[300.0, 900.0, 1800.0, 3600.0],
                        help="how long a passive reducer is given before we"
                             " cross out; swept because the inventory clock is"
                             " exactly what this measurement should set")
    parser.add_argument(
        "--book-tolerance", type=float, default=60.0,
        help="maximum seconds after the intended exit time for a captured"
             " book to remain usable; later/missing books are UNKNOWN")
    args = parser.parse_args()

    connection = sqlite3.connect(
        f"file:{Path(args.database).resolve()}?mode=ro", uri=True)
    programs = load_programs(connection)
    series_by_market = load_series(connection, programs)
    tape_by_market = load_tape(connection)
    settlements = load_settlements(connection)

    # Collect fills once; the exit policy is what varies across the sweep.
    fills = []
    for ticker, (series, tick, _total_snapshots) in series_by_market.items():
        tape = tape_by_market.get(ticker) or []
        tape_ts = [row[0] for row in tape]
        for index, snapshot in enumerate(series):
            if index + 1 >= len(series):
                break
            wanted = target_quote(args.policy, snapshot, tick)
            if wanted is None:
                continue
            want_bid, bid_depth, want_offer, offer_depth = wanted
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

    if args.policy == "polymarket-current":
        print(policy_banner())
    print(f"size {args.size:g}   policy {args.policy}")
    print(f"simulated fills to exit: {len(fills)}\n")
    if not fills:
        print("no fills; nothing to measure")
        return 1

    header = (f"{'deadline':>9s}{'fills':>7s}{'passive':>9s}{'crossed':>9s}"
              f"{'settled':>9s}{'unknown':>9s}{'thin':>7s}"
              f"{'priced%':>9s}{'total $':>11s}{'mean $':>10s}{'median $':>11s}")
    print(header)
    print("-" * len(header))

    for deadline in args.exit_deadline:
        passive_pnl, crossed_pnl, settled_pnl, priced = [], [], [], []
        thin = 0
        unknown = 0
        for ticker, index, fill_ts, direction, entry, tick in fills:
            series, _, _ = series_by_market[ticker]
            tape = tape_by_market.get(ticker) or []
            tape_ts = [row[0] for row in tape]
            start = book_at_or_after(
                series, index, fill_ts, args.book_tolerance)
            rested = None
            if start is not None:
                start_index, _ = start
                rested = passive_exit(
                    series, start_index, tape, tape_ts, fill_ts, direction,
                    entry, args.size, tick, deadline)
            if rested is not None:
                price, _ = rested
                value = direction * (price - entry) * args.size
                passive_pnl.append(value)
                priced.append(value)
                continue
            # Deadline expired: cross only against a later book close enough to
            # the intended exit instant. The entry book is never reused.
            timed = book_at_or_after(
                series, index, fill_ts + deadline, args.book_tolerance)
            crossed = (crossed_exit(timed[1], direction, args.size)
                       if timed is not None else None)
            if crossed is None or crossed[1] < args.size - 1e-9:
                if crossed is not None:
                    thin += 1
                if ticker in settlements:
                    value = settlement_pnl(
                        settlements[ticker], direction, entry, args.size)
                    settled_pnl.append(value)
                    priced.append(value)
                else:
                    unknown += 1
                continue
            vwap, filled, fee = crossed
            value = direction * (vwap - entry) * filled - fee
            crossed_pnl.append(value)
            priced.append(value)

        total = len(fills)
        print(f"{deadline:9.0f}{total:7d}{len(passive_pnl):9d}"
              f"{len(crossed_pnl):9d}{len(settled_pnl):9d}{unknown:9d}"
              f"{thin:7d}{100.0 * len(priced) / total:8.1f}%"
              f"{sum(priced):11.4f}"
              f"{statistics.fmean(priced) if priced else 0.0:10.4f}"
              f"{statistics.median(priced) if priced else 0.0:11.4f}")

    print()
    print("P&L is entry-to-exit for fully priced positions. Timed crosses use the")
    print("first book at/after the deadline and include the taker fee at actual")
    print("VWAP. Passive maker fees remain unmeasured. Missing/stale or thin books")
    print("are UNKNOWN unless a recorded YES/NO settlement prices the whole fill;")
    print("unknown exposure contributes neither zero dollars nor a made-up price.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
