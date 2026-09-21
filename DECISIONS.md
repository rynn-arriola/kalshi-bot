# Operator decision ledger

This is the authority record. AI agents may recommend decisions but may not mark
them accepted without an explicit operator instruction.

## Accepted decisions

### D-001 — Measure before building

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Do not build the full Kalshi bot yet. Determine whether the
  Polymarket US strategy can work profitably on Kalshi through measurement.
- **Consequence:** Production package, multi-market execution, deployment, and
  scaling work are paused.
- **Revisit when:** The experiment gates in `EXPERIMENT.md` have enough evidence
  to support a build/no-build recommendation.

### D-002 — AI-maintained repository

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Assume the operator will not write the code. AI agents maintain
  the code, tests, research, and handoff documentation.
- **Consequence:** Every material session must leave `STATUS.md`, `NEXT.md`, and
  the evidence trail usable by a fresh AI session.
- **Revisit when:** The operator changes the maintenance model.

### D-003 — Operator retains consequential decisions

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** The operator makes strategy, capital, risk, live-action,
  deployment, and scope decisions. AI agents investigate, recommend, implement
  approved work, and report results.
- **Consequence:** No AI may convert a recommendation into authorization.
- **Revisit when:** Only by explicit operator instruction.

### D-004 — No live mutation in the current phase

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator, preserving the existing project constraint
- **Decision:** Current work is read-only measurement and experiment design.
  Live order placement remains outside scope. A later minimal evidence run must
  receive a separate operator decision, and the operator performs the arming
  action unless this decision is explicitly amended.
- **Consequence:** Keep `kalshi_auth.py` read-only and add no order endpoint yet.
- **Revisit when:** Read-only gates justify a minimal live experiment.

### D-005 — Polymarket repository is a read-only reference

- **Status:** ACCEPTED
- **Date:** 2026-08-17
- **Decision owner:** Operator
- **Decision:** Do not modify `D:\polybot\liquidity-bot`; copy concepts only
  after separating venue-independent safety from venue-specific calibration.

### D-006 — Canonical GitHub repository

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Publish and maintain this project at
  `https://github.com/rynn-arriola/kalshi-bot.git`.
- **Consequence:** This remote carries measurement code, tests, and AI handoff
  documentation. Ignored credentials and captured data remain local only.
- **Revisit when:** The operator names a replacement repository.

### D-007 — Isolated server measurement is allowed

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Read-only Kalshi measurement may run on the server that hosts
  the Polymarket bot, but it must be installed in a new standalone Kalshi
  project folder and never inside the Polymarket folder.
- **Consequence:** Use a separate top-level directory, environment, process,
  configuration, data, and logs. Do not import from, write inside, restart, or
  make API calls through the Polymarket project. Read-only Kalshi API calls are
  permitted from that isolated project; authenticated writes and all live order
  actions remain prohibited by D-004. The boundaries in
  `docs/SERVER_MEASUREMENT.md` are mandatory.
- **Revisit when:** Measurement resource use interferes with production, or the
  operator selects a separate server.

### D-008 — Include spread scalping in the measurement

- **Status:** ACCEPTED
- **Date:** 2026-08-27
- **Decision owner:** Operator
- **Decision:** Measure whether two-sided spread capture is profitable on the
  current Kalshi data, both alone and combined with liquidity reward. For the
  pure-scalping result, compare feasible quote-spread widths and identify which
  width, if any, has the best bounded net P&L without crediting any reward.
- **Consequence:** Offline/read-only replay may measure pair completion,
  one-sided inventory, fees, exits, and net. Keep pure scalping and reward
  separate before producing a combined result. Spread widths must use the same
  market universe, evaluation windows, size, queue assumptions, and exit rules;
  report gross pair edge and fill rate separately from net. This does not
  authorize live orders or a new strategy implementation.
- **Revisit when:** A fixed-universe replay provides a decision-grade estimate.

### D-009 — Move read-only measurement to the laptop

- **Status:** ACCEPTED
- **Date:** 2026-08-28
- **Decision owner:** Operator
- **Decision:** The former server was destroyed. Restart the approved read-only
  Kalshi measurement on the operator's laptop, which is reachable from this PC.
  The live Polymarket project remains on this PC.
- **Consequence:** Install and run Kalshi only inside the laptop's separate WSL
  path `/home/polybot/kalshi-bot`, with its own environment, process, data, and
  logs. Do not use or modify the laptop's stale Polymarket copy, and do not
  touch the live Polymarket folder or process on this PC. D-004's no-order and
  no-write boundary remains unchanged.
- **Revisit when:** The operator changes the measurement host or ends the
  capture.

### D-010 — `run parity` operator command

- **Status:** ACCEPTED
- **Date:** 2026-08-28
- **Decision owner:** Operator
- **Decision:** When the operator says `run parity`, reconcile the Kalshi
  project across this PC, the laptop, and GitHub so tracked code and AI
  documentation resolve to one identical commit.
- **Consequence:** First inspect and preserve uncommitted work on both machines;
  never overwrite a divergence silently. Push/fetch only after the tracked state
  is verified, then print the PC, laptop, and GitHub commit IDs. Also verify the
  laptop measurement service and live database health, create an
  integrity-checked SQLite online-backup snapshot, and copy the closed snapshot
  plus matching log to this PC. Runtime databases/logs remain gitignored and
  must never be pushed to GitHub.
