# Astra re-review: D-036 fixes

Date: September 20, 2026. Result: no new blocking findings in the four fixes.
R1-R4 from [the original review](REVIEW_D036_ASTRA.md) are cleared within the
reviewed scope. This is component review clearance, not live-trading approval.

## Findings disposition

- R1, dependency retirement: current dependency reachability drives retirement;
  globally increasing revisions prevent reuse after removal. Shared milestones
  remain reachable, and retired pending loads cannot restore old evidence.
- R2, critical admission: background shared reads leave admission capacity for
  critical reads as well as transport headroom. The default 32-entry cap reserves
  two entries; a two-entry cap reserves one. A one-entry cap cannot reserve space,
  an explicitly documented and tested limitation.
- R3, generation provenance: disconnect retires service-owned pending loads;
  shared REST reads are scoped by service identity, generation and revision.
  New generations cannot inherit old wire payloads. Old shielded wire work remains
  REST-owned and bounded until completion or owner shutdown.
- R4, token-head wakeups: the head waits for either refill time or a change event,
  then recalculates quota, priority and throttle constraints. Helper tasks are
  cancelled and joined; existing token spending and shared-429 rules remain.

## Verification performed during this re-review

- Market-input suite: 44 tests passed (2.397s).
- Metadata-scheduler suite: 25 tests passed (4.219s).
- Rate-limit suite: 18 tests passed (1.194s).
- Combined injected-transport probe using actual RestReads, ExitInputService and
  MetadataScheduler: generation 1's market response was held while generation 2
  began with an attempt limit of one. Generation 2 made a distinct market request,
  published the new 0.02 tick instead of the old 0.01 tick, and recorded no failure
  or exhausted attempt. Two market wire calls were observed. Shutdown left zero
  retiring tasks, pending dependencies or in-flight shared reads.

The 87 focused tests and combined probe were run in this review. Sol's previous
exact full-suite result was 716 tests passing in 56.393s after the last source
edit; its unchanged 30/120 scheduler and token resource fixtures also passed.
The full suite and resource fixtures were not rerun in this re-review.

## Limits and next phase

Git metadata is unavailable (`git status --short` reports no repository). This
review inspected present source and tests, not a verifiable Git diff. No source
or test files were changed in this review; only review/status documents changed.
All probes were offline and used injected fixtures. No credentials, account
calls, live sockets, orders, cancellations or Polymarket changes were involved.

Live readiness remains blocked. Automatic quota freshness/grant-expiry enforcement,
production write limiting, real input approvals and account/history/private-stream/
cash proof are separate remaining work. Next is Astra design for supervised quota
freshness/grant expiry, followed by the mandatory stop for the operator to switch
to 5.6 Sol. This review does not implement or approve that next design.
