# Kalshi architecture: WebSocket first, CPU-efficient, scalable

Priority-3 [opening-account accounting design](DESIGN_OPENING_ACCOUNT_ACCOUNTING.md)
now has [D-068 operational release](BUILD_ACCOUNT_RECONCILIATION.md) on top of
[D-067 durable restrictions](BUILD_DURABLE_ACCOUNTING.md). Schema 5 adds explicit
baseline approval, derived cash/fee obligations and ephemeral source-fenced
release authority. Global venue handoff stays unproved; lower independent cash
ceilings avoid assuming exact venue holds. Real boundary approval and live
activation are separate. New ledgers only; no existing-ledger migration.

D-062 adds [opening-account/cash evidence](BUILD_OPENING_ACCOUNT_CASH_EVIDENCE.md)
and an [offline write-budget primitive](BUILD_WRITE_BUDGET.md) with
[bounded offline dispatcher](BUILD_WRITE_DISPATCHER.md). These remain
non-authorizing. [Source-bound inventory candidates](BUILD_DISPATCH_SOURCES.md)
now connect actual owners to the injected path with final source/stop fences.
The [write-quota source](BUILD_WRITE_QUOTA_SOURCE.md) consumes the shared guarded
read pair, preserving full method costs and read-owner validity through dispatch.
The [outcome owner](BUILD_MUTATION_OUTCOMES.md) binds 429 pauses to the original
request shard and signals existing recovery at observation and after retained
durable recording; uncertainty never releases authority or creates a retry loop.
Verified production inputs, transport and supervised runtime integration
remain unfinished. D-063 restores development in the primary session without
delegated agents or model switches unless explicitly requested again.

D-059 [command capacity/handoff design](DESIGN_COMMAND_CAPACITY_HANDOFF.md),
implemented offline under [D-060](BUILD_COMMAND_CAPACITY_HANDOFF.md), addresses
the overall review's first two priorities with bounded durable safety credits
and atomic preparation/single-use dispatch receipts. Schema 3 refuses old
ledgers without explicit migration; no production account/transport authority
is added. Existing supervisor, continuity, risk and live-disable gates below
remain unchanged. The [independent D-060 review](REVIEW_D060_ASTRA.md) identified
R1-R6; the [offline corrections](BUILD_COMMAND_CAPACITY_REVIEW_FIXES.md) add
durable authorization identity, canonical dispatch terms, source-backed reducer
authority, bounded proven-unsent reauthorization, fail-closed SENDING ownership
and O(1) hot capacity accounting with full startup reconciliation.

D-055 [S2 detailed design](DESIGN_WINDOWS_SUPERVISOR_S2.md) is the current
native-process/IPC proposal after S1 and D-048 clearance. It specifies S2A inert
lifecycle foundations followed by separately assigned S2B offline runtime and
restriction transfer. D-056 [implements S2A](BUILD_WINDOWS_SUPERVISOR_S2A.md)
offline. Its [Astra review](REVIEW_D056_ASTRA.md) identified ownership, launch,
IPC, validation, power, security, diagnostics and journal defects. D-057
[implements corrections](BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md) under the operator's
Astra fix-phase exception; independent review remains required. S2B remains
unimplemented, blocked and separately assigned.

D-050 [native Windows supervisor proposal](DESIGN_WINDOWS_SUPERVISOR.md) specifies
one process supervisor and one runtime child, durable operator control and bounded
automatic recovery. D-051 [S1 implementation](BUILD_WINDOWS_SUPERVISOR_S1.md)
adds the immutable execution-disabled transition policy and separate transactional
control journal. D-056 adds only S2A native process handles and inert IPC; runtime
integration still requires separately assigned S2B after the reviews below.
This does not establish account proof or authorize live operation.
The [D-051 review](REVIEW_D051_ASTRA.md) required policy/contract and resource-
verification fixes. D-052 [implements those fixes](BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md)
offline. The [D-052 re-review](REVIEW_D052_ASTRA.md) clears original hold/crash/
benchmark findings but requires five follow-ups before S2. D-053
[implements those follow-ups](BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md)
offline. [D-053 Astra review](REVIEW_D053_ASTRA.md) clears four D-052 findings
but requires two clock-continuity corrections.
D-054 [implements those corrections](BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md)
offline. [D-054 Astra review](REVIEW_D054_ASTRA.md) clears both clock findings
and completes S1 review. D-048 is also cleared below. D-056 now supplies S2A
native fixture evidence, not S2B runtime/reboot behavior or live operation.

