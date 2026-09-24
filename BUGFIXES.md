# Bugfixes — kalshi-bot

## 2026-09-24 — an unchanged approved deposit could acquire a false cash hold

**Mechanism:** The approved $500 ACH row originally had no `finalized_ts` and
was retained as boundary-relevant evidence. Kalshi later populated that field
with the original pre-boundary creation time. The relevance filter correctly
dropped the now fully pre-boundary row, but exact baseline matching mistook its
absence for unattributed cash activity even though its identity and economics
were unchanged.

**Fix:** Keep a separate bounded complete funding history from the same
cursor-exhausted source. A missing relevant approved row matches only when the
complete source proves the same applied deposit and all fields are identical
except for a null-to-integer finalization timestamp strictly before the boundary.
The complete history is non-authorizing. Omission, new activity, changed fields,
non-applied status and finalization at or after the boundary still block.

**Verification:** The focused opening/account-release tests, 274-test fast plus
native-supervisor gate and complete 1,667-test suite pass; the complete suite has
one expected Windows symlink-privilege skip. Live loading/restart is recorded
separately in [STATUS](STATUS.md).

## 2026-09-23 — transient failures could leave a healthy-looking bot unable to refill

**Mechanism:** Account/book readers retired after one three-attempt round while
the runtime continued. Three temporary account-repair failures cleared their own
request and parked permanently. Child health ignored both states. An unexpected
death recovered flat but deliberately disarmed, so orders were not rebuilt.
Exact compressed observation archives also retained a finite hard ceiling.

**Fix:** D-110 adds capped persistent reader rounds with a 60-second healthy
reset, classified transient REST repair cooldowns, explicit recovery/degraded
health projection, verified-flat crash recovery followed by a fresh normal
ranking/dispatch child, and cumulative hash-only rollover for superseded
observation archives. Manual stop, ambiguity, unknown mutations, integrity and
economic/loss holds remain fail-closed. Exact economic evidence is not rolled up.

**Verification:** See [the build record](docs/BUILD_UNATTENDED_RECOVERY.md) and
the current test/restart evidence in [STATUS](STATUS.md).

**Live acceptance:** Generation 106 stopped flat through the supported path.
Generation 108 loaded published commit `600b109`, ranked 1,024/1,024 markets and
rebuilt 30 orders across 15 $2+ priority markets. All readers are subscribed,
account proof is current, SQLite integrity is OK, and no risk, accounting, retry
or supervisor hold remains. Ten startup 429s were handled by ordinary retries.

## 2026-09-23 — repeated full recovery filled the journal and starved reward proof

**Mechanism:** At the exact 30-order/flat steady state, every expiring three-
second account report launched the full history/opening-account recovery. Each
pass took about three seconds, dirtied all 1,024 markets, expired most five-
second reward proofs and appended a new inspection, cash observation and
operational release. The 64 MiB hot journal eventually latched
`accounting_journal_full` and recovery exhausted.

**Fix:** A successful full recovery may establish a scheduling-only scope only
when ranking coverage is complete, all 30 venue orders exactly join to owned
non-reducing entries, the account is flat and all source/dispatcher/window gates
are current. That scope uses one exact account snapshot refresh and owner-only
deep evaluation while preserving all WebSocket ingestion. Any difference or
failure returns to full recovery. Superseded steady observations are atomically
compressed into bounded hash-verified archives; economic evidence is never
archived and archive identities remain deduplicated.

**Verification:** Real account/writer integration, changed-state escalation,
owner-only scheduling, archive/reopen/deduplication and capacity-hold regressions
pass. The maintained fast suite passes 257 tests; the complete suite passes
1,657 tests with one expected Windows privilege skip. The 1,024-market steady
benchmark processed every decision with a 0.0714 CPU ratio. No live process,
order or database was changed.

**Live acceptance:** The authorized restart exposed the expected old-build
terminal deadlock after all 30 orders were canceled and the account showed zero
positions/exposure. After exact-child forced termination was separately
authorized, the new recovery path archived 8,192 events, cleared the hold only
through a successful exact release and stopped flat. Normal generation 106 then
ranked 1,024/1,024 markets and reached 30 resting orders/zero positions. The
hot journal is below its trigger, SQLite integrity is OK and no accounting hold
remains. Long-duration finite archive growth remains follow-up work.

## 2026-09-23 — STOP generation fence broke clean child completion

**Mechanism:** Durable STOP correctly advanced the control generation and
revoked trading authority. The production child also treated that expected
generation difference as loss of its exact identity, so a cleanup-only parent
message raised `child admission revoked` after the runtime was already
`STOPPED_FLAT`. The latch path could additionally apply a second STOP from a
stale parent snapshot.

**Fix:** Exact parent session, child ID/generation and native binding still fence
identity. Control-generation change now revokes all non-cleanup authority while
allowing only `PULSE`, `STOP_HINT` and exact `FENCE_ACK`. The parent rereads the
durable state before a latch-derived STOP, making the normal external stop one
generation transition.

**Verification:** Unit coverage exercises generation mismatch with cleanup
traffic and rejects `ADMIT`; the native process test proves one generation
advance and clean disarm. Broader focused supervisor/runtime verification
passes, followed by the 1,650-test complete suite with one expected privilege
skip.

## 2026-09-23 — retained reward endpoints still missed the reconciliation cadence

**Mechanism:** Account refresh starts around report age three seconds and may
complete around age six, beyond the five-second queue-proof lease. The earlier
repair retained an endpoint but did not observe the still-valid portion while
the report was temporarily absent, leaving live measured coverage at 5.78%.

**Fix:** Telemetry alone can sample during an exact in-progress reconciliation
while the old proof remains unexpired and account generation/revision, writer,
owned-order signature, plan, book and program terms are unchanged. The sample
cannot satisfy `current()`, reflected quotes, selection, maintenance or
dispatch. It cannot extend the lease. Account revision is included in
continuity, and expired/changed evidence remains UNKNOWN.

**Verification:** Regressions cover direct and service-loop gap sampling, hard
account-revision invalidation, unchanged post-refresh bridging and a six-second
expired gap recorded wholly UNKNOWN. Focused reward/account/runtime verification
and the 1,650-test complete suite pass.

## 2026-09-23 — one-sided full-weight incumbent could retain a slot forever

**Mechanism:** An acknowledged cancellation left one owned entry resting. Its
surviving quote still had full price weight, while a fresh replacement pair was
below the $1 projected-reward minimum. After the 90-second evidence dwell,
maintenance started a cycle only for a qualifying target or an actual-row
blocker; this exact combination had neither and therefore never transitioned.

**Fix:** A fresh incomplete pair whose replacement target is below minimum now
starts an exact non-reentry maintenance cycle after the existing 90-second
dwell. The ordinary ranked selector may use the released capacity afterward.
Qualifying incomplete pairs still use the 30-second same-program repair.

**Verification:** The regression fails on the prior source with 92 seconds of
verified dwell and no cycle. Both incomplete-pair branches pass after repair.
Focused maintenance, dispatch and live-runtime suites pass 140 tests; the full
suite passes 1,647 tests with one expected Windows privilege skip. No live
process was changed during offline verification.

## 2026-09-23 — normal account refresh erased reward coverage and logs rotated too quickly

**Mechanisms:** Every short account reconciliation temporarily removed the
current report. Reward telemetry correctly revoked current authority but also
deleted the previous leased sample, preventing the next identical exact queue
join from measuring any interval. Separately, the production child used only
three 256 KiB log files; generation 92 rotated them in about 3.4 minutes.

**Fix:** Temporary report loss and superseded reads now suspend live proof while
retaining only the prior in-memory interpolation endpoint. The unchanged tracker
still requires overlapping five-second leases, identical continuity and exact
owned-order identity; any gap or mismatch is UNKNOWN. Hard source conflicts and
epoch changes still clear the endpoint. Child diagnostics now use a 12 MiB
current file plus seven backups (96 MiB bounded total), with the configured
retention exposed in status.

**Verification:** Regressions prove a one-second exact refresh bridge, a six-
second wholly unknown gap, missing-report deferral, superseded-read suspension,
hard publication invalidation and the production retention bound. Focused
affected suites pass 328 tests with one expected skip. The complete suite passes
1,645 tests with one expected Windows privilege skip; compile and whitespace
checks pass. No live process, order or configuration was changed.

## 2026-09-23 — manual venue close left the durable ledger long

**Mechanism:** The operator closed one 10-contract position at the venue while
recovery was active. Venue orders and positions were flat, but the bot ledger
still held the opening fill and correctly blocked on inventory mismatch and an
unbound external fill. Inventing bot ownership or deleting the ledger would
have corrupted accounting.

**Fix:** A stopped-owner-only primitive accepts one exact, independently audited
terminal fill only when it exactly flattens local inventory. Its external scope
is retained separately from bot-owned order evidence, included in cold cash
validation, and recognized as an immutable duplicate by later history recovery.
The production ledger was backed up, reconciled to zero position, and retained
the exact $0.665 close loss.

**Verification:** Focused account/recovery suites pass 126 tests. The complete
suite passes 1,641 tests with one expected Windows privilege skip; compile,
whitespace, SQLite integrity and cold cash checks pass. Source commit `9fad565`
is published and deployed. Recovery-only stopped flat, then generation 92
completed 1,024/1,024 ranking and began quoting with no position.

## 2026-09-23 — deterministic cancel 404 crashed recovery

**Mechanism:** Kalshi could return a deterministic absent-target `404` after an
order was already gone. The mutation path treated it like an unexpected error,
crashing recovery and retaining unknown cleanup state even though the specific
cancel could not execute later.

**Fix:** Exact deterministic cancel `404` and create `400` responses are durable
terminal `REJECTED` outcomes. Network ambiguity and server failures remain
unknown and fail-closed.

**Verification:** The complete suite passed 1,639 tests with one expected skip.
The deployed recovery pass cleared resting entries without the prior crash.
Source commit: `16256f2`.

## 2026-09-23 — final priority-admission review exposed three false states

**Mechanisms:** Any candidate blocker was treated as transient, so a fresh
`market_inactive` result could preserve the old $2 hint and indefinitely block
$1 fallback. The revalidation batch advanced only when completely empty, so one
stalled member prevented all later remembered candidates from entering the
window. Dispatch-selection evidence was written while preparing a candidate,
allowing an attempt revoked before transport to look like an admitted order.

**Fix:** Only missing timing/fee proof and exhausted metadata remain pending;
fresh definitive candidate blockers retire the hint. Each proposal tops the
bounded pending set back up without duplicating current/protected work. Entry
evidence is staged by exact batch/client IDs and published only from the
dispatcher result for ACK or a partial venue outcome; callback failure stops the
dispatcher.

**Verification:** Regressions cover hard ineligibility versus temporary
exhaustion, a stalled member plus later-batch progression, successful ACK
correlation and revoked-not-sent omission. Focused dispatch/selection/runtime
verification passes 152 tests. The complete suite passes 1,638 tests with one
expected Windows privilege skip; compile and whitespace checks pass. Reviewed
source commit: `f6b9e3f`.

## 2026-09-23 — historical coverage forgot temporarily invalidated priority rows

**Mechanism:** Startup coverage remembered only that a ticker had once been
evaluated. Account or metadata revocation deleted its selector row, so a formerly
eligible $2 candidate became invisible while a recovered $1 fallback could be
admitted. The actual entry loop also returned before the proposal method that
owned early priority-capacity release, and coverage stopped progressing after
that release.

**Fix:** Selection retains one bounded advisory priority hint per ticker and
revalidates stale hints in batches of at most twice available pair slots (30 at
the current cap). The metadata scheduler prioritizes that bounded batch after
owned maintenance. Missing, exhausted or delayed evidence defers fallback;
fresh changed economics, program removal or expiry retires the hint. The entry
loop can now exercise early release and source events continue coverage without
ledger polling. Hints never satisfy current entry or dispatch checks.