- **Revisit when:** The operator changes the parity destinations or data-retention
  policy.

### D-011 — Plan a live liquidity-reward test; do not build yet

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** Continue the Reference Price liquidity-reward strategy in
  `Bots/kalshi-bot`. Do not run paper testing. Plan the live approach first;
  do not build the bot yet. Capital ceiling is $500 and each order must be
  fewer than 10 contracts. The assistant's $10 loss-stop suggestion has NOT
  been approved. Entry size, market list, exit policy, duration, and maximum
  loss remain planning decisions before a live run.
- **Consequence:** Documentation/research may continue. No trading code,
  deployment, live orders, or transfers are authorized by this planning task.
  This instruction supersedes recommendations to require a forward paper stage.

### D-012 — Official API reference and credential-use permission

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** Collect all public Kalshi API endpoint information into a
  Markdown source reference. The operator also authorizes use of their keys
  when needed. Documentation retrieval is public and does not require keys.
- **Consequence:** Preserve dated sources, exact contracts, and visible gaps;
  keep credentials out of all documentation. Credential access is not a new
  trading, capital-transfer, or bot-building decision. D-011 remains in force.

### D-013 — Research liquidity rewards and every documented reward API

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** Research what is needed to understand and benefit from Kalshi
  liquidity rewards, including every reward API.
- **Consequence:** Read-only official-source/API research and documentation
  are in scope. D-011 remains unchanged: no bot build, paper run or live order
  authorization. Research recommendations are not accepted risk settings.

### D-014 — Polymarket-style documentation and permanent architecture rules

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** Inspect the Polymarket bot's Markdown setup and use that
  organizational pattern for Kalshi. Architecture must primarily use
  WebSocket; when required information is unavailable through WebSocket,
  REST is the fallback. Build for CPU efficiency and scalability. Preserve
  these as standing rules for future sessions.
- **Consequence:** `AI_OPERATOR.md` is the shared entry point; AGENTS/CLAUDE
  route to it. `AI_ENGINEERING.md` records permanent requirements and
  `docs/ARCHITECTURE.md` records the source map and proposed design boundaries.
  Polymarket risk settings, deployment permissions and account-source policy
  are not imported. No CPU benchmark, target capacity or runtime behavior is
  claimed implemented. D-011's planning-only boundary remains unchanged.

### D-015 — AI-operated project; all decisions belong to the operator

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** This project will be AI-operated, but the human operator makes
  all project decisions. AI researches, explains options and recommendations,
  and performs the technical work within the operator's approved scope.
- **Consequence:** Undecided strategy, architecture, implementation scope,
  testing, risk, capital and operational choices return to the operator.
  Recommendations and watchlist ideas are not approvals. Routine technical
  steps within an approved task do not require repeated approval, but cannot
  introduce new policy or expand scope. Record accepted choices here.
  D-011 remains in force: planning only; no bot build or live execution.

### D-016 — Multi-WebSocket plan and initial trading parameters

- **Status:** ACCEPTED requirements; detailed architecture remains PROPOSED
- **Date:** 2026-09-19
- **Decision owner:** Operator, current conversation and clarification
- **Decision:** Use multiple WebSocket connections. Start with 10-contract
  entry orders and at most 30 resting entry orders, excluding orders managing
  open positions. This is not a 30-market or filled-position cap. Use the
  Polymarket-style $25 settled trading-loss stop in each fixed six-hour
  America/New_York window: 00-06, 06-12, 12-18 and 18-00.
- **Consequence:** The 10-contract size supersedes D-011's fewer-than-10
  boundary. Its $500 cap, no-paper-testing and planning-only restrictions
  remain. Open inventory limits, exits and precise stop/resumption mechanics
  remain decisions. No gradual entry-cap ratchet or separate daily loss cap
  is inferred. Loss stops can overshoot and do not cap total realized loss.
- **Design direction:** Recommend the best Kalshi-specific architecture using
  Polymarket's implementation and recorded failures as reference, not a full
  copy. Four connections and component choices in
  [the proposal](docs/MULTI_WEBSOCKET_DESIGN.md) need operator approval.
  No implementation, deployment or live execution is authorized.

### D-017 — Loss stop counts opened-and-closed trades only

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, current conversation
- **Decision:** For the D-016 stop, count only settled trading results from
  positions the bot opened and then closed. "Settled" here means realized
  closed-trade P&L, not waiting for the market event to resolve.
- **Consequence:** Include actual trading fees attributable to those closed
  trades. Exclude open/unmatched inventory, unrealized marks, pending or paid
  rewards, transfers and changes in cash caused by collateral/settlement timing.
  Do not recognize open inventory's estimated loss as settled loss.
  Detailed partial-close, fee-allocation and late-fill/window attribution rules
  remain part of the design for approval; no new risk policy is implied.
  Separate open-inventory protection still needs an operator decision.

### D-018 — Follow Polymarket's open-inventory rules

- **Status:** ACCEPTED policy direction and reference inventory limits;
  Kalshi-specific execution mapping must be reviewed before implementation
