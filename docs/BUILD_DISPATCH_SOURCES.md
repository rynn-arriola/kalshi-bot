# Source-bound inventory dispatch — priority 4, D-062

2026-09-21. Offline build continuation under D-021/D-032/D-062; no new
strategy, account authority, live transport or runtime activation.

## Scope and ownership

`InventoryDispatchSource` uses the actual `RecoveryRuntime` account, book,
inventory manager and writer owners. Its factory binds the source's refresh and
synchronous proof callbacks to the sole injected executor and dispatcher.
It supplies only already-selected safety cancels, exact passive reducers and
due price-capped IOC reducers. No entries, independent planner, REST polling,
background workers or production adapter. `offline_fixture=True` is mandatory.
Blocked, waiting, attention and deferred exit modes cannot be bypassed by
using their passive subplans. Missing current proof returns no candidate.
This deliberately does not invent an emergency fallback strategy.

The dispatcher retains market keys, not authorizations. The producer holds at
most one immutable proof (plan identity, original account observation age,
canonical request). It checks sources after each await; the executor checks
again before/after SENDING and after its synchronous quota hook. Only the
writer's prepare and SENDING revision advances are permitted by the source
fence; exact single-use receipts remain mandatory. Concurrent refresh revokes
both candidates. Deadlines/retry windows, terms replacement, stale ingress,
new account/book epochs, intervening writes and shutdown revoke the decision.
The trading-close clock is checked separately even when an earlier forced
deadline is already past and the next advisory timer is metadata expiry.

Cancel ACK is not terminal/fill proof. Ambiguous sends remain UNKNOWN without
retry. Caller cancellation retains the one dispatch task through durable
outcome recording. Stop before SENDING aborts unsent preparation; stop after
SENDING blocks invocation and retains the conservative UNKNOWN hold. Stop does
not cancel a venue order or flatten inventory. Close joins already-invoked work.

## Field sources and boundaries

| Field | Existing owner/source | Validity/recovery |
|---|---|---|
| Position, basis, order scope, exit journal | Indexed per-market writer view, owned private fills/orders and reconciled snapshot | Writer epoch/revision; current exact account agreement; pending evidence blocks |
| Bid/ask, depth | Existing public WebSocket book owner | Generation/revision, no queued updates, ingress age <=5s; recover/resnapshot on loss |
| Account route/subaccount | Current audited position or durable cancel evidence | Exact explicit exchange index; never guessed/auto-routed |
| Tick bands, event deadline, fee bound | Existing `ExitTerms` metadata producer | Same immutable object, valid lifetime, action deadline; no inferred event clock/fee |
| Quota | Existing injected `WriteBudget` | Account-wide verified-scope contract; real ingestion and owned 429 lifecycle still queued |

No new information request is introduced. Existing recovery/control-plane REST
fallbacks remain responsible for fields unavailable through adequate streams.
The real fee membership/rules review and quota ingestion are not completed by
synthetic terms/quota fixtures.

Current official event-order v2 operations and schemas were checked by public
HTTPS on 2026-09-21 (OpenAPI 3.30.0):
[create](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) and
[cancel](https://docs.kalshi.com/api-reference/orders/cancel-order-v2.md).
Existing adapters retain YES-price bid/ask, exact decimal count, explicit routing,
reduce-only, GTC/post-only versus IOC/no expiration, and nonterminal cancel ACK.
No authenticated request or book-price semantic change was made.

## Resource acceptance (declared before measurement)

Disposable synthetic 30/120-market scopes, actual owners, 8 sequential bursts
of candidate refreshes. One pinned proof, no per-consumer queues, no REST,
indexed per-market writer reads rather than a portfolio query per book tick.
Targets: candidate p99 <100ms, event-loop lag p99 <50ms, traced allocation peak
<32MiB, CPU time <50ms per refreshed key, and manager/proof bounds preserved.
Measure p50/p95/p99, wall/CPU time, loop lag, allocation and reader backlog;
report these as component fixtures, never live throughput or profitability.

## Verification

Native Windows commands:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bot_dispatch*.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B scripts/benchmark_dispatch_sources.py
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

Final focused dispatcher/source suite: **42 passed**. The tests use actual
writer/account/management/book/executor owners, synthetic immutable metadata,
temporary ledgers and an injected no-network transport. Cases include both
inventory directions, exact fractional/partial size, explicit exchange route,
cancel before IOC, missing fees/terms/account proof, ACK without terminal proof,
stale source awaits, intervening writer revision, plan/epoch replacement,
deadline and trading-close crossing, mutable request rejection, concurrent
refresh, shutdown around every awaited stage, caller cancellation and UNKNOWN.

| Scope / positive refreshes | Candidate p50/p95/p99 ms | Loop p50/p95/p99 ms | CPU seconds / ms per key | Peak bytes |
|---|---|---|---|---|
| 30 / 240 | 2.078 / 3.087 / 3.810 | 0.317 / 0.841 / 1.165 | 0.5469 / 2.279 | 119,709 |
| 120 / 960 | 3.099 / 5.437 / 6.214 | 0.460 / 1.333 / 1.873 | 3.3125 / 3.451 | 330,895 |

Both final-source resource runs passed. Wall times: 0.5372s and 3.2343s;
final reader/writer backlogs zero, one structural pinned-proof slot, zero REST
requests and zero portfolio queries during candidate refresh (enforced by a
raising replacement). Every scoped market held synthetic .01-contract inventory;
the 120-market case is a component stress fixture, not approved live scale.
These measurements exclude startup fixture construction and do not measure
venue latency, durable mutation throughput or income.

Actual source/test diff review covered exact request binding, writer receipt
revision advancement, source/deadline races, stop/cancel ownership, permit
release and resource bounds. Review found and corrected late dispatcher stop,
proof changes inside the quota hook, the unused-permit return path and an
already-forced IOC crossing trading close. In-memory removal of final proof,
permit cleanup and close-time guards caused their respective regressions to
fail; repository files were not weakened for these checks.

Final complete suite after the trading-close correction: **1,102 tests run,
1,101 passed, one expected Windows symlink-privilege skip**, in 154.452s.
Disabled preflight returned native exit 2 with `live_ready=false`, no file
creation, credentials or network access. Changed-document local links,
whitespace, staged scope and secret-pattern checks passed. No blocking review
finding remains in this offline slice; publication follows D-065 with remote
parity checked after push, not a bot deployment.

Next steps outside this slice: verified fee metadata and real quota
ingestion, owned 429/outcome recovery, supervised dispatch lifecycle,
ranking/admission and live readiness/approval. No production wiring or proven-
unsent reducer reauthorization/restart policy is added by this producer.
