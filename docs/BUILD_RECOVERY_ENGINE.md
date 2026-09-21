# Recovery-engine integration — D-026

Implemented and verified locally, 2026-09-20. No live authority.

## Scope and verification plan (before implementation)

Connect the existing event engine/account owner/single writer to independent
reader generations and one coalesced recovery worker. Persist normalized private
fills awaiting order ownership; atomic apply/delete, never fake ownership from
the inbox. Preserve recovery across local restarts. Startup, reconnect and missing
evidence trigger bounded REST, not steady duplicate polling of healthy streams.

Keep account proof and per-book proof separate. Disconnect or new private evidence
revokes prior reports immediately. Cursor exhaustion, subscription acknowledgments
and a quiet socket are not complete history/continuity. Entry readiness remains
false until the remaining proof and risk integration exists. No mutation executor
is attached. All background tasks must be joined/canceled on shutdown; stopping
locally does not cancel venue orders or establish flatness.

Planned bounds: at most four independent readers, one recovery worker; three
recovery attempts per trigger episode and three reader connection attempts per
runtime, exponential jittered backoff, existing endpoint token budgets; pending
fill inbox 256 rows with per-record byte bounds; at most 32 missing-order repairs
per pass. Overflow/conflict fails closed without silently pruning evidence.

Offline verification: startup/restart, missed fills, fills before orders, pending
fill conflicts, REST/private races, stale epochs, independent socket failures,
backoff/exhaustion, overload and shutdown. Reverse two safeguards and confirm
tests fail, then restore. Run full suite and blocked credential-free preflight.

Resource fixture declared before measurement: 128 and 1024 injected private fills
across 30/120 markets while deadlines/book callbacks remain serviceable. Existing
WAL/FULL writer, 2ms heartbeat, tracemalloc; setup excluded. Diagnostic budgets:
under 10 seconds per workload, fill durable processing p99 under 100ms, loop lag
p99 under 50ms, incremental Python peak under 40MiB; no lost/duplicated fills or
new-entry authorization. These are laptop diagnostics, not live SLAs.

## Implemented behavior and bounds

`RecoveryRuntime` connects `EventEngine`, `AccountCoordinator`, the durable writer
and single-use reader factories. Construction performs no I/O. The supplied
read-only WebSocket factory creates one bounded reader per subscription group,
up to two book shards, one account connection and one lifecycle connection.
Each reader merger is capped at 256 events/two MiB; existing engine bounds remain.
Acknowledgments require expected channel/request IDs and positive subscription
IDs. All account channels must acknowledge before startup recovery; acknowledgment
timeout is ten seconds. Book sequence loss wakes only that shard's reconnect.
Reader failures do not automatically restart healthy peers. Three connection
attempts per reader per runtime, not a budget reset every successful handshake.

The one coalesced worker runs on startup/reconnect or missing execution evidence,
not on every normal fill or a steady REST polling timer. Each pass enumerates
account state, imports bounded history, binds/drains pending fills, repairs
missing/mismatched terminal orders and re-enumerates current account state.
At most 32 direct order lookups are shared across these phases. Underlying GET
endpoint budgets/pagination/byte limits still apply. Three attempts per trigger
episode, exponential jittered backoff, 20-second whole-pass timeout; the existing
five-second individual reconciliation tokens are unchanged. Exhaustion blocks
until new evidence/connection triggers or an explicit new runtime; no busy retry.

`pending_fills` is additive schema-2 evidence, not an accounting migration. Its
256-row/4096-byte-per-normalized-record bound fails closed on overflow. Durable
stage happens before engine enqueue; even engine queue overflow retains already
staged fills. Duplicates merge compatible timestamp/scope precision only. Exact
order ownership/account/shard and economics are required before atomic fill/risk
application and inbox deletion. An inbox arrival timestamp is not realized P&L:
accounting uses the later first durable *accounting* receipt under D-024, never
backdates a delayed import into an old loss window. First-seen evidence is retained.
No actual account ledger was opened or migrated.

An arriving owned stream order drains up to 32 matching inbox fills without REST;
larger remaining work triggers recovery. Lost terminal order updates are repaired
by positive evidence, never by treating absence as cancellation. Unowned fills,
no-ID ambiguous sends, conflicting corrections and unexplained positions remain
blocked. Partial repairs survive interrupted runs and deduplicate on restart.

