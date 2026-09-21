# What exists

## D-057 S2A review corrections — 2026-09-21

[Fixes and evidence](docs/BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md) cover D-056 R1-R8:
retained native ownership, explicit spawn permission, completed terminal writes,
protocol/power gates, protected files, bounded diagnostics and journal pruning.
Thirty new regressions; complete suite 915 run / 914 pass / one privilege skip,
plus three detected safeguard reversals. 100-cycle ownership assertions pass;
parent idle CPU misses its target and cold-start handle retention is unattributed.
Independent review remains required;
S2B and all live operation remain blocked. No production configuration changed.

## D-056 Astra review — changes required — 2026-09-21

[Independent review](docs/REVIEW_D056_ASTRA.md) reproduces lifecycle, launch,
IPC, protocol, handle and journal defects despite 81 passing existing focused
tests. Persistent-file security, power invalidation and diagnostic requirements
also remain incomplete. S2A is not cleared; the implementation/resource evidence
below is qualified by this review. Sol corrections are next; S2B remains blocked.

## D-056 native Windows supervisor S2A — 2026-09-21

D-056 [build evidence](docs/BUILD_WINDOWS_SUPERVISOR_S2A.md) implements the
approved inert-process half of the [D-055 design](docs/DESIGN_WINDOWS_SUPERVISOR_S2.md).
It adds protected role/stop/control objects, inherited lifetime handles,
transactional native reservations, strict bounded local IPC, one fixed child
fixture, cold orphan release and native acceptance/resource tests. The 60-second
idle and 100-cycle run meets every S2A target; 81 focused and 885 complete tests
pass, and disabled preflight remains fail-closed. There is no production start CLI,
runtime adapter, account/network/order path or live authority. Independent Astra
review is mandatory before any separately approved S2B work.

## D-055 S2 design artifact — not implementation — 2026-09-21

[S2 architecture and acceptance](docs/DESIGN_WINDOWS_SUPERVISOR_S2.md) defines
the native lifecycle/IPC interfaces, inherited ownership, durable stop/unknown
recovery behavior and resource tests. Proposes S2A inert child first, then S2B
offline runtime and restriction transfer. Source and official Windows/Python
contracts were inspected. D-056 above now implements S2A only and awaits Astra
review; S2B remains unimplemented.

## D-048 Astra review — retained finalization cleared — 2026-09-21

[Independent review](docs/REVIEW_D048_ASTRA.md) clears D-047 R1 with no new
blocking findings. All 868 full and 205 targeted tests pass, plus nine repeated
shutdown regressions and two writer-thread failure/cancellation probes. Both
D-048 and supervisor S1 review gates are complete. S2 remains unbuilt and needs
separate assignment; venue continuity and live readiness remain unproven.

## D-054 Astra review — supervisor S1 cleared — 2026-09-21

[Independent review](docs/REVIEW_D054_ASTRA.md) clears both D-053 clock
findings with no new blocking findings in this diff. All 64 focused and 868 full
tests pass, plus 48 independent fault-sequence cases and four parent-defect
detections. Disabled preflight remains fail-closed. This completes offline S1
review only; D-048 review and separate assignment still gate S2. No runtime or
native reboot/process-integration readiness is claimed.

## D-054 supervisor clock review fixes — 2026-09-21

D-054 [build evidence](docs/BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md) implements
both findings from the [D-053 Astra review](docs/REVIEW_D053_ASTRA.md). A stale
or out-of-phase child payload cannot consume local clock distrust; the hold is
durable and the payload remains labeled stale. Default wall/monotonic continuity
uses tolerated deltas and retains its persisted identity instead of comparing a
fresh quantized estimate. All 64 focused and 868 full tests pass, including
10/10 repeats, counterfactual parent checks, resource checks and disabled
preflight. This is Sol implementation evidence; the independent review above
now clears it within S1. D-048 and separate assignment still gate S2.

## D-053 Astra review — two clock fixes required — 2026-09-21

[Independent review](docs/REVIEW_D053_ASTRA.md) clears D-052 R1/R2/R3/R5 in
offline S1, but reproduces clock-fault loss after stale events and false boot
changes from small sampling skew. All 59 focused and 863 full tests pass;
additional transaction probes qualify the implementation claims below. This
records the `b051067` review state; D-054 above implements both findings and
awaits Astra review. S2 and D-048 remain gated.

## D-053 supervisor sequence and clock fixes — 2026-09-21

D-053 [build evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md)
implements all five findings from the [D-052 Astra re-review](docs/REVIEW_D052_ASTRA.md).
Repeated STOP commands fence prepared arms; expired startup/progress deadlines
cannot be refreshed away; failed-spawn release retains attention; persisted
clock continuity fails closed across stores/restarts; and identityless child
events are stale. All 59 focused and exact 863 full tests pass, including 10/10
focused repeats, resource checks and disabled preflight. This is offline Sol
implementation evidence pending Astra re-review; S2 and D-048 remain gated.

## D-052 supervisor re-review — changes required — 2026-09-21

[Astra re-review](docs/REVIEW_D052_ASTRA.md) clears original D-051 R4/R6/R7
within offline S1, but reproduces four P2 follow-ups and one P3 identity gap.
All 46 focused and 850 full tests pass; additional failure-sequence probes show
why S2 is not cleared. This records the review-time state at `7bf5241`; D-053
above implements those findings and awaits Astra review. D-048 remains separate.

## Supervisor S1 review fixes — 2026-09-21

D-052 [review-fix evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md)
implements R1-R7 from the [D-051 Astra review](docs/REVIEW_D051_ASTRA.md).
The execution-disabled supervisor now separates trusted control time from event
timestamps, fences every safety disarm, enforces lifecycle ownership and bounded
deadlines, persists explicit retry holds, distinguishes process exit from cleanup
and measures real persisted supervisor work. All 46 focused and exact 850 full
tests pass, plus 10/10 repeated focused runs, compilation, disabled preflight and
the 60-second CPU fixture. No launcher, runtime wiring or live action was added.
Independent Astra re-review is next; S2 remains blocked.

