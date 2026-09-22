# Permanent engineering rules

These are design/review requirements, not claims about implemented behavior.
Current state belongs in [STATUS.md](STATUS.md), authorization in
[DECISIONS.md](DECISIONS.md), and session routing in [AI_OPERATOR.md](AI_OPERATOR.md).

D-061 supersedes D-049's mandatory model selection and switch gates. Continue
authorized work with the active model while retaining actual review,
verification, safety and authority boundaries from `AI_OPERATOR.md`.

## Standing operator rules — D-014

1. Follow the Polymarket bot's Markdown ownership/routing pattern, adapted to
   Kalshi. Do not import its strategy, risk limits, endpoint semantics,
   credentials, runtime permissions or deployment commands.
2. **WebSocket first for information.** Use documented feeds wherever they
   supply the required information with sufficient correctness/freshness.
   **REST is the fallback for information not available through WebSocket.**
3. **CPU-efficient and scalable from the design stage.** Every new component
   needs bounded resource use, clear state ownership, and a performance/scaling
   verification plan. Do not defer these requirements to a rewrite.

## Transport and authority

- D-036 uses one account-wide Read budget from verified limit/cost documents,
  never one per WebSocket/market/shard. Capacity is not available server tokens.
  Preserve endpoint costs, account-read priority, bounded background headroom
  and shared 429 pauses even on the final/late attempt. Writes require separate
  verified scope/cost/routing and cancel/exit priority; no read quota authorizes
  mutations. Supervised launch must enforce quota freshness/grant expiry.
  Metadata retry exhaustion survives lifecycle/reconnect ACKs; explicit retry
  preserves cooldown and never approves missing market/profile evidence.

- D-035 history receipts attest only completed bounded enumerations after durable
  staging. Keep interval gaps, source provenance and omitted known fills explicit.
  Never credit future time, infer a venue watermark from cursor exhaustion, or
  restore current authority from persisted receipts. Unknown old fills are not
  foreign by default; no receipt can install a launch boundary or reset risk.

- D-034 metadata publication must preserve observed stream fields even before
  bootstrap/after baseline expiry, reject conflicting REST, and bind all awaited
  dependencies to current generation/revision/freshness. Event timing requires
  reviewed rules-to-milestone scope; fee precision requires verified membership.
  Never infer either from expiry labels or cash formatting. Future launch owns
  bounded control-plane refreshes, not per-book metadata polling.

- D-032 exit inputs require verified tick bands, event-risk/maintenance timing
  and a conservative taker-fee bound. Expected/latest expiry is not an event-risk
  clock. IOC must be exact remaining inventory, reduce-only and without expiry.
  Book freshness is measured from ingress, not later processing. Advisory plans
  never confer execution authority; cancel ACK/absence never proves no fill.

- D-019 requires native Windows, with its own virtual environment, Windows
  process ownership/locking, graceful control and recovery. Do not copy bash,
  flock, systemd or POSIX-signal assumptions from the Polymarket runtime.
- D-020 requires source tracing and appropriate offline verification before
  asserting inherited behavior. Documents are routing/history, not code proof.

- Maintain a field-level source map: primary stream, missing fields, REST
  endpoint if any, scope, freshness, completeness and recovery rules.
- Do not poll REST for data already supplied by a healthy sufficient stream.
  Every REST consumer needs a documented reason, budget and refresh trigger.
- Use stream snapshots/deltas when available. Incomplete startup/history,
  reconnect gaps or authoritative reconciliation may require bounded REST
  because required complete information is unavailable in the stream.
- A disconnected stream does not prove REST is equivalent or authorize blind
  trading. Revoke stale proof, recover the stream, and validate fallback
  completeness, freshness and capacity before it authorizes risk. If neither
  source is adequate, block new risk; never fabricate state.
- Data delivery and order commands are separate. Use documented mutation
  endpoints when authorized; do not invent WebSocket order commands.
- D-072 entry quoting is one source-bound two-leg unit: reserve both legs in one
  writer transaction, then submit one V2 batch create. Batch transport is not
  assumed atomic. Identify every row by client order ID; any mixed, missing or
  uncertain outcome requires reconciliation and no automatic retry. Charge the
  documented per-order batch cost to the unscoped write bucket. Existing
  single-create reducers and single-order cancels keep safety priority.
- One account-state coordinator owns reconciled state; one mutation authority
  owns orders. Source generations, scope and timestamps prevent older REST
  responses overwriting newer stream evidence. Missing data means unknown.

## CPU and scalability requirements

- Use event-driven scheduling: evaluate changed markets and due safety timers,
  not every market on every iteration. Position/risk deadlines remain serviced
  even when no market event arrives.
- Share bounded subscriptions, normalized books, metadata caches and in-flight
  reads. Avoid one connection/poll loop/database query per consumer or market.
- Apply ordered book deltas incrementally. Coalesce downstream recomputation,
  not unapplied deltas or execution events. Fills/order events must not be lost.
- Bound queues, concurrency, subscriptions, caches, retention and retries.
  Overflow invalidates affected state and triggers recovery; never silently
  discard safety-critical information. Backoff must avoid reconnect/poll storms.
- Prioritize fills, cancellations, risk and exits over discovery, analytics
  and reporting. Expensive catalog work must be chunked/preemptible.
- Keep database scans, blocking network/file operations and heavy reports off
  the event-processing path. Durable intent must still precede a mutation;
  batching must not weaken that guarantee.
- D-060 command preparation is one writer transaction: risk checks, durable
  capacity funding, intent and PREPARED mutation evidence. Dispatch consumes
  the immutable post-commit receipt once. Preserve the 4,096 ordinary-entry /
  8,192 total mutation bounds and the 4,096 intent/order bounds; funded safety
  commands convert held capacity atomically. Never bypass credits, silently
  reclaim history, reuse a stale/old-epoch receipt or auto-migrate an old ledger.
