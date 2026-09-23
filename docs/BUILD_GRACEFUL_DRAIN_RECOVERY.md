# Progress-aware graceful drain — D-088

## Incident

The authorized stop began from 14 resting entries and no positions. The old
child acknowledged two cancels before failing closed on stale pre-transport
proof. A recovery-only child acknowledged three further cancels, then reported
`blocked_retry_exhausted` with nine saved resting entries. It stayed alive because
flatness was unproven; the supervisor retained it and raised `shutdown_timeout`.

The stop was therefore slow because recovery had stopped making progress, not
because venue cancellation normally needs minutes.

## Mechanism and repair

Every acknowledged cancel advances durable state, invalidates the report that
authorized it and requests a fresh recovery pass. `_recover` previously counted
that required progress cycle as a failed attempt. Three successful cancels could
therefore consume all three attempts.

The repair records `recovery_passes` before each pass. If the pass increments
that source-consistent counter and a new recovery request is queued, the current
cycle ends and the queued cycle receives a fresh three-failure budget. A pass
without measured progress retains the original 1/2-second backoff and exhausts
after three attempts. Ownership, source, accounting, quota and send-edge checks
are unchanged; UNKNOWN outcomes are not retried.

## Verification

The regression models five successive source-consistent safety mutations. The
fixed owner reaches a sixth repaired pass without delay or exhaustion. Removing
the progress branch reproduces timeout/exhaustion after three passes. Focused
recovery, live-runtime, supervision and native-supervisor suites pass: 156 tests.
The final suite passes 1,479 tests: 1,478 passed and one expected Windows
privilege skip. Live recovery evidence is recorded in STATUS after deployment.
