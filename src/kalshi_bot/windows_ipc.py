"""Bounded local Windows named-pipe transport for the inert S2A harness."""
from collections import deque
import ctypes
from ctypes import wintypes
from queue import Empty, Full, Queue
import os
from threading import Event, Lock, Thread
import time

from .supervisor_protocol import (COALESCED_KINDS, FrameDecoder,
                                  MAX_CONTROL_FRAMES, encode_frame)
from .values import InvalidData, identity
from .windows import WindowsSecurity, _close_handle, current_user_sid


ERROR_IO_PENDING = 997
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_OPERATION_ABORTED = 995
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
INFINITE = 0xffffffff
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_TYPE_BYTE = 0
PIPE_READMODE_BYTE = 0
PIPE_WAIT = 0
PIPE_REJECT_REMOTE_CLIENTS = 0x8
OPEN_EXISTING = 3
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000


class _Overlapped(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


def _api():
    if os.name != "nt":
        raise InvalidData("native Windows IPC required")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                 wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateEventW.restype = wintypes.HANDLE
    api.SetEvent.argtypes = [wintypes.HANDLE]
    api.SetEvent.restype = wintypes.BOOL
    api.ResetEvent.argtypes = [wintypes.HANDLE]
    api.ResetEvent.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.WaitForMultipleObjects.argtypes = [wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
    api.WaitForMultipleObjects.restype = wintypes.DWORD
    api.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_Overlapped)]
    api.ReadFile.restype = wintypes.BOOL
    api.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_Overlapped)]
    api.WriteFile.restype = wintypes.BOOL
    api.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Overlapped),
                                        ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
    api.GetOverlappedResult.restype = wintypes.BOOL
    api.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Overlapped)]
    api.CancelIoEx.restype = wintypes.BOOL
    return api


def supervisor_pipe_name(scope_digest, nonce):
    if not isinstance(scope_digest, str) or len(scope_digest) != 64:
        raise InvalidData("invalid pipe scope digest")
    identity(nonce)
    return rf"\\.\pipe\KalshiLiquidityS2-{scope_digest}-{nonce}"


