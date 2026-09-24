# Opening-account accounting: next implementation contract

September 21, 2026. Priority 3 under D-062/D-064. Design and decision record,
not a live baseline, migration, account read, or entry grant. Supersedes no
accepted risk/accounting rule. The existing [evidence reader](BUILD_OPENING_ACCOUNT_CASH_EVIDENCE.md)
is the input; do not rebuild it. D-067 implements the durable candidate,
observation/restriction journal and command gates in
[BUILD_DURABLE_ACCOUNTING.md](BUILD_DURABLE_ACCOUNTING.md). References below to
an approved baseline or successful release are now implemented offline under
[D-068](BUILD_ACCOUNT_RECONCILIATION.md); real launch evidence remains required.

## Release-path investigation — 2026-09-21, accepted under D-068

D-068 accepts operational reconciliation after the operator's “Ok follow poly.”
This permits an offline positive accounting path, not a live launch or a claim
of globally complete venue history. D-066 economic restrictions remain active.

### What was verified

- [User data timestamp](https://docs.kalshi.com/api-reference/exchange/get-user-data-timestamp)
  explicitly describes an **approximate** last-validation indication for balance,
  orders, fills and positions. It is not a shared sequence number or a replay
  boundary. Waiting until it passes a local timestamp cannot prove completeness.
- [Order reads](https://docs.kalshi.com/api-reference/orders/get-orders) distinguish
  resting/canceled/executed orders and retain resting orders in the current API;
  older terminal orders require historical storage. [Fill reads](https://docs.kalshi.com/api-reference/portfolio/get-fills)
  support order/account/exchange filters, but older fills also require historical
  retrieval. Per-order cumulative counts provide a useful reconciliation target,
  not proof that the current REST response includes the latest execution.
- [User orders](https://docs.kalshi.com/websockets/user-orders) and
  [user fills](https://docs.kalshi.com/websockets/user-fills) carry order identity,
  quantities, account/exchange scope and fill economics. The reviewed contracts
  do not establish a shared REST/stream replay cursor.
- `balance_dollars` is documented as available cash, with an exchange breakdown
  on the primary-account response. Do not substitute portfolio value, add back
  inferred holds, or import perpetual-futures margin rules into predictions.
- Polymarket source cross-check: `account_snapshots.py:426` brackets positions
  with matching cash reads; `bot_era.py` separates owned ledger activity from
  account-wide funding/equity. Matching cash cannot rule out offsetting activity
  or common REST/stream delay. The reference is not a stronger venue guarantee.

### Accepted operational gate

Replace the unconditional requirement for a globally complete venue history
with a separately named **bot-owned reconciliation** requirement. Keep
`venue_handoff_proven=false`; never re-label this operational gate as an atomic
snapshot or lossless venue guarantee. Preserve the operator-approved $500,
10-contract, 30-resting-entry and six-hour loss policies.

1. **Opening:** explicit launch-boundary approval tied to ledger identity,
   primary account and exclusive ownership. No prior bot sends. Fresh scoped
   zero-position/zero-resting-order reads, no pending/unbound evidence, bracketed
   cash observations and an active private epoch. Store the candidate plus the
   distinct approval; a generic review acknowledgement cannot approve a boundary.
2. **Catch-up:** freeze new-entry preparation while one retained account-owner
   pass reads complete bounded pages and reconciles the exact durable intent/
   order universe. Bind all fills by order and execution identity; compare
   cumulative filled counts, terms and current position quantities. A missing
   order is not canceled; unknown sends, missing fills, mismatched scope,
   conflicting economics or an incomplete archive pass cannot release the hold.
   Preserve already seen events if later responses omit them.
3. **Source fence:** capture reader generation, ingress revision, writer epoch
   and revision before the pass; invalidate on every change, disconnect, timeout
   or failure. Bound freshness at issuance and consumption. Reconcile once per
   coalesced bootstrap/recovery need using the shared read budget, not per tick.
4. **Cash:** use two independent ceilings, never two summed deductions:
   `max(0, min(fresh_venue_available, local_cash - outstanding_obligations))`.
   Starting local cash comes only from the approved flat boundary. Derive local
   cash from owned fill economics, including actual fees, with open-order and
   candidate fee bounds from verified metadata. Do not credit pending rewards,
   unknown transfers or unreviewed settlements. Apply account-wide **and**
   exchange-specific constraints; aggregate cash cannot fund another shard by
   assumption. Portfolio risk limits remain a separate check, not a cash balance.
   This lower-bound model avoids needing to guess whether venue cash has already
   deducted a particular order hold. It does not prove exact venue hold semantics.
5. **Release transaction:** recompute current state on the sole writer; append
   the exact resolved restriction instances and evidence digest to an immutable
   reconciliation record. Clear only eligible source/observation restrictions.
   Bind any short-lived admission receipt to checkpoint, cash, active epoch,
   source revisions and writer revision; recheck at reservation and send. Never
   accept a caller `account_known` or `handoff_proven` boolean as a substitute.
   Saturation or inability to save the release leaves restrictions intact.
6. **Economic holds:** D-066 settlements still require a specific operator
   reconciliation, not auto-release after apparent flatness. Unknown activity,
   conflicting fills/corrections, journal corruption/fullness and wrong scope
   need their underlying cause resolved. A release cannot discard lots, invent
   P&L, reset risk windows, or turn a review reference into resolved economics.
7. **Restart:** persisted evidence survives, but no admission receipt survives a
   writer restart or private disconnect. Reconcile again. Pending commands keep
   their cash/exposure obligations until exact terminal/proven-unsent evidence.
   Existing schema-4 files are not automatically migrated by this assignment.

**Residual risk requiring the operator's choice:** an event delayed by both REST
and WebSocket can temporarily escape the checks. Offsetting fills can leave a
matching position/cash snapshot. The proposed gate reduces and bounds known
uncertainty but cannot promise immediate detection of all venue activity or a
guaranteed maximum loss. The alternative is retaining the strict requirement
and seeking a stronger documented venue contract. This is why changing the
entry gate needs approval, rather than silently deleting the current hold.

### Accepted implementation checklist

- Extend existing accounting/writer ownership with scoped cash state and
  immutable release evidence; no second account reader or orchestrator.
- Extend `AccountCoordinator` to produce source-bound reconciliation input from
  existing history/private-epoch owners; keep cancellation ownership and bounds.
- Bind the resulting short-lived evidence to `portfolio.reserve_entry` and
  `execution.begin_send`, retaining all other command/risk/transport checks.
- Add deterministic fixtures for successful opening/release, wrong/expired/
  forged/replayed evidence, restart, ingress during every await, missing or
  late fills, archived orders, duplicate fees, settlement and correction holds,
  cross-shard cash, pending/ambiguous sends and transaction rollback.
- Prove cash equations with YES/NO opening, partial close, full close and
  reversal examples; compare the two-ceiling result when venue cash includes
  or excludes working-order holds. Reject missing fee bounds. Demonstrate the
  residual common-delay scenario explicitly rather than marking it detected.
- Test bounded 30/120-market paths and retained-history scaling, review the
  actual diff, run full suite and disabled preflight, then commit/push/parity.
  No account call, real boundary approval or live start is part of that build.

## Source and authority boundary

- The bot will use primary subaccount 0 exclusively and begin only from a
  freshly verified zero-position, zero-resting-order account (D-064). The exact
  UTC boundary belongs to a separately approved launch. Earlier fills remain
  separate reconciliation evidence (D-030), never silently deleted or imported.
- The current ledger owns bot fill IDs, weighted-average lots, actual fill fees,
  matched-close P&L and first-durable-receipt loss windows (D-024). It does not
  own venue settlements, corrections, cash-flow or opening checkpoint records.
  `realized_totals` assumes an append-only receipt journal; a correction cannot
  rewrite an older P&L row without an explicit transactional invalidation rule.
- [Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance) is a
  scoped observation of available balance, portfolio value, per-exchange
  breakdown and its own update timestamp, not an atomic snapshot with orders,
  positions or fills. [Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions)
  and [settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements)
  are separate histories. The settlement response shows ticker, exchange index,
  result, counts/costs, revenue, fee and time, but no stable correction/reversal
  identity or documented replay barrier. Do not interpret `revenue` as bot P&L
  or infer original lot basis from aggregate venue costs.
- The [total resting-order value](https://docs.kalshi.com/api-reference/portfolio/get-total-resting-order-value)
  endpoint is explicitly intended for FCM members; it is not a general hold
  ledger for this bot. The published [private fill feed](https://docs.kalshi.com/websockets/user-fills)
  does not document a shared REST watermark/replay cursor. Cursor exhaustion,
  a quiet stream and matching repeated balances do not prove handoff completeness.

## Proposed ownership and data flow

1. `AccountCoordinator` remains the sole account reader. It gathers current
   scoped positions, resting orders, balance and bounded histories under one
   retained inspection. Preserve exact source/query, cursor exhaustion,
   observed times, reader generation and writer revision. Reject stale or
   conflicting evidence; do not poll per market.
2. A pure opening-account assessor derives a **candidate**, never authority:
   primary scope, proposed boundary, zero inventory/order evidence, no pending
   fills or unresolved commands, exact cash observation, source receipts and
   explicit blockers. Zero venue inventory suggests zero starting lot basis
   only for that candidate; it does not prove that a late pre-boundary fill
   cannot arrive. Every result retains the venue-handoff and non-atomic-cash
   blockers until an approved boundary/proof protocol exists.
3. D-067's single-writer schema-4 checkpoint binds a **proposed**, not approved,
   boundary, ledger identity, writer revision, source digests, cash observation,
   flat local audit and unresolved blockers. It never grants entry authority.
   Existing schema-3 ledgers are refused before mutation; no migration exists.
   Installing an approved live baseline still requires the source proof and
   separately authorized opening protocol below.
4. After a checkpoint, preserve distinct journals for bot fills, venue cash
   observations, member funding, scoped transfers, settlements and potential
   corrections. Deduplicate by documented identity and reject immutable
   conflicts. Member-level funding and intra-exchange transfers without exact
   account/completion attribution remain unknown. Cash movement is not trading
   P&L or a settled-loss reset.
5. Admission uses current, scoped available-cash evidence plus the existing
   single-writer held-risk/working-order reservations. Do not derive cash from
   fills/settlements alone, subtract guessed holds, count `portfolio_value` as
   spendable, or reuse a pre-await balance. Unknown available cash blocks new
   entries; reducing/cancel safety authority follows its separate rules.

## Failure and accounting rules

- D-066 accepts the recommended safety rule: an unexpected settlement of a
  bot-owned open lot pauses new entries pending operator reconciliation. It is
  **not** silently treated as a fill or assigned six-hour P&L. Existing matched
  trade closes and actual fill fees continue under D-024. A settlement on an
  old or unknown-owned lot cannot enter bot-era P&L. An observed settlement
  after a merely proposed boundary is conservatively marked for reconciliation,
  not asserted to be bot-owned. D-067 now persists this restriction when the
  explicit account-owner reconciliation operation is invoked.
- A duplicate settlement with changed economics, a reversed/corrected fill,
  an unexplained cash delta, an old order/fill crossing the proposed boundary,
  or mismatched exchange/account scope must persist a blocker. No automatic
  correction rewrite, synthetic close, refund, payout or risk-window reset.
  D-025 already requires a verified venue correction contract before any
  automatic correction policy.
- A pending or unscoped transfer/funding record stays visible and blocks any
  claim that cash has been fully attributed. An absent venue event is not proof
  of no event. A restarted process must not re-arm from a historical flat read.
- Lifecycle enrichment is narrower than economic reconciliation. A complete,
  cursor-exhausted funding source may prove that an already approved applied
  deposit gained only a pre-boundary finalization timestamp. That history grants
  no authority; missing records, new records, changed identity/economics/status
  or finalization at/after the boundary remain unexplained activity.

## Implementation sequence and acceptance

**A. Non-authorizing assessor.** Add a bounded pure review of the existing
opening evidence and local audit. Require exact scope/epoch/revision/time
agreement. Distinguish observed flatness, cash equality and unresolved
cash/settlement activity, while keeping `approved`, `ready_for_entry` and
`live_ready` false. Test wrong scope, zero/nonzero positions, resting/foreign
orders, pending fills, source conflicts, cancellation/revision races and old
funding. No ledger or network access.

**B. Durable accounting.** D-067 authorizes and implements a writer-owned
immutable candidate and cash-event/restriction journal in disposable schema-4
ledgers. No existing schema-3 ledger is migrated. The exact live opening and
successful reconciliation-release protocol remain unproved. Fault-inject crash before/after atomic
commit, duplicate/conflicting events, out-of-order arrival, stale balance,
restart and receipt-window cases.
Prove no event changes the stop meter except the approved accounting paths.

**C. Live-authority integration gate.** D-067 enforces durable restrictions at
reservation and prepared send; this does not yet produce an eligible live entry.
Bind a fresh approved checkpoint, continuity assessment,
cash revision and current account/book/risk state to one entry decision. Revoke
on every ambiguous event or gap. Verify 30/120-market workloads, bounded
history/queue costs, shutdown/restart, full suite and disabled preflight. Do not
enable a production write transport or live run in this phase.

The D-066 rule now has durable entry restrictions under D-067. Exact launch
timestamp, a proved reconciliation release, fresh account proof and live
trading approval remain separate gates. The operator
has not approved a formula for assigning reconciled settlement P&L to a window.

## Polymarket code cross-check (read-only)

The checked `C:/Users/rynna/Bots/liquidity-bot` source separates older account
activity from bot-owned history (`bot_era.py`), keeps account-wide cash/equity
distinct from bot-era P&L (`account_snapshots.py`), brackets a position mark with
two matching cash reads, and returns unknown realized/open P&L when position
basis is absent. Its `cash_activity.py` treats the opening cash timestamp as
exclusive to avoid subtracting an included transfer twice. Its
`execution_ledger.py` attributes delayed realized losses by durable receipt for
risk windows. These are useful boundary and failure-mode patterns, not portable
venue contracts: Kalshi's settlement fields, account scope, correction identity
and cash-hold semantics must be verified independently. No Poly files changed.

Phase A implemented: `assess_opening_accounting` classifies a revision-matched
local flat candidate and cash equality from already normalized evidence. It
explicitly marks an observed post-proposed-boundary settlement as requiring
reconciliation, without computing settlement P&L or auto-clearing the finding.
It neither installs basis/cash nor clears any evidence blocker. D-067 adds
Phase B's durable observations and Phase C's entry-restriction checks. Source
proof, cash attribution and a release granting live entries remain unresolved.
