# Active work queue

## D-126 recovery renewal and logging

1. Generation 166 is running on published release `1777e41`; do not restart
   merely to prove the deployment again.
2. Monitor sustained full-recovery reasons, routine renewal escalation count,
   order occupancy, reward coverage, quota deferrals and public-book proof churn.
   Initial live and offline regression success do not establish indefinite
   improvement or guaranteed 30-order occupancy.
3. Actual Kalshi reward credits still need independent verification; UNKNOWN
   tracking intervals must not be reconstructed as earned rewards.

## D-125 command-capacity archive repair

1. D-125 is verified, published and deployed; generation 164 created one real
   archive and rebuilt up to 28 orders with zero positions. Do not restart merely
   to prove it again.
2. Monitor sustained occupancy and residual `book_queue_pending` /
   `book_revision_changed` proof churn separately. Do not treat a momentary
   26–28 count as a changed cap, guaranteed eligibility or profitability.
3. Keep ACK/rejected/unknown and all financial evidence hot; archive only exact
   `NOT_SENT` creates from retired episodes.

## D-124 replacement refill repair

1. D-124 is verified and deployed with D-125. Initial live diagnostics separate
   queued/changed book proof from the removed redundant risk-read windows.
2. Continue any residual occupancy investigation under D-125 item 2; do not
   equate synthetic refill or a momentary live count with guaranteed occupancy.

## D-123 stopped-bot repair

1. D-123 is verified, published and deployed; generation 160 is running and
   rebuilding orders. Do not restart simply to prove the operation again.
2. At subsequent checks, verify live safety-action recovery, occupancy/refill,
   quota health and any native exit codes. Use `runtime.logging.run_id` for
   logs, not the separate live-session ID. Offline regressions are not evidence
   of a new real fill/exit cycle or indefinite uptime.
3. Preserve separate unfinished Command 1 work; no unrelated feature merge.

Earlier queues below are historical.

## After Command 1 on D-121/D-122

1. Generation 158 is running on `d4e888b`; do not restart merely to prove it.
   Monitor live quota-refresh survival, withdrawal decision-to-ACK latency,
   occupancy/refill and reward-quality evidence without assuming profitability.
2. The permanent D-116 Command 1 implementation remains unfinished. Replace the
   one-time stopped reconciliation path with a bounded supported command that
   cancels, reconciles exact terminal/fill evidence, flattens inventory when
   authorized, restarts, and reports each stage without repeated broad scans.
3. Preserve the separate unfinished command-1 worktree until that scoped build
   is explicitly resumed; do not merge it merely because this operation worked.

Earlier queues below are historical and do not authorize repeat operations.

## D-122 quota-refresh failure

1. D-121 plus D-122 are verified, published and deployed at code `5d34d0e`.
   The 1,771-test full gate and 47 canonical post-deployment tests pass; see STATUS.
   Keep the bot stopped. Do not repeat deployment or infer restart permission.
2. At a separately authorized restart, let normal recovery reconcile the external
   cancellations. Measure quota-refresh survival, decision-to-cancel latency and
   ranked refill; offline tests are not live proof.
3. Preserve the separate unfinished command-1 worktree.

Earlier queues below are historical and do not authorize repeat operations.

## D-121 startup/recovery/refill repair

1. D-121 implementation, review and clean full verification are finished; see
   STATUS for the 1,759-test gate and Finding 184 for reproductions. Do not
   equate synthetic timing with live acceptance.
2. At the next explicitly authorized restart, deploy the verified release
   through the supported owner path; measure initial-fill time, public 429s,
   decision-to-cancel latency, recovery attempts and ranked refill. Keep the
   canonical live source pinned until then; no new restart is requested here.
3. Preserve the separate unfinished command-1 worktree.

Earlier queues below are historical and do not authorize repeat operations.

## D-120 fill-risk withdrawal

1. D-120 implementation, review and focused/fast/full verification are finished,
   and published release `3e0a346` is deployed on generation 152. Do not repeat
   the restart merely to prove deployment.
2. Continue measuring withdrawal latency and fills during cancellation,
   cooldown/refill behavior and reward time lost. Do not label estimates as
   calibrated probabilities or assume larger target means more actual queue.
3. Preserve the separate unfinished command-1 worktree.

## D-119 refill pipeline

1. D-119 implementation, review and focused/fast/full verification are finished.
   Keep the live canonical checkout pinned. At a separately authorized restart,
   deploy the verified release and measure live refill, blocker attribution,
   renewal and recovery. Do not equate synthetic 30-order success with guaranteed
   live eligibility or profits.
2. Preserve the separate unfinished command-1 worktree; it is not this release.

Earlier queues and source/deployment snapshots below are historical.

## After Command 1 / D-118 deployment

1. D-118 is deployed on generation 148. Do not repeat the restart. Measure live
   refill and remaining source-driven deferrals; eight initial orders and full
   historical ranking coverage do not establish full 30-order occupancy.
2. Preserve the separate `data/command1-dev` worktree. Its automatic emergency
   liquidation still needs its own verification/integration; this operation
   canceled entries with inventory already flat and does not validate that path.

Older deployment instructions below are historical, not repeat actions.

## D-118 source release — current queue

1. D-118 implementation, review and focused/fast/full verification are finished.
   Keep the running canonical checkout pinned. At a separately authorized
   restart, deploy the verified release and measure actual refill, metadata
   work and dispatch deferrals. Do not promise all 30 slots or guaranteed reward.
2. The queried position closed under its existing timed policy; do not send a
   competing close. Read Finding 180 rather than acting on older position data.
3. Preserve the separate unfinished command-1 worktree and its own verification
   requirement. It is not included in this release.

Older queue entries below are historical; the source-release status is in STATUS.

## After Command 1 / D-117 deployment

1. D-117 is deployed on generation 146; do not repeat this restart. Verify actual
   refill and market-local maintenance behavior from current telemetry, without
   claiming every historical ranked market is currently executable.
2. Investigate the old generation's post-prepare `QuotaUnavailable` shutdown:
   distinguish temporary revoked quota from fatal integrity errors and preserve
   prepared-command abort/ambiguity semantics. No bypass or automatic retry of
   uncertain sends. Evidence is in STATUS; this is not fixed by D-117.
3. Command-1 software remains isolated in `data/command1-dev`; finish its own
   corrected-environment verification/review before integration. The operator's
   latest operation needed no flattening because the venue was already flat.

Earlier publication/deployment tasks below are historical, not repeat actions.

## D-117 release handoff — market-local repricing admission

1. D-117 implementation/review and full release verification are finished;
   evidence and source location are in STATUS. Publish the reviewed commit from
   that isolated checkout; do not hot-update the active package or restart merely
   to prove synthetic tests.
2. At the next explicitly authorized restart, safely stop the exact current
   owner, then fast-forward the clean canonical checkout to the published
   master. Verify source identity before the supported start and measure actual
   refill. Do not promise 30 orders or assume every historical rank is current.
3. Keep command-1 changes in their separate `data/command1-dev` worktree. They
   are not included in D-117 and still need their own verification/integration.

The older active queue below is retained as background, not a competing task.

## Active now — trading runs independently of command-1 development

1. Manual-close accounting and supported restart are finished on `40b69f0`;
   do not repeat that reconciliation. Generation 144 is trading; see STATUS.
2. Finish isolated `data/command1-dev` verification/review. Inspect the full
   suite's results and rerun native tests with its own `.venv`, not canonical
   Python plus PYTHONPATH (children deliberately sanitize that variable).
   Then publish the reviewed command changes. Do not claim the current child
   supports the command until a separately coordinated deployment loads it.
3. Preserve live trading; no additional live restart merely to manufacture a
   test. Command 1 is explicit immediate liquidation, not ordinary stop policy.
