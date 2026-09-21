# D-039 — Quota leases and automatic refresh

Date: September 20, 2026. Native Windows, execution disabled.
Operator explicitly authorized BOTH phases of the
[Astra design](DESIGN_QUOTA_FRESHNESS.md). Both phases are implemented; independent
[Astra review](REVIEW_D039_ASTRA.md) found three P2 issues and a test timeout.
D-041 [fixes and current verification](BUILD_QUOTA_REVIEW_FIXES.md) are complete;
independent re-review is pending. Results below preserve the earlier implementation
run evidence. This document is not live-readiness approval.

## What changed

- `quota.py`: explicit probe/policy/scope types, bounded full document validation,
  immutable candidates/leases and a single-loop guard. Numeric returned Read
  settings determine the bucket, never the tier label. Earliest finite Predictions
  grant expiry limits validity; other-lane grants do not. Absent expiry is allowed;
  null Predictions expiry blocks pending contract clarification.
- `rest.py`: opt-in guarded mode on an unused service, same-bucket conservative
  probes, control admission and priority slot tickets, validation before every
  actual attempt, revision-bound response rejection, and a shared active-work
  clock watchdog. Ordinary callers cannot gain probe privilege via read arguments.
  Control requests are costs then limits, with a unique owner scope. A timed-out
  pair retains ownership until its actual worker drains; no overlapping retry.
- `quota_supervisor.py`: one refresh owner, coalesced triggers, scheduled refresh,
  bounded backoff/exhaustion, explicit retry retaining cooldown, clock-fault hold
  and irreversible stop. 401/403 requires attention after the first pair failure.
- `runtime.py`: optional supervisor ownership on the same REST service, quota
  status/blockers, once-per-transition invalidation and a quota wait for recovery.
  Restoring quota does not clear independently exhausted recovery or risk holds.
- `metadata_scheduler.py` and `account.py`: preserve typed quota holds instead of
  treating infrastructure unavailability as failed market/ownership evidence.
  Healthy private-stream fill processing continues to the durable writer.
- `observability.py`: registered quota transition/retry/fault codes. No raw grants,
  credentials, API responses or exception messages are logged.

No order endpoint, write bucket, tier-upgrade call, credential loader, launch
command, live connection or mutation was added. Existing unmanaged fixtures remain
available but runtime labels them unmanaged; they cannot establish live readiness.

## Lifetime and ownership

Defaults implement the design's local safety policy: 300s maximum observation age,
90s refresh lead/minimum candidate remaining lifetime, 5s grant-expiry margin,
2s clock-divergence tolerance and 65s pair timeout. Probe settings have NO default:
the future launcher must inject an explicitly reviewed allowance. Benchmark probe
settings are fixture values, not a production entitlement or current account tier.

Age begins before the first pair dispatch, conservatively including queue time.
Both UTC and monotonic deadlines must remain valid; equality expires. Regressions
and excessive drift are sticky faults. Stale/late evidence cannot extend its own
validity. Restart requires new evidence, not persisted tokens or an old lease.

Guard attachment requires unused shared reads, the same clock object, at least
three admission entries and two wire slots. At default capacity, background has a
30-entry bound and ordinary requests leave a control entry free. Control receives
priority for the next available wire/token opportunity; already dispatched work
cannot be preempted. No guarantee of response latency is implied.

All requests, including recovery probes, debit the SAME bucket. Entering probe
mode zeros the local estimate once, clamps against lower retained limits and
higher retained route costs, and preserves the longest 429 pause and spent count.
Repeated status calls do not reset refill clocks. Impossible costs block rather
than being truncated. Published capacity is never assumed to be available tokens.

At startup, create one TokenBudget/RestReads, attach one QuotaGuard with the same
clock and shared diagnostic sink, then create one QuotaSupervisor. Pass that exact
supervisor/read service to optional RecoveryRuntime integration. Constructors
perform no network or filesystem I/O. Runtime owns supervisor tasks; its caller
still owns closing RestReads and the writer. Do not attach another service per
socket, market or shard. Clock faults require a new owner, not a reconnect reset.

