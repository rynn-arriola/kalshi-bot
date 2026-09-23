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


def _validate_handle_security(handle, user_sid, *, access_mask=0,
                              object_type=SE_KERNEL_OBJECT, expected_dacl=None,
                              allowed_dacls=(), owner_only=False):
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
    status = advapi.GetSecurityInfo(handle, object_type,
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
        if owner_only:
            return
        actual = _security_sddl(advapi, descriptor, DACL_SECURITY_INFORMATION)
        if object_type == 1:
            # Windows may retain SE_DACL_AUTO_INHERITED after protection. P is
            # mandatory; ACEs must still be exact, explicit user/System grants.
            actual = actual.replace("D:PAI(", "D:P(")
        mask = f"0x{access_mask:x}"
        expected = expected_dacl or f"D:P(A;;{mask};;;SY)(A;;{mask};;;{approved})"
        if actual not in (expected, *allowed_dacls):
            raise InvalidData("Windows object DACL differs")
    finally:
        api.LocalFree(descriptor)


def _file_handle(path, *, create=False, write_dacl=False, share_delete=False,
                 user_sid=None):
    api = _native_api()
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    access = READ_CONTROL | 0x80 | (0x40000 if write_dacl else 0)
    with WindowsSecurity(user_sid) as security:
        handle = api.CreateFileW(str(path), access, 7 if share_delete else 3,
            ctypes.byref(security) if create else None, 1 if create else 3,
            0x02000000 | 0x00200000, None)  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
    if not handle or handle == wintypes.HANDLE(-1).value:
        raise InvalidData("protected control file unavailable")
    return handle


def _control_path(path, *, directory):
    path = Path(path)
    if (not path.is_absolute() or str(path).startswith("\\\\")
            or "onedrive" in str(path).casefold()):
        raise InvalidData("local unredirected control path required")
    for part in (path, *path.parents):
        info = part.lstat()
        if info.st_file_attributes & 0x400:
            raise InvalidData("control reparse path refused")
    if path.is_dir() != directory or (not directory and
            (not path.is_file() or path.stat().st_nlink != 1)):
        raise InvalidData("control file type differs")


def _file_dacl(user_sid, *, directory=False):
    flags = "OICI" if directory else ""
    return f"D:P(A;{flags};FA;;;SY)(A;{flags};FA;;;{user_sid})"


def _inherited_sidecar_dacl(user_sid):
    # SQLite can recreate WAL/SHM during its final close after our originally
    # protected sidecar is delete-pending. The protected parent grants only
    # these two inheritable ACEs, so the resulting file is equally scoped even
    # though Windows marks its DACL/ACEs as inherited.
    return f"D:AI(A;ID;FA;;;SY)(A;ID;FA;;;{user_sid})"


def protect_fresh_control_root(root, user_sid):
    """Only explicit initialization may protect an empty operator-supplied root."""
    _control_path(root, directory=True)
    handle = _file_handle(root, write_dacl=True, user_sid=user_sid)
    try:
        _validate_handle_security(handle, user_sid, object_type=1, owner_only=True)
        if any(Path(root).iterdir()):
            raise InvalidData("fixture control root must be empty")
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.ULONG)]
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL)]
        advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        advapi.SetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int,
            wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        advapi.SetSecurityInfo.restype = wintypes.DWORD
        descriptor, dacl = ctypes.c_void_p(), ctypes.c_void_p()
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                _file_dacl(user_sid, directory=True), 1, ctypes.byref(descriptor), None):
            raise InvalidData("control file security unavailable")
        try:
            if (not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present),
                    ctypes.byref(dacl), ctypes.byref(defaulted)) or not present.value
                    or not dacl or advapi.SetSecurityInfo(handle, 1,
                    DACL_SECURITY_INFORMATION | 0x80000000, None, None, dacl, None)):
                raise InvalidData("fresh control root protection failed")
        finally:
            api = _native_api()
            api.LocalFree.argtypes = [ctypes.c_void_p]
            api.LocalFree.restype = ctypes.c_void_p
            api.LocalFree(descriptor)
    finally:
        _close_handle(handle)


class ProtectedControlFiles:
    """Pin root/database against deletion; validate, never repair existing ACLs."""
    def __init__(self, path, user_sid, *, create=False, readonly=False):
        self.path, self.user_sid = Path(path), user_sid
        self.handles = []
        self.sidecar_handles = {}
        try:
            for target, directory in ((self.path.parent, True), (self.path, False)):
                if not directory and create:
                    # CREATE_NEW cannot truncate or replace an existing file.
                    handle = _file_handle(target, create=True, user_sid=user_sid)
                else:
                    _control_path(target, directory=directory)
                    handle = _file_handle(target, user_sid=user_sid)
                self.handles.append(handle)
                _control_path(target, directory=directory)
                _validate_handle_security(handle, user_sid, object_type=1,
                    expected_dacl=_file_dacl(user_sid, directory=directory))
            self.validate_sidecars(create_missing=not readonly)
        except BaseException:
            self.close()
            raise

    def validate_sidecars(self, *, create_missing=False):
        for suffix in ("-wal", "-shm", "-journal"):
            target = Path(str(self.path)+suffix)
            retained = self.sidecar_handles.get(suffix)
            if retained is not None:
                # The retained handle denies delete/rename while allowing SQLite
                # read/write sharing.  Revalidate the same kernel object without
                # reopening and retraversing the filesystem on every operation.
                _validate_handle_security(retained, self.user_sid, object_type=1,
                    expected_dacl=_file_dacl(self.user_sid),
                    allowed_dacls=(_inherited_sidecar_dacl(self.user_sid),))
                continue
            exists = target.exists()
            create = not exists and create_missing and suffix != "-journal"
            if not exists and not create:
                continue
            if not create:
                _control_path(target, directory=False)
            handle = _file_handle(target, create=create, share_delete=False,
                                  user_sid=self.user_sid)
            try:
                _control_path(target, directory=False)
                _validate_handle_security(handle, self.user_sid, object_type=1,
                    expected_dacl=_file_dacl(self.user_sid),
                    allowed_dacls=(_inherited_sidecar_dacl(self.user_sid),))
                self.sidecar_handles[suffix] = handle
            except BaseException:
                _close_handle(handle)
                raise

    def close(self):
        while self.sidecar_handles:
            _, handle = self.sidecar_handles.popitem()
            _close_handle(handle)
        while self.handles:
            _close_handle(self.handles[-1])
            self.handles.pop()


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
        _close_handle(self.handle)
        self.handle = None


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
        _close_handle(self.handle)
        self.handle = None


def role_present(scope_id, role, *, user_sid):
    """Read-only protected lease presence; no PID lookup or lease creation.

    Presence is not a health proof. Access/security failures are unknown, never
    absence. The short-lived inspection handle is closed before returning.
    """
    api = _native_api()
    api.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.OpenMutexW.restype = wintypes.HANDLE
    handle = api.OpenMutexW(READ_CONTROL | SYNCHRONIZE, False,
                            role_object_name(scope_id, role))
    if not handle:
        if ctypes.get_last_error() == ERROR_FILE_NOT_FOUND:
            return False
        raise InvalidData("Windows role presence unavailable")
    try:
        _validate_handle_security(handle, user_sid, access_mask=0x1f0001)
        return True
    finally:
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
        _close_handle(self.handle)
        self.handle = None


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
            if result:
                raise InvalidData("Windows power notification close failed")
            self.handle = wintypes.HANDLE()


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
