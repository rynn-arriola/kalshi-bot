# Current status

## Entry-quality filters implemented; live start still separate — 2026-09-22

D-083 adds the accepted new-entry policy to the existing WebSocket selector.
Both size-10 sides must be at their exact current reference prices with full
reward weight, each must retain at least 70% of entry value under the current
full-depth/fee exit stress, and the pair must project at least $1 through its
bounded earning horizon. $2+ candidates take slots before $1–<$2 fallback
candidates; the normal rate/efficiency ranking remains inside each tier.

Focused selection, discovery, admission, dispatch and complete synthetic live
composition tests pass. The full offline suite ran 1,434 tests in 215.907
seconds with 1,433 passed and one expected Windows privilege skip. The 30/120
market selection and admission resource gates pass. Existing orders and
inventory are not canceled or repriced by this filter. No production process,
credential, ledger, order or live launch was used.
[Implementation contract](docs/BUILD_ENTRY_QUALITY_GATES.md).

## Candidate timing blocker fixed; live acceptance remains — 2026-09-22

D-082 implements the bounded scheduled-release family from the
[executable Poly comparison and Kalshi adaptation](docs/REVIEW_CANDIDATE_TIMING_POLY.md).
Automatic preparation now accepts only the exact Kalshi economic-data release
condition with a reviewed release milestone type, an occurrence timestamp and a
safe occurrence/milestone relation. The occurrence timestamp is rules-bound and
the relation is rechecked from current metadata at runtime. Unknown early-close
families, including sports, remain blocked.

A fresh credential-free public refresh prepared **1,024** reviewed candidates
and 128 initial WebSocket markets from 4,923 incentive rows and 4,917 market
rows. First-failure exclusions were 1,505 unknown early-close rules, 1,960
missing future primary milestones, 38 ambiguous milestones and six inactive or
capped programs. The ignored local input validates with no legacy blanket
approvals. The full offline suite ran 1,431 tests, with 1,430 passed and one
expected Windows privilege skip. A 45-second read-only startup connected all required feeds and
reported `startup_verified=true`; it intentionally placed no orders and created
no production ledger. First supervised live acceptance is still unverified and
requires a separate explicit operator launch.

## End-to-end supervisor repairs verified offline — 2026-09-22

All seven findings from the [D-081 review](docs/REVIEW_D081_END_TO_END.md) are
implemented and covered by production-path regressions. Account ownership now
survives exception drain; preparation/cooldown waits remain supervised; actual
quota restrictions survive process loss; temporary health blockers do not become
retry holds; recovery filters unrelated expired candidates; post-admission exits
retain recovery semantics; and terminal flat status is saved only after cleanup.

Final offline suite: **1,428 run, 1,427 passed, one expected Windows privilege
skip**. Native 60-second supervision and 30/120-market runtime, selection and
admission gates pass. No live process, credentials, venue request, production
ledger or order was used. Software checklist items 2–6 are complete again;
first supervised live acceptance remains separate item 7 and is not yet verified.

## D-081 production supervisor connected and verified offline — 2026-09-22

The foreground start/stop/status scripts now route through the native Windows
supervisor and one fixed production child. The parent cannot read credentials;
the child retains the existing account lease, financial ledger and live runtime.
An unexpected child exit can only launch a bounded recovery-only child, which
sets entries paused before composition and must reach verified flatness before
the supervisor disarms. It never automatically resumes quoting.

One-time initialization, fixed launch fingerprints, protected production control
scope, saved-status labeling and recovery-mode regressions are implemented.
The complete offline suite passes 1,419 tests with one expected Windows
privilege skip. Final native 60-second/100-cycle targets and offline S2B,
selection and admission 30/120-market gates pass. The production diff was
reviewed and corrected before publication. No bot, credentials, Kalshi request, ledger or
order was started by this work; first supervised live acceptance remains item 7.

