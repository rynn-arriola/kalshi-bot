# D-047 — Continuity shutdown ownership fixes

Date: September 20, 2026. Native Windows; execution disabled. Implements both
P2 findings from [the D-046 Astra re-review](REVIEW_D046_ASTRA.md) after the
operator switched to 5.6 Sol and assigned the work. No real account, credential,
network connection, order action or Polymarket change was used.

## Source behavior

`RecoveryRuntime` now creates one retained shutdown task. Repeated cancellation
of the caller is recorded but cannot cancel that owner. The owner stops and
joins every child reader, preserves bounded queued fill evidence, finalizes the
private epoch, closes optional services, publishes `running=False`, and only
then returns cancellation to the caller.

Child task results are inspected. A failure first observed by the main runtime
keeps its original exception; a failure arising during cleanup becomes a safe
`runtime cleanup failed; reconciliation required` error. This preserves existing
failure semantics while preventing shutdown errors from disappearing inside
`gather(return_exceptions=True)`.

The bounded account queue drain now handles each item independently. Invalid
queue provenance, buffered reader failures, malformed private events and failed
fill staging mark the span invalid and are retained as a safe cleanup failure.
Draining continues so later valid fills can still reach the durable inbox.
After marker closure and durable gap refresh, the cleanup owner emits the safe
reader/runtime diagnostics and returns failure to the caller. Raw payloads and
exception messages are not logged.

The design remains one account reader and one writer with the existing
256-message/2 MiB ingress bounds. It adds no REST calls, polling loops,
per-market tasks, order authority or positive continuity gate.

## Regression evidence

Three new offline regressions cover:

- cancellation during an accepted in-flight fill, a queued tail fill and a
  second caller cancellation: both fills are durable, the reader is closed,
  no `kalshi-account` task survives, the marker is closed invalid, durable gap
  count is one and runtime liveness is false;
- a malformed buffered fill before a valid tail: the valid tail remains durable,
  the queue drains, marker/gap state is invalid and runtime cleanup fails visibly;
- an injected teardown staging failure before another valid fill: draining
  continues, the later fill is durable and cleanup fails visibly.

The implementation also preserves the original unexpected runtime exception
when sibling tasks fail during its shutdown; cleanup no longer masks that
already observed fault.

Verification:

- Six affected modules: **199 tests in 26.997 seconds, all passed**.
- Exact full suite: **801 tests in 76.494 seconds, all passed**.
- Native disabled preflight: exit 2, `live_ready=false`, no files, credentials
  or network accessed.

## Resource evidence

The continuity fixture still includes eight measured marker pairs:

| Markets / synthetic IDs | Marker p99 ms | Assessment p99 ms | Loop p99 ms | Peak bytes |
|---|---:|---:|---:|---:|
| 30 / 128 | 2.454 | 0.129 | 0.844 | 151,165 |
| 120 / 4,096 | 3.014 | 0.301 | 6.124 | 1,491,171 |

The inherited history fixture also passes: 128 rows in 0.1393 seconds with
inspection/loop p99 2.856/7.527 ms and 108,331 B peak; 4,096 rows in 1.7298
seconds with inspection/loop p99 9.809/29.522 ms and 2,505,049 B peak. These are
local engineering fixtures, not venue throughput measurements.

## Handoff

Return to Astra for independent re-review under D-037. Venue history/stream
handoff, starting basis, settlements/corrections, account exclusivity and cash
proof remain unresolved. Every entry/live gate stays false; Phase 2/3 and live
operation remain unauthorized.