## Supervisor S1 review — changes required — 2026-09-21

[D-051 Astra review](docs/REVIEW_D051_ASTRA.md) reproduces six P2 policy/contract
defects and one P3 resource-verification issue. All 32 focused and 836 full tests
pass, but stop fencing, lifecycle/progress, retry/startup and crash recovery need
additional regressions and fixes. The sleep-only CPU measurement does not verify
parent workload. This section records the original review state at `7b8d6cd`;
D-052 above now implements the requested fixes. S2 remains blocked pending Astra
re-review, alongside the separate D-048 gate.

## Native Windows supervisor S1 — 2026-09-21

D-051 [implementation evidence](docs/BUILD_WINDOWS_SUPERVISOR_S1.md) adds an
immutable execution-disabled process-supervision policy and separate
transactional SQLite control journal. Durable stop/generation state,
attempt-before-spawn ordering, bounded recovery, useful-progress health and
fail-closed outcomes have 32 focused and 836 full passing tests plus resource
and disabled-preflight checks. It has no process launcher or runtime wiring and
awaits independent Astra review before S2.

## Native Windows supervisor design — 2026-09-21

D-050 [proposal](docs/DESIGN_WINDOWS_SUPERVISOR.md) traces Polymarket source and
defines process ownership, durable stop/restart controls, recovery classification
and S1-S3 implementation gates. Six isolated Poly host-recovery tests pass. Its
offline S1 is now implemented under D-051 above; later gates remain pending.

## Mandatory two-model routing — 2026-09-21

D-049 makes `AI_OPERATOR.md` the canonical usage-efficient routing rule for the
only two agents: GPT-6 Astra and GPT-5.6 Sol. Every substantive task begins with
a short recommendation; Sol defaults to routine/approved work, while Astra is
reserved for material design, uncertainty, risk and meaningful live-money review.
D-037 is superseded where different. Documentation only; no runtime change.

## Retained connection finalization — 2026-09-21

D-048 [implementation evidence](docs/BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md)
addresses the D-047 review finding. Connection teardown now has one retained
owner through disconnect/stop overlap, fill drain and marker/gap finalization.
Three new regressions pass with 231 focused and 804 full tests, resource checks
and disabled preflight. The subsequent [Astra review](docs/REVIEW_D048_ASTRA.md)
now clears this fix in scope; live gates remain false.

## D-047 review — disconnect/stop overlap remains — 2026-09-21

[Astra review](docs/REVIEW_D047_ASTRA.md) verifies the original fixes with 228
passing focused tests and three counterfactual regression failures against the
previous runtime. One P2 remains: shutdown can cancel a disconnect drain already
in progress, leaving valid queued evidence and an open marker. Actual transport
consumer probes reproduce both stop modes 3/3 each. Next role is Sol fixes after
the operator switch; source/tests are unchanged and trading remains disabled.

## Continuity shutdown ownership fixes — 2026-09-20

D-047 [implementation evidence](docs/BUILD_ACCOUNT_CONTINUITY_SHUTDOWN_FIXES.md)
addresses both D-046 re-review findings. Repeated cancellation retains cleanup
ownership through reader join and marker finalization. Per-item draining records
errors, preserves later valid fills and surfaces shutdown failure. All 199
focused and 801 full tests pass with resource/preflight checks. Independent
Astra re-review is next; all live/venue-handoff gates remain false.

## D-046 re-review — shutdown changes required — 2026-09-20

[Astra re-review](docs/REVIEW_D046_ASTRA.md) clears original R2-R5 and verifies
the immediate-stop fix. Two P2 cases remain: a second cancellation can leave
the shielded account reader alive, and malformed buffered input can abort the
drain with later valid fills unretained and the shutdown error swallowed. All
196 focused tests pass; additional probes expose these gaps. Source/tests were
not changed in review. Next role is Sol fixes after the operator switch.

## Continuity Phase 1 review fixes — 2026-09-20

D-046 [implementation evidence](docs/BUILD_ACCOUNT_CONTINUITY_REVIEW_FIXES.md)
addresses all R1-R5 findings: bounded shutdown owns queued/in-flight fill
evidence, accepted epoch opens cannot become hidden orphans, quota status is
coherent, the retention test drains its callback, and reconnect work is now
measured. All 196 focused and 798 full tests pass, as do resource/preflight
checks. Independent Astra re-review is next. Venue proof and live authority
remain false.

## Continuity Phase 1 review findings — fixed by D-046 — 2026-09-20

[D-045 Astra review](docs/REVIEW_D045_ASTRA.md) found two P2 lifecycle bugs
and three P3 status/verification issues. Review reran 192 focused and 794 full
tests successfully, but separate probes reproduce missed shutdown fills and
hidden orphan markers. The quota failure was a callback-timing test flake;
reconnect resource activity was outside the original benchmark measurement.
This records the review-time state; D-046 above fixes all five findings and now
awaits Astra re-review. All live/venue-handoff gates remain false.

## Evidence-only account continuity Phase 1 — 2026-09-20

D-045 [implementation and verification](docs/BUILD_ACCOUNT_CONTINUITY_PHASE1.md)
adds durable local private-epoch markers, unapproved starting-account candidates,
source-bound assessment and safer position-stream/pagination handling. All 168
directly affected tests and resource fixtures pass. A 792-test complete run
passed once, but the final 794-test run had one unrelated reproducible quota
weak-reference failure; see STATUS. Independent Astra review is next. This does
not establish a venue handoff, opening inventory or live authority.

## Starting-account continuity design — 2026-09-20

