# D-055 — S2 native Windows lifecycle design

September 21, 2026. **Design only; implementation awaits operator approval.**
Extends [D-050](DESIGN_WINDOWS_SUPERVISOR.md), not a second recovery policy.
[S1](REVIEW_D054_ASTRA.md) and [D-048](REVIEW_D048_ASTRA.md) reviews are clear.
The proposed first Sol assignment is **S2A only**, followed by Astra review;
S2B needs a separate assignment. No production launcher, credentials, venue
connections, orders, services/tasks, laptop restart or live auto-resume.

## 1. Source findings and boundary

Inspected current `ebb9892` source and preserved the uncommitted review docs:

- `windows.py`: `WindowsLease` excludes by kernel-object presence; it does not
  acquire a reusable transaction mutex. `WindowsStopEvent` is sticky and opens
  an existing object for requests. Neither provides explicit S2 access control,
  inherited ownership, IPC or parent-death handling.
- `supervision.py` / `supervisor_store.py`: reviewed deterministic policy and
  bounded journal; separate child/control generations; actions follow commit.
  Store v3 / state v2 have no parent-session or native ownership provenance.
  Construction can create an empty store; S2 must distinguish initialization
  from opening existing state. Default clock evidence is not an OS boot ID.
- `runtime.py`: reviewed retained shutdown and connection finalizers must be
  joined, not abandoned at a process deadline. `running=True` alone does not
  prove healthy readers, progress, quota or durable ownership.
- `rest.py`, `quota.py`, `quota_supervisor.py`: shared budget/cooldown, expiring
  quota proof and retry exhaustion exist, but are process-local. The supervisor
  cannot reconstruct safe retry permissions merely from an exit code.
- `cli.py` remains credential-free `policy`/`preflight`; `BotConfig` rejects live
  activation. Existing Windows tests cover duplicate leases/stop events, not
  the proposed parent/child ownership and IPC protocol.

S2A launches only a fixed inert fixture. S2B adds an explicitly injected offline
`RecoveryRuntime` fixture with its own disposable ledger and fake reads/readers.
Neither loads keys or uses `readonly_reader_factory` with a real signer.
No change to strategy, capital, entry size, resting-order cap, loss windows,
percentage entry reducer, market selection or inventory policy.

## 2. Ownership and modules

One parent owns lifecycle/control; one child owns fixture runtime and ledger.
Controller invocations submit durable arm/stop or inspect local state. They
cannot launch children themselves or open the financial ledger for writes.

| Module | Interface/responsibility |
|---|---|
| `supervision.py` | Keep S1 policy; add the narrowly typed local safety/orphan events below |
| `supervisor_store.py` | Transactional parent-session, reservation and recovery-fence evidence; explicit create/open modes |
| `windows.py` | Retain existing primitive contracts; add secure S2 role lease, control mutex, stop latch and handle ownership |
| `windows_ipc.py` | Local-only overlapped pipe, bounded framing and retained I/O close; no policy or ledger |
| `supervisor_protocol.py` | Strict immutable envelopes, decoder and allowed message/state transitions |
| `process_supervisor.py` | `SupervisorHost.run()`, retained shutdown, timer, policy actions, owned child process |
| `supervisor_control.py` | `initialize_fixture`, `arm(expected_generation)`, `stop`, read-only `inspect`; dedicated control worker |
| `supervised_runtime.py` | S2B `RuntimeAdapter`: injected startup, useful-progress snapshot, retained stop/join and recovery fence |
| `tests/fixtures/supervisor_child.py` | Fixed S2A child entry; explicit finite scenarios, no arbitrary module/command loading |
| `tests/test_bot_supervisor_native.py`, `test_bot_supervisor_ipc.py`, `test_bot_supervised_runtime.py` | Native lifecycle, protocol/fault and S2B integration checks |
| `scripts/benchmark_supervisor_native.py` | Disposable inert-process CPU/memory/latency/handle fixture; never account access |

Public contract sketches (names may be adapted consistently, semantics may not):

