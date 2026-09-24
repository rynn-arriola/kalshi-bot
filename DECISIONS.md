# Operator decision ledger

This is the authority record. AI agents may recommend decisions but may not mark
them accepted without an explicit operator instruction.

## Current ranking/admission decision

D-069 accepts the reference audit's selection direction for offline construction.
It does not authorize live selection, price chasing, new risk limits or trading.
D-070 extends it with Poly-style bounded discovery and estimated reward tracking,
and explicitly withdraws the proposed fixed 60-market pool.

### D-113 — Separate routine freshness from full startup/refill recovery

- **Status:** ACCEPTED, implemented and verified, 2026-09-24; not deployed.
- **Decision owner:** Operator: “Ok lets do it,” accepting Finding 175's repair.
- **Scope:** Renew account/accounting evidence using a bounded empty-history
  tail after a successful full proof, independently of order occupancy or ranking
  completion. Let advisory market ranking progress during account recovery.
- **Boundary:** No larger freshness windows, invented continuity, changed risk
  or ranking policy. Source/economic changes, nonempty tails and uncertainty
  require ordinary recovery. Advisory observations never authorize dispatch.
  This implementation request does not authorize a live restart.

### D-112 — An explicit restart command covers exact-child timeout recovery

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** The operator directed that future explicit instructions to
  restart this bot require no second termination prompt.
- **Scope:** A `restart` command authorizes the supported stop and start. If the
  supported stop times out, it also authorizes terminating only the exact
  managed child after immediately rechecking PID, generation, production scope,
  and stop-latched/disarmed state.
- **Boundary:** Never kill by process name, terminate unrelated or ambiguously
  identified processes, start a second bot, mutate venue orders ad hoc, edit the
  ledger, or bypass recovery/flat-state checks. If the child exits naturally,
  do not issue the termination.

### D-111 — Repair the false funding hold and restart through exact recovery

- **Status:** ACCEPTED, implemented, published and live on generation 111,
  2026-09-24.
- **Decision owner:** The operator directed the bot to be fixed and restarted,
  then explicitly authorized force termination of only the verified retained
  generation-108 child after the supported stop timed out.
- **Scope:** Accept only null-to-pre-boundary `finalized_ts` enrichment of the
  same approved applied deposit when complete cursor-exhausted funding history
  proves every other field unchanged. Terminate only the exact identified stale
  child, then use normal recovery-only and fresh-child supervisor behavior.
- **Boundary:** No accounting hold is manually deleted. Missing/new/changed cash
  activity, later finalization, incomplete history, risk limits, strategy and
  market-selection policy remain unchanged and fail-closed.
- **Live acceptance:** Recovery-only cleared the false hold and proved flat;
  generation 111 then ranked 1,024/1,024 markets and reached 30 entries across
  15 $2+ priority markets with zero positions and no persistent blocker.

### D-110 — Recover transient outages and rebuild fresh quotes after a crash

- **Status:** ACCEPTED, implemented, published and live on generation 108,
  2026-09-23.
- **Decision owner:** After reviewing Finding 169, the operator directed all
  findings to be fixed and required restart attempts to continue through any
  diagnosed issue until a healthy restart succeeds.
- **Scope:** Persist account/book/lifecycle readers through capped retry rounds;
  retry classified transient account reconciliation after cooldown; report retry
  states truthfully; after unexpected death only, let verified-flat recovery-only
  completion start one fresh normal child that re-ranks and rebuilds through the
  existing dispatcher; roll superseded exact observation archives into a bounded
  cumulative hash commitment before their finite generation fills.
- **Boundary:** ACK alone never resets retries. Invalid data, ambiguity, economic
  or loss holds, uncertain mutations, incomplete cleanup, manual STOP and local
  integrity failures never auto-resume. No stale order is replayed and no risk,
  size, selection, reference-price or reward threshold changes. Exact economic
  rows remain retained; only superseded observation archives become hash-only.
- **Implementation:** [unattended recovery](docs/BUILD_UNATTENDED_RECOVERY.md).
- **Live acceptance:** The supported restart stopped generation 106 flat, then
  generation 108 matched the published production fingerprint, ranked all 1,024
  markets and rebuilt 30 entries across 15 $2+ priority markets with no position,
  retry round, risk/accounting hold or supervisor attention state.

### D-109 — Bound steady full-cap recovery and accounting retention

- **Status:** ACCEPTED, implemented, published and live on generation 106,
  2026-09-23.
- **Decision owner:** Operator directed the measured generation-102 recovery,
  CPU, reward-coverage and accounting-capacity issues to be addressed.
- **Scope:** At an exact full-cap, flat, fully ranked account, refresh the exact
  account snapshot without repeating history/opening-account reconstruction,
  keep full WebSocket ingestion while limiting optional deep evaluation to the
  owned markets, and losslessly archive superseded recovery observations before
  the durable accounting journal reaches its hot limit.
- **Boundary:** Any fill, position, order, cash, account/source revision,
  dispatcher work, vacancy, window change or failed refresh returns to the
  existing full recovery. The optimization grants no trading authority and does
  not change limits, ranking, quote prices, exits, deployment or live orders.
- **Live acceptance:** The authorized restart canceled 30 old entries and proved
  zero orders/positions/exposure before one exact-child forced termination was
  separately authorized for the old build's terminal journal deadlock. Recovery-
  only then archived 8,192 events, cleared the capacity hold through exact
  release and stopped flat. Normal generation 106 ranked 1,024/1,024 markets,
  reached 30 entries/zero positions, and exercised the bounded steady path.

### D-108 — Reconcile the explicit manual close and resume the preserved account

- **Status:** ACCEPTED, implemented, published and deployed, 2026-09-23.
- **Decision owner:** Operator reported the one open position was manually closed,
  directed the required repair, and authorized restart.
- **Scope:** Adopt only the exact audited terminal close fill into the stopped
  ledger, retain its external origin for cold cash validation, reconcile the
  account to flat, then use the normal recovery-only and live startup sequence.
- **Boundary:** This is not general manual-trading support. Ordinary recovery
  still rejects new unbound fills, and no position, limit or strategy changed.

### D-107 — Treat deterministic absent cancel targets as terminal rejection

- **Status:** ACCEPTED, implemented, published and deployed, 2026-09-23.
- **Decision owner:** Operator directed repair of the observed slow/failing
  cancellation path and restart after review.
- **Scope:** A proved deterministic cancel `404` and create `400` now close the
  exact mutation as `REJECTED` instead of crashing recovery and leaving it
  unknown. Ambiguous transport/server failures remain fail-closed.
- **Boundary:** No broader cancel authority, ownership relaxation, force stop,
  market-selection change or risk-limit change is included.

### D-106 — Repair final priority-admission review findings

- **Status:** ACCEPTED, implemented and published; not deployed, 2026-09-23.
- **Decision owner:** Operator: “Fix it,” after the end-to-end review identified
  three concrete D-105 defects.
