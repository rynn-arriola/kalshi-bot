# D-046 — Account continuity review fixes

Independent review update: [D-046 re-review](REVIEW_D046_ASTRA.md) clears original
R2-R5 and verifies immediate-stop delivery, but requires repeated-cancellation
ownership and malformed-buffer drain/error handling fixes. The evidence below
records the implementation run; its broad shutdown claims are qualified by
those reproduced cases. D-047 subsequently implemented the
[shutdown ownership fixes](BUILD_ACCOUNT_CONTINUITY_SHUTDOWN_FIXES.md), pending
Astra re-review.

Date: September 20, 2026. Native Windows; execution disabled. Implements the
five findings in [the D-045 Astra review](REVIEW_D045_ASTRA.md) after the
operator switched to 5.6 Sol and said "Ok fix it." No real Kalshi account,
credential, network connection, order action or Polymarket change was used.

## Fixes

- **R1 — shutdown delivery ownership.** Account-reader callbacks now carry an
  explicit in-flight/failed delivery state. Parent cancellation no longer
  implicitly cancels the reader before controlled teardown. Teardown gives an
  in-flight callback a bounded one-second join, then joins the reader and drains
  its bounded account queue. Buffered fills are staged through the durable inbox;
  buffered/skipped/cancelled delivery makes the epoch `undrained`, never clean.
  Queue emptiness alone is no longer sufficient.
- **R2 — accepted epoch-open ownership.** Runtime owns the generated marker ID
  before awaiting the single writer. If the accepted command's acknowledgement
  is cancelled or fails, teardown closes that exact marker and reloads durable
  gap count rather than trusting its old cache. Reconnect cannot hide an orphan
  marker until process restart.
- **R3 — coherent status capture.** Quota polling now occurs before continuity,
  snapshot and history are captured. A synchronous quota-expiry listener cannot
  return an old positive continuity result beside a newly revoked snapshot.
- **R4 — quota regression synchronization.** The weak-reference test gives the
  scheduled task callback one event-loop turn after `budget_refresh` clears,
  then retains its original garbage-collection assertion. Production exception
  ownership and immutable rollover behavior are unchanged.
- **R5 — measured reconnect workload.** The eight marker open/close operations,
  gap query, heartbeat, wall timer and allocation tracking now share one measured
  section. Output separately labels reconnect latency, synthetic receipt-ID count
  and its one in-memory receipt object. It does not claim stored-receipt, venue or
  production throughput.

The architecture remains event-driven and bounded: one account reader, one
writer, the existing 256-message/2 MiB ingress limits, no per-market task/query,
and no additional healthy-stream REST call. All authority gates remain false.

## Regression and suite evidence

Four new tests plus one replaced artificial backlog fixture cover:

- a fill in the actual reader queue immediately before orderly stop;
- cancellation while an accepted durable fill callback is still in flight;
- cancellation after a durable epoch open but before its acknowledgement;
- a failed open acknowledgement followed by reconnect and durable gap reload;
- quota expiry during one status call.

The first two verify retained pending-fill evidence and an invalid local span.
The open-marker cases verify no hidden orphan: cancellation closes one invalid
marker, while reconnect reports one persisted gap and cannot claim local
consistency. The status test requires snapshot and continuity to revoke together.

Verification on native `.venv/Scripts/python.exe`:

- 44 continuity/quota tests and 152 recovery/verification/history tests pass:
  **196 focused tests** total.
- The stabilized quota weak-reference regression passes **10/10** consecutive
  process-local runs.
- Exact full suite: **798 tests in 74.418 seconds, all passed**.
- Execution-disabled preflight: native exit 2, `live_ready=false`, no file,
  credential or network access.

## Resource evidence

The final measured continuity fixture passed:

| Markets / synthetic IDs / cached | Reconnect p99 ms | Assessment p99 ms | Loop p99 ms | Incremental peak |
|---|---:|---:|---:|---:|
| 30 / 128 / 30 | 3.141 | 0.084 | 0.970 | 150,695 B |
| 120 / 4,096 / 120 | 3.062 | 0.234 | 0.886 | 1,491,801 B |

Each fixture measured eight marker open/close epochs; reconnect wall time was
0.0230/0.0222 seconds. The inherited history fixture also passed: 128 rows in
0.1184 seconds with inspection/loop p99 2.498/7.093 ms and 108,331 B peak;
4,096 rows in 1.7121 seconds with inspection/loop p99 9.311/29.511 ms and
2,504,519 B peak. These are disposable local engineering fixtures only.

## Remaining gate

Phase 1 now returns to Astra for independent re-review under D-037. The fixes do
not establish a Kalshi REST/private-stream watermark, late-publication bound,
complete starting basis, settlements/corrections, cash or account exclusivity.
No baseline is approved; `venue_handoff_proven`, `ready_for_entry`,
`entry_allowed` and `live_ready` remain false. Phases 2/3 and live operation
remain unauthorized.