**Verification:** Synthetic regressions cover account-wide row invalidation,
fallback deferral, fresh downgrade, bounded later batches, scheduler priority,
runtime early release, continued coverage, source-event wakeup and dispatch-tier
evidence. The complete suite passes 1,636 tests with one expected Windows
privilege skip; compile, whitespace and documentation checks are part of
publication. Reviewed source commit: `9a20e57`.

## 2026-09-23 — owned metadata starvation and false clean-stop failure

**Mechanisms:** Four book shards delivered and evaluated all 1,024 markets, but
the separate metadata scheduler gave incumbent order markets no priority over
the full optional discovery set and used only two broad workers. Current owner
metadata could therefore expire before its next turn. During the subsequent
verified-flat stop, an already in-flight parent `PULSE` arrived after the child
latched stop; the child treated it as revoked authority and exited before
publishing its terminal fence, so the supervisor recorded `unknown_failure`.

**Fix:** Broad discovery uses four bounded metadata workers. Due tickers with
inventory, owned orders or maintenance bindings are selected before FIFO
discovery work. Stop-latched children accept liveness-only `PULSE`, `STOP_HINT`
and exact `FENCE_ACK` messages while still rejecting `ADMIT` and all trading
authority; parent identity/death checks are unchanged.

**Verification:** Priority scheduling, broad-runtime construction, active-owner
classification and stop-latched message regressions pass. The affected 120-test
set and exact three-test composition set pass; the complete suite passes 1,630
tests with one expected skip. Recovery-only generation 75 stopped flat and
disarmed without the prior false failure. Normal generation 76 reached metadata
high-water four, 1,024/1,024 ranking coverage and 15 simultaneously observed
owned markets. Full live evidence belongs in `STATUS.md`.

## 2026-09-23 — invalid passive reducer, stranded due IOC and partial fallback

**Mechanisms:** Kalshi rejected passive GTC creates carrying `reduce_only=true`;
after bounded recovery exhausted, the existing due IOC could not reacquire proof
until process replacement. Separately, a 120-second partial ranking release let
$1 fallback orders consume slots before known-later $2 candidates.

**Fix:** Passive GTC exits use the venue-valid false wire flag but retain exact
durable `managed_exit` authorization and an ephemeral single-create transport
arm. IOC stays venue-enforced reduce-only. A due inventory episode rearms one
fresh recovery. Incomplete timeout stays closed; full current $2 capacity may
open priority-only while historical coverage continues. Four measured book
shards replace two in prepared configuration.

**Verification:** 1,024/1,024 books and 100% five-second freshness were observed
in all four two/four-shard stages; four shards passed both complete target sets.
Focused 402-test verification passes. Final review also caught and repaired the
event engine's stale two-shard constructor bound. The post-fix complete suite
passes 1,628 tests with one expected skip. Full results:
[D-103](docs/BUILD_EXIT_COVERAGE_PRIORITY.md).

## 2026-09-23 — current queue evidence discarded and post-drain recovery stranded

**Mechanism:** Queue reflection unnecessarily depended on current market plans
at publication; transient plan/metadata gaps (including a status inspection)
deleted its separate account-bound proof. Incumbent drift could therefore fail
to accumulate even with unchanged orders. During rapid paused cancellation,
account repair could exhaust before the queue finished, without a final wake.

**Fix:** Publish bounded queue identity from the exact complete account report;
consume it only with fresh matching owned inventory, book and reward terms.
Temporary market gaps invalidate sampled rates without renewing or deleting a
still-current queue lease. Account/epoch invalidation, changed quantity/price,
and the original five-second expiry still defeat use. Superseded reads have a
separate counter; real failures emit bounded stack-only diagnostics. A durable
paused-cancel outcome requests one bounded post-drain reconciliation when both
dispatch and any in-flight repair are idle; no new outcome means no new retry.

**Verification:** Regression/full-suite evidence and review are recorded in
[D-101](docs/BUILD_REPRICING_SOURCE_JOIN.md). Generation 68 then completed two
live exact-pair reference repairs, returned to 30 orders and recorded no fill or
position through acceptance. The repaired final-drain wake remains pending the
next operationally necessary stop; do not stop solely to manufacture that test.

## 2026-09-23 — history receipt capacity killed the writer

**Mechanism:** Recovery appended one immutable enumeration receipt about every
few seconds. All 4,096 live receipts covered the same growing interval; reaching
the fixed hot-row cap raised inside `history_complete`, permanently failed the
serial writer and triggered a recovery-only supervisor replacement. The
replacement drained locally known entries but could not establish current
account proof. Metadata publication races and quota holds were also double-
reported as ERROR even though their scheduler paths were retry/defer states.

**Fix:** At the hot cap, validate and compress every exact receipt into one
content-addressed append-only archive row, then delete the hot rows and insert
the new current receipt in the same SQLite transaction. Archived rows remain
audit evidence and an explicit continuity blocker, never current account
authority. Overtaken metadata reads retry without consuming failure budget;
quota holds defer without dependency-failure logs.
Reward reflection also waits for a current clean account report instead of
counting the missing prerequisite as a failed reflection every four seconds;
successful recovery already requests an immediate join.

**Verification:** Rollback injection preserves all hot rows when archival fails;
scope/time tests prevent unrelated archives from blocking; an existing schema-5
ledger adds the archive table safely. A disposable 4,097-receipt run left one
hot receipt, preserved 4,096 exact receipts in one 88,318-byte archive and had no
coverage gap. No production ledger was modified or copied.

## 2026-09-23 — maintenance starvation, reducer rejection storm and log flood

**Mechanisms:** A valid reference-drift sample arriving just over five seconds
after the prior sample erased the 30-second dwell, so normal account/reflection
cadence could postpone repricing forever. One passive inventory reducer then
received deterministic HTTP 400 responses 79 times across four prices because
each fresh client ID bypassed prior rejection evidence. Broad discovery also
logged completeness changes for hundreds of empty markets, rotating three log
files through roughly ten seconds of history.

**Fix:** Count only explicitly fresh evidence coverage across gaps up to 15
seconds and bind cancellation to an exact current owner/program/account lease.
Successful account recovery wakes coalesced reflection. Persist consecutive
identical reducer rejection backoff at 10/20/40/60 seconds; material order-term
changes remain immediately eligible. Capture only a validated venue error code,
never raw error text. Log inventory-plan changes only for material markets and
one final transition after they become empty.

**Verification:** Live-like 6-second cadence, long gap, ownership/lease race,
restart-durable rejection, exponential delay, error-body bounds and 1,024-style
empty-market logging regressions pass. Deliberate reversals failed the relevant
tests. Full-suite and publication evidence are recorded in STATUS.

## 2026-09-23 — paused drain serialized on recovery and terminal fence was rejected

**Mechanisms:** Every stopped-session entry-cancel outcome revoked continuity and
started full REST recovery before another cancellation. Thirty entries therefore
took about 70 seconds to drain. Once flat, the child control path treated the
already-latched stop as revoking its terminal `FENCE_ACK`, producing a false
failure and shutdown timeout.

**Fix:** A safety-only writer query selects one exact owned, nonterminal,
nonreducing entry with no submitted/uncertain prior cancel. While entries are
paused, the sole dispatcher may drain those exact orders back-to-back through
the existing durable mutation pipeline; normal reducers and live maintenance
keep their original recovery behavior. Terminal fencing permits only
`STOP_HINT`/`FENCE_ACK` after authority is revoked and still requires exact
generation, child, parent-session and native binding.

**Verification:** Two regressions prove same-market paired entries drain without
REST recovery; terminal tests prove the fence succeeds only with exact identity
and a live parent while a trading pulse remains rejected. The complete suite ran
1,591 tests successfully with one expected Windows privilege skip. Live speed
must be measured on the next operationally required controlled stop.
Recovery-only generation 62 subsequently completed `STOPPED_FLAT` and disarmed
normally, live-verifying the terminal-fence half of the repair.

## 2026-09-23 — passive deferral, cancellation order and resting cap enforcement

**Mechanisms:** `passive_deferred` could not enter passive dispatch or writer
authorization; passive cancellations followed lexical IDs rather than removing
building exposure first; the ratchet applied to admissions but not live overflow.

**Fix:** Keep exact passive management after ordinary depth/loss deferral,
prioritize building-side cancellation and actively withdraw owned flat overflow,
retaining complete pairs first. No changed exit loss, capital or contract limits.
Three new regressions fail when their fixes are reversed in memory. Full details
and incumbent-maintenance integration: [D-098](docs/BUILD_ORDER_MAINTENANCE.md).

Bugs that reached an instrument or runtime. Symptom, mechanism, fix — written
when fixed, not at the end of a session. Companion to `FINDINGS.md`. Each live
entry states whether orders, positions or exposure were observed.

---

## 2026-09-23 — transient Windows status replacement stopped live children

**Mechanism.** `status.json` publication performed one `os.replace`. A Windows
reader denying delete sharing could make that call raise `PermissionError`; the
runtime correctly failed closed, but a momentary local diagnostic-file conflict
therefore stopped both normal and recovery children. Repository status readers
also used ordinary opens without an explicit delete-sharing contract.

**Fix.** D-097 makes repository status readers request read/write/delete sharing.
Atomic JSON publication now uses a unique same-directory temporary file and a
bounded two-second retry only for `PermissionError`. Other errors and exhausted
contention still propagate. The old complete file remains authoritative until a
successful replace; failed temporary artifacts are removed.

**Verification.** A native Windows test holds the destination open while denying
delete sharing and releases it after 100ms; publication then succeeds with a
whole current document. Synthetic transient and permanent-denial tests cover
retry, bounded failure, old-document preservation and cleanup. Complete suite:
1,557 tests, one expected privilege skip. No live restart was performed.

## 2026-09-23 — early fallback entries consumed capacity before broad ranking

**Mechanism.** Entry dispatch consumed incremental rankings immediately, allowing
early $1 fallbacks to fill capacity before later $2 candidates were evaluated.

**Fix.** D-096 adds a bounded initial combined-coverage checkpoint on new entries
and direct entry dispatch. Current-source selection follows coverage or timeout;
inventory/cancellation processing is independent. This does not add incumbent
replacement or guarantee all markets remain fresh simultaneously.

**Verification.** Opposite-shard arrival-order, missing metadata, timeout/staleness,
source-generation, direct dispatch and safety tests; [contract](docs/BUILD_INITIAL_RANKING.md).
Final verification/deployment evidence belongs in STATUS.

## 2026-09-23 — expired public candidate scope blocked normal restart

**Mechanism.** Candidate preparation ran only for first-ledger initialization.
A later normal restart loaded the prior scope directly, so any expired timing
review blocked before fresh account reconciliation even though preparation is
public-only and already supervised.

**Fix.** Every explicit normal supervisor arm now runs the existing bounded,
credential-free candidate preparation before input loading. Recovery-only stays
narrow and does not expand discovery scope. All subsequent source/account/order
gates remain unchanged.

**Verification.** Production startup regressions assert normal preparation and
the existing supervised stop/cancellation behavior; recovery-mode construction
remains non-initializing. Final suite results are recorded in STATUS.

## 2026-09-23 — terminal-dependent host and misleading saved health

**Mechanism.** The foreground launcher coupled supervisor life to its terminal;
the status command returned old healthy control/runtime snapshots without a
current presence check. The earlier actual process-exit cause remains unknown.

**Fix.** D-094 separates the on-demand host from the console/job, fails visibly
if the OS denies independence, correlates startup receipts and never equates
startup with trading readiness. Protected-role probes label historical health
as historical and expose stopped/unknown process state without PID adoption.

