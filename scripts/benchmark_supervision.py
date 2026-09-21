"""Offline D-050 S1 policy/resource fixture; no process, credentials or network."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.supervision import (
    ChildPhase, EventKind, SupervisorAction, SupervisorEvent, decide, initial_state)
from kalshi_bot.supervisor_store import SupervisorStore


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[int((len(ordered)-1)*percent/100)]


def measure_decisions(markets):
    state = initial_state("benchmark", 0)
    # Synthetic market count is workload metadata only: the parent policy has no
    # market collection, task or scan and therefore must remain constant-cost.
    samples = []
    tracemalloc.start()
    try:
        for sequence in range(1, 5001):
            observed = float(sequence)
            started = time.perf_counter()
            state = decide(state, SupervisorEvent(EventKind.TICK, observed)).state
            samples.append(time.perf_counter()-started)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    result = dict(case="pure_policy", synthetic_markets=markets,
        decisions=len(samples), p50_ms=round(percentile(samples, 50)*1000, 4),
        p95_ms=round(percentile(samples, 95)*1000, 4),
        p99_ms=round(percentile(samples, 99)*1000, 4), peak_bytes=peak,
        per_market_tasks=0, live_ready=state.live_ready)
    result["pass"] = result["p99_ms"] < 5 and peak < 10*1024*1024 and not state.live_ready
    return result


def measure_idle(seconds):
    class FixtureClock:
        def __init__(self):
            self.started = time.perf_counter()

        def monotonic(self):
            return time.perf_counter()-self.started

        def utc(self):
            return 1000.0+self.monotonic()

    started_wall, started_cpu = time.perf_counter(), time.process_time()
    wakes = 0
    policy_events = 0
    fixture_clock = FixtureClock()
    with TemporaryDirectory() as temporary:
        with SupervisorStore(Path(temporary)/"control.db", scope_id="benchmark",
                clock=fixture_clock.utc,
                monotonic_clock=fixture_clock.monotonic) as store:
            generation = store.read().generation
            armed = store.apply(SupervisorEvent(EventKind.ARM, fixture_clock.utc(),
                expected_generation=generation, build_fingerprint="benchmark-build",
                config_fingerprint="benchmark-config")).state
            policy_events += 1
            due = store.apply(SupervisorEvent(EventKind.TICK, fixture_clock.utc()))
            policy_events += 1
            if due.actions != (SupervisorAction.START_DUE,):
                raise AssertionError("benchmark start did not become due")
            running = store.apply(SupervisorEvent(EventKind.START_REQUESTED,
                fixture_clock.utc(), expected_generation=armed.generation,
                child_id="benchmark-child")).state
            policy_events += 1
            running = store.apply(SupervisorEvent(EventKind.CHILD_STARTED,
                fixture_clock.utc(), expected_generation=running.child_generation,
                child_id=running.child_id)).state
            policy_events += 1
            sequence = 0
            while wakes == 0 or time.perf_counter()-started_wall < seconds:
                sequence += 1
                running = store.apply(SupervisorEvent(EventKind.CHILD_STATUS,
                    fixture_clock.utc(), expected_generation=running.child_generation,
                    child_id=running.child_id, child_phase=ChildPhase.HEALTHY,
                    progress_sequence=sequence)).state
                store.apply(SupervisorEvent(EventKind.TICK, fixture_clock.utc()))
                policy_events += 2
                wakes += 1
                remaining = seconds-(time.perf_counter()-started_wall)
                time.sleep(min(1.0, max(0.0, remaining)))
            journal_events = len(store.history(limit=min(policy_events, store.event_limit)))
            live_ready = store.read().live_ready
    wall = time.perf_counter()-started_wall
    cpu = time.process_time()-started_cpu
    cpu_percent = 100*cpu/wall if wall else 0
    result = dict(case="idle_parent", wall_seconds=round(wall, 3),
        cpu_seconds=round(cpu, 6), cpu_percent_one_core=round(cpu_percent, 4),
        wakes=wakes, max_wakes_per_second=1.0, policy_events=policy_events,
        journal_events=journal_events, live_ready=live_ready)
    result["pass"] = (cpu_percent < 1 and wakes <= int(seconds)+1
                      and policy_events >= 6 and journal_events == policy_events
                      and not live_ready)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idle-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    if not 0 < args.idle_seconds <= 60:
        parser.error("idle seconds must be in (0,60]")
    results = [measure_decisions(markets) for markets in (30, 120)]
    results.append(measure_idle(args.idle_seconds))
    for result in results:
        print(json.dumps(result, sort_keys=True))
    if not all(result["pass"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