- **Date:** 2026-09-19
- **Decision owner:** Operator: "Open inventory just follow poly rule"
- **Reference:** Polymarket checkout `54ac71a241d1ad6f02e3445655bb7115247bac02`,
  `DECISIONS.md`, `docs/SAFETY_INVARIANTS.md`,
  `src/liquidity_bot/commissioning.py` and `reconciler.py`.
- **Decision:** Adopt that setup's open-inventory protection: cancel
  risk-building orders in a market after its first fill; manage only the exact
  remaining reducing quantity; do not add inventory while positioned; preserve
  ownership and exposure reservations until positive terminal/flat proof.
  Reducing orders do not consume the 30 resting-entry allowance.
- **Exposure limits:** Carry over the documented size-10 setup's $90
  per-market and $420 portfolio unmatched-loss exposure ceilings. Include
  filled inventory, working risk-building orders and deduplicated ambiguous
  sends; these are not additional allowances on top of inventory. The $500
  capital ceiling and actual buying-power checks also apply. They are exposure
  ceilings, not target allocation, realized-loss stops or permission to scale.
  Polymarket derives these as `9 * size` and `(slots + 10) * size` at
  size 10 / 32 slots. Carrying over its current dollar limits does not select
  32 Kalshi markets or reinterpret 30 resting orders as 30 slots.
- **Exit reference:** Work an exact passive reducer at the active touch,
  without a break-even floor or stepping ahead of one's own valid order.
  After 900 seconds evaluate a cancel-confirm, price-capped IOC. This is not
  guaranteed flatness after 15 minutes: ordinary crossing can defer for
  inadequate depth or projected loss worse than $8 at size 10, retaining the
  passive reducer. Absolute event/maintenance/HARD deadlines override ordinary
  deferral. Polymarket's pre-event boundary is five minutes before kickoff.
- **Kalshi adaptation:** Map the relevant event-risk/close deadline and exact
  quantity/fee/depth contracts before implementation; no automatic sports-only
  clock or Polymarket fractional-residue rule is imported. Unsupported cases
  require an operator decision, not invented behavior. No venue execution
  or profitability validation is claimed.
- **Unchanged:** D-016/D-017's size, 30-entry ceiling and closed-trade-only
  six-hour $25 stop; no paper stage; planning only. This does not authorize
  a build, start, orders, a loss-based entry ratchet or new strategy rules.

### D-019 — Native Windows, not Ubuntu/WSL

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, current conversation
- **Decision:** Use native Windows for this project, not Ubuntu/WSL.
- **Consequence:** Active project is
  `C:/Users/rynna/OneDrive/Documents/Bots/kalshi-bot`. Future environment,
  launch/control, locking, shutdown and recovery design must support Windows.
  Do not mirror further edits into WSL or treat that copy as active authority.
  D-009's WSL requirement and contrary historical runtime guidance are superseded.
  Preserve old WSL files/data; no deletion, migration, service installation,
  scheduled task, runtime change or bot start is authorized by this decision.

### D-020 — Verify inherited behavior in Polymarket code

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, current conversation
- **Decision:** Do not rely on documents to establish Polymarket behavior.
  Verify the actual code before carrying its rules into Kalshi.
- **Consequence:** Trace configuration into enforcement and inspect edge cases;
  use safe relevant tests, distinguish defaults/selected values from live state,
  and correct summaries that overstate the evidence.
- **Correction to D-018:** The verified code uses `9 * size` per market and
  `(configured market slots + 10) * size` portfolio exposure. $90 is verified
  at size 10; $420 requires 32 configured slots and is not a fixed code limit.
  Kalshi slot count remains pending; do not treat the previous $420 wording as
  separate approval to select 32 markets. Preserve the requested Poly formula.
  All working/unknown-absent orders, including reducers, contribute to the
  reference's conservative dollar exposure; their 30-entry-count exclusion is
  a separate rule. See [code audit](docs/POLYMARKET_INVENTORY_CODE_AUDIT.md).
  104 configuration/reconciler tests passed on Windows. No live state is claimed.

### D-021 — Begin Windows-native implementation; accept percentage entry caps

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator: "Ok lets start building it", responding to the
  source-verified percentage-cap table.
- **Decision:** Start implementing the Windows-native liquidity-reward bot.
  Adopt 30/25/20/15/10/0 resting-entry caps at $0/$5/$10/$15/$20/$25
  closed-trade net loss, ratcheting downward during each fixed six-hour window.
  Keep 10-contract entries and exclude position-management orders from entry count.
- **Consequence:** Supersedes D-011's no-build restriction, not its no-paper
  requirement. Offline software/fault/load tests are allowed. Build the proposed
  multi-WebSocket/single-owner design with live execution disabled; no deployment,
  live start, order, cancellation or transfer is authorized. Unresolved managed
  market count and venue-specific risk/exit decisions must remain explicit
  live-readiness blockers rather than assumed defaults.

## Remaining implementation/live decisions

### D-022 — Include market rankings

- **Status:** ACCEPTED scope
- **Date:** 2026-09-20
- **Decision owner:** Operator: "Make sure we do the rankings of the market too"
- **Decision:** Include market rankings in the liquidity-reward bot build.
- **Boundary:** This does not select a live market set, profitability threshold,
  automatic allocation/repricing policy or larger capital/market capacity.
  Informational views distinguish gross reward arithmetic from unknown net
  profit/paid rewards and expose stale/unsafe/missing-input exclusions.

