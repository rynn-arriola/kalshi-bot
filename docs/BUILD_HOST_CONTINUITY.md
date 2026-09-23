# D-094: independent host and stopped-account reconciliation

## Scope

The operator approved repair of the remaining host/reconciliation blockers on
2026-09-23. No trading restart, venue mutation, service, scheduled task, startup
entry or power-setting change occurred. D-093 discovery and monetary limits are
unchanged.

## Host change

`Start-LiquidityBot.ps1 -Live` now invokes a fixed `supervised_live launch`
command. It launches the existing supervisor with native Windows
`DETACHED_PROCESS`, `CREATE_NEW_PROCESS_GROUP` and `CREATE_BREAKAWAY_FROM_JOB`.
The OS must allow breakaway; creation failure is reported, with no fallback to
a terminal-dependent host. No shell command interpolation, inherited terminal
handles or machine-wide setting changes are used. `-Foreground` retains the
explicit diagnostic mode. The supervisor's exact-child ownership, parent-death
watch, shutdown, recovery fence and restart budgets are unchanged.

The launcher waits at most ten seconds for its unique atomic host receipt in
`data/trader/supervisor/launches/<uuid>.json`. `HOST_STARTED` means the supervisor
acknowledged startup, **not** that market/account readiness or trading succeeded.
Early exit is blocked; timeout is unknown and requires status inspection before
any retry. It never kills/relaunches an uncertain host. Host receipt failure
joins the owned supervisor through its existing graceful cleanup. Parent and
child diagnostics remain in the existing bounded log sinks.

`Get-LiquidityBotStatus.ps1` probes protected parent/child lease presence without
PID adoption, starting a worker or querying Kalshi. Top-level states are
`STOPPED`, `RUNNING_UNVERIFIED`, `TRANSITION_OR_ORPHAN`, or `UNKNOWN` on probe
failure. Saved control/runtime payloads remain historical; their presence never
proves current health or flatness. The runtime file's age is included, and
oversized/unreadable saved telemetry is not trusted. A live process/heartbeat,
fresh runtime/account/source evidence and readiness gates must still be checked
after any authorized launch.

The laptop must stay awake and online. Independence from a launching terminal
does not survive logout, reboot, power loss, supervisor termination or an OS job
that prohibits breakaway. No automatic boot recovery was installed.

## Verification

Native inert acceptance creates a kill-on-close Windows job, launches the
supervisor outside that job, then exits the launching process. The supervisor
and inert child subsequently reach healthy state and stop through the ordinary
durable control path. It uses a unique fixture scope and no credentials, venue
calls or production profile. Existing parent-death behavior remains tested.
Additional regressions cover creation denial/no fallback, explicit live gating,
timeout/no forced kill, receipt identity, malformed identity, receipt-write
failure cleanup, protected presence and saved-healthy/dead-process reporting.
Final suite and documentation-check counts are recorded in [STATUS](../STATUS.md).

Microsoft's [process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
define the console/job behavior. The original cause of the earlier host exit
remains inferred, not proved; see the
[dated investigation](INVESTIGATION_LIVE_EXIT_2026-09-22.md).

## Account evidence and exact local repair

VERIFIED by authenticated **GET only** at 2026-09-23 05:01:38 UTC (01:01 Eastern):

- All 28 locally resting order identities returned exact canceled records with
  zero filled quantity. Absence from an order list was not used as cancellation.
- Complete bounded primary-account enumerations returned zero resting orders
  and zero nonzero-position rows.
- Cutoff-aware fill history from the first intent (2026-09-22 23:09:18.234813
  UTC) through 05:01:38.464391 UTC returned zero fills in one page. This is a
  dated enumeration, not an atomic account barrier or perpetual history proof.

While holding parent, child and account-writer exclusion leases, consistent
SQLite backups of ledger and control databases passed integrity checks under
`data/trader/d094-backup-20260923T050138Z/`. The existing `record_order` validator
imported the 28 terminal records in one transaction, checking exact intent terms,
versions and fill agreement. Current counts: 68 terminal and 10 previously
aborted intents; no acknowledged intents remain. Fill, inventory, realized P&L,
risk windows, accounting, opening checkpoint and history/private-epoch tables
were compared before/after and remained unchanged. Capacity credits were released
through the existing terminal-order path, not a manual reset.

Existing owner-lost/orphan-released/stop events then cleared only the proven
dead child reservation. Control is disarmed, stop-latched, child absent; recovery
fences and financial history were not cleared. The ignored evidence JSON and
one-time repair script remain under `data/trader/`; never publish their private
order identities. Backups are recovery artifacts, not files to blindly restore
over later financial activity.

No trading process was started. This closes the named host and manual-cancellation
repair work, not live acceptance of D-093 or profitability. Next launch still
requires explicit authority, current reviewed inputs and normal readiness gates.
