# D-041 Astra re-review

Date: September 20, 2026. Review only; no source/test changes.
Outcome: original D-039 R1-R3 are cleared in the reviewed scope. Two low-priority
follow-ups remain below. This is not production or live-readiness approval.
Historical review record: D-042 subsequently implemented both follow-ups;
independent re-review of that implementation is pending. See
[D-042 build evidence](BUILD_QUOTA_REVIEW_FOLLOWUPS.md).

Reviewed present quota, REST, supervisor and runtime code against D-040, together
with the regression tests. Git metadata remains unavailable, so no verified Git
diff or commit coverage is claimed. All probes used injected transports/clocks.

## R1 — P3: Repeated cancellation leaves incorrect running status

Location: `src/kalshi_bot/quota_supervisor.py:176` through `:179`.

`run()` sets `running=False` only after awaiting its shutdown join. Cancellation
while already waiting in that join skips the assignment. A subsequent successful
`close()` does not repair it. The run task can therefore be done and all wire work
drained while status continues to claim the supervisor is running.

VERIFIED with a gated quota worker: start `run()`, cancel it, wait for `stopping`,
cancel it again, then release the worker with a 429 and join close. After the
second cancellation: run task done, `running=True`, one slot and one control task
still owned. After drain: `running=True`, zero slots, no active refresh, one shared
throttle and zero leftover tasks. Physical ownership and late-429 processing work;
the remaining defect is lifecycle reporting. Stop remains irreversible.

Fix acceptance: publish final run liveness in a cancellation-safe finally path,
independent of whether an observer completes the drain. Keep physical ownership
and repeated-close joining unchanged. Add a repeated-cancellation regression
covering status before and after actual drain. Do not infer restart permission
from `running=False`; `used` and `stopping` retain their existing meanings.

## R2 — P3: Stored rollover exception retains raw quota payloads

Location: `src/kalshi_bot/quota_supervisor.py:84`.

The supervisor retains the caught exception itself as its pending record. The
exception's traceback retains frames from `_refresh_quota`, including the raw
`limits` and `costs` ReadResults and the parsed candidate. This survives completed
pair cleanup and garbage collection while rollover is pending, contrary to the
design's small immutable scheduling record with no raw responses retained.

VERIFIED with an unchanged finite grant at the scheduled refresh, followed by
garbage collection. The pending exception's direct traceback still contains
`_finished`, `_refresh_budget_owned`, `_refresh_quota`, and `install`; the quota
pair frame retains `candidate`, `costs`, and `limits`. Only frame/local names were
printed, never payload values. This is unnecessary retention for the pending
interval, not evidence of an unbounded leak or credential disclosure.

Fix acceptance: copy only the immutable validated boundary/provenance fields into
a separate pending record. Do not retain the caught exception or its traceback
in supervisor state, and do not mutate a shared exception to erase another
caller's evidence. Add a retention regression after the completed pair/callers
are released, preserving pending timing, typed caller errors and retry counts.

## What is cleared

- Original R1: valid near-expiry evidence defers once; old hard cutoff is enforced;
  renewal/downgrade requires installation of a new valid pair. Existing failures
  survive deferral and a second pending result consumes the failure budget.
- Original R2: cancelled close observers no longer cancel physical wire work.
  Both REST and supervisor tests pass; the additional repeated-cancel probe keeps
  its slot until completion and applies the late 429.
- Original R3: the clock-fault and service-close cooldown waiters terminate with
  typed errors. No reanchoring or new request was needed.
- The timeout test explicitly controls expiry after worker entry and separately
  tests expiry before dispatch. Its former wire-start race is removed.

## Verification and handoff

- Current review focused run: 60 tests passed in 8.548 seconds.
- Current review complete run: 776 tests passed in 67.355 seconds.
- Extra injected probes covered shared refresh callers, repeated cancellation,
  late-429 drain and pending-record retention. No source/test fixes were made.
- D-041 benchmark results are implementation evidence; resource benchmarks and
  preflight were not rerun in this review. No keys, account calls, real sockets,
  orders/cancels, ledger imports or Polymarket changes.

Stop for the operator's Sol handoff for these two small follow-ups. They fit the
existing D-040 ownership and minimal-state design; no new architecture/risk choice
is needed. Do not silently start another milestone or change live authority.
