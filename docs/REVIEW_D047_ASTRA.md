# D-047 independent Astra review

Reviewed September 21, 2026: `ecf04c3` against `1753a23`, native Windows,
`C:/Users/rynna/Bots/kalshi`. Working tree was clean. Source and test files
were not changed; probes used disposable ledgers and process-local injection.

## Verdict

Changes required: one P2 cancellation race remains. D-047 fixes the two exact
D-046 reproductions, and all three added regressions detect the old defects.
However, the retained runtime cleanup task can itself interrupt a connection's
already-running teardown. Local fill preservation and marker finalization are
therefore not yet cleared. Live/entry gates remain false.

## R1 — P2: Stop cancels an account drain already started by a disconnect

Primary location: `src/kalshi_bot/runtime.py:694-699`. Related drain/finalization:
`runtime.py:477-531`, especially the staging await at line 497.

`_shutdown()` cancels every unfinished child, even when `_connection()` is
already inside its `finally` after a transport failure. Cancellation at an
await in that drain exits the `finally`; the per-item `except Exception` does
not catch `CancelledError`. The retained runtime task then joins the cancelled
connection and explicitly excludes its cancellation from the failure results.
No owner resumes the remaining drain or closes/reconciles the epoch. Shielding
the outer runtime cleanup does not protect this earlier connection cleanup.

This requires only an ordinary stop overlapping disconnect cleanup, not repeated
caller cancellation. The same loss occurs with one cancellation of `run()`.
An accepted writer command remains durable, but later buffered fills are lost
when the stopped runtime and reader are discarded.

### Reproduction

First reproduced with `ReaderEpochTests`: queue a reader exception followed by
two valid fills; pause the first teardown-stage acknowledgement after its
durable commit; call `runtime.stop()`. The runtime returns successfully with
one valid fill still queued, one durable fill and an open epoch.

Then reproduced with the actual `WebSocketReaders.run` consumer, TaskGroup and
`(name, event, wire_bytes)` queue. Only `_pump` was injected; no socket or signer
was used. Other readers and account reads used existing offline fixtures:

1. Emit all four account ACKs and await completed empty-account recovery.
2. The injected pump queues three valid fills and raises a transport failure.
3. Let the real consumer and connection enter normal disconnect teardown.
4. Wrap `writer.stage_fill` to commit normally, then pause its acknowledgement
   when `reader_states['account'] == 'disconnected'`.
5. At that barrier, either call `runtime.stop()` or cancel the runtime task.
6. Await runtime completion and inspect its real queue, inbox and epoch.

Each mode reproduced **3/3 times**, six independent disposable ledgers total:

| Observation | Ordinary stop | Caller cancellation |
|---|---|---|
| Runtime outcome | Returns success (`None`) | `CancelledError` |
| Durable fills / supplied fills | 2 / 3 | 2 / 3 |
| Remaining real queue | 1 fill, 100 fixture wire bytes | 1 fill, 100 fixture wire bytes |
| Epoch | Still open | Still open |
| Cached gaps / durable gaps | 0 / 1 | 0 / 1 |
| Runtime running / reader invalid | false / true | false / true |

The acknowledgement barrier controls scheduling; it does not alter the durable
write. This extends the existing tests' post-commit barrier technique to a drain
that starts before runtime shutdown.

### Fix boundary and acceptance

Retain connection finalization ownership regardless of whether it starts from
a disconnect, handshake failure, runtime fault, ordinary stop or cancellation.
Runtime shutdown must join that finalization without cancelling it midway.
Preserve bounded queue work, the single writer and safe failure reporting;
merely reporting a gap or catching cancellation without finishing the tail is
insufficient. Do not mark the span clean after a disconnect.

Add both ordinary-stop and caller-cancellation regressions at an already-active
disconnect drain, including the actual transport tuple/byte accounting path.
Verify every valid buffered fill is durable, queue/bytes are zero, epoch closes
invalid, cached and durable gap counts agree, and no reader/finalizer survives.
Also exercise stop during marker close and repeated cancellation while the
connection finalizer is pending. Keep the three D-047 regressions and original
runtime-error propagation behavior. Genuine storage failure must remain visible.

## Verified scope

- Seven focused modules passed **228 tests in 29.047 seconds**: continuity,
  recovery, recovery runtime, verification, history coverage, quota supervisor
  and logging. An earlier command named a nonexistent logging module; its 199
  real tests passed but the invocation failed to import that extra module.
  The corrected 228-test run above passed without errors.
- Process-local counterfactual: load the previous commit's runtime class and
  run the three new tests unchanged. All three fail on their intended old
  behavior (3 failures, 0 errors; 2.624 seconds). No checkout/source edits.
- Native preflight exits 2 with `live_ready=false`, no file creation,
  credential access or network access.
- Reviewed the source/test Git diff and neighboring transport/writer/service
  ownership. No additional independent finding in this scope.

The 801-test full suite and resource results remain Sol's recorded implementation
evidence; neither was rerun during this review. This review does not establish
venue continuity or live eligibility. No account requests, credentials, live
connections, orders or Polymarket changes occurred.

## Handoff

Under D-037, stop for the operator's switch to 5.6 Sol and assignment of R1.
Only review/evidence/handoff Markdown files changed. Preserve the evidence-only
architecture, then return the fix with regression evidence for Astra review.

## Implementation response — D-048

After this review, the operator switched to the implementation model and said
"Fix it." [D-048 implementation evidence](BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md)
records retained connection finalization, three regressions and focused/full/
resource/preflight verification. This note preserves the original review
verdict; independent Astra re-review is the next gate.
