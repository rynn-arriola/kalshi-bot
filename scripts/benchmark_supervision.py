"""Offline D-050 S1 policy/resource fixture; no process, credentials or network."""
import argparse
import json
import time
import tracemalloc

from kalshi_bot.supervision import (
    EventKind, SupervisorEvent, decide, initial_state)


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
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    wakes = 0
    while time.perf_counter()-started_wall < seconds:
        remaining = seconds-(time.perf_counter()-started_wall)
        time.sleep(min(1.0, max(0.0, remaining)))
        wakes += 1
    wall = time.perf_counter()-started_wall
    cpu = time.process_time()-started_cpu
    cpu_percent = 100*cpu/wall if wall else 0
    result = dict(case="idle_parent", wall_seconds=round(wall, 3),
        cpu_seconds=round(cpu, 6), cpu_percent_one_core=round(cpu_percent, 4),
        wakes=wakes, max_wakes_per_second=1.0)
    result["pass"] = cpu_percent < 1 and wakes <= int(seconds)+1
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