D-044 [Astra design](docs/DESIGN_ACCOUNT_CONTINUITY.md) specifies an evidence-only
Phase 1 and conditional later phases. Phase 1 was built under D-045 above;
conditional venue proof and opening-state phases remain unbuilt. Trading remains
disabled.

## Canonical GitHub checkout — 2026-09-20

D-043 replaced the old remote tree with the current Windows Kalshi project on
the GitHub default `master` branch and connected the active folder to it. The
old divergent branch history remains in `master`; the obsolete `main` branch
was removed. [Publication evidence](docs/GITHUB_PUBLICATION.md). Credentials
and local runtime/data artifacts were excluded. This did not enable trading.

## Quota review correction design — 2026-09-20

D-042 [follow-up fixes](docs/BUILD_QUOTA_REVIEW_FOLLOWUPS.md) address the two P3
findings from the D-041 re-review. All 62 focused quota tests, 778 full-suite tests
and quota resource fixtures pass. [Astra re-review](docs/REVIEW_D042_ASTRA.md)
clears both: 62 focused tests, two process-local reversals and a boundary/caller
probe passed. The full suite/resource results are implementation evidence.

D-040 supplied [the design contract](docs/DESIGN_QUOTA_REVIEW_FIXES.md); D-041
implemented [the fixes](docs/BUILD_QUOTA_REVIEW_FIXES.md). The exact full suite
and resource checks pass. [Astra re-review](docs/REVIEW_D041_ASTRA.md) clears the
original findings with two P3 follow-ups; current review tests pass.

## Quota leases and automatic refresh — 2026-09-20

D-039 implements BOTH phases of the [Astra design](docs/DESIGN_QUOTA_FRESHNESS.md):
expiring account-scoped quota evidence, guarded shared GETs, restricted same-bucket
recovery, automatic supervision and runtime holds without stopping healthy stream
fills. 46 focused tests, two guard reversals, 30/120 resource fixtures and the idle
check passed during implementation. The initial Astra review found three P2 issues
and a full-suite test timeout; see [review](docs/REVIEW_D039_ASTRA.md).
Current verification outcomes belong in STATUS; D-041/D-042 fixes are now cleared.
[Scope, verification and remaining limits](docs/BUILD_QUOTA_FRESHNESS.md).
No production allowance or live activation is established.

## Metadata scheduling and shared read-rate controls — 2026-09-20

Review status: Astra's four additional probes identified reliability defects.
Sol implemented the four fixes and added nine focused regressions; 30/120
scheduler and token resource checks pass. Astra re-review cleared all four in
scope with 87 focused tests and an integrated reconnect probe; see
[re-review evidence and limits](docs/REVIEW_D036_ASTRA_R2.md) and STATUS for the
prior complete-suite outcome. This is not live-readiness approval.

D-036 adds `metadata_scheduler.py`, optional runtime ownership, coalesced lifecycle
refresh, deadline revocation, bounded retries and generation-safe shutdown.
`RestReads` adds explicit coalesced quota refresh; its shared token budget now
prioritizes account reads, reserves background headroom and honors final/late
429 pauses. No guessed tier capacity or per-socket budget multiplication.
25 scheduler and 18 rate tests, prior two guard reversals and 30/120-market/request
resource checks pass. See [scheduler](docs/BUILD_METADATA_SCHEDULER.md),
[rate limits](docs/RATE_LIMITS.md) and STATUS for the full-suite outcome.
D-039 above subsequently adds quota-freshness/grant enforcement. No production write limiter,
real market/profile approvals, account calls or trading activation are supplied.

## Durable history enumeration receipts — 2026-09-20

D-035 adds `history_coverage.py`, receipt persistence after staged-row validation,
restart interval-gap inspection and recovery/status wiring. Omitted prior fills
remain discrepancies, not silently forgotten history. No new financial accounting
or launch boundary. All 670 tests (31 focused), two guard reversals and 128/4,096-row
diagnostics pass. [Contract, measurements and gaps](docs/BUILD_HISTORY_COVERAGE.md).

## Source-bound market inputs — 2026-09-20

D-034 adds typed `market_inputs.py`, five scoped GET metadata adapters and
optional runtime lifecycle/publication wiring. Shared caches preserve stream
updates across stale REST and invalidate terms before changes. No automatic
market-rule interpretation or member-profile assumption; no autonomous refresh
controller/live feed started. All 639 tests pass (41 focused), two safeguard reversals and
30/120-market diagnostics pass. [Contracts and gaps](docs/BUILD_MARKET_INPUTS.md).

## Structured logging and safe error handling — 2026-09-20

D-033: `observability.py` supplies bounded secret-safe JSONL, rotation, Windows
exclusive ownership, correlation and health counters. Runtime/engine, recovery,
REST, ledger writer, injected commands and inventory transitions are instrumented;
CLI has opt-in `--log-dir`. No default filesystem side effects or trading start.
598 full-suite tests (29 focused fault tests), two safeguard reversals and 30/120-market logging
diagnostics pass. [Usage, scope and evidence](docs/LOGGING_AND_ERRORS.md).

## Source-verified inventory exit plans — 2026-09-20

D-032 adds `exits.py`, durable mutation-attempt projection, versioned exit inputs
and ingress-fresh book gating in advisory inventory management. Cancel races,
partial IOC fills and ambiguous restarts retain proof gates; nothing dispatches.
569 Kalshi tests, 104 Poly reference tests, two in-memory safeguard reversals and
30/120-market diagnostics pass. No production fee/event-time producer or live
execution authority is supplied. [Evidence and gaps](docs/BUILD_INVENTORY_EXITS.md).

## Poly-derived exposure default — 2026-09-20

