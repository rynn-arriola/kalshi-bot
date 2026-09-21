"""Native Windows ownership primitive; no services or scheduled tasks."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
from threading import Event

from .values import InvalidData, identity as validate_identity


ERROR_ALREADY_EXISTS = 183
ERROR_FILE_NOT_FOUND = 2
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 258
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
READ_CONTROL = 0x00020000
DUPLICATE_SAME_ACCESS = 0x00000002
SDDL_REVISION_1 = 1
DEVICE_NOTIFY_CALLBACK = 2
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
SE_KERNEL_OBJECT = 6
LOCAL_SYSTEM_SID = "S-1-5-18"


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


def _native_api():
    if os.name != "nt":
        raise InvalidData("Windows runtime required")
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _close_handle(handle):
    if handle:
        api = _native_api()
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        if not api.CloseHandle(handle):
            raise InvalidData("Windows handle close failed")


def current_user_sid():
    """Return the current token's SID without exposing account names."""
    api = _native_api()
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    api.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                              ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    api.LocalFree.argtypes = [ctypes.c_void_p]
    api.LocalFree.restype = ctypes.c_void_p
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(api.GetCurrentProcess(), TOKEN_QUERY,
                                   ctypes.byref(token)):
        raise InvalidData("Windows token unavailable")
    try:
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not needed.value:
            raise InvalidData("Windows token identity unavailable")
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(token, 1, buffer, needed,
                                           ctypes.byref(needed)):
            raise InvalidData("Windows token identity unavailable")
        user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(text)):
            raise InvalidData("Windows SID conversion failed")
        try:
            return validate_identity(text.value)
        finally:
            api.LocalFree(text)
    finally:
        _close_handle(token)


class WindowsSecurity:
    """Protected user/System DACL whose native allocation has explicit lifetime."""
    def __init__(self, user_sid=None, *, inheritable=False):
        self.user_sid = validate_identity(user_sid or current_user_sid())
        if not self.user_sid.startswith("S-"):
            raise InvalidData("Windows SID required")
        self.inheritable = bool(inheritable)
        self.descriptor = ctypes.c_void_p()
        self.attributes = None

    def __enter__(self):
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.ULONG)]
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        sddl = f"D:P(A;;GA;;;SY)(A;;GA;;;{self.user_sid})"
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, SDDL_REVISION_1, ctypes.byref(self.descriptor), None):
            raise InvalidData("Windows security descriptor unavailable")
        self.attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes),
            self.descriptor, self.inheritable)
        return self.attributes

    def __exit__(self, *_):
        if self.descriptor:
            api = _native_api()
            api.LocalFree.argtypes = [ctypes.c_void_p]
            api.LocalFree.restype = ctypes.c_void_p
            api.LocalFree(self.descriptor)
            self.descriptor = ctypes.c_void_p()
            self.attributes = None


def _security_sddl(advapi, descriptor, information):
    text = wintypes.LPWSTR()
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, SDDL_REVISION_1, information, ctypes.byref(text), None):
        raise InvalidData("Windows object security conversion failed")
    try:
        return text.value
    finally:
        api = _native_api()
        api.LocalFree.argtypes = [ctypes.c_void_p]
        api.LocalFree.restype = ctypes.c_void_p
        api.LocalFree(text)


def _validate_handle_security(handle, user_sid, *, access_mask):
    """Require the approved owner class and exact protected user/System DACL."""
    approved = validate_identity(user_sid)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetSecurityInfo.restype = wintypes.DWORD
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                              ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi.GetSecurityInfo(handle, SE_KERNEL_OBJECT,
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), None, None, None, ctypes.byref(descriptor))
    if status:
        raise InvalidData("Windows object security unavailable")
    api = _native_api()
    try:
        owner_text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(owner, ctypes.byref(owner_text)):
            raise InvalidData("Windows object owner unavailable")
        try:
            if owner_text.value not in {approved, LOCAL_SYSTEM_SID}:
                raise InvalidData("Windows object owner differs")
        finally:
            api.LocalFree.argtypes = [ctypes.c_void_p]
            api.LocalFree.restype = ctypes.c_void_p
            api.LocalFree(owner_text)
        actual = _security_sddl(advapi, descriptor, DACL_SECURITY_INFORMATION)
        mask = f"0x{access_mask:x}"
        expected = f"D:P(A;;{mask};;;SY)(A;;{mask};;;{approved})"
        if actual != expected:
            raise InvalidData("Windows object DACL differs")
    finally:
        api.LocalFree(descriptor)


def role_object_name(scope_id, role):
    validate_identity(scope_id)
    if role not in {"parent", "child", "control", "stop"}:
        raise InvalidData("invalid Windows supervisor role")
    digest = hashlib.sha256(scope_id.casefold().encode()).hexdigest()
    return f"Global\\KalshiLiquidityS2-{role}-{digest}"


