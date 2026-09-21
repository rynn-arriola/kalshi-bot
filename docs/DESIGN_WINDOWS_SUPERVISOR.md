# Native Windows supervisor and automatic recovery

Date: September 21, 2026. D-050 requirement; design approved for S1.
The operator requested a Polymarket-like supervisor before returning to the
D-048 review. D-049 requires an Astra design stop before Sol implementation.
D-051 now implements the execution-disabled S1 policy/control foundation; see
[build evidence](BUILD_WINDOWS_SUPERVISOR_S1.md). Subsequent
[S1](REVIEW_D054_ASTRA.md) and [D-048](REVIEW_D048_ASTRA.md) reviews are clear.
[D-055](DESIGN_WINDOWS_SUPERVISOR_S2.md) now details S2's proposed interfaces
and phase gates. S2/S3 remain unimplemented and this design adds no live launch,
installation or order authority.

## Source evidence

Polymarket checkout `C:/Users/rynna/Bots/liquidity-bot`, clean commit
`c5029321b75246bc6fd9f0d87fc372549c3b99c3`, was inspected directly:

- `scripts/supervise_commissioning.sh`: clean exit 0 ends supervision; 2/3/4
  enter attention; 5 and unexpected process deaths use restart backoff. Three
  consecutive runs shorter than 120 seconds stop the loop; backoff is 10 to 60
  seconds. The script does not independently establish account safety.
- `src/liquidity_bot/live_commissioning.py`, `main` and `_run`: a non-flat
  result maps to 3; a flat runner failure maps to 5; startup transport errors
  can also map to 5 without a flat result. Every new process must repeat its
  ownership/recovery preflight. Exit 5 alone is not proof of safety.
- `src/liquidity_bot/host_recovery.py`: persists arming, attempt count and
  generation before spawning, rejects stale children, caps host recoveries at
  three, and launches recovery-only after host disappearance. Successful host
  recovery leaves trading paused. Missing/disarmed state cannot authorize launch.
- `scripts/stop_commissioning.sh`: persists disarm before signaling processes;
  force kill is explicit. `scripts/watch_host.ps1` and
  `scripts/install_host_watchdog.ps1` supervise WSL from Windows; those execution
  paths are incompatible with Kalshi D-019 and will not be copied.
- `live_commissioning.py`, `_stuck_mutations`: attributable market trouble and
  account-wide ownership uncertainty have different scopes. Kalshi must retain
  its own source/revision and recovery contracts rather than copy classifications.

Six existing `test_host_protection.HostRecoveryTests` passed natively in 0.056 s
using inert launch mocks and temporary state: missing/manual stop, duplicate
executor prevention, persistent attempt cap, stale child, launch failure/corrupt
state, and saved source selection. The POSIX control-lock test and Bash
supervisor tests were not run; source inspection is not Windows execution proof.
The first test invocation lacked `src` on the import path; the corrected
process-local `src`/`tests` paths produced the results above. No Poly file,
dependency, configuration or process was changed; no live-state claim is made.

Kalshi base `82946a2`: `runtime.py` already owns bounded reconnect/recovery,
generation invalidation and retained teardown; `quota_supervisor.py` supervises
read-quota refresh only. `windows.py` provides process-lifetime exclusion and
named stop events. `cli.py` has only policy/preflight commands, and `config.py`
rejects live activation. There is no process supervisor or live launcher.
Reader exhaustion can leave `RecoveryRuntime.running=True`; heartbeat health
must therefore inspect useful progress and holds, not that boolean alone.

## Recommended structure

Use one native Windows supervisor process and at most one runtime child. The
child owns all venue connections, the trading ledger and eventual mutation
authority. Existing in-process recovery remains the first response to recoverable
failures. The supervisor owns process lifecycle and durable control state only;
it has no API keys, venue clients, financial-ledger writes or market polling.

