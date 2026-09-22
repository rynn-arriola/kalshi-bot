# D-081 end-to-end review — 2026-09-22

Reviewed code: `9a476a70fcfddb20d1bf16dd7abcd0b809b3019a`.
**RESOLVED OFFLINE:** all seven findings below are repaired and covered by
regressions. This does not change the accepted recovery policy or prove live
acceptance.
The original review performed no implementation or live operation. The later
resolution changed code and tests only; it did not access credentials, a venue,
the production ledger or orders.

## Resolution evidence — 2026-09-22

- R1: the account lease encloses exception cleanup and retained task join.
- R2: production enables authenticated recovery fences; exceptional quota state
  is also atomically journaled at read/write/exhaustion transitions, restored
  before activity, and cooldown waits retain parent supervision.
- R3–R6: health/retry state is separated, preparation is supervised, recovery
  scope is owner-aware, and production exit classification is profile-specific.
- R7: terminal STOPPED_FLAT is saved only after all runtime resources join.
- Direct repair regressions: **9 passed**. Existing production tests: **7 passed**;
  live-runtime tests: **26 passed**; native supervisor tests: **12 passed**.
- Final suite: **1,428 run, 1,427 passed, one expected privilege skip** in
  216.181 seconds. Native 60-second parent and 30/120-market S2B, selection and
  admission gates pass.

No production account path was created and no external I/O occurred. Item 7,
the first supervised live acceptance, remains unverified.

## Findings, in repair priority order

### R1 — P1: keep account ownership until exception-path drain has joined

`supervised_live_child.py:232,289`: the account `WindowsLease` context unwinds
before the outer exception handler requests stop and awaits the running task.
An IPC/control/status failure therefore releases the direct-launch exclusion
while the original runtime still drains. The supervised child lease does not
protect the separate direct live launcher. A synthetic IPC failure allowed a
second real Windows lease with the same synthetic identity during that drain.
Keep the account lease through every runtime/resource join, including failure
paths; test that a competing direct owner is refused until cleanup ends.

### R2 — P1: carry real runtime restrictions across production replacement

`supervisor_launch.py:64` disables recovery fences for production;
`process_supervisor.py:405` rejects them. The production child neither captures
nor restores actual component exhaustion/cooldown state. `live.py:286` instead
constructs fresh read tokens and quota state; read/write 429 deadlines and quota
retry exhaustion are process-local (`rest.py`, `write_budget.py`,
`quota_supervisor.py`). Entry pause alone does not preserve restrictions on
recovery reads/cancels/reductions. This is a source-traced omission, not an
observed venue incident. Wire authoritative restriction persistence/restoration
before recovery activity, with explicit handling of missing evidence. Test a
crash during cooldown and after exhaustion against the production composition.

### R3 — P1: separate temporary health blockers from durable retry holds

`supervised_live_child.py:265` publishes risk/accounting blockers as status
blockers. `process_supervisor.py:400` turns all of them into retry holds;
`supervision.py:678` unions them permanently, even after a healthy status.
Ordinary `accounting_not_released` can therefore prevent recovery after a later
crash, and `ARM` also refuses outstanding holds. A synthetic degraded → healthy
→ unexpected-exit sequence ends in `attention_required/retry_exhausted` with
that obsolete hold. Production has no matching resolution path. Keep transient
health separate; preserve and explicitly resolve genuine durable exhaustion.

### R4 — P1: supervise candidate preparation and honour stop before runtime

`supervised_live_child.py:234` awaits public candidate preparation before entering
the IPC/status loop. The preparation stage services no parent pulses or status,
while parent startup/pulse deadlines are already active. Queued pulses older
than four seconds fail protocol validation; the child also retains its
pre-preparation pulse clock. A longer first-run refresh can thus fail startup,
and a stop during preparation is not rechecked before calling `run_live`.
The offline probe observed zero IPC reads/statuses during preparation and
confirmed a five-second-old pulse is rejected. Monitor this bounded stage and
check revocation before signer/runtime ownership. Test slow refresh and stop
during refresh without network or credentials.

### R5 — P1: do not let expired unowned candidates prevent account recovery

`supervised_live_child.py:237` uses the same strict `LaunchInputs.load` for
recovery as for entries. `live.py:73` rejects the entire scope if any review
expires. One expired, unowned candidate in the broad pool therefore prevents
recovery of still-current owners, before reconciliation/cancellation can start.
Synthetic current A plus expired UNOWNED, with an existing dummy ledger,
returned exit 27 and never called the runtime. Separate recovery-owner inputs
from entry eligibility; do not simply waive expiry for new entries. Test owned
inventory plus expired unrelated candidates and expired owner metadata.

### R6 — P1: classify post-admission exit 27 consistently without IPC result

`supervised_live_child.py:124,308` uses 27 for possible runtime failure, but
`process_supervisor.py:455` still maps all 20–30 exits without a delivered RESULT
to `startup_refused`. IPC failure can therefore suppress the intended bounded
recovery even after the runtime held orders. The real host finish handler,
given exit 27 and no result, reproduced that classification. Define consistent
profile-specific exit semantics and test loss of RESULT after runtime admission.
The prior build record's claimed fix of this mismatch was incomplete.

### R7 — P2: persist terminal verified-flat runtime status after cleanup

`live.py:247` publishes DRAINING before setting the returned STOPPED_FLAT result.
The old direct CLI saves the return value; the supervised child does not.
The parent saves only `supervisor/last-result.json`, so `data/trader/status.json`
remains stale. `live refresh-candidates` requires STOPPED_FLAT in that runtime
file and refuses refresh even after a clean supervised shutdown. A synthetic
verified-flat run returned STOPPED_FLAT while its last published snapshot stayed
DRAINING. Persist the terminal result atomically after successful resource joins;
test supervised stop → status → allowed refresh, and failure must never save flat.

## Verification and scope

- Existing production supervisor tests: **7 passed**.
- Existing live runtime tests: **26 passed**.
- Six additional offline probes: **6 defects reproduced** (R1/R3/R4/R5/R6/R7).
  Passing these diagnostic assertions means the defects exist, not readiness.
- R2 is verified by the source paths above; no real cooldown/restart was induced.
- Local diagnostic script: ignored `data/review-d081/probes.py`; run with
  `.venv\Scripts\python.exe -B data/review-d081/probes.py`. It patches production
  dependencies and uses disposable inputs plus a unique synthetic Windows lease.
- Existing test commands: `.venv\Scripts\python.exe -B -m unittest discover
  -s tests -p test_bot_production_supervisor.py` and the same command with
  `test_bot_live_runtime.py`.

The earlier 1,419-test suite result is historical and was not repeated here.
The seven existing production tests do not exercise the admitted production
child's full runtime/IPC lifecycle. Direct-composition and fixture results cannot
stand in for that missing coverage. Add regressions on the actual production
path with fake venue wires, then rerun relevant suites and resource gates before
re-review. Live acceptance remains separate and unverified. No profitability
claim follows from this software review.