- **Scope:** Retire remembered priority on fresh definitive ineligibility while
  preserving it for missing/temporarily exhausted proof; continuously refill
  the bounded revalidation window around stalled candidates; and publish
  dispatch-selection evidence only after an ACK or partial venue outcome.
- **Boundary:** No strategy, limits, source concurrency, configuration, runtime,
  deployment, restart, cancel or live-order change is included.

### D-105 — Revalidate remembered $2 candidates before $1 fallback

- **Status:** ACCEPTED, implemented and published; not deployed, 2026-09-23.
- **Decision owner:** Operator: “Ok do it,” after review of the priority-admission
  investigation and recommendation.
- **Scope:** Retain bounded advisory memory of previously current $2 candidates,
  prioritize their metadata refresh in batches up to twice available pair slots,
  and defer $1 fallback until that batch is freshly resolved. Make early $2
  capacity release reachable from the actual runtime loop, continue full
  coverage afterward, and expose bounded selection evidence in status.
- **Boundary:** Advisory memory never authorizes an order. Every pair still needs
  current book, program, metadata, account, risk and dispatch proof. Keep current
  qualifying owners, four book shards, REST concurrency, limits and exit policy
  unchanged. No deployment, restart, cancel or live order action is included.

### D-104 — Prioritize owned metadata and repair clean supervisor shutdown

- **Status:** ACCEPTED, published, deployed and live-observed, 2026-09-23.
- **Decision owner:** Operator directed completion of the four-shard fixes and
  restart after verification, then explicitly accepted repair of the diagnosed
  metadata and shutdown defects.
- **Scope:** Keep current owned/maintenance markets ahead of optional discovery
  in the shared metadata scheduler, use four bounded metadata reads only in
  broad discovery, and permit liveness-only parent pulses during a latched stop
  so verified-flat cleanup can finish. Review, test, publish, then restart with
  the preserved ledger and existing limits.
- **Boundary:** A stop-latched child receives no admission or mutation authority;
  identity/dead-parent checks remain mandatory. Do not change strategy, reward
  thresholds, quantity, capital, loss limits or exit timing.

### D-103 — Repair exits and require priority-safe broad ranking

- **Status:** ACCEPTED implementation; restart not authorized, 2026-09-23.
- **Decision owner:** Operator: “Fix all the work but dont restart yet,” after
  prioritizing the observed exit/recovery incident, repeatable 1,024-market
  source coverage and $2-first admission.
- **Scope:** Use the venue-valid passive-exit payload while retaining exact local
  managed-exit authority; rearm one fresh recovery at a due safety boundary;
  measure two versus four book shards; prepare four shards; and prevent partial
  ranking from admitting $1 fallback before complete coverage or a full current
  $2 slate. Review, test, commit and push.
- **Boundary:** Keep the bot stopped and flat. No account/order mutation,
  deployment, restart, ledger edit, risk/quantity/loss change or incumbent
  reward-chasing replacement. Existing qualifying owners remain retained.

### D-101 — Repair actual-order repricing and final drain reconciliation

- **Status:** ACCEPTED, deployed and live-observed, 2026-09-23.
- **Decision owner:** Operator requested the demonstrated repricing fix and a
  review of retained logs for the next restart, then explicitly clarified:
  "stop the bot and cancel all order."
- **Scope:** Repair reproduced reward-source joins that starve incumbent
  maintenance, verify the two-leg cancellation/replacement path, and repair the
  observed post-drain recovery stall. Review, test, commit and publish.
- **Boundary:** Keep qualifying incumbents, $2-first/$1-fallback entry ranking,
  sizes, risk, exact fill/terminal proof and all freshness limits unchanged.
  The later explicit restart instruction authorized controlled deployment and
  launch. The preserved ledger and unchanged limits were used; no initialization
  or account-wide cancellation was performed during restart.

### D-102 — Safety stop and immediate bounded close after live fill

- **Status:** ACCEPTED operation, completed flat, 2026-09-23.
- **Decision owner:** Operator: “Close position first then lets see where we at
  on the other work.”
- **Scope:** Cancel remaining entries through the supported stop, close only the
  exact 10-contract KXONPOS position through the existing ledger-backed IOC path,
  and verify venue/account flatness before further development.
- **Boundary:** No new entries, ledger reset, account-wide cancel, risk change or
  unrelated process termination. Production remains stopped after verified
  flatness; another restart requires a separate instruction.

### D-100 — Repair live maintenance timing and rejected-reducer churn

- **Status:** ACCEPTED, deployed and live-observed, 2026-09-23.
- **Decision owner:** Operator: “add the fix but do not restart yet,” followed by
  a request to review the change, inspect current live logs and fix unusual
  behavior before restart.
- **Scope:** Preserve verified reference-drift evidence through brief ordinary
  source gaps without counting unknown time; reset on a changed owner/program/
  account generation or a gap over 15 seconds; require a fresh exact lease at
  cancellation send. Wake reward reflection after successful account recovery.
  Treat scalar create HTTP 400 as no-order proof, retain only a bounded error
  code, and durably back off consecutive identical reducers 10/20/40/60 seconds.
  Changed price, quantity or IOC mode may proceed immediately. Suppress empty
  broad-discovery inventory-plan logs while retaining material/final transitions.
  The required log review also authorizes repair of the observed 4,096-receipt
  writer crash: atomically archive the exact old audit rows before retaining a
  fresh hot receipt, never use archived evidence as current account authority,
  and classify overtaken metadata publications/quota deferrals as retry/defer
  states rather than failed market attempts.
- **Boundary:** No risk, quote-size, loss, market-selection or exit-deadline
  change. Unknown writes remain non-retrying. The operator subsequently
  authorized the controlled deployment and restart. The preserved ledger and
  limits were used; no initialization or account-wide cancellation occurred.

### D-099 — Emergency force cancellation, shutdown repair and controlled restart

- **Status:** ACCEPTED operation and implementation, 2026-09-23.
- **Decision owner:** Operator: “Force cancel all order then fix this” and, for
  the combined entry/exit repair, “fix it then restart.”
- **Scope:** Immediately cancel every account order, stop only the verified bot
  processes, repair the slow cancellation and false terminal-timeout mechanisms,
  test/review/publish/deploy, reconfirm a flat account and perform the already
  authorized normal restart.
- **Boundary:** Preserve the ledger, strategy and configured limits. No
  initialization, blind resend, risk expansion or process-wide termination.
  Cancellation speed cannot weaken exact owned-order, mutation, transport,
  identity or recovery proof; restart remains conditional on current flatness
  and normal supervisor admission.

### D-098 — Retain rewarded owners and review the complete order lifecycle

