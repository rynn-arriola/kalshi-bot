"""Pure, versioned Kalshi liquidity-reward calculations.

This module has no network, credential, database, or order code.  It preserves
the February 2026 rule only to reproduce historical analyses; captures made on
or after 2026-07-30 must use ``july-2026-one-fifth``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Iterable, Sequence


class RewardRuleMode(str, Enum):
    JULY_2026 = "july-2026-one-fifth"
    FEBRUARY_2026 = "february-2026-best-bid"


@dataclass(frozen=True)
class RewardRuleSpec:
    mode: RewardRuleMode
    label: str
    source_date: str
    effective_date: str
    source_url: str
    reference_at_one_fifth: bool
    scale_pool_for_excluded_snapshots: bool
    status: str


RULES = {
    RewardRuleMode.JULY_2026: RewardRuleSpec(
        mode=RewardRuleMode.JULY_2026,
        label="July 2026 one-fifth reference",
        source_date="2026-07-15",
        effective_date="2026-07-30",
        source_url=(
            "https://www.cftc.gov/filings/orgrules/"
            "rules07152610358.pdf"),
        reference_at_one_fifth=True,
        scale_pool_for_excluded_snapshots=True,
        status="CURRENT for captures on or after 2026-07-30",
    ),
    RewardRuleMode.FEBRUARY_2026: RewardRuleSpec(
        mode=RewardRuleMode.FEBRUARY_2026,
        label="February 2026 best-bid reference",
        source_date="2026-02-11",
        effective_date="2026-02-26",
        source_url=(
            "https://www.cftc.gov/sites/default/files/filings/"
            "orgrules/26/02/rules02112639183.pdf"),
        reference_at_one_fifth=False,
        scale_pool_for_excluded_snapshots=False,
        status="SUPERSEDED on 2026-07-30; comparison only",
    ),
}

DEFAULT_RULE_MODE = RewardRuleMode.JULY_2026
MINIMUM_PAYOUT = Decimal("1.00")


@dataclass(frozen=True)
class QualifyingSide:
    reference_price: float | None
    cutoff_price: float | None
    total_score: float
    reached_target: bool
    qualifying_levels: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class PayoutResult:
    rule_mode: RewardRuleMode
    period_share: Decimal
    non_excluded_fraction: Decimal
    raw_payout: Decimal
    rounded_payout: Decimal
    payable_payout: Decimal
    clears_minimum: bool


def coerce_rule_mode(value: RewardRuleMode | str) -> RewardRuleMode:
    if isinstance(value, RewardRuleMode):
        return value
    try:
        return RewardRuleMode(str(value))
    except ValueError as exc:
        choices = ", ".join(mode.value for mode in RewardRuleMode)
        raise ValueError(f"unknown reward rule {value!r}; choose {choices}") from exc


def rule_spec(value: RewardRuleMode | str = DEFAULT_RULE_MODE) -> RewardRuleSpec:
    return RULES[coerce_rule_mode(value)]


def rule_banner(value: RewardRuleMode | str = DEFAULT_RULE_MODE) -> str:
    spec = rule_spec(value)
    return (
        f"reward rule: {spec.mode.value} | source {spec.source_date} | "
        f"effective {spec.effective_date} | {spec.status} | {spec.source_url}"
    )


def _levels(levels: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: dict[float, float] = {}
    for raw_price, raw_size in levels:
        price, size = float(raw_price), float(raw_size)
        if not math.isfinite(price) or not 0 < price < 1:
            raise ValueError("reward price must be finite and between zero and one")
        if not math.isfinite(size) or size <= 0:
            raise ValueError("reward size must be finite and positive")
        key = round(price, 8)
        merged[key] = merged.get(key, 0.0) + size
    return sorted(merged.items(), reverse=True)


def _ticks(reference: float, price: float, tick_size: float) -> int:
    distance = max(0.0, reference - price)
    # Ceil is conservative when input lands fractionally off-grid: it never
    # overstates score by rounding a partial tick toward the reference.
    return max(0, math.ceil(distance / tick_size - 1e-9))


def qualify_side(
    levels: Sequence[tuple[float, float]],
    target_size: float,
    discount_factor: float,
    *,
    mode: RewardRuleMode | str = DEFAULT_RULE_MODE,
    tick_size: float = 0.01,
) -> QualifyingSide:
    """Walk one bid ladder and return its qualifying score denominator."""

    target = float(target_size)
    discount = float(discount_factor)
    tick = float(tick_size)
    if not math.isfinite(target) or target <= 0:
        raise ValueError("target_size must be finite and positive")
    if not math.isfinite(discount) or not 0 < discount <= 1:
        raise ValueError("discount_factor must be in (0, 1]")
    if not math.isfinite(tick) or tick <= 0:
        raise ValueError("tick_size must be finite and positive")

    ordered = _levels(levels)
    if not ordered:
        return QualifyingSide(None, None, 0.0, False, ())

    spec = rule_spec(mode)
    reference = ordered[0][0] if not spec.reference_at_one_fifth else None
    cumulative = 0.0
    qualifying: list[tuple[float, float]] = []
    for price, size in ordered:
        cumulative += size
        qualifying.append((price, size))
        if reference is None and cumulative + 1e-9 >= target / 5.0:
            reference = price
        if cumulative + 1e-9 >= target:
            break

    if cumulative + 1e-9 < target or reference is None:
        # The filed procedure clears the whole set when Target Size is missed.
        return QualifyingSide(reference, None, 0.0, False, ())

    score = sum(
        (discount ** _ticks(reference, price, tick)) * size
        for price, size in qualifying
    )
    return QualifyingSide(
        reference_price=reference,
        cutoff_price=qualifying[-1][0],
        total_score=score,
        reached_target=True,
        qualifying_levels=tuple(qualifying),
    )


def share_with_order(
    levels: Sequence[tuple[float, float]],
    target_size: float,
    discount_factor: float,
    order_price: float,
    order_size: float,
    *,
    mode: RewardRuleMode | str = DEFAULT_RULE_MODE,
    tick_size: float = 0.01,
) -> float | None:
    """Return our normalized side share after inserting one resting order."""

    price, size = float(order_price), float(order_size)
    if not math.isfinite(size) or size <= 0:
        raise ValueError("order_size must be finite and positive")
    merged = list(levels) + [(price, size)]
    result = qualify_side(
        merged, target_size, discount_factor, mode=mode, tick_size=tick_size)
    if not result.reached_target or result.cutoff_price is None:
        return None
    if price + 1e-9 < result.cutoff_price:
        return None
    assert result.reference_price is not None
    ours = (
        float(discount_factor)
        ** _ticks(result.reference_price, price, float(tick_size))
    ) * size
    return ours / result.total_score if result.total_score > 0 else None


def snapshot_qualifies(
    yes_levels: Sequence[tuple[float, float]],
    no_levels: Sequence[tuple[float, float]],
    target_size: float,
    discount_factor: float,
    *,
    mode: RewardRuleMode | str = DEFAULT_RULE_MODE,
    tick_size: float = 0.01,
) -> bool:
    """True only when both sides independently reach Target Size."""

    return all(
        qualify_side(
            levels, target_size, discount_factor,
            mode=mode, tick_size=tick_size,
        ).reached_target
        for levels in (yes_levels, no_levels)
    )


def calculate_payout(
    period_share: float | Decimal,
    reward_pool: float | Decimal,
    non_excluded_snapshots: int,
    total_snapshots: int,
    *,
    mode: RewardRuleMode | str = DEFAULT_RULE_MODE,
    minimum_payout: Decimal = MINIMUM_PAYOUT,
) -> PayoutResult:
    """Apply exclusion scaling, cent-flooring, and the per-program minimum."""

    share = Decimal(str(period_share))
    pool = Decimal(str(reward_pool))
    if not Decimal("0") <= share <= Decimal("1"):
        raise ValueError("period_share must be in [0, 1]")
    if pool < 0:
        raise ValueError("reward_pool cannot be negative")
    if total_snapshots <= 0:
        raise ValueError("total_snapshots must be positive")
    if not 0 <= non_excluded_snapshots <= total_snapshots:
        raise ValueError("non_excluded_snapshots must be within total_snapshots")

    spec = rule_spec(mode)
    observed_fraction = (
        Decimal(non_excluded_snapshots) / Decimal(total_snapshots))
    applied_fraction = (
        observed_fraction
        if spec.scale_pool_for_excluded_snapshots else Decimal("1"))
    raw = share * pool * applied_fraction
    rounded = raw.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    clears = raw >= minimum_payout
    return PayoutResult(
        rule_mode=spec.mode,
        period_share=share,
        non_excluded_fraction=observed_fraction,
        raw_payout=raw,
        rounded_payout=rounded,
        payable_payout=rounded if clears else Decimal("0.00"),
        clears_minimum=clears,
    )