D-031 rechecks actual Poly source/defaults and sets the formula reference to 20:
size 10 yields $300 aggregate exposure, independently of live market occupancy.
Existing pure admission and atomic writer gates enforce it; CLI exposes the
reference. 510 Kalshi tests (12 new), 104 Poly tests and two in-memory safeguard
reversals verified. Preflight remains blocked; no live calls or trading.
[Source, scope and boundaries](docs/BUILD_POLY_EXPOSURE.md).

## Bounded private-stream check — 2026-09-20

`diagnostics.py` and `scripts/check_private_streams.py` provide a manually
opted-in, count-only private-channel probe using the existing read-only reader.
Actual account accepted all four channels on two sequential connections;
close/re-subscription succeeded. No account events occurred, so delivery and
gap recovery are not live-verified. 19 new tests; 498 total pass; two in-memory
safeguard reversals detected. No trading start, ledger import or risk changes.
See [scope/results](docs/BUILD_PRIVATE_STREAM_CHECK.md). D-030 baseline direction
is recorded, not an installed production accounting baseline.

## Windows project relocation — 2026-09-20

D-029: active folder is `C:/Users/rynna/Bots/kalshi`, beside Polymarket, outside
OneDrive. All 3,453 files (272,372,691 bytes) passed tree SHA-256 verification
immediately after the move; the separately supplied credential also matched
before/after hashes without displaying its contents. Native environments,
editable-package path and launchers repaired with unchanged pinned runtime
versions. All 479 tests pass in 28.163s; preflight correctly exits 2. Historical
data moved intact; only relocation pointers remain at the old project root.
No account validation, trading start, Polymarket changes or WSL migration.

## Atomic local account verification — 2026-09-20

`verification.py` and writer/coordinator integration check exact account-wide
order/fill/position/reservation agreement in one transaction. Epoch/revision
guards reject stale reports; runtime retains history scope and ingress provenance
and rejects foreign orders even with matching aggregate counts. `observe_costs`
checks active capacity once per snapshot. 479 tests pass (29 new); two reversals,
20 Poly source tests and resource diagnostics verified.
[Scope/results](docs/BUILD_ACCOUNT_VERIFICATION.md). Complete starting basis,
history/stream/cash proof and live execution remain unimplemented/unverified.

## Inventory/risk integration — 2026-09-20

`portfolio.py` builds bounded shared exposure views and atomic OFFLINE-only
entry reservations. `management.py` maintains revision-checked passive advisory
plans; runtime refreshes on account events, recovery, books and deadlines.
Ledger position clocks persist through partial closes/restart; missing old
clocks block age assumptions. 450 tests pass, including 40 new tests; two
reversals detected/restored and both resource diagnostics pass.
[Scope/results/remaining gaps](docs/BUILD_INVENTORY_RISK.md). No mutation
dispatch, live authority, complete-account proof or chosen portfolio cap.

## Recovery-connected event engine — 2026-09-20

`runtime.py` supervises independent read-only reader generations and a single
bounded recovery worker. `inbox.py` durably retains fills until exact ownership
is resolved; writer applies/deletes atomically. Engine integration preserves
book/deadline progress during network recovery and revokes account reports at
private ingress. 410 tests pass, two safety reversals detected/restored; offline
128/1024-fill diagnostics pass. [Scope/results](docs/BUILD_RECOVERY_ENGINE.md).
No live CLI/start, mutation attachment, complete account proof or venue use.

## Automatic fill recovery and exit-basis fallback — 2026-09-20

D-025 imports verified owned fills automatically in bounded transactions,
resolves missing order bindings and preserves immutable deduplication and
receipt-window risk. New `position_basis.py` provides a separate, fresh,
owned-quantity venue-cost fallback for exit planning only. Incremental durable
window totals avoid repeated journal scans. 371 tests pass; two safety reversals
detected/restored; 128/1024-fill diagnostics pass unchanged local budgets.
[Scope/results/gaps](docs/BUILD_AUTO_RECOVERY.md). No live trading or migration.

## Archived-order recovery milestone — 2026-09-20

GET-only archive support, strict bounded normalization and exact owned-intent
binding; typed 404 fallback for previously bound orders; stale-generation guards
and missing-fill reservation retention. 335 tests pass; two fault reversals
detected/restored. Local 128/4096-order diagnostics passed; no live readiness or
automatic fill replay. [Scope/results](docs/BUILD_ARCHIVE_RECOVERY.md).

## Approved accounting implementation — 2026-09-20

D-024 implemented in ledger/normalization: weighted-average basis, immediate
matched partial-close P&L and full actual fees, durable receipt windows and
separate execution-time evidence. Schema 2 fails closed on old accounting files.
306 tests pass; 10,000 actual Poly arithmetic comparisons agree within 1e-24
dollars per fill; two intentional reversals detected/restored. No live start,
automatic historical replay or migration. [Details](docs/BUILD_ACCOUNTING.md).

## Further executable Poly policy audit — 2026-09-20

[Capacity, accounting, selection, exits and restart trace](docs/POLYMARKET_POLICY_CODE_AUDIT.md).
216 relevant reference tests passed on Windows; Poly stayed unchanged. Identified
immediate fee charging, weighted-average basis and receipt-time risk attribution,
plus the conditional passive-exit tick improvement omitted from short summaries.
Documentation only: no Kalshi accounting/config/trading-runtime changes.

## Event/command engine and quote/ranking components — 2026-09-20

Added `quoting.py`, `ranking.py`, `metadata.py`, `engine.py`, `execution.py`,
an additive mutation journal and native Windows stop-request controls. These
are execution-disabled components, not a production trader. 280 tests passed,
including combined injected lifecycle and cross-process Windows checks.
Two safety reversals detected/restored. 30/120-market diagnostic workloads passed
after scheduling/duplicate-work fixes. [Scope/results/gaps](docs/BUILD_ENGINE_RANKING.md).
Rankings remain gross estimates, without automatic selection or a live feed.