class PipeEndpoint:
    """One worker owns one outstanding read/write and every OVERLAPPED buffer."""
    def __init__(self, handle, *, name):
        if not handle:
            raise InvalidData("connected pipe handle required")
        self.handle = handle
        self.name = name
        self.api = _api()
        self.control = Queue(maxsize=MAX_CONTROL_FRAMES)
        self.incoming = Queue(maxsize=MAX_CONTROL_FRAMES+1)
        self._coalesced = None
        self._slot_lock = Lock()
        self.error = None
        self.closed = False
        self.activity = Event()
        self._close_event = self.api.CreateEventW(None, True, False, None)
        self._wake_event = self.api.CreateEventW(None, False, False, None)
        if not self._close_event or not self._wake_event:
            _close_handle(self._close_event)
            _close_handle(self._wake_event)
            _close_handle(handle)
            raise InvalidData("pipe worker event unavailable")
        self.thread = Thread(target=self._run, name="kalshi-supervisor-ipc", daemon=False)
        self.thread.start()

    def send_control(self, envelope):
        if self.closed or self.error is not None:
            raise InvalidData("supervisor IPC unavailable")
        if envelope.kind in COALESCED_KINDS:
            raise InvalidData("coalesced message requires publish_latest")
        try:
            self.control.put_nowait(encode_frame(envelope))
        except Full as exc:
            raise InvalidData("supervisor control queue overflow") from exc
        if not self.api.SetEvent(self._wake_event):
            raise InvalidData("supervisor IPC wake failed")

    def publish_latest(self, envelope):
        if self.closed or self.error is not None:
            raise InvalidData("supervisor IPC unavailable")
        if envelope.kind not in COALESCED_KINDS:
            raise InvalidData("retained message cannot be coalesced")
        frame = encode_frame(envelope)
        with self._slot_lock:
            self._coalesced = frame
        if not self.api.SetEvent(self._wake_event):
            raise InvalidData("supervisor IPC wake failed")

    def receive(self, timeout=None):
        try:
            item = self.incoming.get(timeout=timeout)
        except Empty:
            if self.error is not None:
                raise InvalidData("supervisor IPC failed") from self.error
            return None
        finally:
            if self.incoming.empty():
                self.activity.clear()
                if not self.incoming.empty() or self.error is not None:
                    self.activity.set()
        if isinstance(item, BaseException):
            raise InvalidData("supervisor IPC failed") from item
        return item

    def wait_activity(self, timeout):
        if self.closed:
            return True
        return self.activity.wait(timeout)

    def _take_outgoing(self):
        result = []
        while len(result) < MAX_CONTROL_FRAMES:
            try:
                result.append(self.control.get_nowait())
            except Empty:
                break
        with self._slot_lock:
            if self._coalesced is not None:
                result.append(self._coalesced)
                self._coalesced = None
        return result

    def _record_error(self, error):
        if self.error is None:
            self.error = error
            self.activity.set()
            try:
                self.incoming.put_nowait(error)
            except Full:
                pass

    def _write(self, data):
        event = self.api.CreateEventW(None, True, False, None)
        if not event:
            raise InvalidData("pipe write event unavailable")
        overlap = _Overlapped(hEvent=event)
        buffer = ctypes.create_string_buffer(data)
        transferred = wintypes.DWORD()
        try:
            success = self.api.WriteFile(self.handle, buffer, len(data), None,
                                         ctypes.byref(overlap))
            if not success and ctypes.get_last_error() != ERROR_IO_PENDING:
                raise InvalidData("supervisor pipe write failed")
            handles = (wintypes.HANDLE*2)(self._close_event, event)
            result = self.api.WaitForMultipleObjects(2, handles, False, INFINITE)
            if result == WAIT_OBJECT_0:
                self.api.CancelIoEx(self.handle, ctypes.byref(overlap))
                self.api.WaitForSingleObject(event, INFINITE)
                return False
            if result != WAIT_OBJECT_0+1:
                raise InvalidData("supervisor pipe write wait failed")
            if not self.api.GetOverlappedResult(self.handle, ctypes.byref(overlap),
                                                ctypes.byref(transferred), False):
                raise InvalidData("supervisor pipe write completion failed")
            if transferred.value != len(data):
                raise InvalidData("partial supervisor pipe write")
            return True
        finally:
            _close_handle(event)

    def _run(self):
        decoder = FrameDecoder()
        read_event = self.api.CreateEventW(None, True, False, None)
        buffer = ctypes.create_string_buffer(16384)
        overlap = _Overlapped(hEvent=read_event)
        pending = False
        arrivals = deque()
        tokens = 64.0
        token_time = time.monotonic()
        try:
            if not read_event:
                raise InvalidData("pipe read event unavailable")
            while True:
                if not pending:
                    self.api.ResetEvent(read_event)
                    success = self.api.ReadFile(self.handle, buffer, len(buffer), None,
                                                ctypes.byref(overlap))
                    if not success:
                        error = ctypes.get_last_error()
                        if error in (ERROR_BROKEN_PIPE, ERROR_OPERATION_ABORTED):
                            break
                        if error != ERROR_IO_PENDING:
                            raise InvalidData("supervisor pipe read failed")
                    pending = True
                handles = (wintypes.HANDLE*3)(self._close_event, self._wake_event,
                                              read_event)
                result = self.api.WaitForMultipleObjects(3, handles, False, INFINITE)
                if result == WAIT_OBJECT_0:
                    self.api.CancelIoEx(self.handle, ctypes.byref(overlap))
                    self.api.WaitForSingleObject(read_event, INFINITE)
                    break
                if result == WAIT_OBJECT_0+1:
                    for frame in self._take_outgoing():
                        if not self._write(frame):
                            return
                    continue
                if result != WAIT_OBJECT_0+2:
                    raise InvalidData("supervisor pipe read wait failed")
                transferred = wintypes.DWORD()
                if not self.api.GetOverlappedResult(self.handle, ctypes.byref(overlap),
                                                    ctypes.byref(transferred), False):
                    error = ctypes.get_last_error()
                    if error in (ERROR_BROKEN_PIPE, ERROR_OPERATION_ABORTED):
                        break
                    raise InvalidData("supervisor pipe read completion failed")
                pending = False
                if not transferred.value:
                    break
                now = time.monotonic()
                tokens = min(64.0, tokens+(now-token_time)*32.0)
                token_time = now
                frames = decoder.feed(bytes(buffer[:transferred.value]))
                if len(frames) > tokens:
                    raise InvalidData("supervisor protocol rate exceeded")
                tokens -= len(frames)
                for envelope in frames:
                    arrivals.append(now)
                    while arrivals and now-arrivals[0] > 1:
                        arrivals.popleft()
                    if len(arrivals) > 64:
                        raise InvalidData("supervisor protocol burst exceeded")
                    try:
                        self.incoming.put_nowait(envelope)
                        self.activity.set()
                    except Full as exc:
                        raise InvalidData("supervisor receive queue overflow") from exc
        except BaseException as exc:
            self._record_error(exc)
        finally:
            if not self.closed:
                if decoder.buffer:
                    self._record_error(InvalidData("partial supervisor frame at EOF"))
                else:
                    self._record_error(InvalidData("supervisor pipe peer closed"))
            self.activity.set()
            if pending:
                self.api.CancelIoEx(self.handle, ctypes.byref(overlap))
                self.api.WaitForSingleObject(read_event, INFINITE)
            _close_handle(read_event)

    def close_and_join(self, timeout=10):
        if self.closed:
            return
        self.closed = True
        self.api.SetEvent(self._close_event)
        self.api.SetEvent(self._wake_event)
        self.api.CancelIoEx(self.handle, None)
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise InvalidData("supervisor IPC worker did not stop")
        handle, self.handle = self.handle, None
        close_event, self._close_event = self._close_event, None
        wake_event, self._wake_event = self._wake_event, None
        _close_handle(handle)
        _close_handle(close_event)
        _close_handle(wake_event)


