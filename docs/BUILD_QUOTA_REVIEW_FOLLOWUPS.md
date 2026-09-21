# D-042 — Quota re-review follow-ups

Date: September 20, 2026. Sol implementation in the native Windows project,
following the existing [D-040 design](DESIGN_QUOTA_REVIEW_FIXES.md) and the two
P3 findings in the [D-041 Astra review](REVIEW_D041_ASTRA.md). Independent
[Astra re-review](REVIEW_D042_ASTRA.md) clears both in scope. No production or live-readiness
approval is inferred.

## Changes

- `QuotaSupervisor.run()` publishes `running=False` and wakes status observers
  from an unconditional final path. If a second cancellation interrupts its
  shutdown join, the task no longer claims to be running. The irreversible
  `used`/`stopping` flags still prevent restart; REST retains physical worker
  ownership and a later explicit close can join it.
- The one pending grant rollover is now a frozen `RolloverBoundary` with only
  scope, epoch, sequence and wall/monotonic expiry. The supervisor no longer
  stores the caught `QuotaRolloverPending` or its traceback. Validation, due
  time, failure count, typed caller hold and hard-expiry behavior are unchanged.
- New injected regressions double-cancel `run()` while a quota wire call is
  gated, check status before and after drain and confirm its late 429 enters the
  shared throttle. A second test verifies the completed pair's candidate can
  be collected while rollover remains pending.

## Verification

- Focused quota suite: 62 tests passed in 8.893 seconds.
- Exact full suite after the last source/test edit: 778 tests passed in 66.998
  seconds. Asyncio slow-task diagnostics appeared in unrelated inventory and
  runtime tests; they were not failures.
- `scripts/benchmark_quota_freshness.py`: explicit and automatic 30/120 caller
  fixtures pass, zero leftover tasks; rollover 30/120 fixtures each use six
  quota GETs and no GET between the deferred and boundary pairs; ten-second
  idle fixture has zero extra GETs. Each fixture reports `diagnostic_pass=true`.
- Git status/diff/commit coverage is unavailable because this folder has no
  Git metadata. Review must inspect present source/tests and this evidence.

All tests use injected transports and clocks. No credentials, real Kalshi
account/API calls, live sockets, orders/cancellations, risk changes, ledger
imports or Polymarket changes. Trading remains disabled; production quota
allowance, write limiting and complete account/launch proof are separate gates.

Review is complete. Next role: Astra design for the next selected milestone,
then STOP before Sol implementation under D-037.
