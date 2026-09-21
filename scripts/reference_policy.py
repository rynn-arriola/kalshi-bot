"""Pure pricing helpers for Kalshi Reference Price reward strategies."""

from __future__ import annotations

import json

from analyze_capture import qualifying


def tick_sizes_from_market_meta(connection) -> dict[str, float]:
    """Return captured exchange tick sizes keyed by market ticker.

    The order book can be sparse, so a gap between displayed levels is not
    necessarily the venue tick. ``price_ranges.step`` is authoritative when
    the collector captured market metadata.
    """

    ticks = {}
    try:
        rows = connection.execute(
            "SELECT market_ticker, raw_json FROM market_meta"
            " WHERE raw_json IS NOT NULL ORDER BY fetched_at")
    except Exception:
        return ticks
    for recorded_ticker, raw in rows:
        try:
            market = (json.loads(raw) or {}).get("market") or {}
            ticker = str(market.get("ticker") or recorded_ticker)
            steps = [float(row["step"])
                     for row in market.get("price_ranges", [])
                     if float(row.get("step", 0)) > 0]
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if steps:
            ticks[ticker] = min(steps)
    return ticks


def snapshot_tick(ladders: dict[str, list[tuple[float, float]]],
                  default: float = 0.01) -> float:
    prices = set()
    for ladder in ladders.values():
        prices.update(price for price, _ in ladder)
    ordered = sorted(prices)
    gaps = [round(right - left, 6)
            for left, right in zip(ordered, ordered[1:])
            if right - left > 1e-9]
    return min(gaps) if gaps else default


def reference_order_prices(
    ladders: dict[str, list[tuple[float, float]]],
    target_size: float,
    discount_factor: float,
    *,
    reward_rule: str,
    tick: float,
    behind_ticks: int = 0,
) -> dict[str, float] | None:
    """YES/NO bid prices at, or a fixed number of ticks behind, reference."""
    if behind_ticks < 0:
        raise ValueError("behind_ticks cannot be negative")
    prices = {}
    for side in ("yes", "no"):
        reference, _score, reached = qualifying(
            ladders[side], target_size, discount_factor,
            mode=reward_rule, tick_size=tick)
        if not reached:
            return None
        price = round(reference - behind_ticks * tick, 6)
        if price <= 0:
            return None
        prices[side] = price
    if prices["yes"] + prices["no"] >= 1.0 - 1e-9:
        return None
    return prices


def reference_target_quote(
    snapshot: dict,
    tick: float,
    programs: tuple[tuple[str, float, float], ...],
    *,
    reward_rule: str,
    behind_ticks: int = 0,
) -> tuple[float, float, float, float] | None:
    """YES-frame quote satisfying the most aggressive active reference pair."""
    candidates = []
    for _program_id, target_size, discount in programs:
        prices = reference_order_prices(
            snapshot["ladders"], target_size, discount,
            reward_rule=reward_rule, tick=tick, behind_ticks=behind_ticks)
        if prices is not None:
            candidates.append(prices)
    if not candidates:
        return None
    yes_bid = max(row["yes"] for row in candidates)
    no_bid = max(row["no"] for row in candidates)
    yes_offer = round(1.0 - no_bid, 6)
    if yes_bid >= yes_offer - 1e-9:
        return None
    bid_queue = sum(size for price, size in snapshot["ladders"]["yes"]
                    if abs(price - yes_bid) <= 1e-9)
    offer_queue = sum(size for price, size in snapshot["ladders"]["no"]
                      if abs(price - no_bid) <= 1e-9)
    return yes_bid, bid_queue, yes_offer, offer_queue
