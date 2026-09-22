# D-071 — Inventory-safe market admission and rotation

## Design before implementation

One optional offline runtime service owns candidate admission. Reuse D-070's
bounded head/tail discovery, protected owners and fresh selected incumbents.
Book subscription capacity is not order capacity: D-069 still admits only
whole 10-contract pairs under the existing 30-entry/cash/exposure/risk limits.
No orders or financial reservations are made by this component.

The current readers have immutable initial subscriptions. Use the existing
subscribe/resnapshot path for controlled replacement of one book reader at a
time. Keep every retained market on its current shard; never reconnect account
or lifecycle readers for discovery. Join the old reader before installing a
new scope and start a new book generation. This temporarily invalidates books
on that shard (including retained markets); do not pretend their continuity was
preserved. Old-generation frames cannot authorize new candidates. A fresh book,
account report, reviewed exit metadata and current program are required to rank.

Kalshi also documents incremental update_subscription. We do not implement its
ACK/snapshot/delete ordering here or assume an undocumented deletion barrier.
Current official sources checked 2026-09-21:
[connection commands](https://docs.kalshi.com/websockets/websocket-connection),
[book snapshots and deltas](https://docs.kalshi.com/websockets/orderbook-updates).
Local source of truth: `docs/KALSHI_API_REFERENCE.md` WebSocket command schemas.

Before removal, use a fresh account report, one current portfolio view and exact
writer inventory evidence for each removed market. Position, exposure, any
order, unresolved intent/fill, exit attempt/cancel or missing scope proof keeps
the market. Recheck source identity, writer revision, ingress, stop and catalog
after every await and after reader join. Engine scope changes occur only outside
an in-flight engine step. Failed/revoked handoffs keep the old scope and restart
its book reader for fresh snapshots; no rollback claims about venue orders.

Metadata changes only when its existing workers/reads are idle. Prune retired
market caches and scheduling keys, preserve retry exhaustion/cooldowns through
bounded tombstones, register new keys without invented timing/fee reviews.
Removed scheduler keys must not survive to fire against a new scope. Keep one
flat anchor per existing shard when the desired universe is empty, avoiding an
unfiltered subscribe; that anchor is not admission authority.

## Bounds and acceptance

- One admission worker and at most one rotating book reader; at most 16 removes
  and 16 additions per pass, within the existing market capacity (max 1,024).
- Use existing incentive interval for periodic discovery; source notifications
  coalesce and retries back off, with no book-tick catalog scans or new REST
  budget. Account events, due safety work and recovery take priority.
- Reader failure budgets survive planned rotations. Stop/cancellation joins all
  owned readers and the handoff; no detached operation or replacement after stop.
- Tests: protected inventory/orders/unknowns, source changes around awaits/join,
  snapshot prerequisite, removed/readded keys, bounded caches, retry exhaustion,
  metadata activity and cancellation/shutdown. Use synthetic readers/ledgers only.
- Resource fixture: 30/120 markets, ten scope cycles; CPU <5s, allocation peak
  <16 MiB, control-operation and loop p99 <50ms for the stated synthetic scope.
  Report reader teardown/writer latency separately; not a venue-latency claim.

## Verification

Implemented entry point: `RecoveryRuntime.attach_admission(offline_fixture=True)`
after selection/incentive attachments, before `run()`. Construction opens nothing.
The runtime owns the admission task and stable book-loop tasks. `cycle()` is also
available to deterministic fixtures; concurrent calls are rejected before awaits.
`status()` reports running/handoff state, completed/deferred counts and no order
authority. Missing proof retains old scope; rejected joins resubscribe the old
scope, never claim continuity or canceled orders. Retry exhaustion remains held.

31 focused tests pass (4.991 seconds): real disposable writer/runtime handoff to
a new ticker, fresh-book ranking and constrained order slots; zero mutations;
owned orders, nonzero inventory, unknown intents and unresolved exits retained;
account/catalog/clock/revision/cancellation changes across awaits and reader join;
second-shard timers, empty-universe anchor, batch/capacity bounds; metadata cache
pruning, missing new reviews, retry/cooldown retention and saturation; repeated
reader cancellation; automatic service scheduling and runtime-owned shutdown.
An in-memory reversal of the final pending-request guard makes the late-commit
test fail (scope B replaces A after cancellation). No source was changed by this
negative control. Earlier related regression run: 253 tests passed; final focused
tests include subsequent race and expiry additions.

`scripts/benchmark_market_admission.py`:

| Markets / cycles | CPU seconds | Peak bytes | Commit p50/p95/p99 ms | Loop delay p50/p95/p99 ms |
|---|---:|---:|---|---|
| 30 / 10 | 0.0* | 23,197 | 0.460 / 1.057 / 1.057 | 14.657 / 15.174 / 15.174 |
| 120 / 10 | 0.0* | 29,852 | 1.112 / 1.546 / 1.546 | 12.399 / 13.842 / 14.652 |

All declared synthetic commit/loop gates pass. *CPU duration was below this
Windows process timer's resolution, not proof of zero CPU. Workload protects
one shard while changing at most 16 keys on the other, checks stale timer cleanup
and bounded scope, and yields between cycles. Reader teardown, writer/metadata
work and network/account latency are excluded. The 4.991-second focused suite
exercises reader/writer handoffs but is not a latency percentile benchmark.
No 30/120-market production performance claim.

Final full suite: `python -B -m unittest discover -s tests -q` — 1,327 run,
1,326 passed, one expected Windows symlink-privilege skip, 186.636 seconds.
Actual diff review and whitespace checks pass; 341 scoped local documentation
links resolve. Publication is scoped to these source/tests/benchmark/doc changes
under D-065; credentials, runtime data and unrelated files are excluded.
Disabled preflight reports `live_ready=false`, no file creation, credential or
network access. No authenticated/venue request, bot process, order, live database
or Polymarket modification occurred. Official docs were read through web research.

## Remaining outside #1

#2 is implemented under [D-072](BUILD_ENTRY_DISPATCH_TRANSPORT.md). Real reward
reflection/checkpoint lifecycle (#3), real fees/timing/account inputs,
native supervisor and final readiness/launch remain. Incremental subscription
updates are a future optimization, not a hidden prerequisite for the implemented
joined replacement path. The existing one/two book-shard topology is retained;
this work does not approve extra venue connections or enable a live CLI.
