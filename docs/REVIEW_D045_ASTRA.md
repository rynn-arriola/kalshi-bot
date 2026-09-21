# D-045 Phase 1 — independent Astra review

Date: 2026-09-20. Reviewed commit `07e8984` against `42b6c50`, including all
changed source/tests and the continuity benchmark. The active Windows checkout
was clean at review start. Review only: no implementation/test fixes, real
account calls, credentials, live sockets, order actions or Polymarket changes.

## Verdict

**Changes required before clearing Phase 1.** Two P2 lifecycle findings can
mislabel missing local evidence as clean. Three P3 findings concern status
coherence and verification. All entry/live gates still remain false; none of
these observations establishes a venue handoff or authorizes trading.

## R1 — P2: A consumed-but-discarded fill can produce a clean stop marker

Locations: `src/kalshi_bot/runtime.py:264-266` and `410-428`;
`src/kalshi_bot/transport.py:125-128`;
`tests/test_bot_continuity.py:270-285`.

The reader removes an event from its queue before calling `_consume`. Once
`stop()` sets `stop_requested`, `_consume` returns without staging that event.
The new close logic checks queue emptiness/bytes and engine idleness, but those
do not establish delivery: the reader can empty the queue by discarding events.
Cancellation during an in-flight callback also needs explicit ownership, not
just a queue-size check.

Reproduction, using the existing `ReaderEpochTests` fixture and its actual
`FakeReader.queue`, without substituting a queue:

1. Launch and wait for `repaired_entries_blocked`.
2. `reader.queue.put_nowait(fill_event())`, immediately followed by
   `runtime.stop()` with no intervening await.
3. Await runtime completion and inspect the marker and pending inbox.

Three of three runs returned `clean_local_delivery=True`, reason `stopped`,
empty reader queue, ingress/fill counts `0/0`, pending fills `0`, gap count `0`.
The observed fill was never durable. The existing backlog test replaces the
reader's queue while it is waiting on the original queue, so it exercises only
the nonempty-queue predicate, not this shutdown race. The production reader has
the same dequeue-before-callback ordering.

Sol fix boundary: retain ownership of already received private events through
bounded shutdown; durably stage positive fill evidence before discarding or
acknowledging it. Track in-flight delivery/drain outcome explicitly. A skipped,
cancelled or undrained event must prevent a clean marker. Add real-queue and
in-flight-stage/cancellation regressions; do not infer delivery from emptiness.

## R2 — P2: An accepted epoch-open can be orphaned and hidden until restart

Locations: `src/kalshi_bot/runtime.py:172-180`, `285-289`, `408-409`;
`src/kalshi_bot/writer.py:85-90`, `204-208`.

The runtime assigns `_epoch` only after awaiting the open command. Accepted
writer commands intentionally survive caller cancellation. A handshake timeout
can therefore cancel the reader after the marker commits but before the caller
receives it. Cleanup has no matching `_epoch` to close. Reconnect then opens
another marker, while `_persisted_epoch_gaps` remains the startup value because
history is loaded only when that cache is `None`.

Reproduction: use the reader fixture with two attempts and zero retry delay.
Wrap the first `open_private_epoch` to await the original durable operation,
then delay its acknowledgement for 11 seconds. The actual 10-second handshake
timeout cancels that waiter; the second attempt opens normally and repairs.
Result: two open database markers, **one prior database gap**, but runtime status
reports `persisted_gap_count=0` and `local_evidence_consistent=True`. The sole
reported blocker is the permanent unproven-venue-handoff blocker. Restart would
discover the orphan, but the current run incorrectly overlooks it.

Sol fix boundary: own the epoch identity and accepted open operation before the
await; join/reconcile its outcome on cancellation. Conservatively invalidate
the cached history whenever an accepted lifecycle write has an unknown outcome,
and refresh it through the existing single writer before reporting consistency.
Add timeout-after-commit and cancellation-before-ack regressions that compare
runtime status with database gap inspection. Preserve bounded control-plane
reads, not per-event database scans.

## R3 — P3: A quota transition can make one status response internally stale

Location: `src/kalshi_bot/runtime.py:648-651`, `676-682`.

`verification_status()` captures `continuity` before `quota.poll()`. Polling can
synchronously invoke `_quota_transition`, which revokes the account/history and
refreshes `self.continuity_assessment`. The returned response still uses the old
local variable alongside the newly invalidated report.