### D-023 — Market capacity follows the approved limits

- **Status:** ACCEPTED direction, 2026-09-20
- **Decision owner:** Operator: "Market capacity is based on our limits"
- **Decision:** Derive active entry breadth from capital, exposure, entry-count
  and eligibility constraints rather than asking for an arbitrary market target.
- **Boundary:** 30 entries can fund at most 15 two-sided or 30 one-sided entry
  markets before other gates. Inventory remains managed outside that count.
  No 30/32-slot setting or $400/$420 portfolio cap was selected. Resolve the old
  slot-dependent exposure formula explicitly; do not raise its cap automatically
  with occupancy or treat $500 capital as a newly selected portfolio-risk cap.
- **Related request:** Check actual Poly code for partial closes, selection,
  exits and restart. The audit below supplies evidence, not blanket adoption.

### D-024 — Adopt source-verified partial-close accounting

- **Status:** ACCEPTED, 2026-09-20
- **Decision owner:** Operator: "Ok do it then", accepting the recommendation
  based on `docs/POLYMARKET_POLICY_CODE_AUDIT.md`.
- **Decision:** Realize each matched partial close immediately using weighted-
  average entry basis. Charge actual fill fees immediately, including opening
  and unmatched portions. Count each fill once in the six-hour window when it
  is first durably recorded; retain venue execution time separately for reports.
  Late fills do not rewrite old risk windows. Preserve ratcheted caps and stops
  across restarts; exclude unrealized marks and rewards from this meter.
- **Boundary:** Supersedes D-017 only for fee timing and resolves partial-close
  and late-fill-window attribution. Existing capital, size and stop thresholds
  are unchanged. No live activation, automatic old-ledger migration, correction/
  reversal/settlement policy or complete historical-recovery approval is implied.
  Refuse incompatible accounting ledgers rather than silently reinterpret them.

### D-025 — Polymarket-style automatic recovery, adapted to Kalshi

- **Status:** ACCEPTED, 2026-09-20
- **Decision owner:** Operator: "Just do something like polymarket", after the
  executable-code explanation of automatic backfill and venue-cost fallback.
- **Decision:** Implement automatic recovery of verifiable bot executions,
  idempotent replay, immutable-identity conflict blocking, and a separately
  attributed venue-cost fallback for managing known inventory when local fill
  basis is incomplete. Ordinary verifiable repairs need no per-fill approval.
- **Adaptation:** WebSocket remains primary; bounded REST supplies missing order,
  history and reconciliation evidence. Preserve D-024 receipt-window accounting,
  per-fill risk ratchets and original duplicate receipts. Venue position cost
  never invents executions, fees, settled P&L or complete history proof.
  Exact account/market/order ownership and fresh position evidence are required
  before exposing fallback exit basis. Preserve its first-seen clock on restart.
- **Boundary:** Copy venue-confirmed correction handling only when Kalshi has a
  verified equivalent contract; absent that, conflicting fills/settlements stay
  blocked, not silently rewritten. No reset of holds, new exposure allowance,
  old-ledger migration or live activation is authorized. Recovery reports alone
  cannot establish complete stream continuity or allow new orders.

### D-026 — Connect recovery to the event engine

- **Status:** ACCEPTED, 2026-09-20
- **Decision owner:** Operator: "Ok do recommendation", accepting recovery
  integration for startup/restarts, disconnects, missed fills and fill-before-order.
- **Decision:** Wire the approved recovery components into the main event engine;
  automatically recover verifiable evidence with bounded resources/retries and
  keep new entries blocked until adequate account proof exists.
- **Boundary:** Native Windows, WebSocket first, existing capital/accounting
  rules unchanged. No live launch, credentials, orders, cancellations, new
  correction/settlement policy or fabricated continuity proof. Tests use injected
  transports and disposable local ledgers, not a paper trading stage.

### D-027 — Connect inventory management and account-wide risk checks

- **Status:** ACCEPTED build scope, 2026-09-20
- **Decision owner:** Operator: "Ok do next", accepting the next inventory-exit
  and account-wide-risk integration milestone.
- **Decision:** Wire approved exact-quantity passive inventory management and
  shared risk/reservation checks into the recovery-connected engine. Verify
  Polymarket's actual enforcement; preserve existing limits and percentage caps.
- **Boundary:** No portfolio-cap selection, forced-exit/deadline mapping, live
  activation or new authority to send/cancel orders. Keep unresolved decisions
  explicit blockers; exercise positive reservation paths only in offline fixtures.

### D-028 — Continue account-state verification

- **Status:** ACCEPTED build scope, 2026-09-20
- **Decision owner:** Operator: "Ok do next", following D-027's handoff.
- **Scope:** Continue account-state verification: coherent local snapshot/order/
  pending-fill checks and recovery provenance, with offline fault/load tests.
- **Boundary:** No claim of complete history from matching net positions or
  exhausted cursors; no invented private-stream barrier, starting basis, cash
  semantics, correction policy, portfolio cap or exit policy. No live activation.

### D-029 — Move Windows project beside Polymarket

- **Status:** ACCEPTED, 2026-09-20
- **Decision owner:** Operator requests transfer under rynna/Bots, then confirms
  the same Bots parent as Polymarket.
