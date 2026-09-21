# D-036 — Bounded metadata refresh scheduler

Scope: native Windows, execution-disabled implementation, September 20, 2026.
No credentials, real account/network reads, live sockets, orders or paper process.

Review update: [Astra review](REVIEW_D036_ASTRA.md) recorded four reproducible
defects beyond the initial 707-test suite. Sol implemented the four fixes and
added nine regressions across input, scheduler and rate suites. The subsequent
[Astra re-review](REVIEW_D036_ASTRA_R2.md) cleared the four fixes in scope with
87 focused tests and an integrated reconnect probe. STATUS records Sol's prior
final complete-suite outcome; this is not live-readiness approval.

## Predeclared contract and checks

Reuse D-034 source contracts and shared GET token budgets. No new endpoint or
venue semantics. Bootstrap only after lifecycle subscription acknowledgment;
coalesce relevant lifecycle changes and refresh expired/missing dependencies.
Sufficient stream fields reuse the existing cache; no per-book metadata polling.

One scheduler with at most two refresh tasks; bounded unique ready/deadline state
for the fixed <=1,024-market universe and compacted lazy heap <=2x scope.
No per-market loop/thread. New work yields to pending private/recovery work.
Three consecutive failures exhaust a market's attempts; lifecycle notifications
and reconnect ACKs must not reset the budget or bypass backoff. Successful refresh
or explicit control-plane retry may reset it. No automatic rearming of trading.

Revoke expired terms before waiting for worker capacity. Keep UTC and monotonic
expiry bounds, shorten at reviewed/scheduled changes and market open/close.
Clock discontinuity must fail closed. Stop/disconnect cancels pending refresh
consumers and invalidates terms; old generations cannot publish into a new one.
Own scheduler/service shutdown but not the caller's shared REST transport.

Tests: ACK/bootstrap, deduplication, event fanout, warm stream updates without
REST, expiry, blocked reviews, cooldown/exhaustion, disconnect/reconnect, slow
reads, overload priority, unexpected faults, clock jumps and shutdown. Two
in-memory safeguard reversals. Resource fixtures: 30/120 managed markets,
shared dependencies, cold bootstrap then 100 change requests per market;
<=2 refresh workers, <=2N heap, exact baseline REST counts, no extra warm reads,
wall <3/10 seconds, event-loop lag p99 <50ms, Python peak <16MiB. Offline software
checks, not simulated profitability or production capacity guarantees.

## Implementation

`MetadataScheduler` owns one bounded coordinator and up to two refresh consumers.
Runtime starts/joins it only when the optional D-034 service is supplied. Initial
subscription ACK queues the managed universe; repeated ACKs do not reset retries.
Lifecycle/review/profile changes coalesce by ticker. A compacted deadline heap
handles provenance expiry, reviewed deadlines and market open/close boundaries.
Pending private events and active recovery defer new refresh dispatch, but not
expired-term revocation. Stream-sufficient updates reuse cached dependencies.

Expected failures back off (1/2/4 seconds for the default three-attempt budget).
Exhausted markets require an explicit control-plane retry; reconnect and ordinary
events cannot reset the budget. Explicit retry preserves an existing cooldown and
does not approve a review/profile. Per-market minimum spacing is 50ms; each
consumer has a 30-second timeout. Unexpected errors and discontinuous clocks
fail closed through runtime supervision. The 250ms clock/stop watchdog performs
no REST calls or whole-market scans. No new entry/exit execution authority exists.

Disconnect cancels consumers, revokes terms and clears queued work; shared reads
remain owned by their services and cannot publish across generations. Shutdown
joins the scheduler and metadata service, not the caller's shared REST owner.
Runtime reports scheduler counters and shared read-budget status. Manual refresh
cannot race a running scheduler; explicit queued refresh remains available.

Metadata can now dirty a market before its first book. Engine processing skips
markets without a snapshot until the normal snapshot event marks them dirty;
it does not fabricate a book. Canceled consumers use non-propagating task waits
with safe exception consumption, avoiding Python 3.14 shield exception logging.

The operator's additional rate-limit request is implemented in the existing
shared GET service; see [rate-limit contracts and results](RATE_LIMITS.md).
No quota is multiplied by the number of markets, workers or WebSockets.

## Verification results

The initial 24 scheduler tests cover bootstrap, expiry, stream reuse, overload, cooldown,
clock faults, reconnect generations and actual injected runtime ownership.
13 read-budget tests cover the rate-limit additions. In-memory reversals of
expired-term revocation and shared 429 throttling each produce the intended
assertion failure with no test errors; original code is restored immediately.

`scripts/benchmark_metadata_scheduler.py`, injected reads/real Windows clocks:

| Managed markets | Cold reads | Extra warm reads | Wall / CPU s | Peak bytes | Loop lag p50 / p95 / p99 ms | Worker / heap peak |
|---:|---:|---:|---:|---:|---:|---:|
| 30 | 35 | 0 | 0.0764 / 0.0625 | 174,413 | 0.438 / 9.719 / 9.719 | 2 / 60 |
| 120 | 125 | 0 | 0.1694 / 0.1406 | 438,274 | 0.386 / 1.091 / 14.966 | 2 / 240 |

Both workloads pass all predeclared budgets. Counts are fixture calls, not actual
Kalshi traffic; this is neither paper trading nor a live latency/throughput claim.
Final full-suite outcome is recorded in `../STATUS.md`. Preflight remains false
(native exit 2), with no credential/network use or files created.

Sol reran this unchanged workload after R1-R4: 30/120 markets still make exactly
35/125 baseline reads and zero extra warm reads, with worker peak 2 and heap peaks
60/240. Wall time was 0.0756/0.1527s; CPU 0.0156/0.1562s; peak Python bytes
181,707/442,905; loop lag p99 13.813/2.489ms. Both pass the original bounds.
The input and scheduler focused suites now contain 44 and 25 tests respectively.

## Remaining boundaries

Real account fee profile, reviewed market timing, production account/stream/cash
proof and launch supervision are still required. D-039 subsequently adds optional
[automatic quota-age/grant-expiry enforcement](BUILD_QUOTA_FRESHNESS.md); the
future separate write-budget transport remains unimplemented. No live socket, order, cancel, account call, old-ledger import,
market/risk choice, launch boundary or Polymarket modification occurred.
