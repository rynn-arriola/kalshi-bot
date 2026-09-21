# D-051 independent Astra review

Reviewed September 21, 2026: `7b8d6cd` against `965e4af`, native Windows,
`C:/Users/rynna/Bots/kalshi`. Initial working tree was clean. Reviewed the
complete S1 source/test changes, journal, benchmark and approved D-050 design.
Probes ran in memory or disposable test databases. Source/tests are unchanged.

## Verdict

Changes required before S2: six P2 policy/contract findings and one P3 resource
verification finding. The immutable execution-disabled boundary and transactional
attempt reservation are present, but passing tests do not establish the claimed
stop, recovery and useful-progress behavior. No actual process or live account
was exercised. These are foundation defects, not observed trading incidents.

## R1 — P2: Event timestamps bypass stale filtering and stop generation fencing

Location: `src/kalshi_bot/supervision.py:362-364`; related stop handling at
383-398 and child filtering at 437-445.

Clock regression is evaluated before event identity and before STOP. An old
child result stamped 150, delivered after the current child's status at 200,
requests graceful stop of the current child with `clock_regressed` instead of
being ignored. A delayed event is not evidence that the local clock reversed.

The same ordering undermines the stop/arm race guarantee. Through the actual
`SupervisorStore.apply()` transaction: ARM at 100 creates generation 1; TICK at
102 commits; a queued STOP stamped 101 produces attention at generation 1,
without advancing the control generation. An ARM prepared against generation 1
with timestamp 103 then succeeds, clears the stop and restores BACKOFF. The
existing concurrency test uses identical timestamps and misses this ordering.

Acceptance: STOP must always durably invalidate previously prepared arms even
when its observation is older than the last committed event. Filter stale child
identities before allowing their payload to affect current safety state. Separate
trusted local clock samples from event observation time; use the design's
monotonic in-boot deadlines and validated persisted-clock continuity. Regress
both transaction orderings with distinct timestamps, plus genuine clock reversal.

## R2 — P2: Out-of-phase spawn events can discard a running child

Location: `src/kalshi_bot/supervision.py:468-484`.

Matching identity is the only substantive precondition on SPAWN_FAILED. After
START_REQUESTED at 100 and CHILD_STARTED at 101, a matching SPAWN_FAILED at 102
clears the active identity and enters BACKOFF. At 112 a replacement gets
`SPAWN_RECOVERY` without any result/exit evidence for the original child. The
policy therefore permits overlapping children if a launch outcome is delivered
late or misclassified after process creation.

CHILD_STARTED is also replayable after startup: repeating it at 129 resets useful
progress to 129 with sequence still zero, so TICK at 150 leaves RECOVERING instead
of detecting the original stall. Identity matching does not validate lifecycle.

Acceptance: enforce a transition matrix and mandatory active identities. A spawn
failure may release only a still-unconfirmed reservation with proof that no child
was created. Once creation is confirmed, retain ownership until confirmed exit;
reject duplicate/late start acknowledgements without renewing progress. Test
these cases during running, stopping and attention as well as initial startup.

## R3 — P2: A work deadline substitutes for ongoing health and refunds attempts

Location: `src/kalshi_bot/supervision.py:418-434`, with deadline publication at
497-504. The current healthy-reset test explicitly expects the faulty result.

After one HEALTHY status at 102 with progress sequence 1 and work deadline 1000,
TICK at 702 leaves HEALTHY and resets attempts/history to zero. There were no
further heartbeats or progress for 600 seconds. An arbitrarily distant deadline
can suppress stall detection, and unchanged-sequence status messages can extend
it indefinitely. A slow operation does not prove the event loop is alive or
establish ten minutes of demonstrably healthy progress.

Acceptance: track fresh loop progress separately from outstanding-work deadlines;
bound and identify legitimate work extensions. Missing heartbeats/progress must
not be excused indefinitely by a work deadline. Reset the incident budget only
after continuously observed healthy progress, preserving the rolling launch
history as required. Replace the current one-status reset test with progressive
health observations and add silent-child/deadline-extension counterexamples.

## R4 — P2: Persisted retry holds do not block restart and ARM deletes them

Location: `src/kalshi_bot/supervision.py:373-381`, 447-466 and 538-542.

A status carrying `quota_retry_exhausted`, followed by a cleanly finalized
TRANSIENT_FAILURE, enters BACKOFF and requests `SPAWN_RECOVERY` at the next due
time while still carrying that hold. Neither TICK nor START_REQUESTED checks the
hold. A separate RETRY_EXHAUSTED result with `quota_retry_exhausted` and
`cooldown_pending`, followed by ARM, removes both holds outright. Retaining a
string through status updates is insufficient to preserve a recovery blocker.

