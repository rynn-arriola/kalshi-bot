# D-028 account-state verification

Completed scoped local-verification milestone, 2026-09-20. No credentials,
account calls, live sockets or venue trading writes. Full account completeness
is still NOT established.

## Before-build scope and budgets

Add one bounded single-writer reconciliation command combining venue-cost
observation with local inventory, exact owned resting-order comparison,
unbound intents and missing/pending-fill checks. Report owner epoch/revision;
reject overtaken reads and invalidate stored reports on subsequent mutations.
Retain history interval/cutoff/account-generation provenance through final
reconciliation. Runtime repair success must require coherent local checks,
not an equality of aggregate counts. No additional network requests/poll loops.

Completeness remains unknown where venue contracts do not supply an atomic
snapshot/stream barrier or approved starting-inventory basis. Keep these as
separate explicit blockers; do not invent a positive live-authorized branch.

Verification planned: exact/foreign/missing/terminal/stale orders, partial-fill
gaps, unbound intents, pending inbox, scope/shard mismatches, cross-await local
mutations, private ingress, reconnect and recovery-history provenance. Two
offline safeguard reversals, restored full suite and blocked preflight.

Resource workload: 30/120 synthetic markets with inventory and owned resting
orders, 30/120 complete local inspections. Disposable WAL/FULL SQLite, tracemalloc
and 2ms heartbeat; setup excluded. Predeclared budgets: inspection p99 <250ms,
loop-lag p99 <50ms, peak incremental Python memory <40MiB. Exact results unchanged
at both sizes. Existing recovery load budget remains <10s for 1024 fills.

## Implementation and evidence

`verification.py:AccountAudit` checks local positions, all retained owned order
fill quantities (including terminals), exact resting-order identity/terms,
foreign/absent orders, unbound active intents, pending fills and account/shard
scope. The writer applies venue-cost observations and reads the audit in one
transaction, returning its epoch/revision. Coordinator rejects overtaken results;
current reports expire on subsequent writer mutations, restart, disconnect or age.
Inventory plans and exit-basis consumers use the current-report gate.

`RecoveryReport` retains requested start/end, archive cutoff, account, generation
and account revision. Runtime separately tracks ingress revisions: replaying an
already-persisted pending fill is not a new external observation. New ingress
between history and final reconciliation prevents a coherent repaired status.
Runtime requires exact local agreement, not aggregate intent/order count equality.
Failed passes no longer increment the completed-repair count. Status reads use
in-memory reports only, with no new polling or database work.

The audit is a necessary local agreement check, NOT complete execution-history,
cash, starting-basis, settlement/correction or lossless-stream proof. These stay
explicit blockers even for an empty, matching account. No new trading cap,
automatic selection, forced-exit rule, starting baseline or live authority.

## Primary contracts and reference trace

Rechecked official public documentation September 20 and the September 19 local
API/AsyncAPI snapshot (not private account endpoints):

- [User fills](https://docs.kalshi.com/websockets/user-fills) and
  [user orders](https://docs.kalshi.com/websockets/user-orders) describe updates
  on executions/order changes. Their published event schemas do not establish
  a shared REST/private-stream snapshot watermark. An acknowledgment is not
  complete historical evidence; absence of a documented barrier stays UNKNOWN.
- [Market positions](https://docs.kalshi.com/websockets/market-positions) can
  change on trades or settlements. A matching position alone cannot establish
  the missing executions or their fees.
- [Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance) reports
  available balance and a last-update timestamp. That timestamp is not a shared
  order/history cursor; an old timestamp can mean unchanged cash, not a stale
  response. Production cash/hold reconciliation remains unfinished.

Actual Poly source read-only at
`580dcc9f49a7f8fb58c8ebff4708d2904786e9ad`: `account_source_runner.py` validates
candidate snapshot scope/completeness, rejects obsolete source generations and
keeps exact order proof on the serial owner. `account_snapshots.py` treats exact
order responses as positive evidence, not complete negative snapshots. This
implementation inherits those distinctions, not Poly-specific EOF semantics,
cash-bracketing guarantees or its selected REST mode. Its 20 account-snapshot
tests pass in .018s; Poly Git status remained clean.

## Verification

Native Windows full suite: **479 tests passed in 29.407s**, 29 new. Two existing
disconnect/slow-disk fault tests were redirected from the replaced inventory-only
read to the new atomic command; the unresolved-intent assertion now checks the
more precise unbound-intent blocker. No old safety assertion was removed.

Two temporary safeguard reversals failed as expected and were restored:

1. Removing the writer epoch/revision publication guard allowed a report already
   overtaken by a new local reservation.
2. Removing the foreign-resting-order blocker falsely marked a recovery repaired.

Batch tests verify capacity rollback and preserved original position age/exact
cost. Full suite also verifies existing cost fallback, fills, risk and restart
behavior. Compilation passes. Preflight returns `live_ready=false`, native exit
2, with no file creation, credentials or network access. Kalshi has no usable Git
metadata; no commit/diff or remote parity is claimed. Only named source/docs/tests
were edited; no historical ledger was opened or migrated.

## Resource results

Disposable WAL/FULL, tracemalloc, 2ms heartbeat, setup excluded. Each market has
an executed owned opening order/fill, inventory, and an owned resting reducer.
Notional sizes are synthetic scaling fixtures, not approved live allocations.

| Markets / inspections | Wall / CPU s | Inspection p50 / p95 / p99 ms | Loop p99 ms | Incremental peak bytes |
|---|---|---|---|---|
| 30 / 30 | .2960 / .2969 | 9.546 / 11.542 / 13.458 | 11.969 | 148441 |
| 120 / 120 | 5.6195 / 5.5156 | 44.548 / 66.991 / 71.887 | 29.802 | 480689 |

Both predeclared budgets pass. Initial 120-market run was 16.4618s, inspection
p99 174.951ms. It passed but exposed a full venue-position capacity scan after
each position write. `observe_costs` now checks capacity once per batch inside
the same transaction; rollback, exact Decimal values and age semantics remain.

Existing recovery workload also passes: 128/1024 fills on 30/120 markets,
.6606/6.9880s wall, fill-processing p99 7.314/10.887ms, loop-lag p99 3.482/4.382ms,
all 8/64 requested deadlines served. That diagnostic does not call the changed
snapshot-batching path. None of these measurements establishes live venue
latency, profitability, continuous-production capacity or a paper-trading stage.

## Next discriminating work

Establish the permitted starting-account baseline and historical coverage
contract, plus the missing cross-source continuity/cash guarantees; seek venue
clarification if no primary contract supplies them. Do not disguise a bounded
history interval or repeated matching snapshots as proof. Separately resolve
the non-circular portfolio-risk cap and Kalshi event/expiry/forced-exit mapping
with the operator before implementing those policy-dependent execution branches.
