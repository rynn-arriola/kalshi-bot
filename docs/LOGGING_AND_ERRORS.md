# D-033 — Logging and error-handling guide

Implemented September 20, 2026, for the execution-disabled Windows components.
No bot, collector, paper process or live account call was started to test this.

## What to inspect

Use one shared `Diagnostics` instance for `LedgerWriter`, `RestReads`,
`RecoveryRuntime` and any offline `InjectedExecutor`. Runtime passes it to the
engine and inventory manager. Construction does not start a logging worker;
start explicitly before components, stop runtime first, drain writer/reads, then
close diagnostics last. Blocking startup/close belong outside the event loop
or in `asyncio.to_thread`. Imports/default component construction create no logs.
The future supervised launcher must wire this shared lifecycle and require
healthy enabled diagnostics; that production launcher is not implemented yet.

The local, credential-free CLI now supports:

```powershell
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight --log-dir "$env:LOCALAPPDATA\KalshiLiquidityBot\logs"
```

This only checks local configuration and writes diagnostic files. It cannot
trade, start readers, access keys or grant live readiness; exit 2 is expected.
Without `--log-dir`, the CLI still creates no files. Failed configuration checks
return a stable `cli_failed` code rather than echoing untrusted file/error text.
`logging_unavailable` means the diagnostic sink itself failed.

`events.jsonl` contains one JSON object per line; `.1` is the newest archive.
Default retention is current file plus four backups, each up to 5 MiB (25 MiB
total for these files, including across restarts). Rotation replaces oldest log
segments only, never databases. Use a dedicated local log directory, not OneDrive
or a network share. A Windows named lease prevents simultaneous writers/rotation
in the same directory. Logs are gitignored; no existing data was removed.

The supervised production child has a higher explicit bound because it owns the
high-volume runtime stream: one 12 MiB current file plus seven backups, 96 MiB
total. Generation 92's measured byte rate projects about 7.2 hours of history;
duration varies with event volume and is not guaranteed. `status()` reports
`max_bytes`, `backups` and `retention_bytes`. The parent and non-production
diagnostics keep their narrower configured/default bounds.

Each record includes schema version, UTC timestamp, monotonic nanoseconds,
run ID, monotonically increasing sequence, severity, component and event code.
Context includes allowed stream names, attempts, generations, revisions, queue
backlog, HTTP status, static endpoint templates/commands, inventory mode and
allowlisted blockers. These make common failures readable without raw payloads.

Market/order/operation references are run-local keyed fingerprints. Matching
references correlate events within one run without exposing raw identifiers;
they intentionally change at restart. They cannot join directly to raw venue IDs.
Cross-restart authoritative investigation still uses the separate durable ledger.
Timestamps/sequence aid debugging; they are not financial ordering authority.

For errors, inspect `errors[].type`, `category` and `frames`: our module,
function and line are recorded, with at most four linked/group errors and twelve
frames each. External frames are labeled `external`. Exception messages, source
text, locals, headers, keys, signatures, URLs with queries, response bodies and
unknown context fields are never formatted. This is schema exclusion, not a
best-effort regex over arbitrary secret-bearing strings. It intentionally trades
raw error detail for safety; reproduce using the indicated source location.

## Debugging sequence

1. Read `runtime.status()['logging']` or the CLI `logging` object. Check `failure`,
   `failure_detail` (safe type/errno/frames), `dropped`, `backlog`, `high_water`,
   `accepted` and `written` before trusting
   missing events. A clean closed sink has `closed=true`, `healthy=false`,
   `failure=null` and equal accepted/written counts. Disabled is not healthy.
2. Select the run ID and first WARNING/ERROR. Follow stream/generation or
   operation reference, then sequence, to see the preceding transition.
3. Open the indicated module/function/line. Compare durable evidence and the
   current account/book proof; logs never override either.
4. Fix/reproduce with offline tests. Do not restart, reset risk, release holds,
   or resend an ambiguous order merely to clear an error.