4. Track remaining source-driven refill deferrals separately; do not label
   20/22 orders a verified 30-order refill or guarantee $2 actual payout.

## Historical handoff — superseded by the active queue above

## Finish the entry/advisory race repair

1. Finding 177 passed the full 1,702-test gate and is published as `c9dce41`.
   Generation 141 canceled all entries and was exactly terminated under D-112.
   Await the operator's manual-close confirmation, reconcile its real fills/fees
   and any remaining exit, then verify flat. Do not send a competing close.
2. After verified flat shutdown, finish the authorized normal restart and
   measure ranked refill without the reproduced advisory race. Record actual
   durations and ownership/account/logging state, not just process start.
3. Record remaining environment-exit uncertainty separately; no persistent
   service, startup entry, machine setting or broad process termination is approved.
4. Operator requested a simpler emergency close-all/restart path. Define explicit
   flattening distinct from normal restart, through the current owner and exact
   reduce-only exits. Do not change the ordinary stop policy implicitly.

## Earlier deployed stop/recovery latency repair

1. Finding 176's integrated drain/recovery correction is verified, published and
   running on generation 139. Do not repeat its completed release tests/restart.
2. Profile remaining cold-scan/refill latency: broad ranking took 152.8 seconds,
   while fresh-source entry deferrals still slowed growth to 12 orders in the
   observed window. Separate changed-book/metadata evidence from writer delay;
   do not widen freshness gates or infer that every remembered market is current.
   Full 30-order refill is not yet verified. Current details belong in STATUS.
3. No extra restart is required solely to manufacture a cancellation test.
   Check live stop-to-cancel and stop-to-exit timing at the next requested stop.

## Historical queues — superseded by the priority above

### Earlier D-113 deployment checklist

1. The D-113 source repair and final release verification/review are finished.
   The operator approved implementation; this turn does not authorize restart.
   On a separately authorized supported restart, confirm the new child/build
   uses routine refresh before full occupancy, discovery progresses during
   recovery, and fresh ranked orders refill without recurrent timer-only full
   recovery. Preserve the exact-child, flat-recovery and single-writer rules.
2. Measure renewal phase timings, full-recovery trigger/duration, candidate
   freshness and order growth. A passing synthetic test is not a promised live
   latency or proof of 30 economically eligible orders. Investigate any remaining
   measured bottleneck rather than increasing freshness windows or book shards.
3. Continue measuring actual rewards, fees and settled trading loss separately.

The semantic ranking and subsequent priority-revalidation changes are already
published through `6db4d6e` and generation 131 is running. Do not execute old
generation-specific restart instructions below as current authorization.

## After semantic reward-catalog ranking identity repair

1. Publish the verified catalog-content identity repair, then finish the
   operator's authorized restart. Generation 125 is flat with zero orders;
   never start a second child beside it.
2. Verify the new normal child preserves coverage across an unchanged periodic
   catalog refresh, reaches 1,024/1,024 current ranking, and refills through the
   existing $2-priority/$1-fallback policy without bypassing source checks.
3. Require current account proof, zero positions, all six readers, healthy
   logging/dispatch and no persistent recovery or supervisor hold at acceptance.
4. Continue measuring actual paid rewards, fees and settled trading loss;
   semantic catalog identity changes startup continuity, not profitability.

## After incremental accounting-release proof repair — current priority

1. Publish the verified chained-receipt repair, then finish the operator's
   authorized supported restart. Generation 119 is recovery-only, flat and has
   no resting orders; never start a second child beside it.
2. Require recovery-only to release accounting within the existing 20-second
   whole-pass bound, prove current zero orders/positions, and stop flat. The
   armed supervisor may then launch one fresh normal child under D-110.
3. Verify the normal child reaches complete four-shard ranking, ordinary ranked
   refill and current reference/reward maintenance with all readers and logging
   healthy. Neither process exit nor order count alone is acceptance.
4. Measure full-recovery duration and chained receipt count after deployment.
   The repair overlaps the short elapsed-tail read with the final account
   snapshot only during full accounting recovery; steady refresh is unchanged.

## After generation 116 reducer-drain deployment

1. Leave generation 116 under its supervisor and monitor natural fills, passive
   reducer aging, cancel-before-IOC handoff, reference-price maintenance and
   vacancy refill. Do not restart merely to manufacture another incident.
2. Compare actual paid rewards with fees and settled trading loss. Fourteen of
   the 15 current markets entered through the $2+ projected tier; the remaining
   allowed fallback projected about $1.47, but neither projection is payout.
3. Measure the 1,024-market startup duration and catalog-reset count on later
   restarts. This run remained fail-closed and completed after two resets; only a
   persistent measured failure warrants changing the coverage policy.
4. D-112 lets an explicit future `restart` instruction cover exact-child
   termination after a supported-stop timeout, but all identity, recovery,
   flat-state and single-process checks remain mandatory.

## After exact closed-settlement reconciliation repair

1. Keep generation 111 and its 28 existing orders unchanged until the operator
   separately authorizes a supported deployment/restart. Do not manually delete
   the settlement hold or edit the production ledger.
2. On that restart, require recovery to reproduce the exact two-fill settlement
   proof, clear only `settlement_reconciliation_required`, and obtain current
   account/history evidence before a fresh normal child may refill.
3. Verify zero positions, no settlement conflict, the expected existing-order
   cleanup/recovery result, all readers, healthy logging, and ordinary ranked
   refill. Any changed venue settlement economics must remain blocked.
4. Continue comparing actual paid rewards with trading loss and fees; this
   accounting repair does not establish profitability.

## After generation 111 D-111 live acceptance — current priority

1. Leave generation 111 under its supervisor and monitor natural fills, exits,
   reference-price maintenance and vacancy refill. Do not restart merely to
   manufacture more acceptance evidence.
2. Compare actual paid rewards with trading loss and fees. The 15 current markets
   passed the $2+ projected-reward priority tier, but projections are not payout.
3. Investigate only persistent measured failures. The startup 429 retries and
   temporary incomplete-recovery warnings cleared with zero exhausted rounds.
4. Continue measuring hot-journal/archive growth and long-duration recovery;
   this successful incident proves the exact funding path, not every outage.

## After generation 108 D-110 live acceptance — current priority

1. Leave generation 108 under its current supervisor and monitor natural
   disconnect, fill, exit and vacancy behavior. A normal stable run does not by
   itself prove the unexpected-death recovery path.
2. Measure paid rewards against trading loss and fees; all 15 current markets
   entered through the $2+ projected-reward tier, but projections are not payout.
3. Measure hot-journal/current-archive growth. The immediate journal cap and the
   future exact-archive ceiling are repaired, but the cumulative rollover has not
   yet been exercised by live data.
4. Investigate only persistent measured failures. The ten startup HTTP 429
   retries recovered normally and no reader or recovery retry round remains.

## After generation 106 D-109 live acceptance

1. Leave generation 106 under its current supervisor and monitor natural fills,
   exact exits, reference-price maintenance, paid rewards, fees and settled
   trading loss. Do not infer profitability from projected reward.
2. Measure hot-event and compressed-archive growth over a longer stable window.
   The immediate 64 MiB hot-journal failure is repaired, but the exact archive
   count is deliberately finite. Design a leaner normalized/hash-only account
   proof format before archive capacity becomes operationally relevant; do not
   delete economic, conflict, fill or settlement evidence.
3. Investigate only if the handled startup 429 burst or post-mutation full
   recovery cadence persists under a stable unchanged 30-order slate. Preserve
   current source, ownership and entry gates while measuring.
4. The separate broad-discovery p99 loop-lag timing gate remains open at
   117–121 ms versus 100 ms. It did not block the 1,024/1,024 live ranking or
   current order slate.

## After generation 102 steady-state repair

