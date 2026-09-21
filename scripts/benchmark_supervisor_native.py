"""Native S2A resource/leak evidence using fixed inert test scopes only."""
import argparse
import asyncio
import ctypes
from ctypes import wintypes
import json
import gc
import os
from pathlib import Path
import statistics
import tempfile
import threading
import time
import tracemalloc
from uuid import uuid4

from kalshi_bot.process_supervisor import SupervisorHost, fixture_fingerprints
from kalshi_bot.supervision import SupervisorPolicy, SupervisorState
from kalshi_bot.supervisor_control import ControlOwner, ScopeSpec, SupervisorController
from kalshi_bot.windows import current_user_sid, WindowsRoleLease, _close_handle
from kalshi_bot.supervisor_store import SupervisorStore


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("page_faults", wintypes.DWORD),
        ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
        ("peak_paged_pool", ctypes.c_size_t), ("paged_pool", ctypes.c_size_t),
        ("peak_nonpaged_pool", ctypes.c_size_t), ("nonpaged_pool", ctypes.c_size_t),
        ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t)]


def _ticks(value):
    return (value.high << 32) | value.low


def native_threads(pid):
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
            ("thread_id", wintypes.DWORD), ("process_id", wintypes.DWORD),
            ("base_priority", wintypes.LONG), ("delta_priority", wintypes.LONG),
            ("flags", wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Thread32First", "Thread32Next"):
        getattr(kernel, name).argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        getattr(kernel, name).restype = wintypes.BOOL
    handle = kernel.CreateToolhelp32Snapshot(4, 0)
    if handle == wintypes.HANDLE(-1).value:
        raise RuntimeError("native thread snapshot failed")
    try:
        entry = Entry(size=ctypes.sizeof(Entry))
        found = kernel.Thread32First(handle, ctypes.byref(entry))
        count = 0
        while found:
            count += int(entry.process_id == pid)
            found = kernel.Thread32Next(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise RuntimeError("native thread enumeration failed")
        return count
    finally:
        _close_handle(handle)


def child_metrics(child):
    """Diagnostic query only; lifecycle authority remains the retained Popen."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    if child.poll_exit() is not None:
        raise RuntimeError("fixture child already exited")
    handle = kernel.OpenProcess(0x1000 | 0x10, False, child.process.pid)
    if not handle:
        raise RuntimeError("fixture metric handle unavailable")
    try:
        if child.poll_exit() is not None:
            raise RuntimeError("fixture child exited during metric binding")
        return process_metrics(handle)
    finally:
        _close_handle(handle)


def process_metrics(handle):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE,
                                             ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessHandleCount.restype = wintypes.BOOL
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(_MemoryCounters),
                                           wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    created = _FileTime(); exited = _FileTime(); kernel_time = _FileTime(); user_time = _FileTime()
    handles = wintypes.DWORD(); memory = _MemoryCounters(ctypes.sizeof(_MemoryCounters))
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                  ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise RuntimeError("GetProcessTimes failed")
    if not kernel.GetProcessHandleCount(handle, ctypes.byref(handles)):
        raise RuntimeError("GetProcessHandleCount failed")
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
        raise RuntimeError("GetProcessMemoryInfo failed")
    return dict(cpu_seconds=(_ticks(kernel_time)+_ticks(user_time))/10_000_000,
                handles=handles.value, working_set_bytes=memory.working_set,
                native_threads=native_threads(kernel.GetProcessId(handle)))


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, int(len(ordered)*fraction))]


def scope_for(root):
    return ScopeSpec("fixture", "test-"+uuid4().hex, current_user_sid(), root)


async def arm(controller, host):
    state = (await controller.inspect()).state
    build, config = fixture_fingerprints(host.fixture_mode)
    receipt = await controller.arm(expected_generation=state.generation,
                                   build_fingerprint=build,
                                   config_fingerprint=config)
    if receipt.decision.stale:
        raise RuntimeError("fixture arm became stale")


async def wait_for(predicate, timeout=15):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.01)


async def idle_measurement(seconds):
    await asyncio.to_thread(lambda: None)
    baseline = process_metrics(-1)
    baseline_threads = threading.active_count()
    with tempfile.TemporaryDirectory() as temporary:
        scope = scope_for(Path(temporary))
        ControlOwner.initialize_fixture(scope)
        host = SupervisorHost(scope)
        task = asyncio.create_task(host.run())
        await host.started.wait()
        owner = ControlOwner(scope)
        controller = SupervisorController(scope, owner)
        await arm(controller, host)
        await wait_for(lambda: host.controller_state is not None
                       and host.controller_state.state == SupervisorState.HEALTHY)
        tracemalloc.start()
        await asyncio.sleep(min(5.0, seconds))
        traced_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        parent_start = process_metrics(-1)
        child_start = child_metrics(host.child)
        delays = []
        # Expensive native thread snapshots are diagnostics, not the timed idle
        # workload. Sample parent CPU after them and before the end snapshots.
        parent_cpu_start = time.process_time()
        began = time.perf_counter()
        due = began+.1
        while time.perf_counter()-began < seconds:
            await asyncio.sleep(max(0, due-time.perf_counter()))
            now = time.perf_counter()
            delays.append(max(0.0, now-due)*1000)
            due += .1
        elapsed = time.perf_counter()-began
        parent_cpu_end = time.process_time()
        parent_end = process_metrics(-1)
        child_end = child_metrics(host.child)
        backlog = host.max_incoming_backlog
        wakes = host.loop_wakes
        policy_latencies = list(host.policy_latencies_ms)
        await controller.stop()
        await asyncio.wait_for(task, 10)
        await owner.close()
    final = process_metrics(-1)
    return dict(seconds=elapsed,
        parent_cpu_percent=(parent_cpu_end-parent_cpu_start)*100/elapsed,
        child_cpu_percent=(child_end["cpu_seconds"]-child_start["cpu_seconds"])*100/elapsed,
        added_working_set_bytes=max(0, parent_end["working_set_bytes"]-baseline["working_set_bytes"])
            + child_end["working_set_bytes"],
        traced_peak_bytes=traced_peak,
        event_loop_delay_p50_ms=percentile(delays, .50),
        event_loop_delay_p95_ms=percentile(delays, .95),
        event_loop_delay_p99_ms=percentile(delays, .99),
        policy_latency_p99_ms=percentile(policy_latencies, .99),
        max_message_backlog=backlog, loop_wakes=wakes,
        parent_handle_delta=final["handles"]-baseline["handles"],
        native_thread_delta=final["native_threads"]-baseline["native_threads"],
        parent_thread_delta=threading.active_count()-baseline_threads)


async def cycle_measurement(count):
    async def run_batch(batch):
        with tempfile.TemporaryDirectory() as temporary:
            scope = scope_for(Path(temporary))
            ControlOwner.initialize_fixture(scope)
            policy = SupervisorPolicy(restart_delays=(.01,),
                max_incident_restarts=batch, rolling_restart_limit=batch)
            host = SupervisorHost(scope, fixture_mode="exit_after_status", policy=policy)
            task = asyncio.create_task(host.run())
            await host.started.wait()
            owner = ControlOwner(scope, policy=policy)
            controller = SupervisorController(scope, owner)
            await arm(controller, host)
            await wait_for(lambda: host.controller_state is not None
                and host.controller_state.state == SupervisorState.ATTENTION_REQUIRED,
                timeout=batch*2+10)
            receipt = await controller.inspect()
            if receipt.state.incident_attempts != batch or receipt.state.child_id is not None:
                raise RuntimeError("cycle fixture did not preserve exact attempts/exits")
            await host.request_shutdown()
            await asyncio.wait_for(task, 10)
            await owner.close()
            if host.validated_results != batch or host.child_exits != batch:
                raise RuntimeError("cycle result/exit evidence missing")
            for role in ("parent", "child"):
                with WindowsRoleLease(scope.scope_id, role):
                    pass
            with SupervisorStore.open_existing(scope.store_path, scope_id=scope.scope_id,
                    security_sid=scope.approved_user_sid) as store:
                rows = store.connection.execute("SELECT count(*) FROM events").fetchone()[0]
                if rows > store.event_limit:
                    raise RuntimeError("cycle journal retention exceeded")
            for name in ("parent-logs", "child-logs"):
                logs = tuple((scope.control_root/name).glob("events.jsonl*"))
                if len(logs) > 3 or sum(p.stat().st_size for p in logs) > 3*262144:
                    raise RuntimeError("cycle log retention exceeded")
    # Warm every retained executor/native path before taking the leak baseline.
    await run_batch(5)
    await asyncio.gather(*(asyncio.to_thread(time.sleep, .05) for _ in range(8)))
    baseline = process_metrics(-1)
    baseline_threads = threading.active_count()
    completed = 0
    sessions = 0
    while completed < count:
        batch = min(32, count-completed)
        await run_batch(batch)
        completed += batch
        sessions += 1
    gc.collect()
    final = process_metrics(-1)
    owned_threads = tuple(thread.name for thread in threading.enumerate()
        if thread.name.startswith(("kalshi-supervisor-", "kalshi-diagnostics")))
    return dict(cycles=completed, sessions=sessions,
        parent_handle_delta=final["handles"]-baseline["handles"],
        native_thread_delta=final["native_threads"]-baseline["native_threads"],
        parent_thread_delta=threading.active_count()-baseline_threads,
        retained_supervisor_threads=owned_threads)


async def main(args):
    if os.name != "nt":
        raise RuntimeError("native Windows required")
    cold = process_metrics(-1)
    cold_threads = threading.active_count()
    idle = await idle_measurement(args.idle_seconds)
    cycles = await cycle_measurement(args.cycles)
    await asyncio.get_running_loop().shutdown_default_executor()
    gc.collect()
    final = process_metrics(-1)
    managed_cleanup = dict(parent_handle_delta=final["handles"]-cold["handles"],
        native_thread_delta=final["native_threads"]-cold["native_threads"],
        parent_thread_delta=threading.active_count()-cold_threads)
    targets = dict(parent_idle_cpu_under_one_percent=idle["parent_cpu_percent"] < 1,
        event_loop_p99_under_50_ms=idle["event_loop_delay_p99_ms"] < 50,
        added_memory_under_40_mib=idle["added_working_set_bytes"] < 40*1024*1024,
        handles_returned=cycles["parent_handle_delta"] <= 0,
        threads_returned=(cycles["parent_thread_delta"] == 0 and cycles["native_thread_delta"] <= 0
                          and not cycles["retained_supervisor_threads"]))
    print(json.dumps(dict(workload="one inert S2A child; no market simulation or unsupervised baseline",
        idle=idle, cycles=cycles,
        managed_executor_cleanup=managed_cleanup, targets=targets),
                     sort_keys=True, indent=2))
    if not all(targets.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--idle-seconds", type=float, default=60)
    parser.add_argument("--cycles", type=int, default=100)
    values = parser.parse_args()
    if values.idle_seconds <= 0 or not 1 <= values.cycles <= 1000:
        parser.error("positive idle seconds and 1..1000 cycles required")
    asyncio.run(main(values))