Three failed pair attempts exhaust automatic refresh; backoffs are 5/15s plus
bounded jitter, then a 60s cooldown. Each endpoint keeps its existing three-wire-
attempt cap. Public explicit refresh delegates to the supervisor and cannot
bypass exhaustion. Healthy WebSockets are not stopped by an ordinary quota hold.
No fresh lease can independently enable entries or production exits.

## Verification

46 new tests pass: 31 quota/parser/transport and 15 supervisor/runtime tests.
Coverage includes grant bounds/lanes/nulls, strict age boundaries, late and
superseded evidence, shared throttling, saturated admission, held token/slot waits,
consumer cancellation, pair timeout drain, restart/stop, scope changes, retry
exhaustion, logging failure, metadata holds and durable private fills during an
authentication/quota outage. Existing risk and recovery tests remain applicable.

Two in-memory guard reversals were detected by failing regression assertions:
removing expiry enforcement and resetting a late candidate's observation start.
Methods were restored immediately; source files were not rewritten for reversals.

The exact final complete suite passes: **762 tests in 64.218 seconds**, after the
last source/test edit. The outcome is also recorded in `../STATUS.md`. An intermediate
755-test suite passed before the final seven regressions were added; it is not
the final verification claim. Preflight remains `live_ready=false`, native exit 2,
without credential/network access or file creation.

### Quota resource fixture

`scripts/benchmark_quota_freshness.py`, injected clocks/wire on native Windows:

| Mode | Callers | Accepted / refused | CPU s | Peak bytes | Loop lag p99 ms | Gate check p99 ms |
|---|---:|---:|---:|---:|---:|---:|
| Explicit refresh | 30 | 30 / 0 | 0.2969 | 468,890 | 11.993 | 0.068 |
| Explicit refresh | 120 | 31 / 89 | 0.3281 | 412,120 | 9.385 | 0.051 |
| Automatic owner | 30 | 30 / 0 | 0.2812 | 366,237 | 9.390 | 0.048 |
| Automatic owner | 120 | 31 / 89 | 0.2812 | 382,834 | 9.294 | 0.038 |

Each fixture made exactly two bootstrap quota GETs; 1,000 coalesced notifications
did not multiply them. Each wire GET charged 10 fixture tokens (320/330 total).
Maximum observed wire slots: 2; admission: 30/31; zero leftover tasks or waiters.
10,000 guard/status checks are included. All predeclared resource bounds pass.
The 120-caller burst deliberately exercises admission rejection, NOT 120 completed
simultaneous requests. The automatic fixture holds 30/120 metadata scopes without
stream ACK; full healthy market refresh is exercised by the unchanged D-036
benchmark, and actual private-stream ingress by injected runtime tests.

The real 10-second idle supervisor check produced ten health wakes and zero extra
GETs. Token/wire wait times are printed separately by the diagnostic; these are
offline engineering measurements, not venue latency, live capacity or income.

### Unchanged D-036 regression workloads

Both existing 30/120 benchmarks passed their original budgets:

- Metadata: 35/125 cold reads, zero extra warm reads; CPU 0.0312/0.1406s,
  peak 180,373/449,023 bytes, loop lag p99 12.867/2.871ms; worker peak two.
- Rate limiting: exactly 300/1,200 tokens; wall 1.5619/6.0618s, CPU
  0.0156/0.5625s, peak 120,943/378,376 bytes, loop lag p99 14.769/15.383ms.

## Remaining boundaries and review handoff

No current account quota or probe setting was fetched/approved for production.
Local observation TTL cannot guarantee that Kalshi has not revoked a grant early
or changed costs between requests. An in-flight request cannot be recalled on
expiry; late success is rejected as proof and late 429 still pauses the bucket.
Blocking worker I/O retains its existing bounded transport behavior and can delay
shutdown; cancellation never claims that the physical request disappeared.

Production write limiting/transport, account/history/private-stream/cash proof,
actual market/fee/time approvals and supervised live launch remain separate gaps.
Capital, order sizes, entry caps, loss windows, reducers and exposure are unchanged.
No keys, venue calls, orders, cancellations, history imports or Polymarket changes.

Git metadata remains unavailable. Review present source/tests and named scope;
do not claim a verified Git diff. Next role: Astra independent review of both
phases, especially dispatch/provenance, refresh draining, priority, clocks,
quota/recovery interactions and shutdown. Do not advance to live operation.
