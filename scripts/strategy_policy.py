"""Pure quote policy copied conceptually from the current Polymarket bot.

Reference inspected read-only at local commit
``3134678e9937881a4b890c500fd905efb28abad6`` on 2026-08-26. The strategy
implementation is ``src/liquidity_bot/reconciler.py::entry_quote_price``;
configuration authority is ``commissioning.py``. No Polymarket API is used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


POLYMARKET_REFERENCE_COMMIT = "3134678e9937881a4b890c500fd905efb28abad6"
POLYMARKET_MINIMUM_ENTRY_SPREAD = 0.02
POLYMARKET_MINIMUM_ENTRY_PRICE = 0.10
POLYMARKET_INVENTORY_DEADLINE_SECONDS = 900


@dataclass(frozen=True)
class EntryQuotes:
    yes_bid: float
    yes_offer: float
    joined_touch: bool


def polymarket_entry_quotes(
    yes_bid: float,
    yes_offer: float,
    tick_size: float,
    minimum_gap: float = POLYMARKET_MINIMUM_ENTRY_SPREAD,
) -> EntryQuotes | None:
    """Map the current Polymarket entry-price rule into YES-price space.

    Join both touches when the gap is already at least two cents. On a tighter
    valid book, center an exact two-cent quote window on the tick grid. This is
    entry behavior only; the production exit rule is different.
    """

    bid, offer = float(yes_bid), float(yes_offer)
    tick, gap = float(tick_size), float(minimum_gap)
    if not all(math.isfinite(value) for value in (bid, offer, tick, gap)):
        raise ValueError("entry quote inputs must be finite")
    if not 0 < bid < 1 or not 0 < offer < 1:
        raise ValueError("entry touches must be between zero and one")
    if tick <= 0 or not 0 < gap < 1:
        raise ValueError("tick and minimum gap must be positive")
    spread = offer - bid
    if spread < -1e-9:
        return None
    if spread + 1e-9 >= gap:
        return EntryQuotes(bid, offer, True)

    gap_ticks = math.ceil(gap / tick - 1e-9)
    midpoint = (bid + offer) / 2.0
    bid_ticks = math.ceil(
        (midpoint - gap_ticks * tick / 2.0) / tick - 1e-9)
    quote_bid = round(bid_ticks * tick, 10)
    quote_offer = round((bid_ticks + gap_ticks) * tick, 10)
    if not 0 < quote_bid < quote_offer < 1:
        return None
    return EntryQuotes(quote_bid, quote_offer, False)


def policy_banner() -> str:
    return (
        "strategy policy: polymarket-current | local source commit "
        f"{POLYMARKET_REFERENCE_COMMIT} | join touch at >=2c; otherwise "
        "preserve 2c entry gap | no Polymarket API used"
    )
