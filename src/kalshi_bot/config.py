"""Accepted business settings, bounded engineering limits and explicit gaps."""
from dataclasses import dataclass, fields
from decimal import Decimal
import json
from pathlib import Path

from .values import InvalidData, decimal, integer


# Operator-approved (capital, contracts per order, six-hour loss stop) sets.
APPROVED_MONEY = frozenset((
    (Decimal("500"), Decimal("10"), Decimal("25")),  # original reference profile
    (Decimal("780"), Decimal("30"), Decimal("25")),  # D-142 after the $300 deposit
))
_ACTIVE = None
_REFERENCE = None  # Immutable reference profile, built once (review #5).


def active():
    """The approved configuration the running bot loaded (D-142).

    Live startup activates config/bot.json; without it (offline tools and
    tests) this is the reference profile. Never a silent mix of the two.
    """
    global _REFERENCE
    if _ACTIVE is not None:
        return _ACTIVE
    if _REFERENCE is None:
        _REFERENCE = BotConfig()  # Frozen dataclass: safe to share.
    return _REFERENCE


def activate(config):
    global _ACTIVE
    if not isinstance(config, BotConfig):
        raise InvalidData('approved configuration required')
    _ACTIVE = config
    return config


@dataclass(frozen=True)
class BotConfig:
    schema_version: int = 1
    # Reference profile. The running bot uses config/bot.json via active() (D-142).
    capital_usd: Decimal = Decimal("500")
    entry_contracts: Decimal = Decimal("10")
    max_resting_entries: int = 50  # D-138; must equal risk.MAX_RESTING_ENTRIES
    window_stop_usd: Decimal = Decimal("25")
    minimum_entry_retained_value: Decimal = Decimal("0.70")
    # D-155: largest loss per contract one filled leg may carry (bid price, or
    # 1 - ask price). Finding 216: 0.80 costs ~8% of reward, blocks KXBROSFT.
    maximum_entry_downside: Decimal = Decimal("0.80")
    minimum_projected_reward_usd: Decimal = Decimal("1")
    priority_projected_reward_usd: Decimal = Decimal("2")
    # D-031: Poly's verified local default calibrates exposure, not occupancy.
    # D-023 keeps actual entry breadth limits-driven. None still fails closed
    # for explicitly unresolved configurations; never infer it from live counts.
    managed_market_slots: int | None = 20
    live_enabled: bool = False
    book_connections: int = 4
    event_queue_capacity: int = 8192
    max_levels_per_side: int = 4096
    max_managed_markets: int = 128

    def __post_init__(self):
        for name in ("capital_usd", "entry_contracts", "window_stop_usd",
                     "minimum_entry_retained_value", "minimum_projected_reward_usd",
                     "priority_projected_reward_usd", "maximum_entry_downside"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        integer(self.schema_version, 1, 1)
        if (self.capital_usd, self.entry_contracts, self.window_stop_usd) not in APPROVED_MONEY:
            raise InvalidData("unapproved money/size setting")
        if (self.minimum_entry_retained_value != Decimal("0.70")
                or self.maximum_entry_downside != Decimal("0.80")
                or self.minimum_projected_reward_usd != Decimal("1")
                or self.priority_projected_reward_usd != Decimal("2")):
            raise InvalidData("unapproved entry-quality setting")
        from .risk import MAX_RESTING_ENTRIES
        integer(self.max_resting_entries, MAX_RESTING_ENTRIES, MAX_RESTING_ENTRIES)
        if self.live_enabled is not False:
            raise InvalidData("live execution is unavailable in this build")
        integer(self.book_connections, 2, 4)
        integer(self.event_queue_capacity, 1, 65536)
        integer(self.max_levels_per_side, 1, 10000)
        integer(self.max_managed_markets, 1, 1024)
        if self.managed_market_slots is not None:
            integer(self.managed_market_slots, 1, self.max_managed_markets)
            if self.portfolio_exposure_usd > self.capital_usd:
                raise InvalidData("portfolio exposure exceeds the capital ceiling")

    @property
    def market_exposure_usd(self) -> Decimal:
        return self.entry_contracts * 9

    @property
    def portfolio_exposure_usd(self) -> Decimal | None:
        if self.managed_market_slots is None:
            return None
        return self.entry_contracts * (self.managed_market_slots + 10)

    @classmethod
    def load(cls, path: Path) -> "BotConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected = {field.name for field in fields(cls)}
        if not isinstance(raw, dict) or set(raw) != expected:
            raise InvalidData("config must contain exactly the supported fields")
        return cls(**raw)

    def live_blockers(self) -> list[str]:
        blockers = ["live activation is not authorized or available in this build"]
        if self.managed_market_slots is None:
            blockers.append("limits-driven capacity/exposure mapping is not implemented")
        blockers.extend([
            "account eligibility, stream entitlement and complete reconciliation unverified",
            "paid reward reconciliation, launch boundaries and restart acceptance remain unfinished",
            "complete history/stream proof, corrections and recovery integration remain unfinished",
        ])
        return blockers
