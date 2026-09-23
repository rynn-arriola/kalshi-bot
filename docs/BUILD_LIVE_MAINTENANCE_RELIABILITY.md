# D-100: live maintenance reliability repair

Prepared September 23, 2026 in isolated checkout `fix/order-maintenance`.
Production generation 63 remains on `ad96429`; no stop, deployment, restart or
assistant venue mutation occurred.

## Evidence and design

The [dwell investigation](INVESTIGATION_MAINTENANCE_DWELL_2026-09-23.md)
reproduced starvation when otherwise valid observations arrived every six or
eight seconds. The live ledger separately showed 79 deterministic HTTP-400
passive reducers for one position across four prices before its hard IOC closed.
Retained diagnostics covered only ten seconds because empty broad-discovery
markets emitted over 95% of log rows.

Read-only Polymarket executable code was checked at its current local checkout.
It never blindly retries mutations, separates entry rejection from reducing
safety work and uses a 10-second circuit when a risk-reducing mutation itself is
rejected. Kalshi keeps that separation but persists consecutive identical
reducer backoff at 10, 20, 40 then 60 seconds. This is not a copy of Poly's
venue-specific 403 policy: Kalshi scalar HTTP 400 is already exact no-order
proof, and a changed price, quantity or passive/IOC mode starts a new material
command sequence immediately.

## Implementation

- Drift stores exact program/writer/account/order identity and verified source-
  covered seconds. Unknown intervals add no time; gaps over 15 seconds reset.
- A maintenance cycle carries its evidence deadline and identity. The remaining
  original leg may proceed after positive terminal proof of the first; changed
  quantity/price/owner or an expired lease cannot cancel at the send edge.
- Successful account repair requests one coalesced queue-position reflection so
  private account and reward evidence can join on the same report generation.
- Reducer HTTP-400 evidence is matched durably by active inventory episode and
  canonical request excluding only the new client ID. Consecutive identical
  rejections back off exponentially to 60 seconds and survive restart.
- HTTP errors are read under the existing byte/deadline bounds. Only an ASCII
  alphanumeric/`._-` error code up to 100 characters is retained; message,
  details and raw body are discarded.
- Inventory-plan diagnostics ignore empty discovered markets, retain all markets
  with positions/orders/unresolved exit work, and emit one final transition.

## Verification and review

Focused maintenance, reward, dispatch, command-handoff, transport and logging
sets pass. Deliberate reversals proved detection of dwell starvation, stale
send authorization, missed reflection wake, duplicate reducer retries, lost
error code and empty-market log flooding. Review replaced an initially permanent
identical-command hold with bounded safety backoff so a temporary venue condition
cannot suppress passive inventory management until the hard IOC deadline.

Final complete-suite count, commit and remote parity belong in STATUS. Live
acceptance remains pending a separately authorized controlled deployment/restart;
do not induce a fill or rejection solely to test it.

## Live-log follow-up: bounded history receipts and metadata races

The required post-fix log review found a separate deterministic failure. At
14:25:20 UTC the production writer rejected `history_complete` because the hot
`history_enumerations` table had exactly 4,096 rows. Every row was omission-free
and covered the same start with a progressively later end. The supervisor
automatically started a recovery-only child; it acknowledged 30 cancellations
but exhausted recovery, so its local zero-order/zero-position report is not a
current venue-flat proof.

The repair adds an additive schema-5 archive table. At capacity, the writer
validates the exact indexed rows, serializes them canonically, content-addresses
and compresses the payload, inserts one append-only archive, removes the hot rows
and inserts the fresh receipt in one transaction. Any validation, archive-limit,
compression or SQLite failure rolls the whole operation back. Archived counts
remain visible by subaccount and relevant interval, but archived evidence adds a
continuity blocker and cannot become current release authority.

Polymarket's current code was checked as a design reference: durable executions
are long-term truth while venue history reads are bounded recent positive
evidence. Kalshi preserves more exact audit data than that reference; it does
not copy Polymarket's venue history semantics.

The replacement child also produced 48 `exit_inputs_failed` events at the exact
final publication-race check and four dependency failures caused by
`QuotaUnavailable`. A typed superseded-read outcome now revokes and reschedules
without incrementing the market failure streak. Quota holds emit a deferred INFO
event and retain the scheduler's existing infrastructure wait. Real malformed,
conflicting or exhausted metadata still fails closed.

Final status review found 533 reward-reflection failures while the replacement
child had no current account report. Those attempts failed before any queue REST
request, but still wasted a four-second telemetry wake and obscured real failures.
The reward service now defers locally until the exact report prerequisite is
current; successful account recovery already requests the immediate reflection.

Focused recovery/metadata review: 237 tests passed. A disposable production-
scale run committed 4,097 receipts in 2.175 seconds, leaving one hot receipt and
one exact 4,096-receipt archive of 88,318 bytes with no active coverage gap.
No live database was modified or copied. Final complete suite: **1,611 tests
passed, one expected Windows privilege skip**, 259.825 seconds. Publication and
deployment state remain owned by STATUS. The reviewed implementation was
published as `5df66f7`; the active production checkout was not changed.
