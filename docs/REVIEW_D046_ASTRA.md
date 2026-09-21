# D-046 independent Astra re-review

Reviewed September 20, 2026: commit `1753a23` against `07e8984` in the native
Windows checkout. Git was clean at review start. Source/tests were not edited;
all probes used injected readers, disposable ledgers and process-local patches.
No credentials, account requests, live sockets, orders or Polymarket changes.

## Verdict

Changes required: two P2 shutdown findings remain. Original D-045 R2-R5 are
cleared within their stated scope. Original R1's immediate-stop reproduction
is fixed, but the broader shutdown-delivery requirement is not yet cleared.
The runtime still cannot grant live/entry authority.

## R1 — P2: Repeated cancellation abandons the shielded account reader

Locations: `src/kalshi_bot/runtime.py:425-428`, `455-464`, `707-717`.

The new shield correctly prevents the first parent cancellation from immediately
cancelling a private callback. However, teardown next awaits `delivery_idle`
before calling `reader.cancel()`. A second cancellation of `run()` propagates
through its unshielded cleanup gather and interrupts this wait. The connection
task exits before cancelling/joining its shielded reader. There is no retained
cleanup owner to finish that work. The same interrupted path skips
`running=False`.

Offline reproduction using the existing `ReaderEpochTests` fixture:

1. Launch and wait for the empty-account recovery to finish.
2. Wrap `writer.stage_fill` so it commits the first fill, signals a test barrier,
   then waits on a release event. Enqueue that fill and wait for the barrier.
3. Enqueue a second valid fill on the reader's actual queue.
4. Cancel `runtime.run()`; wait for its account reader state to become `stopped`
   as the connection enters teardown. Cancel the runtime task a second time.
5. Await the runtime task and inspect its reader, queue, marker and inbox.

Observed: runtime task done, `running=True`, reader not closed, one live
`kalshi-account` task, one buffered fill, one durable pending fill, and one open
marker. The escaped reader had to be explicitly cancelled/joined by the probe
before disposing the fixture. The second fill remains unowned by runtime
shutdown; a caller following the documented writer-close contract can close the
writer while that reader is still alive. The leaked reader is the substantive
regression from adding the shield; stale liveness is an additional symptom.

Fix boundary for Sol: retain and join a cleanup owner through repeated caller
cancellation. Ensure reader termination, bounded fill preservation and marker
finalization remain owned, and publish accurate liveness even when the caller
is cancelled again. Add a regression with two cancellations at the in-flight
wait, a queued tail fill, and assertions on live child tasks, durable evidence,
terminal marker/gap and runtime status. Do not solve this merely by changing the
`running` flag.

## R2 — P2: A drain error loses the remaining tail and is swallowed at stop

Locations: `src/kalshi_bot/runtime.py:472-486`, `707-717`.

Teardown removes each buffered event before parsing/staging it. One malformed
fill raises out of the entire drain before subsequent valid fills are retained
or the epoch closes. This exception occurs in the connection's `finally`,
outside its `reader_failed` handler. During shutdown, `run()` discards all
results from `gather(..., return_exceptions=True)` and returns normally.

Offline reproduction: use the same post-commit in-flight barrier for a first
fill. Queue a fill with `count_fp='invalid'`, followed by another valid fill.
Request orderly stop. The one-second callback wait expires; the reader is
joined and the new drain attempts the malformed event.

Observed: `run()` returned `None` successfully, the reader was closed, one valid
tail event remained queued, only the first fill was durable, the writer stayed
healthy, and the epoch remained open while cached gap count remained zero.
The normal `runtime_stopped` path was reached despite the failed drain. This
does not produce a clean persisted marker, but it silently loses observed
positive evidence and hides shutdown failure from the caller.

Fix boundary for Sol: make the drain outcome explicit. Preserve later valid
fill evidence within the bounded queue when a malformed event is encountered,
keep the span invalid, and surface cleanup errors through runtime failure/status
and safe diagnostics. Inspect cleanup task outcomes instead of unconditionally
discarding them. If durable storage itself fails, retain that terminal failure;
never report a successful drain. Add malformed-before-valid-tail and injected
teardown-write-failure regressions, including marker/cache consistency.

## Cleared original findings and verification

- Original R1 immediate-stop case: the new regression passes. An extra probe
  exercised the actual `WebSocketReaders.run` consumer with an injected pump and
  its real `(name, event, bytes)` queue. Eight queued fills were all durable;
  queue and bytes reached zero; the marker was `undrained`, not clean.
- Original R2: an actual 10-second handshake timeout after a committed marker
  open, with an 11-second delayed acknowledgement and a second connection
  attempt, produced two markers with one open/current marker, one prior durable
  gap, cached gap count one, and false local consistency. The cancellation and
  lost-acknowledgement regressions also pass.
- Original R3: quota polling precedes status capture; its expiry-boundary
  regression passes.
- Original R4: the retention regression preserves its assertion and passes
  10/10 additional repetitions after the callback-turn synchronization.
- Original R5: marker open/close work and gap inspection are inside the timer,
  heartbeat and allocation measurement. The fixture accurately labels synthetic
  receipt IDs and its one receipt object. This measures the marker workload,
  not a full network reconnect or venue throughput.

Six focused modules (`test_bot_continuity`, `test_bot_recovery`,
`test_bot_recovery_runtime`, `test_bot_verification`,
`test_bot_history_coverage`, `test_bot_quota_supervisor`) passed **196 tests in
22.558 seconds**. R1/R2 probes above reproduced remaining issues independently
of that suite. The 798-test full-suite pass remains Sol's recorded evidence;
the full suite and history benchmark were not rerun in this review.

Continuity benchmark rerun passed both measured scopes:

| Markets / synthetic IDs | Marker-pair p99 ms | Assessment p99 ms | Loop p99 ms | Peak bytes |
|---|---:|---:|---:|---:|
| 30 / 128 | 3.105 | 0.127 | 1.224 | 151,596 |
| 120 / 4,096 | 3.220 | 0.231 | 1.313 | 1,491,641 |

Preflight remains native exit 2, `live_ready=false`, with no file creation,
credential access or network access. No source or test changes during review.

## Handoff

STOP under D-037 for the operator's switch to 5.6 Sol and assignment of these
two fixes. Preserve the evidence-only architecture and already-cleared fixes.
After implementation and targeted/full verification, return to Astra re-review.
No Phase 2/3, baseline approval, changed risk policy or live activation.

## Implementation response — D-047

After this review, the operator switched to 5.6 Sol and assigned both fixes.
[D-047 implementation evidence](BUILD_ACCOUNT_CONTINUITY_SHUTDOWN_FIXES.md)
records retained cleanup ownership, per-item drain/error handling, regressions
and verification. This note preserves the original review verdict; independent
Astra re-review is the next gate.
