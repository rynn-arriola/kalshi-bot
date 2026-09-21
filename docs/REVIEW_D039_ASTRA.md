# D-039 — Astra review of both quota-freshness phases

Date: September 20, 2026. Result: NOT CLEARED. Review only; no source/test fixes.
Historical review findings were implemented under [D-041](BUILD_QUOTA_REVIEW_FIXES.md);
independent Astra re-review of those fixes is pending. The observations below
describe the pre-fix state.

Reviewed present source against D-038/D-039, including dispatch, refresh ownership,
grant deadlines, runtime holds and recovery. Git metadata is unavailable, so this
is not verified Git-diff coverage. All probes used injected clocks/transports;
no credentials, account calls, real sockets, trading or Polymarket changes.

## R1 — P2: Normal finite-grant expiry exhausts automatic refresh

Locations: `src/kalshi_bot/quota_supervisor.py:95` and
`src/kalshi_bot/quota.py:245`.

The supervisor schedules at hard deadline minus refresh lead. Installation
rejects remaining validity less than or equal to that same lead. A server
returning the unchanged, still-valid grant therefore cannot satisfy installation
when its scheduled refresh runs. The normal response consumes the failure budget;
after three attempts the supervisor never checks the later valid downgrade.

VERIFIED injected example, seconds from bootstrap: grant expires at 300, hard
deadline 295, refresh due 205. Responses at 205, 210 and 225 retain that valid
grant; failure counts become 1, 2 and 3, and automatic refresh is exhausted.
At 301, the injected server offers a valid no-grant document, but stepping the
supervisor makes zero new GETs and ordinary reads remain unavailable.

This is an inherited Astra DESIGN CONFLICT: the accepted design specifies both
timing rules. Implementation follows those conflicting requirements. Merely
moving refresh earlier does not solve non-extending deadlines and can cause
repeated immediately-due refreshes.

Recommended design correction, NOT approved policy: distinguish valid but
non-extending evidence at a known grant boundary from malformed/network failures;
provide bounded rollover revalidation while retaining the existing hard expiry,
shared probe bucket, no inferred entitlement and no busy loop. Clarify this in
Astra design before Sol changes acceptance/retry policy. Required regressions:
unchanged grant, renewed grant, post-expiry no-grant/downgraded configuration,
malformed responses and network failure exhaustion. Ordinary reads must never
cross the old hard deadline without new valid evidence.

## R2 — P2: Cancelling shutdown abandons a physical refresh worker

Locations: `src/kalshi_bot/rest.py:450` and `:675`; also inspect the shutdown joins
in `src/kalshi_bot/quota_supervisor.py:116`.

After a pair timeout, `_refresh_quota` drains control tasks with an unshielded
gather. Cancelling `RestReads.close()` propagates through its unshielded pair join
and cancels that drain. The fetch task releases its logical slot and disappears
from tracking although its `asyncio.to_thread` worker is still running. A late
429 is consequently never processed, and a subsequent close cannot join the
forgotten physical request. Normal refresh-consumer cancellation tests do not
cover cancellation of this shutdown/drain path.

VERIFIED with a gated wire worker after pair timeout:

| Observation | Slots | Tracked control tasks | Worker returned | Throttles |
| --- | ---: | ---: | --- | ---: |
| Before cancelling close | 1 | 1 | false | 0 |
| After cancelling close | 0 | 0 | false | 0 |
| After releasing worker with 429 | 0 | 0 | true | 0 |

Fix acceptance: cancellation-safe ownership must outlive cancelled close/observer
tasks; retain actual-work tracking and slot ownership until the worker returns,
process its late 429, and allow repeated close to join remaining work. Add a
regression combining pair timeout, cancelled/repeated close and a gated late 429.
Do not allow replacement refreshes to overlap the retained worker.

## R3 — P2: Explicit refresh can hang after a clock fault during cooldown

Location: `src/kalshi_bot/quota_supervisor.py:51`.

An explicit refresh waiting for an active pair checks only `stopping` and
`exhausted`. If a clock fault occurs during the retained retry cooldown, the guard
wakes the waiter but neither condition is true. The waiter sleeps again, while
`step()` refuses to start any work in `clock_fault`. The public call has no way
to complete without external cancellation or shutdown.

VERIFIED: inject 401 exhaustion, explicitly reopen retry without resetting its
60-second cooldown, start `reads.refresh_budget()`, then advance the wall-clock
offset by three seconds. Observed state is `clock_fault`, active task absent,
waiter still pending and cooldown retained (`not_before=60.001`). Probe cleanup
cancelled the caller and closed the services.

Fix acceptance: every wait iteration must recognize terminal guard/service states
and complete with a typed safe error. Test clock fault and close while awaiting
cooldown, asserting bounded completion and no new GETs. Do not reanchor the clock,
clear cooldown or restore quota as a side effect.

## Verification and separate test-reliability issue

- Focused quota suites: 46 passed in 5.951 seconds.
- Full suite: 762 tests in 66.472 seconds, FAILED with one error in
  `test_timeout_drains_wire_before_another_pair_can_start` at
  `tests/test_bot_quota.py:365`: its three-second wait for wire entry timed out.
- Immediate module rerun: all 31 `test_bot_quota.py` tests passed in 4.122 seconds.
- The test sets a 30 ms pair timeout before dispatch, then assumes the worker
  enters before that deadline. Scheduling sensitivity is a HYPOTHESIS supported
  by that structure and the pass on rerun, not a proven cause of the full-run
  failure. Investigate and make deadline/worker coordination deterministic;
  do not hide the failure by reporting only the passing rerun.
- Three separate injected probes reproduced R1-R3 despite the passing focused
  suite. Benchmark and preflight outcomes in the build report are historical
  implementation results; neither was rerun in this review.

The previous Sol full-suite pass (762 tests in 64.218 seconds) remains historical
evidence, not this review's result. No source/test changes were made here.

## Handoff

Stop after review. Next: operator-approved Astra clarification for R1's timing
contract, then STOP for the operator to switch to 5.6 Sol. Sol implements the
approved correction plus R2/R3, investigates the timing test, adds regressions and
reruns the focused/full suites and affected resource fixtures. Independent Astra
re-review follows. No new milestone or live activation is authorized.
