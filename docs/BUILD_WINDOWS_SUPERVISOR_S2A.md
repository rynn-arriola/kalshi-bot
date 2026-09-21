# D-056 — Native Windows supervisor S2A

Review status: [independent Astra review](REVIEW_D056_ASTRA.md) requires R1-R8
corrections and does not clear S2A. The implementation measurements below are
historical Sol evidence; the review qualifies their scope and reproduces faults
outside the existing test coverage. D-057 [implements the corrections](BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md)
and awaits independent review. S2B remains blocked.

Date: September 21, 2026. Native Windows; execution disabled. Implements only
S2A from the approved [D-055 design](DESIGN_WINDOWS_SUPERVISOR_S2.md). This is
Sol implementation evidence and must receive independent Astra review before any
separately assigned S2B work.

## Implemented boundary

- Protected account-scoped parent/child presence objects, stop latch and
  OS-thread-owned transaction mutex. Existing object owner and exact user/System
  DACL are checked; permissive squatting fails closed.
- Store schema 4/control schema 3 with explicit fresh-fixture initialization,
  open-existing/read-only modes, parent sessions and atomic native reservation,
  created, bound, exited and orphan-release evidence.
- Strict immutable 8,192-byte JSON frames over one local-only overlapped named
  pipe. Control queues are bounded at 64; status/pulse use one coalesced slot;
  duplicate fields, nonfinite values, replay, gaps, overflow, wrong peer and
  partial/closed transport fail closed.
- One fixed inert child launched with a retained real interpreter process handle,
  explicit source/config fingerprints, minimal environment, explicit inherited
  child-presence/stop/parent handles and no arbitrary command/module loading.
- One parent host with durable-before-spawn reservation, current-state admission,
  activity-driven IPC plus one-second safety timing, exact retained exit evidence,
  bounded restart accounting, graceful-only stop and lease-proven cold orphan
  release. Parent/session loss, abandoned control, IPC and power changes disarm.

No production start CLI, runtime adapter, financial-ledger transfer, recovery
fence, service/task wrapper, bot configuration/runtime change, credentials,
network/account access, order operation, deployment or live authority was added.
S2B is deliberately rejected by the protocol and remains a separate phase.

## Native acceptance and resources

Focused S1/S2 tests cover immutable framing, malformed/fragmented input, exact
sequences, explicit store creation, local safety/orphan policy, new-session
disarm, duplicate parents, cross-process role exclusion, abandoned mutex,
permissive DACL squatting, pipe/stop crossing, normal health/exit, persisted crash
budget, admitted hung-child non-replacement, parent death and cold orphan release.

The fixed resource fixture ran 60.002 seconds idle and 100 exact child cycles:

| Measure | Result | Target |
|---|---:|---:|
| Parent CPU | 0.990% of one core | <1% |
| Child CPU | 0.651% of one core | reported separately |
| Event-loop delay p99 | 16.372 ms | <50 ms |
| Policy latency p99 | 7.491 ms | reported |
| Added working set | 34,140,160 bytes | <40 MiB |
| Maximum message backlog | 1 | bounded |
| 100-cycle handle delta | -2 | no positive growth |
| Retained supervisor threads | 0 | 0 |

The harness warms managed executor paths before the cycle baseline and reports
its framework cleanup separately, so lazy executor allocation is not mislabeled
as a supervisor leak. Test fixtures are software checks, not paper trading,
profit evidence or live readiness.

## Verification

- Focused S1/S2 suite: **81 tests passed in 12.239 seconds**; the intentional
  crash-budget regression also passed **10/10** repeated native runs.
- Exact complete suite: **885 tests passed in 88.276 seconds**.
- Native disabled preflight returned expected exit 2 with `live_ready=false`,
  `creates_files=false`, `credentials_accessed=false` and
  `network_accessed=false`.
- Byte compilation, `git diff --check`, local-link and sensitive-content checks
  are required before publication.

Real sleep/reboot remains unverified and requires separate approval. Astra must
review the complete S2A diff for ownership, spawn/STOP races, cancellation,
security, IPC closure and incorrect assumptions before S2B can be considered.
