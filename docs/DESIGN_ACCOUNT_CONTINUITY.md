# D-044 — Starting account and private-stream continuity design

Date: September 20, 2026. Design and source review only. Native Windows;
execution disabled. This is the next D-037 Astra design handoff. Stop before
implementation so the operator can switch to 5.6 Sol and select Phase 1.

## 1. What can be established now

The desired result is a defensible starting inventory and a complete record of
bot-owned fills after a chosen launch boundary, including reconnects. The
present code can establish *positive* facts: a fill reached the durable inbox,
a paginated REST enumeration returned particular rows, a matching owned order
exists, and a local ledger agrees with a scoped account observation. It cannot
yet establish that no fill was omitted between a REST read and private stream,
that an empty cursor is a venue-wide snapshot barrier, or that an earlier flat
account is still flat. `ready_for_entry` must remain false in this milestone.

Checked current official documentation September 20, 2026:

- [User fills](https://docs.kalshi.com/websockets/user-fills) publishes live
  execution messages with trade/order IDs and a subaccount field; [user orders](https://docs.kalshi.com/websockets/user-orders)
  publishes order updates. Their examples do not provide a shared REST/history
  watermark or replay cursor. A subscription ACK proves subscription acceptance,
  not that pre-ACK events were replayed.
- [Market positions](https://docs.kalshi.com/websockets/market-positions) is an
  update stream. Its published example has no subaccount field, while current
  `AccountCoordinator.on_event` requires one. Until actual scoped semantics are
  established, an unscoped position update is an invalidation/diagnostic input,
  not authoritative position or basis evidence.
- [Historical data](https://docs.kalshi.com/getting_started/historical_data) and
  [cutoffs](https://docs.kalshi.com/api-reference/historical/get-historical-cutoff-timestamps)
  split recent and archived fills by a moving trade timestamp. They do not state
  a bounded publication delay or an atomic handoff to a private socket.
  [Recent fills](https://docs.kalshi.com/api-reference/portfolio/get-fills)
  have a subaccount query; [historical fills](https://docs.kalshi.com/api-reference/historical/get-historical-fills)
  do not document that query and require per-row account evidence.
- [Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions),
  [resting orders](https://docs.kalshi.com/api-reference/orders/get-orders)
  and [balance](https://docs.kalshi.com/api-reference/portfolio/get-balance)
  are separate REST reads, not one atomic account snapshot. The balance
  `updated_ts` is its own last-change time, not a stream checkpoint.
  [Settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements)
  are a separate paginated source; settlement/correction accounting is not in
  the present recovery implementation.

These are limits of the published contract, not assertions that Kalshi never
offers stronger private guarantees. No credential or account read was used in
this design. Confirm any venue-specific guarantees before building a positive
continuity gate.

## 2. Existing code to retain

| Owner | Existing behavior | Missing proof |
|---|---|---|
| `runtime.py` / `transport.py` | One bounded account reader, generation changes, ACK validation, immediate ingress revocation, durable fill staging before queue acceptance | No venue replay/watermark; in-memory ingress revision does not survive crash |
| `account.py` | Exact local order/position audit, scoped snapshot, bounded historical fill/order recovery | Snapshot is several REST calls; no launch baseline, no atomic cross-source barrier |
| `recovery.py` / `history_coverage.py` | Recent+archive fill merge, cutoff recheck, immutable completed-enumeration receipts and omission detection | A receipt proves only returned rows and requested interval, not venue completeness |
| `writer.py` / `verification.py` | Single durable owner, deduplicated fills, exact owned-order comparison, local revision fence | No durable private-epoch gap record or approved starting inventory |

`RecoveryRuntime._repair()` already performs two local snapshots around history,
then checks account generation and ingress revision. Preserve that ordering and
its 20-second bound. Do not turn either snapshot or a zero-row history pass into
a complete-account certificate. `history_coverage.ready_for_entry` and runtime
`entry_allowed` stay false. D-030 keeps the previously seen 18 fills outside
the bot trading record while retaining them as reconciliation evidence; no
launch timestamp, migration or loss reset was approved.

Polymarket source was inspected read-only: `account_snapshots.py` treats recent
execution history as positive backfill and an empty response as insufficient
negative proof; `account_source_runner.py` validates candidate scope and drains
private events around a source handoff; `bot_era.py` separates bot-era results
from account-wide history. Reuse those distinctions, not its endpoint semantics,
cash guarantees, retention or dates. The Polymarket folder was not changed.

## 3. Evidence model and interfaces

Add `src/kalshi_bot/continuity.py` as a small, pure assessment layer. It does
not own a network loop, order command or cash balance. Proposed frozen records:

- `PrivateEpoch`: subaccount, reader generation, writer epoch, required-channel
  ACK set, local start/end times, ingress counters, durable fill count, terminal
  reason and a `clean_local_delivery` diagnostic. A clean local span says only
  that our bounded reader observed no local transport/queue failure. Its
  subaccount is the configured assessment target, not a claim that the whole
  private feed is scoped to it; each event still needs its own account evidence.
- `StartingAccountCandidate`: explicitly selected subaccount and *proposed*
  UTC boundary, current scoped snapshot/report revisions, outstanding/foreign
  order IDs, pending fills, position quantities and unresolved-basis markers.
  It is a proposal for operator review, never a self-approved baseline.
- `ContinuityAssessment`: source generation, writer epoch/revision, receipt
  IDs/interval gaps, observed stream-span state, exact local agreement and a
  stable tuple of blockers. It has separate `local_evidence_consistent` and
  `venue_handoff_proven` flags; Phase 1 fixes the latter to false. It cannot
  set entry authority.

Use the existing single `LedgerWriter` for any durable epoch marker. A marker
is opened when account subscription is accepted and closed only after orderly
reader drain; a crash leaves it open/unknown on restart. A transport error,
queue/byte overflow, malformed private event, writer failure, missed ACK,
generation mismatch or account scope ambiguity makes the span invalid. An
in-memory counter or quiet period cannot repair it. Do not write raw private
payloads or credentials into the marker or diagnostic logs.

`RecoveryRuntime` remains the one account-state owner. Its private handler
continues to stage fills before queue acknowledgment and recomputes assessment
only on account/recovery changes, not on each public book tick. For a
`market_position` message lacking documented subaccount scope, revoke the
report, retain the account feed for later fills if safe, and request one
coalesced scoped REST reconciliation; do not install its quantity/cost as
authoritative. If scope is explicit and matches, it remains advisory until
reconciled. Preserve today's fail-closed behavior on malformed or conflicting
events. Bounded queues and one recovery worker remain.

`RestReads.collect` should distinguish an explicitly exhausted positions cursor
from an omitted cursor before calling the resulting set complete. Verify the
current positions schema's optionality against a controlled read or venue
clarification; if absent, report incomplete rather than assuming EOF. Keep
recent/archived fill windows overlapping, exact-ID deduplication, cutoff
recheck and the shared account read budget. No new per-market REST polling.

The assessment API should accept already validated `ReconciliationReport`,
`RecoveryReport`, `EnumerationCoverage` and `PrivateEpoch` data, check matching
subaccount/generation/writer revision and return blockers. Status may read the
cached assessment in O(1); a fresh database/history inspection remains an
explicit control-plane operation. Existing `ready_for_entry=False` and
`live_ready=False` remain the outer authority boundary.

## 4. Phase sequence and failure handling

**Phase 1 — evidence-only continuity and baseline candidates (Sol handoff).**
Add the pure assessment records, durable local private-epoch markers and
runtime/status wiring. Tighten incomplete position pagination and handle
unscoped position updates without treating them as scoped facts. Use existing
REST recovery calls; add no new network loop or live action. No baseline is
installed. All positive output is labeled local/observed; the venue handoff
remains unproven. Existing history receipts and accounting stay immutable.

**Phase 2 — conditional venue handoff.** Seek a documented Kalshi sequence,
replay/snapshot barrier or bounded fill-publication contract, including account
scope and reconnect behavior. If one exists, design a barrier-specific overlap
protocol and offline fault tests before any positive handoff result. If none
exists, do not fabricate one from repeated REST reads, matching balances or a
quiet stream. A fresh operator-controlled account boundary may be an alternative
only after the operator selects account/subaccount, exclusivity and timestamp and
we verify that old orders/fills cannot leak across it. Phase 2 is not approved by
this design handoff.

**Phase 3 — complete opening state and cash/settlement contracts.** Establish
starting lot basis or a proven flat opening state, unresolved old orders,
settlements/corrections, transfers and cash/hold reconciliation. Only then
integrate any verified handoff with risk/admission; that integration needs a
separate design, review and live authorization. No automatic old-ledger import
or risk-window reset is implied.

Failure rule for all phases: preserve positive fill/order evidence, revoke
current proof and new-entry eligibility on ambiguity, and report the precise
blocker. Never infer cancellation from 404, missing rows, flat net position or
an empty stream. Writer failure and saturation are terminal for that run;
retry exhaustion remains visible. A later healthy account ACK alone cannot
clear a persisted gap or previously omitted fill.

## 5. Phase 1 acceptance and budgets

Offline regressions: subscribe/ACK and no events; fill before and during REST;
fill after snapshot; fill-before-order; reconnect with old-generation tail;
crash leaving open epoch; queue overflow; cancelled close; duplicate/conflicting
fill; moved cutoff; omitted prior fill; partial/missing positions cursor;
unscoped/mismatched position; foreign resting order; other subaccount;
settlement-shaped position change; writer failure; restart after clean span.
Every case must keep `venue_handoff_proven=False`, `ready_for_entry=False` and
`live_ready=False`. Test that a locally clean span reports no invented venue
continuity and that a source-generation/writer revision mismatch invalidates
the cached assessment. Test at least two process-local fault reversals.

Predeclared resource fixtures: 30 and 120 markets; 128 and 4,096 remembered
fills/receipts, 30/120 cached assessments and a bounded reconnect burst. Reuse
D-035's 10,000 staged-fill and 4,096 receipt caps, D-028's 128-market default
capacity, existing 256-message/2 MiB account reader and the shared read-token
budget. Additional peak Python memory <40 MiB, assessment/inspection p99
<250 ms and event-loop lag p99 <50 ms. No extra REST GET during steady healthy
stream, no per-market task/DB scan and no dropped durable fill. Keep the current
history staging wall budgets (<3 s at 128 rows; <15 s at 4,096). These are
offline engineering budgets, not paper trading or a live throughput promise.
Run focused integration/restart tests, resource fixtures, exact full suite and
execution-disabled preflight after source edits. Review the Git diff for
secrets and unrelated changes. Phase 1 does not need real credentials or account
calls.

## 6. Operator decisions and next gate

UNKNOWN: a shared Kalshi private/REST watermark or replay guarantee, a bound on
late fill publication, and whether position updates can be scoped by
subaccount. Also undecided: exact approved bot launch boundary, account
exclusivity, treatment of pre-bot inventory, corrections/settlements and
cash/transfer baseline. The operator owns those decisions; the design does not
choose a timestamp, subaccount, risk limit or live schedule.

STOP HERE. D-044 authorizes design only. The operator switches to 5.6 Sol and
explicitly assigns Phase 1 implementation, then Astra reviews. This document
does not approve Phases 2/3 or any trading action.