- Pair preparation may compose those D-060 reservations only when rollback is
  all-or-none. The exact immutable pair must survive preparation, quota permit,
  SENDING transition and transport. One writing worker per ledger remains the
  scalability boundary; do not parallelize writes across the same account.
- Preserve exact money/quantities with explicit fixed-point scales or Decimal.
  CPU optimizations cannot change monetary results.
- Start with the simplest bounded concurrent design. Add workers/processes or
  shards only when measured capacity justifies them. Preserve one owner for
  each mutable state partition and one account-wide risk authority.
- Measure CPU, memory, event-loop delay, queue backlog, event-to-decision and
  fill-to-risk-action delay, REST token use and reconnect load. Report latency
  p50/p95/p99 and workload scope. No optimization/scalability claim without data.
- Define workload sizes, bursts, saturation behavior and acceptance budgets
  before implementation. Offline unit/load fixtures are engineering checks,
  not paper trading or simulated-income evidence. Increasing live scale or
  risk still requires explicit operator decisions.

## Safety and verification

- D-033 requires bounded structured diagnostics with stable event codes, run and
  operation correlation, safe stack locations and explicit logging-health state.
  Never log raw credentials, requests/responses, exception messages or locals.
  Keep disk work off the event loop, rotate bounded local files and use one
  shared sink. Logging failures must be visible and revoke runtime authority;
  never silently drop errors, ignore unexpected faults or retry unknown orders.
  Logs are not the durable financial ledger. See `docs/LOGGING_AND_ERRORS.md`.

- Pending rewards are not paid cash; collateral is not realized P&L. D-016 sets
  10-contract entries, max 30 resting entries excluding position-management
  orders, and $25 settled-loss stops in fixed six-hour Eastern Time windows.
  The $500 capital ceiling remains. D-018 adopts Polymarket inventory rules:
  $90 market exposure at size 10; portfolio exposure = size * (market slots + 10).
  D-020 establishes that $420 is a 32-slot example, not an independently
  approved fixed cap. D-023 directs limits-driven market capacity rather than
  an arbitrary fixed slot target. D-031 follows Poly's verified local default
  reference of 20: `10 * (20 + 10) = $300` aggregate exposure. This calibrates
  dollars, not current occupancy or a new 20-market admission ceiling. Never
  widen the risk budget as occupancy grows or import future Poly config changes
  automatically. Count inventory and conservative
  working/ambiguous order exposure, including reducers; the resting-entry
  count exemption is separate. Use exact reducing management after a fill.
  Complete Kalshi-specific exit/deadline mapping before implementation.
  Stop triggers are not guaranteed maximum losses.
- D-024 resolves accounting and supersedes D-017's fee timing: immediately count
  matched partial-close P&L at weighted-average basis and every actual fill fee,
  including fees on open/unmatched inventory. Use first durable receipt windows,
  not original execution windows, for late fills. Keep execution time separately
  for reports; deduplicate without resetting receipts, caps or held stops.
  Never substitute cash changes, open-position marks or reward income.
  Corrections, settlements and old-ledger migration need separate contracts;
  D-018's inventory safeguards remain separate.
- Never blindly retry an ambiguous order creation or infer cancellation from
  absence. Reconcile execution IDs, partial fills and terminal venue proof.
- D-025 permits automatic verified bot-fill recovery. Exact durable intent/order
  scope must precede import; immutable conflicts block. Preserve D-024 receipt
  windows and per-fill ratchets, including within recovery batches. Venue position
  cost may support an independently owned, fresh exit-only basis, never synthetic
  trades, complete-history claims or realized P&L. Do not invent a Kalshi trade-bust
  signal. Derived receipt totals require an append-only journal; any future
  correction/pruning must transactionally invalidate/rebuild them.
- Readers do not place orders or independently update risk authority. Reports
  use local read-only telemetry with source/age, cannot block execution, and
  must not become a second venue-polling system.
- D-026 recovery integration must durably retain unresolved fills before event
  queue acknowledgment, revoke account reports at ingress, and apply/remove inbox
  evidence atomically. Recover independently by reader generation, with one
  coalesced bounded recovery worker. Do not reset retry budgets on an acknowledgment
  or mistake completed repairs for complete history, stream continuity or entry
  authority. Preserve pending evidence and risk holds through local restarts.
- D-027 advisory plans must validate account, book and writer revisions after
  awaits and when consumed. Per-market reads stay indexed/bounded; do not run
  a portfolio scan per public tick. Reservations recompute shared exposure in
  the owner transaction; caller totals and old owner epochs are not authority.
  Positive fixture reservations do not establish a production cash/entry gate.
- Account snapshots must compare exact ownership/terms and pending/terminal-fill
  evidence in one writer view, not aggregate counts. D-028 local agreement and
  history interval provenance never imply a venue/private-stream barrier or
  complete starting basis. Report those missing guarantees separately.
- Review startup, steady operation, overload, stale data, disconnects,
  cancellation races, shutdown and recovery end-to-end before implementing.
  Add focused regressions for fixes; where safe offline, prove tests fail when
  the fix is reversed. Verify final artifacts and relevant complete suites.
- Do not copy Polymarket's stream failure modes or numeric API budgets as
  Kalshi facts. Check [the API reference](docs/KALSHI_API_REFERENCE.md) and current
  official contracts. No invented endpoints, performance results or rewards.
- Preserve unrelated edits, histories and credentials. No secrets in docs,
  logs or tests. No modifications to the Polymarket reference project.

See [architecture](docs/ARCHITECTURE.md) and [document ownership](docs/DOCUMENTATION_STRUCTURE.md).
