# Supervised injected dispatch lifecycle — priority 4

Scope agreed 2026-09-21: connect the existing injected dispatcher to
`RecoveryRuntime` task supervision; stop new work synchronously and retain an
in-flight outcome before returning control to the caller that owns the writer.
This does not connect the inert Windows process supervisor to a trading child
(S2B), implement a live transport, or approve automatic trading restart.

## Design and acceptance, before implementation

One opt-in `DispatchSupervisor` per unused runtime, with literal
`offline_fixture=True` and matching source/dispatcher/writer identities. Caller
events submit bounded market/priority keys through `request_dispatch`; no stored
command or strategy is inferred. Existing source refresh and writer receipts
remain the only injected send path. No entry producer or additional REST reads.

One service task drains the existing 128-key queue. Idle waits on an event;
quota WAITING honors a finite delay (minimum 10ms), or waits for an explicit
source/quota wake when no delay is available. It retries only reevaluation of
unsent keys, never UNKNOWN commands. Duplicate requests coalesce. Failure is
sticky, wakes runtime supervision and stops peers; no replacement worker.

Stop first fences source/dispatcher synchronously. Retained shutdown joins the
dispatch service before closing reader/metadata/quota peers; the outer owner
closes the writer only after runtime completion. Parent cancellation never
abandons durable outcome recording. Missing/failed recording retains SENDING/
UNKNOWN and reports failure. Restart constructs new empty owners and fresh
proof; no old queue/receipt is replayed and no failed owner is reset. Existing
durable command/accounting restrictions remain binding.

Offline acceptance: real disposable writer and source/dispatcher, synthetic
transport/readers. Cover idle wake/coalescing, quota waiting, priorities, stop at
prepare/SENDING/invoke/outcome, repeated cancellation, failure propagation,
writer lifetime, fresh-runtime UNKNOWN holds and no duplicate submission.
Resource acceptance: 30/120 market keys, 300/1,200 blocked reevaluations and
10,000 duplicate requests, queue <=128, one service/one active writer task,
no idle polling in a 50ms fixture span, CPU <1s, peak allocation <8 MiB,
loop lag p99 <50ms, per-key scheduling p99 <50ms. Component measurements exclude
venue latency, production recovery and supervisor processes. Full offline suite,
disabled preflight, scoped diff/secret/link review, commit/push/parity required.

## Implemented ownership

`RecoveryRuntime.attach_dispatch(source, dispatcher, offline_fixture=True)`
attaches matching unused owners once. `request_dispatch(ticker, priority)` is
the event/callback interface; market selection is not added here. The existing
quota transition callback wakes reevaluation, without another poller. The
runtime owns `kalshi-dispatch` alongside its existing tasks. Unexpected dispatch
completion/failure stops the runtime, rather than being treated as ordinary
reader exhaustion. `status()['dispatch']` reports activity, queue bounds and
failure without a model, network request or raw error text.

Cancellation fences submissions before asynchronous cleanup is scheduled.
Shutdown joins accepted command outcomes before cancelling reader peers, and
then joins all peers before returning. An external owner must still await
`runtime.run()` before closing the writer. Neither stop nor restart cancels an
order at the venue. The runtime shutdown wait uses retained `asyncio.wait`,
avoiding the cancelled-shield default logging path already found in the prior
milestone. Stop before the service's first turn is a clean no-send path; a used
service cannot start again. Runtime and dispatcher failures never auto-resume.

## Verification

Native Windows, disposable SQLite only:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bot_dispatch_lifecycle.py -q
.\.venv\Scripts\python.exe -B scripts/benchmark_dispatch_lifecycle.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

23 lifecycle tests pass. Actual runtime/engine/writer/source/dispatcher owners
are exercised with parked synthetic reader/recovery boundaries for deterministic
race timing. Existing reader/fill-drain tests remain in the full suite. Restart
opens the closed synthetic ledger with a new writer epoch and new runtime,
restores fresh synthetic account/book/terms evidence, and verifies UNKNOWN and
held command credits persist without invocation. No existing runtime database
or credential is accessed. A deliberate in-memory early-return replacement of
`DispatchSupervisor.close` makes the reader-before-outcome regression fail;
source files were not weakened.

| Markets / blocked turns | Turn p50/p95/p99 ms | Loop p50/p95/p99 ms | CPU / wall seconds | Peak bytes |
|---|---|---|---|---|
| 30 / 300 | .038 / .116 / .256 | 8.639 / 16.462 / 18.306 | .0312 / .2391 | 25,942 |
| 120 / 1,200 | .042 / .106 / .138 | .056 / 14.541 / 16.970 | .0469 / .2373 | 51,104 |

Both declared resource budgets pass. Queue high-water was 30/120 respectively;
10,000 duplicates per scope were coalesced, with zero idle service turns during
the 50ms idle interval. One service and at most one active dispatch operation;
no venue calls. Nearest-rank percentiles describe whole blocked-key processing
turns, not queue residence, production fills, writer commits or network tails.
Final full suite: **1,179 run, 1,178 passed, one expected Windows symlink-privilege
skip**, in 126.643s. Disabled preflight returns native exit 2,
`live_ready=false`, and no file creation, credentials or network access.

Actual diff review covered ownership identity, early stop, unexpected task exit,
post-SENDING retention, callback/writer failure, cancellation logging, queue
bounds and no replay. It corrected an IDLE status that could remain visible
while a new command awaited persistence, and made unexpected service completion
a runtime failure. No known blocking issue within this offline scope. Nine
changed Markdown files passed local-link checks (285 links); staged whitespace
and secret-pattern checks passed. Publication follows D-065 and is not deployment.

Production readiness, native S2B (including its separate review/resource gates),
real quota/fee inputs, market ranking/admission and live launch approval remain
separate. This milestone does not clear all of priority 4's production gates.
