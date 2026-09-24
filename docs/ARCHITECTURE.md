# Kalshi architecture: WebSocket first, CPU-efficient, scalable

Paused stop scheduling queues owned-entry keys directly to the existing cancel
dispatcher without requiring a management plan. Keys grant no mutation authority;
the writer still validates each exact order. Bulk order enumeration obtains one
transaction-local managed-exit classification set, preserving all individual
order, fill and intent checks. Full recovery collects financial documents with
its final snapshot; paused refresh gives the supervisor the normal fresh-report
interval to finish its flat check before any further renewal.

D-113 separates routine startup/refill renewal from full recovery. After a
successful operational release, a process-local anchor retains exact source
versions, account signature and at most 128 history receipt IDs. Renewal joins
one fresh snapshot with an empty elapsed history tail. Independent cash,
funding and settlement documents are collected concurrently inside that same
snapshot fence and passed to the writer-owned accounting release. The account
balance snapshot is reused as cash evidence rather than fetched serially. It never
refreshes a lease by copying timestamps. Any changed source/economics, missing
proof, nonempty/omitted tail, timeout or bounded-chain exhaustion falls back to
full recovery. D-109's full-cap snapshot-only scheduling optimization retains
precedence; no extra financial enumeration is added to that steady path.

Metadata workers no longer defer solely because full recovery is running;
private ingestion and account-wide quota/safety priority remain intact.
Market-only observations can advance historical coverage and advisory priority
hints during account gaps, but carry no dispatch proof. Current ownership,
inventory, account, book and accounting joins remain mandatory for executable
selection. No risk, freshness, price or reward threshold is relaxed.

D-110 adds [persistent transient recovery and fresh quote rebuilding](BUILD_UNATTENDED_RECOVERY.md).
All readers retain one bounded owner across capped retry rounds; classified REST
transport failures retry after capped cooldowns. Unexpected death still recovers
flat in recovery-only mode, then the still-armed supervisor launches a fresh
normal child to re-rank and rebuild through ordinary gates. Manual stops,
ambiguity and integrity/economic holds never auto-resume. Superseded observation
archives roll into a cumulative hash commitment; exact economic evidence remains.

D-109 bounds steady full-cap work without weakening recovery. Only an exact
flat account at the resting-order cap, with complete ranking and exact owned-
order joins, may use the light account-snapshot refresh and owner-only deep
evaluation scope. All WebSocket events are still applied. Any account, writer,
ingress, dispatch, window or economic change drops the scope and invokes the
ordinary full recovery. Superseded non-economic recovery observations use a
bounded exact compressed archive; current operational and economic evidence
remains in the hot journal.

D-104 separates book transport scale from metadata scheduling. Broad discovery
uses four bounded shared metadata workers, with due inventory/order/maintenance
owners ahead of optional candidates; narrow and recovery modes retain two. This
does not add per-market loops or writers. During shutdown, liveness-only parent
messages may complete the exact terminal fence after the stop latch, but no
admission or mutation authority survives it.

D-103 [repairs exit/coverage/priority behavior](BUILD_EXIT_COVERAGE_PRIORITY.md).
Normal broad discovery uses four measured deterministic book shards. Initial
entry permission requires complete reasoned coverage or enough current $2+
candidates to fill every available pair slot; an early release remains
priority-only until coverage completes. Passive GTC exits carry venue-valid
`reduce_only=false` while exact durable managed-exit proof and a single-create
transport arm preserve reducer authority. Due IOC stays reduce-only and can
rearm one exhausted recovery at the existing safety boundary.

D-098 [incumbent maintenance](BUILD_ORDER_MAINTENANCE.md) adds one bounded
same-program withdrawal/re-entry policy ahead of existing selection/dispatch,
never another writer or scanner. Actual source joins and terminal/fill proof
remain mandatory; safety/exits precede maintenance. Per-program tracker output
is advisory. Qualifying owners are not replaced for better global rank.