| Event family | Meaning and action |
|---|---|
| `reader_failed`, `reader_exhausted` | Connection/proof failure; bounded existing reconnect attempts, then blocked. Subscription ACK is not account continuity. |
| `book_proof_lost`, `private_ingress_failed` | Book/account processing lost authority. Recover affected proof; never use stale state. |
| `recovery_failed`, `recovery_incomplete`, `recovery_exhausted` | Exceptions or incomplete proof; inspect generation/attempt. `recovery_repaired` still does not allow entries. |
| `rest_retry`, `rest_failed`, `rest_transport_failed` | Inspect endpoint template, HTTP status or safe error type. Existing three-attempt HTTP transient policy is unchanged; 401/403 are not blindly retried. |
| `writer_failed`, `writer_overflow` | Durable owner is poisoned; no later risk action may overtake it. Error context is captured before returning sanitized failures. Close failures also latch failed state. |
| `mutation_prepared`, `mutation_sending`, `mutation_ack`, `mutation_rejected` | Durable lifecycle milestones. A rejected create was not accepted; ACK still is not terminal/fill proof. Correlate with operation reference. |
| `mutation_unknown`, `mutation_failed` | Retain reservations and reconcile; never retry blindly. Existing offline-only restriction remains. |
| `inventory_plan_changed` | Mode/blocker transition only, not every price tick. This is an advisory plan, never an executed action. |
| `engine_failed`, `runtime_failed` | Unexpected exception propagated; runtime shuts down peers and revokes proof. Cancellation is a separate INFO event. |

## Bounded operation and failure handling

One worker owns disk writes/flush/rotation. Producers perform bounded encoding
and enqueue without waiting for disk; queue default 1,024 records, maximum 8,192,
record cap 16 KiB. No per-market threads, venue polling or root-logger setup.
Inventory logs coalesce identical mode/blocker states in the existing bounded
market universe. The normal logger does not sample/drop accepted error records.

Queue overflow, encoding failure, sink failure, startup or close timeout latch
unhealthy state and expose loss counters/backlog. No raw fallback stderr dump.
Engine and injected execution gates reject unhealthy diagnostics; the runtime's
single 250ms health watcher also detects failure while idle. The runtime then
stops locally and revokes account/book authority. **This is not cancellation or
flat proof**, and still requires production supervised controls before live use.
Accepted ledger work continues its existing drain/recovery rules; logging never
replaces the intent/fill journal. No mutation retry budget or risk limit changed.

Shutdown waits at most five seconds by default. A stuck diagnostic worker is
daemonized so it cannot hold the process forever; timeout is explicit and records
may be lost. Normal writes flush to the OS but are not fsync-per-event: abrupt
power loss may lose tail logs. Financial durability remains in SQLite, not JSONL.
Third-party/global logs and legacy measurement scripts are not redirected by this
feature. The manual private-stream probe keeps its existing count-only output.

## Verification

Full suite: 598 pass in 40.901s. `tests/test_bot_logging.py`: 29 focused tests.
Covers schema/ordering/correlation,
secret exclusion, exception groups, strict rotation errors, Windows exclusivity,
permissions, saturation, shutdown timeout, multi-thread producers, CLI output,
writer poisoning, REST retry/auth/transport failures, ambiguous mutations, reader
exhaustion, engine exceptions, runtime cancellation and idle log-failure shutdown.
Two in-memory safeguard reversals are detected: disclosing exception text and
ignoring unhealthy logging. No source files modified by those reversals.

Predeclared `scripts/benchmark_logging.py`: 30/120 markets x100 events, 5% error
records, 32-event batches, rotating real local sink. Budgets: producer p99 <5ms,
loop-lag p99 <50ms, traced peak <24MiB, wall <8/20s, CPU <4/12s, zero drops,
all accepted records drained. Both pass:

| Markets / events | Wall / CPU seconds | Producer p99 ms | Loop-lag p99 ms | Peak bytes | Queue high-water |
|---|---|---:|---:|---:|---:|
| 30 / 3,000 | 1.4768 / 0.4844 | 0.414 | 16.444 | 263,324 | 32 |
| 120 / 12,000 | 5.9466 / 2.4844 | 0.408 | 17.345 | 558,421 | 32 |

These are paced local diagnostics with allocation tracing, not maximum exchange
throughput, live bot latency or a guarantee against disk stalls. Saturation and
stalled-disk behavior are tested separately. Full-suite outcome is in STATUS.md.