**Verification.** Native inert launcher/job exit, controlled shutdown, failure
and stale-status regressions pass; [details](docs/BUILD_HOST_CONTINUITY.md).
Separately, GET evidence confirmed 28 manual cancellations with zero fills;
those local records were repaired, with no orders sent or bot restart.

## 2026-09-23 — normal discovery tied book coverage to rotating admission

**Mechanism.** Watching 128 books with 16-market replacements delayed discovery
of qualifying candidates; repeated detail metadata reads increased cold coverage
cost. Simply expanding the watchlist would also enqueue entry attempts for every
candidate against a 128-key dispatcher.

**Fix.** D-093 watches the bounded reviewed universe, shares bulk definitions,
retains complete fee/source checks and queues one fresh ranked entry key per
bounded idle turn. Risk/account limits remain separate. Revision-bound inventory
reuse avoids repeated durable reads for unchanged state.

**Verification.** Full-scope, priority, source-race and cache regressions plus
actual composed fake-ACK tests; 1,024-book runtime benchmark; public-only census
90.073s, 1,013 examined, 150 passing, no final source errors.
[Evidence and limitations](docs/BUILD_BROAD_DISCOVERY.md). No restart or orders.

## 2026-09-22 — partial subscriptions skipped exploration candidates

**Symptom/mechanism.** Discovery advanced past every proposed tail ticker, but
admission subscribed at most 16. With 14 protected synthetic markets, 332 of
1,024 never reached the book set. The exact historical 28-order blocker remains
unproved; this is a reproducible contributing coverage defect.

**Fix.** D-091 advances pending order only for the actual subscribed scope,
preserves unjoined candidates, and uses bounded 30-second refill when another
pair fits a fresh risk window. Existing gates/limits are unchanged. Timestamped
selection and dispatch reasons now survive idle status.

**Verification.** All 1,024 reached in the 14-owner reproduction; old-code
counterfactual fails the new regression. Coverage, defer, churn, dwell, cap and
outside-seed fifteenth-pair tests added. [Build](docs/BUILD_DISCOVERY_COVERAGE.md).
No venue calls, runtime launch or production ledger changes in this repair.

## 2026-09-22 — lifecycle snapshot permanently overflowed its reader queue