## Owned-order management and recovery evidence — 2026-09-20

Added `orders.py` and `recovery.py`; integrated private order/position projections,
owned-fill accounting gates, order bootstrap/direct GET, durable terminal/fill
agreement and bounded current/archive history staging. Pure inventory plans
preserve exact reducers and cancellation-before-replacement; no executor sends
them. 212 tests passed, two safety reversals detected/restored, offline resource
measurements recorded. [Scope and gaps](docs/BUILD_RECOVERY_ORDERS.md).
Automatic replay still awaits accounting policy; no live readiness is claimed.

## Durable writer and account-evidence integration — 2026-09-20

Added `writer.py`, `rest.py` and `account.py`: bounded off-loop SQLite owner,
atomic per-fill risk persistence, GET-only token-governed reads, complete-page
enumeration and stale-generation rejection. Current-position agreement never
enables entries or pretends to prove complete history. 159 tests passed; two
additional safety reversals detected and restored. Offline writer latency measured.
See [scope, source map and remaining gaps](docs/BUILD_ACCOUNT_IO.md).
No keys, live venue sessions, writes, paper run or deployment used.

## Windows-native component foundation — 2026-09-19

`src/kalshi_bot` implements strict config/Decimal boundaries, ledger/intents,
candidate closed-fill accounting, persistent six-hour caps, exposure admission,
incremental sequenced books, a bounded dirty/deadline scheduler, V2 payload
construction, read-only multi-WebSocket readers, native Windows ownership and
credential-free CLI/preflight. Dedicated `.venv`, dependency lock and PowerShell
test/preflight scripts are installed. No live command, executor or integrated
trading engine exists yet. [Scope/tests/limitations](docs/BUILD_FOUNDATION.md).
110 tests passed; offline microbenchmark and two expected reversal failures
recorded. All historical instruments remain intact; no keys or venue writes used.

## Direct Polymarket code audit — 2026-09-19

`docs/POLYMARKET_INVENTORY_CODE_AUDIT.md` traces inventory settings into
execution decisions and records 104 passing reference tests on native Windows.
No Kalshi implementation or Windows runtime has been built. D-019 ends further
WSL mirroring; the Windows docs are now the active handoff.

## Multi-WebSocket architecture recommendation — 2026-09-19

`docs/MULTI_WEBSOCKET_DESIGN.md` records a proposed four-connection,
single-engine design, official source checks and Polymarket incident lessons.
D-016 records accepted requirements; the detailed design remains for review.
This is documentation only, not implemented code or performance acceptance.

## Documentation architecture — 2026-09-19

Core Polymarket-style routing is adopted: `AI_OPERATOR.md` is the shared
contract, AGENTS/CLAUDE are thin pointers, and `AI_ENGINEERING.md` carries
D-014's permanent WebSocket-first/REST-fallback/CPU/scalability rules.
`docs/ARCHITECTURE.md` is a design boundary, not implemented runtime code.
`docs/DOCUMENTATION_STRUCTURE.md` records the inspected checkout and ownership
map. `WATCHLIST.md` separates ideas from decisions; prior Claude text is
preserved under `docs/history/`. Whole-root compaction remains pending.

## Verified liquidity-reward research — 2026-09-19

`docs/LIQUIDITY_REWARD_RESEARCH.md` records current rules, the complete dedicated
reward endpoint contract, supporting APIs, missing personal reward interfaces,
current program statistics, static book examples, risks, and unresolved items.
`scripts/inspect_reward_apis.py` is a one-shot public GET-only inspector with
no credential or execution path. Its dated evidence is under
`data/reward-research/20260919T225211Z/`: 102 successful requests, complete
5,252-program active inventory (5,251 liquidity), and 40 book inspections.
Existing 45 unit tests passed; no strategy/trading implementation changed.
`scripts/audit_reward_research.py` independently verified 252 static scenarios
with Decimal arithmetic and produced `docs/LIQUIDITY_REWARD_AUDIT.json` with
evidence hashes and local-link checks.
The examples assume static books and exclude fills/fees: not live-income evidence.

## Verified documentation update — 2026-09-19

`docs/KALSHI_API_REFERENCE.md` is the local official API contract reference.
It contains 191 REST operations and 423 shared components, both full AsyncAPI
definitions (23 channels / 63 operations), FIX field tables and examples,
source links, authentication/price/fee/rate-limit notes, and discrepancy notes.
`docs/api-specs/` retains the five byte-identical published specifications.
The manifest records 247 successful fetches (240 pages, five specifications,
and two discovery indexes); the audit verifies all 191 operation blocks,
423 component blocks, source hashes, and 614 unique explicit anchors.

`scripts/build_api_reference.py` refreshes public documentation and generates
the Markdown; it has no account/credential/trading path. Its isolated dependency
is PyYAML 6.0.3 in `.docs-venv`. Raw source cache stays under ignored
`data/api-docs/`. `docs/API_REFERENCE_NOTES.md` is the maintained interpretation
input. No live bot implementation was added.

Older inventory below is historical; current authority is D-011/D-012.

Inventory of everything built, what it does, and how it was verified. Updated
when something is finished — not when it is started.

Companion files: `NEXT.md` (what to do next), `FINDINGS.md` (what we learned),
`BUGFIXES.md` (what broke and why).

Last updated 2026-08-27 22:19 America/New_York.

Current authority and scope are in `AI_OPERATOR.md`, `STATUS.md`, and
`DECISIONS.md`. Reproducing an old table means an instrument is operational; it
does not validate the reward-rule interpretation or establish profitability.

---

## Status at a glance

