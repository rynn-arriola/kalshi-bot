# D-056 — Independent Astra review: changes required

September 21, 2026. Reviewed `6992fed` against `ebb9892`, the approved
[D-055 design](DESIGN_WINDOWS_SUPERVISOR_S2.md), and D-049's phase boundary.
The initial working tree was clean. **S2A is not cleared for S2B.** The existing
81 focused tests pass, but independent fault probes reproduce missing safety
behavior. Findings below concern the inert foundation; no live bot was run.

## R1 — P1: retain lifecycle ownership through faults and repeated cancellation

Locations: `process_supervisor.py:218-232, 322-405, 448-461`;
`supervisor_control.py:203-219`; `process_supervisor.py:66-105`.

`run()` catches one cancellation, then awaits an unshielded second `_loop`.
A second cancellation escapes through `finally`, closes control and releases
parent ownership while the child is alive. Other exceptions, including a
well-formed envelope with the wrong child identity, escape without durable
disarm or stop. Native probes using the existing `hang_after_admit` fixture:

| Trigger | Host finished | Child alive | Parent lease free | Durable stop |
|---|---|---|---|---|
| Cancel twice after HEALTHY | yes | yes | yes | true |
| Inject wrong-child STATUS | yes | yes | yes | false; still HEALTHY |

Cold recovery has the same ownership-completion mistake: `_loop` tests
`self.child is None`, which is also true for an old, unadopted child. Holding the
old child lease and reservation, then starting a replacement host, produced
`host_finished=true`, `still_reserved=true`, `stop_signaled=true`. It returns
instead of retaining observation until lease-proven orphan release.

Additional source paths must use the same retained owner: cancelling the await
of shielded `ControlOwner.submit("spawn")` may clear `self.child` before the
worker finishes creating it; failure after Popen/before the created-stage commit
escapes without joining; cancelling `bind()` can abandon the endpoint returned
by its still-running thread. Handle setup also begins before the cleanup `try`:
an injected second-duplicate failure left the first inherited duplicate open,
preventing another child lease even though no process was created. That last
case was reproduced and the exact test-owned duplicate was closed afterward.

Required fix: one retained stop/finalization operation owns pending spawn/bind,
the child, IPC/control workers and parent lease until completion. Repeated caller
cancellation must await that operation. Route protocol/store/queue failures
through durable attention when possible and always attempt the independent stop
signal; preserve uncertain reservations and original fault evidence. Retain cold
observation until exclusion commits. Protect each acquired temporary handle from
the first acquisition. Do not solve this with automatic force-killing.

Acceptance: deterministic barriers for repeated cancellation, malformed message,
spawn pending/commit acknowledgement lost, bind pending, IPC/control join, partial
handle acquisition, and cold recovery with the old lease still present. Assert
ownership remains held until actual completion, not just eventual fixture cleanup.

## R2 — P1: require an affirmative reservation before process creation

Location: `supervisor_control.py:161-183`.

The spawn command checks only `decision.stale`. A local clock fault returns a
nonstale attention decision without reserving a child. `reserve_start` correctly
declines the reservation, but the caller still invokes `factory.spawn()`.

Reproduction: initialize/arm at wall=100, monotonic=10 with fixed boot identity;
change to wall=200, monotonic=11 before START_REQUESTED. A recording factory
observed **one spawn call**, while durable state was `attention_required`,
`child_id=null`, native stage `idle`. Only the subsequent stage update raised
`InvalidData`. No real process was needed to demonstrate this policy bypass.

Required fix: under the control mutex, require the explicit spawn action and
matching committed reservation/session/generation, current arm/fingerprints and
clear stop latch before Popen. A nonstale decision is not launch permission.
Honor safety actions on rejected/stale decisions. A denied or abandoned-control
receipt must have an unambiguous non-spawn outcome; the host currently assumes
every nonstale receipt contains a child value.

Acceptance: inject clock distrust between due tick and reservation, plus STOP,
budget/hold rejection, abandoned mutex and fingerprint drift. Assert zero spawn
calls and a persisted hold. Verify a normal reservation still precedes creation.