Acceptance: S1 must treat unresolved exhaustion/cooldown state as a launch blocker,
as D-050 requires, until a defined explicit resolution occurs. Ordinary ARM,
clean exit, health reset or generic transient failure cannot silently clear it.
Keep hold resolution separate from arming and preserve unexpired cooldowns.
Test through store close/reopen and launch decisions, not only tuple retention.

## R5 — P2: The startup deadline is neither a 60-second allowance nor a bound

Location: `src/kalshi_bot/supervision.py:410-424`.

For a child reserved at 100 with no startup acknowledgement, a normal TICK at
130 requests stop with `progress_stalled`. The generic 30-second progress check
preempts the separate 60-second startup deadline. Conversely, valid STARTING
statuses every two seconds with increasing progress keep it STARTING at 202,
102 seconds after reservation: setting `last_heartbeat_utc` disables the startup
timeout condition permanently. The existing test jumps straight to 161 and
does not exercise regular scheduling or a stuck startup stage.

Acceptance: define startup completion and enforce its absolute deadline despite
heartbeats/stage activity. Apply progress detection consistently with the approved
startup allowance. Regress one-second ticks across the 30/60-second boundaries,
advancing-but-never-complete startup and normal completion before expiry.

## R6 — P2: Unexpected process death cannot take the promised recovery path

Location: `src/kalshi_bot/supervision.py:526-542`; test helper
`tests/test_bot_supervision.py:44-49` defaults every result to completed cleanup.

An UNEXPECTED_DEATH result with the event's default `cleanup_complete=False`
enters UNKNOWN_FAILURE attention before the unexpected-death branch. The test
that claims crash backoff silently supplies `cleanup_complete=True`. A genuinely
crashed child cannot certify completion of its runtime finalizers. The current
contract conflates confirmed OS exit, successful child cleanup and unresolved
durable work, so the approved bounded recovery-after-crash behavior is absent
unless the future adapter overclaims cleanup.

Acceptance: distinguish confirmed process exit/join from child cleanup evidence.
Model the design's recovery-only path after confirmed unexpected death without
asserting clean ledger/account state; carry unresolved evidence and all holds
into the recovery gate. A surviving/unknown child and actual integrity or cleanup
failure must remain blocked. Test abrupt exit with no child result, confirmed
join, uncertain exit and failed cleanup separately. No live auto-resume follows.

## R7 — P3: The idle CPU benchmark measures sleep rather than supervision

Location: `scripts/benchmark_supervision.py:40-53` and the S1 build evidence.

The entire measured idle loop calls `time.sleep`, increments a counter and reads
timers. It does not run `decide`, the journal or a fake supervisor scheduling step.
Patching its `decide` to raise still yields `pass=true`, with zero policy calls.
The 0.0 CPU-second result therefore cannot satisfy the idle-parent acceptance
claim. The 30/120 labels also exercise identical DISARMED policy ticks; they are
explicit metadata, not a measured change in market load.

Acceptance: run an actual bounded offline supervisor step and its intended
persistence cadence inside the timed loop, including normal health and due-work
paths. Otherwise label the sleep measurement as a timer baseline and defer the
parent CPU claim. Keep the pure-decision measurement accurately scoped; report
timer resolution and avoid inferring production process performance from it.

## Verification and boundaries

- Existing supervisor suite: **32 tests passed in 0.202 seconds**.
- Exact complete suite: **836 tests passed in 80.246 seconds**.
- Deterministic probes reproduced every finding above against the committed
  implementation. R1's stop/arm ordering also used the real SQLite transaction.
- Native preflight: exit 2, `live_ready=false`, `creates_files=false`,
  `credentials_accessed=false`, `network_accessed=false`.
- The full 60-second benchmark was not rerun; inspection and the zero-call probe
  establish R7. Earlier measured timing numbers remain implementation evidence
  for their limited workload, not clearance of supervisor CPU acceptance.
- No source/test/config changes, runtime actions, account calls, credential use
  or Polymarket changes. Only review/evidence/handoff documentation is updated.

The complete test run includes D-048 regressions, but this is the D-051 review;
D-048's independent source/teardown review remains separately outstanding.

## Handoff

Recommended agent: 5.6 Sol — implement the established review findings and their
regressions, then rerun focused/full checks and return for Astra review under
D-049. Keep S1 offline and preserve the approved architecture. S2 remains blocked
by this review and the separate D-048 review; no installation or live action is
authorized. No new operator decision is recorded by this review.

## D-052 implementation response

Sol implemented R1-R7 after the operator said “Implement those.” Current evidence
and the exact fix mapping are in
[BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md](BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md).
This response does not alter the review's original findings or self-clear them.
The next phase is an independent Astra re-review; S2 remains blocked.
