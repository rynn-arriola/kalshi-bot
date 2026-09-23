"""Independent-host lifetime fixture. No production profile or account access."""
import argparse
import asyncio
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

from kalshi_bot.detached_host import spawn_host
from kalshi_bot.process_supervisor import SupervisorHost, fixture_fingerprints
from kalshi_bot.supervisor_control import ControlOwner, ScopeSpec, SupervisorController


def own_kill_on_close_job():
    """Simulate a terminal host owning a kill-on-close job, permitting breakaway."""
    class Limits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
            ("max_ws", ctypes.c_size_t), ("process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD)]
    class Extended(ctypes.Structure):
        _fields_ = [("limits", Limits), ("io", ctypes.c_uint64*6),
            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
        ctypes.c_void_p, wintypes.DWORD]
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.GetCurrentProcess.restype = wintypes.HANDLE
    job = api.CreateJobObjectW(None, None)
    info = Extended()
    info.limits.flags = 0x2000 | 0x800  # KILL_ON_JOB_CLOSE | BREAKAWAY_OK
    if not job or not api.SetInformationJobObject(job, 9,
            ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not api.AssignProcessToJobObject(job, api.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    return job  # Only this fixture launcher owns it; os._exit closes the handle.


async def run(scope):
    host = SupervisorHost(scope)
    task = asyncio.create_task(host.run())
    owner = None
    try:
        await asyncio.wait_for(host.started.wait(), 5)
        owner = ControlOwner(scope)
        controller = SupervisorController(scope, owner)
        build, config = fixture_fingerprints()
        state = (await controller.inspect()).state
        await controller.arm(expected_generation=state.generation,
            build_fingerprint=build, config_fingerprint=config)
        # Inert fixture has an independent maximum lifetime, even on test failure.
        await asyncio.wait((task,), timeout=20)
    finally:
        await host.request_shutdown()
        await task
        if owner:
            await owner.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", action="store_true")
    parser.add_argument("--root", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--sid", required=True)
    args = parser.parse_args()
    if args.host:
        asyncio.run(run(ScopeSpec("fixture", args.account, args.sid, Path(args.root))))
    else:
        job = own_kill_on_close_job()
        child = spawn_host([str(Path(__file__).resolve()), "--host", *sys.argv[1:]],
                           cwd=Path(__file__).resolve().parents[2])
        print(json.dumps({"pid": child.pid}), flush=True)
        os._exit(0)  # Host must survive this launching process/console disappearing.
