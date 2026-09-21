# D-052 independent Astra re-review

Reviewed September 21, 2026: `7bf5241` against `7b8d6cd`, native Windows,
`C:/Users/rynna/Bots/kalshi`. Initial working tree clean. Scope: supervisor
policy, control journal, tests and benchmark against D-050 and D-051 acceptance.
All probes used memory or disposable SQLite databases; source/tests unchanged.

## Verdict

Changes required before S2: four P2 findings and one P3 validation finding.
The original delayed-STOP/stale-child examples, confirmed-child replay cases,
hold persistence, truthful crash evidence and real benchmark workload are
improved. Original R4, R6 and R7 are cleared within offline S1 scope. Original
R1/R2/R3/R5 are only partly resolved; the cases below prevent overall clearance.
No deployed behavior or live-money incident is claimed.

## R1 — P2: A repeated STOP does not invalidate a previously prepared ARM

Location: `src/kalshi_bot/supervision.py:440-450`.

The `repeated` branch deliberately reuses the control generation while a child
is stopping. Reproduced through both pure policy and `SupervisorStore.apply()`:

1. Start child in generation 1; STOP at 102 creates generation 2.
2. Prepare ARM against generation 2 at observation time 102.5, but delay delivery.
3. A second STOP at 103 leaves generation 2 unchanged.
4. Confirm clean child exit at 104; the state becomes DISARMED at generation 2.
5. Deliver the old ARM at control time 105: it is accepted (`stale=false`) and
   changes the state to BACKOFF at generation 3, clearing the latest stop.

The first delayed-stop regression is fixed, but the same ordering guarantee
does not cover subsequent stop commands. The existing repeated-stop test
explicitly expects unchanged control generation and misses the queued ARM.

Acceptance: every distinct stop command must fence earlier arm requests,
including when already STOPPING or ATTENTION. Retain the child's separate
generation so its eventual result still joins correctly. If duplicate delivery
is to be idempotent, distinguish it with command identity rather than inferring
it from state. Add transaction tests for both ARM/STOP delivery orders, delayed
observation times, multiple stops and final child exit.

## R2 — P2: Status delivery can erase an expired deadline and refund attempts

Location: `src/kalshi_bot/supervision.py:587-612`; timer checks at 501-538.

Timeouts run only for TICK, whereas CHILD_STATUS can change phase and refresh
progress first. Three deterministic counterexamples:

- Reserve at 100, confirm creation at 101, then receive HEALTHY sequence 1 at
  161 before the timer callback. The expired 60-second startup becomes HEALTHY;
  TICK at 161 no longer examines startup and returns no stop action.
- Publish progress at 102.2; run one-second ticks through 132. A progress status
  at 132.5 arrives after the 30-second limit but before TICK 133 and refreshes
  the timestamp. The missed deadline is silently lost during normal timer cadence.
- Publish HEALTHY sequence 1 at 102; after 600 seconds with no observations,
  receive HEALTHY sequence 2 at 702 before TICK 702. `healthy_since_utc` remains
  102, so that tick sets incident attempts and launch history to zero. Two
  observations are treated as ten minutes of continuously observed health.

This matters after delayed timer scheduling or parent suspension as well as
near ordinary timer boundaries. The new progressing-health test is a positive
example; it does not establish rejection of discontinuous history.

Acceptance: evaluate elapsed startup/progress health against the prior state
before accepting evidence that would erase the lapse. Make timeout precedence
independent of status-versus-tick ordering. An observation gap must invalidate
the continuous-health interval and cannot refund the incident budget. Regress
all three sequences, both callback orders, and valid bounded slow work. Preserve
rolling launch history according to its own window.

## R3 — P2: Failed spawn after timeout raises instead of releasing the reservation

Location: `src/kalshi_bot/supervision.py:562-574`.

SPAWN_FAILED is now valid for an unconfirmed reservation in STOPPING/ATTENTION,
but its intermediate `bare` state clears `attention_reason`. The final state
chooses ATTENTION_REQUIRED from the original reason without restoring that
reason. The immutable state validator then raises
`InvalidData: attention state requires a reason`.