class PipeServer:
    def __init__(self, name, *, user_sid=None):
        self.name = name
        self.user_sid = user_sid or current_user_sid()
        self.api = _api()
        self.api.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, ctypes.c_void_p]
        self.api.CreateNamedPipeW.restype = wintypes.HANDLE
        self.api.ConnectNamedPipe.argtypes = [wintypes.HANDLE,
                                              ctypes.POINTER(_Overlapped)]
        self.api.ConnectNamedPipe.restype = wintypes.BOOL
        self.api.GetNamedPipeClientProcessId.argtypes = [wintypes.HANDLE,
                                                         ctypes.POINTER(wintypes.ULONG)]
        self.api.GetNamedPipeClientProcessId.restype = wintypes.BOOL
        with WindowsSecurity(self.user_sid) as security:
            self.handle = self.api.CreateNamedPipeW(name,
                PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1, 65536, 65536, 0, ctypes.byref(security))
        if not self.handle or self.handle == wintypes.HANDLE(-1).value:
            raise InvalidData("supervisor named pipe creation failed")

    def accept(self, *, timeout=10, expected_pid=None):
        event = self.api.CreateEventW(None, True, False, None)
        overlap = _Overlapped(hEvent=event)
        try:
            success = self.api.ConnectNamedPipe(self.handle, ctypes.byref(overlap))
            if not success:
                error = ctypes.get_last_error()
                if error == ERROR_PIPE_CONNECTED:
                    pass
                elif error == ERROR_IO_PENDING:
                    result = self.api.WaitForSingleObject(event, int(timeout*1000))
                    if result == WAIT_TIMEOUT:
                        self.api.CancelIoEx(self.handle, ctypes.byref(overlap))
                        self.api.WaitForSingleObject(event, INFINITE)
                        raise InvalidData("supervisor named pipe connection timed out")
                    if result != WAIT_OBJECT_0:
                        raise InvalidData("supervisor named pipe connection failed")
                    transferred = wintypes.DWORD()
                    if not self.api.GetOverlappedResult(self.handle, ctypes.byref(overlap),
                            ctypes.byref(transferred), False):
                        raise InvalidData("supervisor named pipe connection failed")
                else:
                    raise InvalidData("supervisor named pipe connection failed")
            pid = wintypes.ULONG()
            if not self.api.GetNamedPipeClientProcessId(self.handle, ctypes.byref(pid)):
                raise InvalidData("supervisor pipe client identity unavailable")
            if expected_pid is not None and pid.value != expected_pid:
                raise InvalidData(
                    f"supervisor pipe client process mismatch: {pid.value} != {expected_pid}")
            handle, self.handle = self.handle, None
            return PipeEndpoint(handle, name=self.name)
        finally:
            _close_handle(event)

    def close(self):
        handle, self.handle = self.handle, None
        _close_handle(handle)


def connect_pipe(name, *, timeout=10, expected_server_pid=None):
    api = _api()
    api.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    api.WaitNamedPipeW.restype = wintypes.BOOL
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE,
                                                ctypes.POINTER(wintypes.ULONG)]
    api.GetNamedPipeServerProcessId.restype = wintypes.BOOL
    if not api.WaitNamedPipeW(name, int(timeout*1000)):
        raise InvalidData("supervisor pipe server unavailable")
    handle = api.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None,
                             OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if not handle or handle == wintypes.HANDLE(-1).value:
        raise InvalidData("supervisor pipe connect failed")
    try:
        pid = wintypes.ULONG()
        if not api.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)):
            raise InvalidData("supervisor pipe server identity unavailable")
        if expected_server_pid is not None and pid.value != expected_server_pid:
            raise InvalidData("supervisor pipe server process mismatch")
        return PipeEndpoint(handle, name=name)
    except BaseException:
        _close_handle(handle)
        raise
