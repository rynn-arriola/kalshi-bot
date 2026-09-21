# Current status

## Current update — 2026-09-21

D-048 Sol implemented the P2 fix from the D-047
[Astra review](docs/REVIEW_D047_ASTRA.md); see
[build evidence](docs/BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md). Each connection
now retains one finalizer through stop/repeated cancellation until its reader is
joined, valid tail fills are durable, the marker is closed and gaps are refreshed.
Three new regressions cover real transport queue/byte accounting, ordinary stop,
caller cancellation and marker-close cancellation. All 231 focused and exact
804 full tests pass; continuity/history resource checks and disabled preflight
pass. STOP for Astra review under D-037. Venue handoff, starting basis, Phase
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