1. Generation 102 is live but account-blocked with 30 resting orders. A
   supported restart/deployment requires separate operator authorization; do not
   clear the database hold, cancel orders or replace the child ad hoc.
2. On an authorized restart, require the normal recovery path to archive the
   superseded journal evidence, clear only the capacity hold through a successful
   exact release, and report current account proof before any new entry.
3. Measure full-recovery cadence, REST spend, process CPU, steady-refresh
   counters and reward observed/unknown seconds over 30–60 stable seconds. Verify
   a synthetic or natural vacancy/fill immediately escalates to full recovery.
4. The broad-discovery functional checks pass, but two runs missed its 100 ms
   p99 loop-lag threshold at 117–121 ms. Investigate that separate timing gate
   before claiming broad-discovery performance acceptance; it does not invalidate
   the exact full-cap benchmark or the 1,657-test functional release gate.

## After generation 97 log audit

1. Keep the bot stopped until a separate supported restart is authorized. On
   the next restart, require recovery-only clean disarm before normal launch if
   the historical attention state demands it.
2. In the next normal generation, remeasure observed versus unknown reward
   seconds over a stable 30–60 second 30-order window. Verify clean supervisor
   terminal handling when the next operational stop occurs. Estimates still do
   not prove venue payout or profitability.

## After one-sided incumbent repair

1. Publish the reviewed repair, then use the authorized supported stop/restart
   path; verify flat terminal shutdown before starting the new generation.
2. Verify the new generation reports the 96 MiB child-log bound, current account
   evidence, all six readers, healthy dispatch, and no persistent uneconomic
   orphan after its 90-second evidence dwell.
3. Continue measuring actual reward, trading loss and fees. Do not infer payout
   or profitability from projected reward or maintenance status.

## After reward telemetry repair

1. Deployment/restart is a separate operator decision. Generation 92 still runs
   the previous source; do not interrupt it merely to manufacture acceptance.
2. After a separately authorized restart, verify the reported 96 MiB child-log
   bound and measure reward observed/unknown seconds over a representative
   stable-order window. Do not infer improvement from offline tests alone.
3. Continue checking natural exits and actual venue payout under unchanged
   strategy and limits. Compare paid reward with trading loss and fees before
   treating projected reward as profit. See [findings 163–164](FINDINGS.md).

## After generation 92 restart

1. Leave the current process under its supervisor and monitor natural fills,
   exact exits, maintained reference-price eligibility and actual paid rewards.
2. Compare realized reward with trading loss and fees before changing strategy
   or treating projected reward as profit.
3. Investigate measured failures only. Do not weaken full-coverage/current-proof
   gates merely to shorten the observed two-to-three-minute startup.

## D-106 reviewed priority revalidation

The verified [priority-admission repair](docs/INVESTIGATION_PRIORITY_ADMISSION_2026-09-23.md),
including its final review corrections, is published at `f6b9e3f`. Keep
generation 76 and its current incumbents untouched. Deployment/restart remains a
separate operator decision. If later deployed, measure priority-refresh latency,
batch progression, admitted-tier evidence and quota load before considering any
REST-concurrency change.


## After D-104 live acceptance — generation 76 running

1. Monitor natural fills, exact exits, incumbent reference maintenance, reward
   progress and source-known time. Do not induce fills or churn for acceptance.
2. Reconcile actual venue payout and net trading result before changing market
   strategy or treating projected reward as income.
3. Preserve the ledger and current limits. Investigate measured live failures
   before adding architecture or relaxing freshness/economic gates.

## D-103 prepared; restart remains a separate decision

1. D-103 review, complete verification, commit and push are complete at
   `4f5f902`.
2. The operator subsequently authorized restart. Reconfirm current stopped/flat
   account and supervisor state, then deploy the reviewed
   commit with the preserved ledger and limits, then verify four book readers,
   ranking state, exact passive/IOC exit behavior and current account state.
3. After a separately authorized live run, observe actual $2 candidate/order
   composition, natural-vacancy fallback behavior, fills, exits and payout.
   Synthetic ranking and projected reward do not prove paid reward or profit.

## Priority after verified flatness

Completed by D-103; retained below as the incident-derived checklist.

1. Fix the exercised exit/recovery failure before another trading restart:
   passive `reduce_only` GTC received HTTP 400, recovery exhausted, and the due
   15-minute IOC did not dispatch until a recovery-only replacement started.
   Preserve exact ledger/account proof and reproduce both mechanisms in tests.
2. Build an order-disabled initial-ranking probe comparing two versus four book
   shards and shorter checkpoints. Require a reason for every market and repeated
   1,024/1,024 coverage. The existing probe proved fast initial snapshots but
   inadequate five-second freshness at 512 on two shards.
3. Once source coverage is proven, require the 15 available market slots to use
   $2 candidates whenever at least 15 simultaneously pass every gate. Keep $1
   only as fallback; define controlled fallback upgrades without blind churn.
4. Review/test/commit/push each unit. Keep production stopped until the exit
   failure is fixed and a separate restart instruction is given.

## After D-101 live acceptance — generation 68 running

The [verified/reviewed repair](docs/BUILD_REPRICING_SOURCE_JOIN.md) is deployed.
Two real same-market reference repairs completed and the bot returned to its
30-order cap without a fill or position.

1. Monitor natural fills, exits, further reference repairs, reward-source
   coverage and actual payout. Do not induce a fill or source failure solely for
   acceptance; estimates are not paid reward or profit.
2. Measure the repaired post-drain reconciliation on the next operationally
   necessary stop. Do not stop the healthy bot merely to manufacture evidence.
3. Preserve the production ledger and current limits. Investigate measured live
   failures before adding architecture or relaxing freshness/economic gates.

## After D-100 live acceptance — 2026-09-23

The reviewed [maintenance reliability repair](docs/BUILD_LIVE_MAINTENANCE_RELIABILITY.md)
is published, deployed and running in generation 66. History archival and the
account/reflection join are live-verified; current process and account evidence
belong in STATUS.

1. Monitor actual fills, inventory exits, reference-drift maintenance, reducer
   rejection backoff and reward progress. Do not induce a fill, rejection or
   source outage solely for acceptance.
2. Measure the next operationally necessary controlled drain. Do not stop the
   healthy bot only to manufacture a timing result.
3. Preserve the current ledger and configured limits. Estimated rewards remain
   advisory; reconcile actual payout and trading result before changing strategy.

## After D-099 live acceptance — 2026-09-23

1. Monitor generation 63 for fills, positions, exits, same-market maintenance,
   current reward reflection and any supervisor recovery. Estimated reward is
   not paid reward or profit.
2. On the next operationally necessary controlled stop, measure the accelerated
   30-order drain and verify a normal `STOPPED_FLAT` terminal result. Do not stop
   the healthy bot solely to manufacture this measurement.
3. Preserve the current ledger and configured limits. Investigate measured live
   failures before adding more architecture or relaxing any gate.

## D-098 next restart bundle

0. Resolve the newly observed live recovery incident in STATUS: ambiguous send,
   exhausted reconciliation and reported inventory. Establish exact order/fill
   state and original failure evidence before any deployment/restart. No ledger
   reset, blind resend or assumed flatness; live actions need operator authority.

The [order-maintenance bundle](docs/BUILD_ORDER_MAINTENANCE.md) passed final
verification/review (1,582 tests, one expected skip). Publication must preserve
the unchanged live source; STATUS records the deliberate deployment lag.

1. After incident resolution and separate restart approval, controlled stop/drain and verified disarm,
   deploy the reviewed commit with the same ledger/limits and verify startup.
   Do not update the active package beneath its recovery fingerprint.
2. Observe actual reference status, same-market repricing, terminal/fill
   reconciliation, cap drainage and reward progress. Synthetic tests prove
   neither payout nor profitability.

D-098 supersedes the earlier unapproved-repricing statement below; reward-
chasing replacement remains prohibited. Older queues are dated context.