| phase | scope | state |
|---|---|---|
| Research | Reward rules | **resolved — July filing is current** |
| Research | Fee model, universe shape | measured, with named gaps |
| Instruments | Raw capture, signed reads, formula replay | **done** |
| Analysis | Reward share, two-sided rate, tick effect | **done** |
| Analysis | Fill cost, integrated net, ranking metric | **done** |
| Analysis | Exit cost | **corrected later-book replay done** |
| Analysis | End-date concentration | **not started** |
| Experiment 0 | Rule and accounting audit | **done** |
| Experiment 1 | Fixed-universe replay | **active** |
| Experiment 2 | Read-only live shadow | **replacement R3 active at `b970654`** |
| Experiment 3 | Minimal live evidence run | **not authorized** |
| Full bot phases | Package, executor, scheduler, deployment | **paused by D-001** |

The full-bot phases are deliberately not started. Current work is limited to
the evidence ladder in `EXPERIMENT.md`. See `STATUS.md` for blockers and
`NEXT.md` for the active queue.

---

## Instruments — built and working

### `scripts/strategy_policy.py`

Pure implementation of the current Polymarket entry-price rule, pinned to the
audited local/GitHub commit in `docs/POLYMARKET_REFERENCE.md`. It joins both
touches at a spread of at least 2¢ and otherwise centers an exact 2¢ window on
the price grid. No Polymarket API or project import is used at runtime.

**Verified:** seven unit fixtures plus a one-time read-only parity check against
the current reference function for wide, tight, locked, and half-cent books;
all quote pairs matched exactly.

### `scripts/record_books.py`

Raw capture of liquidity-incentive programs, order books, trades, and exchange
status. **Interprets nothing**: stores exact venue JSON with a timestamp.

| capability | detail |
|---|---|
| programs | all active liquidity programs, paginated, every ~15 min |
| books | `depth=100` (200 returns HTTP 400), per sweep |
| trades | 48h backfill on first sight, then overlapping windows, deduped on `trade_id` |
| exchange status | so closed-market gaps are not read as zero liquidity |
| errors | recorded as data, including sweep overruns |

Selection is capped per series (default 3) — without it the top 40 by
`reward/target` came back as 29 markets from one event.

**Verified:** running now, 40 markets across 18 series, 4,625 books and 2,531
trades, 1 non-fatal error (a sweep overrun, which is recorded deliberately).

**Revised 2026-08-18**, after two defects were measured (see `BUGFIXES.md`):

- **Sticky selection.** A ticker, once picked, is held until its program's
  `end_date` passes. Re-ranking from scratch every 15 minutes meant only **19 of
  82 markets survived a 20-hour run**, so churn was destroying period coverage
  faster than duration built it — and coverage is the guard that decides whether
  a market's share is trustworthy at all.
- **Terminal-state programs are polled too.** `status=active` was hardcoded, so
  a program's end state and any `paid_out` transition could never be observed.
  Checked live: `settled`/`ended`/no-filter return a different population.
- **`market_meta` refreshes** each program cycle instead of once on first sight,
  so a market settling mid-capture records its result.

**Current selection:** default `--rank-by density` scans books and ranks by
pool divided by measured competing score. Legacy `--rank-by target` is wrong
and comparison-only: `reward/target` is anti-correlated with revenue (FINDINGS
11). Density now uses the July reward reference through `reward_rules.py`; the
private February scorer was removed before the first server shadow. Real sample
spacing is the sweep duration, not `--interval` — read the timestamps.

**Server verification 2026-08-27 UTC:** deployed tracked commit `c135242` to
the standalone `/root/kalshi-bot` directory without copying credentials. All 25
tests passed there. A two-minute canary made public Kalshi reads only and wrote
65 book snapshots, zero non-200 responses, zero errors, and an integrity-clean
database. The 14-day transient service `kalshi-readonly-capture-14d` then
started with 75 tracked markets, 60-second sweeps, a 5-read/s limiter, hourly
density ranking, 20% CPU quota, 256 MB memory maximum, separate data/logs, and
no authenticated or order endpoint.

At the eight-hour operational checkpoint the service still had zero restarts,
zero recorder errors, and zero non-200 book responses. It was tracking 75
markets; the newest book was 30 seconds old. Hourly 1,000-candidate density
rescans take about 200 seconds and create a measured maximum active-market gap
of 267 seconds, which downstream reports must treat as missing capture time.

**Corrected after the first run:** one TLS EOF raised `URLError` outside the
HTTP-status handler and closed the intended 14-day capture at 9h51m. Public GET
requests now retry up to three times with bounded backoff; exhausted failures
return local status 599 so callers record the missing observation instead of
killing the process. Two network-failure fixtures raise the full suite to 27
tests. The exact commit passed the endpoint scan and all 27 tests on the server;
replacement R2 started at 2026-08-28 00:34:59 UTC with the original CPU,
memory, request-rate, process, data, and log isolation.

R2 was stopped cleanly by a host shutdown at 2026-08-28 01:22:04 UTC and its
transient unit did not return after boot. The same tested commit passed all 27
tests and the endpoint scan again; replacement R3 started at 02:17:05 UTC in a
fresh database/log with the same isolation and limits.

**Transport fix verified against a real failure:** at 10:27:03 UTC, R3 logged
an attempt-1/3 `URLError` caused by a connection reset, recovered without a
restart or traceback, and continued writing fresh books through the 12:58 UTC
check. No exhausted status-599 observation was required.

**Relocated to laptop 2026-08-29 UTC:** exact commit `0043c3a` was installed in
the standalone WSL path `/home/polybot/kalshi-bot` from a verified Git bundle.
The deployed checkout is clean and matches this PC and GitHub. The endpoint scan
found no account, order, or write method; all 27 tests and compilation passed.
A two-minute public-read canary closed cleanly with 70 books, 2,189 trades,
zero errors/non-200 books and SQLite quick check `ok`. Laptop R1 then started at
03:39:05 UTC with the same 75-market, 60-second, five-read/s, 20%-CPU and 256 MB
boundaries. A SQLite-consistent start checkpoint was mirrored to this PC; raw
data and logs remain gitignored and are not stored on GitHub.

