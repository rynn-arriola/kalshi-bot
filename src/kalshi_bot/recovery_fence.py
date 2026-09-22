"""Pure bounded recovery-fence values; no runtime, ledger or I/O imports."""
from dataclasses import dataclass
import math

from .values import InvalidData, identity, integer


MAX_FENCE_HOLDS = 32
MAX_FENCE_COOLDOWNS = 8


@dataclass(frozen=True)
class FenceCooldown:
    name: str
    deadline_utc: float

    def __post_init__(self):
        identity(self.name)
        if (isinstance(self.deadline_utc, bool)
                or not isinstance(self.deadline_utc, (int, float))
                or not math.isfinite(self.deadline_utc)
                or self.deadline_utc < 0):
            raise InvalidData("invalid recovery-fence cooldown")

    def to_dict(self):
        return {"name": self.name, "deadline_utc": float(self.deadline_utc)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"name", "deadline_utc"}:
            raise InvalidData("invalid recovery-fence cooldown fields")
        return cls(**value)


@dataclass(frozen=True)
class RecoveryFence:
    parent_session: str
    child_id: str
    child_generation: int
    fence_revision: int
    component_holds: tuple[str, ...] = ()
    cooldowns: tuple[FenceCooldown, ...] = ()
    terminal_checkpoint_complete: bool = False

    def __post_init__(self):
        identity(self.parent_session)
        identity(self.child_id)
        integer(self.child_generation, 0, 2**63-1)
        integer(self.fence_revision, 1, 2**63-1)
        if (not isinstance(self.component_holds, tuple)
                or len(self.component_holds) > MAX_FENCE_HOLDS):
            raise InvalidData("invalid recovery-fence holds")
        for hold in self.component_holds:
            identity(hold)
        if len(set(self.component_holds)) != len(self.component_holds):
            raise InvalidData("duplicate recovery-fence hold")
        if (not isinstance(self.cooldowns, tuple)
                or len(self.cooldowns) > MAX_FENCE_COOLDOWNS
                or any(not isinstance(item, FenceCooldown) for item in self.cooldowns)):
            raise InvalidData("invalid recovery-fence cooldowns")
        if len({item.name for item in self.cooldowns}) != len(self.cooldowns):
            raise InvalidData("duplicate recovery-fence cooldown")
        if type(self.terminal_checkpoint_complete) is not bool:
            raise InvalidData("invalid terminal checkpoint flag")

    def to_dict(self):
        return dict(parent_session=self.parent_session, child_id=self.child_id,
            child_generation=self.child_generation, fence_revision=self.fence_revision,
            component_holds=list(self.component_holds),
            cooldowns=[item.to_dict() for item in self.cooldowns],
            terminal_checkpoint_complete=self.terminal_checkpoint_complete)

    @classmethod
    def from_dict(cls, value):
        fields = {"parent_session", "child_id", "child_generation", "fence_revision",
                  "component_holds", "cooldowns", "terminal_checkpoint_complete"}
        if not isinstance(value, dict) or set(value) != fields:
            raise InvalidData("invalid recovery-fence fields")
        if (not isinstance(value["component_holds"], list)
                or not isinstance(value["cooldowns"], list)):
            raise InvalidData("invalid recovery-fence collections")
        try:
            holds = tuple(value["component_holds"])
            cooldowns = tuple(FenceCooldown.from_dict(item) for item in value["cooldowns"])
        except (TypeError, KeyError) as exc:
            raise InvalidData("invalid recovery-fence collection") from exc
        return cls(value["parent_session"], value["child_id"],
            value["child_generation"], value["fence_revision"], holds, cooldowns,
            value["terminal_checkpoint_complete"])