- **Status:** ACCEPTED implementation, 2026-09-23.
- **Decision owner:** Operator accepted incumbent retention, actual-reference
  monitoring, controlled same-market repricing and per-program reward progress,
  then requested the full entry/exit comparison with executable Polymarket code
  and inclusion of relevant fixes in the next restart bundle.
- **Scope:** Keep qualifying markets rather than chasing higher-ranked spares;
  reaching an estimated $1 does not release a market. Reuse the existing tracker,
  source owners, dispatcher and exact terminal/fill reconciliation. New entries
  retain $2-first/$1-fallback and 70% retained-value gates. Inventory handling
  takes priority over reward maintenance. Fix demonstrated lifecycle defects
  without importing Poly's current numeric risk settings or sports-only policy.
- **Boundary:** Build/test/review/publish in an isolated checkout. No live order
  action, deployment or restart is authorized by preparing the next bundle.
  Reward estimates remain advisory, never paid cash or guaranteed payout.

### D-097 — Repair recurring Windows status publication failure

- **Status:** ACCEPTED implementation, 2026-09-23.
- **Decision owner:** Operator: “Fix it.”
- **Scope:** Repair the observed transient Windows atomic-replacement failure,
  add a real contention regression, retain whole-document publication and
  fail-closed permanent-error handling, then verify/review/commit/push.
- **Boundary:** No trading logic, risk/configuration change, ledger reset or live
  restart. A later restart still requires explicit operational authority.

### D-096 — Initial combined-ranking checkpoint

- **Status:** ACCEPTED implementation and subsequent reviewed restart, 2026-09-23.
- **Decision owner:** Operator: “Ok do recommended,” then “Can you also restart
  once you review the fix.”
- **Scope:** Keep both book feeds and missing-field metadata concurrent; delay
  new entries until initial evaluated coverage or a bounded timeout, then rank
  current eligible candidates together with existing $2-first/$1-fallback rules.
  Revalidate prices, sources and limits before each order. Test and review before
  controlled stop/deployment/restart using the existing ledger.
- **Boundary:** No incumbent-upgrade policy, automatic repricing, risk changes,
  second bot or force-kill. Timeout never makes missing/stale evidence eligible.
  Inventory, cancellation and recovery continue independently of the checkpoint.

### D-095 — Controlled live restart after D-094 repair

- **Status:** ACCEPTED operation, 2026-09-23 Eastern.
- **Decision owner:** Operator: “Restart.”
- **Scope:** Start the existing normal production supervisor with the preserved
  ledger, reviewed inputs, strategy, risk limits and capital limits. Observe the
  launch through current process, account, source, admission and order evidence.
- **Boundary:** No initialization, configuration/risk changes, force-kill or
  second process. Existing readiness gates remain authoritative; if they block,
  diagnose rather than bypass them.

### D-094 — Repair host continuity and verify stopped-account recovery

- **Status:** ACCEPTED implementation/verification, 2026-09-23 Eastern.
- **Decision owner:** Operator: “Ok fix that too,” following the remaining
  host-continuity and manual-cancellation reconciliation blockers.
- **Scope:** Independent on-demand Windows supervisor launch, truthful liveness
  inspection, inert process-lifetime tests and GET-only account reconciliation
  evidence. Preserve exact order/fill recovery and all existing restrictions.
- **Boundary:** No live restart or order actions; no persistent service, startup
  task or power changes. Any local evidence import requires stopped-owner leases
  and a consistent backup; never infer canceled orders from absence or reset risk.

### D-093 — Adopt broad reviewed books and shared bulk metadata

- **Status:** ACCEPTED implementation, 2026-09-23 Eastern.
- **Decision owner:** Operator: “Ok lets use that,” following D-092's measured
  recommendation.
- **Scope:** Watch up to the existing 1,024 reviewed candidates on two public
  book shards; share bounded bulk event/market/milestone reads. Preserve current
  validators, complete fee schedules, freshness, generations and quotas. Bound
  ranking-to-entry work independently from public subscription breadth.
- **Boundary:** Supersedes D-091's 128-book rotating scope for normal live
  composition only. Monetary/account capacity, 30 resting entries, reward gates
  and all execution proofs remain unchanged. Test integration and performance;
  no live restart, account calls, order actions or production ledger changes.

### D-092 — Research and measure discovery alternatives before architecture changes

- **Status:** ACCEPTED read-only research/testing, 2026-09-23 Eastern.
- **Decision owner:** Operator: “Ok test it,” followed by research and comparison
  before blindly building an architecture.
- **Scope:** Bounded public-market WebSocket capacity measurements at increasing
  reviewed/rewarded scope, current official API research and comparison of
  broader subscriptions, ticker-assisted discovery and snapshot/metadata options.
- **Boundary:** Diagnostic instruments only. No production configuration, risk,
  order, ledger, restart or architecture change. Existing WS-first policy remains;
  broad REST book polling is not implicitly approved. Present evidence and the
  recommended implementation scope before adopting a production design.

### D-091 — Repair discovery coverage and bounded refill progress

- **Status:** ACCEPTED implementation, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Ok lets do it,” approving the preceding
  market-coverage diagnosis and recommendation.
- **Scope:** Consume exploration progress only for actually subscribed markets,
  retain unadmitted candidates across partial/deferred rotations, and improve
  bounded refill cadence when another pair fits the current risk limit. Add
  composed coverage/selection tests and bounded exclusion diagnostics.
- **Boundary:** Preserve protected ownership, 128 active books, two shards,
  16 additions per rotation, reward/reference/value gates, quota, risk and
  freshness rules. No live restart, venue commands, ledger edits or hosting
  overhaul in this work unit.

### D-090 — Size lifecycle transport for one bounded full-market snapshot

- **Status:** ACCEPTED, DEPLOYED and live-verified, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Also fix this issue before restart,” “Continue
  working,” and “Why it take so long just to cancel the order?” during the
  authorized stop/restart investigation.
- **Scope:** Restore the transport's existing 8,192-event / 16-MiB bounds only
  for the unscoped lifecycle subscription, whose measured initial snapshot was
  about 5,018 rows. Preserve account/scoped-book limits at 256 / 2 MiB.
- **Boundary:** Queueing remains bounded and overflow remains fail-closed. No
  ranking, reward, order, risk or stop-loss rule changes. If one complete live
  snapshot still cannot converge, stop flat and measure high-water before any
  further capacity change.

### D-089 — Correct proven pre-transport cancellation outcomes before restart

- **Status:** ACCEPTED implementation and controlled recovery, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Also fix this issue before restart,” followed by
  “Continue working,” after two cancellations remained blocked by the same
  pre-transport proof-change path.
- **Scope:** When the sole executor has advanced a command to `SENDING` but an
  explicit final proof check fails before transport invocation, atomically record
  `NOT_SENT`/`ABORTED`, release applicable capacity and request fresh recovery.
