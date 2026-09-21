"""Synthetic local write-budget hot path; no credentials or venue calls."""
import json
import time
import tracemalloc

from kalshi_bot.quota import QuotaScope
from kalshi_bot.write_budget import ORDERS, WriteBudget, WriteQuotaSnapshot


WALL = 1700000000


def snapshot():
    limits = dict(usage_tier='fixture', read=dict(refill_rate=100, bucket_capacity=100),
                  write=dict(refill_rate=1000000, bucket_capacity=1000000), grants=[])
    costs = dict(default_cost=10, endpoint_costs=[])
    return WriteQuotaSnapshot(limits, costs, scope=QuotaScope(), epoch=1, sequence=1,
                              start=(0, WALL), end=(0, WALL), ttl=300)


def workload(shards, rounds=100):
    core = WriteBudget(snapshot(), shards=tuple(range(shards)), now=(0, WALL),
                       offline_fixture=True)
    for shard in range(shards):
        for _ in range(rounds):
            permit = core.try_reserve('POST', ORDERS, shard=shard, now=(1, WALL+1))
            if permit is None:
                raise AssertionError('fixture failed to reserve')
            core.consume(permit, 'POST', ORDERS, shard=shard, now=(1, WALL+1))
    if core.status(now=(1, WALL+1)).outstanding:
        raise AssertionError('fixture leaked permits')


def measure(shards):
    cpus, walls = [], []
    for _ in range(5):
        cpu, wall = time.process_time(), time.perf_counter()
        workload(shards)
        cpus.append(time.process_time()-cpu)
        walls.append(time.perf_counter()-wall)
    tracemalloc.start()
    workload(shards)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return dict(shards=shards, commands=shards*100,
                cpu_max_ms=max(cpus)*1000, wall_max_ms=max(walls)*1000,
                peak_bytes=peak, samples=5,
                passed=max(cpus) < .250 and peak < 8*1024*1024)


def main():
    results = [measure(shards) for shards in (30, 120)]
    print(json.dumps(results, indent=2))
    if not all(result['passed'] for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
