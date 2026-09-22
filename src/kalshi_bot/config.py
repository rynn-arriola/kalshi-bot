"""Accepted business settings, bounded engineering limits and explicit gaps."""
from dataclasses import dataclass, fields
from decimal import Decimal
import json
from pathlib import Path

from .values import InvalidData, decimal, integer


@dataclass(frozen=True)
class BotConfig:
    schema_version: int = 1
    capital_usd: Decimal = Decimal("500")
    entry_contracts: Decimal = Decimal("10")
    max_resting_entries: int = 30
    window_stop_usd: Decimal = Decimal("25")
    # D-031: Poly's verified local default calibrates exposure, not occupancy.
    # D-023 keeps actual entry breadth limits-driven. None still fails closed
    # for explicitly unresolved configurations; never infer it from live counts.
    managed_market_slots: int | None = 20
    live_enabled: bool = False
    book_connections: int = 2
    event_queue_capacity: int = 8192
    max_levels_per_side: int = 4096
    max_managed_markets: int = 128

    def __post_init__(self):
        for name in ("capital_usd", "entry_contracts", "window_stop_usd"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        integer(self.schema_version, 1, 1)
        if (self.capital_usd, self.entry_contracts, self.window_stop_usd) != (
            Decimal("500"), Decimal("10"), Decimal("25")
        ):
            raise InvalidData("unapproved money/size setting")
        integer(self.max_resting_entries, 30, 30)
        if self.live_enabled is not False:
            raise InvalidData("live execution is unavailable in this build")
        integer(self.book_connections, 2, 2)
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
