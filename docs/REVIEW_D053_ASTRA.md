# D-053 independent Astra review

Reviewed September 21, 2026: `b051067` against `7bf5241`, native Windows,
`C:/Users/rynna/Bots/kalshi`. Initial working tree clean. Scope: D-053 supervisor
policy, shared clock journal and regression tests against D-052 acceptance.
Probes used memory or disposable SQLite stores; source/tests are unchanged.

## Verdict

Changes required: two P2 clock findings. D-052 R1, R2, R3 and R5 are cleared
within execution-disabled S1. R4 is partly fixed: ordinary clock discontinuities
and same-boot reopen now have shared evidence, but stale-event ordering can lose
the fault, and the default boot estimator can manufacture one. S2 remains blocked,
alongside the separate D-048 review. No deployed incident is claimed.

## R1 — P2: A stale child event consumes a real clock discontinuity

Locations: `src/kalshi_bot/supervisor_store.py:181-194` and
`src/kalshi_bot/supervision.py:445-469`.

`apply()` detects an untrusted local clock sample, but `decide()` returns early
for stale child identity/lifecycle before consulting `clock_trusted`. The store
then unconditionally replaces the shared checkpoint with that untrusted sample.
Consequently the following event sees a stable delta from the new checkpoint
and treats the clock as trusted, without ever persisting an attention hold.

Deterministic reproduction through the real SQLite transaction:

1. Initialize at wall 100 / monotonic 0 and ARM generation 1.
2. Advance wall to 10000 and monotonic to 1. Deliver an old child's result.
3. It returns `stale=true`, remains armed BACKOFF with `stop_latched=false`, and
   journals `clock_trusted=0` while replacing the clock checkpoint.
4. Close/reopen; advance both clocks by one second and deliver TICK. It journals
   `clock_trusted=1` and returns `START_DUE`. Matching START_REQUESTED returns
   `SPAWN_RECOVERY`, without an intervening operator ARM or clock-fault hold.

Additional probes reproduce fault loss with both the default and injected boot
providers, in BACKOFF and with a HEALTHY active child. The active child stays
HEALTHY and receives no graceful-stop action after the discontinuity.

Acceptance: a genuine local-clock trust failure must be durably handled even
when the accompanying child event is stale or out of phase. Do not replace a
trusted checkpoint in a way that forgets an unhandled fault. Keep stale payload
timestamps non-authoritative: restoring the old behavior where an old child can
invent a clock fault is not a fix. Cover stale identity, duplicate lifecycle,
missing identity, two store instances, close/reopen and a following valid
tick/start/status; preserve STOP fencing and child ownership.

## R2 — P2: The default boot identifier changes under harmless sampling skew

Location: `src/kalshi_bot/supervisor_store.py:107-117,132-138`.

Without an injected `boot_id`, every sample recomputes
`floor((wall_utc-monotonic)/10)`. The two clocks are read sequentially. Crossing
a bucket boundary due to sampling delay or a small wall-clock correction is
therefore interpreted as a reboot, regardless of the separate two-second skew
tolerance. An armed supervisor is disarmed and requires manual recovery.

Reproduction using the actual default provider, without injecting a boot ID:

- Initial sample: wall 110.001 / monotonic 10 gives `estimated-10`; ARM succeeds.
- Next sample: wall 111.001 / monotonic 11.002 gives `estimated-9`.
- TICK enters `ATTENTION_REQUIRED(clock_untrusted)`, even though wall and
  monotonic deltas differ by only 0.002 seconds. These values can represent a
  two-millisecond delay between the separate wall and monotonic reads on the
  same boot. No reboot or large clock jump is necessary.

The new clock tests inject a fixed boot ID, bypassing this default behavior.
Acceptance: use stable, validated boot continuity and account for sampling
uncertainty; do not use a freshly quantized wall/monotonic difference as an exact
identity. Exercise the default clock path near bucket boundaries and across
store instances/reopen, small permitted jitter, genuine clock adjustments and
boot/monotonic discontinuity. Genuine uncertainty must still hold for attention.

## Verification and handoff

- Existing focused supervisor suite: 59 tests pass in 0.360 seconds.
- Six selected new policy regressions detect their original defects when only
  the parent commit's policy is loaded in memory: repeated STOP, late startup,
  late progress, discontinuous healthy history, failed-spawn release and missing
  child identity. The checkout was not altered for this comparison.
- Exact full suite in `.venv`: 863 tests pass in 79.900 seconds. The first
  discovery command used global Python and encountered missing `tzdata` and
  `cryptography`; the configured project environment resolves those setup errors.
- Native preflight returns exit 2, `live_ready=false`, and false file creation,
  credential and network access flags.
- The 60-second resource measurement was not rerun. D-053's recorded 0.3645%
  result remains Sol's evidence; this review makes no new CPU claim.

Only review/evidence/handoff documents changed. Recommended next agent: 5.6 Sol
to implement R1/R2 and verification after the operator switch, then return for
Astra review under D-049. No source fixes, runtime changes, new operator decision,
S2 implementation, account calls or live action occurred in this review.

## D-054 implementation response

The operator authorized both R1/R2 fixes. D-054 implements them with 64 focused
and 868 full passing tests; see
[implementation evidence](BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md). This update
does not alter the review findings or claim Astra clearance. S2 and runtime/live
actions remain blocked pending independent Astra re-review.
