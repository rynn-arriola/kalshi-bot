# D-048 — Retained connection finalization

Date: September 21, 2026. Native Windows; execution disabled. Implements the
P2 finding from [the D-047 Astra review](REVIEW_D047_ASTRA.md). No credential,
account, network, order or Polymarket action was used.

## Behavior

Every connection generation now creates one retained finalizer when its reader
exits for any reason. That finalizer owns reader/lost-task join, bounded private
queue drain, positive fill staging, private-epoch close and durable gap refresh.
The connection awaits it through repeated cancellation and propagates any real
finalization failure before returning cancellation.

This closes the disconnect/stop overlap: runtime shutdown may cancel the parent
connection to initiate or join teardown, but it cannot cancel teardown midway.
The existing retained runtime cleanup owner then joins the connection. No new
queue, polling loop, REST request, per-market task or execution authority was
added. Queue and byte limits, one account reader and the single writer remain.

## Regression evidence

Three offline regressions were added:

- the actual `WebSocketReaders.run` consumer receives four ACK tuples, then an
  injected pump disconnect leaves three valid `(stream, event, wire_bytes)` fill
  tuples for teardown; ordinary runtime stop during the first accepted drain
  write preserves all three fills, drains queue/bytes, closes an invalid epoch,
  reconciles cached/durable gaps and leaves no reader/finalizer task;
- the same transport path under caller cancellation and a second cancellation
  has the same durable/marker result before returning `CancelledError`;
- repeated caller cancellation while a durable marker close acknowledgement is
  held cannot abandon the connection finalizer or leave the marker open.

Both disconnect tests fail against commit `ecf04c3` at their required retained-
finalizer assertion: **2 failures, 0 errors in 0.445 seconds**. The current
implementation passes all three, as well as the three D-047 regressions and
existing runtime-fault propagation checks.

## Verification

- Seven affected modules: **231 tests in 32.179 seconds, all passed**.
- Exact full suite: **804 tests in 79.024 seconds, all passed**.
- Native disabled preflight: expected exit 2, `live_ready=false`, no files,
  credentials or network accessed.

Continuity resource fixtures pass:

| Markets / synthetic IDs | Marker p99 ms | Assessment p99 ms | Loop p99 ms | Peak bytes |
|---|---:|---:|---:|---:|
| 30 / 128 | 3.301 | 0.118 | 0.949 | 151,445 |
| 120 / 4,096 | 2.690 | 0.222 | 0.854 | 1,492,641 |

Inherited history fixtures also pass: 128 rows in 0.1456 seconds with
inspection/loop p99 2.794/5.335 ms and 108,331 B peak; 4,096 rows in 1.7111
seconds with inspection/loop p99 9.957/30.037 ms and 2,504,491 B peak. These are
local engineering fixtures, not venue throughput evidence.

## Handoff

Return to Astra for independent review under D-037. Venue history/stream
handoff, opening basis, settlements/corrections, account exclusivity and cash
proof remain unresolved. Entry and live gates remain false; Phase 2/3 and live
operation remain unauthorized.