- **Decision:** Relocate the Windows project from OneDrive to
  `C:/Users/rynna/Bots/kalshi`, alongside (not inside) `liquidity-bot`.
  Move the supplied Kalshi credential file from the separate OneDrive Kalshi
  folder without displaying or changing its contents. Preserve project data.
- **Boundary:** Update active routing/environment paths and verify locally.
  No Polymarket changes, WSL migration, live trading, bot start or venue writes.
  D-019's Windows requirement remains; its old active path is superseded.
  The previously requested read-only account inspection remains pending.

### D-030 — Separate pre-bot history; verify private streams read-only

- **Status:** ACCEPTED scope and baseline direction, 2026-09-20
- **Decision owner:** Operator: "Ok do it", accepting the next-steps recommendation.
- **Decision:** Keep the 18 previously returned fills separate from this bot's
  trading record, retaining prior history as reconciliation evidence. Verify
  private WebSocket access and reconnect behavior without placing orders;
  continue the execution-disabled build and bring unresolved risk/exit choices
  back before implementing them.
- **Boundary:** This is not approval to discard history, assign every old fill
  to a foreign owner, reset existing risk windows, or choose a launch timestamp.
  A fresh scoped account check and durable ownership/history evidence are still
  required before arming. Any prior fill that proves bot-owned follows D-024/025;
  unknown ownership remains unresolved, never silently ignored. No historical
  ledger migration or automatic import of the 18 fills is authorized.
- **Unchanged:** $500 capital, size 10, 30 resting entry orders, $90 per-market
  exposure and the approved six-hour accounting/caps. No new aggregate exposure
  dollar cap or Kalshi event/IOC deadline was specified. No trading start,
  placement, cancellation, account mutation or paper-trading stage is authorized.

### D-031 — Follow Polymarket's exposure formula and verified local default

- **Status:** ACCEPTED direction, implemented using verified reference default,
  2026-09-20.
- **Decision owner:** Operator: "Just follow poly", responding to the proposed
  fixed $400 portfolio ceiling. That proposal is superseded, not accepted.
- **Source:** Local Poly HEAD `51cf59548b8e339be790e0662b6594ff0af77ddc`;
  `commissioning.py` computes quote size times (configured slots + 10).
  `slot_capacity.py` and both launchers default to 20; no local
  `data/commissioning_slot_capacity` override exists. This is checkout/default
  evidence, not a claim about a running process or another host.
- **Implementation:** Use that 20-slot reference for the exposure formula at
  Kalshi's approved size 10: $300 aggregate conservative exposure. Keep the
  $90 per-market limit, $500 capital ceiling, and 30 resting-entry cap unchanged.
  Inventory, working orders including reducers, and deduplicated uncertain sends
  share that exposure allowance; it never grows with current occupancy.
- **Capacity boundary:** This resolves the exposure calibration, not a new
  target or ceiling of 20 traded Kalshi markets. D-023's entry breadth remains
  limits-driven; the technical 128-market tracking bound is not a dollar budget.
  No automatic synchronization to future Poly configuration changes. Reconfiguring
  the reference capacity requires operator review, not hot changes under orders.
- **Unchanged:** Existing accounting/holds, history, exits and live-readiness
  requirements. No credentials, venue reads/writes, Poly modifications, live start
  or approval of unrelated Poly policies is implied.

### D-032 — Build source-verified inventory exits, execution disabled

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", accepting the inventory-exit milestone.
- **Scope:** Exact passive reducers, conditional one-tick improvement, keeping
  an exact reducer at touch, 900-second ordinary exit evaluation, cancel-confirm
  before price-capped IOC, partial fills and reconnect/restart safeguards.
- **Reference adaptation:** Preserve the size-10 $8 ordinary projected-exit-loss
  allowance and 50% stressed displayed depth. Absolute verified event/maintenance/
  HARD deadlines override ordinary loss deferral, not ownership, book freshness,
  cancellation proof or actual tradability. Use actual Kalshi tick bands and
  reduce-only IOC semantics, not Poly payloads or fractional-residue exceptions.
- **Timing boundary:** Implement explicit verified event-risk time minus five
  minutes, bounded by the market's trading close. Do not substitute latest or
  expected expiration for event risk. Unknown event timing/early-close exposure
  stays an explicit producer/readiness gap; no invented universal event clock.
  Closed/inactive markets require attention, not an impossible flatten claim.
- **Authority:** Advisory plans and offline injected-command tests only. Live
  fee/deadline producers, complete account proof and production execution still
  require verification; no orders, cancels, account writes or live start authorized.

### D-033 — Structured diagnostics and error handling

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator requests proper logging for debugging and error handling.
- **Scope:** Bounded structured local logs, secret-safe failure context, correlation,
  rotation, observable retry/fatal states and offline fault/performance tests.
- **Boundary:** Preserve risk/proof gates and existing retry limits. No swallowing
  unexpected errors, blind mutation retries, account calls or live activation.
  Logs are diagnostics, never the durable financial ledger or recovery authority.

### D-034 — Connect verified market inputs to advisory exits

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", accepting the next market-input milestone.
- **Scope:** Typed market/tick/fee/milestone readers, stream-first invalidation,
  bounded missing-field REST fallback and source/freshness-bound ExitTerms.