[Recovery contract](docs/DESIGN_PRODUCTION_SUPERVISOR.md) ·
[Build and verification](docs/BUILD_PRODUCTION_SUPERVISOR.md) ·
[Run guide](docs/RUN_LIQUIDITY_BOT.md) ·
[Remaining checklist](NEXT.md#production-supervisor-connection--ordered-checklist)

## Production supervisor checklist prepared — 2026-09-22

D-080 records the operator's request to begin with a
[prioritized checklist](NEXT.md#production-supervisor-connection--ordered-checklist).
The existing native supervisor and S2B fixture were built; D-081 now connects a
separate fixed production profile. S2B deliberately
holds after a crash without a terminal fence, so item 1 must define the production
recovery contract before connecting the child. Checklist creation is complete;
software verification, supervised live acceptance and a later host watchdog remain open.
This update changes documentation only. The prior 1,412-test result below remains
the code evidence; no fresh runtime or account readiness is claimed.

## D-079 broad rewarded-market preparation implemented — 2026-09-22

The existing selector can now receive a broad exact universe instead of one
manual ticker. Public launch preparation joins active reward programs to full
market rules and one future primary milestone, then stores at most 1,024
candidates with 128 initial WebSocket books. The unchanged selector ranks fresh
book competition; the unchanged entry cap is 30. Cheap density remains only a
head/tail exploration hint. Automatic preparation initially excluded all
early-closing markets and resolves milestone uniqueness before its T-5 cutoff.
D-082 above now admits only the reviewed scheduled-release subset while retaining
the unknown-rule exclusion.

A pre-fix credential-free refresh prepared 1,024 candidates from 4,759 program
rows and 4,753 matching markets, with 3,228 future milestones inspected. That
unsafe ignored input was superseded by D-082's current validated scope. No bot,
account signer or mutation endpoint was started. [Build record and boundaries](docs/BUILD_AUTOMATIC_CANDIDATES.md).
Full suite: 1,412 run / 1,411 passed / one expected Windows privilege skip.
Existing 30/120-market tracker and admission resource gates pass.

## D-078 automatic selection integrated and verified — 2026-09-22

The actual launcher now attaches the existing admission owner. Reviewed
candidates can enter subscriptions beyond an optional initial seed set; exact
timing reviews survive rotation and the existing metadata service checks current
rules, fees and deadlines before ranking/dispatch. Skip diagnostics are bounded
and explicit. Unknown timing is never inferred from expiry. Working orders,
inventory, pending activity and all trading limits remain protected.

At D-078 publication the ignored inputs contained one reviewed market. D-079
subsequently replaces that operational bottleneck with bounded automatic
preparation; no running process was changed. Component wiring and a prepared
scope are not venue-wide approval or live profitability evidence.
[Build and verification record](docs/BUILD_LIVE_SELECTION.md).
Final full suite: 1,401 run / 1,400 passed / one expected Windows privilege skip
in 216.316s. Ten repeated composed discovery cases and 30/120-market resource
gates pass. Review, documentation links and private-file checks pass.

## D-077 original runtime connected; not yet live — 2026-09-22

The original runtime now has an explicit non-fixture execution composition,
foreground Windows launcher and drain request. Ranking, account release, write
quota, durable pair dispatch and the V2 transport are connected. Fill/book/timer
events queue the existing passive/IOC exits. No alternative canary is the launch
path. See [operation and remaining inputs](docs/RUN_LIQUIDITY_BOT.md).

Synthetic verification reaches a two-order ACK through the complete composed
runtime, with real local accounting and fake wires only. Separate regressions
cover partial-fill reducers, cancellation priority, IOC, paused entries and
missing cash proof. Real GET/WebSocket startup checks connect books, private
channels, lifecycle, metadata, catalog and quota; they do not place orders or
approve a production opening baseline.

**Prepared for an explicit operator launch, not yet trading:** the ignored
`config/live-inputs.local.json` is installed for the currently reviewed
`KXAAAGASD-26SEP23-4.4750` scope. Its exact rules digest, exchange shard and
primary milestone binding passed the real metadata pipeline with no blockers.
The operator confirmed this is a personal account opened directly with Kalshi;
the conservative direct-member profile produced a $0.0276 per-contract taker-fee
bound. No production account ledger has been created and no live order was
submitted. First launch still requires the operator's explicit `-Initialize`
command, which captures and approves the fresh opening before any entry can pass.
Automatic supervisor restart and paid-reward reconciliation are not claimed by
this unit. Its admission omission is corrected by D-078 above.
Verification: full suite 1,384 run / 1,383 passed / one expected skip; final
launcher regressions 18/18; ten repeated synthetic compositions passed.
Read-only startup evidence and limits are recorded in the run guide. The selected
market's 15:15:51 UTC book produced a $1.06 remaining-reward estimate and $9.60
combined quoted collateral estimate; these are transient estimates, not payout
or profitability evidence.

## D-076 historical canary — superseded; not a launch path

[Implemented and verified](docs/BUILD_LIVE_CANARY.md): a separate one-market
canary can prepare one fresh, exact two-sided post-only size-10 quote and monitor
it for at most six hours. It requires a flat account, current eligible program,
fixed book/rules, an estimated $1 minimum and an exact run-ID confirmation. The
single-use mutation capability is bound to the full two-order request digest;
first fill or planned end triggers cancellation of acknowledged orders.

Fresh read-only evidence found $500.4268 cash, zero positions/orders and one
same-day candidate with $9.60 maximum combined cost, $7.10 maximum one-sided
loss and $1.49 estimated reward. That preview expired; **no live order was
submitted**. The earlier count should read 1,367 tests run, 1,366 passed and one
skip. Its two wall-clock-dependent tests were subsequently fixed. D-077 retires
submission via this separate path; the rest of this section is historical.

## D-075 offline supervised runtime/recovery fence — 2026-09-22

[Implemented and verified](docs/BUILD_WINDOWS_SUPERVISOR_S2B.md): the fixed
native child can now own a disposable injected `RecoveryRuntime`, apply persisted
restrictions before any fake read, drain readers/writer on stop and transfer a
bounded transactional terminal fence. Unknown death, missing terminal checkpoint,
exhaustion/cooldown and cross-session clock uncertainty remain durable holds;
tokens/source proof never restore. Explicit resolution is current-revision,
childless and scoped.

58 focused supervisor tests pass with one expected privilege skip; 112 runtime/
continuity/dispatch/quota regressions pass. The 30/120-market S2B resource fixture
passes its loop/memory/owner/drain targets. Final suite: 1,362 run in 199.588
seconds, 1,361 passed and one expected skip. No credentials, network, bot start,
order, configuration or deployment occurred. Remaining: member fee-profile
evidence and the fee-bound decision, selected-market timing reviews, launch-
boundary account proof, integrated readiness review and separate live-start
authority.

## D-074 supervisor resource clearance and quota evidence — 2026-09-22

[Implemented and verified](docs/BUILD_WINDOWS_SUPERVISOR_RESOURCE_FIXES.md):
retained, non-delete-sharing WAL/SHM handles remove repeated path work while
preserving exact DACL validation; host timer ticks coalesce only materially idle
results after full clock/policy evaluation. The native 60-second/100-cycle
acceptance now passes every target: parent CPU 0.781%, loop p99 16.048 ms,
39,587,840 added bytes, backlog 1 and warmed handle/thread deltas -2/-2/0.

114 focused S1/S2 tests pass with one expected privilege skip; 67 write/quota
and 11 entry-dispatch checks pass. Final complete suite: 1,352 run in 188.770
seconds, 1,351 passed and one expected privilege skip. A separately
authorized bounded read-only quota verification returned HTTP 200 and validated: Basic read
200/600, write 100/100, default cost 10, 17 overrides and no grants. Current
colon/wildcard route syntax now validates; single cancel costs 2 while supported
creates and quota-control reads fall back to 10. Fee-member profile and selected-market
timing reviews remain unknown; launch-boundary account evidence and S2B remain
required. Current fee guidance also makes the old per-fragment balance-rounding
bound overly pessimistic; it remains safe and unchanged pending an explicit
reviewed fee-bound decision. No bot, order endpoint, configuration, deployment
or restart occurred.

## D-073 reward reflection/checkpoint lifecycle — 2026-09-22

[Implemented execution-disabled](docs/BUILD_REWARD_REFLECTION.md): the tracker now
uses one bounded account-wide queue-position read to join exact resting-order
identity to fresh private account and aggregate WebSocket book evidence. The
runtime owns load-before-observation, periodic atomic checkpointing, stop, final
flush and service failure propagation. Any mismatch/race/staleness remains
UNKNOWN; estimates are not paid rewards or trading authority.

47 reward/reflection tests and 196 focused integration tests pass. Final full
suite: 1,347 run in 171.937 seconds, 1,346 passed and one expected Windows
privilege skip. The existing 30/120-market reward resource gates pass; disabled
preflight remains expected exit 2 and `live_ready=false`. Diff, documentation,
secret and publication checks are recorded in the build record. No credentials,
account/venue request, bot operation or live mutation occurred. Next: real
fee/timing/account/quota input verification, then native supervisor/readiness.

## D-072 entry-pair dispatch and mutation transport — 2026-09-22

[Implemented execution-disabled](docs/BUILD_ENTRY_DISPATCH_TRANSPORT.md): current
ranked additions now become an exact two-leg writer reservation and one guarded
V2 batch create. The same bounded adapter covers existing single reducer creates
and cancels. Source/accounting/quota proof is rechecked at the send edge; batch
cost is charged per leg to the unscoped bucket. Partial, unidentified and
uncertain results persist conservatively, trigger recovery and never retry.

Final full suite: 1,339 run, 1,338 passed, one expected Windows privilege skip.
11 entry/transport checks, 65 dispatcher checks, 35 write-budget checks and
30/120-pair resource gates pass. Disabled preflight remains `live_ready=false`.
No credentials, venue/account request, bot operation or live mutation occurred.
Next: production reward reflection/checkpoint lifecycle (#3), then remaining
real-input, native-supervisor and readiness/launch gates.

## D-071 automatic market admission/rotation — 2026-09-21

[Implemented offline](docs/BUILD_MARKET_ADMISSION.md): one supervised admission
service now connects candidates to real runtime book-scope replacement and fresh
ranking. It joins one old reader, rechecks exact flat/clear ownership, changes
bounded scope and requires new snapshots. Account/lifecycle readers are not
restarted. Inventory, orders, unresolved exits/fills and uncertain scope remain
protected. Order/cash limits still belong to the existing selector/writer.

31 focused tests and 30/120-market scope-commit resource checks pass. Review
closed a late-commit cancellation race with a failing in-memory negative control.
Final full suite: 1,327 run, 1,326 passed, one expected Windows privilege skip.
Diff/documentation checks pass; detailed scope and evidence are in the build record.
No credentials, venue/account request, live order, bot operation or risk change.
Live execution remains disabled. Next: source-bound entry-pair dispatch and
production order transport (#2); reward reflection/checkpoint lifecycle and
remaining supervisor/readiness work are separate queued milestones.

## D-070 Poly-style discovery and per-program estimates — 2026-09-21

[Implemented offline](docs/BUILD_REWARD_TRACKER.md): bounded ranked-head/rotating-tail
candidate planning, protected owners and stable fresh incumbents, with no fixed
60-market pool. Existing 10-contract/30-resting-entry and financial limits remain.
The actual-order tracker separates program IDs, estimated accrual, qualifying
time, unknown gaps and estimated time to $1. Explicit atomic checkpoints preserve
totals, not live source proof; runtime dirty-market observations reuse existing
inputs and shared validation. Telemetry exhaustion reports a fault without
interrupting inventory management. Final full suite: 1,296 run, 1,295 passed,
one expected Windows privilege skip. Focused/resource, diff and documentation
checks pass; disabled preflight remains `live_ready=false`.

This completes the offline component, not automatic live rotation or verified
earnings. Production own-order/public-book reflection remains unproved; owned
orders therefore report UNKNOWN outside explicit fixtures. Next: inventory-safe
subscription admission, entry-pair dispatch and explicit checkpoint lifecycle
wiring in the future supervised runtime. No account calls or live operations.
Verification scope and remaining integration are recorded in the build document.

## Priority 5 incentive discovery/refresh — 2026-09-21

[Bounded catalog integration](docs/BUILD_INCENTIVE_DISCOVERY.md) connects one
runtime-owned refresh service to the existing advisory selector and shared
read budget. Complete pagination, source/expiry fences, per-market unsupported
input exclusion, bounded retries and joined shutdown are implemented offline.
26 focused tests and the 5k/10k-catalog resource gates pass. Final full suite:
1,247 run, 1,246 passed, one expected Windows privilege skip. Review, documentation
and secret checks pass; disabled preflight remains `live_ready=false`.
No venue/account request, credentials, bot operation or risk change occurred.

Next: inventory-safe subscription rotation/admission, verified working-order
reflection and source-bound entry-pair dispatch. These and runtime/readiness
gates still prevent claiming a finished live trader. Live execution is disabled.

## D-069 reward-aware selection component — 2026-09-21

[Implementation and verification](docs/BUILD_MARKET_SELECTION.md) adds hourly
reward/capital-efficiency selection, current-quote qualification diagnostics,
entry-horizon projections, conservative whole-pair budgets and retained owners.
An explicit offline runtime attachment reuses existing dirty-book and inventory
observations; no extra per-tick portfolio reads or venue traffic. 42 focused
tests and representative 30/120-market resource gates pass. Full suite: 1,221
run, 1,220 passed, one expected Windows privilege skip; disabled preflight
remains `live_ready=false`. Live execution remains disabled.

Priority 5 is not fully connected: discovery/refresh is now connected above;
rotating subscription admission, verified resting-order reflection and entry
dispatch handoff remain. No new policy approval is needed to repeat this
accepted selection direction; new repricing thresholds/live activation are
separate. Existing runtime/readiness blockers remain.

## Priority 5 ranking reference audit — 2026-09-21

[Polymarket code audit and Kalshi adaptation](docs/POLYMARKET_RANKING_AUDIT.md)
is complete: 56 Poly selection and 68 Kalshi engine tests pass offline. Reuse
bounded discovery, fresh shortlist checks and inventory-safe ownership; retain
Kalshi's own scoring. Proposed hourly-reward-first admission, capital-efficiency
tie-break and stable incumbents await the operator's policy decision. No ranking
integration, bot/configuration change or live action occurred. Priority 5 and
the previously recorded runtime/readiness gates remain unfinished.

## Priority 4 supervised injected dispatch lifecycle — 2026-09-21

[Lifecycle integration](docs/BUILD_DISPATCH_LIFECYCLE.md) connects the injected
dispatcher to the existing runtime task supervisor. Event-driven, bounded keys;
one writing operation; no idle polling or blind retries. Stop fences new work
synchronously, drains accepted outcomes before reader teardown, and returns
only after owned tasks finish. Fresh runtime/ledger reopen preserves UNKNOWN
and held capacity without replay. No automatic restart/re-arm of failed owners.

23 focused lifecycle tests and 30/120-market resource scopes pass; full suite
1,179 run, 1,178 passed, one expected Windows privilege skip. Evidence is in the
build record. This completes the assigned offline lifecycle
piece, not a live trader or native S2B process integration. Next: priority 5
reward ranking/admission; then priority 6 runtime/readiness acceptance. Real
quota/fee inputs, process-supervisor gates and launch approval remain. No account
calls, secrets, bot operation, deployment or live-order changes.

## Priority 4 owned write outcomes — 2026-09-21

The [outcome/recovery handoff](docs/BUILD_MUTATION_OUTCOMES.md) now pauses the
original write shard on an injected HTTP 429, revokes stale account/plan proof
and signals the existing recovery owner before and after durable recording.
Failed writes retain UNKNOWN/capacity holds; no automatic retry or resume.
Cancel ACK is still not terminal evidence. Cancellation waits preserve ownership
without leaking worker exceptions through Python's default loop logger.

This is the bounded offline outcome-handling milestone, not completion of
priority 4 or trading readiness. Full suite: 1,156 run, 1,155 passed, one expected
Windows privilege skip; focused and both resource scopes passed. Details are
recorded in the build record.
Next: supervised dispatcher lifecycle/end-to-end shutdown; then ranking/admission
and final runtime readiness. Real quota/fee inputs and launch approval remain
required. No account calls, credentials, bot operation or live orders.

## Priority 4 shared write-quota ingestion — 2026-09-21

The [write-quota source](docs/BUILD_WRITE_QUOTA_SOURCE.md) now consumes the
existing guarded REST document pair and feeds the injected dispatcher. Full
method-specific costs, source identity, grant/TTL expiry and owner clocks remain
binding at submission. Refresh revokes old permits, starts empty and preserves
shard cooldowns. No additional poller or per-market quota requests.

Offline component only: real account quota/probe policy and member fee-profile
evidence are still unverified. Next implementation: owned write-429/outcome
recovery and supervised lifecycle; fee readiness, ranking/admission and launch
gates remain. No credentials, account requests, trading, bot start or restart.
Final verification: 1,130 tests run, 1,129 passed, one expected Windows privilege
skip; 28 new source/dispatcher tests and both resource scopes passed. Details
are in the build record.

## Priority 4 source-bound inventory dispatch — 2026-09-21

The [candidate/dispatch integration](docs/BUILD_DISPATCH_SOURCES.md) now uses
actual account, book, inventory-plan and writer owners for safety cancels,
exact passive reducers and due IOC reducers. Source proof is rechecked through
the final injected send edge; shutdown cannot start a late mutation. Cancel
ACK/unknown results still require reconciliation. One writing task and one
pinned proof; no new REST polling or live transport.

This completes the bounded offline candidate-production slice, not priority 4
as a whole or trading readiness. Remaining: verified live fee metadata and
quota ingestion, owned 429/outcome recovery and supervised dispatch lifecycle;
then ranking/admission and runtime readiness. Tests, resource measurements and
review evidence are recorded in the build link: final full suite 1,102 run,
1,101 passed, one expected Windows privilege skip; 42 focused tests and both
resource scopes passed. Live execution remains disabled;
no credentials, account requests, bot operation or live orders were involved.

## D-068 operational reconciliation release — 2026-09-21

The operator accepted the Polymarket-style approach. The implemented
[release path](docs/BUILD_ACCOUNT_RECONCILIATION.md) joins existing recovery,
exact owned orders/fills, an explicitly approved flat-opening cash baseline,
bounded history and the active private epoch. Only temporary observation/source
holds can clear. Five-second revocable leases gate reservation, queued SENDING
and the final injected send edge. Restart never restores a lease; settlements,
conflicting economics and unattributed funding remain held. New schema-5
ledgers only; existing schemas are refused without migration.

Cash uses independent venue/local ceilings per account and exchange, actual
owned fill costs/fees and conservative working obligations. This completes the
offline accounting release component, not a live trader. Global venue handoff
remains unproved by design; D-068 accepts the residual common-delay risk.
No real boundary was approved, existing ledger opened, venue contacted, bot
started/restarted or live order changed. Verification and its limits are in the
build record. Next: source-bound production candidate/dispatch integration,
then ranking/admission and supervised runtime readiness.

Verification: 1,074 tests run, 1,073 passed, one expected Windows
privilege skip; after the final command guard, focused release/handoff tests
53/53 passed (full suite not repeated after that guard). All declared synthetic
30/120-market resource bounds passed. Disabled preflight returned native exit 2.

## D-067 durable accounting enforcement — prior step, extended by D-068

The writer now retains an immutable opening candidate, separate cash/funding/
settlement observations and persistent restrictions in fresh schema-4 ledgers.
An explicit account-owner reconciliation operation joins reads, normalization
and durable capture; stale sources retain positive settlement evidence but
cannot create the candidate. Entry reservation and prepared entry sending
check restrictions inside the writer transaction. Cancels/reducers retain
their own safety rules. Cross-boundary/undated fills are quarantined outside
matched P&L; rejected financial evidence leaves a restriction across restart.
No existing ledger was migrated or opened. No account/credential/trading action.

Source completeness is still unproved: there is no verified shared REST/WS
barrier or cash-hold mapping, no approved launch boundary and no reconciliation
that permits releasing these restrictions. A review acknowledgement does not
clear them. The [build record](docs/BUILD_DURABLE_ACCOUNTING.md) distinguishes
implemented enforcement from external readiness gates. The full suite ran
1,046 tests: 1,045 passed and one expected Windows privilege skip. After adding
a reducer-path regression, all 48 durable-accounting/command-handoff tests
passed. Synthetic resource budgets passed; disabled preflight returned native
exit 2 with no files, credentials or network access. Scoped diff review passed.

## D-066 settlement safety policy — historical step, superseded by D-067

The operator approved pausing new entries for unexpected settlement of a
bot-owned open position pending reconciliation. The offline opening assessment
now explicitly marks observed settlements after its proposed boundary for
reconciliation; it assigns no settlement P&L and never releases a hold. This is
not a durable runtime pause or proof of bot ownership. Fresh opening checkpoint,
event handoff and durable hold/release integration remain unbuilt. Live trading
stays disabled. Focused opening tests pass 25/25. The full suite ran 1,024
tests: 1,023 passed and one expected Windows privilege skip. The 128/4,096/
50,000-row opening benchmark passed all declared bounds. Native preflight
exited 2 with `live_ready=false` and reported no file creation, credential
access or network access.

## Priority-3 opening accounting update — 2026-09-21

The first offline accounting slice is a pure, non-authorizing assessment of
the existing opening evidence. It distinguishes a locally flat primary account
candidate from cash agreement and retains settlement/cash activity counts and
every blocker. No checkpoint, settlement P&L, correction, cash/hold authority
or live entry path was added. The design was cross-checked against the actual
Polymarket source; its venue-specific rules were not imported. Focused opening
tests pass (23/23). The full suite ran 1,022 tests: 1,021 passed and one
expected Windows symlink-privilege skip. The 128/4,096/50,000-row opening
benchmark met all declared bounds. Native disabled preflight exited 2 with
`live_ready=false`, no file creation, credential access or network access.
The settlement loss-meter choice and exact opening boundary remain undecided.
Live trading remains disabled.

## Current update — 2026-09-21

D-065 now requires verification, scoped diff/secret review, commit, push and
parity check for each completed work unit. This changes repository publication
only; live operation remains disabled.

Latest offline correction: the injected write dispatcher now holds its permit
through durable SENDING and consumes it synchronously at the send edge.
Synthetic quota expiry during that handoff makes no transport call, records
UNKNOWN and holds the owner for reconciliation; expiry before SENDING remains
NOT_SENT. An asynchronous send-edge callback is rejected before SENDING. The
final focused run passed 48 tests. The complete suite ran
**1,018 tests: 1,017 passed, one expected Windows symlink-privilege skip** in
129.871s on the D-065 publication candidate. Disabled preflight remains
`live_ready=false`, native exit 2, with
no file creation, credentials or network. This is offline-only and does not
clear opening-account, dispatch, ranking, supervisor or live gates.

D-063 restores single-session development. All delegated workers are stopped;
the primary session completed their partial handoffs. No new workers or model
switches unless explicitly requested again.

D-064 selects the primary Kalshi account (subaccount 0) for exclusive bot use,
with no nonzero positions or resting orders permitted before arming.
This is an operator policy, not current account proof or live authorization.
The exact boundary remains unchosen until a separately approved launch.

D-062 continues the remaining review priorities. Priority 3 now has a bounded
[opening-account/cash evidence reader](docs/BUILD_OPENING_ACCOUNT_CASH_EVIDENCE.md):
scope/query-bound histories, precise cash, revision fences, retained inspection
ownership and 512-row off-loop normalization. Latest complete-suite verification:
**1,015 run, 1,014 pass, one expected native symlink-privilege skip** in
134.201s, including D-064's primary/flat-policy tests.
Preflight stays disabled and side-effect-free.
The old pending/undated cash finding is fixed and independent evidence-only
review cleared it. Primary review/test coverage finishes the batching delta.
Maximum-history normalization again passes the bounded resource fixture: 50,000
rows, loop p99 11.334 ms, maximum 40.203 ms. Priority 3 still needs a fresh
flat-account verification, exact launch boundary and durable cash/settlement/
basis contracts. No baseline or entry authority is installed. Priority 4's
[offline write budget](docs/BUILD_WRITE_BUDGET.md)
and [bounded cancel/reducer dispatcher](docs/BUILD_WRITE_DISPATCHER.md) now pass
45 focused tests. Five-sample 30/120-shard CPU/allocation fixtures pass their
predeclared targets; 12,000 commands max 187.5 ms CPU and 22,572 B peak.
The dispatcher uses injected candidates, the durable writer and its sole
offline executor; it is not attached to recovery runtime or venue transport.
Production mutation authority, ranking/admission and supervised runtime remain
unfinished.
At the time of the D-062 build, no live operation, account call, credential
access, configuration change, deployment, restart, commit or push occurred.
The later D-065 publication rule supersedes that historical no-push boundary.

### Priorities 1/2 — completed offline

R1-R6 from the [independent D-060 review](docs/REVIEW_D060_ASTRA.md) are corrected
offline; [evidence](docs/BUILD_COMMAND_CAPACITY_REVIEW_FIXES.md). Durable issuing
identity, canonical dispatch terms, authoritative reducer eligibility/routing,
bounded proven-unsent reauthorization, immediate post-SENDING recovery holds and
constant-time hot capacity counters now close overall-review priorities 1/2 in
the offline component. A post-prepare authority recheck also durably aborts a
reducer if account, book, or management state changes while queued. Focused
**258** and complete **950** tests pass (one
existing native symlink-privilege skip). Correct complete-history 30/120-market
benchmarks pass after fixture self-audit; worst retained-history CPU growth is
**1.429x**, backlog 1.
Disabled preflight remains exit 2 and side-effect-free. D-061 supersedes mandatory
model recommendations/switches. No account/credential/network/live action,
migration, configuration, deployment, restart, commit or push occurred. Opening
account/continuity and cash contracts are the next overall priority; all live
readiness gates remain closed.

### D-060 implementation evidence before independent review

D-060 implements the approved [D-059 command-capacity and atomic-handoff design](docs/DESIGN_COMMAND_CAPACITY_HANDOFF.md)
in offline, execution-disabled scope. Schema 3, durable capacity credits, funded
safety cancellations, atomic risk/intent/PREPARED receipts and single-use
dispatch consumption are present; schema 2 is refused without migration. The
[build evidence](docs/BUILD_COMMAND_CAPACITY_HANDOFF.md) records 21 new focused
tests, 244 impacted tests, and the complete **936-test run: 935 passed, one
existing native symlink-privilege skip**. Original resource cases reported pass,
but the independent review above invalidates their acceptance fixture; disabled
preflight remains side-effect-free. No risk/config/live transport/runtime/account
state changed. Account proof, production dispatch/exits, archive policy,
ranking/allocation and S2A/S2B gates remain open.

### D-058 overall review before D-059 planning

Previous D-057 work is committed locally as `8c03aa0`; no push. The operator
authorized Astra for this commit and the requested overall review (D-058).
[Overall code triage](docs/REVIEW_OVERALL_2026-09-21.md) reproduces two pre-live
integration/capacity problems: a full mutation journal refuses safety cancels,
and chaining risk reservation into execution double-reserves and faults the
writer. It also orders the remaining account-proof, exit/write-dispatch,
ranking/allocation and supervised-runtime work. Fresh targeted verification:
267 tests pass, two in-memory probes reproduce, disabled preflight stays
side-effect-free. No bot source/config/runtime change. This is not exhaustive
D-057 clearance; its independent review/resource gates and S2B block remain.
Review/handoff Markdown is local and uncommitted. Next recommendation: Astra
for a bounded design of the two order-lifecycle findings, only on assignment.

### D-057 implementation evidence before overall triage

D-057 implements the [S2A review corrections](docs/BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md)
under the operator's explicit Astra fix-phase exception. Retained ownership,
affirmative launch permission, terminal IPC completion, child protocol/power
validation, protected control files, bounded diagnostics and journal pruning are
corrected with 30 new regressions. Complete suite: **915 run, 914 passed, one
native symlink-privilege skip, 114.296 seconds**. Three safeguard reversals detect
their defects; credential-free preflight remains disabled, expected exit 2, with
no side effects. The 100-cycle ownership/retention assertions pass, but corrected
idle parent CPU is **2.135% of one core against <1%**; cold-baseline +13 handles
also remain unattributed. Memory and loop-latency targets pass in the inert scope.
**Independent Astra review and focused resource follow-up are next; S2B remains
blocked.** No live runtime/configuration/account use,
deployment or restart. Changes are local and uncommitted.

### D-056 review before D-057 corrections

D-056 [independent Astra review](docs/REVIEW_D056_ASTRA.md) requires changes
before S2B. Native probes reproduce lost ownership on repeated cancellation or
malformed messages, premature cold-parent completion, spawn after policy denial,
lost terminal IPC frames, missing child envelope validation, a setup-handle leak
and unbounded session history. Source review also identifies missing child/power
invalidation, persistent-file protection and bounded diagnostics. All 81 existing
focused tests pass (12.268 seconds); disabled preflight remains side-effect-free.
The 885-test and resource numbers below are historical Sol evidence, not review
clearance. **STOP under D-049. Recommended next agent: 5.6 Sol for the bounded
R1-R8 corrections and verification in the review.** No S2B or live authority.
Review/handoff documentation is local and uncommitted; source/config unchanged.

### D-056 implementation evidence before independent review

D-056 implements the approved D-055 S2A inert-process foundation; see
[build evidence](docs/BUILD_WINDOWS_SUPERVISOR_S2A.md). Protected account-scoped
Windows role objects, one thread-owned control mutex, inherited child/stop/parent
handles, transactional reservations, strict bounded named-pipe IPC, a fixed inert
child and retained fail-closed shutdown are present. Native acceptance tests cover
duplicate ownership, abandoned control, DACL squatting, crash/hang, parent death,
cold orphan release and exact stop/exit behavior. The 60-second/100-cycle resource
fixture passes all targets: parent CPU 0.990%, event-loop p99 16.372 ms, added
working set 34,140,160 bytes, backlog 1, no retained supervisor thread and handle
delta -2. All 81 focused and 885 complete tests pass; the crash race passes
10/10 repeated runs, and disabled preflight remains side-effect-free. **STOP for independent Astra review under D-049. Recommended agent:
Astra.** S2B, production runtime/CLI/service integration and all live operation
remain unimplemented and unauthorized.

### D-048 review before S2 design

D-048 [independent Astra review](docs/REVIEW_D048_ASTRA.md) clears D-047 R1
with no new blocking findings. All 868 full tests pass (79.456 seconds), plus
205 targeted tests, nine repeated shutdown regressions and two independent
writer-failure/cancellation probes. Preflight remains disabled with no side
effects. D-048 and supervisor S1 prerequisite reviews are now complete; S2 is
still unbuilt and requires separate assignment. **STOP under D-049.** Next
recommended agent: Astra for detailed native S2 ownership/IPC design on operator
assignment, then Sol implementation after approval. Local review docs remain
uncommitted; no code, configuration, runtime or live action changed.

### D-054 review before the separate D-048 review

D-054 [independent Astra review](docs/REVIEW_D054_ASTRA.md) clears both D-053
clock findings with no new blocking findings in the execution-disabled S1 diff.
All 64 focused and 868 full tests pass (full: 78.100 seconds); 48 additional
failure-sequence cases pass and four regressions detect the parent defects.
Disabled preflight remains exit 2 with no side effects. Supervisor S1 review is
complete, not production readiness. **STOP under D-049.** Next recommended
agent: Astra for the separate D-048 review, on operator assignment. S2 remains
unbuilt and needs D-048 clearance plus separate assignment. Only local review/
handoff documents changed; no runtime, configuration or live action.

### D-054 implementation evidence before Astra review

D-054 implements both findings from the D-053
[Astra review](docs/REVIEW_D053_ASTRA.md); see
[build evidence](docs/BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md). Local clock
trust failure now enters a durable hold before stale child filtering while the
ignored payload remains labeled stale. Default continuity retains one persisted
boot estimate when wall/monotonic deltas agree within tolerance; small sampling
jitter no longer creates a boot change, while real discontinuities fail closed.
All 64 focused and exact 868 full tests pass (full: 76.297 seconds), including
10/10 focused repeats and four parent-code counterfactual detections. Resource
and disabled-preflight checks pass. **STOP for independent Astra re-review under
D-049.** S2 and D-048 remain gated. No runtime, configuration or live action.

### D-053 Astra review before D-054 fixes

D-053 [independent Astra review](docs/REVIEW_D053_ASTRA.md) requires two P2
clock fixes: stale child events can consume a detected clock discontinuity
without retaining a hold, and the default boot estimator can falsely disarm on
two milliseconds of sampling skew. D-052 R1/R2/R3/R5 are cleared within S1;
R4 remains partly open. All 59 focused and 863 full tests pass (full: 79.900
seconds); additional disposable-store probes reproduce both gaps. Preflight
remains disabled with no side effects. This records the review-time state at
`b051067`; D-054 above implements both requested fixes. S2 and D-048 remain gated.

### D-053 implementation evidence before Astra review

D-053 implements all five findings from the D-052
[Astra re-review](docs/REVIEW_D052_ASTRA.md); see
[build evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md). Every STOP
now advances the control generation; prior-state deadlines win over late status;
failed-spawn release preserves attention; a transactional shared clock checkpoint
detects wall/boot/monotonic discontinuity; and child events require complete
identity. All 59 focused and exact 863 full tests pass (full: 79.164 seconds),
including 10/10 focused repeats. The persisted-work benchmark and disabled
preflight pass. **STOP for independent Astra re-review under D-049.** S2 and the
separate D-048 review remain gated. No runtime, configuration or live action.

### D-052 Astra re-review before D-053 fixes

D-052 [independent Astra re-review](docs/REVIEW_D052_ASTRA.md) requires changes:
four P2 findings in repeated-stop fencing, status/deadline ordering and health
reset, failed-spawn finalization, and clock continuity across store instances;
one P3 finding accepts child results without identity. All five reproduce
offline despite 46 focused and 850 full tests passing (full: 79.093 seconds).
Original D-051 R4/R6/R7 are cleared within S1; R1/R2/R3/R5 remain partly open.
Disabled preflight stays exit 2 with no side effects. STOP for the operator's
5.6 Sol switch and documented R1-R5 fixes under D-049. S2 and D-048 remain
gated. This records the review-time state at `7bf5241`; D-053 above implements
the requested fixes.

### D-052 implementation evidence before re-review

D-052 implements R1-R7 from the D-051
[independent Astra review](docs/REVIEW_D051_ASTRA.md); see the
[review-fix evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md). Trusted
monotonic-normalized control time, strict lifecycle transitions, bounded useful-
progress deadlines, persistent explicit retry holds, absolute startup timing,
truthful process-exit/cleanup evidence and a real journal workload now replace
the reviewed behavior. All 46 focused and exact 850 full tests pass; focused
tests also pass 10/10 repeated runs. The 60-second fixture performs 124 persisted
policy events at 0.3385% of one core. Disabled preflight remains exit 2 with no
files, credentials or network. STOP for Astra re-review under D-049. S2 and the
separate D-048 review remain outstanding; no runtime or live action was added.

### D-051 Astra review before D-052 fixes

The review reproduced six P2 control/recovery findings and one P3 resource-
verification finding against `7b8d6cd`, despite 32 focused and 836 full passing
tests. Its report remains the acceptance source for D-052 and records the
original evidence; it is not a claim about the corrected working tree.

### D-051 implementation evidence before review

D-051 implements the approved D-050 supervisor S1 foundation; see
[build evidence](docs/BUILD_WINDOWS_SUPERVISOR_S1.md). Immutable execution-
disabled policy and a separate transactional SQLite control journal now cover
durable stop/generation state, stale children, attempt-before-spawn ordering,
bounded backoff/retries, useful-progress health and fail-closed outcomes. All 32
focused and exact 836 full tests pass; the 30/120-market and 60-second idle
resource fixtures and disabled preflight pass. No process launcher, runtime
wiring, service/task, credential/network access or live action was added. STOP
for independent Astra review. D-048's separate review remains pending before
S2/runtime integration.

### Prior D-050 supervisor design

D-050 [native Windows proposal](docs/DESIGN_WINDOWS_SUPERVISOR.md) traced
Polymarket source at `c5029321`; six isolated host-recovery tests passed. The
operator approved its S1 design through “Implement.” D-051 above implements only
the offline policy/control foundation, not deployment or live auto-resume.

### Prior D-049 workflow update

D-049 records the operator's permanent usage-efficient two-model workflow.
`AI_OPERATOR.md` is canonical: every substantive task starts with one short
Astra/Sol recommendation; Sol is the default, Astra is reserved for material
design/uncertainty/risk and meaningful live-money review, and mismatches stop
before development. D-037 is superseded where routing differs. Documentation
only; bot logic, configuration, data and runtime state are unchanged. D-050 above
now takes design priority; D-048 independent Astra review is still outstanding.

### D-048 implementation awaiting Astra review

D-048 Sol implemented the P2 fix from the D-047
[Astra review](docs/REVIEW_D047_ASTRA.md); see
[build evidence](docs/BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md). Each connection
now retains one finalizer through stop/repeated cancellation until its reader is
joined, valid tail fills are durable, the marker is closed and gaps are refreshed.
Three new regressions cover real transport queue/byte accounting, ordinary stop,
caller cancellation and marker-close cancellation. All 231 focused and exact
804 full tests pass; continuity/history resource checks and disabled preflight
pass. STOP for Astra review under D-049. Venue handoff, starting basis, Phase
2/3 and trading remain unauthorized.

### D-047 Astra review before finalizer fix

D-047 [Astra review](docs/REVIEW_D047_ASTRA.md) requires one P2 follow-up:
runtime shutdown cancels a connection already draining after a disconnect,
leaving a valid tail fill queued and an open epoch with a stale gap cache.
The real WebSocket consumer reproduces this 3/3 times on ordinary stop and
3/3 on caller cancellation. Both exact D-046 reproductions are fixed, and the
three new tests detect the previous implementation's defects. All 228 focused
tests and native disabled preflight pass; the full suite/resource results below
remain Sol's evidence. Only review/handoff documents changed. STOP for the
operator's Sol switch and R1 fixes under D-037. Trading remains disabled.

### D-047 implementation evidence before independent review

D-047 Sol implemented both P2 fixes from the D-046
[Astra re-review](docs/REVIEW_D046_ASTRA.md); see
[build evidence](docs/BUILD_ACCOUNT_CONTINUITY_SHUTDOWN_FIXES.md). Repeated
caller cancellation cannot abandon the retained cleanup owner, account reader,
queued tail fill or marker. Malformed/staging failures no longer stop the bounded
drain before later valid fills and now make runtime shutdown fail visibly after
marker/gap reconciliation. All 199 focused and exact 801 full tests pass;
continuity/history resource checks and native disabled preflight pass. STOP for
Astra re-review under D-037. Venue handoff and starting basis remain unproven;
Phase 2/3 and trading remain unauthorized.

### D-046 re-review before shutdown fixes

D-046 [Astra re-review](docs/REVIEW_D046_ASTRA.md) clears original D-045 R2-R5
and verifies the immediate-stop fix, but leaves two P2 shutdown findings:
repeated cancellation can abandon the shielded reader; a malformed buffered
fill can abort draining before a valid tail fill, with the error swallowed by
shutdown. Both were reproduced offline. All 196 focused tests pass; actual
handshake-timeout and production-consumer queue probes verify the original
fixes, and the corrected benchmark/preflight pass. The 798-test full-suite
result below is Sol's evidence, not a rerun in this review. Only review/handoff
documents changed. STOP for the operator's Sol switch and fixes. Trading remains
disabled; Phase 1 shutdown delivery is not yet cleared.

### D-046 implementation evidence before re-review

D-046 Sol implemented all R1-R5 fixes from the D-045 independent
[Astra review](docs/REVIEW_D045_ASTRA.md); see
[build evidence](docs/BUILD_ACCOUNT_CONTINUITY_REVIEW_FIXES.md). Real queued and
in-flight fills are retained during bounded shutdown and invalidate clean local
delivery; accepted epoch-open cancellation is owned, closed and gap-reconciled;
quota-boundary status is coherent. The quota retention test now waits for its
legitimate callback turn, and reconnect work is inside resource instrumentation.
All 196 focused tests and the exact 798-test suite pass. The quota regression
passes 10/10 repetitions; continuity and inherited history resource fixtures
pass. Native preflight remains exit 2 and `live_ready=false` without files,
credentials or network. STOP for Astra re-review under D-037. Venue handoff,
starting basis, Phase 2/3 and all live actions remain unproven/unauthorized.

### D-045 independent review before fixes

D-045 independent [Astra review](docs/REVIEW_D045_ASTRA.md) requires changes:
R1 queued fills can be dropped during stop while recording a clean marker;
R2 a cancelled epoch-open acknowledgement can hide a durable gap until restart.
R3 is a stale status response, R4 an inherited quota-test callback scheduling
flake, and R5 an unmeasured reconnect-resource claim. Review reran 192 focused
tests and all 794 tests successfully, but additional probes reproduce R1-R3;
the original quota regression failed 10/10 isolated repetitions and passed
10/10 with a process-local callback-drain wait. Passing suites do not clear these
findings. Only review/handoff documents changed. STOP for the operator's
5.6 Sol switch and fixes; trading and Phases 2/3 remain unauthorized.

### D-045 implementation evidence before independent review

D-045 Sol implemented [evidence-only continuity Phase 1](docs/BUILD_ACCOUNT_CONTINUITY_PHASE1.md).
Durable local private-epoch markers, scoped baseline candidates, source-bound
assessment and position-stream/pagination safety are built. All 168 directly
affected tests pass. One earlier 792-test full-suite run passed, but the final
794-test run failed one pre-existing quota-supervisor weak-reference assertion,
reproduced in isolation; this is an open verification finding, not a cleared
suite. The 30/120-market continuity and inherited
128/4,096-row history resource fixtures pass. Native Windows preflight remains
`live_ready=false`, exit 2, without credentials/network/files. No actual
account read or trading. Venue REST/private-stream handoff and starting basis
remain unproven. STOP for independent Astra review of source and Git diff under
D-037; no Phase 2/3 or live authority.

### Prior D-044 design

D-044 Astra design is complete: [starting account/private-stream continuity](docs/DESIGN_ACCOUNT_CONTINUITY.md).
It specifies an evidence-only Phase 1, conditional venue handoff Phase 2 and
opening-account/cash Phase 3. Current Kalshi documentation does not establish a
shared REST/private-stream checkpoint or bounded late-fill publication; the
design therefore keeps all entry/live-readiness gates false. Official public
docs and current Kalshi/Polymarket source were reviewed; no source/tests were
changed or account/credential calls made. STOP for the operator to switch to
5.6 Sol and explicitly assign Phase 1 implementation under D-037. No live use.

### Prior D-043 publication

D-043: the canonical GitHub repository now holds the Windows project on its
default `master` branch. Its old tracked tree was replaced with 170 checked
source, test, config and documentation files. The obsolete divergent `main`
branch was retired after its history was merged into `master`; the old tips
remain recoverable in Git history. The active `C:/Users/rynna/Bots/kalshi`
folder is now a Git checkout tracking `origin/master`. Credentials, captured
data, backups, logs, virtual environments and machine-local transfer/deployment
state remain local and ignored. See `docs/GITHUB_PUBLICATION.md`. Repository
publication did not start the bot or change trading authority.

### Prior D-042 review

Astra D-042 re-review clears both P3 follow-ups with no new findings in scope.
All 62 focused quota tests pass (8.720s). Each new regression detects its old
defect in a process-local reversal; an additional probe verifies immutable
boundary state, preserved caller exception/traceback and pending timing.
See `docs/REVIEW_D042_ASTRA.md`. No source/test files changed during review.
The 778-test full suite and resource checks below are Sol's implementation
results, not reruns in that review. Git diff was unavailable at the time;
D-043 subsequently restored Git metadata in the active folder.
Next role: Astra design for the next selected milestone, then STOP for the
operator's Sol switch. Trading remains disabled.

### D-042 implementation evidence

D-042 Sol fixed both P3 follow-ups from Astra's D-041 re-review. Repeated
cancellation now reports `running=False` even if the shutdown join is interrupted;
the physical REST worker remains owned and its late 429 is applied. Pending
rollover stores only an immutable boundary record, not a caught exception or
response traceback. Two regressions were added. All 62 focused quota tests and
the exact 778-test full suite pass. Explicit/automatic 30/120 resource fixtures,
30/120 rollover stages and the ten-second idle check pass. See
`docs/BUILD_QUOTA_REVIEW_FOLLOWUPS.md`. No Git metadata/diff is available.
Independent Astra re-review above now clears these fixes. No live activation or
account use; production and launch gates remain open.

### Earlier review and implementation history

Astra D-041 re-review clears original D-039 R1-R3 in scope, with two P3 follow-ups:
repeated cancellation leaves running=True after drain, and the pending rollover
exception retains raw quota response frames. See `docs/REVIEW_D041_ASTRA.md`.
That review reran 60 focused tests (8.548s) and all 776 tests (67.355s), all passed.
Additional injected probes confirmed ownership/late-429 safety and both small
findings. No source/test fixes in review. STOP for the operator's Sol handoff for
the two follow-ups; no design change is required. Trading remains disabled.

D-041 Sol fixes implemented for D-039 review R1-R3 and the timeout test.
`docs/BUILD_QUOTA_REVIEW_FIXES.md` records source scope and verification.
60 focused quota tests pass (8.585s); the exact full suite passes: 776 tests in
65.657s. Explicit/automatic 30/120 read fixtures, new 30/120 grant-rollover
fixtures and ten-second idle check pass their declared bounds. Two in-memory
reversals were detected, then restored. No Git metadata/diff is available.
The independent review above now clears the original fixes and records two
low-priority follow-ups. No live activation or account use.

D-040 design clarification complete: `docs/DESIGN_QUOTA_REVIEW_FIXES.md` proposes
one bounded grant-boundary deferral, unchanged hard expiry, cancellation-safe
drain ownership, terminal waiter checks and deterministic timeout regressions.
That design has now been implemented under D-041 above. The original review
findings and its test timeout below describe the pre-fix state, not current
verification. Astra re-review is pending.

D-039: the operator explicitly requested implementation of BOTH D-038 phases.
Guarded quota leases, restricted same-bucket probes, automatic refresh ownership,
runtime/metadata/recovery holds and safe diagnostics are implemented, opt-in and
execution-disabled. See `docs/BUILD_QUOTA_FRESHNESS.md` for scope and evidence.
46 new focused tests pass. Both quota workloads (30/120, explicit/automatic),
the 10-second idle check and unchanged D-036 metadata/rate fixtures pass their
predeclared bounds. Two intentional in-memory guard reversals were detected.
Final exact complete suite: 762 tests passed in 64.218s after the last source/test
edit. Preflight remains live_ready=false, native exit 2, with no file creation,
credential access or network access. Git metadata/diff remains unavailable.
Prior Astra review: NOT CLEARED. Three reproduced P2 findings: normal finite-grant
rollover exhausts refresh, cancelled shutdown loses physical request ownership,
and a cooldown refresh waiter hangs on clock fault. The first is an inherited
design conflict. See `docs/REVIEW_D039_ASTRA.md` for evidence and acceptance.
This review's focused 46 tests pass (5.951s); the full 762-test run has one timeout
error (66.472s). The affected 31-test module passes on rerun (4.122s); scheduling
sensitivity is suspected, not confirmed. The all-pass result above is Sol's
prior D-039 run. D-041 fixes and current verification are recorded above.
No live activation, credentials/account calls,
orders, cancellations, ledger imports or Polymarket changes. Production probe
configuration, write limiting and complete account/launch proof remain missing.

D-037 is now the permanent development workflow: Astra design (NO implementation),
STOP for the operator to switch to 5.6 Sol, Sol implementation/tests, Astra review,
then Sol fixes preserving the architecture. See `AI_OPERATOR.md` for exact gates.
The operator switched to 5.6 Sol and all four Astra D-036 findings have been
implemented: retired metadata dependencies use unique revisions; background
reads leave admission room for critical GETs; new metadata generations use a
distinct shared-read scope; token heads wake when quota/priority changes.
`docs/REVIEW_D036_ASTRA.md` preserves the original evidence and acceptance checks.
Nine new regressions cover review replacement, shared milestones, pending old
loads/reconnect, background saturation, small admission caps, wire scoping,
quota changes and throttle extension. Focused input/scheduler/rate suites pass
(44/25/18 tests). Both 30/120 scheduler and token workload fixtures pass their
predeclared budgets. The exact final full suite passes: 716 tests in 56.393s.
Current review: Astra cleared R1-R4 with no new blocking findings in scope.
All 87 focused tests were rerun; a combined REST/service/scheduler reconnect probe
confirmed fresh generation data, no retry charge and clean shutdown. See
`docs/REVIEW_D036_ASTRA_R2.md`. The 716-test result above is Sol's prior full run,
not a new full-suite run during re-review. Subsequent quota-freshness implementation
is recorded above; independent review remains gated by D-037.

D-036 work already added bounded runtime-owned metadata scheduling and shared
read-rate improvements: quota-document refresh, account priority/background
headroom, endpoint costs, empty document-based token startup and final/late 429
pauses. The initial D-036 milestone had 24 scheduler and 13 rate tests, two
in-memory guard reversals and passing 30/120 resource fixtures. Astra
ran the prior 707-test baseline (54.564s) and reproduced four gaps. Sol's exact
final 716-test suite passes (56.393s) after the last source edit. Git metadata remains
unavailable, so no Git diff/commit coverage is claimed. Preserve all existing work.

Preflight still reports live_ready=false (native exit 2). No keys/account calls,
live sockets/orders/cancels, risk changes, launch boundary, old-ledger imports or
Polymarket changes. D-039 now supplies optional automatic quota freshness/grant
expiry enforcement; production write limiting remains unimplemented. See
`docs/BUILD_QUOTA_FRESHNESS.md`, `docs/BUILD_METADATA_SCHEDULER.md` and
`docs/RATE_LIMITS.md`. Future design work must STOP before implementation.

### Prior history-receipt milestone

D-035: completed history enumerations now have durable, bounded receipts with
source provenance, exact-record digests and interval-gap inspection after restart.
Later responses omitting remembered fills cannot be labelled repaired; partial
staging cannot mint a completed interval. These are enumeration records, NOT
complete account/history/cash or private-stream continuity proof.
31 focused tests, two in-memory guard reversals and 128/4,096-row diagnostics pass.
All 670 tests pass (48.627s). Preflight remains blocked (native exit 2).
No credentials, account calls, old-fill import, launch boundary, risk reset, live
process or Polymarket changes. See `docs/BUILD_HISTORY_COVERAGE.md`.
Its then-next piece was bounded control-plane metadata refresh scheduling,
now implemented in D-036 above and cleared by the scoped re-review.

### Prior market-input milestone

D-034: market/tick/fee/milestone input adapters now publish advisory ExitTerms
through optional runtime integration. Lifecycle updates revoke stale terms;
shared bounded GET fallback supplies missing metadata. Rules-bound timing reviews
and a verified member-fee profile are explicit prerequisites, not assumed facts.
41 focused tests and 30/120-market diagnostics pass; no real market reviews,
account profile, live reader, order, account call or trading start installed.
All 639 tests pass (44.198s). Local preflight still reports live readiness false,
with no credential/network access or files created. See
`docs/BUILD_MARKET_INPUTS.md`; live scheduling, account completeness and execution
remain blocked.

### Prior logging milestone

D-033: bounded structured logging and error diagnostics are implemented across
runtime/engine, recovery, REST, ledger writer, injected execution and inventory
transitions. JSONL rotation runs on one Windows-owned worker; safe event codes,
stack locations, correlation and logging-health counters replace lost causes.
CLI logging is opt-in; future supervised launch must wire the shared sink.
All 598 tests pass (40.901s), including 29 focused logging tests; two safeguard
reversals and 30/120-market logging diagnostics pass with zero drops. No keys,
account calls, trading process, risk changes or historical-data deletion.
See `docs/LOGGING_AND_ERRORS.md`. Live readiness remains false.

### Prior inventory-exit milestone

D-032: source-verified inventory exit planning is built, execution disabled.
Exact passive reducers, conditional one-tick improvement, 15-minute evaluation,
cancel/fill confirmation, bounded reduce-only IOC plans and explicit verified
event/maintenance deadline inputs are covered. Book freshness uses ingress time,
not dequeue time. All 569 Kalshi tests and 104 Poly reference tests pass;
30/120-market planner and inventory-read diagnostics pass. No keys, private
account calls, bot start or orders this milestone. Live event-time/fee producers,
complete account proof and production execution remain unfinished; preflight
still reports live readiness false (exit 2).
See `docs/BUILD_INVENTORY_EXITS.md` for exact scope and limitations.

### Prior exposure milestone

D-031: operator chose "Just follow poly" over the fixed $400 proposal.
Rechecked current Poly source/defaults: reference capacity 20, formula
`10 * (20 + 10) = $300` aggregate exposure, $90 per market. Kalshi config and
code defaults now agree; entry breadth remains limits-driven, not capped at 20
by this reference input. Capital $500, size 10 and 30 resting entries unchanged.
510 Kalshi tests and 104 Poly reference tests pass; two in-memory safeguard
reversals detected. No credentials, venue calls or trading start this milestone.
See `docs/BUILD_POLY_EXPOSURE.md`. Account proof, exits and live integration
remain blockers; preflight still exits 2 with live readiness false.

### Prior private-stream milestone

D-030: accepted separate pre-bot history, without resetting/importing old fills
or installing a launch baseline. Added a bounded manual private-stream probe.
Actual account acknowledged all four private channels in both short sessions;
close/re-subscription succeeded. Zero account events occurred, so live fill
delivery, gap recovery and full account proof remain UNKNOWN. All 498 tests
pass; two in-memory safeguard reversals detected. No orders, bot start or
trading-ledger changes. The then-proposed $400 ceiling was subsequently
superseded by D-031 above.
See `docs/BUILD_PRIVATE_STREAM_CHECK.md` for exact scope and next blockers.

### Earlier REST account inspection

Read-only account inspection succeeded at 21:32 UTC (17:32 Eastern).
The new `kalshi-bot.txt` supplies the matching API-key ID; Kalshi accepted
authenticated GETs with the existing RSA private key. Primary subaccount 0,
all exchange shards: cash `500.4268` dollars, portfolio value zero, no resting
orders and no nonzero positions. Recent fills returned 18 rows; member-wide
archived fills returned zero, with all queried cursors exhausted. This is a
bounded observation, not complete lifetime/history/private-stream proof.
See `FINDINGS.md` section 44 for scope, limits and remaining unknowns.
No secrets printed, credential edits, ledger imports, bot starts or mutations.
Bot code remains unchanged; all live-readiness gates remain in force.

### Windows relocation

D-029 relocates the active Windows project to `C:/Users/rynna/Bots/kalshi`,
beside `C:/Users/rynna/Bots/liquidity-bot`, outside OneDrive. All 3,453 project
files matched SHA-256 tree verification immediately after moving; the supplied
credential file was moved unchanged and is explicitly gitignored. No key
contents displayed, account calls, bot start or Polymarket/WSL changes.
Both native Python environments and executable launchers now resolve the new
folder; pinned dependency versions are unchanged. All 479 tests pass here
(28.163s); the CLI preflight remains correctly blocked (exit 2). The old project
folder contains only relocation pointers. The subsequent read-only account
inspection is recorded above; relocation itself did not establish API access.

### Prior account-verification milestone

D-028 adds atomic local account verification: exact owned/foreign/missing
resting orders, fill gaps, pending fills, unbound reservations and position/scope
agreement. Reconciliation reports now carry writer evidence and reject stale
local state; history intervals and source revisions survive the recovery pass.
479 tests pass (29 new), two safeguard reversals detected/restored, 20 reference
account-snapshot tests pass; 30/120-market resource checks pass after batching
position-capacity validation. See `docs/BUILD_ACCOUNT_VERIFICATION.md`.
This completes local agreement checks, NOT full account-history/stream/cash
proof. Starting-basis policy and venue completeness guarantees remain missing.
Portfolio cap and Kalshi-specific exits remain undecided. Preflight stays blocked
(native exit 2); no keys, live account calls, trading or paper process used.

### Prior inventory/risk milestone

D-027 connects advisory inventory management and account-wide risk inspection
to the recovery engine. Exact passive reducer/cancel plans refresh on private
events, recovery, changed books and age timers; stale account/book/writer state
revokes them. Single-writer offline reservations include inventory, working
orders and unknown sends without counting a bound intent twice. Reducers remain
in dollar exposure but not entry count. No portfolio-cap default was chosen.
450 tests pass (40 new); two safeguard reversals detected/restored. Both new
30/120-market resource diagnostics and existing recovery diagnostics pass.
See `docs/BUILD_INVENTORY_RISK.md`. Preflight remains blocked (native exit 2).
No live activation, keys, account calls, orders or paper-trading process.
Complete history/stream/cash proof, production reservation authority, capacity
mapping, improved passive pricing, forced exits and launch controls remain open.

### Prior recovery-engine milestone

D-026 recovery is connected to the event engine through `RecoveryRuntime`:
independent bounded reader reconnects, coalesced startup/gap recovery, a durable
fill-before-order inbox, missed terminal-order repair and immediate ingress
revocation of stale account reports. Healthy known fills use WebSocket data
without REST polling. Engine deadlines/books continue during awaited recovery.
410 tests pass (39 new); two safeguards reversed/detected/restored. The local
128/1024-fill ingress/engine diagnostics pass predeclared budgets; see
`docs/BUILD_RECOVERY_ENGINE.md`. No live process, keys or venue calls were used.
This is a read-only integrated component, not an enabled trader. Full starting
history/stream proof, correction/settlement rules, account-wide risk/exits and
production launch controls remain unfinished. Entry authorization stays false.

### Prior automatic-recovery milestone

D-025 now implements Polymarket-inspired automatic verified fill recovery and
separate venue-cost exit-basis fallback. Missing ownership remains blocked;
conflicting immutable fills fail closed. Imports preserve D-024 receipts,
fees and per-fill cap ratchets; venue costs never invent fills or realized P&L.
371 tests pass (36 new); two safety reversals detected/restored. Injected
128/1024-fill recovery diagnostics pass unchanged budgets after removing
repeated full-window sums and per-fill inventory allocations.
See `docs/BUILD_AUTO_RECOVERY.md`. No live account calls, keys, venue writes or
old-data migration. Complete history/stream proof, correction/settlement handling,
limits-driven exposure and production integration remain unfinished. Live stays off.

### Prior archive milestone

Archived terminal-order recovery added scoped exact intent binding and bounded
404 fallback; 335 tests passed. `docs/BUILD_ARCHIVE_RECOVERY.md` records that
milestone. D-025 supersedes its pending automatic-import decision.

### Prior accounting milestone

D-024 approved and implemented source-verified accounting: weighted-average
matched partial closes, immediate actual fees (including opening fees), and
first-durable-receipt risk windows. Execution timestamps are retained separately;
duplicates cannot charge twice or move the original receipt. Caps/holds survive
restart. Schema 2 refuses old accounting databases; no historical data migrated.
306 tests pass. A 10,000-fill comparison with actual Poly arithmetic agrees within
1e-24 dollars per fill (different Decimal precision), with exact positions.
Two intentional accounting reversals failed tests and were restored.
See `docs/BUILD_ACCOUNTING.md` for scope, latency measurements and remaining gaps.
The earlier reference audit remains at `docs/POLYMARKET_POLICY_CODE_AUDIT.md`.

**D-021: implementation started, live activation NOT authorized.** Native Windows
foundation now exists in `src/kalshi_bot`, installed into its own `.venv`.
The preceding milestone added Reference Price calculations, market ranking views,
metadata caching, bounded event dispatch, an offline-injected durable create/cancel
lifecycle and native Windows stop-request controls. D-025 subsequently added
automatic verified replay; production risk/execution integration and complete recovery remain unfinished.
Rankings are gross unchanged-book estimates, not profit or permission to trade.
That milestone's 280 tests passed, including all 45 legacy tests; two further safety reversals
failed as expected and were restored. 30/120-market diagnostic load budgets passed
after correcting event-loop starvation. The read-only local preflight correctly
refuses live readiness. No credentials, venue sessions, orders, deployments,
WSL operations or Polymarket mutations occurred.
See `docs/BUILD_ENGINE_RANKING.md` and the earlier milestone reports for scope, benchmark limits
and missing integration. This is not a complete or live-ready trading bot.
Percentage-based entry caps are accepted by D-021. D-023's limits-driven capacity
needs non-circular exposure integration; other live-risk details remain unresolved.
No paper-trading process ran.

### Prior planning handoff (superseded where D-021 changes scope)

D-019: native Windows only for new Kalshi work; WSL is historical, not an active
runtime or mirror destination. No runtime was installed, migrated or started.
D-020 requires code evidence for Polymarket rules. The source trace and 104
passing Windows tests are recorded in `docs/POLYMARKET_INVENTORY_CODE_AUDIT.md`.
An additional 22 risk-window tests passed. The requested "percentage position
reducer" needs terminology confirmation: source implements a percentage-budget
resting-entry cap, not percentage liquidation of open inventory.

D-015 confirms the operating model: AI performs approved technical work; the
human operator makes all project decisions. Undecided choices require the
operator's decision, not an AI assumption. This documentation update does not
authorize implementation, deployment or trading.

**Phase: planning and API documentation.** The operator selected the Reference
Price liquidity-reward strategy, rejected paper testing, and explicitly said
not to build anything yet. D-016 updates entry size to 10 contracts and sets
at most 30 resting entry orders, excluding orders managing open positions.
Capital ceiling remains $500. The stop is $25 settled trading loss in each
fixed six-hour Eastern Time window. A stop trigger is not a guaranteed maximum
loss. D-018 adopts Polymarket's open-inventory rules. D-020 verifies the $90
market cap at size 10, but portfolio exposure is `10 * (market slots + 10)`:
$420 only at 32 slots. Kalshi market-slot count remains undecided, separately
from 30 resting entries and the $500 capital ceiling.
After a fill, cancel building risk and work the exact reducer. The 15-minute
exit evaluation can defer under the reference depth/$8 early-loss rule;
absolute deadlines take priority. Kalshi-specific deadline/exit mapping and
exact resumption policy remain to be reviewed.

D-017 explicitly limits the stop meter to realized P&L from trades the bot
opened and closed, including their attributable fees. Open inventory, marks,
rewards, transfers and cash-settlement timing do not count. This is closed-trade
realization, not a requirement to wait for event resolution.

Multiple WebSockets are now required. The recommendation in
`docs/MULTI_WEBSOCKET_DESIGN.md` proposes four connections feeding one engine,
with Polymarket incident lessons and Kalshi-specific contracts. Socket count
and detailed architecture are proposals, not approved or implemented behavior.

D-014 now requires Polymarket-style document routing, WebSocket-first data,
REST for missing information, and CPU-efficient/scalable design from the start.
The inspected reference is `C:/Users/rynna/Bots/liquidity-bot`, not the old
OneDrive folder. AGENTS/CLAUDE route to `AI_OPERATOR.md`; permanent rules are
in `AI_ENGINEERING.md`, with a proposed source/component map in
`docs/ARCHITECTURE.md`. Only Markdown changed; no bot/transport implementation,
benchmark, live process change or Polymarket mutation occurred. Root-history
compaction and an automated documentation audit remain pending.

Liquidity research is complete in `docs/LIQUIDITY_REWARD_RESEARCH.md`.
September 19 at 22:52 UTC: 5,251 active LIP programs, all with 0.50 discount;
102 logged public GETs succeeded. A purposive 40-book inspection found 27
with two-sided target depth. Static remaining-period arithmetic cleared $1
on one size-5 pair and five size-9 pairs, not a venue-wide profit estimate.
The $1 threshold is per individual program. Only one dedicated public reward
endpoint exists in the captured specs; no personal reward ledger was found.
Eligibility/source discrepancies and missing live risk decisions remain open.
No credentials, account API calls, trading writes, bot build or paper run occurred.

The official API reference is complete at `docs/KALSHI_API_REFERENCE.md`:
240 documentation pages, 191 REST operations across three API families,
23 WebSocket channel definitions, both complete AsyncAPI specifications,
20 FIX pages' technical material, and the CF Benchmarks passthrough.
The 2026-09-19 snapshot has zero failed sources and zero unresolved schema refs.
See `docs/API_REFERENCE_AUDIT.json` for field-preservation and source-hash checks.
Keys were not used and no account or trading API was called during that documentation task.

The September 19 reference-policy replay reported modeled net +$0.51/day at
size 5 and +$0.61/day at size 10, using hindsight selection, 300-second repricing,
3600-second exits, zero maker fees, and externally resolved settlements. These
are simulation results, not paid reward or proof of an executable edge. Size 10
is a historical comparison, not a validated outcome for the D-016 live plan.
No further paper-testing stage is planned.

Windows project: `C:/Users/rynna/Bots/kalshi` (D-029).
Historical data/code copy: `/home/polybot/kalshi-bot` in Ubuntu-24.04 WSL.
D-019 retires it from active Kalshi work; no further mirroring or execution.
Git inspection still reports that the local copy is not a usable repository;
no commit, push, or claim of GitHub parity has been made.

The remainder below is retained September 14 history, not current authority.

## Historical status — 2026-09-14

Last verified: 2026-09-14 21:25 (America/New_York).

## Executive state

**Phase:** measurement and model correction.

**Objective:** determine whether the Polymarket US liquidity-reward strategy has
a conservatively positive net expectancy on Kalshi before building a full bot.

**Current verdict:** do not build the transferred strategy. On the 12.97-day
laptop capture, even a hindsight-selected reward portfolio loses money after
same-clock fills and exits. The most favorable tested case sets maker fees to
zero, gives passive exits 60 minutes, and prices unknown exits at zero; it still
models `-$4.98/day`. This passes Experiment Stage 1's stop gate.

**Canonical repository:** `https://github.com/rynn-arriola/kalshi-bot.git`.
Credentials and captured market data remain ignored and local-only.

**Live state:** no Kalshi strategy order has ever been placed by this project.
There is no production bot, deployment, scheduler, reconciler, or authorized
write path.

**Measurement state:** laptop R1 is closed and no collector process is running.
It captured 1,567,512 books and 41,868 trades from 2026-08-29 03:39 UTC through
2026-09-11 02:52 UTC (12.97 days). SQLite quick check is `ok`; 1,567,498 book
reads returned 200 and 14 exhausted reads recorded status 599. The recorder did
not write a clean end timestamp, so the exact stop cause remains unknown.

The corrected size-10 replay uses the current July rule, matches program terms
to book time, excludes edited/invalid programs, requires 80% period coverage
and 100 snapshots/day, and caps the hindsight portfolio at 30 markets/$300.
Modeled reward is `$7.75/day`. Same-clock central net ranges from `-$30.41/day`
at a 300-second exit to `-$7.36/day` at 3600 seconds. The 3600-second
maximum-loss bound is `-$11.65/day`; even zero maker fees leave `-$4.98/day`
central and `-$9.24/day` conservative.

The former server was destroyed by the operator, so its R3 process and unmirrored
R3 data are no longer the active evidence source. Historical R1 remains
preserved locally as `data/server-shadow-20260827-closed.db`. A two-minute
laptop canary closed cleanly at commit `0043c3a`; verified PC copies are
`data/laptop-canary-20260829.db` and `.log`. A consistent SQLite-backup snapshot
of laptop R1 at 03:44 UTC is mirrored on this PC as
`data/checkpoint-laptop-r1-start-20260829T0344Z.db` and `.log`.

## What is verified now

- The Polymarket US reference strategy was profitable under its six-day
  balanced-leg report for 2026-08-20 through 2026-08-25: trading
  `-$31.16/day`, venue reward `+$85.56/day`, reported net `+$54.40/day`.
- The reward rows were reproduced from the live venue earnings endpoint. The
  trading report is partial accounting: it excludes unbalanced markets and
  cannot allocate positions that settle instead of closing.
- The current reference code was re-audited without a Polymarket API call.
  Local/GitHub `main` match at `3134678`; its strategy files match reviewed
  deployed source `5825db8`. Exact behavior is versioned in
  `docs/POLYMARKET_REFERENCE.md`.
- Both venues reward resting size through a discounted, normalized share of
  qualifying book liquidity, but their implementations are not identical.
- Kalshi's July 15 certified filing, effective July 30, governs the August
  capture. It uses the one-fifth-of-Target-Size reference and scales the pool by
  the non-excluded snapshot fraction. The current Help Center agrees.
- On `capture_long.db` at size 10, the current rule gives a median one-tick
  reward-share multiple of `1.000x` over 112,492 side observations. The
  superseded February mode gives `1.943x`; prior "inside doubles reward" claims
  are superseded for this dataset.
- The existing capture and replay instruments run and reproduce their published
  tables. Reproducible output does not validate an outdated rule or a biased
  counterfactual.
- The isolated server recorder passed all 25 tests and a two-minute public-API
  canary before the long run. The canary recorded 65 book rows across 50
  candidate markets with zero HTTP failures, zero recorded errors, and a valid
  SQLite integrity check. The Polymarket supervisor/trader PIDs and start times
  were unchanged before and after it.
- At 2026-08-27 10:49 UTC, the long run contained 41,501 book rows, 5,241
  trades, 17,597 program rows, zero non-200 books, and zero recorded errors.
  The latest book was 30 seconds old and all 75 actively tracked tickers had
  books in the preceding five minutes.
- Laptop capacity is ample for the isolated Kalshi measurement. Windows reports
  16 logical CPUs, 31,866 MB total RAM with 17,522 MB free, and 706.8 GB free on
  C:. WSL reports 15,545 MB RAM with 14,782 MB available and 952 GB free. The
  long collector used about 79 MB with a 90 MB peak under its 256 MB cap and is
  limited to 20% of one CPU. The active Windows `Server Mode` plan disables
  sleep and hibernation on AC power; the laptop must remain plugged in because
  battery settings still permit sleep/hibernation. No upgrade is indicated.
- The Polymarket supervisor and trader were restarted at 2026-08-27 04:02:57
  UTC after the launch check. Kalshi stayed active, no OOM event occurred, and
  host load was low at inspection. The cause of the Polymarket restart is
  **UNKNOWN**; do not attribute it to Kalshi without evidence.
- The closed server dataset contains 50,038 books, 5,626 trades, and 17,672
  program rows with zero recorded HTTP errors/non-200 books before the fatal
  TLS disconnect. The database integrity check passes.
- On that 9h51m dataset, size-10 15-minute touch quotes completed both sides in
  11 of 8,620 windows (0.1%) and filled only one side in 88 (1.0%). Stepping
  inside completed 21 pairs (0.2%) and produced 140 one-sided fills (1.6%).
  Pure spread scalping therefore looks unfavorable: inventory is created about
  7–8 times more often than a spread is captured.
- A current-rule, same-clock proxy for the Polymarket entry policy modeled
  `$28.36/day` reward and `-$9.75/day` 300-second markout across 30 funded
  markets, proxy `+$18.61/day`. This is **not net P&L**: the corrected
  900-second exit replay priced 92 of 106 fills for `-$54.83` total with 14
  unknown, and the two instruments do not yet share a fixed universe or
  realized-exit clock.
- On thin books, adding size has diminishing marginal reward because our own
  score enters the denominator. This is arithmetic. The portfolio-level optimum
  has not been measured on a fixed universe.

## Active blockers

### B2 — Adverse selection is not represented credibly (critical)

`exit_cost.py` now prices against the first usable book at or after the exit
deadline and carries missing/thin books as unknown. Under the current
Polymarket entry policy at size 10 and a 900-second deadline, it fully priced 67
of 84 simulated fills for total P&L `-$27.85`; 17 remain unknown. This
corrected loss path is not yet integrated with the
fixed-universe reward replay, maker fees remain unknown, and missing exposure
still needs explicit conservative bounds.

### B3 — Sizing sweep is not like-for-like

The published sizes fund different market portfolios under a fixed capital cap
and changing guards. The monotonic decline in aggregate reward per resting
contract is suggestive, but it does not establish an optimum near ten contracts.
A fixed-universe, per-market marginal curve is required.

### B4 — No payout calibration on Kalshi

`period_reward / 10_000` is strongly corroborated but has not been reconciled to
an actual strategy payout. The minimum is per individual program according to
current Kalshi help. A live experiment must be sized to clear it conservatively.

### B5 — No live Kalshi fill/exit sample

Maker fees, qualification uptime, queue position, fill rate, competitor
reaction, actual exit cost, and realized reward remain unobserved for this
strategy on Kalshi.

## Existing evidence, bounded correctly

- `capture_long.db`: density-selected capture used for the newest replay. It is
  short relative to many program periods and assumes captured competition is
  representative later.
- `reward_rules.py`: pure, versioned current/legacy reward arithmetic with
  hand-checkable fixtures and tests. Reports print the rule and source date.
- `net_sizing.py`: integrates reward interruption and simulated fills on one
  clock. Its `proxy` combines predicted reward with markout; it is not complete
  net P&L and remains affected by B2–B3.
- The size table in `FINDINGS.md` section 18 used the superseded reward rule and
  a portfolio-changing sweep. It is retained as history and must not drive a
  strategy or sizing decision.
- Reward-only `sizing.py` under the current rule reports `$7.369/day` after the
  per-program minimum for seven size-10 markets on `capture_long.db` under the
  audited entry-price policy. It is not fixed-universe and is not a net-profit
  result.
- The hypothesis that Polymarket's reward jump was caused by the listed August
  25 uptime fixes is unproven; the reward increase began on August 23–24.

## Current scope boundary

Approved now:

- Repair and test measurement instruments.
- Re-run read-only analysis and produce conservative bounds.
- Compare pure spread-scalping quote gaps separately from rewards on identical
  data and assumptions; initially test join-the-touch and feasible 1¢–5¢ gaps.
- Run verified read-only measurement on the laptop under the isolated
  boundaries in `docs/SERVER_MEASUREMENT.md`.
- Observe and analyze the active read-only server capture; stopping or
  correcting that measurement remains inside the same safety boundary.
- Design a minimal one-market evidence probe and its safety case on paper.

Not approved now:

- Full Kalshi bot implementation.
- Live order code or authenticated write endpoints.
- Deployment, capital allocation, market selection for a live run, or an arming
  command.

The active work order is `NEXT.md`. Operator authority is in `DECISIONS.md`.

The daily capacity heartbeat is paused at the operator's request to conserve
Codex usage. Laptop checks and SQLite-backup mirrors to this PC are manual when
the operator opens this task and asks; they remain read-only with respect to
Kalshi and are not authorized to restart anything without an operator request.

## Resolved blocker

### B1 — Kalshi rule-source conflict

**Resolved 2026-08-26.** The later July filing supersedes the February filing
effective July 30 and matches the Help Center. Current August analysis defaults
to `july-2026-one-fifth`; the February mode remains comparison-only.

### B6 — Recorder retry resilience

**Resolved 2026-08-28.** At 10:27:03 UTC, R3 encountered a real `URLError`
caused by a connection reset on attempt 1/3. The request recovered within the
bounded retry path: the service retained PID 3898 with zero restarts, logged no
traceback, recorded no exhausted status-599 failure, and was still writing fresh
books at 12:58 UTC. This resolves transport survival, not the need to complete
the planned capture window.
