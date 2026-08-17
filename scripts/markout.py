"""Fill rates and markout for a resting two-sided quote.

This is the missing half of FINDINGS 6g. That section measured what a
*completed* pair pays -- both sides filled, spread captured. It deliberately did
not measure how often the pair completes, and a pair that only half-fills is not
a spread capture at all, it is a directional position taken at the touch.

Method, entirely on recorded data:

  1. At each book snapshot, rest a quote on both sides. `--policy touch` joins
     both touches; `--policy inside` steps one tick inside each, where the book
     leaves room for it.
  2. Walk the trade tape forward over `--window` seconds. A resting YES bid is
     filled by trades where the taker bought NO; a resting YES offer by trades
     where the taker bought YES. Direction comes from the price pair and
     `taker_side`, never from a book-side field, because `taker_book_side`
     reports 'bid' and 'ask' in opposite frames for the same kind of trade
     (FINDINGS 6f).
  3. Queue position follows from the policy, and this is the point of the
     comparison. Joining a touch puts us BEHIND everything already resting
     there, so we fill only once cumulative volume exceeds that depth plus our
     own size. Stepping inside creates a new price level that is empty by
     construction, so we are first in line.
  4. For a side that filled alone, mark out against the mid at +60/300/900s.

Markout is signed in YES-equivalent terms and is GROSS of fees. The maker fee
rate is still unmeasured on this account -- both fills were `is_taker: true`
(FINDINGS 6e) -- so a fee-net number here would be an invention.

The static-book assumption applies throughout, and it bites hardest on exactly
the policy that looks best: if we step inside, nothing here models the other
makers stepping inside us.

    python -B scripts/markout.py --policy touch
    python -B scripts/markout.py --policy inside
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HORIZONS = (60.0, 300.0, 900.0)
DEFAULT_TICK = 0.01


def parse_ts(value: str) -> float:
    """Epoch seconds from an ISO timestamp, tolerating 'Z' and offsets."""

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).timestamp()


def best_level(ladder: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Highest bid on a ladder, with the size resting there."""

    if not ladder:
        return None
    price = max(p for p, _ in ladder)
    size = sum(s for p, s in ladder if abs(p - price) < 1e-9)
    return price, size


def infer_tick(prices: set[float]) -> float:
    """Smallest gap between distinct observed prices in one market.

    Market metadata carries no tick field, so the grid is recovered from what
    the venue actually published. Most markets come back at a cent, but not
    all -- 739 snapshots showed a 0.001 spread, which a hardcoded cent would
    have silently mispriced by an order of magnitude.
    """

    ordered = sorted(prices)
    if len(ordered) < 2:
        return DEFAULT_TICK
    gaps = [round(b - a, 6) for a, b in zip(ordered, ordered[1:])
            if b - a > 1e-9]
    return min(gaps) if gaps else DEFAULT_TICK


def load_books(
    connection: sqlite3.Connection,
) -> dict[str, tuple[list[tuple], float]]:
    """Per market: a time-ordered YES-frame series, and the inferred tick.

    The venue publishes two bid ladders. A NO bid at 0.95 is an offer to sell
    YES at 0.05, so the YES offer is one minus the best NO bid -- the same
    reduction the reference implementation makes, and the only part of its
    bid/offer model that ports (docs/REFERENCE_CRITIQUE.md 4a).
    """

    series: dict[str, list[tuple]] = defaultdict(list)
    seen: dict[str, set[float]] = defaultdict(set)
    for ticker, fetched_at, raw in connection.execute(
            "SELECT market_ticker, fetched_at, raw_json FROM books"
            " WHERE raw_json IS NOT NULL ORDER BY fetched_at"):
        book = (json.loads(raw) or {}).get("orderbook_fp") or {}
        yes = [(float(p), float(s)) for p, s in (book.get("yes_dollars") or [])]
        no = [(float(p), float(s)) for p, s in (book.get("no_dollars") or [])]
        bid, offer = best_level(yes), best_level(no)
        if bid is None or offer is None:
            continue
        seen[ticker].update(p for p, _ in yes)
        seen[ticker].update(round(1.0 - p, 4) for p, _ in no)
        yes_bid, bid_size = bid
        no_bid, offer_size = offer
        series[ticker].append(
            (parse_ts(fetched_at), yes_bid, bid_size,
             round(1.0 - no_bid, 4), offer_size))
    out: dict[str, tuple[list[tuple], float]] = {}
    for ticker, rows in series.items():
        rows.sort()
        out[ticker] = (rows, infer_tick(seen[ticker]))
    return out