Reproduction: reserve at 100; TICK 160 produces STARTUP_TIMEOUT; matching
SPAWN_FAILED at 161 throws. Through SQLite, the transaction rolls back: revision
is unchanged and the nonexistent child's identity remains reserved. The same
mechanism applies to an unconfirmed launch already in clock-fault attention.
The added stopping/attention test uses a confirmed child, so it only exercises
the stale-event path and misses this valid transition.

Acceptance: preserve the original attention cause while releasing a positively
failed, unconfirmed reservation. Test startup timeout, clock-fault attention,
ordinary manual stop and confirmed-child rejection through store close/reopen;
valid failure events must commit without an exception or losing stop intent.

## R4 — P2: Reopening the store trusts an unvalidated wall-clock anchor

Location: `src/kalshi_bot/supervisor_store.py:58-60,92-94,134-135`.

Each store instance takes a new wall/monotonic anchor; neither the persisted
state nor the clock sample carries continuity evidence across instances. Only
`now < updated_utc` is detected by policy. A forward wall adjustment is accepted
as elapsed time and can expire a persisted cooldown immediately.

Reproduced with a temporary journal: failed spawn at wall 101/monotonic 1 sets
restart due 111. Close it; advance monotonic to 2 but wall to 10000; reopen and
TICK. It returns START_DUE, although only one second elapsed. Two simultaneously
open controllers can also disagree because their anchors were sampled on
opposite sides of an adjustment. This does not satisfy D-050 or original R1's
validated persisted-clock continuity requirement.

Acceptance: establish a shared, validated clock domain across controllers and
store lifetimes; do not age cooldowns or launch history from unverified UTC.
When continuity cannot be established, hold for attention. Regress forward and
backward wall adjustments, same-boot reopen, concurrent store instances and
boot/suspend uncertainty. Preserve STOP fencing even while clock trust is lost.

## R5 — P3: Missing child identity is accepted when no child exists

Location: `src/kalshi_bot/supervision.py:411-415`; event fields at 284-287.

The child filter only compares equality: `None == None` passes when both state
and event omit child ID/generation. An initial DISARMED state accepts
`CHILD_RESULT(outcome=UNKNOWN_FAILURE, process_exited=True)` with no identity
and enters ATTENTION_REQUIRED, advances generation and journals a fictitious
child result. A typed event is therefore not sufficient identity validation.

Acceptance: require a real active/reserved child identity and explicit matching
generation for all child events, or reject malformed contracts at construction.
Test missing and partially missing identity in DISARMED, BACKOFF and childless
ATTENTION states. Malformed/stale input must not mutate valid control state.

## Verification and handoff

- Existing focused supervisor suite: 46 tests pass in 0.238 seconds.
- Additional deterministic probes reproduce R1-R5. R1 and R3 also exercise the
  actual SQLite transaction; R4 uses close/reopen of a temporary store.
- A process-local injected failure in `supervisor_store.decide` interrupts the
  corrected idle fixture on its first policy call, confirming original R7's
  zero-policy-work defect is gone. The 60-second CPU measurement was not rerun;
  D-052's 0.3385% result remains Sol's measured evidence.
- Native preflight returns exit 2, `live_ready=false`, and false file creation,
  credential and network access flags.
- Exact complete suite: 850 tests pass in 79.093 seconds, native exit 0.

Only review/evidence/handoff documentation changes in this phase. No source,
tests, runtime, configuration, credentials, account calls or Polymarket changes.
D-048's separate review remains outstanding. Recommended next agent: 5.6 Sol
to fix R1-R5 and verify, then stop for Astra re-review under D-049. No new
operator decision, S2 implementation or live action is authorized by this review.

## D-053 implementation response

The operator authorized the documented R1-R5 fixes. D-053 implements them with
59 focused and 863 full passing tests; see
[implementation evidence](BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md).
This update does not alter the review findings or claim Astra clearance. S2 and
all runtime/live actions remain blocked pending independent Astra re-review.
