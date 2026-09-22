"""Fixed launch profiles for the native supervisor."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from .supervisor_fixture import repository_root, source_path
from .values import InvalidData


PRODUCTION_MODE = "production_live"


@dataclass(frozen=True)
class ProductionChildMode:
    initialize: bool
    recovery_only: bool


def production_child_mode(*, initialize_approved, ledger_exists, recovery_only):
    """Resolve one-time opening and fail closed around recovery."""
    for value in (initialize_approved, ledger_exists, recovery_only):
        if type(value) is not bool:
            raise InvalidData("production child mode flags must be boolean")
    if recovery_only and not ledger_exists:
        raise InvalidData("recovery ledger is missing")
    if not ledger_exists and not initialize_approved:
        raise InvalidData("first run requires explicit initialize approval")
    return ProductionChildMode(
        initialize=initialize_approved and not ledger_exists,
        recovery_only=recovery_only)


def _hash_paths(paths):
    root = repository_root()
    digest = hashlib.sha256()
    for path in sorted((Path(value).resolve() for value in paths), key=str):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def production_build_fingerprint():
    """Fingerprint the complete shipped package used by the live child."""
    package = Path(__file__).resolve().parent
    return _hash_paths(package.glob("*.py"))


@dataclass(frozen=True)
class ProductionLaunchProfile:
    """One explicit live graph; never accepts an arbitrary executable."""
    initialize_approved: bool = False

    def __post_init__(self):
        if type(self.initialize_approved) is not bool:
            raise InvalidData("production initialize approval must be boolean")

    @property
    def mode(self):
        return PRODUCTION_MODE

    @property
    def supports_fence(self):
        return False

    @property
    def build_fingerprint(self):
        return production_build_fingerprint()

    @property
    def config_fingerprint(self):
        root = repository_root()
        config = root / "config" / "bot.json"
        if not config.is_file():
            raise InvalidData("production bot configuration is missing")
        digest = hashlib.sha256()
        digest.update(b"production-live-v1\0")
        digest.update(b"initialize-approved=" + str(self.initialize_approved).encode())
        digest.update(b"\0")
        digest.update(config.read_bytes())
        return digest.hexdigest()

    def command(self, executable, common, *, recovery_only):
        command = [str(executable), "-B", "-m", "kalshi_bot.supervised_live_child",
                   *common, "--profile", self.mode]
        if self.initialize_approved:
            command.append("--initialize-approved")
        if recovery_only:
            command.append("--recovery-only")
        return command

    @staticmethod
    def recovery_only(state):
        return bool(state.recovery_reasons)

    @property
    def source_path(self):
        return source_path()