- `ScopeSpec(environment, account_scope, approved_user_sid, control_root)`:
  opaque account label, not key ID; immutable validated absolute local path.
  Account-wide role names exclude checkout path, PID, subaccount and market.
  All subaccounts of this bot account share exclusion. S2 accepts only unique
  `test-*` scopes under an explicit disposable fixture root; no production map.
- `ControlOwner.submit(command) -> await ControlReceipt(revision, decision)`:
  one dedicated thread owns its SQLite connection and transaction mutex.
  Controllers use the same serialization contract, not the parent's queue.
- `OwnedChild.poll_exit() -> None | ExitEvidence` wraps the retained `Popen`
  object, never PID lookup; `request_stop()` only signals the owned latch.
  Exit evidence is constructed locally, never accepted from child JSON.
- `PipeEndpoint.send_control(frame)`, `publish_status(snapshot)`,
  `receive()`, `close_and_join()`: bounded buffers and retained native I/O.
- `RuntimeAdapter.start(context)`, `health_snapshot()`, `request_stop(reason)`,
  `join() -> CleanupEvidence`: context cannot contain execution authority.

These are additions, not a rewrite of financial/account owners. No direct
SQLite access from the event loop, per-market supervision tasks or parent REST.

## 3. Windows identity and access control

Use distinct global, account-scoped names for parent presence, child presence,
the transaction mutex and the stop event. Prefixes/digests are deterministic
from the canonical scope; never silently fall back to checkout/session-local
names when access is denied. Namespace squatting or unexpected object type is
a refusal, not permission to use another name.

S2 objects/files have explicit protected access limited to the approved user
and LocalSystem. Inspect existing owner/DACL/type before trusting an object;
never overwrite somebody else's security descriptor. Reject remote shares,
OneDrive roots and unexpected reparse-path redirection. Same-user malicious
code or administrators are outside the isolation guarantee; this is not a
sandbox. Default pipe security is too broad for this design. See Microsoft's
[pipe security contract](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights).

The transaction mutex uses real wait/acquire/release on the **same OS thread**.
`WAIT_ABANDONED` acquires ownership but means the protected operation may be
incomplete: inspect durable state and install an attention hold, never continue
the interrupted spawn automatically. Timeout/access failure denies arm/spawn;
STOP still attempts the independent event. Release only if acquired. This
follows [wait semantics](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)
and [thread-owned release](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-releasemutex).

The child presence lease deliberately remains a **presence lease**, not a
thread-owned mutex. Parent acquires it before process creation and explicitly
inherits a duplicate into the child. Thus ownership already exists during
spawn and survives parent death, including before the child's Python bootstrap.
Parent retains its copy until confirmed exit; child retains its copy until
process termination, beyond runtime/writer/diagnostic cleanup. Do not inherit
the parent lease or transaction mutex. A crash closes process handles; the
object persists while either authorized holder remains. These are documented
[mutex handle-lifetime semantics](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw).
The child's lifetime handle must not have an early context-manager, garbage-
collection or `atexit` close: let the OS close it at process termination. Include
a test that delays interpreter/thread finalization after runtime cleanup.

Keep the child stop-latch handle and a real parent-process handle with
SYNCHRONIZE and PROCESS_QUERY_LIMITED_INFORMATION rights
in the explicit inheritance list as well. Obtain the latter by duplicating the
parent process handle, not by trusting a PID supplied by another process.
Use [DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)
with minimal rights. Native tests must prove inheritance and exact close order.

## 4. Control store and launch ordering

S2 proposes store schema **4** / control-state schema **3** for new fixture
stores, with strict field validation. Refuse older schemas without modifying
them; no migration/deletion of existing journals or ledgers in this assignment.
`open_existing` must not create an absent database. `initialize_fixture` is
explicit, childless, disarmed and restricted to a fresh test root.

Add a singleton parent session ID and one bounded native reservation linked to
the same child ID/generation as S1: session ID, build/config digests, creation
stage and diagnostic PID if returned. No PID grants authority. Session changes,
control state and evidence changes share one transaction/revision. Keep the
existing bounded event history; no append-only unbounded process table.

Proposed policy extensions, covered by pure tests before integration:

