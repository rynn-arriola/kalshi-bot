"""Pinned identities for the fixed, inert S2A subprocess fixture."""
import hashlib
from pathlib import Path

from .values import InvalidData


FIXTURE_MODES = frozenset(("normal", "crash_after_admit", "hang_after_admit",
                           "exit_after_status"))


def repository_root():
    root = Path(__file__).resolve().parents[2]
    if "onedrive" in str(root).casefold():
        raise InvalidData("S2A fixture checkout cannot be inside OneDrive")
    return root


def fixture_path():
    path = repository_root() / "tests" / "fixtures" / "supervisor_child.py"
    if not path.is_file():
        raise InvalidData("fixed supervisor fixture is missing")
    return path.resolve()


def source_path():
    return (repository_root() / "src" / "kalshi_bot" / "__init__.py").resolve()


def build_fingerprint():
    digest = hashlib.sha256()
    package = Path(__file__).resolve().parent
    paths = (fixture_path(), package/"__init__.py", package/"supervision.py",
             package/"supervisor_store.py", package/"supervisor_control.py",
             package/"supervisor_protocol.py", package/"supervisor_fixture.py",
             package/"windows.py", package/"windows_ipc.py",
             package/"process_supervisor.py", package/"observability.py")
    for path in tuple(item.resolve() for item in paths):
        digest.update(path.relative_to(repository_root()).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def config_fingerprint(mode):
    if mode not in FIXTURE_MODES:
        raise InvalidData("invalid inert fixture mode")
    return hashlib.sha256(("s2a-inert:"+mode).encode()).hexdigest()
