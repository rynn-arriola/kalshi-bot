# Live exit and 28-order plateau investigation

Investigation date: 2026-09-22 Eastern. Scope: local read-only diagnosis,
synthetic disposable tests and documentation. No live restart, venue requests,
order commands or production database changes were performed.

## Current account and process knowledge

The operator reports manually canceling all orders. No venue-side confirmation
or post-cancellation position reconciliation was performed in this investigation.
The former production child PID 46304 and its supervisor are absent. Saved
runtime status last updated at 23:22:32 Eastern, with 28 entries, no recorded
positions and $121.20 exposure. That is historical evidence only.

## Priority 1: candidate coverage before ranking

The operator explicitly prioritizes fewer discovered/tradable markets over
hosting improvements. VERIFIED LOCAL: launch inputs contain 1,024 timing-reviewed
candidates and 128 seeds. The live writer uses its default 128-market subscription
capacity. The last status contains 5,072 catalog markets, 128 subscribed program
markets and only two completed admission rotations. Each rotation adds at most
16 tickers, so this run could have covered **at most 160 distinct markets**, not
all 1,024. That is an upper bound, not a measured distinct-ticker history.

VERIFIED CODE/TEST: normal successful admission waits 300 seconds, inherited
from catalog refresh. Source changes can request an earlier cycle; readiness
failures can defer it. The initial scope and discovery ordering use cheap
pool/time/target scores, not the book-based $2/$1 reward ranking. Therefore the
earlier 50 priority markets are not guaranteed to appear in the live 128.

VERIFIED SYNTHETIC DEFECT: `CandidateDiscovery.choose` advances its exploration
cursor across the entire proposed tail, before `MarketAdmission._cycle` accepts
only up to 16 additions. The remaining proposed tickers are not carried forward.
Repeated proposals, including deferred attempts, can skip unexplored candidates.
The existing candidate-only coverage test does not compose this partial consumer.

`scripts/diagnose_selection_breadth.py` now exercises the actual discovery and
admission selection arithmetic with 1,024 fixed synthetic programs, two 64-market
shards, 14 protected markets and immediately successful fake joins. It visits
692 distinct markets, leaving **332 never subscribed**. The complete exploration
state repeats at cycle 189 from cycle 119, proving the fixed-input cycle cannot
reach the missing candidates merely by waiting longer. Account/metadata checks,
wall-clock expiry and actual WebSockets are deliberately excluded to isolate
this defect. The reproduction is characterization, not a passing readiness gate;
replace its expected-bug assertion when repairing coverage.

UNKNOWN: the exact contribution of this defect to the historical 28-order
plateau. Real catalogs, owners and incumbents change, and the earlier 50-market
scan's per-ticker gate results were not located in retained artifacts. Do not
claim all 332 were economically eligible or that repairing discovery guarantees
30 orders. The saved 54 cached/zero current selection values are transient proof
counts, not a count of markets passing economics.

First recommended repair: make exploration progress acknowledge actual admission,
retaining bounded pending candidates across partial/deferred joins; then decouple
bounded refill progress from the five-minute catalog refresh when slots are empty.
Preserve owned markets, two book shards, shared quota, and every economic/freshness
gate. Verify composed full-universe coverage and a synthetic viable fifteenth
market initially outside the first 128, rather than merely widening capacity.
Record per-stage exclusions to distinguish unseen, stale, uneconomic and
dispatch-blocked markets. No production implementation was made in this audit.

## Separate operational blocker: process hosting and misleading saved health

VERIFIED: the live launcher runs the supervisor in the invoking foreground
terminal. The production child is owned by that supervisor. The last terminal
session (52769) is no longer retrievable. Parent logs contain a start but no
stop/failure record for the final run; child logs end during normal reconciliation
at 03:22:32.950543 UTC, without a terminal result or recorded runtime traceback.
The saved `last-result.json` belongs to the preceding recovery run, not this run.

VERIFIED CODE: `supervised_live._status` returns persisted control/runtime data
with `saved_snapshot_only=true`; it does not establish current process liveness
or downgrade an old `healthy` value when the heartbeat ages out. The previous
operational report interpreted this data too strongly.