## After D-097 — running; observe live outcomes

The [initial ranking checkpoint](docs/BUILD_INITIAL_RANKING.md) is published,
deployed and live-observed. Complete suite: 1,554 tests, one expected skip. The
run reached 30 resting entries, then failed during atomic status publication.
Recovery canceled all entries and verified flatness. D-097's repair and controlled
live restart are complete; STATUS owns current process and verification state.

1. Continue bounded observation of status publication, fills, exits, actual reward
   evidence and source availability. The bot is running at 30 resting entries;
   preserve the existing controlled stop/recovery path and do not suppress a
   permanent I/O failure.
2. Before proposing another selection policy, measure simultaneously current
   metadata/ranking coverage: startup released after 120s with 864/1,024 evaluated.
   More elapsed time alone does not keep earlier metadata fresh. Do not relax
   freshness or claim global $2 optimality from cumulative coverage.
3. Incumbent replacement/repricing remains unapproved and unimplemented. Later
   better candidates do not displace already resting orders automatically. The
   latest public census found 4/15 incumbents in the $2+ tier versus 40 available
   priority samples and one five-tick stale ask; use that evidence if the operator
   chooses to design bounded replacement/repricing.

## After D-094 host/account repair — 2026-09-23

[Host continuity and manual-cancellation reconciliation](docs/BUILD_HOST_CONTINUITY.md)
are complete. D-095's authorized restart is running at the 30-order limit with
no observed position at the acceptance checkpoint. Next: monitor actual fills,
partial closes/exits, order turnover, reward estimates and settled trading loss.
Measure broad-book freshness, metadata retries, exclusions and candidate-to-order
conversion under sustained operation. Do not infer profitability from resting
capacity; preserve existing limits and use the controlled stop path if needed.

D-096 above addresses early entry before initial coverage. A future safe incumbent
replacement policy still requires a separate decision; do not enable price
chasing or cancellation churn implicitly.

## Historical pre-D-094 queue — completed blockers retained below

### After D-093 implementation — 2026-09-23

[Broad discovery](docs/BUILD_BROAD_DISCOVERY.md) is implemented and verified.
Retain the existing pre-restart order below. Do not restart implicitly.
The new public-only census completes in 90 seconds with 150 passing markets;
that is not a current-account or simultaneous-slate guarantee.

## Market-coverage repair complete offline; remaining live acceptance

The bot is stopped and the operator reports all orders manually canceled.
See the [read-only investigation](docs/INVESTIGATION_LIVE_EXIT_2026-09-22.md).

D-091 [repairs coverage/refill](docs/BUILD_DISCOVERY_COVERAGE.md). All 1,024
synthetic candidates are reached; the complete 1,492-test suite passes with one
expected skip. No further discovery implementation is pending from this unit.

1. Separately establish/test process-host continuity and truthful liveness status.
2. Before a separately authorized live restart, reconcile manual cancellations
   and any fills using actual venue evidence. Do not treat stale saved state as
   current or mark local orders canceled without evidence.
3. During authorized acceptance, inspect broad-book freshness, metadata retries,
   proposal exclusions and entry-source blocks. Distinguish subscribed/economically qualified/
   selected/placed counts; do not promise 30 entries or earnings from offline
   coverage. Resolve any measured bottleneck before expanding capacity.

## Historical completed D-089 publication/recovery checklist


1. Publish and deploy the verified D-089 pre-transport abort fix.
2. Clear only the stale dead-child control owner. With parent, child and account
   leases held, back up the ledger and transactionally correct exactly the two
   retained cancel rows whose timestamps/stacks prove the old pre-transport
   branch. Audit both identities and capacity; never generalize to other UNKNOWNs.
3. Start recovery-only and verify both retained orders plus any naturally
   observed fills/positions reconcile to `STOPPED_FLAT`.
4. Only after verified flatness, use the already authorized normal live start and
   confirm current catalog, books, lifecycle, account and admission status.

## Current: publish D-087 and reference-price verification

1. Complete the exact staged-diff/security review and publish the isolated branch.
   The final complete suite passes: 1,478 run, 1,477 passed, one expected skip.
2. Obtain explicit controlled deployment/restart
   authority; preserve the same ledger, limits and source-fingerprint procedure.
3. Postdeployment acceptance must prove lifecycle subscribed, complete current
   catalog, broad fresh books and normal reference/economic gates before judging
   order breadth. Do not infer profitability from source/reference correctness.

## Priority: repair observed selection-source failures

Diagnosis is recorded in FINDINGS section 125. D-086 implements items 1 and 2
in the isolated `fix/reward-source-refresh` branch; see
[repair](docs/BUILD_REWARD_SOURCE_REFRESH.md). Verification is complete; obtain
controlled live deployment authority for the isolated fix. Do not overwrite the active
package while its old supervisor owns the recovery fingerprint.

Predeployment [live source check](docs/VERIFY_REWARD_SOURCE_LIVE.md) now passes:
128 refreshed books versus 4.81 average baseline on the same feed. Still needed:
full timing/fee/economic-filter counts and diagnosis of the independently
observed production lifecycle retry exhaustion. Neither requires placing orders.

1. Verify repaired full-catalog refresh under live shared-read load after deployment.
   The [reward API re-audit](docs/REWARD_API_REAUDIT_2026-09-22.md) measured 1,000-row
   pages: five requests / 1.986 seconds versus roughly 50 at our current size.
   Offline page-size/resource tests now pass; live shared-budget behavior remains
   to be observed before considering broader redesign.
   Preserve complete/fresh reward proof; do not bypass exhaustion or use an
   expired catalog to place entries. Verify the proposed repair offline before
   any separately approved live deployment/restart.
2. Quiet-book venue response/sequence compatibility is verified by the bounded
   source probe. After separately approved deployment, verify the same behavior
   under real runtime/account/metadata load; keep the stale-data limit unchanged.
3. Evaluate the existing 128-market/16-per-cycle/300-second discovery path and
   add bounded per-stage exclusion evidence. Prove current capacity can fill
   when qualifying markets exist before considering wider subscriptions.

## Live observation after recovered restart

The handoff fix is published as `238df32`. D-085 recovery reached verified flatness,
and the authorized normal run has completed two admission rotations.

1. Observe continued discovery/ranking and actual occupancy against the unchanged
   30-order ceiling. A reviewed candidate count is not a tradable-market count.
2. Collect actual order duration, fills/fees and estimated versus paid rewards;
   do not label projections or zero current inventory as profitability evidence.
3. Preserve exact evidence for any new blocker; do not bypass account, timing,
   reward or risk gates or introduce optional hardening into this live trial.

## First supervised opening recovery

Completed history: the first authorized launch failed closed before any order
because personal deposit/internal-transfer evidence was not attributable and a partial
opening checkpoint could not resume. D-084 implements exact completed
pre-boundary attribution plus same-checkpoint resume. The later live opening and
D-085 recovery are verified in STATUS.md; this is no longer a pending opening
task. Never delete or replace `data/trader/account.db`.

## Current-path review findings repaired

[Current review](docs/REVIEW_CURRENT_LIVE_PATH_2026-09-22.md), priority order:

1. R1: connect the durable loss hold to owned-entry cancellation/drain.
2. R2: preserve incentive/selection authority through the final entry-send fence.
3. R3: allow exact owned cancellations without requiring a recent book price.
4. R4: qualify/tier overlapping programs before selecting one per market.

All four are implemented with focused production-path regressions and bounded
resource checks. The 1,441-test suite and GET-only startup pass. This repair unit
is reviewed and published; proceed to item 7. No optional feature was added.

## Candidate timing qualification resolved; live acceptance follows review fixes