def load_trades(connection: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Per market, a time-ordered tape as (ts, yes_price, size, taker_side)."""

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
        # The price pair is the authority on direction and it must sum to one.
        # A row that fails this is not reinterpreted, it is dropped.
        if abs(yes_price + no_price - 1.0) > 1e-6 or taker not in {"yes", "no"}:
            continue
        tape[ticker].append((ts, yes_price, size, taker))
    for rows in tape.values():
        rows.sort()
    return tape


def mid_at(series: list[tuple], target: float, tolerance: float) -> float | None:
    """Mid from the book snapshot nearest `target`, or None if none is close.

    Captures have gaps -- one run ended at 11:48Z and the next began at 17:15Z
    -- and a horizon landing in a gap has no observation. Returning None keeps
    those out of the sample rather than marking out against a book from hours
    later.
    """

    if not series:
        return None
    low, high = 0, len(series) - 1
    while low < high:
        middle = (low + high) // 2
        if series[middle][0] < target:
            low = middle + 1
        else:
            high = middle
    best = None
    for index in (low - 1, low, low + 1):
        if 0 <= index < len(series):
            gap = abs(series[index][0] - target)
            if best is None or gap < best[0]:
                best = (gap, series[index])
    if best is None or best[0] > tolerance:
        return None
    row = best[1]
    return (row[1] + row[3]) / 2.0


def first_fill(
    tape: list[tuple], start: float, window: float,
    price: float, queue_ahead: float, size: float, side: str,
) -> float | None:
    """Time our whole order would fill, or None inside the window.

    A resting YES bid is filled by a taker buying NO, and vice versa. Trades
    through our price can only happen once our level is cleared, so they count
    toward the same queue.

    We want the WHOLE order done: a partial leaves the same directional risk
    with a smaller spread to show for it.
    """

    taker_that_fills_us = "no" if side == "bid" else "yes"
    cumulative = 0.0
    for ts, yes_price, traded, taker in tape:
        if ts <= start:
            continue
        if ts > start + window:
            break
        if taker != taker_that_fills_us:
            continue
        reaches_us = (yes_price <= price + 1e-9 if side == "bid"
                      else yes_price >= price - 1e-9)
        if not reaches_us:
            continue
        cumulative += traded
        if cumulative >= queue_ahead + size - 1e-9:
            return ts
    return None


def quote(
    policy: str, yes_bid: float, bid_size: float,
    yes_offer: float, offer_size: float, tick: float,
) -> tuple[float, float, float, float, bool]:
    """Our two prices and the queue ahead of each, under one policy.

    Returns (bid, bid_queue, offer, offer_queue, stepped_inside).

    Stepping inside needs three ticks of spread so a tick still separates our
    two orders afterwards. FINDINGS 6g measured that room is absent 71% of the
    time; with no room the side simply joins the touch, which is what makes
    this a policy rather than a filter.
    """

    if policy == "inside" and (yes_offer - yes_bid) >= 3 * tick - 1e-9:
        # A price strictly between the two touches is an empty level, so there
        # is nobody ahead of us on it.
        return (round(yes_bid + tick, 6), 0.0,
                round(yes_offer - tick, 6), 0.0, True)
    return yes_bid, bid_size, yes_offer, offer_size, False


def describe(values: list[float], label: str) -> str:
    if not values:
        return f"  {label:<22s} no samples"
    median = statistics.median(values)
    mean = statistics.fmean(values)
    positive = 100.0 * sum(1 for v in values if v > 0) / len(values)
    text = (f"  {label:<22s} n={len(values):<5d} median ${median:+.4f}"
            f"   mean ${mean:+.4f}   positive {positive:.0f}%")
    if len(values) >= 10:
        deciles = statistics.quantiles(values, n=10)
        text += (f"\n  {'':<22s} p10 ${deciles[0]:+.4f}"
                 f"   p90 ${deciles[-1]:+.4f}"
                 f"   trimmed mean ${statistics.fmean(sorted(values)[1:-1]):+.4f}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/capture.db")
    parser.add_argument("--policy", choices=("touch", "inside"), default="touch",
                        help="join both touches, or step one tick inside each")
    parser.add_argument("--size", type=float, default=5.0,
                        help="our contracts per side")
    parser.add_argument("--window", type=float, default=3600.0,
                        help="seconds a quote is given to fill")
    parser.add_argument("--stride", type=float, default=None,
                        help="seconds between sampled snapshots; defaults to"
                             " --window so samples do not overlap")
    parser.add_argument("--tolerance", type=float, default=30.0,
                        help="how far a markout book may sit from its horizon")
    args = parser.parse_args()
    stride = args.stride if args.stride is not None else args.window

    connection = sqlite3.connect(
        f"file:{Path(args.database).resolve()}?mode=ro", uri=True)
    books = load_books(connection)
    trades = load_trades(connection)

    sampled = quotable = stepped = 0
    outcomes: dict[str, int] = defaultdict(int)
    pair_edge: list[float] = []
    markout: dict[tuple[str, float], list[float]] = defaultdict(list)
    markout_any: dict[float, list[float]] = defaultdict(list)

    for ticker, (series, tick) in books.items():
        tape = trades.get(ticker) or []
        last_sample = None
        for ts, yes_bid, bid_size, yes_offer, offer_size in series:
            if last_sample is not None and ts - last_sample < stride:
                continue
            last_sample = ts
            sampled += 1
            # An overlapping or locked book is stale or bad data, not a
            # tradeable market -- the same rule entry_quote_price applies.
            if yes_offer - yes_bid < 1e-9:
                continue
            quotable += 1

            bid, bid_queue, offer, offer_queue, inside = quote(
                args.policy, yes_bid, bid_size, yes_offer, offer_size, tick)
            stepped += int(inside)

            bid_fill = first_fill(
                tape, ts, args.window, bid, bid_queue, args.size, "bid")
            offer_fill = first_fill(
                tape, ts, args.window, offer, offer_queue, args.size, "offer")

            if bid_fill is not None and offer_fill is not None:
                outcomes["both"] += 1
                pair_edge.append((offer - bid) * args.size)
                continue
            if bid_fill is None and offer_fill is None:
                outcomes["neither"] += 1
                continue

            # Exactly one side filled: we hold directional risk that the pair
            # edge never compensated.
            outcomes["one_sided"] += 1
            if bid_fill is not None:
                outcomes["bid_only"] += 1
                fill_ts, entry, direction, tag = bid_fill, bid, 1.0, "long"
            else:
                outcomes["offer_only"] += 1
                fill_ts, entry, direction, tag = offer_fill, offer, -1.0, "short"

            for horizon in HORIZONS:
                mid = mid_at(series, fill_ts + horizon, args.tolerance)
                if mid is None:
                    continue
                value = direction * (mid - entry) * args.size
                markout[(tag, horizon)].append(value)
                markout_any[horizon].append(value)

    print(f"policy                  {args.policy}"
          f"   (size {args.size:g}, window {args.window:g}s, stride {stride:g}s)")
    print(f"snapshots sampled       {sampled}")
    print(f"quotable (non-locked)   {quotable}")
    if not quotable:
        print("no quotable snapshots")
        return 1
    if args.policy == "inside":
        print(f"room to step inside     {stepped}"
              f"   ({100.0 * stepped / quotable:.1f}%)"
              f"   -- the rest joined the touch")

    print("\n=== what happens to a quote resting on both sides ===")
    for key, label in (("both", "pair completed"),
                       ("one_sided", "one side only"),
                       ("neither", "neither side filled")):
        count = outcomes[key]
        print(f"  {label:<22s} {count:6d}   {100.0 * count / quotable:5.1f}%")
    if outcomes["one_sided"]:
        print(f"    of those: bid only {outcomes['bid_only']}"
              f"   offer only {outcomes['offer_only']}")
        ratio = outcomes["one_sided"] / max(1, outcomes["both"])
        print(f"    one-sided : completed = {ratio:.1f} : 1")

    if pair_edge:
        print("\n=== completed pairs: gross spread captured ===")
        print(describe(pair_edge, "pair edge"))

    print("\n=== one-sided fills: markout, YES-equivalent, gross of fees ===")
    for horizon in HORIZONS:
        print(describe(markout_any[horizon], f"all @ {horizon:g}s"))
    print()
    for tag in ("long", "short"):
        for horizon in HORIZONS:
            print(describe(markout[(tag, horizon)], f"{tag} @ {horizon:g}s"))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