D-044 [starting-account/private-stream continuity design](DESIGN_ACCOUNT_CONTINUITY.md)
has an evidence-only D-045 [Phase 1 implementation](BUILD_ACCOUNT_CONTINUITY_PHASE1.md)
whose [review findings](REVIEW_D045_ASTRA.md) are addressed by the D-046
[review fixes](BUILD_ACCOUNT_CONTINUITY_REVIEW_FIXES.md).
[D-046 re-review](REVIEW_D046_ASTRA.md) identified two shutdown findings,
addressed by [D-047](BUILD_ACCOUNT_CONTINUITY_SHUTDOWN_FIXES.md). Its
[Astra review](REVIEW_D047_ASTRA.md) verifies those exact fixes but requires
one follow-up for stop overlapping an already-active disconnect drain, now
implemented under [D-048](BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md).
[D-048 Astra review](REVIEW_D048_ASTRA.md) clears that finding in offline scope.
It does not establish a venue history/stream
barrier, opening inventory or live-entry authority.

Status: **D-021 implementation underway; component foundation only, no live trader**.
See [initial foundation](BUILD_FOUNDATION.md) and
[account-I/O integration](BUILD_ACCOUNT_IO.md) and
[owned-order/recovery evidence](BUILD_RECOVERY_ORDERS.md), plus
[event owner, quote/ranking and command components](BUILD_ENGINE_RANKING.md).
Approved D-024 accounting is implemented in the [accounting milestone](BUILD_ACCOUNTING.md).
Archived terminal-order evidence is implemented in the
[archive recovery milestone](BUILD_ARCHIVE_RECOVERY.md). D-025 adds
[automatic verified fill recovery and exit-only venue-cost fallback](BUILD_AUTO_RECOVERY.md).
Neither proves complete starting inventory or authorizes live trading.
D-026 connects reader generations, engine dispatch and recovery in the
[recovery-engine milestone](BUILD_RECOVERY_ENGINE.md), with a durable pending-fill
inbox and no attached mutation authority. Remaining proof/risk/exit integration
still blocks entries; no live reader was started during verification.
D-027 adds [inventory/risk integration](BUILD_INVENTORY_RISK.md): immutable
per-market advisory plans carry account/book/writer revisions; independent age
timers do not postpone earlier safety deadlines. Account-wide exposure and
offline compare-and-reserve run in the single writer, not on public book ticks.
No complete cash proof, live mutation dispatch or automatic forced exit is claimed.
D-028 adds [atomic local account verification](BUILD_ACCOUNT_VERIFICATION.md).
One owner transaction compares exact order/fill/reservation/position scope and
persists venue-cost observations; its revision travels with the report. Runtime
keeps history interval and ingress provenance separate from repair success.
These local consistency checks do not supply missing venue completeness guarantees.
D-031 [exposure calibration](BUILD_POLY_EXPOSURE.md) uses Poly's verified local
reference of 20 at size 10: $300 aggregate, $90 per-market, with the separate
$500 capital and 30-entry ceilings unchanged. Reference capacity calibrates the
budget, not live occupancy; actual Kalshi entry breadth remains limits-driven.
D-032 [inventory exit planning](BUILD_INVENTORY_EXITS.md) adds exact passive and
bounded IOC proposals, durable attempt projection, ingress freshness and timer
evaluation. Verified live fee/event-time producers and dispatch are not built;
all plans remain advisory and execution-disabled.
D-033 [structured diagnostics](LOGGING_AND_ERRORS.md) adds a bounded shared
JSONL sink and component failure/transition instrumentation. One Windows-owned
worker rotates local logs; health failures stop the execution-disabled runtime,
not venue orders. The future launcher must explicitly own this shared lifecycle.
D-034 [market inputs](BUILD_MARKET_INPUTS.md) adds stream-first field overlays,
bounded shared missing-field reads and optional runtime publication of advisory
exit terms. Real timing reviews/member profile remain unfinished; D-036 below
adds refresh scheduling. No live feed or trading authority is established.
D-035 [durable history receipts](BUILD_HISTORY_COVERAGE.md) records completed
enumeration scope/digests and provides bounded local gap inspection after restart.
Omitted remembered fills block a repaired label. Historical receipt coverage is
not current stream authority, a chosen launch boundary or complete account proof.
D-036 [metadata scheduling](BUILD_METADATA_SCHEDULER.md) adds one optional
runtime-owned bounded coordinator: ACK bootstrap, coalesced changes, expiry
revocation, retry exhaustion and generation-safe shutdown. The existing shared
[GET budget](RATE_LIMITS.md) now prioritizes account reads, reserves background
headroom, refreshes explicit quota documents and pauses on every 429. No lock is
held while waiting for tokens; bounded followers use queue-change events.
D-039 implements both phases of the [quota freshness design](DESIGN_QUOTA_FRESHNESS.md):
guarded leases/explicit refresh and optional supervised scheduling/runtime holds.
See [implementation evidence](BUILD_QUOTA_FRESHNESS.md); independent Astra review
found three issues. D-040's [design correction](DESIGN_QUOTA_REVIEW_FIXES.md)
was implemented under [D-041](BUILD_QUOTA_REVIEW_FIXES.md). [Astra re-review](REVIEW_D041_ASTRA.md)
clears the original findings with two low-priority follow-ups, now fixed under
[D-042](BUILD_QUOTA_REVIEW_FOLLOWUPS.md) and [cleared](REVIEW_D042_ASTRA.md). Production probe configuration,
write budgets and launch remain open.
Boundaries below describe
the full design; they are not a claim that every component is connected or built.
Standing operator decision D-014, September 19, 2026. D-021 supersedes D-011's
planning-only restriction, retaining no paper trading and no live activation.
Performance targets and
complete risk/exit policy are not yet accepted. D-016 adds multiple connections,
10-contract entries, a 30-resting-entry ceiling excluding position-management
orders, and fixed six-hour $25 settled-loss stops. See the
[multi-WebSocket recommendation](MULTI_WEBSOCKET_DESIGN.md), [STATUS](../STATUS.md) and
[DECISIONS](../DECISIONS.md) for current truth and authority.

