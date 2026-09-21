# D-041 — Quota review fixes

Date: September 20, 2026. Windows-native, execution disabled.
Sol implementation of [D-040 design](DESIGN_QUOTA_REVIEW_FIXES.md), addressing
[Astra findings R1-R3](REVIEW_D039_ASTRA.md). [Astra re-review](REVIEW_D041_ASTRA.md)
clears those original findings with two P3 follow-ups, subsequently fixed in
[D-042](BUILD_QUOTA_REVIEW_FOLLOWUPS.md) pending independent re-review.
The D-041 review tests pass.
No credentials, account calls, live sockets, orders, cancellations or Polymarket
changes. This is not live-readiness approval.

## Changes

- `quota.py` reports valid, near-expiry grant evidence as a typed pending
  boundary. It never installs that evidence as a new lease. An identical old
  read configuration keeps only its original hard deadline; changed read
  settings, costs or earliest expiry revoke old read authority immediately.
  Other invalid/expired evidence still fails normally.
- `quota_supervisor.py` permits one free deferral since the last successful
  install. One shared pair is due at actual grant expiry, subject to existing
  cooldown, 429 pause, slots and worker drain. Failure count is preserved;
  another near-boundary result counts as failure. Request storms cannot start an
  early pair. Explicit refresh returns a typed pending hold during the wait.
  Terminal state checks release refresh callers waiting in cooldown.
- `rest.py` retains one owned close/drain task. Cancelling a close observer cannot
  cancel the physical fetch. Repeated close joins that owner; a late 429 still
  pauses the shared budget. Timed-out pair cleanup joins control tasks without
  propagating cancellation. Safe transition/close events are registered.
- The timeout test now arms its deadline only after wire entry, preserving a
  separate test for timeout before worker dispatch. Worker gates release during
  cleanup.

## Verification

- 60 focused quota tests passed in 8.585s after the final test additions.
- Exact full suite after the final source/test edit: 776 tests passed in
  65.657s. The prior timing-sensitive timeout did not recur in this run.
- The unchanged explicit/automatic 30/120 mixed-read resource fixtures all
  passed. CPU: 0.3594/0.3281s explicit, 0.3125/0.3281s automatic;
  traced peak <0.5 MiB, event-loop p99 lag <12.2ms, no leftover tasks.
- New 30/120 rollover stages passed: six total quota GETs (two bootstrap, two
  deferred, two boundary), zero GETs between the latter pairs, 60 tokens,
  no leftover tasks; traced peaks 35,768/34,229 bytes. This is injected
  transport only and does not establish live account behavior or a feed ACK.
- Ten-second idle fixture: ten health wakes, zero extra GETs.
- Two in-memory reversals detected by regressions: restoring old near-boundary
  rejection produced one test failure; removing close shielding produced one
  failure and one teardown error. Both reversals were process-local and restored
  automatically. The normal 776-test suite passed after the final code edit.

Original R1/R2/R3 are now cleared in the reviewed scope; follow-ups are recorded
in the review linked above. No Git metadata is available in
this folder, so present source and test evidence were inspected without claiming
Git diff or commit coverage. Preflight was not rerun in this fixes turn; the
prior execution-disabled result remains historical. Production probe allowance,
write limiting and complete account/launch proof remain separate blockers.

The subsequent D-042 implementation and its next Astra re-review gate are
recorded separately in the linked follow-up build note.
