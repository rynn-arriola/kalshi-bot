"""Native Windows ownership primitive; no services or scheduled tasks."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path

from .values import InvalidData, identity as validate_identity


def suggested_data_directory() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not root or not Path(root).is_absolute():
        raise InvalidData("native Windows LOCALAPPDATA is required")
    return Path(root) / "KalshiLiquidityBot"


class WindowsLease:
    """System-wide Windows kernel object tied to process lifetime, not a PID file.

    Must be held while the ledger/runtime is active. No lockfile deletion race.
    """
    def __init__(self, identity: str):
        if os.name != "nt":
            raise InvalidData("Windows runtime required")
        if not identity:
            raise InvalidData("ownership identity required")
        digest = hashlib.sha256(identity.casefold().encode()).hexdigest()
        self.name = "Global\\KalshiLiquidityBot-" + digest
        self.handle = None
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL

    def __enter__(self):
        if self.handle is not None:
            raise InvalidData("lease already held")
        ctypes.set_last_error(0)
        handle = self.api.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise InvalidData("Windows ownership lock unavailable")
        if error == 183:  # ERROR_ALREADY_EXISTS; presence is our exclusivity gate.
            self.api.CloseHandle(handle)
            raise InvalidData("another process owns this bot identity")
        self.handle = handle
        return self

    def __exit__(self, *exc):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class WindowsStopEvent:
    """Named, manual-reset local stop request; not a kill or cancel-all command.

    Only the owner creates it. Controllers open an existing object, so sending
    a stop to an absent runtime cannot create a stale stop for a future launch.
    Hold WindowsLease separately for the full runtime and stop/join before close.
    """
    def __init__(self, identity: str):
        if os.name != "nt":
            raise InvalidData("Windows runtime required")
        validate_identity(identity)
        digest = hashlib.sha256(identity.casefold().encode()).hexdigest()
        self.name = "Global\\KalshiLiquidityStop-"+digest
        self.handle = None
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateEventW.restype = wintypes.HANDLE
        self.api.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.OpenEventW.restype = wintypes.HANDLE
        self.api.SetEvent.argtypes = [wintypes.HANDLE]
        self.api.SetEvent.restype = wintypes.BOOL
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL

    def __enter__(self):
        if self.handle is not None:
            raise InvalidData("stop event already owned")
        ctypes.set_last_error(0)
        handle = self.api.CreateEventW(None, True, False, self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise InvalidData("Windows stop event unavailable")
        if error == 183:
            self.api.CloseHandle(handle)
            raise InvalidData("stop event already owned")
        self.handle = handle
        return self

    @property
    def requested(self):
        if self.handle is None:
            raise InvalidData("stop event not owned")
        result = self.api.WaitForSingleObject(self.handle, 0)
        if result not in (0, 258):
            raise InvalidData("Windows stop event check failed")
        return result == 0

    def request(self):
        handle = self.api.OpenEventW(2, False, self.name)  # EVENT_MODIFY_STATE
        if not handle:
            if ctypes.get_last_error() == 2:  # ERROR_FILE_NOT_FOUND
                return False
            raise InvalidData("Windows stop request unavailable")
        try:
            if not self.api.SetEvent(handle):
                raise InvalidData("Windows stop request failed")
            return True
        finally:
            self.api.CloseHandle(handle)

    def __exit__(self, *_):
        if self.handle is not None:
            self.api.CloseHandle(self.handle)
            self.handle = None