## Required approach

D-019: run natively on Windows, not Ubuntu/WSL. D-020 requires executable
Polymarket code evidence; see [inventory audit](POLYMARKET_INVENTORY_CODE_AUDIT.md).
The multi-WebSocket proposal records Windows lifecycle/storage requirements.

WebSocket supplies primary live information. REST supplies required information
that documented streams do not provide, including missing bootstrap/history
or reconciliation evidence. Avoid duplicate steady-state polling. CPU efficiency
and scalability are acceptance requirements, not results already established.

## Source map

This division follows the current published event-contract interfaces. Check
the exact fields and semantics against the API reference before coding.

| Needed information | Primary source | Justified REST use / limitation |
|---|---|---|
| Full book and depth changes | `orderbook_delta`, initialized by `orderbook_snapshot` | Bounded fetch if required state cannot be obtained/validated from stream; first consider stream `get_snapshot` |
| Ticker and public trades | `ticker` / `trade` | Missing history or metadata, not duplicate continuous polling |
| Own order lifecycle | `user_orders` | Complete initial inventory, missing fields, gap/ambiguity proof |
| Own executions | `fill` | Initial/history/gap backfill with durable execution-ID deduplication |
| Own positions | `market_positions` | Complete startup state and reconciliation not proven by updates |
| Market/event lifecycle, order groups | Documented lifecycle/group streams | Missing full definitions, schedules or state |
| Incentive definitions, target, discount, dates and pools | REST `/incentive_programs` | No documented incentive stream; cache/version, bounded refresh and pagination |
| Market/event/series metadata, ticks, fees | Stream fields where available; REST for remainder | Full definitions/fee changes, cached by ID/version and invalidated on relevant changes |
| Cash, account limits and endpoint costs | REST where no equivalent documented account stream exists | Centralized bounded reads; no per-market duplicate polling |
| Final personal reward credits | No documented public API found | Scores and balance differences cannot replace Rewards/Activity credit evidence |