| Proposed file | Responsibility |
|---|---|
| `src/kalshi_bot/supervision.py` | Immutable state/events, failure classification and pure transition policy |
| `src/kalshi_bot/supervisor_store.py` | Separate bounded SQLite control journal; atomic generation/stop/attempt transitions |
| `src/kalshi_bot/process_supervisor.py` | One parent loop; spawn, bounded status channel, exit handling and interruptible backoff |
| `src/kalshi_bot/supervised_runtime.py` | Child lifecycle adapter; current-generation health, fail-closed recovery and retained shutdown |
| `src/kalshi_bot/windows.py` | Reuse execution lease/stop primitives; add narrowly scoped control/process-handle support |
| Future `scripts/Start-BotSupervisor.ps1`, `Stop-BotSupervisor.ps1`, `Get-BotSupervisorStatus.ps1` | Thin native wrappers; no independent recovery policy |

An optional Windows scheduled task can later restart the supervisor after host
loss/logon, subject to durable disarm and explicit installation authority. It
must use the same controller, not become another trader/watchdog implementation.
No WSL, Bash, systemd, automatic Git pulls, dependency installs or self-modifying
code. Software defects go through Astra/Sol review and fixes.

## Control and child contracts

- `SupervisorPolicy`: validated restart budget, delay bounds, health and shutdown
  deadlines, approved build/config fingerprints and allowed recovery mode.
  Defaults and numbers below are proposals requiring approval, not new bot config.
- `ControlState`: schema version, environment/account scope identifier, control
  generation, desired mode, durable stop latch, pinned build/config identity,
  attempt history, next eligible restart, attention reason and active child ID.
  No balances, loss totals, fills, credentials or account-proof booleans.
- `ChildStatus`: control generation plus unique child ID, sequence, lifecycle,
  event-loop progress, outstanding-work deadlines, bounded reader/writer/quota/
  logging health summaries and reason codes. Missing, malformed, regressing or
  old-child observations never renew health. No raw responses/exception text.
- `ChildResult`: matching identity, reason enum, cleanup completion and whether
  unresolved work remains. Exit status is diagnostic, not authority to trade.
- `ProcessHandle`: spawn only the fixed interpreter/module with validated
  arguments (`shell=False`, hidden window), await exit, request graceful stop and
  retain the exact OS handle until join. Never terminate by PID/name search.
- Pure `decide(state, event, clock_sample) -> transition` produces explicit
  actions such as persist attempt, spawn recovery, request stop or enter attention.
  External side effects occur only after the required transaction commits.

Store control state under the approved non-OneDrive local data directory, apart
from the financial ledger. One short Windows control mutex serializes local
controllers and the supervisor for stop/arm/spawn decisions; never hold it
across an await or network call. Existing `WindowsLease` is a presence-based
exclusion primitive, not a reusable transactional mutex. Use distinct supervisor
and child lease identities; the child execution lease is account/environment
scoped across checkout paths, with the mapping explicitly selected at launch.

Before every spawn, recheck desired mode/generation under that control mutex and
durably reserve an attempt. Serialize process creation with the stop decision;
the child rechecks generation/stop state before opening account activity. Manual
stop first persists disarm, then signals the current child. If persistence fails,
still request a graceful stop and report the durable-disarm failure; a startup
control-store failure must block all launches. Unknown/corrupt control state is
never interpreted as a new armed session. Old child completion cannot clear a
new stop, alter a newer session or refund attempts. Controller access is limited
to the same approved Windows user; identities are not authentication tokens.

## Recovery states and behavior

States: `DISARMED`, `STARTING`, `RECOVERING`, `HEALTHY`, `DEGRADED`, `STOPPING`,
`BACKOFF`, `ATTENTION_REQUIRED`. Health is distinct from trading readiness.
Every child starts with entries blocked. Only existing account/risk/terms gates
inside the child may authorize actions; a supervisor `HEALTHY` label never can.