D-082 implements and verifies the first bounded timing family: exact scheduled
economic-data releases with current occurrence and primary-milestone proof.
The real public refresh now prepares 1,024 reviewed candidates and 128 initial
books. Unknown early-close rules and sports remain blocked; provider freshness
must be resolved before adding a sports family. Do not restore blanket approval.
After the current review fixes, proceed to supervisor checklist item 7 below.

## Production supervisor connection — ordered checklist

The [end-to-end review](docs/REVIEW_D081_END_TO_END.md) findings R1–R7 are
repaired and verified offline. Items 2–5 remain complete. Item 7 remains the
first supervised live acceptance; software evidence is not live/account evidence.
The later current-path review above reopens software review item 6 for its
new findings; it does not undo the earlier seven D-081 repairs.

D-080 requested this checklist first; D-081 implements the software connection.
This is not permission to launch. Reuse the existing
[native design](docs/DESIGN_WINDOWS_SUPERVISOR_S2.md) and
[S2B implementation](docs/BUILD_WINDOWS_SUPERVISOR_S2B.md). The
[supervised foreground launcher](docs/RUN_LIQUIDITY_BOT.md) is the implemented path.
Items 1–6 form the software work; item 7 is live acceptance; item 8 is later host
recovery. Track evidence here as each item finishes. Earlier hour estimates are
provisional until item 1 resolves the production recovery boundary.

1. [x] **Define the production recovery contract.** Trace the actual Poly
   supervisor, host recovery and runner paths against Kalshi's owners. Record
   which faults retry in-process, permit a bounded child restart, allow only
   recovery, or require attention. S2B currently blocks automatic relaunch after
   a missing terminal fence (`recovery_fence_unknown`); specify the exact proof
   and permitted operations for any proposed recovery-only child instead of
   clearing that hold. Specify whether successful recovery resumes entries or
   stays paused. Acceptance: reviewed transition/failure table and module map;
   any changed restart policy is explicitly identified before implementation.
2. [x] **Connect a fixed production child to the existing host.** Reuse native
   leases, IPC, control journal and bounded scheduling. Give only the child
   credential access, financial-ledger ownership and existing mutation authority.
   Preserve fixture restrictions through a separate explicit production path.
   Bind approved account, checkout/configuration and child identity; prevent the
   direct launcher and supervised child from running concurrently. Acceptance:
   one parent/child and one financial writer across launch paths, with injectable
   synthetic dependencies exercising the production composition.
3. [x] **Make initialization and recovery survive process failure.** Preserve the
   same ledger, opening boundary, loss windows, inventory clocks and uncertain
   orders. Never replay `--initialize`, delete a partial ledger or create a new
   risk baseline on retry. Reconcile before enabling new entries; do not replay
   ambiguous mutations. Carry actual exhaustion holds and shared cooldowns into
   the control fence; obtain fresh quota/source proof. Address expired candidate
   reviews while inventory remains, without refreshing authority over an
   uncertain ledger. Acceptance: crashes before/after opening approval and
   durable order send recover or produce a precise attention state without
   duplicate orders, lost owners or reset restrictions.
4. [x] **Connect health, stop and operator controls.** Route start/stop/status
   scripts through the production host. Report parent/child identity, useful
   runtime progress, stage, restart attempts and the exact blocker; distinguish
   saved snapshots from current liveness. Operator stop must persist through
   backoff and parent restart. Preserve graceful order/inventory drain and require
   actual child exit before replacement. Acceptance: stop wins during startup,
   retry and drain; stale status/IPC cannot re-arm or report a flat account.
5. [x] **Test failure recovery and resource limits.** Use disposable ledgers and
   fake venue wires for child/parent death, stalled progress, disconnects, 429
   cooldowns, partial fills, unknown sends, logging/disk/IPC failure and interrupted
   shutdown. Verify bounded retries, no competing child and retained safety
   state. Reuse existing 30/120-market and native lifecycle benchmarks, including
   parent idle CPU, loop latency and handle/task cleanup. Acceptance: focused
   regressions and relevant full suite pass; measured budgets are met. These are
   software fault tests, not a paper-profitability stage.
6. [x] **Review and publish the software.** Review the actual production diff for
   ownership races, recovery mistakes and accidental fixture bypasses; fix valid
   findings and rerun affected checks. Update the run guide, current status and
   verification records, commit/push, and verify repository parity. Acceptance:
   reproducible evidence, no known blocking finding, documented remaining live
   criteria and a clean reviewed commit. Software completion alone is not live
   acceptance.
7. [ ] **Verify the first supervised live run.** Refresh and validate corrected
   candidate inputs, current authentication/account/fee/quota evidence and launch
   readiness. After explicit live-start authority, observe ranked resting orders,
   fills/exits if they naturally occur, logs and status under the existing limits.
   Verify authorized graceful stop/recovery separately; never force live failure
   or create fills to satisfy a test. Acceptance: label each observed criterion
   and leave unobserved failure behavior explicit; document remaining blockers.
8. [ ] **Later: Windows host watchdog.** Plan native recovery if both parent and
   child disappear, using the durable armed/stopped state. Recheck Poly's actual
   at-logon trigger; do not promise reboot recovery before login. Define separate
   resume/reboot acceptance and task removal. Install persistent tasks or alter
   power/startup settings only with operator authorization. Acceptance: scoped
   ownership/stop tests and an explicitly approved host test; simulated events
   alone do not prove recovery after a real reboot.

## Foreground-launch context

D-079 removes the one-market launch-input bottleneck, and D-082 supplies a
validated broad local scope for the reviewed scheduled-release family. The first
explicit initialization refreshes that scope from public sources before any
trading authority exists. Do not
replace final WebSocket competition ranking with reward/target, describe all
catalog rows as eligible, or refresh candidate authority over a non-flat or
uncertain existing ledger. The next work is supervised live acceptance item 7;
first live initialization remains a separately authorized operation.

D-083's [entry-quality gates](docs/BUILD_ENTRY_QUALITY_GATES.md) now require
exact full-weight reference quotes, 70% retained value per side and a $1
remaining-reward floor, with $2+ candidates ahead of the $1–<$2 fallback. Do not
turn these projections into payout/profit claims or add reward-chasing cancels.

The [D-078 automatic reviewed-market selection](docs/BUILD_LIVE_SELECTION.md)
integration is verified. D-079 now prepares those exact current rules/milestone
bindings automatically. Do not replace missing timing with expiry or describe
the whole reward catalog as tradable.

A later explicit operator start captures/approves the fresh opening with
`-Initialize`. The coding assistant does not invoke it. After launch, inspect
real orders/fills/fees, shutdown and estimated versus paid rewards. Optional
hardening remains deferred; production supervisor integration is queued above.

The older milestone notes below describe their original execution-disabled
scope; D-077's [run guide](docs/RUN_LIQUIDITY_BOT.md) owns current launch wiring.

D-073 completes #3's execution-disabled [reward reflection and checkpoint
lifecycle](docs/BUILD_REWARD_REFLECTION.md). Do not add per-market book polling,
treat a queue row as atomic cross-source proof, restore live samples from disk or
count estimates as paid rewards.

D-074 clears the S2A CPU/ownership resource gate and records a fresh validated
[read-only quota pair](docs/BUILD_WINDOWS_SUPERVISOR_RESOURCE_FIXES.md). D-075
implements the separately assigned [offline S2B runtime and transactional
restriction transfer](docs/BUILD_WINDOWS_SUPERVISOR_S2B.md). Do not add a dynamic
runtime factory, restore tokens/source proof, infer clean exit from RESULT, or
turn this fixture path into a production launcher. Next priority: establish the
member direct/non-direct fee profile and present the current per-order fee-bound
correction for explicit decision; then prepare selected-market timing reviews,
capture launch-boundary account evidence and complete integrated readiness review.
A live start remains a separate operator decision.