### `scripts/kalshi_auth.py` — 127 lines

Signed read-only access. **No order function exists in this module and there is
no code path to an order endpoint.**

RSA-PSS/SHA-256 over `timestamp + METHOD + path`, where the signed path includes
the `/trade-api/v2` prefix and excludes the query string, timestamp in
milliseconds as a string, salt length = digest length. All four details are easy
to get wrong and fail identically with `token_authentication_failure`, so they
are documented in the module.

**Verified:** authenticated against the live account. Balance read, `/account/limits`,
positions, orders, fills, settlements all returning 200.

### `scripts/reward_rules.py` and `scripts/analyze_capture.py`

Pure, versioned reward arithmetic plus replay over captured raw books. The
default `july-2026-one-fifth` mode follows the July filing effective July 30;
the February best-bid mode remains for historical reproduction only. The
module has no network, credential, database, or order path.

Reports per `(ticker, side)`: two-sided rate, denominator, share at the touch,
share one tick inside, and a crowding flag when our own size would dominate the
side.

**Verified:** 11 hand-checkable unit tests cover both references, better levels,
Target Size failure, the two-sided gate, proposed-order insertion,
excluded-snapshot scaling, cent flooring, and the $1 minimum. On 58,453
`capture_long.db` snapshots, current mode gives a median inside/touch multiple
of **1.000x** over 112,492 sides; legacy mode gives **1.943x**. Every report
prints its rule mode, source date, effective date, status, and source URL.

### `scripts/markout.py` — 320 lines

Fill rates and markout for a resting two-sided quote, replayed over captured
books and the trade tape. Answers the half of `FINDINGS.md` 6g that the spread
analysis could not: whether the pair actually completes.

Reduces every trade to a signed YES-equivalent from the `yes_price_dollars` /
`no_price_dollars` pair and `taker_side`, never from `taker_book_side` — which
reports `bid` and `ask` in opposite frames for the same kind of trade. Queue
position follows from the quoting policy: joining a touch rests behind the
displayed depth, stepping a tick inside creates an empty level and is first in
line. Tick size is inferred per market from the observed price grid, because
market metadata carries no tick field and not every market is on a cent.

**Verified:** 140 non-overlapping one-hour windows, 44 markets. Produced the
near-zero-pair-completion result and the 8.6% both-directions-traded ceiling.
The fill detector was checked against a front-of-queue bound before the result
was trusted — it does produce fills and completed pairs when queue position is
removed, so the rate is a property of the tape rather than a broken predicate.

**Corrected 2026-08-17:** the headline "0 pairs" was a sample size, not a
property. At 1,064 windows the same code finds 7. See `pooled_markout.py` and
FINDINGS 6h.

**Known limits:** requires a full fill, counts no partials, gross of fees, and
assumes a static book — which is weakest exactly where the answer is most
favourable, since nothing models other makers stepping inside us.

### `scripts/sizing.py` — 250 lines

End-to-end revenue estimate: pool x our share, per market, with the filing's
two-sided rule and its $1.00 minimum payout applied. Reuses `analyze_capture`'s
`qualifying` and `share_with_order` rather than reimplementing the formula.

Encodes the payout chain's non-obvious steps: our fraction of the pool is the
**mean** of our two side shares, excluded snapshots scale down the payable pool
under the current rule, payout is floored to cents, and the $1 minimum applies
per program.

**Verified:** current-mode size-10 touch replay on `capture_long.db` reports
**$7.369/day** after the minimum across seven paid markets and $65.20 modeled
collateral. The legacy mode reports $93.414/day across 18 paid markets, which
demonstrates why the old rule cannot drive an August decision.

**Known limits:** only 10 of 52 markets survive the guards, at 10-25% period
coverage, so share is extrapolated 4-10x. Assumes continuous resting and a
static book.

### `scripts/pooled_markout.py` — 322 lines

Pools one-sided fills across every capture and settles their sign with a
**binomial sign test** and a **bootstrap CI on the mean**, at each size. Imports
`markout.py`'s fill predicate, queue model and YES-frame reduction rather than
reimplementing them.

Exists because the obvious approach failed. 6h said the sign needed a bigger n,
and widening the universe from 40 to 150 markets made the sample grow *slower*
— ranking by `reward/target` selects thin books, so added markets are quieter
than held ones. Accumulation is rate-limited by the same property that makes the
strategy work, so the fix was a better statistic, not more data.

The sign test is immune to the single −$1.75 outlier that made 6h's mean
useless; the bootstrap bounds the mean, which is what P&L is actually paid in.

**Verified:** produced FINDINGS 6i — drag −$0.1271/fill at 5 contracts, 95% CI
[−$0.2374, −$0.0369], sign test p=0.0014 at 300s. Re-measures fill rate and
markout independently at each size rather than scaling one number. Also
corrected two claims made from an earlier inline version of this analysis: the
captures are **not** independent (69 shared markets), and completed pairs are
7, not 0.

**Known limits:** pooled p-values are optimistic because of that market
overlap — the wide slate alone does not reach significance and its CI includes
zero. Reward per size is imported from FINDINGS 9 as a constant, not recomputed,
so the seam between the two measurements stays visible.

### `scripts/net_sizing.py` — 340 lines

Reward accrual and fill simulation on **one clock**, so the two stop
contradicting each other. `sizing.py` never reads the trade tape and assumes we
rest continuously; `markout.py` assumes we are filled. Adding their outputs
double-counts our presence during exactly the minutes a fill has our quotes
down. Here a fill takes the quotes down and the reward integral stops on both
sides, which is what section 2's two-sided rule requires.

Models two things `markout.py` deliberately did not: **queue position persists**
across snapshots while our price is unchanged (a real quoter holds its place),
and **partial fills** under `--fill-model partial`.