| Trigger | Proposed response |
|---|---|
| Book disconnect/stale market inputs with known scope | Existing stream-first repair; block affected entries, keep account and inventory service alive |
| Account disconnect, missing fills or quota staleness | Block new account-wide risk; use existing bounded stream/reconciliation/shared-budget recovery |
| HTTP 429/transient read failure | Honor shared cooldown and existing retry owner; no second parent REST loop or immediate process restart |
| Proven transient process failure or unexpected process death | Once the old child is confirmed exited, bounded restart into recovery; never directly restore entry permission |
| Typed retry exhaustion | Hold with the precise cause; do not reboot the process to reset a component's retry budget |
| Ownership conflict, financial inconsistency, schema/config/authentication error, writer/logging failure or repeated unknown defect | Attention with entries blocked; retain safe diagnostics and supported inventory service when possible |
| Risk stop/manual stop | Preserve the stop and risk history; the supervisor cannot clear or reclassify it as a crash |
| Heartbeat/progress deadline missed while process exists | Request retained graceful stop; no replacement until actual exit is confirmed |
| Sleep/resume, host loss or supervisor loss | Invalidate freshness; recover current-generation ownership/state first; proposed cold recovery leaves new entries paused for operator review |

The classifier uses typed causes, scope, durable state and cleanup evidence,
not exception-name/string matching. Broad `OSError`, a disconnect or normal exit
does not establish a safe account. Unclassified results go to attention, except
confirmed unexpected process death may start the bounded recovery-only path.
If cleanup also fails, record both causes; a successful exit code cannot erase it.

Do not let one known book failure stop unrelated healthy markets once existing
scope/risk gates support that isolation. Never infer isolated ownership from a
market label on an unknown order. Unknown executions retain reservations and
must not be resubmitted blindly. Inventory is never dropped from managed scope
because discovery/ranking retires a market.

After any restart, recover the same financial ledger, pending intent/inbox and
private-epoch gaps. Preserve D-024 loss receipts, D-021 window ratchets, D-031
exposure and all unresolved orders. Do not choose a new launch boundary, reset
six-hour windows, fabricate fills or release reservations from absence.
Recovery-only allows no new entries. Any eventual cancellation/reduction still
requires approved mutation authority, verified ownership and current exit inputs;
without them it is read-only and blocked. Routine same-session recovery may
resume only within a future explicitly approved auto-resume policy and fresh
proof. Cold recovery defaults to paused pending that separate approval.

Proposed failure limits: 10/20/40/60-second restart delays with bounded jitter;
three automatic relaunches per incident and at most three in a rolling ten-minute
window. Persist attempts before spawn, including failed launches. Only ten
minutes of demonstrably healthy progress closes an incident; mere uptime,
subscription ACK or one successful read does not reset it. Supervisor restart
retains the budget. Use monotonic deadlines within one boot; persisted UTC
cooldowns require validated clock continuity, otherwise hold for attention.
Existing component exhaustion latches are never silently cleared by this reset.
The runtime adapter must carry exhausted-retry holds and unexpired shared 429
cooldowns across eligible restarts. Losing that state is a recovery blocker,
not permission to refill API tokens. Recreate source freshness and quota leases
from current validated evidence; join any surviving local transport workers
before replacement. S1 represents these as explicit blockers only; durable
runtime integration belongs to S2 and may not weaken D-036/D-039 contracts.

Proposed heartbeat cadence: two seconds, with 30 seconds without advancing valid
progress treated as unresponsive. Use event-loop progress plus deadlines for
actually outstanding work; quiet markets and an intentionally idle writer are
healthy. A separate thread emitting heartbeats cannot certify a stalled loop.
Allow a bounded 60-second startup with explicit stages; expiry requests graceful
stop. These are detection thresholds, not venue-risk or flattening guarantees.

Proposed graceful-stop budget: 60 seconds for the offline harness. On expiry,
keep the execution lease/child ownership, report attention and continue observing
the existing child; do not spawn a replacement or automatically force-kill it.
A production drain/exit deadline and any forced termination require a separate
approved policy. A stuck native process cannot be promised automatic repair.
Power loss cannot be handled while the laptop is off; persistent venue protection
must be designed and verified separately before live use.