D-096's [initial combined-ranking checkpoint](BUILD_INITIAL_RANKING.md), amended
by D-103 above, delays only normal broad-mode entries. Book shards and metadata
remain concurrent; current eligibility/dispatch proofs remain separate from
historical coverage. Inventory/safety work never waits.

D-094 [independent Windows hosting](BUILD_HOST_CONTINUITY.md) separates the
on-demand supervisor from the launching terminal/job. The existing exact child,
recovery fences and single account writer remain unchanged. Local status probes
protected process-role presence; saved snapshots are not liveness/account proof.

D-093 [broad reviewed discovery](BUILD_BROAD_DISCOVERY.md) supersedes normal
live subscription rotation below: up to 1,024 books on configurable shards,
with D-103 preparing four after measurement, plus shared bulk
missing-field metadata and one bounded ranked-entry handoff. Trading/account
capacity stays unchanged. Recovery-only retains the narrow ownership path.

D-091 [repairs exploration coverage](BUILD_DISCOVERY_COVERAGE.md): actual joined
scope, not a proposed slate, advances the bounded pending queue. Available-pair
refill uses a 30-second minimum dwell independently of catalog refresh. Existing
subscription ownership, quotas, economic filters and mutation authority remain.

D-087 [restores advisory lifecycle connectivity](BUILD_LIFECYCLE_RECONNECT.md)
after bounded attempt rounds. Disconnect still revokes all lifecycle-derived
authority; account/book exhaustion semantics and metadata retry holds are unchanged.

D-086 [repairs reward sources](BUILD_REWARD_SOURCE_REFRESH.md): one shared
1,000-row incentive query and a connection-owned, bounded quiet-book snapshot
controller. Responses retain normal generation/sequence/depth validation and
transport ingress timestamps; requests never grant freshness or order authority.

D-079 adds [bounded automatic candidate preparation](BUILD_AUTOMATIC_CANDIDATES.md)
ahead of D-078. Public REST supplies information unavailable from the live book
stream: current incentive definitions, complete rules and primary milestones.
It creates at most 1,024 exact candidate bindings and 128 initial book
subscriptions. Fresh order books remain WebSocket-owned and the existing
competition-aware selector remains final; no per-market REST book scanner is
introduced. Candidate authority is not subscription or order authority.

D-081's [supervised foreground composition](RUN_LIQUIDITY_BOT.md) now launches
D-077's runtime through one fixed native child and explicit process-local live session, preserving
accounting/source/quota authorization. D-078 attaches the existing admission
owner with a separate reviewed candidate registry and optional initial seed
scope; [live selection](BUILD_LIVE_SELECTION.md) never approves unknown rules.
It preserves owned markets, resolves fresh metadata and requires snapshots
after joined reader replacement. The fixed S2B fixture remains isolated below.
Production wiring is implemented, but live venue launch and observed production
recovery remain unverified and require separate operator authority.

D-075 [implements the fixed offline S2B runtime and recovery fence](BUILD_WINDOWS_SUPERVISOR_S2B.md).
The native child owns one injected `RecoveryRuntime`, disposable ledger and fake
readers; no signer/network/mutation client can be supplied. Restrictions load
before fake requests, terminal cleanup joins runtime/readers/writer, and the
parent durably commits bounded holds/cooldowns before ACK. Missing terminal
evidence blocks relaunch. This closes the designed offline S2B phase, not
production runtime construction, real-input readiness or live launch authority.

D-072's [entry-pair dispatch and mutation transport](BUILD_ENTRY_DISPATCH_TRANSPORT.md)
connects a current D-069 selection to one atomic local two-leg reservation and
one Kalshi V2 batch request. The writer remains the sole risk/durability owner;
the dispatcher reserves the documented per-order write cost from the unscoped
batch bucket and rechecks source, accounting and quota evidence at the send
edge. Per-row venue outcomes are not treated as atomic: mixed or unidentified
results latch recovery and are never retried. The same bounded adapter exposes
single create and cancel operations for existing inventory exits. The D-081
fixed production child constructs this adapter only after explicit `--live`
launch authority; offline component tests confer no such authority.

