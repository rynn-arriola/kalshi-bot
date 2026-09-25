# Current status

## Live trading resumed; emergency command remains isolated — 2026-09-24 20:12 ET

Release `40b69f0` is published with local/remote parity. The stopped-owner
reconciliation applied the three actual manual-close fills and canceled exit
evidence; local and venue cash matched, position was flat, and receipt-window
net P&L is -$2.184600. A verified stopped-ledger backup was retained locally.
The supported restart launched generation 144, currently PID 50416, supervisor
healthy. At 20:12:07 ET its fresh matching snapshot showed 20 resting entries,
zero positions, current account proof, no accounting blockers and healthy logs.
Earlier this run reached 22 entries, all 11 acknowledged pairs from the $2+
projected-reward tier. Ranking covered 1,024/1,024 in 101.7 seconds. Neither
full 30-order occupancy nor reward payout is established by these observations.

D-116 command-1 code is under development in ignored `data/command1-dev` Git
worktree; it is NOT in the active bot. Ten command tests, 45 live-runtime tests
and the 297-test fast subset pass. Initial isolated native tests failed because
the sandboxed children discard PYTHONPATH and loaded the other checkout. A
worktree-only venv with explicit local dependency paths fixes that mismatch;
all 12 native supervisor tests then pass. The initial full-suite run still needs
its final results inspected and affected environment tests rerun as necessary.
Logs: `data/command1-full.log`, `data/command1-fast-native.log`,
`data/command1-native-corrected.log`. No extra live restart solely to test this
feature is planned; keep current trading running while finishing verification.

## Manual-close accounting repaired; applying and restarting — 2026-09-24

The operator confirmed manual close and renewed restart authority. Fresh venue
reads show no orders or positions. The exact three-fill reconciliation dry-run
matches venue cash and records net loss $2.1846 without invented fills.
The 39-test accounting suite, fast gate (286 tests), and full 1,703-test gate
pass with one expected Windows privilege skip. Source/test diff review passed.
Apply the stopped-owner reconciliation, then supported restart; do not mistake
the former historical local position for fresh venue inventory.
Command-1 development is isolated in an ignored Git worktree and not deployed.

## Stopped for operator manual close — 2026-09-24 19:49 ET

The operator elected manual close after D-115. No one-off close was executed.
Exact generation 141/PID 44492 was reverified against scope, process identity,
timeout and stop latch, then terminated under D-112. Both managed processes are
absent; control generation 143 is stopped/disarmed with recovery required.
Last runtime evidence at 19:49:30 ET showed -10 contracts in
`KXTOKENUSE-26SEP28-T138` and zero entry orders. This is historical, not fresh
venue proof. The passive exit can remain after process termination; cancel it
before manual close. Await operator confirmation, then reconcile actual fills
and fees and verify flat before the authorized restart. No competing close.

Release `c9dce41` is published and fully tested. Normal refill acceptance remains
pending. Earlier running/draining statements below are historical.

## Race repair deployed; entries canceled, inventory drain active — 2026-09-24

Release `c9dce41` is published with local/remote parity. The first supported
start released the dead generation-139 ownership record. The next start launched
generation 141, PID 44492; the supported stop was delivered during startup so
normal entries stayed paused while it reconciled/canceled old orders. This was
a normal child explicitly stop-latched, not a recovery-only child as anticipated.

Live log `7d8e6d36360145d1844e91e6295d0691` records 21 cancel ACKs between
19:40:56.212 and 19:41:03.563 ET (7.351 seconds first-to-last ACK; approximately
7.5 seconds first-send-to-last-ACK). Resting entry count is zero. Reconciliation
found one -10-contract `KXTOKENUSE-26SEP28-T138` position from an earlier entry;
the bot acknowledged its passive reducer and remains `DRAINING`. Its current
first-seen clock is 19:41:06 ET, so the existing 15-minute timed-exit policy is
due around 19:56:06 ET if it has not closed sooner. The supervisor shutdown
timeout does not kill this inventory owner. No force termination was performed.

The open position, not entry cancellation latency, now delays flat restart.
Keep the approved exit policy unless the operator separately authorizes an
immediate close. Final normal-run refill acceptance remains pending.

### Release verification

Finding 177 is fixed in source and passes all 44 production-mode synthetic entry
tests. Three race reproductions failed before their corresponding fixes. The
first complete gate ran 1,702 tests and exposed two outdated mocks (async status
and the new background keyword); both fixtures were corrected and their 30/49
test suites pass. The final complete gate passed 1,702 tests in 216.744 seconds,
with no failures and one expected Windows symlink-privilege skip. The fast gate
passed 285 tests before the final in-flight-read regression; that regression is
included in the final full run. Actual source/test diff review and whitespace
checks passed. No changed build has been deployed yet.
Generation 139 is no longer present: its last saved snapshot at 19:26:00 ET had
22 entries, zero positions. The supported stop at 19:31:34 latched/disarmed control
but had no child to signal. Do not treat absent processes as canceled orders.
The authorized restart must reconcile and drain through recovery-only first.

## Stop/recovery latency repair deployed; refill still slow — 2026-09-24

Release `1c9c326` is published and running as generation 139, PID 50452, following
the authorized start at 19:09:15 ET. At 19:16:39 ET local telemetry showed 12
resting entries, zero positions, a current account report, no accounting blockers,
all six readers subscribed and healthy logging without drops/backlog. All six
acknowledged entry pairs were selected from the $2+ priority tier. This is not
proof of reward payout or a completed 30-order refill.

Live repair latency across 26 completed passes was 3.165–4.339 seconds
(mean 3.650), versus the previous repeated approximately 20-second passes.
72 routine renewals completed with zero escalations; the latest took 1.366
seconds. Full ranking covered 1,024/1,024 markets in 152.8 seconds. Startup public
discovery encountered 23 rate-limit retries before completing. Refill progressed
beyond the old two-order stall, but entry source changes still defer attempts
and refill is not yet fast; do not call the entire lifecycle optimized.
There were no ERROR/CRITICAL events in the observed current-run log sample.

Cancellation scheduling is regression-tested during recovery, but live
stop-to-cancel/exit latency on this build has not been measured. No extra stop
was issued just to obtain a benchmark. The current bot remains running.

### Release verification and predecessor

Generation 136 canceled its two entries and eventually reached `STOPPED_FLAT`
at 18:58:43 ET. Both managed processes have exited; no forced termination was
performed on that generation. The prior supervisor timeout remains historical.
Live refill on `63302b4` was not accepted: ranking completed but recovery after
the first pair still repeatedly approached/exceeded 20 seconds.

Finding 176 identifies a local database bottleneck omitted from the initial
API-latency diagnosis. The correction shares order classification, schedules
paused cancels immediately, overlaps final recovery financial reads and avoids
premature renewal during flat shutdown. Focused regressions and same-ledger
offline timing checks pass. The complete release suite ran 1,697 tests in
318.963 seconds with no failures and one expected Windows symlink-privilege
skip; the fast gate passed 281 tests. Source/test diff review and whitespace
checks passed. Source publication and the authorized restart are complete;
the observed refill limitation and unmeasured stop timing are stated above.

## D-113 concurrent renewal correction verified; restart pending — 2026-09-24

The first generation-133 deployment proved that advisory ranking can complete
1,024/1,024 markets during account recovery, but routine renewal intermittently
spent approximately 4.0–4.4 seconds on its snapshot/tail and another 0.6–0.9
seconds on serial financial reads. The unchanged five-second fence therefore
expired, full recovery retried, and refill stalled at two resting entries.

The corrected path collects independent snapshot and financial documents
concurrently under the same original source fence and reuses the fresh account
balance. Exact source, writer, history, cancellation and economic checks remain.
Focused account/recovery tests pass, the fast gate passes 277 tests, and the
complete gate passes 1,691 tests with one expected Windows symlink-privilege
skip. The authorized stop canceled the two entries, verified zero positions,
and exact-child timeout handling left the managed bot fully stopped. Commit,
push and live startup acceptance are pending.

## D-113 verified source repair; not deployed — 2026-09-24

Routine startup/refill renewal now obtains fresh account and financial evidence
without replaying the full opening-to-now history and management pass. Exact
writer/source checks, bounded receipt chains and existing five-second release
fences remain. Metadata and advisory ranking can progress through recovery,
but advisory rows cannot authorize orders. D-109's full-cap shortcut remains
first to avoid adding steady-state work. See `BUGFIXES.md` and Finding 175.

The final complete release suite ran 1,690 tests in 291.256 seconds with zero
failures and one expected Windows symlink-privilege skip. The earlier fast gate
passed 274 tests; final timer/lock regressions are included in the complete run.
Focused account-release (38), selection (48), initial-ranking (30) and metadata
scheduler (32) suites also passed. Negative controls detect disabled renewal
and advisory coverage. A supplemental temporary-ledger check renewed accounting,
reserved an actual writer-owned pair, invoked one synthetic batch transport and
retained two ACKs. No network was involved in these checks. Diff review found no
remaining blocking issue; full recovery now waits for an in-flight refresh
instead of spending retries against its lock.

No live restart or venue operation has been performed for D-113; production
continues to use its previously loaded code. At 18:09:13 ET local telemetry
reported 14 entries, zero positions, healthy logging and no new renewal counter,
consistent with the old build. Deployment acceptance and real startup/refill
latency remain unverified until a separately authorized restart.

## Generation 131 running; startup/refill recovery loop diagnosed — 2026-09-24