**Evidence correction:** the 5,018/5,060 counts below came from the REST incentive
catalog, not measured lifecycle frames. Queue overflow was verified, but the
burst size and snapshot/replay explanation were not. See the
[investigation](docs/INVESTIGATION_LIVE_EXIT_2026-09-22.md#earlier-eligibility-and-lifecycle-claims).

**Symptom.** The normal live restart repeatedly moved the lifecycle reader from
subscribed to retry wait, paused new entries and never completed current market
admission. Four retries ended at `transport._receive` queue overflow. Fourteen
orders were observed, no positions; controlled stop reached verified flatness.

**Mechanism.** Kalshi's unscoped lifecycle subscription emitted about 5,018
initial active-market rows. `readonly_reader_factory` had reduced every
single-stream queue from the transport default of 8,192 to 256, so reconnecting
only replayed the same oversized snapshot.

**Fix.** D-090 restores the existing bounded 8,192-event / 16-MiB transport
limits only for lifecycle. Account and scoped-book readers remain at 256 / 2 MiB.

**Verification.** A regression locks the per-stream bounds; 127 affected tests
and all 1,482 repository tests pass (one expected Windows privilege skip).
Live deployment loaded 5,060 lifecycle markets on attempt one with no retry
round, while all readers, account proof and bounded entries remained healthy.
[Report](docs/BUILD_LIFECYCLE_SNAPSHOT_BUFFER.md).

## 2026-09-22 — pre-transport proof change falsely became UNKNOWN

**Symptom.** Two recovery cancellations never reached transport but were marked
`UNKNOWN`, blocking safe cancellation reauthorization and leaving two orders.

**Mechanism.** The executor treated durable `SENDING` as the network uncertainty
boundary even though final source/account/revision checks still preceded the
injected transport call.

**Fix.** D-089 adds a sole-executor, transactional, all-or-none proven-unsent
transition to `NOT_SENT`/`ABORTED`, releases applicable intent capacity and
re-signals recovery. Post-invocation failures remain UNKNOWN.

**Verification.** Single/batch races assert zero transport calls, exact capacity
release, ownership and recovery signaling. The complete suite passes 1,481 tests
with one expected Windows privilege skip. Historical live-row correction and
recovery remain separate operations. [Report](docs/BUILD_PRETRANSPORT_ABORT.md).

## 2026-09-22 — graceful drain exhausted after three successful cancellations

**Symptom.** An authorized stop reduced 14 resting entries to 9, then remained
`DRAINING`; the supervisor retained the child and reported `shutdown_timeout`.

**Mechanism.** Each acknowledged safety cancel correctly invalidated its source
report and requested a fresh reconciliation. The recovery owner counted those
progress-making cycles against its three-attempt failure budget, exhausted, and
could no longer authorize the remaining cancels in that process.

**Fix.** D-088 starts a fresh bounded failure budget only when the preceding pass
was source-consistent, incremented the completed-pass counter and received a new
recovery request. True no-progress failures still exhaust after three attempts.

**Verification.** A five-progress regression reaches a sixth repaired pass with
no retry delay. Removing the new branch reproduces exhaustion after three. The
focused 156-test set and final 1,479-test suite pass (one expected skip).
[Report](docs/BUILD_GRACEFUL_DRAIN_RECOVERY.md).

## 2026-09-22 — lifecycle reader could not recover after three startup failures

**Symptom.** The live child continued with books/account connected but lifecycle
permanently `retry_exhausted`, preventing that source from recovering in-process.

**Mechanism.** The shared connection owner returned normally after one finite
attempt round. That is intentional for financial/sequence readers but left the
advisory lifecycle reader with no later owner.

**Fix.** D-087 adds lifecycle-only capped retry rounds, monotonic generations,
explicit `retry_wait` status and structured diagnostics. Existing disconnect
revocation and all account/book exhaustion contracts remain.

**Verification.** Fourth-attempt recovery after 1/2/30-second synthetic delays;
161 focused tests pass. Exact original live transport cause is unavailable due
to log rotation, so no unsupported cause is claimed. [Report](docs/BUILD_LIFECYCLE_RECONNECT.md).

## 2026-09-22 — avoid unnecessary catalog pages and refresh quiet books

**Symptom.** Reward discovery exhausted on timeouts; otherwise qualifying quiet
books aged beyond the existing five-second source gate.

**Mechanism.** Both catalog consumers requested only 100 rows despite larger
documented pages. The book reader never requested fresh snapshots after initial
subscription. Transport queue delay could also be hidden by callback-time age.

**Fix.** D-086 shares a 1,000-row query; adds bounded connection-local WS snapshot
requests; and carries actual transport ingress time into the book engine.
Correlated responses retain sequence/depth/generation checks and fail-closed
timeouts. No stale-data relaxation, retry reset or filter change.

**Verification.** Synthetic pagination, actual transport and runtime-selector
regressions plus resource checks. See [report](docs/BUILD_REWARD_SOURCE_REFRESH.md)
and STATUS for suite/publication. Live deployment/acceptance is separate.

The full run also exposed a frozen-clock admission fixture: a legitimate
one-second deferral could wait forever at a fixed injected time. A controlled
injection reproduced this on unchanged source. Only the fixture wait now advances
its retry clock; a regression preserves normal joined shutdown assertions.

## 2026-09-22 — metadata workers starved live market admission

**Symptom.** The live bot rested 12 orders on six markets while a much broader
reviewed candidate set existed; admission reported zero completed rotations.

**Mechanism.** Scope replacement required metadata workers and shared dependency
reads to be idle. The scheduler immediately filled each freed worker slot, so
admission had no cooperative way to obtain that idle handoff.

**Fix.** Add one exact, bounded metadata-rebind reservation. Existing work drains
without launching replacements; admission then repeats every existing fresh
account/inventory/source proof before committing. Reservations expire after five
seconds and clear on rebind or shutdown. Preserve independent shard attempts
when a non-metadata safety proof defers.

**Verification.** New tests cover drain-without-refill, abandoned-reservation
expiry and admission retry after drain. Focused scheduler/admission and composed
live-runtime suites pass. The complete suite ran 1,453 tests: 1,452 passed and
one expected Windows privilege skip. Following D-085's exact operational
correction and verified flat recovery, the normal live run completed two scope
rotations. Wider order occupancy is not inferred from that result; current
observations and the one-time correction are recorded in FINDINGS section 124.

## 2026-09-22 — first live opening attribution and interrupted resume

- **Symptom:** The first supervised live initialization captured a flat account
  but failed opening approval, then bounded recovery children refused the
  partial ledger. No order was placed and exposure stayed zero.
- **Mechanism:** Kalshi retained an applied personal deposit and completed
  intra-exchange transfer without completion timestamps. Durable accounting
  correctly raised `cash_activity_unattributed`, but had no explicit
  personal-opening attribution operation. After the first writer failed, later
  children saw an immutable checkpoint without a baseline and had no mode to
  refresh and approve that same checkpoint.
- **Fix:** D-084 makes opening approval bind exact retained event digests only
  when every cash row is a completed pre-boundary personal deposit or completed
  pre-boundary intra-exchange transfer. It rejects pending/withdrawal/
  subaccount/later activity and every other economic hold. The supervised
  initialize profile can refresh and resume an existing unapproved checkpoint;
  it never recreates the ledger or boundary.
- **Verification:** Focused durable-accounting, account-release and production-
  supervisor tests pass, as do the broader recovery and complete live-runtime
  suites. The full suite ran 1,444 tests in 220.622 seconds: 1,443 passed and
  one expected Windows privilege skip. Live-relaunch evidence is recorded in
  the linked [implementation report](docs/BUILD_FIRST_LIVE_OPENING_RECOVERY.md).

### Clean supervisor shutdown left exact inherited SQLite sidecars

- **Symptom:** The corrected re-arm stopped before a child started because the
  protected supervisor store rejected its own WAL/SHM files.
- **Mechanism:** SQLite recreated its sidecars during final close. Windows gave
  them the protected parent directory's exact user/System full-control ACEs,
  but marked the DACL and ACEs inherited; the validator accepted only the same
  grants marked explicitly protected.
- **Fix:** Only WAL/SHM/journal sidecars may use either exact representation.
  The root and database still require protected explicit DACLs; sidecars with
  any additional principal or permission still fail. The files remain pinned
  and revalidated through retained handles.
- **Verification:** A native regression recreates exact inherited sidecars after
  clean owner close and reopens the protected guard. Existing replacement,
  reparse, DACL and pinning reversals remain active. The current complete suite
  ran 1,445 tests in 218.331 seconds: 1,444 passed and one expected Windows
  privilege skip.

### Recovery-only flat fence raced the required second accounting pass

- **Symptom:** The resumed checkpoint was approved and the supervisor disarmed
  flat, but shutdown left `accounting_source_failed` and
  `opening_proof_unresolved`; normal entry would remain blocked.
- **Mechanism:** Approval deliberately queues a second recovery pass to obtain a
  post-approval writer revision and operational release. The flat fence checked
  the current empty account but not the queued/in-flight recovery owner, so it
  stopped the runtime between those passes. Cancellation of the retained account
  inspection correctly persisted a source-failure hold.
- **Fix:** `STOPPED_FLAT` now requires both an idle recovery lock and no queued
  recovery request before its existing account/writer/risk checks. It never
  clears a hold directly; the next fresh release transaction resolves the
  transient source/opening holds with retained evidence.
- **Verification:** A regression proves both queued and in-flight recovery block
  flat termination and that the same flat proof succeeds after the owner is
  idle. The 75-test focused set and complete 1,446-test suite pass; the latter
  ran in 219.163 seconds with 1,445 passed and one expected Windows privilege
  skip. Live recovery against the retained ledger remains the final check.

## 2026-09-22 — final current production-path integration repairs

- The $25 loss hold blocked new selection but left existing entry orders live.
  It now becomes the same effective entry pause/drain used by supervised stop,
  while normal inventory exits and restart-persistent risk ownership remain.
- Selection authority ended before the writer's final send fences. The exact
  program/observation/source proof is now pinned through preparation and SENDING;
  revocation or expiry produces no transport call.
- Exact owned cancellation incorrectly inherited book and terms freshness from
  price-dependent creates. Its proof is now account/order/writer based; creates,
  reducers and IOC retain all prior market proof.
- Program deduplication ran before the $1/$2 qualification tiers. Qualification
  now runs per program, then chooses one program per market without summing.

Verification: permanent nonfixture send-boundary, loss-drain, stale-source cancel
and overlapping-program regressions pass with related component suites and all
30/120 selection/admission/dispatch gates. A GET-only startup also passed; no
trading runtime, credential exposure/mutation, production ledger or order
endpoint was used. See the
[implementation report](docs/BUILD_CURRENT_PATH_REPAIRS.md).

## 2026-09-22 — zero-candidate timing filter

- The safety correction that withdrew blanket early-close approval left the
  current public catalog with zero automatically eligible markets.
- D-082 admits only the exact scheduled-economic-data release family when the
  occurrence timestamp and sole future primary milestone are present and safe.
  The occurrence timestamp is rules-bound; current metadata rechecks the family
  and rejects later/conflicting milestone clocks before entry.
- Unknown early-close conditions, unsupported milestone types, missing clocks
  and sports remain excluded with explicit reasons. Active reward-program
  membership and fresh-book ranking remain separate runtime requirements.

Verification: 8 candidate-preparation tests, 46 market-input tests and the full
suite pass: 1,431 run, 1,430 passed and one expected Windows privilege skip. A fresh public
refresh produced 1,024 validated candidates; a read-only startup verified the
feed graph without creating a ledger or order.

## 2026-09-22 — production supervisor end-to-end lifecycle repairs

- Account ownership previously ended before exception-path runtime drain. The
  lease now remains held until the retained runtime task and resources join.
- Production omitted durable quota state. Read/write cooldowns and exhaustion
  now persist atomically at the component transition, cross authenticated
  recovery fences, and are restored before any recovery activity.
- Temporary risk/accounting blockers were promoted to permanent retry holds.
  Health phase and durable process restrictions are now separate.
- Candidate preparation and inherited cooldown waits now service heartbeat,
  status and stop; pre-runtime stop cannot claim an existing account is flat.
- Recovery now removes expired unrelated candidates but refuses a missing or
  expired durable-owner review. Exit 27 and unknown production exits preserve
  possible ownership. Verified-flat status is persisted only after cleanup.

Verification: nine direct repair regressions, 1,428-test full suite (1,427 pass,
one expected skip), native 60-second supervisor and 30/120-market resource gates.
No live runtime or external service was used. Full mechanisms and evidence:
[D-081 review](docs/REVIEW_D081_END_TO_END.md).

## 2026-09-22 — automatic candidate launch blockers and timing authority

- First initialization emitted an unregistered diagnostic event, poisoning the
  logging health gate before runtime. The event and bounded count fields are now
  part of the static schema and covered with the real diagnostics writer.
- A full 128-market seed set was unioned with rotated-in inventory, so one later
  owner made restart exceed capacity. Durable positions, order exposure and
  pending fills now take slots first; optional seeds fill only remaining room.
- Automatic preparation marked every market's early-close rules reviewed even
  though it only hashed their text. The correction excluded early-closing
  markets and made legacy blanket approvals fail closed. D-082 later adds one
  exact, separately reviewed scheduled-release family; it does not restore the
  blanket approval.
- The T-5 filter ran before milestone uniqueness, allowing an imminent binding
  to disappear and a later binding to become the deadline. Uniqueness now runs
  first and a sole imminent binding receives its own exclusion.

Verification: 62 focused tests passed. Full offline suite: 1,412 run, 1,411
passed and one expected Windows privilege skip. No bot process, account request,
order endpoint or live input file was changed.

## 2026-09-22 — one-market discovery bottleneck

- The reward filter/ranker was connected, but its candidate authority came from
  an ignored file containing one ticker. It could not compare markets.
- Public preparation now joins active reward programs to complete current rules
  and one future primary milestone, with bounded exclusions and exact digests.
- Candidate authority (1,024), active books (128) and resting entries (30) are
  separate. A 30-market cheap head plus stratified tail feeds the existing
  actual-book rank; reward/target is not promoted to final selection.
- The first real generated file exposed the old 128-KB one-market input limit.
  The validated bound is now 1 MB for at most 1,024 strict review records; the
  actual generated artifact is about 452 KB.

No trading process, credential or mutation endpoint was used. See
[D-079](docs/BUILD_AUTOMATIC_CANDIDATES.md).

## 2026-09-22 — live selector composition

- The launcher did not attach the existing admission owner. It now connects
  reviewed reward candidates to joined scope replacement and fresh selection.
- Metadata retirement discarded timing reviews needed on re-admission. A
  bounded candidate registry retains exact bindings separately from live caches;
  explicit revocation removes the binding, not just the active copy.
- Entry dispatch now checks explicit metadata-result blockers. Candidate
  checks also reject unsupported configured exchange scope, expired timing/fees
  and exhausted metadata retries. Admission rechecks bindings after reader join
  and waits while dispatch is active or entries are paused.
- Optional narrow startup seeds now include durable exposure owners. Existing
  recovery retains unresolved owners rather than losing them during discovery.
- A transient removal/metadata deferral was overwritten as `stable`, delaying
  retry until the five-minute catalog refresh. It now remains `deferred` and
  uses the existing one-second backoff. An in-memory reversal fails the new
  regression; ten repeated full-graph discovery cases pass with the fix.

Verification: synthetic full-graph and source/race regressions, with final results
in [D-078](docs/BUILD_LIVE_SELECTION.md). No live process or orders changed.

## 2026-09-22 — original runtime composition

- Accounting release invalidated its own dispatch snapshot by advancing the
  writer revision. The same release transaction now issues a fresh local audit;
  the account owner accepts it only with unchanged generation/revision, the
  exact current writer revision and original source age. Unrelated writes and
  disconnects still revoke proof.
- Inventory callbacks refreshed advisory plans but never queued safety cancels,
  passive reducers or timed IOC work. They now queue market keys for the existing
  source to revalidate, outside its own refresh path to prevent a feedback loop.
- Five real quota consumers exceeded a four-listener bound. The bound is now
  exactly five; initial write-budget bootstrap remains owned by the same quota
  supervisor. No independent rate budget was introduced.
- Empty reward-order snapshots no longer issue unnecessary queue-position GETs.
  Nonempty reflection is explicitly market-scoped in bounded query chunks.
- Periodic account refresh mistook a command's own preparation revision for
  stale external evidence, potentially revoking its send lease mid-dispatch.
  Background refresh now waits for the active dispatch to finish; real private
  ingress still revokes immediately and all outcomes request reconciliation.
- The flat shutdown check called `writer.orders()`, which settles evidence and
  changes the revision. It now uses the current complete order audit plus
  read-only inventory/risk checks, rejecting any intervening write or stale report.
- A final status-file failure after a launch attempt could report a successful
  exit code or claim trading had never started. It now returns nonzero and
  `NEEDS_ATTENTION`, with neither a no-trading nor a flat-account claim.
- The retired canary's tests used a fixed plan date with the real wall clock.
  An injected validation clock makes those fixtures deterministic.

Verification: full-graph synthetic startup/ACK plus focused accounting, exits,
reward and quota regressions; exact final counts in the [run guide](docs/RUN_LIQUIDITY_BOT.md).

## 2026-09-22 — terminal cash-history cursors

### Valid terminal cash pages were rejected as incomplete

**Symptom.** Fresh deposit, withdrawal, subaccount-transfer and intra-exchange
transfer reads returned a short final page without a `cursor`, while the client
required the field on every page. **Fix.** Only those four documented cash
endpoints may omit a cursor, and only when the returned page is shorter than the
requested limit. Full pages and all other account histories remain strict.
Focused regressions and the full 1,367-test suite pass.

## 2026-09-22 — S2B restriction-transfer ordering

### Stop and coalesced-pulse races could interrupt terminal fence transfer

**Review findings in the new offline component.** A durable stop can queue
STOP_HINT before the terminal FENCE_ACK, and a coalesced pulse created before a
fence commit can arrive after the newer ACK. Treating every post-stop control as
invalid prevented clean retained shutdown; treating the old pulse as a control-
revision regression created a false IPC fault. Blocking on an IPC completion
future inside the child event loop also violated the nonblocking ownership
contract. **Fix.** Permit only FENCE_ACK after STOP_HINT, ignore an older
coalesced pulse without refreshing heartbeat, preserve exact retained-control
ordering and await IPC completions asynchronously. **Verification.** Native
clean-stop, crash-before-ACK and exhaustion/cooldown tests pass; targeted
protocol regressions cover the stale pulse and phase gates. The complete suite
passes. No live process or venue operation was involved.

## 2026-09-22 — native supervisor resource acceptance

### Current endpoint-cost template syntax rejected the complete quota pair

**Symptom.** The fresh account endpoint-cost document passed the general quota
validator but `WriteQuotaSnapshot` would reject it before installing write
evidence. **Mechanism.** Kalshi currently returns Express-style `:order_id`
templates and an unrelated `*endpoint` wildcard; the stricter write parser only
accepted literal and `{order_id}` segments. **Fix.** Validate all three bounded
template forms, canonicalize colon parameters to braces and retain duplicate
detection across representations. **Verification.** A regression containing the
current document shapes installs cancel cost 2 and default create cost 10; the
fresh read-only pair is revalidated through `WriteQuotaSnapshot`. The 67
write/quota and 11 entry-dispatch tests pass; the final full suite also passes.

### Repeated sidecar opens and timestamp-only commits exceeded idle CPU

**Symptom.** The corrected inert S2A benchmark reported 2.03–2.14% parent CPU
against the declared under-1% target while warmed lifecycle ownership was stable.
**Mechanism.** Every control command retraversed paths and reopened WAL/SHM for
the same DACL validation, and each one-second timer wrote/fsynced a journal row
even when policy changed only `updated_utc`.
**Fix.** Retain sidecar handles without delete sharing and revalidate their exact
DACLs in place. Route host timers through a store method that coalesces only a
no-action, non-stale, materially identical result after clock/policy evaluation.
**Verification.** 114 focused tests pass (one privilege skip); regressions cover
sidecar replacement, no-op revision/history, action persistence and clock-fault
persistence. The full 60-second/100-cycle benchmark passes all targets at 0.781%
parent CPU. See [build evidence](docs/BUILD_WINDOWS_SUPERVISOR_RESOURCE_FIXES.md).

## 2026-09-21 — development components, no live account use

### Admission: cancellation during final inventory proof

**Review finding in the new component.** The handoff checked request ownership
before awaiting final inventory reads, but a caller could cancel while those
reads completed. Fresh account proof alone did not prove the request still existed.
**Fix.** Recheck the exact pending request and its result after those awaits,
before the synchronous scope commit. Serialize the entire discovery/handoff
cycle, not just the pending-reader phase. Join reader teardown through repeated
cancellation; preserve connection failures and metadata retry tombstones.
**Verification.** Dedicated cancellation-race test fails when the final ownership
guard is removed in memory. Scope/timer/retry/metadata tests cover the companion
boundaries. No live defect claimed; [build record](docs/BUILD_MARKET_ADMISSION.md).

### Reward estimates: source gaps, persistence races and telemetry isolation

**Review findings in the new component.** Equal-valued replacement observations
could bridge a revoked interval; a checkpoint reload could overwrite observations
received during disk I/O, and older saves could erase newer evidence. Telemetry
exhaustion must not stop inventory management. Revalidating a large shared book
for every overlapping program also repeats unnecessary work.
**Fix.** Bind source identity, clear samples on invalidation, fence loads by
revision, serialize native file ownership and refuse decreasing evidence. Retain
I/O ownership across cancellation. Surface rejected telemetry as a sticky fault
with unknown rates while management continues. Validate shared books once and
score each program independently.
**Verification.** Focused regressions cover each boundary, including an in-memory
reversal that detects false accrual across a catalog refresh. No live defect or
income claim. See [build record](docs/BUILD_REWARD_TRACKER.md).

### Incentive refresh: retained wire age and late-publication fences

**Review finding in the new offline component.** A shared request retained
after caller timeout could be joined by a later refresh and stamped with its
new observation start. A completed result could also outlive invalidation or
quota loss before its scheduling turn consumed it.
**Fix.** Use a distinct coalescing scope per catalog attempt; recheck generation,
expiry and quota before publication and source identity during selection.
**Verification.** Focused regressions cover both completion windows, old wire
ownership, inventory preservation and distinct observation scopes. No live
defect claimed. See [build record](docs/BUILD_INCENTIVE_DISCOVERY.md).

### Selection: hypothetical quotes, invalidation and repeated book validation

**Integration gaps.** Reference-quote rankings alone could not describe an
existing order losing eligibility; repeating book validation per program cost
465.737 ms in the named maximum-input fixture. New selector cache cleanup and
expiry boundaries also needed explicit regression coverage.
**Fix.** Separate explicit quote-set scoring, preserve protected owners, share
validated book input with independent per-program copies, and revoke all related
cache entries on failure. Exclude unsupported markets without stopping inventory
management. No live defect or automatic cancellation claimed.
**Verification.** 42 focused tests and representative resource checks pass;
[build record](docs/BUILD_MARKET_SELECTION.md) records scope and remaining wiring.

### Dispatch lifecycle: ownership, exit supervision and truthful activity

**Integration gap.** Runtime shutdown did not own an injected dispatcher, so
caller-managed command work had no joined place in runtime teardown.
**Fix.** Attach one matching offline service; stop new work before asynchronous
cleanup and join outcomes before cancelling peer readers. Treat an unexpected
service exit as a runtime fault, not normal reader exhaustion. Show RUNNING
while awaiting a new outcome instead of retaining the previous IDLE label.
**Verification.** Stop at prepare/SENDING/invoke/commit, repeated cancellation,
late 429, persistence failure and new-epoch UNKNOWN holds are covered. Replacing
the join with an early return in memory fails the shutdown-order regression.
No live defect claimed. See [build record](docs/BUILD_DISPATCH_LIFECYCLE.md).

### Write outcomes: recovery timing and retained cancellation errors

**Integration gap.** Transport completion alone was not wired to owned recovery;
an ingress-only signal could also be consumed before outcome commit.
**Fix.** Revoke source proof and coalesce recovery at observation and again after
retained recording. Preserve UNKNOWN/SENDING holds and never infer a safe retry.
**Verification.** Synthetic early event consumption fails if the final signal is
bypassed; ACK/UNKNOWN, writer failure and pre-invoke proof loss are covered.

**Reproduced defect.** On this Python 3.14 installation, cancelling a shielded
dispatcher wait and later receiving a failure prints the retained exception via
the default event-loop handler, outside structured diagnostics. **Fix.** Wait on
the owned task without propagating consumer cancellation, then explicitly consume
its result; use this in dispatcher run/close and executor persistence retention.
**Verification.** The cancellation/429 regression detects the leak when the old
shield wait is restored in memory; no source file was weakened for the check.
See [build record](docs/BUILD_MUTATION_OUTCOMES.md). No production incident claimed.

### Write-quota source: retain the full pair and owner fence

**Integration gap.** The existing quota candidate's document projection is
GET-only; reconstructing write costs from it would silently lose overrides.
The arithmetic budget's raw grant expiry is also later than the read owner's
required safety margin. **Implementation.** Parse original full pair documents
before publication, bind the result to the accepted read lease, and check the
owner at every quota operation, including final consumption. Do not let caller
timestamps mint tokens. Replaced reader/source ownership is a sticky stop.
**Verification.** Exact POST/DELETE versus GET costs, owner replacement and a
grant-margin boundary are covered; bypassing the source fence in memory makes
the grant-margin regression fail. No production bug or account use is claimed.
See [build evidence](docs/BUILD_WRITE_QUOTA_SOURCE.md).

### Source dispatch: late stop, final proof and unused permit

**Mechanism.** Dispatcher stop was checked only before starting work, not after
awaited preparation or at invocation. The executor's final quota hook could
invalidate account/book proof after its last source check. A pre-SENDING
`CommandDenied` return aborted the receipt but left a quota permit outstanding.
**Fix.** Stop fences after both refreshes/preparation and around quota consumption;
repeat exact writer/source checks after the synchronous hook; discard the unused
permit on a denied handoff. Already-invoked work retains its outcome owner.
**Verification.** Deterministic stop/ingress races assert zero injected calls,
NOT_SENT before SENDING versus conservative UNKNOWN afterward, and zero retained
permits. In-memory removal of final source checking and permit cleanup makes
their respective regressions fail. [Build evidence](docs/BUILD_DISPATCH_SOURCES.md).

**Final-review correction.** An already-forced IOC may have metadata expiry as
its next advisory timer although trading close is sooner. The source fence now
also rejects the explicit close time; a regression crosses close within the
five-second source lifetime and blocks invocation. Removing that guard in memory
makes the regression fail. No live market was exercised.

### D-068 release ownership and cancel/reducer integration

**Mechanism found before publication.** A retained reconciliation could outlive
its cancelled consumer; measuring age only after collection renewed stale
evidence. The first reducer-fee integration was accidentally placed in cancel
preparation. Derived fractional cash also needed accounting precision rather
than wire precision on reread.
**Fix.** Shared revocation survives cancellation; the monotonic fence starts
with snapshot collection. Every financial/source write revokes authority, and
the final synchronous send edge checks it. Fee reservations belong only to
reducing creates; cancels retain their existing path. Missing passive fee bounds
block subsequent entries, not safety exits. Derived cash is read as exact Decimal.
**Verification.** Dedicated cancelled-read, frozen-clock, post-commit ingress,
last-send-edge, approved-baseline cancel/reducer and fractional-cash regressions
pass in disposable ledgers. See [build evidence](docs/BUILD_ACCOUNT_RECONCILIATION.md).

### Offline dispatcher spent write permit before durable SENDING await

**Mechanism.** The dispatcher consumed a fresh local write permit before
awaiting the writer's SENDING transition. Quota evidence could expire during
that await, leaving the subsequent injected send without an edge check.
**Fix.** Check the outstanding permit before SENDING, retain it through the
await, then consume it synchronously immediately before the injected invoke.
**Verification.** A synthetic expiry during the handoff makes zero injected
calls, durably records UNKNOWN and latches the dispatcher. An asynchronous
send-edge callback is rejected. 48 focused and 1,018 full tests pass (one
expected native privilege skip). This is offline-only and does not authorize
venue mutations.

### Write-budget hot path exceeded synthetic CPU acceptance

**Mechanism.** Each reserve repeatedly parsed an unchanged route, converted
the same clock pair and revalidated identical command terms. **Fix.** Bound
canonical-route caching to 512 entries, reuse validated equal clock samples,
and share one readiness pass between reserve and delay while preserving exact
rational comparisons and expiry checks. **Verification.** 33 budget regressions,
the 12,000-command five-sample CPU/allocation fixture and the combined focused
dispatcher suite pass; see [write-budget evidence](docs/BUILD_WRITE_BUDGET.md).

### Dispatcher proof loss after durable SENDING was misreported as blocked

**Mechanism.** The injected executor persisted UNKNOWN and latched its recovery
hold, but an initial dispatcher handler caught the denial as ordinary blocked
work. **Fix.** The dispatcher now latches failed when the executor's post-SENDING
hold is active. **Verification.** A synthetic two-stage proof reversal confirms
UNKNOWN, zero invoked requests and a failed dispatcher; no retry is attempted.

### Opening evidence omitted older pending or undated cash movements

**Mechanism.** Creation-time filtering omitted pre-boundary pending funding,
funding with absent/null finalization, and older intra-exchange transfers even
though their completion time was unknown. **Fix.** Retain those observations
with explicit timing/attribution blockers. Preserve exact cash precision,
nullable payout fields and source/query provenance; join inspection work and
recheck revisions after off-loop normalization. **Verification.** New focused
regressions and the 966-test full run pass (one expected skip); see the
[build record](docs/BUILD_OPENING_ACCOUNT_CASH_EVIDENCE.md). Resource and complete
accounting gates remain open.

### D-060 receipt, reducer, recovery and hot-capacity review defects

**Mechanisms.** Receipt identity was not durably bound to its issuing writer;
proof callbacks could mutate outgoing terms; reducer evidence echoed caller
routing and skipped complete management eligibility; proven-unsent attempts
wedged later safety work; some post-SENDING failures released the executor hold;
and repeated full-table integrity scans made valid retained histories exceed the
CPU target. **Fix.** Persist per-preparation authorizations, dispatch fresh
canonical terms, require and persist an exact management/exit decision, recompute
reducer authority transactionally, reauthorize the
same proven-unsent slot under a bounded audit history, hold recovery immediately
after SENDING, and use trigger-maintained hot counters with full startup audits
and transactional limits on legacy writes. A final authority check after queued
reducer preparation aborts stale PREPARED work before returning a receipt.
**Verification.** 258 focused and 950 complete tests pass (one existing skip);
self-audited complete-history 30/120-market cases pass with worst CPU growth
1.429x. See
[review-fix evidence](docs/BUILD_COMMAND_CAPACITY_REVIEW_FIXES.md).

### Safety-command capacity cliff and duplicate entry reservation

**Mechanisms.** The 4,096 mutation-row check rejected every new journal row,
including cancellation of an owned working order. Separately, risk reservation
created the entry intent and the executor tried to reserve the same identity
again, faulting the writer before dispatch. **Fix under D-060.** Durable bounded
credits reserve order/cancel and one-passive/three-IOC drain evidence; funded
safety commands atomically convert held capacity. Entry risk, intent and
PREPARED mutation now commit once and return a post-commit receipt consumed once
by the sole executor. **Verification.** Real 4,096/8,192 boundaries, 21 new
focused regressions and the prior 936-test suite are recorded in the
[build evidence](docs/BUILD_COMMAND_CAPACITY_HANDOFF.md). The
[independent review](docs/REVIEW_D060_ASTRA.md) requires six corrections and
invalidates the original resource acceptance fixture. No live transport or
account was used; these implementation changes are not yet cleared.

### S2A retained ownership, launch permission and shutdown evidence

**Mechanisms.** Repeated cancellation and protocol exceptions could abandon a
live child; a nonstale policy denial was mistaken for spawn permission. Queued
terminal IPC could be discarded on close, and child identity/age checks, both-
process power invalidation, protected control files and diagnostic ownership
were incomplete. Session/native writes bypassed journal pruning.
**Fix under D-057.** A retained lifecycle owner, explicit committed launch grant,
native-write receipts, protocol/power gates, protected/pinned control files,
bounded diagnostics and shared pruning address R1-R8. Uncertain creation remains
held, never automatically retried. **Verification.** Thirty regressions and three
safeguard reversals; 915 complete tests run, 914 pass and one native symlink-
privilege skip. See [evidence and limits](docs/BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md).
Independent review is pending. No live runtime, account or configuration change.

### Native child identity and pipe-close/process-exit race

**Mechanisms.** The Windows virtual-environment launcher briefly spawned the real
interpreter, so the retained `Popen` handle/PID did not identify the pipe client.
After switching to the real base executable with the pinned virtual environment,
an intentional `os._exit` could still close IPC just before its retained process
handle became signaled; under full-suite load the host misclassified that first
crash as an IPC fault. **Fix under D-056.** Launch the real interpreter process,
pass only the fixed virtual-environment identity, validate the exact pipe peer,
and allow a 250 ms bounded wait on that retained process handle before classifying
a live-child IPC failure. **Verification.** Native parent/child identity tests,
10/10 repeated crash-budget runs, 81 focused and 885 complete tests pass. No live
runtime, account or network use.

### Clock fault loss and unstable default boot estimate

**Mechanisms.** Stale child filtering returned before local clock distrust was
handled, then the journal replaced the checkpoint; a later event could resume.
The default exact quantized wall-minus-monotonic identifier could also change
under harmless sampling skew. **Fix under D-054.** Apply independent clock
distrust durably before payload filtering while retaining the stale label, and
validate persisted default continuity from tolerated clock deltas. **Verification.**
Sixty-four focused and 868 full tests, 10/10 focused repeats, four parent-code
counterfactual detections, resource checks and disabled preflight pass. See
`docs/BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md`. No runtime or live use.

### Supervisor sequence, continuity and identity defects

**Mechanisms.** Repeated STOP did not refence generation; late status refreshed
already-expired deadlines; failed-spawn release discarded an attention reason;
clock trust existed only inside one store object; and identityless child events
could match childless state. **Fix under D-053.** Fence every STOP, check prior-
state deadlines first, retain attention on reservation release, transact one
shared boot/wall/monotonic control checkpoint, and require complete child
identity. **Verification.** Fifty-nine focused and 863 full tests, 10/10 focused
repeats, compilation, resource checks and disabled preflight pass. See
`docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md`. No runtime or live use.

### Supervisor control, recovery and resource-contract defects

**Mechanisms.** Delayed/stale event timestamps could bypass stop fencing; late
lifecycle events could release or renew a confirmed child; work/startup timing
could hide stalls; retry holds did not block relaunch; crash evidence conflated
process exit with cleanup; and the CPU fixture measured only sleep. **Fix under
D-052.** Separate monotonic-normalized control time from diagnostic event time,
fence safety stops, enforce lifecycle/deadline/hold contracts, preserve truthful
recovery evidence and exercise the persisted journal in the idle fixture.
**Verification.** Forty-six focused and 850 full tests, 10/10 repeated focused
runs, compilation, disabled preflight and a 60-second 124-event CPU fixture pass.
See `docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md`. No runtime or live use.

### Disconnect teardown interrupted by runtime stop

**Mechanism.** Runtime cleanup cancelled a connection already draining after a
transport failure. That cancellation could stop positive-fill retention before
the queue emptied and skip marker close/cache refresh. **Fix under D-048.** Each
connection creates one retained finalizer and awaits it through repeated
cancellation; genuine finalizer errors still propagate. **Verification.** Three
new regressions, 231 focused tests, 804 full tests, resource fixtures and disabled
preflight pass. See `docs/BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md`. No live use.

## 2026-09-20 — development components, no live account use

### Repeated cancellation and buffered-drain failure

**Mechanisms.** A second cancellation interrupted connection teardown after its
reader had been shielded, leaving the reader alive, tail evidence queued, an
open marker and stale runtime liveness. One malformed/staging failure also
aborted the queue drain, and shutdown discarded that child error. **Fix under
D-047.** A retained cleanup task owns all joins/finalization through repeated
cancellation. Per-item draining records failures, continues preserving later
valid fills and returns a safe cleanup failure after marker/gap reconciliation.
Already observed runtime faults retain their original exception. **Verification.**
Three regressions, 199 focused tests, 801 full tests, resource checks and disabled
preflight pass. See `docs/BUILD_ACCOUNT_CONTINUITY_SHUTDOWN_FIXES.md`. No live use.

### Private-reader shutdown and epoch-open ownership

**Mechanisms.** Stop could cancel a reader after it dequeued a fill but before
durable staging, then infer a clean span from an empty queue. A committed epoch
open whose caller acknowledgement was cancelled could remain orphaned while the
current run retained a stale zero-gap cache. Status also captured continuity
before quota polling could synchronously revoke it. **Fix under D-046.** Bounded
in-flight ownership and post-join queue draining retain fill evidence and mark
interrupted spans invalid. Marker identity is owned before the accepted write;
uncertain acknowledgements close/reload durable gaps. Quota polling precedes
status capture. **Verification.** Queued/in-flight fill, cancelled/failed-open,
reconnect and quota-boundary regressions pass; 196 focused and 798 full tests,
resource checks and disabled preflight pass. See
`docs/BUILD_ACCOUNT_CONTINUITY_REVIEW_FIXES.md`. No live use.

### Position pagination and unscoped private updates

**Mechanisms.** The development REST collector treated an omitted positions
cursor as exhausted pagination. The account handler rejected the documented
market-position example's missing subaccount and disconnected the whole private
reader, risking loss of later fill observations. **Fix under D-045.** Require an
explicit cursor value on every positions page. Treat an otherwise valid unscoped
position as scope ambiguity: invalidate, install no cost/quantity, request one
coalesced scoped reconciliation and keep the fill reader; conflicting or
malformed scope still fails closed. **Verification.** First/later-page cursor,
live-reader, fill-after-unscoped and mismatch regressions pass. No live account
feed or credential was used. See `docs/BUILD_ACCOUNT_CONTINUITY_PHASE1.md`.

### Supervisor liveness and rollover-record retention

**Mechanisms.** A second cancellation during `run()` shutdown skipped the
`running=False` assignment. Holding a pending exception also held its traceback
and completed quota response frames. **Fix under D-042.** Publish liveness in
an unconditional final block; copy validated boundary/provenance fields into an
immutable record. Do not abandon the physical worker or mutate the exception.
**Verification.** Two injected regressions, 62 focused tests, 778 complete tests
and quota resource checks pass. Astra re-review clears both with 62 focused
tests and two process-local reversals; see `docs/REVIEW_D042_ASTRA.md` and
`docs/BUILD_QUOTA_REVIEW_FOLLOWUPS.md`.

### Grant rollover, close ownership and cooldown waiter

**Mechanisms.** A valid unchanged finite grant was counted as a failed refresh
at the scheduled lead; cancelling a close could cancel the owner of a still
running thread; a clock fault could leave an explicit refresh waiting forever.
**Fix under D-041.** One bounded typed rollover observation, retained close/drain
task with non-propagating joins, and terminal checks on each refresh wait.
The wire-entry timeout test now controls its deadline after entry.
**Verification.** 60 focused tests, 776 complete tests, both 30/120 resource
fixtures and two in-memory reversals pass/detect as documented in
`docs/BUILD_QUOTA_REVIEW_FIXES.md`. Independent Astra re-review pending.

### Quota holds must not consume unrelated recovery attempts

**Mechanism.** A generic invalid-read failure can be counted as a failed market
refresh or swallowed as missing order-binding evidence, even when shared quota
authority is unavailable. **Fix under D-039.** Propagate typed QuotaUnavailable;
metadata/recovery wait without charging their attempts and retain earlier exhausted
states. A restored lease wakes eligible recovery only, never clears risk holds.
**Verification.** Injected runtime and scheduler regressions, including a durable
private fill during quota outage. Both quota phases await independent Astra review.

### Valid review changes exhausted metadata keys

**Mechanism.** Historical dependency epochs were retained indefinitely under a
six-per-market cap, so replacing a fully reviewed market's milestone blocked new
inputs even after reconnect. **Fix.** Retire unreferenced cache/dependency keys
against the current market/review graph; use globally unique epochs so delayed
old tasks cannot publish after a key is recreated. Keep dependencies referenced
by other markets. **Verification.** 25 successive replacements, shared milestone,
pending old read and reconnect regressions; 30/120-market resource checks pass.

### Background reads could fill admission before account work reached priority

**Mechanism.** A reserved transport slot did not reserve entries in the bounded
in-flight map. **Fix.** Bound background admissions below total capacity so two
entries remain for critical reads when capacity allows. Existing deduplication,
token priority and transport limits remain. At capacity one, reservation is
impossible and requests honestly fail. **Verification.** Saturated 32-entry and
small-capacity regressions; 30/120 token resource checks pass.

### Old metadata wire reads could consume a new generation's retry

**Mechanism.** Shared pending and REST deduplication keys lacked generation and
revision provenance. **Fix.** Disconnect retires service-owned pending tasks;
metadata REST coalescing includes service/generation/revision scope. Old wire
work remains owned and bounded by the shared REST service until it finishes.
**Verification.** Reconnect with an old gated dependency at a one-attempt limit,
separate old/new wire payloads, stale-review task and shutdown tests pass.

### Token head slept through quota reconfiguration

**Mechanism.** Only follower waiters listened for a queue/configuration change;
the head slept on its old refill timer. **Fix.** The head awaits either the timer
or a change signal, then recalculates cost/refill/throttle without granting extra
tokens. Both wait tasks are joined on cancellation. **Verification.** Higher/lower
rate, throttle extension, priority and cancellation tests plus token load checks.

### Background token waits could delay account reads; terminal 429 lost the pause

**Mechanism.** The old bucket held its lock while awaiting refill, preventing
new critical reads from using available tokens. A final rejected retry raised
before notifying the shared limiter. **Fix.** Bounded priority/FIFO waiters, no
lock across sleep, a reserved transport slot for account work when concurrency
allows, and shared throttling before final/deadline error handling. Quota documents
start the local estimate empty and refresh atomically. Tiny positive waits round
up to one microsecond to avoid non-advancing floating-clock loops, never extra
token grants. **Verification.** 13 focused tests, reversed-throttle assertion
failure and 30/120-request resource fixtures. No live 429 experiment.

### Metadata bootstrap can precede the first orderbook snapshot

**Mechanism.** The new scheduler can publish terms and dirty a market before its
book exists; unconditional book indexing then raises KeyError. **Fix.** Skip
advisory processing until a snapshot exists; snapshot ingestion marks it dirty
normally. **Verification.** Injected runtime bootstrap/shutdown regression.

### Canceled shield consumers could expose raw background exceptions

**Mechanism found during D-036 verification.** Python 3.14 shield cancellation
could log the later underlying exception despite our consuming done callback.
**Fix.** Shared REST/metadata consumers use non-propagating `asyncio.wait`, with
explicit result/exception consumption and safe dependency diagnostics. Underlying
work remains bounded and service-owned. **Verification.** Pending disconnect,
reconnect and timeout cases in the 24-test scheduler suite; no raw account data
is supplied by fixtures or included in logs.

### Later empty history could hide previously remembered missing fills

**Mechanism.** Recovery inspected missing ownership only among rows in the current
response. A later empty enumeration could therefore get a locally repaired label
while earlier staged, unaccounted fills remained. Global live-entry gates still
blocked trading. **Fix.** Durable enumeration completion compares returned rows
with retained same-account/same-interval evidence; omissions remain visible and
block the repaired label. It never deletes evidence or infers correction/ownership.
**Verification.** Empty-after-positive and interrupted-staging regressions, restart
inspection, rollback and an in-memory reversed runtime guard. No live use.

### Stream metadata can arrive before a REST baseline or after its expiry

**Mechanism found during D-034 build.** Invalidating only a pending REST request
could lose the known stream update when no fresh baseline existed; the next old
REST response could then publish obsolete state. **Fix.** Preserve bounded
field overlays and require later REST agreement, in addition to revision/generation
checks and immediate published-term revocation. **Verification.** Pre-bootstrap,
expired-baseline, in-flight and conflicting-REST regressions pass. No live use.

### Sanitized failures discarded root-cause locations

**Mechanism.** Writer/REST failures deliberately suppressed raw exceptions, and
reader/recovery catches only updated state. Debugging could not identify the
failing code path. Writer close errors could also escape its worker cleanup.
**Fix.** Schema-limited error events preserve exception type/category and stack
locations before returning sanitized errors; close failures poison the writer
and are logged. Unexpected runtime exceptions still propagate after cleanup.
**Verification.** Focused writer/REST/runtime faults and credential sentinel tests
pass. Strict logging I/O, queue saturation and idle-runtime health failure are
also tested. No live account used; see `docs/LOGGING_AND_ERRORS.md`.

### Delayed public messages must not refresh an old book

**Mechanism.** Book sequence validity alone did not prove wall-clock freshness;
using processing time would make queued old data appear newly received.
**Fix.** Capture monotonic ingress time with the bounded public queue, retain it
on book application and reject inventory-plan books older than five seconds.
Reconnect generations and failed shards continue to invalidate book authority.
**Verification.** Delayed-queue, stale-book and terms-replacement races are in
`tests/test_bot_exits.py`; all 569 tests pass. No live account was used.

### Moving the project retained old Python environment paths

**Symptom/mechanism.** The copied environment's editable `.pth`, activation
scripts and executable launchers still referred to the old OneDrive location.
**Fix.** Regenerate both environments in the new location, reinstall the same
pinned runtime packages and editable project, and regenerate pip launchers.
**Verification.** Package imports and executable launchers resolve
`C:/Users/rynna/Bots/kalshi`; 479 tests pass there and preflight exits 2.

### Separate account reads and aggregate counts could mislabel recovery

**Symptom/mechanism.** Reconciliation read inventory before a separate venue-cost
write. A local reservation could overtake publication without changing the
private revision. Runtime aggregate intent/order counts did not detect foreign
resting orders and incremented completed passes even when checks failed.
**Fix.** Atomic account audit with exact terms/scope/fill gaps and writer revision;
current-report consumers reject intervening local writes. Runtime requires the
audit and source provenance; only passing repairs increment completion.
**Verification.** Stale-read, foreign-order and matching-flat/missing-opposite-fill
regressions; removing the stale guard or foreign blocker fails its test. Full
479-test suite passes. No live state or money was involved.

### Position snapshot capacity validation repeatedly scanned all positions

**Symptom/mechanism.** Each venue-cost write scanned the whole observation table,
making a full snapshot's capacity checks quadratic in active positions.
**Fix.** Batch observations and check active capacity once inside the same
transaction. **Verification.** Capacity-overflow rollback and original-age tests;
120-market diagnostic p99 reduced from 174.951ms to 71.887ms. No limits weakened.

### Advisory inventory plans could outlive local writer evidence

**Symptom/mechanism.** Account/book revisions alone missed an intervening local
intent reservation; an awaited read could also be overtaken by a writer command.
**Fix.** Attach owner epoch/revision to immutable inventory reads and check it
before publication and retrieval. **Verification.** Regressions revoke both
published and in-flight plans after local writer mutation; full 450 tests pass.

### Historical flat observations could exhaust active-market capacity

**Symptom/mechanism.** Zero-quantity, zero-cost venue history inserted empty
exposure entries and counted them against the active-market limit.
**Fix.** Exclude only fully flat zero-cost historical rows; preserve positive
costs, mismatches and active order risk. **Verification.** 130 old flat rows
produce zero active exposure without poisoning the owner.

### Fill-before-order delivery could permanently fail event dispatch

**Symptom/mechanism.** The prior coordinator rejected an unbound fill; propagating
that exception through the engine marked the entire dispatcher failed. It had
no durable inbox for a fill whose order evidence arrived later.

**Fix.** Persist normalized fill evidence before enqueueing; apply/delete in the
single writer transaction only after exact ownership/scope. Later stream order
evidence drains the matching inbox; missing evidence uses bounded recovery.
Stale epochs cannot publish current projections and never delete pending fills.

**Verification.** Startup/restart, disconnect-before-dispatch, later stream
binding, duplicate/conflict, rollback and queue/inbox overflow tests pass.
Full suite 410. No production trader was operated.

### Recovery integration needed ingress revocation and missed terminal repair

**Symptom/mechanism.** Dispatch-only invalidation leaves a REST report visible
while a newer private event waits in a queue. Fill recovery alone can leave a
durable order incorrectly marked resting after a missed terminal update.

**Fix.** Revoke reports before ingestion's first await; generation/revision checks
reject overtaken reads. Repair missing/mismatched owned orders by positive
GET/404-archive evidence within a shared 32-lookup pass budget. Pending fills
cannot exceed positive terminal fill quantity; atomic failures retain the inbox.

**Verification.** Both races and terminal-quantity rollback are covered. Removing
ingress revocation or the pending terminal-quantity guard each failed its targeted
test; restored afterward. Exact bounds/results in `docs/BUILD_RECOVERY_ENGINE.md`.

### Automatic recovery exceeded its existing freshness deadline

**Symptom/mechanism.** The first 1024-fill offline recovery took 5.0559 seconds
and could not return a completed report. Every fill summed the entire current
receipt window and allocated rows for every active inventory market.

**Fix.** Transactional Decimal window totals with an append-only journal cursor;
cold windows use the time index, subsequent observations read new rowids only.
Cache updates roll back with fills and risk caps. Count the uniquely indexed
one-lot-per-ticker table without allocating all tickers on each fill. No freshness,
per-fill ratchet, durability or diagnostic budget was weakened.

**Verification.** Nine dedicated total/rollback/restart/boundary tests; 371 tests
overall. Latest 1024-fill run: 1.6215 seconds, batch p99 46.784ms. Deliberately
recounting the cursor row caused four regressions; fix restored. Journal pruning
or corrections must invalidate/rebuild derived totals transactionally and are
not supported by this optimization. No production ledger was opened.

### History staging accepted conflicting execution-time evidence

**Symptom/mechanism.** Staging compared durable fill economics, but not the new
D-024 execution timestamp. An identical fill identity with a contradictory time
could be stored as apparently matching recovery evidence.

**Fix.** Compare history time against the durable source precision. Reject a
conflict atomically; permit finer evidence within the stored coarse interval.
Do not move the receipt clock, replay P&L or charge fees again.

**Verification.** Conflicting-time rollback and compatible finer-time tests pass
within the complete 335-test suite. No existing account database was operated.

### Starting reconciliation retained older auxiliary reports

**Symptom/mechanism.** The coordinator cleared its main report, but could leave
the preceding history/archive report visible while a replacement attempt ran.

**Fix.** Clear all auxiliary recovery reports at reconciliation start, as well
as on private events/disconnects. A stale/incomplete attempt cannot appear current.

**Verification.** Focused replacement-report test and disconnect/generation/
incomplete-batch tests pass. Readiness remains false throughout.

### New ranking batches starved the event loop in an offline load check

**Symptom.** The first 120-market book/ranking fixture exceeded declared event
loop and ranking latency budgets. No real trading process was involved.

**Mechanism.** Async decision callbacks could perform synchronous Decimal work
without yielding across 32 markets. Quote planning also rebuilt/validated the
same book twice, and snapshot levels repeated value validation in ladder insertion.

**Fix.** Eight-market maximum decision batches yield after every market and
preempt for arriving private events/timers. Reuse already validated local book
copies and use internal validated insertion only after snapshot boundary checks.
Continue pending dirty work even when no new market event arrives.

**Verification.** Priority, dirty-drain, sequence and numeric regressions pass;
all 280 tests pass. The final 30/120-market diagnostic checks pass their unchanged
budgets. Exact results, limited headroom and measurement caveats are in
`docs/BUILD_ENGINE_RANKING.md`. This is not a live latency SLA.

### Unbound account fills could enter the bot-only accounting path

**Symptom/mechanism.** The previous coordinator checked subaccount scope but
forwarded unbound private fills to the ledger. It did not yet distinguish this
bot's trades from other activity on the same account.

**Fix.** Require a durable exact owned-order binding before accounting a private
fill; validate its market/direction and account. Missing optional subaccount may
be resolved only through that binding. Unbound/foreign fills halt for explicit
order/history recovery, including the legitimate fill-before-order race.

**Verification.** Updated old fixtures to create owned bindings; new regression
proves an unbound fill cannot change the bot ledger. This is a development-path
correction, not evidence that a live loss meter or account was affected.

### Required pagination cursor was treated as optional

**Symptom.** An injected malformed orders/fills response containing rows but no
`cursor` could be returned as an exhausted enumeration.

**Mechanism.** The generic pager defaulted every absent cursor to an empty string.
The published Orders/Fills response schemas require that field; Positions and
Incentives permit optional cursors. These contracts cannot share that assumption.

**Fix.** Reject missing cursors for orders, current fills and historical fills;
retain the documented optional behavior for other supported paged endpoints.

**Verification.** Focused offline regression covers all three required-cursor
operations and the optional positions case. No venue account calls or money were
involved. Final full-suite and deliberate reversal evidence is recorded in the
recovery milestone report.

## 2026-08-17

### Trade capture recorded zero trades across 40 markets

**Symptom.** After adding trade capture, a 40-market sweep stored 0 trades with
no `fetch_trades` errors. Reads as "these markets never trade".

**Mechanism.** The window was `now - interval*3 - 30`, about 45 seconds. The
markets that rank highest on `reward/target` are thin *by construction* — that
thinness is why they rank — so almost none trade within any 45-second window.
The endpoint was fine; the question was too narrow.

**Fix.** Two modes. First sight of a market pages back `--trade-backfill-hours`
(default 48) with pagination; afterwards a deliberately overlapping window of at
least 300s. Trades dedupe on the venue's `trade_id`, so overlap costs bandwidth
and nothing else, while a gap loses fill signals permanently. Recovered 91
trades across 4 markets immediately, back to 2026-08-15.

### The per-market analysis reported a share that was arithmetically impossible

**Symptom.** `KXATPRETIRE-27DJO-Y` showed a 41% share against a denominator of
466. Five contracts against 466 cannot be 41%.

**Mechanism.** Yes and no medians were pooled into one row. That market's yes
side has a touch of **1.0 contract at 0.43** with the next level 13 ticks away
at 0.30 — and `0.5^13` is 0.0001, so the whole ladder below the touch is
arithmetically irrelevant. Its yes denominator is ~1.1 against ~990 on no. The
median of two numbers three orders of magnitude apart describes neither.

Worse, the "trust" flag divided our size by that pooled denominator, so the one
side where we would genuinely **be** the book was marked `ok`.

**Fix.** Report per `(ticker, side)`. Compute the crowding flag from the share
we would actually hold, not from the raw denominator.

**Kept as a finding, not just a fix:** a 0.50 discount factor makes any level
more than ~10 ticks from the touch worthless, so a book with a thin touch and
deep liquidity far away yields an enormous share. Those are exactly the books
where a static-book counterfactual is least trustworthy.

### The pair-trade net edge was understated 6x by pricing fees at 0.50

**Symptom.** `analyze_spread.py` reported a net pair edge of **$0.0062** on five
contracts against a gross of $0.0500, i.e. fees consuming 88% of the trade. The
conclusion drawn from that number -- reported to the operator before it was
checked -- was that the pair trade barely clears its own fees.

**Mechanism.** Both legs were priced at 0.50 as a "representative" price for the
fee curve. But `0.07·P·(1−P)` is a parabola with its **maximum** at exactly 0.50,
and the rewarded universe is mostly tail-priced -- KXRAIN's yes side sits at
0.08. Charging every leg at the single worst point of the curve overstated cost
by about six times. The correct figure is **$0.0379 net, positive in 98.2% of
snapshots**.

**Fix.** Charge each leg at its own touch price, per snapshot, rather than at any
representative value.

**The general rule this earns:** a fee, spread or slippage model must be
evaluated at the actual price, never at a stand-in. A "representative" value
sitting at the extremum of a curve is not conservative, it is simply wrong, and
it was wrong here in the direction that kills a viable strategy. Note the
asymmetry with liquidity-bot's habits: there, conservative stand-ins are correct
because they bound *risk*. Here the stand-in was applied to a *cost*, where the
same instinct destroys the result instead of protecting it.

### Two reported results were artifacts of sample size, not measurements

**Symptom.** Two claims were reported to the operator and one of them was
written into `FINDINGS.md`: that the pair trade **never** completes (0 in 140
windows), and that the one-sided markout sign was confirmed by "two independent
slates that agree exactly".

**Mechanism.** Different for each, same root.

*Zero pairs.* The true completion rate is 0.7%. In 140 windows the expected
count is 1.0, so observing zero is unremarkable — the sample could not
distinguish 0.7% from 0%. At 1,064 windows the same code finds 7. An
intermediate diagnosis, that zero was "a property of the politics slate", was
also wrong: the original slate produces pairs too once it has enough windows.
The variable was never the slate.

*Independent slates.* `capture.db` and `capture_wide.db` share **69 markets** —
88% of the narrow slate — and overlap in time, so some fills are plausibly the
same event counted twice. Run separately the wide slate does not reach
significance and its CI includes zero; only pooling produces p=0.0014. The word
"independent" was assumed from the fact that the databases are separate files,
which is a property of the storage, not of the sample.

**Fix.** `pooled_markout.py` measures and prints the shared-market count on
every run, so the overlap cannot be assumed again. FINDINGS 6h and 6i carry both
corrections in place rather than silently updated numbers.

**The general rule this earns:** *a rate that is indistinguishable from zero at
the observed n must be reported as an upper bound, never as zero.* "0 pairs in
140 windows" was arithmetic; "the pair never completes" was an inference the
arithmetic did not support, and it was load-bearing — 6h used it to resolve the
6g quoting-policy conflict. The conclusion survived, but only by luck.

Note the pattern shared with the fee-pricing bug above: both took a convenient
point value — 0.50 for a price, 0 for a rate — and treated it as the measurement
instead of as one reading with an interval around it.


## 2026-08-18

### The capture ranked candidates by a metric anti-correlated with revenue

**Symptom.** Every market this project has ever recorded was chosen by
`period_reward / target_size`. Measured against replayed revenue over 74
markets, that ranking scores **Spearman −0.150** — its top 12 markets earn
**$24.39/day** where ranking by `reward / measured denominator` earns
**$158.61/day**.

**Mechanism.** The metric was ported from liquidity-bot's `rank_candidates` and
restated in `docs/PLAN.md` as *"exactly the right Kalshi metric"*. Its stated
premise, at `record_books.py:341`, is that *"target size is the denominator we
compete against"*. On Polymarket that holds — `target_size` runs 5,000-15,000
and really does measure required liquidity. On Kalshi it is **1000 in 99.2% of
programs**, so the ratio degenerates to ranking by pool, badly.

Meanwhile the quantity it stands in for varies enormously: the measured
denominator spans **629x** across the same sample. FINDINGS section 4 had
already recorded why — DiscountFactor 0.50 collapses the effective competition
to the top few ticks — and nobody connected it to the ranking.

**Fix.** FINDINGS 11 records the measurement and the replacement metric.
`docs/PLAN.md` line 212 is corrected in place rather than left to be re-read as
settled.

**The general rule this earns:** *a ported calibration is a hypothesis, not a
fact.* The top of `FINDINGS.md` already says liquidity-bot's calibrations "are
NOT valid here until re-measured", and that discipline was applied to
`fill_hazard`, the 900s clock and the 2-cent spread rule — but not to the one
line that decided which markets we looked at for two days. **It survived because
three documents agreed with each other and none of them tested it.**

### Selection churn was destroying the coverage it was meant to build

**Symptom.** `sizing.py` discards any market observed over less than 10% of its
program period, and that guard was excluding the large majority — 32 of 52 at
one point. The obvious reading is "capture for longer".

**Mechanism.** `rank()` re-picked the top N from scratch every 15 minutes with
no memory, so tracked markets rotated out mid-run. Measured across three runs:

| run | tracked | distinct seen | present for the whole run |
|---|---|---|---|
| capture.db, 8h | 40 | 44 | 36 |
| capture.db, 20h | 40 | 82 | **19** |
| capture_wide.db, 4h | 150 | 242 | 82 |

**Only 19 of 82 markets survived the whole 20-hour run.** Duration was building
coverage and churn was destroying it faster, so a longer capture would not have
fixed it — the wide run's 214 markets collapsing to 1 trustworthy market was
partly this, not only its short duration.

**Fix.** Sticky selection: once picked, a ticker is held until its program's
`end_date` passes. Also fixed while there: program polling was hardcoded to
`status=active`, so a program's terminal state and any `paid_out` transition
were never observable — checked against the live API, `status=settled`/`ended`
and no filter return a different population. And `market_meta` was fetched once
on first sight, so a market settling mid-capture recorded no result.

**The general rule this earns:** *when a guard rejects most of your data, check
whether your own collection caused it before concluding the data is thin.*

---

## 2026-08-26

### Reward replay used a superseded filing and omitted current payout scaling

**Symptom.** August analyses treated the best bid as Reference Price, reported
that stepping one tick inside nearly doubled reward share, and paid
`share × pool` without reducing the pool for excluded snapshots.

**Mechanism.** The scorer implemented Kalshi's February 11 filing. A later July
15 certified filing, effective July 30, changed the reference to the first level
where cumulative size reaches one fifth of Target Size and added the
non-excluded-snapshot multiplier. The current Help Center matches the later
filing. The captured books are from August, after the change took effect.

**Fix.** Added pure versioned rules in `scripts/reward_rules.py`, made the July
mode the default, retained February only as a `SUPERSEDED` comparison, applied
pool scaling/cent flooring/the $1 minimum, and made every report print the mode
and source. Eleven unit tests and hand-calculated fixtures cover the divergent
rules.

**Verification.** Across 58,453 `capture_long.db` snapshots at size 10, current
mode reports inside/touch median `1.000x` (p10/p90 `1.000x`) over 112,492 sides;
legacy mode reports median `1.943x` (p10 `1.557x`, p90 `1.986x`). Current
reward-only portfolio output falls to `$7.369/day` after minimums versus
`$93.414/day` in legacy mode. The old one-tick and reward-dollar results are
therefore superseded, not alternative current estimates.

### Forced exits reused the entry book after waiting

**Symptom.** `exit_cost.py` claimed to wait 5–60 minutes before crossing, but
the deadline changed only the chance of a passive fill. Any forced cross was
priced from `series[index]`, the book associated with entry.

**Mechanism.** Reusing the entry snapshot erased the price move during the
holding period—the exact adverse-selection term the instrument was intended to
measure. Partial depth was also priced while the unfilled remainder silently
contributed zero.

**Fix.** Timed crosses now use the first captured book at or after the deadline
within an explicit tolerance. Missing, stale, and insufficient books are
`UNKNOWN` unless a recorded settlement prices the entire position. Passive
queue depth is zero when the reducer improves the touch and displayed size only
when it joins.

**Verification.** Six tests cover later-only selection, stale gaps, both exit
directions, actual-price fees, settlement signs, and passive pricing. On
`capture_long.db` at size 10 under the audited Polymarket entry policy and a
900-second deadline, 67 of 84 fills are priced for total P&L `-$27.8505`; 17
remain unknown and contribute no fake zero.

**The general rule this earns:** a clock parameter is not modeled merely
because it appears in a loop. Verify that the data used after the wait actually
comes from after the wait, and make every unpriced residual visible.

### Recorder selection retained the superseded scorer

**Symptom.** Reports used the corrected July reward module, but
`record_books.py --rank-by density` still calculated candidate density from a
private copy of the February best-bid formula.

**Mechanism.** The recorder intentionally duplicated the old scoring helper so
analysis changes could not break capture. Versioning the governing rule made
that safety argument backwards: the duplicate silently selected a different
market sample even though stored books remained raw.

**Fix.** Candidate ranking now calls the pure, network-free current rule module
and prints its source banner when capture starts. The recorder still stores
unaltered venue JSON.

**Verification.** A hand fixture that scores 60 under July and 35 under
February now asserts the recorder returns 60. The full measurement suite passes.

---

## 2026-09-19 — Documentation import verification

The first discovery parser accidentally joined a truncated link in an index
description to the next entry. Restricting matching to complete index bullets
removed the synthetic URL; the fresh manifest has no failed source requests.

The initial technical extractor missed indented MDX fences/tables and HTML
tables. It now retains their surrounding section/tab labels, host constants,
and technical contents. All 20 FIX pages have technical extracts. Generated
YAML is checked against all 191 REST operations and 423 components, both full
AsyncAPI blocks, all 247 retrieval hashes, and 614 unique explicit anchors.
No trading code was changed.

## 2026-09-14

### Latest program row contaminated historical reward replay

**Symptom.** `sizing.py` indexed programs only by market ticker, overwriting
every prior record. It then applied the last observed terms to every earlier
book and summed high-return programs from different dates as if simultaneous.

**Mechanism.** A ticker can have several program IDs and program terms can be
edited. Ticker-only lookup erased both program identity and time. Ranking all
period rows without integrating boundaries erased portfolio time as well.

**Fix.** `program_timeline.py` performs as-of matching by program ID, enforces
start/end time, and excludes edited/invalid histories. `sizing.py` integrates
the funded portfolio on the capture clock, shares collateral for simultaneous
programs on one ticker, and excludes sparse candidate scans. The emitted
schedule carries selected program terms into `portfolio_exit.py`, which quotes
only on books that qualify.

**Verification.** Unit fixtures cover pre-observation books, ended programs,
multiple IDs, edited terms, non-overlapping periods, shared collateral, and
nonqualifying fill suppression. The full 12.97-day run produces the measured
results in `FINDINGS.md` section 24.

### Exact fee boundary rounded up from 1.75 cents to 1.76 cents

**Symptom.** At one contract and 50 cents, floating-point error made `ceil`
charge 0.0176 instead of the exact 0.0175 fee.

**Mechanism.** The binary product was infinitesimally above 175 units before
the four-decimal ceiling.

**Fix.** Subtract a 1e-12 arithmetic tolerance before applying `ceil` in both
exit calculators. This changes only representational overshoot at an exact
boundary.

**Verification.** Dedicated tests assert taker 0.0175 and estimated maker
0.0044 at 50 cents.

## 2026-08-27

### One transient TLS EOF ended the intended 14-day capture

**Symptom.** The isolated server recorder ended after 9h51m. Its SQLite run was
closed cleanly and contained zero recorded errors, while the log ended with
`urllib.error.URLError` wrapping an SSL EOF.

**Mechanism.** `get_json()` converted HTTP error responses into data but caught
no connection, TLS, timeout, or invalid-JSON exception. The outer `finally`
flushed and closed SQLite, but the transient transport failure still terminated
the process. Because failure occurred before an HTTP response, no status row
was available for the caller to record.

**Fix.** Public GETs now retry three times with 1s/2s bounded backoff. If every
attempt fails, `get_json()` returns local sentinel status 599 and the existing
caller records the missing observation instead of ending the run. It still
does not retry venue HTTP statuses or any write operation; no write endpoint
exists.

**Verification.** One fixture fails once then succeeds and asserts two limiter
calls plus one backoff. A second exhausts all attempts and asserts status 599,
three limiter calls, and two backoffs. All 27 tests pass locally and on the
server, the module compiles, and exact commit `b970654` passed the endpoint
scan. R3 then encountered a real connection-reset `URLError` at 2026-08-28
10:27:03 UTC on attempt 1/3. It recovered without a restart or traceback and
continued writing fresh books through at least 12:58 UTC, with zero recorded
errors and zero non-200 book rows. Real-failure survival is now verified.