**Verified:** produced FINDINGS 10 — net **$10-$26/day** at 25 contracts on
$300 across 12 markets, roughly **40% below** the $31.76 that adding sections 9
and 6i gave. Persistent queue raises the fill rate to ~37/day against the ~11/day
6i implied, so 6i's rate is a lower bound from a pessimistic queue assumption.

Carries a **concentration guard**: drop a market whose best 10% of snapshots
carry over 30% of its reward score. Without it, switching from `sizing.py`'s
median to the formally-correct mean moved reward 44% ($37.44 to $53.98) — because
ranking by mean selects markets whose mean is inflated by a few thin-touch
snapshots. With the guard, mean and median agree within $3.

**Known limits:** `--flatten-seconds` is unmeasured and spans the answer by a
factor of 2.6, so the post-fill policy is now the dominant uncertainty. Gross of
fees, static book, shares extrapolated from 10-33% period coverage.

### `scripts/exit_cost.py`

What it costs to get flat after a fill, as realised P&L rather than markout.
Simulates passive close, timed taker cross, and recorded settlement. A timed
cross walks the first usable book at or after the deadline for the whole size
and pays the proven fee formula at actual VWAP. Missing, stale, and thin books
without settlement are explicit unknown exposure.

**Verified:** six unit tests cover later-only book selection, capture-gap
rejection, YES/NO ladder direction, fee charging, settlement signs, and passive
pricing. On `capture_long.db`, size 10 under the current Polymarket entry policy
and a 900-second deadline produced 84 simulated fills: 11 passive, 56 fully
crossed, 17 unknown, total priced P&L **−$27.8505**, mean **−$0.4157**, median
**−$0.3070**.

**Known limits:** its fill detector requires whole-order tape volume and differs
from `net_sizing.py` partial mode. Passive maker fees are unmeasured. At 900
seconds, 20.3% of fills are unknown, so the priced total is not a conservative
portfolio loss bound until those exposures are bounded.

---

## Documentation — built

| file | purpose |
|---|---|
| `AGENTS.md` | authoritative AI contract, boot sequence, and authority boundary |
| `STATUS.md` | canonical current truth and blockers |
| `DECISIONS.md` | accepted operator decisions and pending decision requests |
| `EXPERIMENT.md` | active evidence ladder and reporting contract |
| `NEXT.md` | ordered executable queue only |
| `FINDINGS.md` | durable evidence, hypotheses, and corrections |
| `BUGFIXES.md` | instrument bugs: symptom, mechanism, fix, verification |
| `docs/PLAN.md` | paused historical full-build design |
| `docs/REFERENCE_CRITIQUE.md` | dated reference audit; architecture versus calibration |
| `docs/REWARD_RULES.md` | governing sources and hand-checkable fixtures |
| `docs/PNL_ACCOUNTING.md` | canonical definition of measured net and unknown exposure |
| `docs/POLYMARKET_REFERENCE.md` | versioned current reference behavior and fidelity gaps |
| `README.md` | project entry point |

---

## What explicitly does NOT exist

No production package, `pyproject.toml`, or `src/kalshi_bot/`; no live risk
model, ledger, reconciler, or order code. Tests cover measurement arithmetic
only.

Nothing has placed an order. Nothing has committed capital. `$22.64` sits
untouched in the account.

This is the intended state. The instruments answer questions; the bot gets built
from the answers.

---

## Answered by what we built

- Taker fee formula, proven against two real fills
- Rate limits — 200/s reads, ~50x the reference implementation's assumption
- Two-sided rate — 85%, versus ~60% from an 8-market hand sample
- Under the current July rule, one tick inside adds no reward share on the long
  capture: median/p10/p90 all 1.000x over 112,492 side observations
- No short exists: selling YES is executed as buying NO
- The pair trade effectively does not complete — 7 pairs in 1,064 windows
  (0.7%), so reward is the only established revenue source and quoting one tick
  inside costs nothing realised
- One-sided fills are adverse — sign test p=0.0014, mean −$0.1271/fill at 5
  contracts with a bootstrap CI excluding zero
- A later-book exit replay measures adverse trading losses and preserves
  missing/thin exits as unknown instead of zero

### `scripts/program_timeline.py`, corrected `scripts/sizing.py`, and `scripts/portfolio_exit.py`

Program histories are matched to each book timestamp and accounted per program
ID. Edited program IDs and invalid periods are excluded rather than assigned a
favorable version. The reward portfolio integrates programs on the actual
capture clock, shares collateral across simultaneous programs on one ticker,
and excludes sparse hourly candidate scans. `portfolio_exit.py` replays entry
fills only while the selected program qualifies, persists displayed queue,
prices passive or timed-cross exits, charges estimated maker/taker fees, stops
reward during inventory, and carries unknown exits at zero and maximum-loss
bounds.

**Verified 2026-09-14:** 38 tests pass. The 12.97-day laptop R1 replay at size
10, 80% coverage, 100 snapshots/day, 30 markets and $300 produces $7.75/day
modeled hindsight reward. Combined central results are -$30.41/day (300s),
-$21.12/day (900s), and -$7.36/day (3600s). At 3600s with maker fees forced to
zero, central remains -$4.98/day.

## Still unanswered, and why

| question | why the instruments cannot answer it |
|---|---|
| `period_reward` scale | no earnings endpoint exists; likely needs a real payout |
| maker fee rate | both account fills were `is_taker: true`; needs one resting fill |
| `revenue: 0` on a settled position | needs a second settlement to compare |
| post-only support | needs an order placement, which the operator must run |
| cost of a fill in *lost reward* | needs open question 3 resolved: must our own orders be on both sides, or merely someone's? |
| whether 6h generalises | 44 politics/econ markets, ~14h of books, no sports |