Latest local runtime observation: 17:52:16 ET, 12 resting entries and zero
reported positions. All six readers are subscribed; logging is healthy without
drops. Historical ranking coverage is 959/1,024 with zero source resets and
`priority_capacity_met`; this is not a current executable slate or full refill
acceptance. Steady-refresh attempts remain zero. Recovery repeatedly interrupts
metadata work and current candidate selection.

The source published through `6db4d6e` includes semantic catalog continuity,
partial reward-change preservation and priority-candidate revalidation. Earlier
generation-125 deployment tasks below are historical, not pending instructions.
Generation 131's loaded build fingerprint is
`f6694d822acb0bc02b847988927e5a46fd2dbf3e41b4178dc1e73a18a6365541`.

[Finding 175](FINDINGS.md#175-routine-freshness-recovery-starves-startup-and-refill--2026-09-24)
records the confirmed scheduling problem, live measurements, offline
reproductions and limits of the evidence. Investigation is complete; the
recommended refresh/ranking repair is not implemented. Four focused offline
regressions passed. This investigation changed only documentation: no runtime
configuration, source, orders, processes or live database were modified, and no
restart was performed. Reported account counts are local telemetry, not a new
independent venue reconciliation.

## Historical status records

## Generation 125 flat in semantic-blind ranking reset loop; repair verified — 2026-09-24

The final accounting-recovery repair deployed successfully: recovery-only
completed on its first pass, cleared both history blockers, proved zero orders
and positions, reached `STOPPED_FLAT`, and handed off to normal generation 125.
All six readers subscribed and the normal child remains supervisor/logging
healthy with zero dropped logs and no position. Its ranking cannot finish on the
loaded build because every periodic reward-catalog observation timestamp is
treated as a changed reward universe. By 16:18 ET it had reset eight times,
retained 34 historical $2+ candidate hints, held zero orders and was evaluating
319/1,024 markets in the latest generation. Hints do not authorize entries.

Source now identifies a reward catalog by a deterministic digest of its active
program identities, markets, exact economic terms, start/end, payout state and
excluded markets. A refresh with identical semantics preserves initial-ranking
coverage; a semantic change still resets it. A missing/revoked catalog grants no
authority and does not erase coverage before its replacement can be compared.
Affected discovery/ranking tests, the 263-test fast gate and complete 1,674-test
suite pass with one expected Windows privilege skip. Generation 125 cannot
hot-load the repair and remains flat pending replacement under the authorized
restart operation.

## Generation 119 flat in recovery-only; incremental release proof verified — 2026-09-24

The authorized supported restart canceled all 28 generation-116 entries and
verified zero positions. The old loaded child could not complete its final flat
proof before `shutdown_timeout`; D-112 identity, generation, scope, stop-latch,
command line and current zero-order/zero-position checks were repeated, then
only exact child PID 50360 was terminated. Its parent exited and the supported
launcher started generation 119 in recovery-only mode. It remains flat with no
resting orders and cannot place entries, but the first repair's second complete
opening-to-now history scan makes each recovery exceed the unchanged 20-second
whole-pass deadline. The child is retrying transiently rather than releasing.

Source now preserves the first complete history proof and, after management,
enumerates only the elapsed tail from that receipt's exact eligible right edge
concurrently with the final account snapshot.
Operational release accepts the chained receipts only when their union has no
gap, every receipt has matching provenance and no omission, and a receipt with
a right edge inside the existing five-second window reaches the final account
observation. An empty omission-free tail does not invalidate the concurrent
snapshot; any new or omitted fill rejects the shortcut and requires another
ordinary full recovery. The account signature is rechecked and no freshness,
timeout, ownership, source or mutation fence is widened. Focused tests,
the 263-test fast gate and complete 1,672-test suite pass with one expected
Windows privilege skip. Generation 119 cannot hot-load this final repair and
must be replaced through the already authorized supported restart operation.

## Generation 116 live on paused-reducer repair — 2026-09-24

The old generation became flat and exited naturally before the separately
authorized exact-PID termination ran, so no process was killed. Its final current
account snapshot had zero positions and `STOPPED_FLAT`. The supported launcher
then started published commit `f46c23c`; recovery-only proved flat and the
supervisor launched a fresh normal child with build fingerprint
`34342a52bac7208a96a2b42361167f773845f704b8895041c5ed0262e3774da4`.

Generation 116 completed current four-shard coverage of 1,024/1,024 markets
after two source-generation resets and reached the configured cap of 30 resting
entry orders across 15 markets. Dispatch evidence classifies 14 markets in the
$2+ projected-reward priority tier and one allowed $1+ fallback at approximately
$1.47; projected rewards are not verified payouts. Repeated current samples show
zero positions, all six readers subscribed, no risk/accounting/supervisor hold,
zero reader/recovery retry rounds, healthy engine/dispatch/logging, and zero
dropped logs. Both live SQLite databases report `quick_check: ok`. The current
run has no ERROR/CRITICAL event; 16 handled startup HTTP 429 retries and 17
temporary recovery-incomplete warnings cleared without an exhausted retry.

## Generation 114 stop-latched on old reducer path; repair verified — 2026-09-24

The supported restart entered recovery and canceled all 26 stale entry orders,
but the old loaded child retained one owned passive reducer and a 10-contract
short position in `KXCTMFPERMITS-27MAY03-T4000`. A supported stop is latched;
the supervisor and child remain present in `attention_required` with
`shutdown_timeout`, entries paused and no entry orders. All six readers and
logging remain healthy. The status field `resting_entries: 0` counts entries and
does not imply that the reducer is absent.

The source repair permits the empty paused entry-drain path to continue through
the existing source-verified reducer cancel-before-IOC plan. Its regression, the
263-test fast gate and the complete 1,671-test suite pass with one expected
Windows privilege skip. The current process cannot hot-load this repair. No
force termination, direct venue mutation, database edit or second bot was used.

## Generation 111 blocked by closed-market settlement; source repair verified — 2026-09-24

Generation 111 remains present under its supervisor with 28 resting orders,
zero reported positions and all six readers subscribed. It is degraded and
cannot refill because `settlement_reconciliation_required` is latched after
`KXTRUEV-26SEP23-T1258.69` settled. The retained ledger proves that the bot had
already bought 10 YES at $0.20 and sold 10 YES at $0.02 before settlement,
leaving no lot; matched-fill accounting already booked `-$1.8138` including
fees. The venue settlement row exactly reports 10 YES/$2.00, 10 NO/$9.80,
$0 revenue and $0.0138 fees.

[The source repair](docs/BUILD_CLOSED_SETTLEMENT_RECONCILIATION.md) clears only
this hold when current venue evidence exactly matches fully closed, owned,
terminal fills and the account remains flat for the ticker. It never books
settlement economics twice. Open, missing, external, uncertain or conflicting
evidence remains blocked. Focused tests, the 262-test fast gate and the complete
1,670-test suite pass with one expected Windows privilege skip. A read-only
online copy of the actual production ledger also produces the exact two-fill
proof. No live process or order was changed; generation 111 still runs the old
build until a separately authorized supported restart.

## Generation 111 running after exact funding recovery — 2026-09-24

The repair published at `ba3c19c` is live. After identity, generation and flat-
state checks, the separately authorized force termination targeted only stale
generation-108 child PID 22556; its parent exited without intervention. The next
supported launch retained the unexpected-death/cleanup reasons and ran recovery-
only. That child cleared the false `cash_activity_unattributed` hold through the
exact accounting release, proved current zero orders/positions/exposure and
reached `STOPPED_FLAT`. The supervisor then launched fresh normal generation 111.

Generation 111 ranked 1,024/1,024 reviewed markets across all four book shards
before rebuilding. It reached 30 resting entries across 15 markets; all 15 have
priority-tier dispatch evidence and the minimum projected remaining reward is
$2.158. Two stable acceptance samples 20 seconds apart show zero positions,
current account proof, six subscribed readers, no risk/accounting hold, no retry
round, healthy engine/dispatch/logging and zero dropped logs. Both account and
supervisor SQLite `quick_check` results are `ok`. Nineteen handled startup HTTP
429 retries and temporary incomplete-recovery warnings cleared without a lasting
hold; the acceptance log scan found no ERROR/CRITICAL event. A later one-order
vacancy returned from 29 to 30 through normal refill and stayed at cap for three
consecutive current-account samples. Actual reward payout and profitability
remain unverified.

## Generation 108 running on D-110; unattended-recovery release accepted live — 2026-09-23

All four Finding-169 gaps now have code and focused offline regressions: persistent
capped reader rounds, classified transient account-repair retries, truthful child
health, verified-flat crash recovery followed by a fresh ranked normal child, and
hash-only rollover of superseded observation archives. Manual stop, ambiguous
orders, incomplete cleanup, loss/economic restrictions and integrity failures
remain fail-closed. Exact economic rows are not rolled up. The complete release
gate passed 1,662 tests with one expected Windows privilege skip before the final
test-only stable-reader regression; that 49-test module and the 274-test fast plus
native-supervisor gate also pass. Exact-diff review found no release blocker.

The supported restart canceled all 30 generation-106 orders and reached
`STOPPED_FLAT` with zero orders, positions and exposure before disarming. Published
commit `600b109` then started generation 108 with the matching production build
fingerprint. Ranking covered 1,024/1,024 markets across four book shards in
209.19 seconds and rebuilt 30 resting orders across 15 markets. Every selected
market was a $2+ projected-reward priority candidate at dispatch. The acceptance
sample has zero positions, current account proof, all six readers subscribed,
healthy parent/child, logging and dispatch, zero retry rounds, no risk/accounting/
supervisor blockers, and 22/22 successful steady account refreshes. SQLite
`quick_check` is `ok`. Ten handled startup HTTP 429 retries and one transient
in-flight `SENDING` status snapshot caused no unknown mutation or lasting hold.
Actual payout, profitability and a natural crash-recovery incident remain
unverified by this restart.

## Uptime review complete; unattended recovery gaps remain — 2026-09-23

Generation 106 remains running unchanged: at 22:37 ET, 30 resting orders,
zero positions and all six readers subscribed. This review did not restart,
stop or mutate the bot. [Finding 169](FINDINGS.md) records four priorities:
finite account/book retry rounds, transient account repair that can remain
blocked, intentional crash-recovery-to-disarmed policy, and finite archive
capacity. Healthy process heartbeats alone do not establish recovery/refill
readiness. Offline reproductions confirmed these paths; 257 fast tests and
26 durable-accounting tests passed. Fixes/automatic rearm policy are not yet
implemented or authorized by this review, and long unattended uptime is not
certified. Current short reconciliation gaps are distinct from persistent faults.

## Generation 106 running on D-109; journal recovery accepted live — 2026-09-23

The operator-authorized restart first canceled all 30 generation-102 entries.
The account showed zero resting orders, zero positions and zero exposure, but
the old loaded build could not append the final flat proof after its hot
accounting journal filled and reached `shutdown_timeout`. With separate operator
authorization, only the exact generation-102 child PID was force-terminated;
its parent then exited and no unrelated process was touched.

The next launch correctly ran recovery-only. It archived 8,192 superseded
accounting events, cleared `accounting_journal_full` only through a successful
exact accounting release, proved `STOPPED_FLAT`, and disarmed. A second explicit
launch started normal generation 106 from published commit `b75ea57`. Initial
ranking covered 1,024/1,024 reviewed markets in 196.08 seconds before entry.
The latest acceptance sample has all four book shards plus account and lifecycle
subscribed, 30 resting orders across 15 markets, zero positions, about $137.80
exposure, healthy supervisor/logging/dispatch, current account evidence and no
accounting hold. The bounded steady path completed 52 refreshes with zero
escalations and suppressed 71,777 optional unowned-market evaluations.

Read-only SQLite `quick_check` is `ok`. The hot journal has 15,977 rows and
47,656,154 payload bytes; four hash-verified compressed archives retain 8,192
older exact events, reducing 19,774,412 source bytes to 1,040,549 compressed
bytes. This fixes the immediate hot-journal saturation. Exact cold audit
archives still grow and have a deliberate finite capacity, so their measured
growth and a leaner normalized/hash-only persistence follow-up remain open.
The initial restart also handled 19 HTTP 429 read retries without a component
failure. Actual paid reward, profitability and long-duration retention remain
unverified.

## Generation 102 degraded; bounded steady-state repair verified offline — 2026-09-23

Generation 102 still runs deployed source `fb5dc68`. Its parent and child remain
present with all six readers subscribed, 30 resting entry orders, zero positions
and about $142.70 exposure. Dispatch, reward tracking and logging remain alive,
but account authority is blocked: repeated full recovery filled the 64 MiB hot
accounting journal at 21:29 ET, latching `accounting_journal_full` and
`blocked_retry_exhausted`. Read-only SQLite validation reports `quick_check=ok`;
23,972 of 23,975 journal rows are repetitive inspection, cash and operational-
release observations, not new fills or positions. The running generation has not
been restarted, canceled or modified.

Offline source now uses one exact account snapshot refresh when the account is
flat and at its 30-order cap, retains full WebSocket ingestion, and performs deep
market work only for the 15 exact owner markets until any source/state change
forces ordinary full recovery. Superseded recovery observations are moved
atomically into compressed, hash-verified audit archives; economic events remain
hot and archived event identities still prevent duplicates. A synthetic 1,024-
market benchmark processed all decisions while suppressing optional work for
1,009 unowned markets and used 7.14% of baseline CPU. The fast suite passes 257
tests and the complete suite passes 1,657 tests with one expected Windows
privilege skip. Deployment and supported restart remain separate operator
decisions; live recovery, CPU and reward-coverage improvement are unverified.
The separate broad-discovery benchmark completed all functional checks twice
but missed its existing 100 ms p99 loop-lag target at 117–121 ms; that timing
follow-up is recorded rather than represented as a passing acceptance result.

## Generation 97 stopped flat; shutdown and reward-gap repairs verified offline — 2026-09-23

Generation 97 completed 1,024/1,024 initial ranking, subscribed all four book
shards plus account and lifecycle, reached 30 resting entry orders, and reported
no position or current risk/accounting blocker. The 96 MiB diagnostic bound was
active. A stable 30-second sample nevertheless observed only 10.606 of 183.601
aggregate program-seconds (5.78%); frequent three-second account reconciliation
still consumed nearly every five-second reward proof despite the earlier
endpoint-retention repair.

The supported stop canceled all 30 entries and the last runtime published
`STOPPED_FLAT` with zero orders, zero positions and zero exposure. The parent and
child are now absent. The supervisor incorrectly retained
`attention_required/unknown_failure`: STOP advanced the durable control
generation, then the exact still-bound child rejected its cleanup-only control
message as an identity loss before publishing a clean result.

Source now keeps the generation fence as revoked trading authority while
allowing only exact bound `PULSE`, `STOP_HINT` and `FENCE_ACK` cleanup traffic;
the parent also refreshes the durable state before applying a redundant local
STOP. Reward telemetry may sample the unexpired remainder of a prior queue proof
only during an exact normal reconciliation token with unchanged account
generation/revision, writer state, order signature, plan, book and reward terms.
It never restores current reward, selection, maintenance or dispatch authority,
never extends the five-second lease, and records expired or changed evidence as
UNKNOWN. Account revision is now part of tracker continuity.

Focused account, runtime, reward and supervisor verification passes **376
tests** with one expected Windows privilege skip. The complete suite passes
**1,650 tests** in 292.702 seconds with the same expected skip; compile and
whitespace checks pass. The bot remains stopped; this repair is offline
verified but not deployed, and live reward coverage improvement remains
unverified.

## One-sided incumbent release repaired offline — 2026-09-23

Generation 92 exposed one 10-contract entry orphan that remained for more than
30 minutes after its opposite side had a confirmed cancel ACK. The market stayed
fully price-weighted on the surviving side, but a fresh replacement pair no
longer cleared the $1 projected-reward gate. Maintenance accumulated more than
its 90-second verified dwell and then had no transition because the actual row
had no blocker and the target was uneconomic.

Source now withdraws that exact orphan without re-entry after the existing
90-second fresh-evidence dwell, releasing the capacity to ordinary ranked
selection. A still-qualifying incomplete pair retains the existing 30-second
same-program repair. Exact account, lifecycle, source-lease and cancel proof are
unchanged. The new regression failed against the old branch at 92 verified
seconds; both paths now pass. Focused maintenance, dispatch and live-runtime
verification passes 140 tests. The complete suite passes **1,647 tests** with
one expected Windows privilege skip; `git diff --check` passes. Generation 92
still runs the previous source until the authorized supported restart completes.

## Reward telemetry continuity and retention repair verified offline — 2026-09-23

The two defects identified by the generation-92 audit are repaired in source
and regression-tested. Normal account-report refresh gaps now suspend the
current reward rate without deleting its prior bounded endpoint. A later exact
observation can bridge only when the existing five-second leases overlap and
the writer epoch, account/book generations and owned-order identity are
unchanged; expired, changed or conflicting evidence remains UNKNOWN. Production
child diagnostics are now configured for a bounded 96 MiB across the current
file and seven archives, projected to retain about 7.2 hours at the measured
generation-92 byte rate instead of about 3.4 minutes. The configured bound is
reported in logging status.

Focused affected verification passes 328 tests with one expected Windows
privilege skip. The exact complete suite passes **1,645 tests** with one expected
skip; `compileall` and `git diff --check` pass. This is offline verification,
not evidence that live reward coverage improved. Generation 92 was not stopped,
restarted or otherwise changed and continues to run its previously deployed
source. See [build record](docs/BUILD_REWARD_TELEMETRY_CONTINUITY.md).

## Generation 92 flow audit — 2026-09-23, approximately 18:36 ET

The bot remains live with 30 resting entry orders and no open inventory at the
latest audit. The oil position exited automatically; its net result was
-$0.7744 including fees. All active entries matched their admission evidence
(28 priority, two fallback). Account reconciliation, feeds, execution and
observed repricing are operational; no current risk/accounting blocker was
reported. This supersedes the open-position snapshot below.

The audit found poor reward telemetry coverage (about 4.7% over a measured
24.6-second interval) and only about 3.4 minutes of retained child logs.
Consequently, neither continuous reward qualification nor profitability is
established. See [finding 163](FINDINGS.md). This was a read-only live audit;
no restart, code/configuration change or induced failure test was performed.

## Generation 92 live after exact account reconciliation — 2026-09-23

The explicit operator close is reconciled and the venue/local account are flat
with respect to inventory before this run. The full suite passes **1,641 tests**
with one expected Windows privilege skip; source commit `9fad565` is published
with local/remote parity. A recovery-only launch verified zero orders, zero
positions, current account evidence and no accounting blockers, then stopped
flat and disarmed.

Generation 92 is now running the deployed source. It completed initial ranking
for **1,024/1,024** reviewed markets using four subscribed book shards. The most
recent acceptance snapshot reported **22 resting orders**, 25 remembered
priority candidates, zero positions, current account evidence, healthy logging,
no risk/accounting blockers and no book or dispatch failure. Projected rewards
remain estimates; paid reward and profitability are not yet proven. A subsequent
current snapshot reached the configured **30 resting-order cap** and reported one
10-contract short inventory position (`KXTXOIL-27MAR31-T5.8`); account evidence
remained current with no reported risk or accounting blocker. Its normal exit
path must now be monitored rather than treating the earlier flat snapshot as
current.

## D-106 priority-admission review fixes published; generation 76 unchanged — 2026-09-23

Generation 76 was locally observed healthy with 30 resting entries and zero
reported positions during this read-only audit. Complete historical coverage
does not prove all eligible $2 candidates received a current admission check:
temporary source/account invalidation deletes their ranking rows. A synthetic
unchanged-market reproduction confirms fallback can then be selected. The
[D-105 repair](docs/INVESTIGATION_PRIORITY_ADMISSION_2026-09-23.md) now retains
bounded advisory candidate history, promotes its refresh ahead of optional
metadata, and defers fallback while a bounded priority batch is unresolved.
Current source/risk/dispatch proofs remain mandatory; hints never authorize an
order. Early priority release is now exercised through the real runtime turn and
historical coverage continues afterward. Final review found three gaps: fresh
definitive ineligibility could retain an obsolete priority hint, one stalled
candidate could prevent a bounded batch from advancing, and prepared attempts
could be reported as admitted before a venue outcome. D-106 repairs all three.
The complete suite passes **1,638 tests** with one expected Windows privilege
skip; focused dispatch/selection/runtime suites pass 152 tests. Reviewed source
commit `f6b9e3f` is published with local/remote parity. It is not deployed and
generation 76 continues running its prior `e614981` code.
The earlier complete 5-priority/10-
fallback count was not supported by a complete current sample; see the audit.


## D-104 deployed; generation 76 live acceptance — 2026-09-23

Generation 72 proved that four public-book shards were not the remaining market
coverage bottleneck: all 1,024 reviewed books received reasoned evaluations and
the runtime reached 30 resting orders across 15 markets. The shared metadata
scheduler still refreshed the entire 1,024-market discovery set with two equal-
priority workers, so incumbent maintenance metadata could cycle through source
loss even while its orders remained live.

Broad discovery now uses four bounded metadata workers and always schedules due
owned/maintenance markets before optional candidates. Discovery remains bounded
and one account/mutation owner is unchanged. The same live run stopped flat with
zero orders and positions, but an in-flight parent `PULSE` reached the child
after its stop latch and was incorrectly classified as revoked authority. A
stop-latched child now accepts only liveness/cleanup messages (`PULSE`,
`STOP_HINT`, exact `FENCE_ACK`); `ADMIT` and trading authority remain rejected.

Focused verification passes 120 tests, the exact composition suite passes three
tests, and the complete suite passes **1,630 tests** with one expected skip.
`compileall` and `git diff --check` pass. Reviewed source commit `e614981` is
published with local/remote parity.

The first supported launch ran required recovery-only generation 75 against the
preserved ledger, verified zero entries/positions, exited `STOPPED_FLAT`,
published its terminal result and disarmed without the former false failure.
Normal generation 76 then subscribed four book shards plus account/lifecycle,
reached metadata concurrency high-water four and completed reasoned ranking for
1,024/1,024 markets before admitting entries. It reached **30 resting orders
across 15 markets, zero positions and $118.00 reserved exposure**.

After admission settled, all 15 maintenance markets were simultaneously
`OBSERVED` and retained; all 30 sides had full reward price weight. Fourteen
pairs exactly matched their owner-adjusted references and one bid was better
than reference while still qualifying. Logging is healthy with zero drops;
engine/dispatch/reward reflection report no failure. Eleven bounded
`recovery_incomplete` warnings occurred while newly acknowledged pairs changed
the account snapshot, with no retained warning after admission stabilized and
no ERROR/CRITICAL event. This proves the exercised source/maintenance path, not
paid reward, profitability or future fill/exit performance. The bot remains
running under generation 76 with the preserved limits and ledger.

## D-103 repaired and verified offline; stopped, not restarted — 2026-09-23

The exit incident, recovery starvation and initial-ranking priority defect are
repaired in the working source. Passive GTC exits now use the venue-valid wire
flag while durable managed-exit proof remains authoritative; due IOC remains
reduce-only. A due inventory episode can rearm one exhausted recovery and must
obtain fresh account proof before dispatch. Incomplete ranking timeout no longer
releases entries; a current $2 slate may release early only when it fills every
available pair slot, and remains priority-only until full coverage.

The order-disabled repeated 1,024-market probe received all books with 100%
five-second freshness in all four stages. Four shards passed both target sets;
two shards had one callback-ingress p99 miss. `config/bot.json` is prepared with
four book connections. The bot remains `STOPPED_FLAT`; no restart, deployment,
private API call, order action or production-ledger change occurred. Build and
measurement details: [D-103](docs/BUILD_EXIT_COVERAGE_PRIORITY.md).

Focused verification passed 402 tests. Final review found and repaired the old
two-shard event-engine construction bound, then added an actual four-shard engine
regression. The post-fix complete suite passed **1,628 tests** with one expected
skip in 276.071 seconds. The reviewed implementation is published as `4f5f902`;
local and `origin/master` were verified equal before restart preflight.

## Stopped flat after recovery-only IOC — 2026-09-23

A read-only WebSocket capacity probe began at 17:18:01.897 UTC. The venue fill
preceded it at **17:18:01.626 UTC**, so the probe did not cause the fill and made
no account or order request. The owned ask in `KXONPOS-26OCT03-T109` filled 10
contracts at 81 cents, leaving a locally reconciled **-10 YES-equivalent** lot.
The opposite entry was canceled. A passive reduce-only bid at 73 cents received
HTTP 400; account recovery then exhausted with 29 unrelated resting entries.

The supported safety stop was invoked. It acknowledged all 29 remaining entry
cancels from 17:22:47–17:22:56 UTC. Two more passive reduce-only bids at 73 cents
were rejected with HTTP 400. Recovery then remained exhausted past the existing
15-minute IOC deadline. After exact PID/parent/session verification, only the
stalled protected child was terminated; its Windows job closed the correlated
parent. No broad process kill, account-wide cancel or ledger reset was used.

The supported launcher started recovery-only generation 71. It reconciled the
preserved lot and submitted the overdue ledger-backed IOC: 10 YES bought at 89
cents at **17:35:02 UTC**. Gross trading loss was **$0.80**, fee **$0.0686**, net
**-$0.8686**. Generation 71 then exited `STOPPED_FLAT` and disarmed. A separate
authenticated GET-only check confirmed **zero resting orders and zero nonzero
positions**; the ledger has zero lots and zero pending fills. Reported account
balance after the close is **$496.1928**. The bot remains stopped.

The capacity probe completed 128 and 256 markets and reached initial snapshot
coverage in 0.34 and 0.56 seconds with 100% and 99.6% minimum steady freshness.
At 512 markets, both current book sockets received all 512 initial snapshots in
0.45 seconds, but five-second fresh coverage fell to 61.1%; the probe stopped
before 1,024 as designed. Initial delivery is not the bottleneck. Refresh cadence
or shard count must be compared in an order-disabled probe before changing the
production topology. Artifact:
`data/book-capacity/d6e3efe0165341fcb5645c419f3bd6fe/result.json` (ignored).

## D-101 deployed; generation 68 live acceptance — 2026-09-23

The operator authorized restart after the verified generation-66 stop. Canonical
source was fast-forwarded without changing the production ledger or limits. The
first supported launch safely released the dead native child reservation and
started no trader. The second launch started normal generation 68 on reviewed
commit `c15d709` with build fingerprint
`ff3cd91803c454d8c742079721734995521c512d5c1dd97238fdace9f57f558c`.

At **17:01:58 UTC**, protected parent/child presence and healthy control were
current; all four readers were subscribed; engine, dispatch and logging reported
no failure; logging had zero drops; account and entry authority were current;
and the bot held **30 resting orders across 15 markets, no reported position and
$117.70 reserved exposure**. Initial ranking released at its 120-second bound
after evaluating 749/1,024 markets across both book shards.

D-101's actual maintenance path completed twice under live account evidence.
`KXMONSTERPOS-26OCT03-T101` moved from `0.69/0.83` to the sampled reference
`0.69/0.82`; `KXTOKENUSE-26SEP28-T144` moved from `0.10/0.58` to `0.10/0.56`.
Each cycle canceled exactly its two owned orders, waited for account recovery,
and restored a complete size-10 pair. The ledger recorded four cancel ACKs and
four replacement-create ACKs, with **zero fills, zero pending fills and zero
open lots** in generation 68 through acceptance. The bot returned to 30 orders.

An independent public-only 1,024-market census found 286 $1-pass markets and 38
$2-priority markets. All 15 selected markets passed; 11 initial pairs exactly
matched the later sequential references. Live owner-bound maintenance samples
classified the intentionally better-than-reference `KXTOKENUSE...T138` pair as
full-price-weight and retained it. The census is sequential, includes aggregate
own liquidity and assumes flat $500 capital; it does not prove global optimality,
paid reward or profitability.

Reward reflection completed repeatedly and supplied current owner-bound
maintenance observations. One bounded `QuotaUnavailable` reflection warning
occurred while the separate public census was running; subsequent reflections
completed. Expected first-pass `recovery_incomplete` warnings occurred while
replacement orders changed the account snapshot, then repaired. No blocking
runtime, control, account, dispatch, engine or logging issue remained at the
acceptance checkpoint.

## D-100 deployed; generation 66 live acceptance — 2026-09-23

Canonical source `dddc1eb` is deployed with the preserved production ledger and
unchanged limits. The old generation could not complete its normal stop because
the already-full history receipt table prevented current account proof. After a
complete authenticated GET-only enumeration verified **0 resting orders and 0
nonzero positions at 15:18:20 UTC**, only the correlated old parent PID 11100 and
child PID 28176 were terminated. No broad process kill, ledger reset or account-
wide cancel was used.

The first cold host safely released the stale native child reservation without
starting a child. Recovery-only generation 65 then ran the reviewed source,
archived the exact 4,096 old history receipts, retained one hot receipt, obtained
current account evidence, completed one repair pass and terminated
`STOPPED_FLAT` with all recovery reasons cleared. Reward reflection deferred
until the account report existed and then completed without failure.

Normal generation 66 is accepted at **15:28:20 UTC**: parent PID 47516, child
PID 24180, runtime `2d25b14f931840b28a9af02c7ee34faf`, correlated build
fingerprint `183f19e91ad294c6249aae8225d1adbf94b9a46059b96ef38bb729f59465d393`.
Control is healthy; account and entry authority are current; all four readers
are subscribed; engine, dispatcher and logging report no failure; and logging
has zero drops. The bot holds **30 resting orders, no reported positions and
$133.10 reserved exposure**. Initial ranking released at its 120-second bound
with 762/1,024 markets evaluated across both book shards. Active six-hour
settled P&L is **-$3.365400**.

Startup emitted bounded first-attempt HTTP-429 retries and transient incomplete
reconciliations while acknowledged entry orders changed the account snapshot;
later passes repaired and current authority was restored. Reward-reflection
failures during those moving snapshots were followed by successful reflections
and no retained error. These observations do not prove payout, profitability,
future source availability or a future live drain latency.

## D-100 reliability bundle prepared; generation 63 recovery-blocked — 2026-09-23

[Implementation and review](docs/BUILD_LIVE_MAINTENANCE_RELIABILITY.md) repair
the reproduced maintenance dwell starvation, stale maintenance-send lease,
account/reflection phase mismatch, deterministic reducer retry storm, empty-
market diagnostic flood and the later history-receipt capacity crash. Poly
executable code was used as a reference for bounded recent history and separate
risk-reducing rejection handling; Kalshi retains its exact receipt audit trail
in an atomic compressed archive and uses durable consecutive 10/20/40/60-second
reducer backoff. No risk, selection, size, loss or exit deadline changed.

Production still runs old source `ad96429`; this repair is not deployed and no
assistant restart occurred. The original child PID 42520 failed at 14:25:20 UTC
when `history_enumerations` reached exactly 4,096 rows. Supervisor generation 63
automatically replaced it with recovery-only child PID 28176. That child
acknowledged 30 cancellation mutations, but recovery exhausted and its current
account proof is absent. At 14:46:23 UTC status was `RUNNING_UNVERIFIED` /
`DRAINING`, with zero locally reported orders/positions and zero exposure.
Those zeroes are historical local observations, **not verified venue flatness**.

Read-only ledger evidence contains 79 repeated passive TRUEV HTTP-400 rejects:
39 at 40c, 22 at 39c, one at 38c and 17 at 37c, plus one earlier unrelated
rejection. No mutation remains UNKNOWN and current retained logs contain no
WARNING/ERROR event. The three rotating logs cover only about ten seconds
because 1,815 of 1,895 records were empty-market `inventory_plan_changed`
events across broad discovery; D-100 suppresses that noise. The replacement
child logged 48 expected publication races and four quota deferrals as ERROR;
these now retry/defer without spending market failure attempts or claiming a
failed dependency. Its 533 no-report reward attempts are also changed to local
deferrals with no queue request, followed by immediate reflection after a
successful recovery. Its readers, engine, dispatcher and logging remain alive,
but recovery is blocked until a reviewed deployment/restart. Final verification:
**1,611 tests passed, one expected Windows privilege skip**, 259.825 seconds.
Reviewed implementation commits `5df66f7` and `09cb482` are published to
`origin/master`. The isolated checkout and remote contain both; the canonical
live checkout deliberately remains on `ad96429`, so publication is not deployment.

## D-099 deployed and live restart accepted — 2026-09-23

Canonical source commit `ad96429` is deployed. A fresh pre-start venue check at
**13:18:08 UTC** verified zero resting orders and zero nonzero positions without
modifying the production ledger. Supervisor generation 62 then ran recovery-only,
reported `STOPPED_FLAT`, cleared every recovery reason and disarmed normally;
this live-verifies the repaired terminal `FENCE_ACK` path.

The subsequent normal generation 63 is healthy: parent PID 11100, child PID
42520, runtime `0017eba031044b0e8b02825d416641d5`. At **13:23:56 UTC** it had
**30 resting orders, no reported positions, $118.20 reserved exposure**, a
current account snapshot, current entry authority, all four readers subscribed,
healthy logging with zero drops, and no risk, accounting, control or recovery
hold. Initial ranking released at its 120-second bound with 794/1,024 markets
evaluated across both book shards. Active settled six-hour P&L remains
**-$1.551600**.

This accepts the restart and terminal-fence repair. The accelerated multi-order
drain remains fully tested but has not been timed in another live stop; do not
interrupt the healthy bot solely to manufacture that measurement. Resting
orders and estimated reward do not prove payout or profitability.

## Emergency cancellation complete; shutdown repair verified — 2026-09-23

The operator ordered an immediate force cancellation after the normal drain was
observed taking too long. The exact protected parent/child processes were stopped
and the authenticated account-wide cancel endpoint returned HTTP 204. A fresh
GET-only account check at **12:43:19 UTC** then verified **0 resting orders and
0 nonzero position rows**. The bot remained stopped while this repair was deployed;
the active six-hour settled trading result is **-$1.551600**.

The preceding normal drain did eventually cancel all 30 entries, but needed
about 70 seconds because every individual cancellation triggered a full account
recovery before the next exact owned cancellation. It reached locally verified
`STOPPED_FLAT`, then incorrectly rejected the child's terminal `FENCE_ACK` after
the stop latch and reported a false shutdown timeout.

The repair drains paused entry orders from exact durable owned-order evidence
without an intervening REST recovery per order. It does not apply that shortcut
to reducers or ordinary live management, and every cancellation retains the
existing prepare/send/outcome ledger and transport fences. A stopped child may
now receive only `STOP_HINT` or its exact terminal `FENCE_ACK`; identity,
generation, native binding and live-parent checks remain mandatory. Final
verification: **1,591 tests passed, one expected Windows privilege skip**.

Three earlier runtime repairs now at canonical `origin/master` are also retained:
rejected create HTTP 400 outcomes become terminal instead of ambiguous; reward
reflection iterates a stable snapshot; and public candidate preparation runs
concurrently (measured about 20.4 seconds instead of about 43 seconds). None
changes the configured trading limits.

## Live recovery blocker observed during D-098 verification — 2026-09-23

At **11:37:15 UTC**, the standard read-only supervisor status showed generation
49 in `recovering`, replacement child PID 35364, runtime
`c113f24a47d84b17956897000d95feee`. New entries were paused; recovery was
`blocked_retry_exhausted`, with `ambiguous_send`, no current account proof,
8 reported resting entries and a reported 10-contract YES-equivalent position
in `KXTOKENUSE-26SEP28-T152`. These are local saved observations, not a fresh
venue reconciliation. Do not infer flatness or cancel success.

Control records `unexpected_death`, `cleanup_unconfirmed`, `unresolved_work`.
Retained child diagnostics show repeated incomplete/exhausted recovery through
11:31:54 UTC; they do not establish the original child's death cause. The prior
healthy checkpoint below is historical. D-098 source is isolated and was not
deployed; no assistant process control or venue action occurred. Resolve this
incident before deployment/restart; do not bypass ambiguity or reset the ledger.

## D-098 order-lifecycle bundle prepared in isolation — 2026-09-23

The [actual-code Poly comparison and implementation](docs/BUILD_ORDER_MAINTENANCE.md)
cover entry, incumbent maintenance, fills, cancellations, passive/IOC exits,
loss-cap drainage and restart. Qualifying incumbents stay; reference drift is
repaired in the same program with terminal/fill proof before replacement.
Existing reward estimates are exposed per program, never as paid cash. Three
demonstrated exit/cap defects are included. Risk amounts are unchanged.

Verified in `fix/order-maintenance`: **1,582 tests run, 1,581 passed, one expected
Windows symlink-privilege skip**, 260.851s. Final source includes cap drainage
and cooperative reflection yielding. An intermediate full run exposed an eager
inventory access against an older minimal fixture; short-circuiting an empty
overflow set fixed it, and the final full run passed. Poly's 76 pure reconciler
tests, three deliberate regression reversals and 493 local documentation links
also passed. Actual diff reviewed for source/race/ownership/exit-priority issues.

Publish this reviewed commit to canonical `origin/master` from the isolated
checkout. Keep the live checkout deliberately at clean `221dacc` until controlled
deployment is authorized; isolated HEAD/remote parity is not deployed parity.
No restart or venue action occurred. The live recovery incident above remains
unresolved and prevents a restart-readiness claim.

## Current: D-097 live restart accepted and running — 2026-09-23

Under the operator's explicit restart instruction, the preserved production
ledger was restarted without initialization. Supervisor generation 49 is healthy
with protected parent/child presence; parent PID 22988, child PID 29288, runtime
`fdda4cd9036a43cf90a4cf6c33e65d60`. At **10:43:46 UTC**, the same child held
**30 resting orders across 15 markets**, no reported positions and **$127.60
reserved exposure**. Account entry authority was current, all four readers were
subscribed, and engine/dispatch/logging reported no failure or dropped logs.

The initial ranking checkpoint placed no orders while waiting and released at
its 120-second bound as `timeout_partial` with **801/1,024 evaluated**. Repeated
invocations of the standard supervisor status command overlapped publication as
orders grew from 22 to 30. The same run/PID remained healthy through a further
30-second observation, and no WARNING/ERROR event was recorded from launch
through the acceptance check. This verifies the previously failing status path
under current live operation; it does not guarantee future OS/storage behavior,
fills, payout, profitability or globally optimal market selection.

A subsequent [public-only quality check](docs/VERIFY_CURRENT_MARKET_QUALITY_2026-09-23.md)
found all 15 owned markets still pass current gates, but only four are in the
$2+ priority tier versus 40 available samples. Fourteen owned markets were at or
better than their sampled reference pair; one ask was five ticks worse. The bot
remained healthy at 30 orders/no reported position after the check. Estimates
are sequential and do not authorize automatic repricing or incumbent replacement.

## D-097 implementation and offline verification

D-097 repairs the recurring Windows `status.json` publication failure. Repository
status readers now explicitly allow delete/rename sharing. Atomic writers use a
unique same-directory temporary file and retry only `PermissionError` for at most
two seconds; permanent failure still propagates, preserves the previous whole
document and retains fail-closed runtime handling. A native regression held the
old status open without delete sharing, then proved publication succeeds after
the handle closes. Synthetic permanent denial proves no false success or partial
status. The complete suite passes: **1,557 tests, one expected Windows symlink-
privilege skip**, 249.309s. Focused live-runtime, host-continuity and production-
supervisor suites also pass.

The code fix was subsequently live-restarted and accepted at the timestamped
checkpoint above. The historical stopped-flat state below remains recovery
evidence, not current process state.

## Historical failure evidence before D-097

The restart is **not a sustained live success**. After the checkpoint below,
the normal child failed at **06:09:22 UTC** with `PermissionError` (errno 13)
in `startup.save_result` at `os.replace`. A recovery-only child hit the same
failure at **06:10:53**. Subsequent recovery reached **STOPPED_FLAT at 06:11:55**:
zero resting entries, no positions and zero reserved exposure. The supervisor
disarmed; protected parent/child roles are both absent and recovery holds clear.

The ranking fix remains deployed and verified. The exact external handle that
caused each historical denial remains unidentified; D-097 addresses the observed
Windows sharing mode and transient-denial class without suppressing permanent
I/O failure.

## D-096 historical live checkpoint before the failure

Implementation `bf03b56` is published/deployed. The final authorized normal run
`8e905c9477a34c8484c55ab32be5144d` (parent 46184, child 18516) was running. At
**06:09:15 UTC**, protected parent/child presence, healthy supervisor, current
account release and all four subscribed readers were verified; engine/dispatcher
reported no failure, logging healthy with zero drops. **30 resting orders / 15
two-sided markets, no fills/positions, $126 reserved exposure** at this checkpoint.

No entries were placed during initial waiting. At **120.132s**, the checkpoint
released as `timeout_partial`: **864/1,024 evaluated** (469/549 and 395/475 by
shard). These frozen historical counts are not current coverage or eligibility.
The first acknowledged creates were prepared at 06:07:09 UTC; 30 create ACKs
were recorded by 06:08:37, plus 18 proven-NOT_SENT legs. No cancellation/replace
mutations had occurred at that observation. Later recovery canceled its orders.

Matching the 15 owned markets to sampled pre-entry proposal estimates gives
**7 $2+ and 8 $1–<$2** markets, versus zero $2+ in the previous observed slate.
These are selection-time samples, not guaranteed or paid rewards and not proof
of an optimal full-universe allocation. Expired/source-changed rows remain
excluded; later better candidates do not automatically replace incumbents.

The first deployment attempt stopped before placing orders because atomic status
replacement raised Windows `PermissionError`. Its supervisor recovered flat and
disarmed. Ordinary diagnostic file handles are a plausible interfering reader;
the exact external handle was not identified. After joining those monitors,
a synthetic replacement-with-reader-open check passed using delete-sharing.
The final run was monitored with that nonblocking reader; no production I/O
safety rule or error handling was bypassed. General status-reader hardening is
a follow-up, not implemented in this checkpoint change.

## D-096 verification and controlled shutdown record

[Initial combined ranking](docs/BUILD_INITIAL_RANKING.md) delays normal broad-mode
entries until evaluated coverage or 120 seconds, then uses only current eligible
rankings. The $2-first/$1-fallback rule and all risk/source checks remain; no
incumbent replacement. Both feeds, metadata and safety work continue concurrently.

Verification: **1,554 tests run / 1,553 passed / one expected Windows privilege
skip**, 239.635s, in the isolated checkout's correctly source-pinned environment.
Focused ranking/live suites: 102 pass; native supervisor suite: 12 pass. Reversing
the gate in memory fails the delayed-priority regression as expected. Exact code
review found no blocking defect. Repository-relative documentation links and
whitespace checks pass (four ignored historical data links are absent from the
isolated checkout, not repository links). No secrets/private data are staged.

The updated 1,024-book synthetic benchmark passes: initial coverage/ranking
0.615s, warm rounds 0.310–0.355s, 15 proposed pairs, 1,024 inventory reads, no book
failures; loop/private/due sentinel p99 55.35/56.19/56.15ms. Fixed source clocks
and synthetic sentinels are not live scan or cancellation latency measurements.

Under the operator's explicit restart approval, the old run drained from 30
orders to **STOPPED_FLAT at 05:55:28 UTC**, with no positions/exposure. The drain
exceeded the supervisor timeout, retaining recovery requirements. An ordinary
recovery-only start verified flatness and disarmed cleanly at **05:56:45 UTC**;
no holds were manually cleared. This was the stopped/disarmed predeployment
checkpoint; the subsequent live acceptance above supersedes that process state.

## D-095 controlled live restart running — 2026-09-23

The operator explicitly authorized a controlled live restart. The prelaunch
input check found expired reviewed markets and correctly blocked before trading.
Normal supervised launch previously refreshed public candidates only for a new
ledger; it now runs the same bounded credential-free preparation on every normal
explicit arm. Recovery-only remains narrow. Focused restart/candidate suites:
**39/39 pass**. Complete suite: **1,537 run / 1,536 passed / one expected Windows
privilege skip**, 245.514s. Commit `2522f7a` is published on `origin/master`.

The independent supervisor acknowledged launch at **05:17:31 UTC / 01:17:31
Eastern**, parent PID 30568, child PID 44308, runtime
`e6b52e1b72ff496ab4b5d0eaf3925f46`. By 05:20 UTC it reached the configured
30-resting-order maximum across 15 two-sided markets, reserved **$126.10** and
reported no position. Both book shards plus account/lifecycle readers are
subscribed; engine, dispatcher and logging report healthy/no failure. A 15-second
sample observed fresh account/live-ready authority in 9/15 samples; periodic
reconciliation correctly revoked it in the other six and then restored it.
Existing orders remained at 30. No risk/accounting blockers or recovery holds.

The bot is **running**. Top-level `RUNNING_UNVERIFIED` is the deliberate protected
process-presence label, not a failure or full readiness claim. Continue observing
fills, exits, order turnover, reward estimates and broad-selection coverage.

Live ranking check at 05:28–05:31 UTC: all 15 owned markets remained exactly at
both current reference prices and full reward weight. No cancel/replace mutations
occurred; automatic repricing is disabled. Their current remaining projections
were $1.02–$1.90, so none occupied the configured $2-priority tier. A public-only
96-second census of all 1,024 reviewed markets found 174 $1-pass samples and 30
$2-priority samples, with zero overlap between those 30 and the 15 owned markets.
The census is sequential/hypothetical-flat, not simultaneous account admission.

The code sorts currently evaluated $2 rows first, but live dispatch filled the
30-order cap while broad metadata was still arriving and does not replace an
incumbent fallback with a later higher-tier market. Therefore $2 priority exists
locally in each proposal but is not enforced for the final steady-state slate.
Do not describe the current live allocation as $2-prioritized.

## D-094 host/account blockers repaired; bot stays stopped — 2026-09-23

[Repair and evidence](docs/BUILD_HOST_CONTINUITY.md): the default explicit live
launcher now starts the supervisor independently of its terminal/job, with a
correlated startup receipt. Native inert job-teardown/shutdown acceptance passes.
Status reports current protected-role presence separately from historical data;
it no longer presents saved healthy state as proof that the bot is running.

GET-only evidence at **05:01:38 UTC / 01:01 Eastern** confirmed all 28 outstanding
local orders canceled with zero fills, zero account resting orders and zero
nonzero-position rows. After consistent ledger/control backups, the existing
validator imported those terminal records and cleared the dead child reservation.
All 68 owned orders are terminal; 10 prior intents remain aborted. Financial,
risk and history tables were verified unchanged. Supervisor is disarmed and
stop-latched with no child; current process-role checks report **STOPPED**.
Private evidence/backups remain ignored. No venue mutations or live restart.

Verification: full suite **1,531 run / 1,530 passed / one expected Windows
privilege skip**, 238.277s. After final receipt-cleanup/bounded-status changes,
**66 focused tests run / 65 passed / the same expected skip**, 46.945s, including
all 14 new host regressions and existing production/native/review-fix suites.
Actual diff/security review found no blocking issue; PowerShell parsing and
the missing-`-Live` refusal check pass. Relative documentation links and
`git diff --check` pass. No remaining development blocker in this repair unit.

Next is a **separately authorized** launch with refreshed reviewed inputs and
normal readiness checks, then live acceptance of D-093 market breadth. Dated
flat-account evidence is not current stream continuity or profitability proof.

## Historical D-093 handoff — its two blockers are resolved above

## D-093 broad discovery verified; bot remains stopped — 2026-09-23

[Integration and evidence](docs/BUILD_BROAD_DISCOVERY.md): next normal launch
observes all reviewed candidates (up to 1,024) on two book shards, shares bulk
event metadata and queues only bounded ranked entry work. Account, order, fee,
freshness and economic limits remain unchanged; recovery-only stays narrow.

Public-only acceptance examined 1,013 markets in **90.073s / 570 REST reads**,
versus 415.320s / 2,563 reads previously. **150 passed market gates**, including
28 $2-priority candidates; no source errors. Sequential hypothetical empty-account
observations, not simultaneous admission or earnings. Synthetic 1,024-book
runtime burst/reconnect targets pass. Complete suite: **1,519 run, 1,518 passed,
one expected Windows privilege skip**, 239.829s. Final targeted rerun: **100 pass**,
22.951s, including three additional bulk boundary regressions and final query
validation changes. Actual diff review found no blocking implementation issue;
482 relative documentation links and whitespace checks pass.
Bot remains stopped; no deployment, account calls or production ledger changes.
Host continuity and manual-cancellation reconciliation remain pre-restart work.

## Historical D-092 recommendation — accepted as D-093 above

## D-092 research favors broad WS books plus bulk metadata — 2026-09-23

[Measured alternatives](docs/RESEARCH_DISCOVERY_OPTIONS_2026-09-23.md): two WS
connections delivered all 1,013 reviewed/rewarded books in 0.560s and met the
45-second diagnostic targets (100% sampled freshness, 10.37% one-core CPU,
67.19 MiB sampled RSS). Four bulk event requests supplied all 1,024 reviewed
market definitions and milestone bindings in 2.228s. Sample detail comparisons
matched existing parser outputs. No production code/configuration changed.

This supersedes a presumptive slow rotating scanner recommendation: propose
broad public books and shared bulk metadata instead, subject to approval and
full-runtime verification. Fee-change completeness, production queue budgets,
ranking/account latency and sustained load remain unverified. Bot stays stopped;
host continuity and manual-cancellation reconciliation remain separate blockers.

## Read-only census: 156 passing markets; discovery speed still unresolved — 2026-09-23

[Measured census](docs/VERIFY_MARKET_GATES_2026-09-23.md) examined 1,013 currently
reviewed/rewarded markets in 6m55s: 156 passed market gates, including 32 $2+
priority candidates. Of these, 141 passes (28 priority) were outside the saved
initial seed. These are sequential observations with hypothetical empty-account
capacity, not current account admission or guaranteed rewards. No orders or
production state changed. Five new tests and 53 existing relevant tests pass.

D-091 fixes skipped candidates, but 128 live subscriptions / 16 replacements /
30-second dwell still constrain discovery. Faster decoupled discovery is a
recommendation, not implemented or approved here. Bot remains stopped; account
reconciliation and process-host continuity remain pre-restart work.

## D-091 coverage/refill repair verified offline; bot remains stopped — 2026-09-22

[Coverage repair](docs/BUILD_DISCOVERY_COVERAGE.md) now advances exploration from
actual subscriptions, preserving candidates across partial/deferred joins. The
1,024-market / 14-owner regression covers every candidate in 56 rotations instead
of missing 332. Risk-aware refill uses 30 seconds, with a minimum post-join dwell;
existing reward, ownership, risk and source checks remain unchanged. Timestamped
selection exclusions and dispatch outcomes are retained in bounded status.

Complete suite: **1,492 run, 1,491 passed, one expected Windows privilege skip**
in 234.396 seconds. Six breadth diagnostics and 30/120-market admission resource
checks pass; the old discovery fails the new coverage regression. Actual diff
review found no blocking issue in this repair. No venue calls, production ledger
changes or live restart occurred. No profitability or current eligible count is
claimed. Host continuity/liveness and manual-cancellation reconciliation remain
separate pre-restart work; historical saved status is not current account proof.

## Historical diagnosis — superseded by D-091 offline repair above

The final supervisor/child are absent; runtime status froze at 23:22:32 Eastern.
The operator reports manually canceling all orders. Current venue flatness has
not been independently checked. No restart or production mutation was performed
during this investigation. Historical `healthy` snapshots below are not current.

[Investigation](docs/INVESTIGATION_LIVE_EXIT_2026-09-22.md) now prioritizes market
coverage. Live watches 128 of 1,024 reviewed candidates; two completed rotations
could cover at most 160 distinct markets. Discovery advances beyond candidates
that its partial admission consumer has not subscribed. The composed frozen-input
reproduction permanently misses 332/1,024 candidates with 14 protected markets.
Fix coverage/refill and retain exclusion reasons first; no production fix yet.

The precise historical 28-order blocker and process termination trigger remain
unknown. Selector/writer fixtures permit 30 orders. Six breadth diagnostics,
47 selector tests and one native parent-death test pass; diagnostic success
includes reproducing the coverage bug, not fixing it. Hosting/liveness remains
a separate pre-restart concern. The earlier 5,060 count was the reward catalog,
not a measured lifecycle snapshot.

## Historical D-090 observation — superseded by process-loss finding above

D-089 was published and deployed. The two retained proof-before-transport
cancels were corrected only after exact ledger/log matching and backup; a
recovery-only run then proved `STOPPED_FLAT`. The authorized normal restart
reached live operation and placed 14 entry orders with no positions.

Live evidence then exposed a separate deterministic limit mismatch: Kalshi's
unscoped `market_lifecycle_v2` subscription delivered about 5,018 initial rows,
while every per-stream transport had been overridden to 256 queued events. The
lifecycle reader overflowed at `transport._receive`, repeatedly reconnected and
paused new entries. Controlled stop canceled 7/14 orders in the first five
seconds and all 14 within the next observed eight-second interval; final saved
state is `STOPPED_FLAT`, zero positions and zero exposure. The parent classified
the reconnecting child's exit as `unknown_failure`, but cleanup/account proof is
complete and no live process remains.

[D-090](docs/BUILD_LIFECYCLE_SNAPSHOT_BUFFER.md) keeps account and scoped-book
queues at 256 events / 2 MiB and raises only lifecycle to the transport's bounded
8,192 events / 16 MiB defaults. Targeted verification passes 127 tests. The
complete suite passes **1,482 tests with one expected Windows privilege skip**.
Commit `afff8f5` is published with local/remote parity. Recovery-only clearance
completed in 26 seconds, then the normal child subscribed lifecycle on attempt
one and ingested 5,060 markets without overflow. The latest acceptance snapshot
is healthy/live-ready with all readers subscribed, current account evidence,
28 resting orders (14 markets), zero positions, $121.20 exposure and zero
dropped logs. The supervisor remains active; no restart was performed after
acceptance.

## Pre-transport cancellation fix verified; exact live recovery pending — 2026-09-22

D-088 successfully continued the recovery drain beyond three progress-making
passes, reducing the saved live state from nine to two resting orders with no
positions. The final two are each blocked by an `UNKNOWN` cancel row. Their
creation timestamps exactly match the only two retained `mutation_unknown`
events whose stacks end at the old `proof_changed_before_submission` branch;
no transport invocation is recorded. No bot process is currently active. The
supervisor control record is stale, stop-latched and saved-snapshot-only.

[D-089](docs/BUILD_PRETRANSPORT_ABORT.md) now records such future proof failures
as transactional `NOT_SENT`/`ABORTED` before transport, with sole-executor
ownership, all-or-none batch behavior, capacity release and recovery signaling.
Real post-invocation uncertainty remains `UNKNOWN`. Focused verification passes;
the complete suite passes **1,481 tests with one expected Windows privilege
skip**. Publication, controlled deployment, exact backed-up correction of only
the two retained pre-transport rows, recovery-only flatness and then the already
authorized normal restart remain pending.

## Graceful-drain defect fixed offline; live recovery pending — 2026-09-22

The authorized stop exposed D-088: acknowledged safety cancellations were
incorrectly consuming the same three-attempt budget as no-progress recovery
failures. Saved state fell from 14 to 9 resting entries with no positions, then
the recovery child stayed `DRAINING` and the parent reported `shutdown_timeout`.
The child later exited before the authorized targeted force-stop executed; no
force-kill occurred. No process is currently trusted to manage the nine saved
resting entries, so normal quoting must not start before recovery-only flatness.

The isolated fix preserves fresh proof after every cancel and renews the bounded
failure budget only after measured reconciliation progress. Its exact reversal
fails as expected. The focused recovery/live/supervisor set passes 156 tests;
the final suite passes **1,479 run, 1,478 passed, one expected Windows privilege
skip**. Publication, deployment and recovery-only restart are pending.

## D-087 lifecycle recovery and reference audit complete; deployment pending — 2026-09-22

The exact old lifecycle transport error is unavailable after bounded-log
rotation. A standalone read-only subscription now succeeds, proving the current
channel/entitlement. [D-087](docs/BUILD_LIFECYCLE_RECONNECT.md) repairs the actual
recoverability defect: only lifecycle continues after three-attempt rounds, on
capped backoff with source revocation and monotonic generations. Account/book
semantics remain unchanged. The focused lifecycle/runtime/source set passes 161
tests. The final complete suite passes: **1,478 run, 1,477 passed, one expected
Windows privilege skip**.

The requested [reference-price audit](docs/VERIFY_REWARD_SOURCE_LIVE.md) also
passed. The book subscription explicitly requests `use_yes_price=true`, so NO
levels already arrive in YES-price coordinates. A fresh read-only run checked
128 rewarded books/programs with zero ladder/reference mismatches; 246 sides had
enough one-fifth depth. The scorer therefore places its initial hypothetical
quotes at the current reference levels when both sides satisfy the full-depth
gate. This is not a reward, fill or economic-profit guarantee.

The active PID 46576 is unchanged at the time of diagnosis: 14 resting entries,
zero positions, lifecycle/catalog exhausted. No process, order, ledger, hold or
configuration was modified. Publication and then controlled deployment/restart
are still pending.

## Read-only live source comparison passed before deployment — 2026-09-22

At 21:19 Eastern, the [30-second source probe](docs/VERIFY_REWARD_SOURCE_LIVE.md)
retrieved 5,006 programs in six public requests and validated 128 rewarded seed
books. After warmup, fresh books averaged 4.81 under the no-refresh timestamp
baseline versus 128 with snapshots on the same feed; final counts were 2/128.
All readers joined; no orders/private REST/trader restart. This verifies source
coverage, not full economic eligibility or production occupancy. Nineteen
targeted tests pass; code/docs are retained on the isolated fix branch.

At 21:20:31 the unchanged production PID 46576 still reported 14 resting entries,
zero positions, catalog exhaustion and a separate lifecycle retry-exhaustion
hold. Full economic-filter verification and lifecycle diagnosis remain before
claiming readiness. Canonical deployment still awaits explicit authority.

## D-086 source repairs verified; deployment pending — 2026-09-22

The [catalog and quiet-book fixes](docs/BUILD_REWARD_SOURCE_REFRESH.md) are in
`fix/reward-source-refresh` at `C:/Users/rynna/Bots/kalshi-reward-source-fix`.
Final full suite: **1,471 run, 1,470 passed, one expected Windows privilege skip**,
227.536 seconds. Both catalog and snapshot-controller resource checks, five
breadth probes and three targeted in-memory reversals pass. Exact code review
found no blocking defect; documentation links/whitespace/secret-pattern checks
pass. Trading limits, economic filters and five-second freshness remain.
The canonical live checkout/process/ledger have not been changed. A controlled
deployment needs separate authority because changing the package while the old
supervisor runs can invalidate its recovery-child fingerprint. Timestamped live
observations below are historical, not a fresh health or order-count report.
This verified unit is retained on the isolated branch; defer the normal D-065
canonical merge until controlled deployment is approved, preserving the current
supervisor's source fingerprint. Live performance/occupancy remains unverified.

## Historical reward API re-audit; before D-086 — 2026-09-22

[Fresh audit](docs/REWARD_API_REAUDIT_2026-09-22.md): our current 100-row incentive
pages underuse the documented maximum of 10,000. A separate public-only read
with 1,000-row pages retrieved 4,981 programs in five requests / 1.986 seconds.
Documented WS `get_snapshot` can refresh quiet books without reconnecting and is
not yet wired into our reader. No replacement personal-reward API was found.
These findings narrow the proposed repair; no live code, filter, retry hold or
process was changed. The live observation below remains timestamped history.

## Breadth diagnosis: 14 orders; fresh reward catalog unavailable — 2026-09-22

At 20:30:30 Eastern the existing child 46576 remained healthy/account-current,
with 14 resting entries, zero positions and no accounting/risk blockers. The
incentive catalog had expired and refresh exhausted three timeout attempts:
`current_markets=0`, `exhausted=true`. This blocks new reward selection; healthy
process status is not full functional readiness. Do not clear the hold or restart
solely to reset its retry budget.

Five offline probes reproduce catalog timeout/exhaustion, five-second quiet-book
rejection, the 128-market live working set, 16-market/300-second rotation and
successful 30-order ranking with sufficient fresh candidates. All five plus 136
existing focused tests pass. These are diagnosis results, not fixes. See
[FINDINGS section 125](FINDINGS.md) for evidence and its limits. No live mutation,
restart or runtime-code change was performed during this diagnostic task.

## Live recovery completed; admission rotation observed — 2026-09-22

The first live quoting generation reached 12 resting orders across six markets,
not because only six markets passed the reviewed reward gates, but because market
admission could not acquire an idle metadata handoff. Two metadata workers
immediately refilled their slots, while admission required all workers and
dependency reads to be idle before replacing subscription scope. Admission
therefore completed zero rotations despite 1,024 reviewed candidates.

The scheduler now supports one exact, five-second admission reservation. Existing
metadata work drains, no new worker starts during the reservation, and the same
fresh account, inventory, timing, capacity and candidate proofs still precede a
scope commit. Abandoned reservations expire and ordinary per-shard safety
deferrals remain independent. The full offline suite ran 1,453 tests in
223.737 seconds: 1,452 passed and one expected Windows privilege skip.

The earlier recovery generations reduced the prior orders to two, then one
pre-transport cancel refusal remained UNKNOWN. D-085 authorized an exact,
backed-up, transactional correction to NOT_SENT with its authorization ABORTED.
Generation 25 then canceled the final two orders and exited `STOPPED_FLAT` at
20:17:22 Eastern, with current account proof, zero positions and no holds.
The same ledger, opening baseline, risk counters and limits were preserved.

The normal supervised run started at 20:17:44 Eastern (host PID 44608, child
46576). At 20:23:48 its local saved status was RUNNING/healthy, with 10 resting
entries, no positions, no accounting blockers and two completed admission
rotations. Account-current/no-risk-blocker evidence was also observed at
20:21:00. These are timestamped observations, not promises
of continuing liveness. Broader order occupancy and profitability remain
unverified. See FINDINGS section 124 for retained operational evidence.

## First live opening failed closed; exact recovery correction verified — 2026-09-22

The explicitly authorized supervised `-Live -Initialize` launch created the
single production ledger and contacted the account, but placed no orders and
held zero exposure. Fresh evidence showed no positions or resting orders. The
opening checkpoint retained one earlier applied $500 personal deposit and one
completed pre-boundary $0.4417 intra-exchange transfer; because their APIs omit
completion timestamps, the prior generic policy left
`cash_activity_unattributed` and the writer failed closed. The supervisor made
only its bounded recovery attempts, then latched `attention_required` with no
live child.

D-084 now allows the explicit opening approval to bind only completed,
pre-boundary personal cash rows by exact event digest. Pending, withdrawal,
subaccount, post-boundary, changed-cash and settlement cases still fail closed.
The same unit repairs interrupted initialization: a fresh matching inspection
may approve the existing immutable checkpoint without deleting the ledger or
choosing a new boundary. Focused accounting, recovery, live-runtime and
production-supervisor suites pass. The full offline suite ran 1,444 tests in
220.622 seconds: 1,443 passed and one expected Windows privilege skip. The
corrected supervised relaunch is the remaining acceptance step.
[Implementation](docs/BUILD_FIRST_LIVE_OPENING_RECOVERY.md).

The first corrected re-arm exposed a separate local-control refusal before any
child or venue connection: SQLite had recreated the supervisor WAL/SHM with the
protected parent's exact user/System grants marked inherited. The sidecar guard
now accepts only that semantically identical inherited representation while the
root/database remain explicit and protected. Native and full-suite verification
now pass: 61 focused/native supervisor tests passed with one expected privilege
skip, and the complete suite ran 1,445 tests in 218.331 seconds with 1,444
passed and one expected skip. The next step is publication, then re-arm.

Generation 3 then resumed the exact checkpoint, approved the baseline with two
attributed cash-event digests, observed a current flat account and disarmed with
zero orders/exposure. A shutdown race was still visible: opening approval had
queued its required post-approval reconciliation, but the flat fence stopped
between passes; cancellation persisted `accounting_source_failed` alongside
`opening_proof_unresolved`. The flat fence now waits for queued/in-flight
recovery before terminal flatness. Another verified recovery-only pass must
transactionally clear those transient holds before normal quoting. The focused
75-test set passed, followed by the complete 1,446-test suite in 219.163 seconds:
1,445 passed and one expected Windows privilege skip.

## Final current-path findings repaired; final acceptance remains — 2026-09-22

The four findings in the
[current-path review](docs/REVIEW_CURRENT_LIVE_PATH_2026-09-22.md) are repaired.
The $25 hard loss hold drains owned entries; reward/program authority survives
to both final send fences; exact cancellation no longer requires current book or
terms; and overlapping programs are qualified/tiered before one-per-market
selection. Permanent regressions and related suites pass, as do the 30/120
selection, admission and dispatch performance gates. No trading process,
credential exposure/mutation, production ledger or order endpoint was used. The
GET-only startup used the configured account credentials for read-only account
verification. Final suite: 1,441 tests in
218.486 seconds, 1,440 passed and one expected Windows privilege skip. The
1,024-candidate input parses; a 45-second GET-only startup verified the account,
book/lifecycle, quota, logging and incentive feed graph and stopped cleanly with
no dispatch. First supervised live acceptance remains separate.
[Implementation](docs/BUILD_CURRENT_PATH_REPAIRS.md).

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