## R3 — P2: finish retained result writes and make IPC close retryable

Locations: `windows_ipc.py:103-113, 219-239, 278-293`;
`tests/fixtures/supervisor_child.py:117-153`.

The child enqueues RESULT and immediately calls `close_and_join`. Close signals
the higher-priority close event and cancels I/O; it does not await completion of
that retained control frame. The parent's 250 ms tail read cannot recover a frame
that was never written. A native pipe probe gated the sender worker until RESULT
was queued and close started: receiver got no message, one control frame remained
unsent, and the worker reported stopped. Thus a clean return code can be recorded
as unexpected death/unknown cleanup; cycle tests do not assert RESULT delivery.

Also, `closed=True` is set before worker join. If join times out, a later call
returns immediately without joining or closing handles. Pending structures must
remain owned and retries must continue the existing close operation.

Required fix: separate submission, completed writes and fully closed state.
Await bounded terminal-control write completion before graceful child exit;
on failure preserve explicit unknown/failure evidence and retain native cleanup.
Repeated close/cancellation must join the same operation. Test nonreading peer,
queued RESULT at teardown, write cancellation and first-join timeout followed by
successful retry; require no retained buffers/handles after confirmed completion.

## R4 — P2: validate parent identity, freshness and protocol phase in the child

Locations: `tests/fixtures/supervisor_child.py:64-98, 121-137`;
`process_supervisor.py:263-274`.

The child checks direction and sequence only. It never compares envelope scope,
session, child or generation, nor checks message age; PULSE refreshes the local
timer regardless of its revision. A mocked-transport probe supplied ADMIT/PULSE/
STOP_HINT with wrong scope/session/child/generation and timestamp `1`, while the
independent store view described the intended child. The child returned **0** and
emitted **HELLO, healthy STATUS, clean RESULT**. Peer PID binding does not fulfill
the required envelope/phase/freshness contract.

The parent also sets a work deadline to receipt time plus the full remaining
duration, without subtracting message transit age as D-055 requires.

Required fix: apply common identity, monotonic age and legal-phase validation in
both directions before any timer/admission update, verify applicable committed
revision/generation, reject unsupported/duplicate controls and subtract transit
age from remaining work. Test each mismatched field, delayed/future pulse, second
ADMIT, S2B controls and delayed work snapshots with exact deadline assertions.

## R5 — P2: implement the child and in-flight power invalidation boundary

Locations: `process_supervisor.py:233-256, 322-334, 433-449`;
`tests/fixtures/supervisor_child.py:27-153`.

Source inspection: only the parent registers `WindowsPowerMonitor`, and it checks
the flag at the top of `_loop`. The child never registers or consumes a power
flag. The parent can resume from an await inside spawn/handshake and send ADMIT
before returning to that check. This omits D-055's requirement that the first
resumed operation invalidate authority in both processes before admission or
status work. Wall/monotonic checks are explicitly only an additional guard.

Required fix: register the callback in both owners and service a sticky
invalidation before admission, pulse/status publication and subsequent launch
work, including after awaited boundaries. Registration failure must refuse the
harness. Use injected callbacks/barriers for acceptance. Actual laptop
suspend/reboot remains unapproved and untested; do not perform it to fix this.

## R6 — P2: protect and verify the durable control files

Locations: `supervisor_control.py:26-44, 85-93`;
`supervisor_store.py:106-162, 177-190`.

Explicit security is installed on kernel objects, but no path establishes or
checks the approved user/System file owner and DACL for the control database or
its sidecars. Initialization only checks an empty directory. An independent
native security query on a newly initialized disposable database reported
`dacl_protected=false`. This verifies the missing protected-file contract; it
does not claim another user had effective access on this laptop.

`ScopeSpec` validates the directory path once; opening the database does not
revalidate the file's reparse/type/owner/security. `open_existing` also uses an
existence check followed by a create-capable SQLite open, rather than a
noncreating open mode. These do not establish D-055's persistent-state trust
boundary under redirection or file replacement.