D-072 completes #2's execution-disabled [entry-pair dispatch and mutation
transport](docs/BUILD_ENTRY_DISPATCH_TRANSPORT.md). Do not rebuild it or infer
live authority from the presence of a network adapter. Mixed/unknown batch
outcomes remain held for reconciliation, and live activation is unavailable.

Production own-order/public-book reward reflection and checkpoint lifecycle are
now implemented under D-073. Preserve UNKNOWN when stream/book/order identity
cannot be joined.

Priority 5 now has D-069's [bounded selection component](docs/BUILD_MARKET_SELECTION.md),
shared [incentive discovery](docs/BUILD_INCENTIVE_DISCOVERY.md), and D-071's
[automatic market admission/rotation](docs/BUILD_MARKET_ADMISSION.md). The latter
owns one-reader-at-a-time joined replacement, exact removal proofs, fresh
snapshots and bounded metadata/cache handoff. Do not rebuild these components
or repeat the accepted Poly/hourly-efficiency policy decision. D-072 now supplies
source-bound entry-pair dispatch and production order transport behind an
unavailable live-activation boundary. Do not add a second REST budget.
Working-order score monitoring still needs reflection evidence, not guessed
private/public synchronization. Automatic repricing thresholds and live launch
remain separate decisions. Preserve all inventory/unknown owners during rotation.

D-070 accepts Poly-style discovery/selection and per-program estimated tracking,
explicitly removing the proposed fixed 60-market pool. The
[offline discovery/tracker component](docs/BUILD_REWARD_TRACKER.md) now exists;
do not rebuild it or treat time-to-$1 estimates as paid cash or exit authority.
Its candidates now reach D-071 subscription admission and D-072 entry dispatch.
Production reflection proof and explicit checkpoint ownership are integrated by
D-073; unknown remains unknown whenever its short-lived join is absent.
D-083 supplies the accepted initial-entry payout/value gates. New category
filters, rotation thresholds or incumbent repricing still require their own
decision, not an automatic copy of Poly configuration.

Priority 5 production reward reflection/checkpoint integration is complete.
Next work is priority 6 runtime/readiness acceptance. Priority 4's
[supervised injected lifecycle](docs/BUILD_DISPATCH_LIFECYCLE.md) now covers stop,
outcome drain, failure propagation and no-replay ledger reopen. This does not
clear production transport, real input or native S2B review/resource gates.
[Owned write outcomes](docs/BUILD_MUTATION_OUTCOMES.md)
now route 429 pauses and recovery notifications without automatic retries;
do not rebuild them. [Shared write-quota ingestion](docs/BUILD_WRITE_QUOTA_SOURCE.md)
is implemented offline using the existing read pair; do not create another
quota poller. Actual account quota/probe configuration and verified member fee
profile remain readiness inputs, not facts proved by fixtures. The
[source-bound candidate integration](docs/BUILD_DISPATCH_SOURCES.md) now covers
account/book/exit rechecks and stopping the injected dispatcher; do not rebuild it.
Keep transport disabled until separately
authorized readiness work and launch approval.

D-068 implements the [operational accounting release](docs/BUILD_ACCOUNT_RECONCILIATION.md)
on top of D-067 restrictions. Do not rebuild it or re-open the accepted global-
proof policy choice. The actual fresh flat boundary still needs explicit
approval during a separately authorized launch. Economic discrepancies require
their own reconciliation; ordinary review/empty history never clears them.
Only new schema-5 synthetic ledgers were exercised; no migration or account
request is authorized by this build.

Updated 2026-09-22. Follow accepted decisions through D-072 and `AI_OPERATOR.md`.
Active folder: `C:/Users/rynna/Bots/kalshi`; do not rebuild the old OneDrive copy.
Native Windows only; no further WSL mirroring or execution.
Follow D-043 for the repository publication: this folder now tracks the canonical
GitHub `master` branch. Future source/doc changes belong here and can be reviewed
with Git. See `docs/GITHUB_PUBLICATION.md`. Live operation remains disabled.
AI performs approved work; present undecided project choices to the operator
and record their decisions before implementation.
D-065 requires verify, scoped diff/secret review, commit, push and parity check
after each completed work unit. Do not publish unfinished or private work.

D-060's [review corrections](docs/BUILD_COMMAND_CAPACITY_REVIEW_FIXES.md) close
overall-review priorities 1/2 in offline scope: focused/full suites, disabled
preflight and valid complete-history 30/120-market resource acceptance pass.
Do not migrate schema-2 ledgers, delete retained history, enable transport,
change risk/configuration, restart or infer live readiness from this clearance.

Priority 3 from the [overall review](docs/REVIEW_OVERALL_2026-09-21.md) now has
[opening-account/cash evidence](docs/BUILD_OPENING_ACCOUNT_CASH_EVIDENCE.md).
Do not rebuild it. Sequential 512-row normalization now passes the bounded
latency fixture with cross-batch conflict tests. D-064 selects exclusive primary
subaccount 0 and requires no nonzero position or resting order before arming.
Fresh real-account evidence is still missing; choose the exact boundary only
during a separately authorized launch. D-067/D-068 now supply the durable
accounting/release component. Automatic corrections, settlement P&L attribution
and live entry authority remain unavailable.

Item 4's [offline write budget](docs/BUILD_WRITE_BUDGET.md) now passes the
synthetic 30/120-shard resource target. The
[bounded dispatcher](docs/BUILD_WRITE_DISPATCHER.md) connects
[source-bound offline candidates](docs/BUILD_DISPATCH_SOURCES.md) to durable
writer receipts and the sole injected executor. The
[write-quota source](docs/BUILD_WRITE_QUOTA_SOURCE.md) now joins the existing
guarded document refresh to that budget. The
[outcome owner](docs/BUILD_MUTATION_OUTCOMES.md) preserves UNKNOWN holds and
signals recovery after persistence. The
[runtime lifecycle](docs/BUILD_DISPATCH_LIFECYCLE.md) joins dispatch outcomes
before reader teardown and preserves restart holds. D-072 adds the bounded
production transport adapter but not a constructible live activation.
No live authority has been connected. D-073 completes item 5's production
reflection/checkpoint integration; item 6 supervised runtime/readiness and prior
resource gates still apply.

D-063: continue directly in this session; no delegated agents or model-switch
steps unless the operator explicitly requests them again.

D-054 [independent Astra review](docs/REVIEW_D054_ASTRA.md) clears both D-053
clock findings and completes the execution-disabled supervisor S1 review.
D-048 [independent Astra review](docs/REVIEW_D048_ASTRA.md) also clears the
retained connection-finalization finding. Both prerequisite review gates are
complete; no Sol fix phase is needed for either review.

D-057 [implements the S2A corrections](docs/BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md)
from the [D-056 review](docs/REVIEW_D056_ASTRA.md). D-074 subsequently attributes
and fixes the idle CPU cost without weakening file security; the full native
resource fixture passes. D-075 now supplies the fixed offline S2B runtime and
recovery fence. Production construction, real-input readiness and live operation
remain unavailable; no service/task or bot start follows from this clearance.