- **Boundary:** No universal event-start inference from expiry/strike dates,
  no assumed membership fee precision, and no automatic approval of market-rule
  interpretations. Unreviewed timing/early-close exposure and unsupported fee
  models remain blocked. No market selection, keys, orders or live activation.

### D-035 — Continue reconciliation and durable history-read evidence

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do next", following D-034's reconciliation handoff.
- **Scope:** Continue account reconciliation, including durable completed history-read
  receipts, explicit interval gaps, restart inspection and bounded offline tests.
- **Boundary:** Receipts describe completed enumerations, not complete venue history
  or a snapshot/stream barrier. Do not choose/install a launch boundary, classify
  unknown old fills as foreign, reset risk, invent correction/settlement semantics,
  change limits or activate trading. Production input scheduling remains queued.

### D-036 — Bounded automatic metadata refresh scheduling

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do next", accepting the D-035 scheduler handoff.
- **Scope:** Lifecycle-driven bootstrap/change/expiry refreshes around D-034,
  bounded shared work, retry limits, shutdown and offline resource/fault checks.
- **Added operator request:** "We have to also work on kalshi rate limits."
  Verify current venue token contracts and improve shared read-budget configuration,
  recovery priority, throttling and diagnostics. Document write/shard requirements;
  this does not enable mutations or tier upgrades.
- **Boundary:** No live launch, account use, market selection, automatic timing
  review or fee-profile approval. Keep existing freshness, risk and authority gates.

### D-037 — Mandatory Astra / 5.6 Sol development handoffs

- **Status:** SUPERSEDED by D-049 on 2026-09-21; retained as workflow history.
- **Decision owner:** Operator, explicitly requiring this flow from now on.
- **Decision:** Astra analyzes the repo/requirements and designs architecture,
  modules, data flow, interfaces, failure handling and implementation phases,
  without implementing. ALWAYS stop after planning so the operator can switch
  to 5.6 Sol. Sol implements Phase 1 against the agreed structure/interfaces,
  adds tests and verifies. Astra handles difficult problems and reviews the
  implementation/current Git diff for architectural violations, races, edge
  cases, security issues and incorrect assumptions. Sol implements the findings
  while preserving the architecture.
- **Consequence:** No automatic design-to-build transition or model switching.
  Canonical phase/handoff procedure: `AI_OPERATOR.md`. General build permission
  and "do next" do not bypass the planning stop. Existing D-036 code is preserved;
  new implementation is paused at this instruction, with review/verification
  handoff recorded in STATUS/NEXT. No deployment/live authority changes.

### D-038 — Design supervised quota freshness and grant expiry

- **Status:** ACCEPTED design scope only, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", responding to the proposed next Astra
  design and required stop before Sol implementation.
- **Scope:** Inspect current code and official contracts; design quota lease
  validation, expiry enforcement, restricted bootstrap/recovery, scheduling,
  ownership, failure handling, phased interfaces and offline acceptance checks.
- **Handoff:** `docs/DESIGN_QUOTA_FRESHNESS.md` is the proposed contract. Stop for
  the operator's switch to 5.6 Sol and approval of Phase 1. Numeric freshness,
  probe and retry settings in that document are recommendations, not separately
  approved production configuration. Phase 2 requires its later handoff.
- **Boundary:** Documentation only this turn; no source/test implementation,
  account use, live activation, tier upgrades, write transport or risk changes.

### D-039 — Implement both quota-freshness phases

- **Status:** ACCEPTED implementation scope, 2026-09-20.
- **Decision owner:** Operator: "Implement both", following the D-038 design.
- **Scope:** Implement both phases in `docs/DESIGN_QUOTA_FRESHNESS.md`, including
  guarded quota leases, automatic scheduling/runtime integration, diagnostics and
  offline correctness/resource checks. This explicitly replaces that plan's
  separate Phase 2 approval gate for this implementation only.
- **Boundary:** Preserve D-037's handoff for Astra review after implementation.
  No automatic model switch, live activation, credentials/account calls, write
  transport, tier upgrade or trading-risk changes. Production probe configuration
  and all other launch proofs remain separately required.

### D-040 — Clarify the quota-review design before Sol fixes

- **Status:** ACCEPTED design scope only, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", responding to the review handoff:
  clarify grant-expiry design, then stop for the switch to Sol fixes.
- **Scope:** Resolve R1's conflicting refresh/acceptance timing and specify
  bounded scheduling, interfaces and regressions; consolidate R2/R3 and the
  timing-test investigation into a clear proposed fixes assignment.
- **Handoff:** `docs/DESIGN_QUOTA_REVIEW_FIXES.md` is the proposed correction.
  Always STOP for the operator's switch and implementation instruction. The
  precise new deferral policy is a design recommendation, not already implemented
  or separately approved production configuration.
- **Boundary:** Documentation and read-only inspection only; no source/test
  fixes, live activation, credentials/account calls, risk changes or new milestone.

### D-041 — Implement the quota review fixes

- **Status:** ACCEPTED implementation scope, 2026-09-20.
- **Decision owner:** Operator: "Implement fixes", after switching to 5.6 Sol.
- **Scope:** Implement D-040's correction for reviewed R1-R3, investigate and
  repair the timing-sensitive test, add regressions and run focused, complete
  and affected resource checks. `docs/BUILD_QUOTA_REVIEW_FIXES.md` records the
  result; independent Astra re-review follows under D-037.
