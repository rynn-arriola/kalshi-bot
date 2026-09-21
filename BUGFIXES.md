# Bugfixes — kalshi-bot

Bugs that reached a running instrument. Symptom, mechanism, fix — written when
fixed, not at the end of a session. Companion to `FINDINGS.md`.

Nothing here has touched money: these are measurement bugs, and a measurement
bug that goes unrecorded becomes a "fact" in FINDINGS.

---

## 2026-09-21 — development components, no live account use

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