- **Boundary:** Any exception at or after transport invocation remains UNKNOWN.
  Do not infer safety from a timeout, HTTP error or missing acknowledgement. The
  two historical rows may be corrected only from exact stopped-owner ledger and
  retained diagnostic evidence, with a verified backup. Normal entries still
  require recovery-only verified flatness.

### D-088 — Repair progress-aware graceful drain before restart

- **Status:** ACCEPTED implementation and controlled restart, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Also fix this issue before restart,” after the
  authorized stop exposed recovery exhaustion with resting orders remaining.
- **Scope:** Preserve source revalidation after every safety cancellation, but
  give a new bounded three-failure budget after a source-consistent pass made
  durable forward progress and queued its required fresh reconciliation.
- **Boundary:** Do not weaken ownership/proof checks, batch uncertain cancels,
  retry an UNKNOWN mutation, reset the ledger/risk state or force flatness.
  Resume normal entries only after recovery reaches verified flatness.

### D-087 — Recover the lifecycle stream after bounded retry rounds

- **Status:** ACCEPTED implementation, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Ok check it then fix it,” after the unchanged
  live process reported permanent lifecycle retry exhaustion.
- **Scope:** Keep account/book retry exhaustion unchanged. For the advisory
  lifecycle reader only, revoke source terms after failure, retain three attempts
  per round, then retry on a capped 30/60/120/240/300-second backoff until stop.
  Preserve monotonically increasing stream generations and bounded diagnostics.
- **Boundary:** A retry/ACK never makes stale metadata current, resets no metadata
  retry hold and grants no trading authority. Deployment/restart remains separate.

### D-086 — Repair reward catalog and quiet-book sources

- **Status:** ACCEPTED implementation, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Ok add all the fix,” following the reward API audit.
- **Scope:** Use bounded 1,000-row incentive pages in preparation and runtime;
  refresh quiet subscribed books using documented WebSocket `get_snapshot`,
  with bounded requests, correlation, sequence checks and offline regressions.
- **Boundary:** Preserve reward/risk filters, freshness, retry exhaustion and
  account authority. No new earnings API is invented. No live restart, retry
  reset, order action or wider market capacity is included in this code task.

### D-085 — Reconcile the single pre-transport cancel refusal

- **Status:** ACCEPTED one-time operational correction, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Sure,” approving reclassification of the
  specific cancellation discussed in the preceding session and recovery/restart.
- **Scope:** With the production process stopped and account ownership held,
  preserve a backup and transactional audit of the one cancel attempt recorded
  at 2026-09-22 23:34:25 UTC. Its retained execution diagnostic points to the
  pre-transport `proof_changed_before_submission` branch. Change that attempt
  from UNKNOWN to NOT_SENT and its exact authorization to ABORTED, allowing
  the existing bounded reauthorization path to obtain fresh cancellation proof.
  Reconcile remaining orders through the supervised recovery path, then resume
  the previously authorized normal bot only after verified flat recovery.
- **Boundary:** No general UNKNOWN retry policy, loss/accounting reset, deletion
  of history, size/capital/filter change or manual venue cancellation. Keep
  original rows and evidence in the ignored local audit and ledger audit entry.

### D-084 — Attribute exact personal opening cash and resume initialization

- **Status:** ACCEPTED live-opening correction, 2026-09-22.
- **Decision owner:** Operator previously identified the account as personal,
  said its $500 bank/card funding may be used, explicitly authorized the live
  run, and then instructed “Lets fix it” after the retained funding blocker was
  shown.
- **Scope:** The explicit opening approval may attribute retained, completed,
  pre-boundary personal deposits and completed pre-boundary intra-exchange
  transfers to the exact current flat cash baseline. An interrupted first
  initialization must resume the same immutable checkpoint after a fresh
  matching inspection; it must not delete the ledger, choose a new boundary or
  replay initialization.
- **Boundary:** Pending/returned/failed funding, withdrawals, subaccount
  transfers, post-boundary activity, settlements, changed cash, positions,
  orders and every other economic hold remain blocking. Attribution records
  exact retained event digests and grants no independent order authority.
- **Contract:** [First-live opening recovery](docs/BUILD_FIRST_LIVE_OPENING_RECOVERY.md).

### D-083 — Gate new entries by value retention and projected reward

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: “Ok lets add those filters,” after reviewing the
  current public rewarded-market measurement.
- **Scope:** A new size-10 two-sided entry must quote both current reference
  prices at full reward weight, retain at least 70% of each side's entry value
  under a full visible-depth immediate exit including the current fee bound, and
  project at least $1 gross reward through the earlier program/entry deadline.
  Candidates projecting at least $2 receive slots before the $1–<$2 fallback;
  the existing ranking remains stable within each tier.
- **Boundary:** These are initial-entry gates, not payout or profit guarantees.
  Existing orders and inventory remain governed by their current management and
  exit rules; this does not add hot repricing, reward-chasing cancellation, a
  fixed market pool, live authority or a bot start.
- **Contract:** [Entry-quality gates](docs/BUILD_ENTRY_QUALITY_GATES.md).

### D-082 — Admit the reviewed scheduled-release timing family

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: “Ok fix it,” after the executable Polymarket
  comparison and current Kalshi public-data audit found zero eligible candidates.
- **Scope:** Replace the blanket early-close exclusion only for Kalshi's exact
  scheduled-economic-data release condition when the market has an occurrence
  time and exactly one future primary milestone of a reviewed release type.
  Bind the occurrence time into the rules digest and recheck the family and
  timing relation at runtime.
- **Boundary:** Unknown early-close rules, sports, related-only milestones and
  missing/conflicting clocks remain blocked. Existing reward, ranking, capital,
  order, position, loss, fee and launch gates remain unchanged. This decision
  does not authorize a live start or order.
- **Contract:** [Candidate timing adaptation](docs/REVIEW_CANDIDATE_TIMING_POLY.md).

### D-081 — Connect the production runtime to the native supervisor

- **Status:** ACCEPTED implementation scope, 2026-09-22.
- **Decision owner:** Operator: “Ok we need to work on all of this, lets start
  the implementation,” after accepting the ordered supervisor checklist.
- **Scope:** Connect one fixed production child to the existing foreground
  Windows supervisor; route start/stop/status through it; preserve the existing
  financial ledger and runtime gates; use bounded recovery-only child restarts.
- **Recovery rule:** Unexpected child death can restart only with entries paused.
  A recovery child reconciles/cancels/manages existing inventory to verified
  flat, then the supervisor disarms. Resuming entries requires a later explicit
  operator start. Startup/integrity/local-control failure and exhausted retries
  require attention.
- **Boundary:** This decision does not authorize the first live run, install a
  host watchdog or scheduled task, alter power settings, reset a ledger, weaken
  risk limits, or change trading strategy.
- **Contract:** [Production supervisor recovery](docs/DESIGN_PRODUCTION_SUPERVISOR.md).

### D-080 — Prepare the production-supervisor work checklist

