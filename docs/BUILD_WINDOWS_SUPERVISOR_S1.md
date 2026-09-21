# D-051 — Native Windows supervisor S1

Review status: [independent Astra review](REVIEW_D051_ASTRA.md) required R1-R7
fixes before S2. D-052 [implements those fixes](BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md)
and awaits Astra re-review. The original implementation evidence below remains
historical evidence for `7b8d6cd`; use the D-052 report for corrected behavior
and current verification.

Date: September 21, 2026. Native Windows; execution disabled. Implements the
approved S1 policy/control foundation from the
[D-050 design](DESIGN_WINDOWS_SUPERVISOR.md). No process was spawned, no
credential or network was accessed, and no runtime, service, task, order or
live configuration was changed.

## Behavior

`src/kalshi_bot/supervision.py` provides immutable supervisor contracts and a
pure state transition policy. A supervisor can be disarmed, starting,
recovering, healthy, degraded, stopping, in backoff or waiting for attention.
It can only request a **recovery-only** child; `entry_allowed` and `live_ready`
are constant false in state and decisions.

The policy persists stop/generation intent, rejects stale children, reserves an
attempt before requesting a spawn, and applies bounded 10/20/40/60-second
backoff. Three incident relaunches or three launches in a rolling ten-minute
window require attention. Ten minutes of useful healthy progress resets the
incident count. Heartbeats alone cannot hide a 30-second useful-progress stall;
an explicit work deadline can account for legitimate slow work. Clock reversal,
integrity failures, unknown outcomes, retry exhaustion, incomplete cleanup or
unresolved work fail closed. Startup/shutdown deadlines never imply a force kill
or restart.

`src/kalshi_bot/supervisor_store.py` owns a separate transactional SQLite
control journal. It uses one singleton control record, a bounded event history,
WAL and full synchronization. Each state transition and event append is atomic;
the start-attempt reservation commits before its spawn request is returned.
Missing storage initializes disarmed, while corrupt, incompatible or
wrong-scope existing storage is refused.

No per-market task or queue was introduced. The policy and journal do not
import the runtime, execution, credentials, network or order paths.

## Verification

- Supervisor regressions: **32 tests in 0.190 seconds, all passed**. They cover
  stop/arm races, stale generations, launch reservation, rollback, retry limits,
  cleanup proof, useful-progress stalls, deadlines, clock reversal, corrupt or
  mismatched storage and bounded history. The focused module also passed 10/10
  repeated runs.
- Exact full suite: **836 tests in 79.646 seconds, all passed**.
- Native disabled preflight: expected exit 2, `live_ready=false`, no files,
  credentials or network accessed.
- Offline 5,000-decision fixtures at 30 and 120 synthetic market labels stayed
  below 0.094 ms p99 and 169 KiB peak, with no per-market tasks and all live
  authority false.
- A 60-second idle-parent fixture woke 60 times and measured 0.0 CPU seconds on
  this Windows timer, below the one-percent-of-one-core ceiling.

These are local engineering bounds, not live process, market or account proof.

## Handoff

Stop for independent Astra review under D-049. Review the state machine,
transaction boundaries, concurrent stop/arm behavior, generation checks,
cleanup evidence, retry accounting, clock handling and absence of live
authority. D-048's separate continuity review remains pending. S2 process
handles, IPC, runtime integration and any installation require both review gates
and a separate assignment; no live auto-resume is approved.
