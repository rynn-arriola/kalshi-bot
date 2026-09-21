"""Replay fills and realized exits on a time-aligned reward schedule.

The schedule comes from ``sizing.py --schedule-output``.  This keeps reward,
entry fills, quote downtime, and exits on the same tickers and clock.  Selection
is still hindsight-ranked, so the combined result is an optimistic strategy
screen rather than a live profit forecast.
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

from exit_cost import (  # noqa: E402
    book_at_or_after, crossed_exit, load_settlements, passive_exit,
    settlement_pnl,
)
from analyze_capture import qualifying  # noqa: E402
from markout import best_level, infer_tick, parse_ts  # noqa: E402
from net_sizing import load_tape, target_quote  # noqa: E402
from reference_policy import reference_target_quote  # noqa: E402


def fee(contracts: float, price: float, rate: float) -> float:
    if contracts <= 0:
        return 0.0
    price = min(max(price, 0.0), 1.0)
    raw_units = rate * contracts * price * (1.0 - price) * 10_000
    return math.ceil(raw_units - 1e-12) / 10_000


def maximum_loss(direction: float, entry: float, size: float) -> float:
    """Worst terminal P&L before fees for one YES-equivalent position."""
    return -(entry if direction > 0 else 1.0 - entry) * size


def parse_settlement_overrides(values: list[str]) -> dict[str, float]:
    """Parse repeatable ``TICKER=yes|no`` settlement overrides."""

    settlements = {}
    for value in values:
        try:
            ticker, result = value.rsplit("=", 1)
        except ValueError as error:
            raise ValueError(f"invalid settlement override: {value!r}") from error
        ticker, result = ticker.strip(), result.strip().lower()
        if not ticker or result not in {"yes", "no"}:
            raise ValueError(f"invalid settlement override: {value!r}")
        settlements[ticker] = 1.0 if result == "yes" else 0.0
    return settlements


def merged_ticker_intervals(schedule: list[dict]) -> dict[str, list[tuple]]:
    intervals: dict[str, list[tuple]] = defaultdict(list)
    for segment in schedule:
        start, end = parse_ts(segment["start"]), parse_ts(segment["end"])
        details = {item["ticker"]: item for item in segment.get("items", [])}
        for ticker in segment["tickers"]:
            detail = details.get(ticker, {})
            rate = float(detail.get("per_day", 0.0))
            programs = tuple(
                (str(p["id"]), float(p["target_size"]),
                 float(p["discount_factor"]))
                for p in detail.get("programs", []))
            rows = intervals[ticker]
            if rows and rows[-1][1] == start \
                    and abs(rows[-1][2] - rate) < 1e-12 \
                    and rows[-1][3] == programs:
                rows[-1] = (rows[-1][0], end, rate, programs)
            else:
                rows.append((start, end, rate, programs))
    return intervals


def load_selected_books(connection, tickers: set[str]):
    series = defaultdict(list)
    prices = defaultdict(set)
    for ticker, fetched_at, raw in connection.execute(
            "SELECT market_ticker, fetched_at, raw_json FROM books"
            " WHERE raw_json IS NOT NULL ORDER BY fetched_at"):
        if ticker not in tickers:
            continue
        book = (json.loads(raw) or {}).get("orderbook_fp") or {}
        ladders = {
            name: [(float(p), float(s))
                   for p, s in (book.get(f"{name}_dollars") or [])]
            for name in ("yes", "no")}
        yes_best, no_best = best_level(ladders["yes"]), best_level(ladders["no"])
        if yes_best is None or no_best is None:
            continue
        prices[ticker].update(p for p, _ in ladders["yes"])
        prices[ticker].update(round(1.0 - p, 4) for p, _ in ladders["no"])
        series[ticker].append({
            "ts": parse_ts(fetched_at), "ladders": ladders,
            "bid": yes_best[0], "bid_size": yes_best[1],
            "offer": round(1.0 - no_best[0], 4), "offer_size": no_best[1],
        })
    return {ticker: (rows, infer_tick(prices[ticker]))
            for ticker, rows in series.items()}


def replay_interval(series, tick, tape, start, end, rate, programs, args):
    timestamps = [row["ts"] for row in series]
    tape_ts = [row[0] for row in tape]
    first = bisect.bisect_left(timestamps, start)
    last = bisect.bisect_left(timestamps, end)
    available = start
    live = None
    last_reprice = -float("inf")
    fills = []
    selected_seconds = max(0.0, end - start)
    lost_reward = 0.0

    index = first
    while index + 1 < min(last, len(series)):
        snapshot, following = series[index], series[index + 1]
        ts, next_ts = snapshot["ts"], following["ts"]
        interval_seconds = max(0.0, min(next_ts, end) - ts)
        if ts < available or next_ts - ts > args.max_book_gap:
            live = None
            if ts >= available:
                lost_reward += rate * interval_seconds / 86400.0
            index += 1
            continue
        if args.policy in {"reference", "reference-minus-one"}:
            wanted = reference_target_quote(
                snapshot, tick, programs, reward_rule=args.reward_rule,
                behind_ticks=1 if args.policy == "reference-minus-one" else 0)
        else:
            wanted = target_quote(args.policy, snapshot, tick)
        if wanted is None:
            live = None
            lost_reward += rate * interval_seconds / 86400.0
            index += 1
            continue
        bid, bid_depth, offer, offer_depth = wanted
        if live is None:
            live = [bid, bid_depth, offer, offer_depth]
            last_reprice = ts
        elif (abs(live[0] - bid) > 1e-9 or abs(live[2] - offer) > 1e-9) \
                and ts - last_reprice >= args.reprice_seconds:
            live = [bid, bid_depth, offer, offer_depth]
            last_reprice = ts
        current_offer = snapshot["offer"]
        current_bid = snapshot["bid"]
        if live[0] >= current_offer - 1e-9 or live[2] <= current_bid + 1e-9:
            live = None
            lost_reward += rate * interval_seconds / 86400.0
            index += 1
            continue
        own_prices = {"yes": live[0], "no": round(1.0 - live[2], 6)}
        reward_qualified = any(
            all(qualifying(
                snapshot["ladders"][side] + [(own_prices[side], args.size)],
                target_size, discount, mode=args.reward_rule,
                tick_size=tick)[2]
                for side in ("yes", "no"))
            for _program_id, target_size, discount in programs)
        if not reward_qualified:
            live = None
            lost_reward += rate * interval_seconds / 86400.0
            index += 1
            continue
        lo, hi = bisect.bisect_right(tape_ts, ts), bisect.bisect_right(tape_ts, next_ts)
        hit = None
        for trade_ts, yes_price, traded, taker in tape[lo:hi]:
            for side in ("bid", "offer"):
                px = live[0] if side == "bid" else live[2]
                queue_index = 1 if side == "bid" else 3
                wants = "no" if side == "bid" else "yes"
                reaches = (yes_price <= px + 1e-9 if side == "bid"
                           else yes_price >= px - 1e-9)
                if taker != wants or not reaches:
                    continue
                remaining = traded
                eaten = min(live[queue_index], remaining)
                live[queue_index] -= eaten
                remaining -= eaten
                if remaining >= args.size - 1e-9:
                    hit = (trade_ts, 1.0 if side == "bid" else -1.0, px)
                    break
            if hit:
                break
        if hit is None:
            index += 1
            continue

        fill_ts, direction, entry = hit
        start_book = book_at_or_after(series, index, fill_ts, args.book_tolerance)
        rested = None
        if start_book is not None:
            rested = passive_exit(
                series, start_book[0], tape, tape_ts, fill_ts, direction,
                entry, args.size, tick, args.exit_deadline)
        entry_fee = fee(args.size, entry, args.maker_rate)
        outcome, exit_time, pnl, exit_fee = "unknown", fill_ts + args.exit_deadline, None, 0.0
        if rested is not None:
            price, exit_time = rested
            exit_fee = fee(args.size, price, args.maker_rate)
            pnl = direction * (price - entry) * args.size - entry_fee - exit_fee
            outcome = "passive"
        else:
            timed = book_at_or_after(
                series, index, fill_ts + args.exit_deadline, args.book_tolerance)
            crossed = crossed_exit(timed[1], direction, args.size) if timed else None
            if crossed is not None and crossed[1] >= args.size - 1e-9:
                price, filled, exit_fee = crossed
                pnl = direction * (price - entry) * filled - entry_fee - exit_fee
                outcome = "crossed"
            elif args.settlements.get(args.ticker, None) is not None:
                pnl = settlement_pnl(
                    args.settlements[args.ticker], direction, entry, args.size) - entry_fee
                outcome = "settled"
                exit_time = end
        downtime = max(0.0, min(exit_time, end) - fill_ts)
        lost_reward += rate * downtime / 86400.0
        fills.append({
            "ticker": args.ticker, "fill_ts": fill_ts,
            "direction": direction, "entry": entry,
            "outcome": outcome, "pnl": pnl, "entry_fee": entry_fee,
            "unknown_loss": maximum_loss(direction, entry, args.size) - entry_fee,
            "downtime": downtime,
        })
        available = exit_time
        live = None
        index = max(index + 1, bisect.bisect_left(timestamps, available, lo=index + 1))
    return fills, selected_seconds, lost_reward


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--database")
    parser.add_argument("--exit-deadline", type=float, default=900.0)
    parser.add_argument("--book-tolerance", type=float, default=90.0)
    parser.add_argument("--max-book-gap", type=float, default=300.0)
    parser.add_argument("--reprice-seconds", type=float, default=0.0,
                        help="minimum time between reference-price replacements")
    parser.add_argument("--maker-rate", type=float, default=0.0,
                        help="maker-fee rate; general event-contract default is"
                             " 0, use 0.0175 only for listed maker-fee series")
    parser.add_argument(
        "--settlement", action="append", default=[], metavar="TICKER=yes|no",
        help="repeatable settlement result not present in the capture database")
    args = parser.parse_args()
    payload = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    args.size = float(payload["size"])
    args.policy = payload["policy"]
    args.reward_rule = payload["reward_rule"]
    database = args.database or payload["database"]
    intervals = merged_ticker_intervals(payload["schedule"])
    connection = sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True)
    books = load_selected_books(connection, set(intervals))
    tapes = load_tape(connection)
    args.settlements = load_settlements(connection)
    try:
        args.settlements.update(parse_settlement_overrides(args.settlement))
    except ValueError as error:
        parser.error(str(error))

    all_fills = []
    selected_seconds = lost_reward = 0.0
    for ticker, ticker_intervals in intervals.items():
        if ticker not in books:
            continue
        args.ticker = ticker
        series, tick = books[ticker]
        for start, end, rate, programs in ticker_intervals:
            fills, seconds, lost = replay_interval(
                series, tick, tapes.get(ticker, []), start, end, rate,
                programs, args)
            all_fills.extend(fills)
            selected_seconds += seconds
            lost_reward += lost

    counts = defaultdict(int)
    priced = []
    unknown_loss = 0.0
    maker_fees = 0.0
    downtime = 0.0
    for fill in all_fills:
        counts[fill["outcome"]] += 1
        maker_fees += fill["entry_fee"]
        downtime += fill["downtime"]
        if fill["pnl"] is None:
            unknown_loss += fill["unknown_loss"]
        else:
            priced.append(fill["pnl"])
    reward = float(payload["modeled_reward"])
    central = reward - lost_reward + sum(priced)
    conservative = central + unknown_loss
    days = float(payload["capture_days"])
    print(f"schedule              {args.schedule}")
    print(f"capture days          {days:.2f}")
    print(f"selected tickers      {len(intervals)} historical unique")
    print(f"size / exit deadline  {args.size:g} / {args.exit_deadline:g}s")
    print(f"reprice interval      {args.reprice_seconds:g}s")
    print(f"maker fee rate        {args.maker_rate:.4f}")
    print(f"fills                 {len(all_fills)}  passive {counts['passive']}  "
          f"crossed {counts['crossed']}  settled {counts['settled']}  unknown {counts['unknown']}")
    print(f"modeled reward        ${reward:.2f}  (${reward / days:.2f}/day)")
    print(f"reward lost downtime  -${lost_reward:.2f}")
    print(f"priced trading P&L    ${sum(priced):+.2f}  (includes estimated maker fees)")
    print(f"unknown max-loss      ${unknown_loss:+.2f}")
    print(f"central combined      ${central:+.2f}  (${central / days:+.2f}/day)")
    print(f"conservative combined ${conservative:+.2f}  (${conservative / days:+.2f}/day)")
    if priced:
        print(f"priced fill mean      ${statistics.fmean(priced):+.3f}")
    unknown = [fill for fill in all_fills if fill["outcome"] == "unknown"]
    if unknown:
        print("unknown exits         " + ", ".join(
            f"{fill['ticker']}@{fill['entry']:.3f}"
            f"({'YES' if fill['direction'] > 0 else 'NO'})"
            for fill in unknown))
    print("selection uses hindsight; central treats unknown exits as $0;")
    print("conservative charges each unknown at its maximum terminal loss.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