- `LOCAL_SAFETY_FAULT(reason)`: trusted local host evidence only. Reasons include
  owner loss, abandoned control operation, IPC failure, suspend/resume and
  recovery-fence uncertainty. Disarm/fence the current generation, preserve
  attempts/holds/child reservation, enter attention and request graceful stop.
  Never emulate this with a fictitious child result. Child wire messages cannot
  directly invoke it; the host validates and classifies evidence.
- `ORPHAN_RELEASED`: a local, scope/revision/child-bound lease-exclusion receipt
  clears an orphan reservation after the cold-start procedure below. It cannot
  arm, reset attempts/holds, assert clean cleanup or authorize a spawn. Record
  lease-based exclusion separately from native observed process exit.

Normal launch, all command/file validation completed before the critical span:

1. Acquire parent presence and open existing control state; a new parent session
   never resumes a prior arm automatically. Explicit fixture ARM is required.
2. On a due S1 action, control worker acquires transaction mutex; re-read state,
   current session/revision, stop latch, fingerprints and holds. Acquire child
   presence lease while still serialized. If it exists, hold; do not spawn.
3. Apply `START_REQUESTED` and commit attempt/reservation **before** process
   creation. Keep the mutex across the synchronous `Popen` call, but not across
   IPC, handshake, runtime initialization or any await. Process creation is not
   assumed instantly cancellable; the independent stop latch remains available.
4. Spawn the fixed interpreter/fixture entry, `shell=False`, `close_fds=True`,
   `CREATE_NO_WINDOW`, explicit cwd and minimal allowlisted environment. Pin
   resolved source/config digests in the arm; reject drift before launch and in
   child HELLO. Do not use PATH lookup, arbitrary commands, user module names,
   `.env`, PYTHONPATH or inherited credential environment variables.
   Reject actual imported source paths/digests that differ from the pinned
   checkout, including an editable install resolving to another checkout.
5. Retain `Popen`, bind returned native diagnostics to the durable reservation,
   then release the mutex. `CHILD_STARTED` means a native child was created, not
   healthy or admitted. Parse HELLO; send a bootstrap admission grant only after
   a serialized current-generation/stop recheck. Child independently reads an
   existing read-only control view under the same mutex and checks its inherited
   stop latch before accepting admission. Admission carries no trading authority.
6. STOP that linearizes before reservation prevents spawn; STOP after creation
   revokes admission/requests shutdown. If STOP follows child admission, the child
   must service it immediately; starting and stopping are not an atomic OS act.

Only a provable no-process-created failure may become `SPAWN_FAILED`. Failure
after creation, losing a commit acknowledgement, or an uncertain constructor
outcome retains the reservation/lease and requests stop. Never close ownership
and retry because a local exception occurred. All actions returned by S1 are
honored even when the associated payload has `stale=true`.