D-071's [automatic admission owner](BUILD_MARKET_ADMISSION.md) now connects those
candidate plans to joined book-reader replacement. One shard changes at a time;
account/lifecycle connections remain independent. Exact flat/clear proof is
rechecked after teardown; new book generations require snapshots. Metadata
scope changes only when existing work is idle, retaining retry exhaustion.
This is subscription authority in an explicit offline runtime attachment,
not order authority or production launch clearance.

D-070 adds [Poly-style candidate discovery and reward telemetry](BUILD_REWARD_TRACKER.md):
protected owners plus bounded ranked-head/rotating-tail exploration, no fixed
market pool. Per-program sampled estimates reuse existing actual-order sources;
unknown reflection stays unknown. Explicit asynchronous checkpoints are separate
from financial accounting. Neither discovery plans nor estimated payout progress
change subscriptions, risk, exits or mutation authority.

D-069's [advisory selection component](BUILD_MARKET_SELECTION.md) reuses existing
runtime/management observations, coalesced evaluations and risk primitives.
Selection never becomes a second mutation owner. [Bounded incentive discovery](BUILD_INCENTIVE_DISCOVERY.md)
now supplies immutable, expiring catalog observations through the shared REST
budget. D-071 supplies subscription rotation above; verified resting-order
reflection remains explicit work; D-072 supplies entry-pair dispatch but no
authority is conferred by ranking or benchmarks.

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
The [injected lifecycle service](BUILD_DISPATCH_LIFECYCLE.md) attaches to runtime
task supervision, drains accepted outcomes before reader teardown and preserves
UNKNOWN on fixture restart. D-075 now tests this ownership inside the fixed
offline S2B child; it does not create live mutation authority.
Production mutation transport now exists behind D-072's explicit live-session
boundary. D-081 supplies native supervised runtime integration; verified live
acceptance remains unfinished. D-063 restores development in the primary session without
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
[implements corrections](BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md). D-074's
[resource follow-up](BUILD_WINDOWS_SUPERVISOR_RESOURCE_FIXES.md) preserves the
security/clock contracts and clears every declared 60-second/100-cycle S2A
resource target. D-075 implements the separately assigned fixed offline S2B
runtime/restriction phase with native crash/cleanup and 30/120-market evidence.

D-050 [native Windows supervisor proposal](DESIGN_WINDOWS_SUPERVISOR.md) specifies
one process supervisor and one runtime child, durable operator control and bounded
automatic recovery. D-051 [S1 implementation](BUILD_WINDOWS_SUPERVISOR_S1.md)
adds the immutable execution-disabled transition policy and separate transactional
control journal. D-056 adds S2A native process handles and inert IPC; D-075 adds
the fixed offline S2B runtime/restriction integration. D-081 adds a separate,
fixed production profile whose crash replacements are recovery-only. This does
not establish current account proof or authorize live operation.
The [D-051 review](REVIEW_D051_ASTRA.md) required policy/contract and resource-
verification fixes. D-052 [implements those fixes](BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md)
offline. The [D-052 re-review](REVIEW_D052_ASTRA.md) clears original hold/crash/
benchmark findings but requires five follow-ups before S2. D-053
[implements those follow-ups](BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md)
offline. [D-053 Astra review](REVIEW_D053_ASTRA.md) clears four D-052 findings
but requires two clock-continuity corrections.
D-054 [implements those corrections](BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md)
offline. [D-054 Astra review](REVIEW_D054_ASTRA.md) clears both clock findings
and completes S1 review. D-048 is also cleared below. D-056 supplies S2A native
fixture evidence; D-075 adds offline S2B runtime behavior. Real suspend/reboot
and live operation remain unverified/unavailable.

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
| Own order presence in aggregate book | No identifying public-book field | Bounded account-wide `/portfolio/orders/queue_positions` join; short-lived and non-atomic, estimate telemetry only |
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