Private ingress invalidates prior account reports before any disk/queue await.
Generation/revision guards and a single private-application lock keep delayed
responses and old socket callbacks from publishing current proof. Recovery waits
for queued private work without monopolizing engine books/deadlines. Local stop
joins/cancels runtime tasks, revokes proof and leaves durable evidence intact.
The owning caller closes the writer afterward to drain already accepted commands.
No local shutdown claims venue cancellation or flatness.

## Source checks

Re-read executable Poly history application at `live_commissioning.py:2641-2679`
and bounded-recovery definitions. Reference HEAD stayed at
`54ac71a241d1ad6f02e3445655bb7115247bac02`. It was clean at the initial check;
the final check showed unrelated `STATUS.md` and
`docs/history/LOW_ORDERS_STOPPED_2026-09-20.md` changes. This task did not modify
or revert them. This carries the reference's positive-evidence/
deduplication principle, not its optional-history entry policy or numeric budgets.

Official [fill feed](https://docs.kalshi.com/websockets/user-fills),
[order feed](https://docs.kalshi.com/websockets/user-orders) and
[Get Order](https://docs.kalshi.com/api-reference/orders/get-order) rechecked this
session alongside the local exact OpenAPI/AsyncAPI schemas. These supply fill/order
identity, account/shard fields and order retrieval; optional scope is not assumed
to mean primary account. Private fills/orders do not provide a demonstrated
gap-free starting-account barrier. The existing archive contract remains the
404-only fallback. No new endpoint or invented sequence/settlement signal added.

## Verification results

Full local suite: **410 tests pass, 39 new**. Coverage includes startup history,
pending fill restart/holds, duplicate stream/history evidence, late stream binding,
archive fallback, foreign/missing scope, stale responses/epochs/acknowledgments,
single-flight recovery, missed terminal updates, no-ID ambiguous sends, atomic
rollback, inbox/engine overload, independent reconnects, timeout/backoff/exhaustion,
lookup bounds, request coalescing, healthy-stream no-polling, responsive books/
deadlines and task cleanup. No source Poly tests rerun in this milestone.

Two temporary offline reversals each failed the intended regression: removing
ingress report revocation; removing pending-fill terminal quantity validation.
Both restored before final suite. Credential-free preflight remains blocked,
`live_ready=false`, native exit code 2. No real account or socket was contacted.

## Resource diagnostic

`scripts/benchmark_recovery_engine.py`, disposable seeded WAL/FULL ledger with
actual runtime ingress, durable inbox and engine dispatch. Injected one-contract
fills are load fixtures, not a change to the approved 10-contract entry size.
Book deltas/deadlines arrive every 16 fills. Seed/setup excluded; tracemalloc and
2ms heartbeat enabled. No network, keys, REST polling or trading calls.

| Workload | 128 fills / 30 markets | 1024 fills / 120 markets |
|---|---:|---:|
| Wall / CPU seconds | .5940 / .5156 | 4.4918 / 4.0781 |
| Fill processing p50/p95/p99 ms | 4.330 / 5.616 / 5.834 | 4.228 / 5.447 / 6.496 |
| Loop lag p50/p95/p99 ms | 1.127 / 2.850 / 3.747 | 1.448 / 2.936 / 3.372 |
| Incremental Python peak bytes | 429991 | 1246681 |
| Heartbeat samples | 180 | 1306 |
| Deadlines serviced | 8 of 8 | 64 of 64 |
| Max sampled writer backlog | 1 | 1 |
| Engine high water (includes setup) | 30 | 120 |
| Predeclared budgets passed | yes | yes |

All imported quantities and fees checked exactly, pending inbox empty, entries
blocked. Single laptop diagnostic runs, not maximum sustained throughput, network
outage acceptance, long-history/reconnect-storm scalability or profit evidence.

## Remaining work and authority

Full starting-history/private-stream completeness, correction/settlement and
retention contracts remain unresolved; a repaired report never grants entry
authority. Explicit history start is supplied by the caller, not automatically
advanced to assume missing old executions cannot exist. Production account-wide
risk reservations, inventory exits/deadlines, selection/rankings, budget bootstrap,
Windows launch/stop arming and final integration are still required. No live CLI
or mutation executor is attached, and no live process/service was installed.
Kalshi has no usable Git metadata here; no Git diff/commit/parity claim is made.