An offline assessment fixture with a fresh report and a real injected
`QuotaGuard` at its deadline returned `local_snapshot_consistent=False`,
`quota_unavailable`, but `continuity.local_evidence_consistent=True`; the cached
assessment was already false. This is a diagnostic defect, not an entry bypass.
Poll/revoke before capturing the assessment and add a boundary-status regression.

## R4 — P3: The quota weak-reference regression races a legitimate done callback

Location: `tests/test_bot_quota_supervisor.py:126-130`.

The test waits for `reads.budget_refresh is None`, then immediately collects
garbage. That condition does not drain the supervisor task's scheduled done
callback. At failure, the event loop's ready queue contained
`QuotaSupervisor.step.<locals>.<lambda>` with the completed task as an argument;
the task still legitimately held its exception/traceback/candidate. After one
event-loop turn and collection, the candidate was gone. The immutable rollover
record was not the retaining owner.

Ten consecutive original-test runs failed; ten process-local runs with one
event-loop yield after that wait passed. No repository test/source was modified
for this probe. Stabilize the regression by waiting for callback completion
before testing lasting retention. Keep the immutable-record and preserved
caller-exception checks; do not remove the weak-reference assertion or alter
production exception ownership merely to make this scheduling race green.
This is inherited verification debt, not a D-045 quota implementation regression.

## R5 — P3: Reconnect activity is outside the reported resource measurement

Locations: `scripts/benchmark_continuity.py:25-35`, `48-60`;
`docs/BUILD_ACCOUNT_CONTINUITY_PHASE1.md:62-72`.

The eight marker open/close operations and gap query finish before the heartbeat,
tracemalloc and wall timer start. Consequently `reconnect_epochs=8` and
`diagnostic_pass=True` do not measure reconnect CPU/latency/peak memory or loop
lag, despite the comment and build report calling this a measured burst.
They measure only the later synthetic assessment/candidate loop, with shared
receipt-ID tuples; that narrower measurement is useful but insufficient for
the D-044 reconnect budget.

Measure the bounded reconnect/marker workload inside its own timed/monitored
section, with explicit workload and sample counts, or clearly withdraw its
resource-pass claim until measured. Retain the distinction between receipt IDs,
actual stored receipts, and full runtime reconnects. Do not claim a venue or
production throughput result from these fixtures.

## Verification performed in this review

- Native `.venv/Scripts/python.exe`, offline disposable ledgers/injected reads.
- Six focused modules (`test_bot_continuity`, `test_bot_recovery`,
  `test_bot_recovery_runtime`, `test_bot_verification`,
  `test_bot_history_coverage`, `test_bot_quota_supervisor`): **192 passed** in
  19.362 seconds.
- Exact `unittest discover -s tests -p test_*.py -q`: **794 passed** in
  72.437 seconds. This one passing run does not clear the separately reproduced
  R4 scheduling flake or the R1-R3 probes absent from the suite.
- R1 reproduced 3/3; R2 and R3 reproduced once each with controlled scheduling.
- R4 original regression 10/10 failures; process-local callback-drain variant
  10/10 passes. No production retention leak demonstrated by that failure.
- Existing continuity benchmark passed its **measured assessment-only** budgets:
  30 markets/128 IDs: assessment p99 0.086 ms, loop p99 0.191 ms, peak 95,236 B;
  120 markets/4,096 IDs: p99 0.139 ms, loop p99 0.259 ms, peak 1,174,700 B.
  R5 limits the scope of that evidence. History benchmark was not rerun here.
- Execution-disabled preflight: native exit 2, `live_ready=false`, no files,
  credentials or network accessed.
- Additive schema/single-writer boundaries, explicit positions cursor handling,
  unscoped position invalidation, and hard-false venue/live flags were inspected.
  No new issue identified in those narrow changes; this is not a complete-account
  or live-readiness certificate.

## Handoff

STOP under D-037. Operator switches to **5.6 Sol** and assigns the fixes.
Preserve the D-044 evidence-only architecture; implement R1-R5 regressions/fixes,
rerun the exact full suite and correctly scoped resource checks, then request
Astra re-review. No Phase 2/3, baseline approval, risk change or live activation.

## Implementation response — D-046

After this review, the operator switched to 5.6 Sol and assigned all fixes.
[D-046 implementation evidence](BUILD_ACCOUNT_CONTINUITY_REVIEW_FIXES.md)
records the source changes, regressions, full-suite and corrected resource
results. This note does not alter the review verdict; independent Astra
re-review is the next gate.