Required fix: create fresh fixture control state with the specified protected
permissions, validate existing root/database/sidecars without rewriting somebody
else's ACL, reject redirection/unexpected types, and use a noncreating existing
store open. Test disposable permissive/reparse/missing/replaced files and ensure
refusal leaves them untouched. Preserve old schemas and journals.

## R7 — P2: connect bounded diagnostics and logging-health failure handling

Locations: `process_supervisor.py:102-104, 153, 257-261, 388-395`;
`supervisor_control.py:127-137`; fixed child startup/exit.

Source inspection: neither process uses the existing D-033 diagnostic owner;
child stdout/stderr go to DEVNULL. Failures become an in-memory exception or
escape, without stable process/session-correlated diagnostic records or a
logging-health gate. For example the malformed-envelope probe left persisted
state HEALTHY while its host task had failed. The independent review can inspect
that exception, but the operator-facing supervision cannot reliably explain it.

Required fix: reuse the existing bounded diagnostic component under D-033/D-055,
with safe event codes and explicit health/close ownership in each process.
Logging failure must block starts and request retained shutdown; do not add an
independent retry policy. Test injected sink failure and safe fault records,
without logging raw exception payloads, environments or credentials.

## R8 — P3: apply the journal bound to native/session events

Location: `supervisor_store.py:341-369, 387-419`.

Only `_apply_locked` prunes history. Disarmed parent-session transitions append
events directly, so 300 successive `begin_parent_session` calls retained **300**
rows with `event_limit=256`. Native-stage writes also omit pruning. A later policy
event may trim rows, but the promised bound does not hold at each committed
transition.

Required fix: share bounded journal insertion/pruning across every event writer
and assert the limit immediately after session and native transitions. This is
small enough to include in the same focused correction phase.

## Verification and evidence limits

- Native project interpreter: **81 focused S1/S2 tests passed in 12.268 seconds**.
- Seven initial independent probes reproduced: denied spawn invoked; repeated
  cancellation abandoned ownership; malformed envelope abandoned ownership;
  cold parent returned with old reservation; terminal frame lost on close;
  child accepted wrong/stale parent frames; session journal exceeded its bound.
- An additional setup-failure probe reproduced a leaked inherited duplicate.
  A native file-security query reproduced the missing protected database DACL.
- The probes used temporary test scopes and disposable stores. Exact registered
  inert child handles were terminated only for cleanup of the hung test fixture;
  its remaining IPC/presence handles and controller threads were then joined.
- Disabled preflight: expected exit **2**, `live_ready=false`, with false file,
  credential and network side-effect flags. No production account/API access.
- Documentation checks: `git diff --check` passed; all relative Markdown links
  in the seven changed documents resolved, and no private-key/token markers were
  found. The tracked source, tests and scripts remain unchanged.
- The previously reported **885** full tests and resource measurements remain
  Sol's historical evidence, not a new independent full-suite or benchmark run.
  No source change required rerunning those long checks for this review.
- The benchmark checks one inert workload, not the design's 30/120 synthetic
  workloads or equivalent unsupervised baseline. Its Python thread count is not
  a native thread count, and the reported +13 handles after managed-executor
  cleanup remain unattributed. A warmed cycle delta of -2 does not independently
  prove complete startup/teardown handle cleanup. Retention, lease disappearance,
  terminal RESULT delivery and fault paths need their own assertions.

## Sol handoff

Implement R1-R7 within the existing S2A design, including the small R8 journal
correction. Add deterministic regressions for these findings, prove they detect
the current defects, run the focused suite, then one full regression run on the
final source. Rerun resource checks once ownership/IPC/logging changes are final;
qualify any workload or baseline not actually measured. Do not turn repeated
green runs into an open-ended test phase.

S2B remains blocked. Stop here for the operator's switch to **5.6 Sol** under
D-049. This review changes documentation only; code fixes and publication are
not performed. Review/handoff files are local and uncommitted.