The documented Python
[Windows launch options](https://docs.python.org/3.14/library/subprocess.html)
support hidden processes and explicit inherited-handle lists. Serialize all
process creation in this host, mark only duplicates inheritable, and close/reset
temporary duplicates in `finally`. Do not access private `Popen` attributes.
Standard streams go to DEVNULL; structured per-process diagnostics are separate.

## 5. Bounded IPC and useful progress

Recommend one randomly named, local-only duplex Windows pipe per child. Parent
creates the first/only instance before spawn, with explicit DACL,
`FILE_FLAG_FIRST_PIPE_INSTANCE`, `FILE_FLAG_OVERLAPPED` and
`PIPE_REJECT_REMOTE_CLIENTS`. Use byte mode with a four-byte unsigned length
prefix and UTF-8 JSON body of **1..8192 bytes**. Reject oversized frames before
allocation; reject duplicate JSON keys, nonfinite numbers, unknown fields,
wrong types/version/scope/session/child/generation and excess nesting. No pickle,
untrusted imports or unbounded JSON/error logging. See
[CreateNamedPipeW](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createnamedpipew).

Bind the connected client to the actual spawned process using
[GetNamedPipeClientProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid)
and the retained process's still-running state, checked before and after peer
validation. Child compares server PID with the identity queried from its
inherited parent handle and also checks that handle for exit. A random
pipe name and fresh launch nonce prevent accidental cross-session binding, but
are not substitutes for access control and native process ownership.

Envelope fields: `version`, `scope_digest`, `parent_session`, `child_id`,
`child_generation`, `kind`, per-lane `sequence`, `sent_monotonic_ns`, `payload`.
Use separate sequence lanes for retained control messages and coalesced status;
coalescing never creates a false missing-control-message diagnosis.

| Direction | Messages | Rule |
|---|---|---|
| Child -> parent | HELLO, STATUS, RESULT; S2B FENCE | HELLO matches pinned build; STATUS is health only; RESULT is cleanup evidence, never process-exit proof |
| Parent -> child | ADMIT, PULSE, STOP_HINT; S2B FENCE_ACK | PULSE/ADMIT carry committed control generation/revision; STOP_HINT supplements the independent event |

At most 64 retained control frames and one replaceable STATUS/PULSE slot per
direction; at most one native read and one native write outstanding per process.
No coalescing of results, fences or stop decisions. Overflow/malformed frames
install an IPC hold and signal stop, not a retry storm. Cap accepted frames at
32/second with a 64-frame burst; validate retained controls in order. A peer
that exceeds the cap fails closed. No unbounded asyncio callback queue: the I/O
worker schedules at most one outstanding event-loop drain notification.

One dedicated overlapped-I/O worker per process owns buffers/OVERLAPPEDs and
native stop/parent-death notifications. On close, stop accepting new operations,
cancel pending I/O and wait for every completion before freeing buffers/handles
or joining the worker. Cancellation is a request, not proof of completion;
[CancelIoEx explicitly requires retaining pending structures](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelioex).
No blocking `ReadFile`, `FlushFileBuffers`, process wait or SQLite operation on
the asyncio loop. Native bindings use complete ctypes signatures and checked
return codes; no ignored close/cancel failure or private asyncio APIs.

Health originates from the child event loop, every two seconds, and includes
phase, advancing useful-progress sequence, bounded work remaining and allowlisted
component blockers. An I/O thread must never invent progress. A quiet healthy
event loop counts as progressing; merely having a reader thread alive does not.
Parent emits PULSE on its own serviced event loop, not its I/O worker.

For this offline phase propose: connect/HELLO timeout 10 s within S1's total
60 s startup, STATUS/PULSE maximum transit age 4 s, parent heartbeat loss 6 s.
Use same-boot `monotonic_ns` for age, not child wall time; Python documents the
[monotonic clock as shared across processes](https://docs.python.org/3/library/time.html#time.monotonic).
Negative age, a clock fault or expired status cannot refresh health. Convert
bounded remaining-work time at ingress to parent control time, subtract transit
age, and retain S1's prior-state deadline checks. Keep S1's 30 s progress and
60 s shutdown budgets unchanged. These are fixture settings, not approved live
timing or maximum-loss guarantees.

## 6. Stop, process death and cold recovery

`stop()` persists S1 STOP under the mutex, then signals the scope's sticky event.
It increments generation even when already stopping. On mutex/database failure,
still signal the existing event and report **durable disarm unconfirmed**; never
claim a successful persistent stop. No event is created by an absent-target stop.
Parent/child latch the event immediately; only an explicit fresh ARM after
childless verification may reset it. IPC backlog cannot delay the signal path.
The S2 event owner may reopen a validated inherited-era event after parent loss,
without resetting it; do not change the existing `WindowsStopEvent` constructor's
duplicate-owner contract to accomplish this.

Child RESULT is retained once and validated, but parent waits for native process
exit through the owned `Popen` before submitting `CHILD_RESULT(process_exited=True)`.
Poll exit on the shared one-second health tick, not a separate busy loop.
Contradictory result/exit evidence enters attention. No RESULT means unexpected
death, not CLEAN; missing cleanup stays unknown. A RESULT while the process
hangs retains ownership through shutdown timeout. Never terminate by PID/name,
auto-force-kill, use a kill-on-close job, or release the child lease early.

Parent cancellation is a retained stop-and-join operation: persist disarm,
signal child, await process exit and all IPC/control workers, then release
parent ownership. At 60 s report attention but keep observing/owning a stuck
child; cancellation or a timeout is not permission to spawn another. Inert
tests may force-terminate only their own registered fixture handles for cleanup,
never through the operational supervisor API or a process-name search.

On parent process death, its inherited process handle signals in the child;
pipe failure or missing PULSE also revokes admission and requests retained child
shutdown. The I/O worker can set a fail-closed latch even if the event loop is
stalled, but cannot claim runtime cleanup. A permanently hung child remains
owned and needs operator attention; no self-repair promise covers that case.

A replacement parent acquires only the parent lease, records a new session and
holds prior armed/nonterminal state for attention. Do not adopt an old process
by PID, resume old clocks/leases, refund attempts or clear component holds.
If old child presence remains, signal its existing stop latch and wait. When
absent, acquire exclusive child presence under the control mutex, fence the old
generation and use `ORPHAN_RELEASED` to clear just the old reservation. Keep the
probe lease until that commit completes. Under the inherited-lifetime contract,
this proves no conforming child remains, not clean financial recovery or an
observed exit code. On ambiguous access/type/schema/commit, retain attention.
Explicit new ARM is still required. Test the pre-Python-bootstrap crash window.

Register native suspend/resume callbacks in both processes; callbacks only set
a sticky invalidation flag and wake the owner. The first resumed operation
processes it before status/grant/launch work, requests stop and holds for
attention. Registration failure blocks the native harness. Microsoft supports
[callback registration without a window](https://learn.microsoft.com/en-us/windows/win32/api/powerbase/nf-powerbase-powerregistersuspendresumenotification).
Existing wall/monotonic checks remain an additional guard, not proof that sleep
did not occur. Reboot always creates a new parent session with cold-recovery
rules. Never suspend/reboot the user's laptop as an automatic test.

## 7. S2B runtime and recovery-fence contract

S2A's inert child has no quota or financial state. S2B adds only a fixed offline
adapter; no dynamic factory loading and no real read/mutation client. The child
opens its fixture writer/read owners, starts the existing runtime, and maps
reader exhaustion, writer/engine/logging faults and quota holds into bounded
typed health. No new retry controller inside the adapter.

Shutdown ordering: revoke admission; request `RecoveryRuntime.stop()`; join its
retained connection/runtime finalizers; drain/join outstanding read workers;
close/join the ledger writer; capture cleanup evidence; flush/close diagnostics;
send RESULT if IPC works; finish IPC and terminate while retaining child lease.
Any failed step stays explicit. RESULT cannot claim cleanup before all required
owners finish; parent requires actual exit as well. Parent never writes fills.

Add one bounded `RecoveryFence` record in the control journal, written only by
the parent from validated FENCE messages: child/session identity, increasing
fence revision, up to 32 typed component-exhaustion holds, up to 8 named cooldown
deadlines in parent control time, and terminal-checkpoint completeness. ACK only
after commit. Child imposes a new restriction locally immediately; uncertainty
about its durable ACK does not allow continued work or restart permission.
Bounds overflow is a hold, not truncation. Removal needs an explicit scoped
resolution command and current revision, never a heartbeat or ARM side effect.

An active child may have unsent restrictions when it crashes. Therefore a last
heartbeat/checkpoint is **not** a complete fence: unexpected S2B death or missing
terminal durable checkpoint adds `recovery_fence_unknown` and blocks automatic
fixture-runtime relaunch. S2A inert crash tests can still exercise S1's bounded
automatic restarts. A clean known S2B checkpoint can preserve permitted recovery
within S1 limits; complete here means only restriction transfer, not account
proof. Do not weaken this rule to simulate automatic recovery success.

Restored exhausted components remain blocked; known shared 429 cooldowns cannot
shorten across restart. Untrusted cross-session time adds a hold instead of
declaring expiry. Tokens restart at zero; quota grants, read leases, current
snapshots, source freshness and entry permission are never restored from disk.
The child must load/apply its validated fence before any fake request. Prove
this with adversarial fake quotas and an abrupt child death before FENCE_ACK.
No network API research or new numerical venue budget is implied by this design.

## 8. Resource bounds and failure acceptance

Parent: one asyncio loop, one control/store thread, one IPC worker and one
bounded diagnostic worker; child adds one control-view worker and one IPC worker
to the existing runtime/writer/read/diagnostic owners. Native callbacks only
latch/signal. No per-market processes/threads or unbounded executor submissions.
Control mailbox limit 64; safety flags/stop event are out of band. Parent health
timer wakes at most once/second plus explicit events; no rearming per tick.
Proposed mutex acquisition bound 5 s; SQLite busy timeout remains bounded.
Queue saturation, persistence failure or unhealthy diagnostics blocks starts
and attempts graceful stop; never retry an uncertain spawn/transaction blindly.

Measure at 30/120 synthetic markets: event-loop p99 <50 ms; added supervisor/
IPC memory <40 MiB against the same unsupervised fixture; parent 60-second idle
CPU <1% of one core with real policy/journal/IPC work. Report parent and child
CPU separately, Python traced memory plus native working-set/handle/thread
deltas, message backlog, wake count and event-to-policy latency. Run 100 child
cycles and verify handles/tasks return to baseline, leases vanish and retained
journal rows/buffers/logs remain bounded. These are targets, not measurements.

Required deterministic barriers and native acceptance cases:

- Two parents and two controllers from different checkout/cwd paths: one parent,
  one child; same account/subaccount variants cannot bypass exclusion.
- STOP before reservation, during process creation, before HELLO/admission,
  during BACKOFF, and repeatedly during teardown. A stale ARM never wins.
- Crash before/after reservation commit, before child bootstrap, after native
  creation/before bind, and during each acknowledgement. No duplicate child or
  refunded attempt; orphan release never marks cleanup clean.
- Parent death with healthy/stalled child; child death before/after RESULT;
  hung cleanup beyond 60 s; IPC EOF/partial/oversized/replayed/wrong-scope frames;
  control/status flooding and nonreading peer. STOP still reaches its latch.
- Native ACL denial/squatting/type mismatch, duplicate role object, wrong peer,
  unexpected handle inheritance, abandoned mutex, inaccessible/missing/corrupt
  store, schema mismatch, lost commit ACK and diagnostic failure.
- Injected power callbacks, wall jumps, monotonic regression and delayed frames
  cannot refresh authority. Real native sleep/reboot needs a separately approved
  manual fixture test; label it unverified until observed, not simulated proof.
- Repeated caller cancellation during IPC close, process join and D-048 drain;
  valid tail fills remain durable, queue/bytes reconcile, marker/gap state is
  truthful, writer faults remain visible and no owner is abandoned.
- S2B fence-before-request, retained exhaustion/429 cooldown, unknown-fence crash,
  zero restored tokens and current-source invalidation; all live/entry flags false.

## 9. Implementation handoff

**S2A / first Sol phase:** native identity/security/lease inheritance, serialized
control store and narrow policy extensions, bounded pipe codec/worker, fixed inert
child, host lifecycle and native fault/resource tests. No runtime adapter,
production CLI start command, PowerShell service/task wrappers or actual account
scope. Stop for Astra review before progressing.

**S2B / separate approved phase:** fixed offline runtime adapter and transactional
restriction transfer, using the cleared S2A primitives; durable fill-drain and
quota/hold restart tests. Stop for Astra review again. S3 and live operations
remain separate decisions after unresolved account/mutation/venue gates.

Each implementation phase requires focused and full relevant suites, unchanged
S1/D-048 regressions, native ownership/fault tests, resource evidence, disabled
preflight, documentation checks and a reviewable diff. Test fixtures are software
correctness checks, not paper trading or reward/profit estimates.

Design-session verification: source and official Windows/Python contracts read;
Markdown link/whitespace/sensitive-marker checks only. No new native process,
IPC, suspend/reboot, runtime or resource tests were run. The prior 868-test result
remains review evidence, not proof of the unimplemented S2 design.
