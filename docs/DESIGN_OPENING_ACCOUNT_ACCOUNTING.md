# Opening-account accounting: next implementation contract

September 21, 2026. Priority 3 under D-062/D-064. Design and decision record,
not a live baseline, migration, account read, or entry grant. Supersedes no
accepted risk/accounting rule. The existing [evidence reader](BUILD_OPENING_ACCOUNT_CASH_EVIDENCE.md)
is the input; do not rebuild it.

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
3. A future single-writer durable checkpoint must atomically bind the approved
   boundary, ledger identity, writer revision, source digests, cash observation,
   empty opening lots, excluded-old-history evidence and unresolved blockers.
   It must never be inferred from a caller boolean. The current schema-3
   trading ledger must not be silently upgraded or given a fabricated baseline;
   design/test any new schema and migration separately before installation.
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
  not asserted to be bot-owned or installed as a durable runtime hold.
- A duplicate settlement with changed economics, a reversed/corrected fill,
  an unexplained cash delta, an old order/fill crossing the proposed boundary,
  or mismatched exchange/account scope must persist a blocker. No automatic
  correction rewrite, synthetic close, refund, payout or risk-window reset.
  D-025 already requires a verified venue correction contract before any
  automatic correction policy.
- A pending or unscoped transfer/funding record stays visible and blocks any
  claim that cash has been fully attributed. An absent venue event is not proof
  of no event. A restarted process must not re-arm from a historical flat read.

## Implementation sequence and acceptance

**A. Non-authorizing assessor.** Add a bounded pure review of the existing
opening evidence and local audit. Require exact scope/epoch/revision/time
agreement. Distinguish observed flatness, cash equality and unresolved
cash/settlement activity, while keeping `approved`, `ready_for_entry` and
`live_ready` false. Test wrong scope, zero/nonzero positions, resting/foreign
orders, pending fills, source conflicts, cancellation/revision races and old
funding. No ledger or network access.

**B. Durable accounting design gate.** D-066 settles the unexpected-settlement
pause rule; the checkpoint schema and exact event/hold/release protocol are not
approved. After those are designed and accepted, add one writer-owned immutable
checkpoint/cash-event journal in disposable ledgers only. Reject schema-3
migration until explicitly designed. Fault-inject crash before/after atomic
commit, duplicate/conflicting events, out-of-order arrival, stale balance,
restart and receipt-window cases.
Prove no event changes the stop meter except the approved accounting paths.

**C. Runtime integration gate.** Bind a fresh checkpoint, continuity assessment,
cash revision and current account/book/risk state to one entry decision. Revoke
on every ambiguous event or gap. Verify 30/120-market workloads, bounded
history/queue costs, shutdown/restart, full suite and disabled preflight. Do not
enable a production write transport or live run in this phase.

The D-066 rule is accepted but only its evidence-only assessment is currently
built. Exact launch timestamp, durable hold/release implementation, fresh
account proof and live trading approval remain separate gates. The operator
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
It neither installs basis/cash nor clears any evidence blocker. Phases B/C
remain gated by the open decisions and source proof above.
