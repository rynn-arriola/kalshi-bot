# Reward telemetry continuity and diagnostic retention repair

Date: 2026-09-23. This is an offline source repair. It did not stop, restart,
reconfigure or otherwise mutate generation 92 or any venue order.

## Problem and boundary

The read-only generation-92 audit measured only about 4.7% reward observation
coverage over 24.6 seconds and about 204 seconds of retained child logs. Source
tracing reproduced the first mechanism: normal account reconciliation removes
the current report before publishing its replacement, while reward telemetry
had treated that temporary gap as a hard historical invalidation.

Current authority must still disappear immediately. The repair may retain an
old interpolation endpoint only; it must not retain a current rate, queue proof,
entry authority or payout claim. Diagnostic retention must remain bounded and
secret-safe.

## Implementation

- `RuntimeRewards` now distinguishes suspension from hard invalidation.
  Suspension clears current source and queue authority but keeps the prior
  in-memory tracker sample.
- `RewardTracker`'s existing rules remain the sole bridge: both observations
  need a rate, continuity must match, the new observation must arrive within
  five seconds and before the prior lease expires. Otherwise the entire elapsed
  interval is UNKNOWN.
- Queue disagreement, source epoch changes, program changes, invalid data,
  checkpoint failure and shutdown retain hard invalidation. Samples are still
  omitted from checkpoints, so restart cannot bridge an outage.
- The supervised child uses eight rotating files capped at 12 MiB each. The
  96 MiB bound projects about 7.2 hours at generation 92's measured rate. Logger
  status exposes the exact configured sizes for later live verification.

## Verification

- Reward and logging suites: 90 tests passed.
- Broader quote-maintenance, live-runtime, reward-source and supervisor suites:
  238 tests passed, with one expected Windows privilege skip.
- Exact complete suite after final test additions: 1,645 tests passed, with one
  expected Windows privilege skip, in 276.027 seconds.
- `compileall` and `git diff --check` pass.

The tests prove bounded accounting behavior, not improved live coverage. That
requires a separately authorized restart and a new measured stable-order window.