D-061 supersedes D-049's mandatory recommendations and manual model switches.
Continue authorized work with the active model while preserving review,
verification and every safety/authority gate.
Sol implemented R1-R4 from
`docs/REVIEW_D036_ASTRA.md` with nine new regressions and passing 30/120 scheduler
and token resource checks. Astra re-review cleared R1-R4 without new blocking
findings: 87 focused tests and the integrated reconnect probe passed. See
`docs/REVIEW_D036_ASTRA_R2.md`. Git diff was unavailable then. The exact prior
full-suite outcome after the last source edit is recorded in STATUS.
D-039 explicitly authorized implementing BOTH D-038 phases in one assignment.
Both are implemented; the initial Astra review found three issues. See
`docs/REVIEW_D039_ASTRA.md`: R1 is an inherited grant-rollover design conflict;
R2/R3 concern shutdown ownership and a clock-fault waiter. D-040 design and
D-041 Sol fixes are complete and Astra cleared original R1-R3 in scope. See
`docs/REVIEW_D041_ASTRA.md` for two P3 follow-ups: truthful run status after repeated
cancellation, and a pending record that does not retain exception/payload frames.
D-042 Sol fixed both and added regressions. Astra re-review cleared both with
no new findings in that scope; see `docs/REVIEW_D042_ASTRA.md` and STATUS. D-044
design, D-045 Sol Phase 1, D-046 fixes/re-review and D-047 shutdown fixes are
complete. D-047 Astra review's R1 is implemented under D-048 and awaits review.
Git diff was unavailable in the historical review; D-043 subsequently connected
the active folder to Git. Live operation remains disabled.

Credential blocker resolved: the new ID file and supplied RSA private key
successfully authenticated the one-time account inspection. See `FINDINGS.md`
section 44. D-030 now approves separating pre-bot history; it does not install
a launch boundary or authorize a loss-accounting reset. Private subscription
and controlled re-subscription access verified; no actual account event occurred.
Exposure decision resolved by D-031: Poly's verified reference 20 gives $300
at size 10, not the fixed $400 proposal. Existing atomic entry gate enforces it;
actual breadth remains limits-driven. D-032 implements advisory exit/deadline
logic. D-034 now supplies source-bound input adapters and runtime seams, but real
market-rule reviews and member-fee profile are not installed. D-036 now provides
bounded metadata scheduling and explicit shared quota refresh. D-035 adds durable
history-read receipts, restart gap inspection
and known-omission blocking, not complete venue proof or a launch boundary.
Supervised quota freshness/grant expiry (item 3) is implemented under D-039 and
its fixes are cleared by D-041/D-042 reviews. Account/history/private-stream/cash proof remains a
launch prerequisite.
Do not rebuild the completed adapters or history receipts.
Credentials and subscription acknowledgments do not authorize live activation.

## Completed

- D-039 both quota phases: opt-in lease/dispatch enforcement and one automatic
  supervisor, same-bucket recovery probes, runtime holds and diagnostics. No
  production probe allowance selected or live activation. Independent review
  found three P2 issues, fixed under D-041 and cleared. D-042 follow-ups are also
  cleared; see `docs/REVIEW_D042_ASTRA.md`.
  `docs/REVIEW_D039_ASTRA.md` owns the original findings.
- D-036 optional runtime-owned metadata scheduler: bounded ACK/bootstrap,
  lifecycle coalescing, expiry revocation and retries. Shared read limits now
  support explicit coalesced quota refresh, account-read priority and all-429
  pauses; capacity is not assumed available tokens. The fixed milestone has
  25 scheduler and 18 rate tests; 30/120-market/request checks pass. See
  `docs/BUILD_METADATA_SCHEDULER.md`, `docs/RATE_LIMITS.md` and STATUS. No live use.
- D-035 durable completed-enumeration receipts and source provenance, exact
  interval-gap inspection across restart, and omitted-known-fill recovery guard.
  All 670 tests (31 focused), two guard reversals and 128/4,096-row diagnostics pass.
  `docs/BUILD_HISTORY_COVERAGE.md` records limits and unanswered venue questions.
  No real launch boundary, old-fill classification/import or account calls.
- D-034 typed metadata, fees, ticks, reviewed milestone binding and optional
  runtime publication/revocation. All 639 tests (41 focused), two reversals and shared
  30/120-market diagnostics pass. `docs/BUILD_MARKET_INPUTS.md` records source
  contracts and remaining real-profile/review/scheduling gaps. No account use.
- D-033 structured local logs and safe failure context across runtime, recovery,
  engine, REST, writer, injected execution and inventory transitions. All 598
  tests (29 focused), two reversals and 30/120-market log diagnostics pass. Runtime logging
  failure stops local processing; it never claims venue cancellation/flatness.
  See `docs/LOGGING_AND_ERRORS.md`. Share this sink in the future launcher.
- D-032 exact inventory-exit planner and timer integration, cancellation/fill
  proof and restart-safe attempt projection. 569 Kalshi tests, 104 Poly tests,
  two reversals and 30/120-market diagnostics pass. No trading or paper process.
  See `docs/BUILD_INVENTORY_EXITS.md`; live input producers remain unfinished.
- D-031 Poly exposure calibration: local reference default 20, $300 aggregate
  at size 10, $90 per market. Config/default/CLI agree; 510 Kalshi tests,
  104 current Poly reference tests and two fault reversals verified. No live
  activation. See `docs/BUILD_POLY_EXPOSURE.md`.
- D-030 baseline direction recorded; bounded private-stream diagnostic built.
  All four private channels acknowledged twice on real account; clean sequential
  re-subscription. No account events, so live delivery/gap recovery unproved.
  498 tests pass; two in-memory safeguard reversals detected. See
  `docs/BUILD_PRIVATE_STREAM_CHECK.md`. No trading process or account mutations.
- Read-only account inspection, 2026-09-20 17:32 Eastern: primary account cash
  $500.4268, zero resting orders/nonzero positions, 18 recent fills and zero
  archived fills returned. Basic-tier budgets were read successfully. No
  credential contents exposed, account writes, ledger imports or bot start.
- D-029 project and supplied credential relocated beside Polymarket; bytes
  verified unchanged before environment/routing updates. Both Python environments
  repaired; 479 tests pass at the new path. Subsequent account evidence is
  recorded above, separately from relocation verification.
- D-028 atomic local account verification, exact order/fill/scope checks,
  writer-revision freshness and recovery history/source provenance. 479 tests,
  two reversals and passing 30/120-market diagnostics. See
  `docs/BUILD_ACCOUNT_VERIFICATION.md`; full account completeness is NOT proved.
- D-027 wires advisory exact passive inventory management, persistent age clocks,
  shared exposure projection and atomic offline reservations to runtime seams.
  450 tests; two reversals; passing 30/120-market and recovery diagnostics.
  See `docs/BUILD_INVENTORY_RISK.md`; no live reservation or exit dispatch.
- D-026 connects independent reader generations, event engine and bounded
  recovery worker. Durable fill-before-order inbox, missed terminal updates,
  startup/restart/reconnect, immediate report revocation and shutdown are tested.
  410 tests; two safety reversals; passing 128/1024-fill diagnostics. See
  `docs/BUILD_RECOVERY_ENGINE.md`. Full proof/live authorization remain blocked.
- D-025 automatic verified fill import, bounded missing-order binding, immutable
  deduplication and separate owned-quantity venue-cost exit fallback. 371 tests,
  two safety reversals and passing 128/1024-fill diagnostics. See
  `docs/BUILD_AUTO_RECOVERY.md`. No complete recovery/live readiness claim.
- Added archived terminal-order retrieval/binding and 404 recovery for known
  orders. Missing fill quantities retain reservations; absent rows prove nothing.
  `docs/BUILD_ARCHIVE_RECOVERY.md`: 335 tests, two reversals, 128/4096-order
  diagnostics. History execution-time conflicts are rejected during staging.
- Implemented D-024 weighted-average partial-close accounting, immediate actual
  fees and receipt-window attribution; retained execution timestamps separately.
  `docs/BUILD_ACCOUNTING.md`: 306 tests, source arithmetic comparison, fault
  reversals and latency measurements. Schema 2 rejects old ledgers without
  automatic migration. Complete recovery is still unfinished.
- Built and verified the first Windows-native component foundation under D-021.
  See `docs/BUILD_FOUNDATION.md`: 110 tests, safety reversals and bounded core
  microbenchmark. This is not a live trader or complete integration.