class WindowsRoleLease:
    """Explicitly protected process-lifetime presence lease for an S2 role."""
    def __init__(self, scope_id, role, *, user_sid=None):
        self.name = role_object_name(scope_id, role)
        self.user_sid = user_sid or current_user_sid()
        self.handle = None
        self.api = _native_api()
        self.api.CreateMutexW.argtypes = [ctypes.POINTER(_SecurityAttributes),
                                          wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE

    def __enter__(self):
        if self.handle is not None:
            raise InvalidData("Windows role lease already held")
        with WindowsSecurity(self.user_sid) as security:
            ctypes.set_last_error(0)
            handle = self.api.CreateMutexW(ctypes.byref(security), False, self.name)
            error = ctypes.get_last_error()
        if not handle:
            raise InvalidData("Windows role lease unavailable")
        try:
            _validate_handle_security(handle, self.user_sid, access_mask=0x1f0001)
        except BaseException:
            _close_handle(handle)
            raise
        if error == ERROR_ALREADY_EXISTS:
            _close_handle(handle)
            raise InvalidData("Windows supervisor role already owned")
        self.handle = handle
        return self

    def duplicate_inheritable(self):
        if self.handle is None:
            raise InvalidData("Windows role lease not held")
        return duplicate_inheritable_handle(self.handle)

    def __exit__(self, *_):
        handle, self.handle = self.handle, None
        _close_handle(handle)


class WindowsControlMutex:
    """Thread-owned short control mutex; never hold across an await."""
    def __init__(self, scope_id, *, user_sid=None, retain_handle=False):
        self.name = role_object_name(scope_id, "control")
        self.user_sid = user_sid or current_user_sid()
        self.handle = None
        self.retain_handle = bool(retain_handle)
        self.owned = False
        self.abandoned = False
        self.api = _native_api()
        self.api.CreateMutexW.argtypes = [ctypes.POINTER(_SecurityAttributes),
                                          wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.api.ReleaseMutex.restype = wintypes.BOOL

    def open(self):
        if self.handle is not None:
            return self
        with WindowsSecurity(self.user_sid) as security:
            handle = self.api.CreateMutexW(ctypes.byref(security), False, self.name)
        if not handle:
            raise InvalidData("Windows control mutex unavailable")
        try:
            _validate_handle_security(handle, self.user_sid, access_mask=0x1f0001)
        except BaseException:
            _close_handle(handle)
            raise
        self.handle = handle
        return self

    def __enter__(self):
        if self.owned:
            raise InvalidData("Windows control mutex already owned")
        self.open()
        result = self.api.WaitForSingleObject(self.handle, 5000)
        if result not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            if not self.retain_handle:
                self.close()
            raise InvalidData("Windows control mutex acquisition failed")
        self.owned = True
        self.abandoned = result == WAIT_ABANDONED
        return self

    def __exit__(self, *_):
        error = None
        if self.owned:
            if not self.api.ReleaseMutex(self.handle):
                error = InvalidData("Windows control mutex release failed")
            self.owned = False
        try:
            if not self.retain_handle:
                self.close()
        finally:
            if error is not None:
                raise error

    def close(self):
        if self.owned:
            raise InvalidData("cannot close an owned Windows control mutex")
        handle, self.handle = self.handle, None
        _close_handle(handle)


class WindowsStopLatch:
    """Protected S2 stop event with explicit create/open ownership modes."""
    def __init__(self, scope_id, *, user_sid=None, create=True, reject_existing=True):
        self.name = role_object_name(scope_id, "stop")
        self.user_sid = user_sid or current_user_sid()
        self.create = create
        self.reject_existing = reject_existing
        self.handle = None
        self.api = _native_api()
        self.api.CreateEventW.argtypes = [ctypes.POINTER(_SecurityAttributes),
            wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateEventW.restype = wintypes.HANDLE
        self.api.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.OpenEventW.restype = wintypes.HANDLE
        self.api.SetEvent.argtypes = [wintypes.HANDLE]
        self.api.SetEvent.restype = wintypes.BOOL
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD

    def __enter__(self):
        if self.create:
            with WindowsSecurity(self.user_sid) as security:
                ctypes.set_last_error(0)
                handle = self.api.CreateEventW(ctypes.byref(security), True, False,
                                               self.name)
                error = ctypes.get_last_error()
            if handle and error == ERROR_ALREADY_EXISTS and self.reject_existing:
                _close_handle(handle)
                raise InvalidData("Windows stop latch already exists")
        else:
            handle = self.api.OpenEventW(SYNCHRONIZE | 0x0002 | READ_CONTROL,
                                         False, self.name)
            error = ctypes.get_last_error()
        if not handle:
            if error == ERROR_FILE_NOT_FOUND:
                raise InvalidData("Windows stop latch absent")
            raise InvalidData("Windows stop latch unavailable")
        try:
            _validate_handle_security(handle, self.user_sid, access_mask=0x1f0003)
        except BaseException:
            _close_handle(handle)
            raise
        self.handle = handle
        return self

    @property
    def requested(self):
        if self.handle is None:
            raise InvalidData("Windows stop latch not open")
        result = self.api.WaitForSingleObject(self.handle, 0)
        if result not in (WAIT_OBJECT_0, WAIT_TIMEOUT):
            raise InvalidData("Windows stop latch check failed")
        return result == WAIT_OBJECT_0

    def request_owned(self):
        if self.handle is None or not self.api.SetEvent(self.handle):
            raise InvalidData("Windows stop latch request failed")

    def duplicate_inheritable(self):
        if self.handle is None:
            raise InvalidData("Windows stop latch not open")
        return duplicate_inheritable_handle(self.handle)

    @classmethod
    def request(cls, scope_id, *, user_sid=None):
        try:
            with cls(scope_id, user_sid=user_sid, create=False) as latch:
                latch.request_owned()
                return True
        except InvalidData as exc:
            if "absent" in str(exc):
                return False
            raise

    def __exit__(self, *_):
        handle, self.handle = self.handle, None
        _close_handle(handle)


def duplicate_inheritable_handle(handle, *, desired_access=0):
    api = _native_api()
    api.GetCurrentProcess.restype = wintypes.HANDLE
    api.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
        wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
        wintypes.BOOL, wintypes.DWORD]
    api.DuplicateHandle.restype = wintypes.BOOL
    duplicate = wintypes.HANDLE()
    options = DUPLICATE_SAME_ACCESS if not desired_access else 0
    current = api.GetCurrentProcess()
    if not api.DuplicateHandle(current, handle, current, ctypes.byref(duplicate),
                               desired_access, True, options):
        raise InvalidData("Windows handle duplication failed")
    return int(duplicate.value)


def inheritable_parent_handle():
    api = _native_api()
    api.GetCurrentProcess.restype = wintypes.HANDLE
    return duplicate_inheritable_handle(api.GetCurrentProcess(),
        desired_access=SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION)


def wait_handle(handle, timeout_ms=0):
    api = _native_api()
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    result = api.WaitForSingleObject(handle, timeout_ms)
    if result not in (WAIT_OBJECT_0, WAIT_TIMEOUT):
        raise InvalidData("Windows handle wait failed")
    return result == WAIT_OBJECT_0


def process_id_from_handle(handle):
    api = _native_api()
    api.GetProcessId.argtypes = [wintypes.HANDLE]
    api.GetProcessId.restype = wintypes.DWORD
    value = api.GetProcessId(handle)
    if not value:
        raise InvalidData("Windows process identity unavailable")
    return int(value)


_PowerCallback = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p,
                                    wintypes.ULONG, ctypes.c_void_p)


class _PowerSubscribe(ctypes.Structure):
    _fields_ = [("Callback", _PowerCallback), ("Context", ctypes.c_void_p)]


class WindowsPowerMonitor:
    """Callback-only suspend/resume latch; callbacks never perform policy work."""
    def __init__(self):
        if os.name != "nt":
            raise InvalidData("Windows runtime required")
        self.changed = Event()
        self.handle = wintypes.HANDLE()
        self.api = ctypes.WinDLL("powrprof", use_last_error=True)
        self.api.PowerRegisterSuspendResumeNotification.argtypes = [
            wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HANDLE)]
        self.api.PowerRegisterSuspendResumeNotification.restype = wintypes.DWORD
        self.api.PowerUnregisterSuspendResumeNotification.argtypes = [wintypes.HANDLE]
        self.api.PowerUnregisterSuspendResumeNotification.restype = wintypes.DWORD
        self._callback = _PowerCallback(self._notify)
        self._subscription = _PowerSubscribe(self._callback, None)

    def _notify(self, _context, _kind, _setting):
        self.changed.set()
        return 0

    def __enter__(self):
        result = self.api.PowerRegisterSuspendResumeNotification(
            DEVICE_NOTIFY_CALLBACK, ctypes.byref(self._subscription),
            ctypes.byref(self.handle))
        if result:
            raise InvalidData("Windows power notification unavailable")
        return self

    def __exit__(self, *_):
        if self.handle:
            result = self.api.PowerUnregisterSuspendResumeNotification(self.handle)
            self.handle = wintypes.HANDLE()
            if result:
                raise InvalidData("Windows power notification close failed")


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