VERIFIED TEST: the existing native parent-death test passes. It intentionally
expects the fixture child to exit after its parent dies, then a newly started
parent to classify the orphan as attention-required. It does not prove that
the supervisor survives closure/reclamation of its outer terminal host.

INFERRED: simultaneous loss of parent/child and missing terminal diagnostics
is consistent with termination of the hosting process tree. UNKNOWN: the exact
termination trigger and exit code. The inspected Windows Application/System
window and desktop log window supplied no causal termination record. Do not
attribute this conclusively to app cleanup, a model change, or a Python crash.

Recommended repair: establish a supported independently owned foreground host
or an explicitly approved durable launcher, and test host/session teardown with
an inert fixture before live use. Report heartbeat age and verified process
presence separately from saved state. A supervisor cannot recover its child
while the supervisor itself is absent. No service/startup entry was installed.

## Last-pair evidence and remaining diagnostic gap

VERIFIED LEDGER: the final run has 28 acknowledged creates, four proven-unsent
creates and no recorded create/cancel uncertainty. Its latest create attempt
is at 23:18:10.950693 Eastern. No subsequent create attempt was recorded during
the remaining roughly four minutes of runtime. This provides no evidence of a
venue rejection of pair 15.

VERIFIED SYNTHETIC: the selector allows one two-order addition at count 28;
counts 29 and 30 allow none. The real writer's disposable fixture reserves
pair 14 at count 28 and pair 15 at count 30; pair 16 is rejected with `entry_cap`.
Thus neither component has an intentional 28-order ceiling.

VERIFIED LOG/CODE: 16 recovery starts occur in the retained final 73 seconds,
roughly 4.6 seconds apart, with completed passes taking roughly 1.8-2.1 seconds.
`_live_refresh` requests recovery as account evidence ages; reconciliation
invalidates selection proofs. This narrows entry opportunity but does not prove
why every opportunity for pair 15 failed. A brief quota-refresh metadata error
also occurs; it is not proof of the exit or the earlier plateau.

The entry source returns `None` at multiple distinct eligibility/freshness
checks. Dispatch results contain blockers, but `DispatchSupervisor` retains
only `last_state`, which is subsequently replaced by `IDLE`. Per-stage rejection
counts and the final selection exclusions are not retained. The precise
historical final-pair blocker therefore cannot be reconstructed from these logs.

Recommended repair: retain bounded, deduplicated rejection counts/last reasons
at candidate, selection and dispatch boundaries; then exercise the full path
from 28 to 30 with realistic refresh/revision timing and current filters. Do not
weaken freshness or reward gates based solely on this diagnosis.

## Earlier eligibility and lifecycle claims

FINDINGS section 120 measured 50 markets at $2+ and 218 at $1+ in a sequential
public snapshot. Those are candidate opportunities, not concurrent placement
capacity. Thirty resting orders permits 15 two-sided markets; conditions and
competition may change after a measurement. Cached/current selection counts
also do not equal the number passing every entry gate.

Correction to D-090's evidence: the numbers 5,018/5,060 came from REST incentive
catalog counters. They do not measure lifecycle WebSocket snapshot size.
Lifecycle `QueueFull` was established from the error stack, and the larger
buffer was followed by no lifecycle reconnects in the observed run. The exact
burst size, whether it was an initial snapshot, and its traffic composition
were not measured. The earlier explanation conflated two independent sources.

## Verification and next boundary

- Existing selector suite: 47 tests passed.
- Existing native parent-death test: one passed, isolated fixture only.
- Additional temporary-fixture checks: selector counts 0/28/29/30 and writer
  pair reservations through 30, rejection of pair 16; passed.
- Breadth diagnostic: six checks passed, including the expected-bug coverage
  reproduction above. This does not mean the reproduced defect is fixed.
- Existing admission suite: 37 passed; discovery-candidate suite: 11 passed.
  Their success alongside the reproduced defect demonstrates the composed
  coverage test gap; it is not evidence against the defect.
- No full-suite repeat: only an offline diagnostic and documentation changed. Prior 1,482-test result
  means 1,481 passed plus one expected skip, not 1,482 passing tests.

Investigation is recorded; production readiness remains unproved. Before a
future live launch, independently reconcile the operator's manual cancellations
and any intervening fills through the existing recovery path. Manual cancellation
must not be replaced with fabricated local terminal evidence.