- Added bounded single-writer durability, atomic per-fill risk updates, GET-only
  token-budgeted REST fallback and stale-generation account evidence guards.
  See `docs/BUILD_ACCOUNT_IO.md`: 159 total tests, two further safety reversals
  and an offline writer latency fixture. Complete account recovery is not done.
- Added owned-order persistence/stream projection, terminal/fill agreement,
  REST order recovery, current/archive fill evidence staging and exact passive
  inventory plans. `docs/BUILD_RECOVERY_ORDERS.md`: 212 tests and resource checks.
- Added Reference Price quote/ranking components, versioned cache, priority event
  owner, injected mutation journal/executor and Windows stop-request primitive.
  `docs/BUILD_ENGINE_RANKING.md`: 280 tests, two reversals and 30/120-market load
  checks. These are not a supervised production runtime or live market ranking.

## Next implementation milestone — no live activation

Reference audit completed: `docs/POLYMARKET_POLICY_CODE_AUDIT.md`, 216 passing
source tests. Use its actual accounting/selection/exit/restart behavior, not the
earlier unverified execution-time accounting proposal. D-023 replaces the request
for arbitrary 30/32 slots with limits-driven admission. D-031 now resolves
exposure calibration using Poly's verified local reference default; do not
reopen the superseded $400 proposal or derive budgets from current occupancy.

1. Follow D-044's phased history/private-stream continuity and starting-inventory
   design around the D-026 recovery-connected engine. Phase 1 is implemented
   under D-045, pending independent review; do not build Phase 2/3 from this
   assignment. D-028 now provides coherent local
   inventory/order/pending evidence and retains the actual history interval;
   it must not be rebuilt or mistaken for a venue snapshot/stream barrier.
   D-035 now records completed enumeration intervals/digests durably and flags gaps
   and omitted known fills. It is not a complete-history certificate. D-030 accepts
   separate pre-bot history, but an actual launch boundary and full coverage proof
   remain open. Establish that coverage contract and seek
   venue clarification where published sources lack cross-source guarantees.
   The durable inbox and bounded recovery
   worker now handle fill-before-order interruptions and missed terminal updates.
   Resolve correction/reversal/settlement and starting-inventory completeness
   contracts before implementing those branches. No verified Kalshi BUSTED
   equivalent is established; conflicts block rather than reverse speculatively.
   Exit-only venue cost is not complete accounting. Old-ledger migration remains
   separately scoped. Never invent fills or release a reservation on 404.
2. Complete production authority around D-027's offline atomic reservations and
   advisory inventory plans, then selection/rankings and bounded discovery/read-
   budget bootstrap. Account cash/order snapshots need coherent proof; the
   conservative fixture cash subtraction is not production balance accounting.
   D-031 supplies the explicit $300 exposure calibration; connect it to production
   cash/admission authority without changing the budget. Reader adapters
   now exist; D-030 checked private subscription access only. Other callbacks remain injected
   seams, not integrated production proofs. Add long-history retention
   and outage/reconnect-storm checks; never duplicate healthy-feed data polling.
3. D-034 supplies typed input producers and runtime lifecycle seams. Establish
   the real account fee profile and reviewed market-specific milestone/rule
   bindings when selecting markets. D-036 now implements bounded control-plane
   bootstrap, expiry and missing-data refresh scheduling around the shared service.
   D-039 implements both phases of `docs/DESIGN_QUOTA_FRESHNESS.md`; its reviewed
   fixes are cleared through D-042. Production probe configuration
   still needs verification/approval at launch; no current account quota inferred.
   Reuse
   sufficient stream fields; do not turn book ticks into metadata polls or treat
   fixture profiles/expiry dates as evidence. The exact exit planner exists;
   connect production transport/write budgets only behind complete account,
   book, writer and terms authority. Keep ambiguous mutations blocked. Quote math and three
   informational ranking views now exist; automatic selection/repricing remains
   unapproved. Confirm variable-band reward ticks before supporting those grids.
4. Follow the proposed D-050 supervisor phases after approval; design priority
   and S1 do not waive D-048 or production proof. Complete Windows supervised
   launch/stop, metrics and outage protection around the ownership/stop primitives;
   wire one D-033 diagnostic sink per process into every
   component, verify enabled/healthy logging, and close it after ledger drain.
   Final end-to-end integration tests. A local stop
   request is not cancellation or flat proof. Do not install live services/start.
5. Preserve D-031's limits-driven admission/exposure calibration and D-032's
   explicit deadline rules; verify each selected market's timing and resume
   integration. Then finish integrated review and seek separate
   explicit live-run authorization. Account/stream eligibility remains unverified.

The percentage entry-cap rule is accepted. No additional paper stage is required.

## Earlier planning checklist — review with D-021 build authority

- Inspected the correct Polymarket checkout read-only and adopted its core
  shared-entry-point/document-ownership pattern. Recorded WebSocket-first,
  REST missing-data fallback, CPU-efficiency and scalability as permanent rules.

- Collected and verified public Kalshi API documentation into
  `docs/KALSHI_API_REFERENCE.md`, with exact published schemas, source dates,
  checksums, a coverage audit, and implementation cautions.
- Preserved historical data. No collector restart, account API calls, orders,
  or bot implementation occurred in the documentation task.
- Researched liquidity rules and all documented reward interfaces; checked
  every incentive filter, paginated the active universe, and inspected 40
  current books. See `docs/LIQUIDITY_REWARD_RESEARCH.md`. This was one-time
  public research, not a paper-trading stage.

## Next: finish the live-run plan

The percentage reducer now means the accepted source-verified entry-cap rule.
It changes order count, not quote size or exact-quantity inventory exits.

Apply `AI_ENGINEERING.md` and `docs/ARCHITECTURE.md` to every item below.

1. Confirm account reward eligibility and a final reward-credit reconciliation
   route; public APIs do not expose a personal LIP reward ledger. Then use the
   research/API reference to specify the Reference Price quote policy,
   repricing, partial fills, exits, reconciliation, expiry, and stop behavior.
2. Respect D-016: $500 capital, 10-contract entries, max 30 resting entries
   excluding position-management orders, $25 settled-loss stops in fixed
   six-hour ET windows. Apply D-018/D-020's verified inventory policy and
   $90 market / `10 * (market slots + 10)` portfolio exposure formula.
   Confirm managed-market capacity separately from the 30-entry-order cap.
   Review Kalshi-specific exit/deadline mapping, any additional
   event-concentration limit, resumption policy, market list and duration.
   Under D-017 count opened-and-closed trade results only; specify partial-close,
   fee-allocation and late-fill/window accounting for review.
3. Build under D-021 and retain live-readiness gates. No paper-testing stage
   is requested. The assistant's suggested $10 stop is not an accepted limit.
4. Credentials may be used when needed under D-012. Verify setup privately
   when account data is needed; do not include keys in documentation.
5. Before live integration, complete the field-level stream/REST map, recovery
   proof and bounded scheduling/resource design. Define workload and CPU,
   memory/latency acceptance budgets; offline engineering checks are not a
   paper-trading stage. Do not copy Polymarket numeric limits.

6. Review `docs/MULTI_WEBSOCKET_DESIGN.md` with the operator. Multiple
   connections are required; four sockets and the detailed topology remain
   recommendations. Confirm venue/account connection allowance, approve
   final live architecture and finish risk settings before live authorization.

## Reference maintenance

Continue the Windows-native foundation with graceful stop/recovery and
non-cloud-synced runtime data. Environment and ownership primitive now exist.
Do not install live services/tasks, relocate historical data or start trading
without separate authorization.

Compact older root narratives into dated history with preserved links, then
add a routing/context/link audit modeled on Polymarket. No automated audit
or full history migration is claimed implemented yet.

Check the reference's source links and snapshot timestamp before implementation.
The snapshot is not an immutable venue guarantee. D-043 restored Git inspection
in the active folder; check its current branch and diff before future changes.