- **Status:** ACCEPTED planning/documentation scope, 2026-09-22.
- **Decision owner:** Operator: “Ok create a to do list for this work lets start
  from that,” following the production supervisor and later host-watchdog discussion.
- **Scope:** Maintain one prioritized checklist in [NEXT.md](NEXT.md#production-supervisor-connection--ordered-checklist),
  covering production integration, recovery rules, tests, review/publication,
  live acceptance and the separately staged Windows host watchdog. Reuse S1/S2.
- **Boundary:** Creating the checklist does not implement or accept a new restart
  policy, start trading, install a scheduled task, change power settings or modify
  Polymarket. Existing model continuity and single-session rules remain.

### D-079 — Automatically prepare the best current rewarded-market universe

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: “We need to fix it that we get the best rewarded
  market,” after confirming the existing one-market input defeated ranking.
- **Scope:** Use public active incentives, complete market rules and exactly one
  future official primary milestone to prepare at most 1,024 candidates; seed at
  most 128 WebSocket books and retain the existing actual-book ranking and
  30-resting-order limit. Keep a rewarded head plus stratified discovery tail.
- **Boundary:** Cheap reward density is exploration, not final selection or a
  profit claim. Runtime rules/milestone/lifecycle checks, T-5 deadline, fee,
  capital, position, loss, ownership and dispatch gates remain. No live start or
  order is authorized. Refresh is blocked with an existing ledger unless saved
  shutdown is verified flat. Automatic preparation excludes early-closing
  markets; their natural-language conditions require a separate explicit review.
- **Contract:** [Automatic candidate preparation](docs/BUILD_AUTOMATIC_CANDIDATES.md).

### D-078 — Connect automatic selection to the original launcher

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: “Ok lets do it,” accepting discovery → market
  checks → ranking → admission, with unsupported candidates skipped visibly.
- **Scope:** Attach the existing admission owner to the actual composition;
  separate the bounded reviewed candidate universe from active subscriptions,
  preserve timing reviews across rotation, resolve fresh fees/rules through the
  existing metadata service, and test the complete handoff with synthetic wires.
- **Boundary:** No inferred event-risk clock, automatic approval of unknown
  rules, sports-only filter, score-chasing cancellations or risk-limit changes.
  Working orders, inventory and uncertain owners remain protected. No live
  start, private-input change, order or deployment is authorized by this build.
  At D-078 publication local inputs contained one review; D-079 subsequently
  supplies bounded exact preparation. D-078 itself never made unknown markets
  eligible.

### D-077 — Finish the existing bot's minimum operating path

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: use the bot already built, defer unnecessary
  hardening, then “Ok finish whats necessary.”
- **Scope:** Connect the original WebSocket/ranking/accounting/dispatch/inventory
  owners to an explicit Windows foreground launch; retain the approved size,
  capital, exposure, loss windows and exit policy. Keep basic logs and graceful
  shutdown. No new paper-trading stage, replacement bot, model switch or worker.
- **Supersedes:** D-076's separate REST canary and hold-to-settlement workflow.
  Its run entry point is retired. Historical previews remain local evidence.
- **Boundary:** Implementation and synthetic/read-only verification are not a
  completed live launch. Reviewed current market/fee inputs and a fresh opening
  baseline remain necessary. No automatic deployment/restart or risk expansion.
  The coding assistant must not submit trades or invoke the trading launcher;
  an operator-run live command is separate from software verification.
- **Contract:** [Minimal original runtime](docs/RUN_LIQUIDITY_BOT.md).
- **Account evidence:** On 2026-09-22 the operator confirmed this is a personal
  account opened directly with Kalshi, not a broker/FCM account. This supports
  the direct-member fee profile; it does not authorize a launch by itself.

### D-076 — Prioritize a minimal live profitability canary — SUPERSEDED by D-077

- **Status:** ACCEPTED build/prepare scope, 2026-09-22; submission pending.
- **Decision owner:** Operator: focus on resting orders and gathering live data
  today; defer additional production hardening until profitability is known.
- **Decision:** Build a one-market canary using the existing Kalshi selection
  arithmetic: two post-only 10-contract orders, at most six hours, estimated
  reward at least $1, cancel on first observed fill or planned end, and preserve
  actual fill/fee/settlement/reward evidence.
- **Risk boundary:** One entry batch only; maximum net position is 10 contracts,
  no market taking/repricing/rotation and no autonomous runtime activation.
  Preparation is read-only. The exact live submission still requires explicit
  operator confirmation after a fresh preview.

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

### D-050 — Design a Polymarket-like native Windows supervisor

- **Status:** ACCEPTED requirement/design scope, 2026-09-21; operator approved
  the S1 design and offline policy values through “Implement.”
- **Decision owner:** Operator requests a supervisor that survives errors and
  recovers automatically, before returning to the D-048 review.
- **Scope:** Trace Polymarket's actual supervisor/recovery source and design
  native Windows process supervision, bounded recovery, persistent stops,
  diagnostics and restart safety. See
  [the proposed design](docs/DESIGN_WINDOWS_SUPERVISOR.md).
- **Boundary:** Approval covers the execution-disabled S1 policy/control
  foundation only. It does not approve automatic source-code fixes, live
  auto-resume, services/tasks, deployment, account calls or trading. Preserve
  all existing risk/authority rules. D-048 review remains pending; design
  priority does not waive its integration gate.

### D-051 — Implement native Windows supervisor S1

- **Status:** ACCEPTED implementation scope and implemented, 2026-09-21.
- **Decision owner:** Operator: “Implement,” after the D-050 Astra design stop.
- **Scope:** Add immutable execution-disabled supervisor contracts and pure
  transition policy, a separate transactional bounded SQLite control journal,
  fake event/process tests and offline resource fixtures. Persist stop and
  generation state, reserve attempts before spawn requests, reject stale child
  events, bound restart/backoff and base health on useful progress.
- **Evidence:** See
  [D-051 build evidence](docs/BUILD_WINDOWS_SUPERVISOR_S1.md): 32 focused and
  836 full tests pass, with resource and disabled-preflight checks.
- **Boundary:** No real process launcher, IPC, runtime integration, service/task,
  credential/network/account access, live auto-resume or trading. Independent
  Astra review is mandatory before S2. D-048's separate review also remains an
  S2 gate.

### D-052 — Implement D-051 supervisor review findings

- **Status:** ACCEPTED implementation scope and implemented, 2026-09-21.
- **Decision owner:** Operator: “Implement those,” after the D-051 Astra review.
- **Scope:** Implement R1-R7 from
  [the D-051 review](docs/REVIEW_D051_ASTRA.md): trusted control/event time
  separation, stop/safety generation fencing, strict lifecycle ownership,
  bounded useful-progress and startup deadlines, persistent explicit retry holds,
  truthful process-exit/cleanup recovery evidence and a real persisted-work idle
  benchmark. Add deterministic regressions and rerun required verification.
- **Evidence:** See
  [D-052 build evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md): 46
  focused and 850 full tests pass, with repeated focused, resource, compilation
  and disabled-preflight checks.
- **Boundary:** Preserve D-051's execution-disabled S1 scope. No process launcher,
  IPC, runtime integration, service/task, credential/network/account access,
  live auto-resume or trading. Independent Astra re-review is mandatory before
  S2; D-048's separate review remains another S2 gate.

### D-053 — Implement D-052 supervisor re-review findings

- **Status:** ACCEPTED implementation scope and implemented, 2026-09-21.
- **Decision owner:** Operator: “Ok implement,” after the D-052 Astra re-review.
- **Scope:** Implement R1-R5 from
  [the D-052 review](docs/REVIEW_D052_ASTRA.md): fence every STOP generation,
  evaluate startup/progress expiry before status refresh, preserve attention
  during failed-spawn release, persist and validate clock continuity across
  store instances/lifetimes, and require complete child identity. Add the
  review's deterministic policy and SQLite regressions.
- **Evidence:** See
  [D-053 build evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md): 59
  focused and 863 full tests pass, with 10/10 repeated focused runs, resource,
  compilation, documentation and disabled-preflight checks.
- **Boundary:** Preserve execution-disabled S1. No process launcher, IPC,
  runtime integration, service/task, configuration, credential/network/account
  access, bot restart, orders or live action. Independent Astra re-review is
  mandatory before S2; D-048 remains a separate S2 gate.

### D-054 — Implement D-053 clock review findings

- **Status:** ACCEPTED implementation scope and implemented, 2026-09-21.
- **Decision owner:** Operator: “Sol implement,” after the D-053 Astra review.
- **Scope:** Implement R1/R2 from
  [the D-053 review](docs/REVIEW_D053_ASTRA.md): durably apply local clock trust
  failures before stale child payload filtering while preserving stale labels,
  and replace exact quantized default boot matching with persisted, tolerance-
  validated wall/monotonic continuity. Add policy and SQLite regressions for
  stale/missing identity, duplicate lifecycle, multiple store handles, reopen,
  active-child ownership, harmless jitter and genuine discontinuities.
- **Evidence:** See
  [D-054 build evidence](docs/BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md): 64
  focused and 868 full tests pass, with 10/10 repeated focused runs, four
  counterfactual parent detections, resource, compilation and preflight checks.
- **Boundary:** Preserve execution-disabled S1. No launcher, IPC, runtime
  integration, service/task, configuration, credential/network/account access,
  bot restart, orders or live action. Independent Astra re-review is mandatory
  before S2; D-048 remains a separate S2 gate.

### D-055 — Design supervisor S2 native lifecycle

- **Status:** ACCEPTED design scope only, 2026-09-21.
- **Decision owner:** Operator: “Astra design s2,” after S1 and D-048 review
  clearance. This does not approve the resulting design's implementation.
- **Scope:** Specify native Windows ownership, process/IPC interfaces, stop and
  crash recovery, bounded resources, offline runtime integration and acceptance.
  See [S2 design](docs/DESIGN_WINDOWS_SUPERVISOR_S2.md).
- **Proposed handoff:** Approve S2A inert-process foundations for Sol first;
  stop for Astra review before a separately assigned S2B offline runtime/fence
  phase. The split and new fixture thresholds await approval.
- **Boundary:** Design/documentation only. No code/configuration change, process
  launch, service/task, laptop suspend/reboot, credentials, venue/account access,
  order action, deployment or live authority. Preserve D-049's design stop.

### D-056 — Implement supervisor S2A inert-process foundations

- **Status:** ACCEPTED and implemented offline, 2026-09-21; Astra review pending.
- **Decision owner:** Operator: “Sol implement,” after the D-055 Astra design.
- **Scope:** Implement only D-055 S2A: protected native role objects, serialized
  control/reservation state, bounded strict local pipe IPC, one fixed inert child,
  retained graceful shutdown, cold orphan release, native fault tests and resource
  evidence. See [build evidence](docs/BUILD_WINDOWS_SUPERVISOR_S2A.md).
- **Boundary:** No S2B runtime adapter or recovery-fence transfer, production start
  command, service/task, bot configuration/runtime change, credentials, network,
  venue/account access, order action, deployment or live authority. Stop for Astra
  review under D-049.

### D-057 — Astra implements the S2A review fixes

- **Status:** ACCEPTED and implemented offline, 2026-09-21; independent review pending.
- **Decision owner:** Operator: “I recommend astra to fix this since sol took so
  long to solve it,” after the D-056 review and correction handoff.
- **Scope:** Astra implements R1-R8 from [the review](docs/REVIEW_D056_ASTRA.md)
  and verifies the inert S2A foundation. This is a task-specific exception to
  D-049's Sol fix phase, not a permanent change to model routing.
- **Boundary:** Preserve the D-055 architecture and all safety gates. No S2B,
  live runtime, configuration, account access, deployment, restart or trading.
  Stop after fixes/verification for independent review; implementation is not
  self-clearance.

### D-058 — Astra commits previous work and performs overall review

- **Status:** ACCEPTED and performed, 2026-09-21.
- **Decision owner:** Operator: “Astra commit then review the one I asked previously.”
- **Scope:** One-task commit exception to D-049, followed by the requested
  overall code review and priority-ordered actions. Previous work committed as
  `8c03aa0`; [review evidence](docs/REVIEW_OVERALL_2026-09-21.md).
- **Boundary:** No permanent routing change, new implementation, source/config
  change, push, runtime action or live authority. Recommendations need a new
  assignment; existing review and readiness gates remain in force.

### D-059 — Plan the first two overall-review priorities

- **Status:** ACCEPTED design assignment, 2026-09-21; plan produced, implementation
  and proposed schema/capacity changes await approval.
- **Decision owner:** Operator: “Ok we are doing it in priority order lets do 1
  and 2 first Astra go ahead and plan it.”
- **Scope:** Astra designs safety-command capacity and the atomic reservation/
  execution handoff in [the plan](docs/DESIGN_COMMAND_CAPACITY_HANDOFF.md), then
  stops for approval and Sol. The earlier overall queue remains the roadmap.
- **Boundary:** Documentation only. No source/config/runtime change, migration,
  history deletion, commit/push, live action or clearance of other readiness gates.

### D-060 — Implement the approved D-059 design

- **Status:** ACCEPTED and implemented offline, 2026-09-21;
  [Astra review](docs/REVIEW_D060_ASTRA.md) requires corrections.
- **Decision owner:** Operator: “Sol implement.”
- **Review assignment:** Operator subsequently: “Astra do it.” Independent
  review only; no new implementation or operational authority inferred.
- **Scope:** Implement both priority fixes exactly through the D-059 interfaces,
  schema-3 disposable ledgers, bounded durable capacity credits, atomic
  preparation/receipt consumption, fault tests and 30/120-market resource
  verification. Evidence: [D-060 build record](docs/BUILD_COMMAND_CAPACITY_HANDOFF.md).
- **Boundary:** No schema-2 migration, archive deletion, risk/config change,
  authenticated transport, account access, deployment, restart or live action.
  Stop after verification for independent Astra review; all other readiness
  gates retain their previous state.

### D-061 — Remove model-switch workflow requirements

- **Status:** ACCEPTED permanent workflow change, 2026-09-21.
- **Decision owner:** Operator: “forget about switching models,” followed by
  “no more changing models even the one from earlier.”
- **Decision:** D-049's required model recommendation, model-mismatch stop and
  manual Astra/Sol phase switching are superseded. Continue authorized work
  with the model already selected; do not recommend or require model changes.
- **Boundary:** This changes only model routing. It does not relax project
  decisions, independent review quality, testing, security, deployment,
  restart, credential, account, capital, risk or live-action controls.

### D-062 — Continue the remaining work in priority order

- **Status:** ACCEPTED offline build assignment, 2026-09-21; in progress.
- **Decision owner:** Operator: “Just do all of it in priority order,” followed
  by “Ok continue working.”
- **Scope:** Finish the remaining authorized development in the
  [overall review](docs/REVIEW_OVERALL_2026-09-21.md). Priority 3 starts with
  [bounded opening-account/cash evidence](docs/DESIGN_OPENING_ACCOUNT_CASH.md),
  current public API verification, offline tests and independent review.
  Continue routine implementation and verification without model-switch gates.
- **Boundary:** No inferred account exclusivity, launch timestamp, inventory
  adoption, settlement/correction policy, loss reset or schema migration.
  Pending choices still require the operator; broad build scope does not grant
  credentials/account calls, live transport activation, trading, deployment,
  restart, commit or push. Existing review and readiness gates remain in force.

### D-063 — Return to single-session development

- **Status:** ACCEPTED workflow change, 2026-09-21.
- **Decision owner:** Operator: “Cant we go back on how we usually build stuff
  like originally,” after discussing delegated workers and usage.
- **Decision:** Continue directly in the primary session. Stop existing workers,
  preserve their partial work, and complete/review/verify it locally. No new
  delegated agents or worker sessions unless explicitly requested again.
  D-061's no-model-switch rule remains.
- **Boundary:** Existing build scope, testing, risk and live-operation rules
  remain unchanged. Worker handoffs are not completion evidence.

### D-064 — Primary account, exclusive bot use, flat opening

- **Status:** ACCEPTED opening-account policy, 2026-09-21; not activated.
- **Decision owner:** Operator: “I wont trade manually on this,” then “Ok” to
  the explicit confirmation: use the primary Kalshi account exclusively for
  this bot, starting only after verifying zero open positions and zero resting
  orders.
- **Decision:** Scope the future bot to primary subaccount 0. No manual trading
  in that account during bot operation. Before arming, require fresh evidence of
  no nonzero positions and no resting orders. Existing history remains separate
  reconciliation evidence under D-030; it is not silently imported or discarded.
- **Boundary:** This records the operator's choice, not current flatness,
  exclusivity proof, a launch timestamp, settled-loss reset, opening basis or
  live authority. Choose the exact accounting boundary during a separately
  approved launch after the required checks. No account/API call, order action,
  migration, deployment or restart is approved by this decision.

### D-065 — Verify, commit and push completed work

- **Status:** ACCEPTED permanent repository workflow, 2026-09-21.
- **Decision owner:** Operator: “When we finish something we should always check
  then commit and push.”
- **Decision:** After each completed work unit, run relevant verification,
  review the exact diff for scope and secrets, commit the verified changes and
  push to the canonical GitHub branch. Verify local/remote commit parity after
  pushing. Do not present unfinished work as complete merely to publish it.
- **Boundary:** This supersedes earlier no-commit/no-push clauses for completed,
  verified repository work only. Preserve unrelated changes, ignored private
  material and remote commits; never force-push or resolve divergence by
  overwriting. If checks or publication fail, report the state and retain work.
  Publication is not bot deployment, account access or live-trading authority.

### D-066 — Pause new entries for unexpected bot-owned settlement

- **Status:** ACCEPTED offline policy, 2026-09-21; not live-integrated.
- **Decision owner:** Operator: “Ok do recommended,” after the recommendation
  to pause new Kalshi entries when a bot-owned open position unexpectedly
  reaches settlement, and reconcile before treating its payout as six-hour
  loss-meter P&L.
- **Decision:** Such a settlement requires a new-entry pause and operator
  reconciliation. Do not synthesize a closing fill, infer basis from venue
  aggregate costs, or automatically add settlement revenue/fees to the D-024
  six-hour matched-fill meter. Preserve the observed position, settlement and
  cash evidence; keep unrelated exit/cancel safety actions available under
  their separate rules. No automatic release merely because the account later
  appears flat or a new six-hour window begins.
- **Boundary:** Existing pre-bot settlements remain historical evidence, not
  proof of a bot-owned event. The precise approved opening boundary, durable
  settlement journal/hold and reconciliation-release protocol are separate
  build gates. This decision does not authorize account calls, schema migration,
  live entry/order actions, deployment or restart.

### D-067 — Finish offline opening-account accounting and enforcement

- **Status:** ACCEPTED build assignment, 2026-09-21.
- **Decision owner:** Operator: “Finish it then,” after the remaining baseline,
  cash/reservations, persistent settlement pause, history/stream and entry-gate
  work was explained.
- **Scope:** Complete the necessary offline design, implementation, integration,
  recovery tests and review under D-064/D-066. Persist accounting evidence and
  restrictions in the single-writer ledger; enforce them in entry reservation
  and prepared-command dispatch. Test new schema only in disposable ledgers.
- **Boundary:** No migration or modification of existing runtime ledgers,
  authenticated account reads, real opening boundary, fabricated venue proof,
  live transport, deployment or trading. Missing venue guarantees remain
  explicit blockers. D-065 governs publication after verification.

### D-068 — Operational reconciliation gate in place of global venue proof

- **Status:** ACCEPTED offline implementation, 2026-09-21.
- **Decision owner:** Operator: “Ok follow poly,” after the actual Polymarket
  reconciliation, freshness gates, buying-power reservations and residual
  silent-staleness limitation were explained from executable code.
- **Context:** The operator requested the required work to finish the release
  path. Investigation found that the reviewed user-data timestamp is explicitly
  approximate; existing source contracts do not establish global REST/stream
  completeness. This explicit choice, not generic build authorization, changes
  the entry-safety criterion.
- **Decision:** Adopt the bot-owned, source-fenced reconciliation and
  conservative two-ceiling cash model in the
  [accounting design](docs/DESIGN_OPENING_ACCOUNT_ACCOUNTING.md). Continue to
  report global venue handoff as unproved. Preserve economic holds and all
  independent risk, operator-settlement, live-activation and restart rules.
- **Tradeoff:** Common REST/stream delay can temporarily hide an event; repeated
  matching observations cannot eliminate that residual risk. The strict-proof
  alternative was not selected; live activation still requires separate approval.
- **Authority:** Offline implementation/tests only, not account requests, a real
  opening boundary, trading or deployment. Do not import Poly's venue fields,
  risk settings or operational permissions. D-066 economic holds remain.

### D-069 — Optimize Kalshi selection using reward qualification and Poly lessons

- **Status:** ACCEPTED offline implementation, 2026-09-21.
- **Decision owner:** Operator: "Ok using all these info make sure we optimize
  our market selection", following the reference-price, competition, loss of
  scoring eligibility and safe quoting discussion.
- **Decision:** Implement the [reference-audit direction](docs/POLYMARKET_RANKING_AUDIT.md):
  eligible feasible size-10 quotes first, estimated gross hourly reward then
  capital efficiency, current reward qualification separate from hypothetical
  new quotes, fresh bounded selection and retained inventory/uncertain owners.
  Do not copy Poly's sports filters, historical reward or fill-loss calibration.
- **Boundary:** Keep D-021's reducer of resting-entry COUNT, not contract size,
  and all existing cash/exposure/exit gates. Show payout uncertainty, not net
  profit or assured payment. Losing scoring is not terminal order evidence.
  No automatic score-chasing repricing, new profitability cutoff, live transport,
  account request, deployment, bot operation or market-set approval.
- **Build contract:** [Selection integration](docs/BUILD_MARKET_SELECTION.md)
  records bounded advisory integration, tests and remaining activation gates.

### D-070 — Poly-style selection and per-program reward tracking, no fixed 60

- **Status:** ACCEPTED offline build, 2026-09-21.
- **Decision owner:** Operator: "follow something like polymarket but optimize
  it to kalshis advantage and add that tracker", then "Forget about the 60
  markets" and "Just do it like poly".
- **Decision:** Drop the proposed fixed 60-market pool. Adapt bounded discovery,
  fresh book-based selection, stable incumbents and flat/clear refill from
  Polymarket's executable code. Add per-program estimated accrual, qualification
  time, unknown gaps and estimated time to the $1 minimum. Preserve Kalshi's
  target/reference rules, actual period duration and separate payout evidence.
- **Boundary:** No automatic import of Poly sports filters, numerical risk,
  fill-loss priors or six-hour reward duration. Size 10, max 30 resting entries,
  existing capital/exposure/exit rules and live-disable remain. No new numerical
  payout buffer, score-displacement threshold or reward-chasing cancellation is
  approved. Track estimates as advisory, never paid cash or entry authority.
- **Implementation:** [Tracker and discovery adaptation](docs/BUILD_REWARD_TRACKER.md).

### D-071 — Connect automatic market admission and rotation

- **Status:** ACCEPTED offline implementation, 2026-09-21.
- **Decision owner:** Operator: "Ok do number 1", referring to automatic market
  admission/rotation in the pending-work list.
- **Scope:** Connect D-070 candidates to bounded book subscriptions and fresh
  D-069 ranking under existing order/capital limits. Never remove inventory,
  working orders or unresolved activity; retain uncertain scope. No fixed pool,
  new category filter, repricing policy, live order transport or bot operation.
- **Implementation contract:** [Admission and rotation](docs/BUILD_MARKET_ADMISSION.md).

### D-072 — Connect selected entry pairs to guarded order transport

- **Status:** ACCEPTED offline implementation, 2026-09-21.
- **Decision owner:** Operator: "Ok do 2", referring to the ordered work item
  after automatic market admission.
- **Scope:** Connect current ranked additions to the existing writer risk gates,
  quota owner and dispatcher. Use one exact two-leg local reservation and one
  documented Kalshi V2 batch create; retain single create/cancel transport for
  inventory exits. Mixed, unidentified or uncertain venue outcomes fail closed,
  request reconciliation and are never retried automatically.
- **Boundary:** This approves construction and synthetic verification only.
  Live activation remains unavailable; no credential/account request, order,
  cancel, deployment, bot start or restart is authorized. The next independent
  strategy/runtime work is production reward reflection/checkpoint lifecycle.
- **Implementation contract:** [Entry dispatch and transport](docs/BUILD_ENTRY_DISPATCH_TRANSPORT.md).

### D-073 — Build production reward reflection/checkpoint lifecycle

- **Status:** ACCEPTED execution-disabled implementation, 2026-09-22.
- **Decision owner:** Operator: "After this can you start working on 3 and 4?"
- **Scope:** Join exact own resting orders, public book levels and queue-position
  evidence for estimate-only reward tracking; own bounded checkpoint load/save
  in runtime lifecycle. Unknown or raced evidence remains UNKNOWN.
- **Boundary:** No paid-reward claim, strategy/risk change, bot start or live
  order authority. [Implementation](docs/BUILD_REWARD_REFLECTION.md).

### D-074 — Continue readiness work after reward reflection

- **Status:** ACCEPTED implementation/read-only verification, 2026-09-22.
- **Decision owner:** Operator requested #4 after #3 and directed remaining work
  in priority order.
- **Scope:** Resolve the existing S2A resource blocker without weakening safety;
  use previously authorized read-only credentials for current limits/costs when
  needed; preserve unresolved fee/timing/account evidence explicitly.
- **Boundary:** No strategy/risk choice, authenticated write, order action,
  service/task, bot start/restart or live launch. S2B and launch remain separate.
- **Implementation contract:** [resource/readiness evidence](docs/BUILD_WINDOWS_SUPERVISOR_RESOURCE_FIXES.md).

### Earlier concentration question — superseded by D-070

- **Status:** Historical discussion; D-070 above is the current build direction.
- **Operator concern:** Rotation may spread earnings below the $1 payout
  minimum; concentrate on the strongest opportunities, referencing Poly's
  moneyline approach. Clarify strict sports moneyline-only versus best eligible
  programs across categories with less rotation before changing selection.
- **Verified rule:** [Kalshi help](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them)
  says a final reward below $1 per individual program is not paid. This is not
  an aggregate event/day/account minimum; estimates can change before payment.
- **Recommendation, not implemented:** Prefer feasible programs with enough
  safe remaining earning time to clear the minimum with a margin; reduce
  unnecessary rotation and track program-specific estimated accrual. Neither
  moneyline classification nor an estimate guarantees payment. Never keep risk
  solely to reach $1 or override existing exit, exposure and stop-loss rules.
- **Boundary:** No new category filter, hard earnings gate, dwell period,
  repricing rule or launch authority accepted/implemented in this build unit.

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