## Failure handling, observability and resource bounds

Reuse D-033 safe event/reason logging. Each process owns one bounded diagnostic
sink with separate files; two processes must not share a rotating file writer.
Correlate parent/child by generation and child ID. Close child diagnostics after
runtime finalizers, REST workers and ledger drain; no supervisor timeout may
abandon D-048 teardown and claim it completed. Always expose process state,
entry eligibility, unresolved inventory status and alert delivery separately.

Use a bounded local status channel, at most one coalesced heartbeat and 64
control messages of at most 8 KiB each. Durable stop is not a droppable message.
Store only bounded attempt history/current control state; rotate diagnostics.
One parent scheduling loop, one child, no per-market supervision threads. Parent
health checks use local evidence only. Future notification delivery uses a
bounded queue and records delivery failure; selecting/connecting a remote alert
channel needs operator direction. Local status must remain usable without it.

If the parent dies while the child lives, the child loses its control heartbeat,
blocks entries and requests graceful shutdown while retaining ownership. A new
parent holds rather than adopting that process by PID; it may launch only after
old-child exit/lease release is established. Cross-session control and process
handle behavior must be tested on native Windows before this becomes operational.

## Implementation phases and acceptance

**S1: offline policy/control foundation.** Proposed next Sol assignment after
operator approval: immutable contracts and pure policy, transactional control
store and fake process/clock tests. No runtime wiring, real child launcher,
credentials, services, task installation or bot configuration changes. S1 can
proceed independently of the pending D-048 review. Use temporary directories.

Acceptance: manual stop during backoff/spawn; stale result after rearm; crash
before/after attempt commit; corrupt/missing state; restart-budget persistence;
clock reversal; clean/refused/exhausted/unknown outcomes; slow healthy work;
heartbeat alive but useful work stalled; child still alive after shutdown
timeout; concurrent stop/start decisions. All fake entry/live gates stay false.
Benchmark pure decisions at 30/120 synthetic markets: no per-market task, p99
decision <5 ms, additional peak Python memory <10 MiB; measure 60-second idle
parent-loop CPU <1% of one core. These are targets, not measured claims.

**S2: native process lifecycle with inert children.** After S1 review and D-048
clearance, implement native locks/handles and bounded IPC; use only an inert
test child and later injected execution-disabled runtime fixtures. Prove one
child across concurrent controllers/checkouts, stop/spawn races, parent death,
sleep/resume, hung child, repeated cancellation and durable fill drain. No live
entry path. Verify at most one parent health wake/second plus explicit events,
30/120-market event-loop p99 <50 ms and additional memory <40 MiB. Preserve
existing continuity/history resource budgets and shared API limits.

**S3: production integration and host recovery.** Separately approved after
D-044 venue handoff/opening account/cash work and production mutation/exit proof.
Connect real runtime outcome mapping, risk gates and optional Windows task;
approve auto-resume scope, boot behavior, timing thresholds and alert destination.
Recheck current official venue contracts for any order protection or API changes.
Installation and first live run remain separate operator actions. Neither S1
nor S2 pretends to solve missing venue guarantees.

Each implementation phase needs focused regressions, native ownership tests
where applicable, resource checks, full relevant suite and disabled preflight,
then independent Astra review under D-049. This design session ran only the six
source-reference tests above and documentation checks; no Kalshi source changed
and the earlier 804-test implementation result was not rerun.

## Handoff

S1 and D-048 reviews are complete. Follow the
[D-055 S2 proposal](DESIGN_WINDOWS_SUPERVISOR_S2.md): stop for operator approval
and the Sol switch, with S2A recommended first. Timing/restart values are approved
only as offline S1 policy, not deployed settings; S2's added fixture settings,
implementation and future live auto-resume remain unapproved.