- **Boundary:** No live start, credentials/account calls, write transport,
  new risk settings, Polymarket changes or production probe selection.

### D-042 — Implement the two D-041 re-review follow-ups

- **Status:** ACCEPTED implementation scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", after the D-041 Astra review.
- **Scope:** Fix truthful supervisor status after repeated cancellation and
  replace retained rollover exceptions with a small immutable boundary record;
  add regressions and verify. `docs/BUILD_QUOTA_REVIEW_FOLLOWUPS.md` records the
  implementation. Independent Astra re-review follows under D-037.
- **Boundary:** Preserve the D-040 design, physical wire ownership and late-429
  accounting. No live start, credentials/account calls, write transport, risk
  changes, Polymarket changes or production probe selection.

### D-043 — Replace the canonical GitHub repository with this Windows project

- **Status:** ACCEPTED repository publication scope, 2026-09-20.
- **Decision owner:** Operator: "all work here gonna use this previous github,
  delete everything on this repo and replace with what we have on kalshi bot now",
  naming `https://github.com/rynn-arriola/kalshi-bot`.
- **Scope:** Publish the present `C:/Users/rynna/Bots/kalshi` source, tests and
  documentation to the existing GitHub repository, replacing its old tracked
  tree. Connect the active Windows folder to that repository. Keep prior Git
  history recoverable; retire the obsolete remote `main` branch after preserving
  its history in the default `master` branch.
- **Boundary:** Exclude credentials, local data, logs, environments and
  machine-local transfer/deployment state. No live bot start or account action.

### D-044 — Design starting-account and private-stream continuity

- **Status:** ACCEPTED design scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it" in response to the recommended next
  Astra design milestone.
- **Scope:** Analyze the current Windows Kalshi implementation and official API
  contract, use Polymarket source as a read-only conceptual reference, and
  specify a phased starting-inventory/private-stream continuity design in
  `docs/DESIGN_ACCOUNT_CONTINUITY.md`.
- **Boundary:** Stop after design for the operator's 5.6 Sol switch under D-037.
  This does not authorize implementation, a launch boundary, live account calls,
  credential use, order actions or trading. An undocumented venue handoff is
  not proof of complete fill coverage or starting inventory.

### D-045 — Implement evidence-only continuity Phase 1

- **Status:** ACCEPTED implementation scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do phase 1" and confirmed "I did" when
  asked whether this task had switched to 5.6 Sol.
- **Scope:** Implement and offline-verify Phase 1 of
  `docs/DESIGN_ACCOUNT_CONTINUITY.md` in the native Windows Kalshi project.
  Record local private epochs and baseline candidates, tighten positions
  pagination, and handle unscoped position updates without claiming account
  authority. Hand off to Astra for independent review under D-037.
- **Boundary:** No venue handoff proof, approved opening inventory, Phase 2/3,
  real account calls, credential use, live order action or activation. All
  entry and live-readiness gates remain false.

### D-046 — Implement D-045 independent-review fixes

- **Status:** ACCEPTED fix scope, 2026-09-20.
- **Decision owner:** Operator: "Ok fix it" after receiving the independent
  Astra review and switching back to the implementation model.
- **Scope:** Implement R1-R5 from `docs/REVIEW_D045_ASTRA.md`: private-event
  shutdown ownership, accepted epoch-open cancellation/gap reconciliation,
  coherent quota-boundary status, quota-test callback synchronization and a
  correctly instrumented reconnect resource fixture. Add regressions and rerun
  focused/full/resource/preflight verification.
- **Boundary:** Preserve D-044's evidence-only architecture. No Phase 2/3,
  approved baseline, risk/policy change, real account/credential call, order
  action, deployment or live activation. Return to Astra re-review under D-037.

### D-047 — Fix D-046 re-review shutdown findings

- **Status:** ACCEPTED fix scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it" after receiving the D-046 Astra
  re-review and switching back to the implementation model.
- **Scope:** Implement both P2 findings from `docs/REVIEW_D046_ASTRA.md`: retain
  reader/marker cleanup through repeated caller cancellation, continue bounded
  queue draining after malformed/staging failures, preserve valid tail fills,
  and surface cleanup failures. Add regressions and rerun focused/full/resource
  and disabled-preflight verification.
- **Boundary:** Preserve the evidence-only architecture and previously cleared
  fixes. No Phase 2/3, baseline, policy/risk change, account/credential call,
  order action, deployment or live activation. Return to Astra re-review.

### D-048 — Fix D-047 connection-finalization finding

- **Status:** ACCEPTED fix scope, 2026-09-21.
- **Decision owner:** Operator: "Fix it", after switching to the implementation
  model following the D-047 Astra review.
- **Scope:** Retain connection finalization when ordinary stop or cancellation
  overlaps a disconnect drain; preserve valid transport-tail fills, finish marker
  close/gap refresh and add the review's real-queue/repeated-cancel regressions.
  `docs/BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md` records implementation and
  verification. Return to Astra review under D-037.
- **Boundary:** Preserve the evidence-only architecture and all prior limits.
  No Phase 2/3, baseline, policy/risk change, account/credential call, order
  action, deployment or live activation.