Sources checked September 19: [books](https://docs.kalshi.com/websockets/orderbook-updates),
[orders](https://docs.kalshi.com/websockets/user-orders),
[fills](https://docs.kalshi.com/websockets/user-fills),
[AsyncAPI](https://docs.kalshi.com/asyncapi.yaml),
[incentives REST](https://docs.kalshi.com/api-reference/incentive-programs/get-incentives).
Full contracts: [local API reference](KALSHI_API_REFERENCE.md).

This is a data-source preference, not a claim that WebSocket places orders.
Future authorized create/amend/cancel commands use documented event-order REST
endpoints; streams confirm changes. No new FIX dependency is selected here.

## Proposed component boundaries

```text
WebSocket readers ----+
                      +--> validation + bounded queues --> state coordinator
REST missing-data ----+                                      |
read service                                                v
                                            changed-market / deadline scheduler
                                                            |
                                                            v
                                                   strategy --> risk gates
                                                            |
                                                            v
                                              durable intent --> order executor
                                                            |
                                               events / reconciliation

Local committed state --> read-only metrics / reports (no mutation authority)
```

- Readers own transport/normalization, not strategy or execution.
- The coordinator owns projections, deduplication, source generation,
  freshness and continuity. Connection liveness is not complete account proof.
- Apply every necessary book delta; downstream decisions can collapse changes
  into one evaluation of the latest valid book.
- Independent deadlines service inventory, risk and expiry without waiting for
  a book change. Background discovery must not delay safety processing.
- REST reads share a token-budget coordinator, cache and in-flight deduplication.
  Budgets follow Kalshi's current costs and shard scope, not Polymarket numbers.
- One mutation authority prevents overlapping replacements/duplicate creates.
  Persistence preserves intent-before-mutation and idempotent fills.
- Reports are downstream; formatting and history scans cannot hold execution
  or multiply venue requests.

## Recovery contract to finish before implementation

1. Initialize required scope; do not assume a newly connected stream includes
   all preexisting orders, positions, cash and history.
2. Track sequences where available, generations, times and scope. Do not assume
   every channel has the same ordering or snapshot guarantees.
3. Gap, stale source or queue overflow invalidates affected proof and blocks
   new risk. Prioritize safety work using trustworthy available state.
4. Prefer stream resynchronization; use bounded REST for missing proof.
   Reconcile snapshots/buffered events without rollback or double counting.
5. Resume only with coherent fresh state and adequate capacity. Reconnection
   alone is not recovery evidence; unresolved state remains blocked.

These are design recommendations under the source policy, not permission to
run an unvalidated automatic REST-only trading mode.

## Performance/scaling acceptance to specify

Each implementation plan must define:

- active markets, subscriptions, book depth, events/sec and burst workloads;
- CPU/core and memory budgets, event-loop lag and latency percentiles;
- queue bounds, cache limits, processing capacity, REST tokens and headroom;
- reconnect storms, delayed storage, throttling and laptop sleep behavior;
- baseline and increased offline workloads with unchanged exact outputs,
  ownership and safety deadlines;
- graceful capacity reduction and admission rules before adding markets.

No thread/process per market or full-universe scan per event by default.
No arbitrary performance claims or accepted market count is introduced here.
Offline correctness/performance checks are not paper trading.

## What is not copied from Polymarket

Its document layout and separation of readers, coordinator, execution and
reporting are useful patterns. Its explicitly selected REST account mode,
private-stream incidents, budgets, market counts, quote size, loss windows and
deployment commands are project-specific. None becomes Kalshi policy by analogy.
No shared runtime, database or secret file is introduced.