### D-049 — Mandatory usage-efficient model selection

- **Status:** ACCEPTED permanent rule, 2026-09-21.
- **Decision owner:** Operator, explicitly requiring model selection before every
  substantive task and limiting the repository to GPT-6 Astra and GPT-5.6 Sol.
- **Decision:** GPT-5.6 Sol is the default for approved implementation, focused
  fixes, verification, routine checks/reports/docs, standard operations and Astra
  review fixes. GPT-6 Astra is reserved for material architecture/design,
  strategy/risk/business logic, uncertain difficult incidents, cross-system
  concurrency/recovery/security/account state, architecture/risk-sensitive API
  research and final review of meaningful or high-risk live-money code.
- **Workflow:** Before substantive work, print `Recommended agent: Astra — ...`
  or `Recommended agent: 5.6 Sol — ...`. A model mismatch stops development for
  the operator's switch. Full development remains Astra design -> Sol implement/
  verify -> Astra review -> Sol fixes/verify, with a stop at each handoff. Small,
  low-risk Sol changes need no Astra review; urgent exposure-prevention actions
  never wait for switching. Do not switch repeatedly within a phase; escalate
  Sol only on evidence of material architectural uncertainty or risk.
- **Boundary:** This supersedes D-037 where routing differs. It does not alter
  authority, safety, testing, deployment, restart, capital, risk or live-action
  rules. `AI_OPERATOR.md` is the canonical detailed procedure.

### Earlier recovery-import question — superseded by D-025

The stricter proposal below was not selected verbatim. D-025 selects a
Polymarket-like automatic recovery flow, including a separate venue-cost fallback.

- **Question:** May missing fills be automatically imported only after proving
  bot ownership and complete starting cost basis, with corrections, unexplained
  inventory and settlement discrepancies blocking new entries for operator review?
- **Recommendation:** Yes, under those evidence gates; never manufacture basis
  from a current balance/position snapshot or treat archive absence as cancellation.
- **Alternative:** Keep every missing-fill import manual/operator-reviewed.
- **Why needed:** D-024 specifies accounting but does not approve the complete
  replay/recovery policy. The async question is unanswered as of this handoff;
  no automatic import or correction/settlement implementation was enabled.
- **Impact:** No new capital allowance. Imported real fills could change current
  receipt-window P&L and tighten caps/stops; they must never loosen a ratchet.
  Unknown/conflicting evidence halts new-entry readiness and retains reservations.
  Existing ledgers/history remain untouched; migration is separately scoped.
- **Work done meanwhile:** Archived order evidence retrieval/binding under D-021
  and existing ownership/terminal-proof rules; not new accounting authority.

### Earlier fixed-slot question — superseded by D-023's capacity direction

The earlier fixed-slot proposal was: 30 slots imply $400 exposure
under the accepted formula, versus $420 for 32. Neither changes the $500 capital
ceiling or 30 resting-entry-order limit. Two-sided quoting consumes two orders
per market. Configuration remains null until dynamic-capacity/exposure integration,
not because the operator must choose one of these fixed-slot suggestions.

### Earlier accounting question — superseded by D-024 above

The following records the earlier, unapproved alternatives for audit only.
The original-execution-window and prorated-fee proposal was NOT selected.

Source correction after the operator requested Poly verification:
`docs/POLYMARKET_POLICY_CODE_AUDIT.md` confirms immediate matched partial-close
P&L, weighted-average basis, immediate actual fees (including unmatched inventory)
and receipt-time loss windows. The earlier execution-time late-fill proposal below
is not a verified Poly copy. Fee timing differs from the Kalshi candidate and
needs explicit approval against D-017; no accounting code changed in this audit.

Requested choice: whether each partial close counts immediately, with proportional
entry/exit fees, and late recovered fills are attributed to their original
execution-time window while preserving already-triggered stops. Alternative:
count only a fully closed position, or leave the contract undecided.

This determines historical replay and loss-window recomputation; current
FIFO/receipt-time fixtures are still candidate accounting, not approval of this
new recommendation. Recovery now stages evidence separately. No answer is
recorded yet. Implementing approved replay must preserve per-fill ratchets,
restart durability and explain tied timestamps/corrections. The $500 capital,
size 10, 30-entry ceiling and $25 window trigger are unchanged. Until resolved,
automatic replay/resumption stays disabled and existing trading data is not
rewritten. This request adds no deployment or live-action authority.

The percentage-budget entry-cap rule is now accepted by D-021. Inventory exits
remain exact-quantity reductions, not percentage liquidation.

Under D-016, size, resting-entry count and the six-hour $25 stop are accepted.
D-018 adopts Polymarket's open-inventory policy; D-020 corrects the evidence:
the old slot-dependent exposure formula needs mapping to D-023's dynamic capacity.
Kalshi-specific deadline/exit mapping, any additional correlated-event limits,
resumption details and final live architecture/performance acceptance remain
unresolved. Implementation is authorized by D-021; live activation is not.
No paper stage is required by the operator.

When a decision becomes necessary, add a short request here containing:

- the exact choice;
- why progress depends on it;
- evidence and uncertainty;
- recommended option and alternatives;
- maximum capital/state impact;
- rollback or stop condition.
