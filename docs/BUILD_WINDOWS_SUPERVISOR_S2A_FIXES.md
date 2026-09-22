# D-057 — S2A review corrections

The resource blockers in this historical build record are resolved by the
[D-074 follow-up](BUILD_WINDOWS_SUPERVISOR_RESOURCE_FIXES.md). The measurements
below remain the exact pre-fix evidence.

September 21, 2026. Astra implementation under the operator's task-specific
exception to D-049. Addresses [D-056 R1-R8](REVIEW_D056_ASTRA.md) within the
[approved S2A design](DESIGN_WINDOWS_SUPERVISOR_S2.md). This is implementation
evidence, **not independent review clearance or permission to start S2B**.

## Changes

| Finding | Correction |
|---|---|
| R1: ownership | One retained host task owns spawn, bind, child observation, IPC, control, diagnostics and native teardown. Repeated cancellation signals stop but cannot cancel that owner. Errors request durable attention and independently signal stop. A cold host keeps observing until lease-proven orphan release commits. |
| R1: uncertain creation | Temporary inherited handles are tracked from their first acquisition. Creation attempted without a returned process remains uncertain: preserve the reservation and ownership, never synthesize SPAWN_FAILED or retry. Only proven pre-creation failure may release. |
| R2: launch permission | Require SPAWN_RECOVERY plus matching committed reservation/session/generation and armed state. Recheck fingerprints, stop latch, power and diagnostic health under serialized launch ownership. A denied/abandoned receipt explicitly has `spawned=false`. |
| R3: IPC completion | Retained controls return native-write completion receipts. The child waits for terminal RESULT completion before closing. Outstanding controls, including in-flight writes, stay bounded. A close timeout remains owned and retryable; `closed` means worker and native handles have actually finished. |
| R4: protocol | Shared peer identity, same-boot age and sequence validation; child-side admission/pulse/stop phase and revision gates. Reject duplicate ADMIT, pre-admission PULSE, unsupported S2B and future/stale frames. Parent work deadlines subtract transit age. |
| R5: power | Both processes register sticky native power invalidation. Parent checks after asynchronous handshake/control boundaries and before admission/pulse/status authority; child checks before and after blocking receive/control work. Registration failure refuses the fixture. |
| R6: control files | Explicit protected approved-user/System DACLs for fresh control state. Pin root/database handles against deletion/replacement, reject unexpected types/reparse paths/owners/ACLs, and validate sidecars. Existing-store opens use SQLite `mode=rw`, read snapshots use `mode=ro` and one transaction. Existing schema precheck is nonmutating; no migration or ACL repair. |
| R7: diagnostics | Parent/child use the existing bounded diagnostic sink with stable supervisor codes, run IDs, operation references and safe error frames. Launch requires healthy logging. Shutdown joins its diagnostic owner. Known fixture validation/safety exit codes cannot become automatic transient restarts. |
| R8: journal | Policy, parent-session and native-stage events use the same pruning bound at each commit. |

The parent's presence lease is released last. Process/IPC/control cleanup has no
automatic forced-kill escape: a stuck child, uncertain creation or unrecoverable
cleanup/store failure can require operator attention indefinitely. This is
intentional exclusion, not a promise to repair every error automatically.

Control-file initialization is restricted to an explicitly empty fixture root.
Opening existing state never repairs permissive security or rewrites an old
schema. Same-user malicious code and administrators remain outside the design's
isolation guarantee. Native file behavior follows Microsoft's
[handle security](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)
and [file creation/sharing](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
contracts. No production data ACL was changed.

## Verification

Thirty new regressions cover the review mechanisms and deterministic barriers:
repeated cancel, spawn/bind/IPC/control-close interruption, lost created-stage
acknowledgement, uncertain constructor, durable-stop failure, cold old-child
presence, denied/abandoned launch, partial handle acquisition, terminal-write
receipt and join retry, identity/age/phase/revision, power, diagnostic failure,
safe error records, file replacement/security/old schema, and journal bounds.

- Focused S1/S2 suite before the last three test-only additions: 108 run,
  107 passed, one skipped, 36.220 seconds. The three additional tests pass
  separately in 2.390 seconds; production source is unchanged between these runs.
- Three process-local safeguard reversals were detected: bypassed peer identity/
  age, disabled journal pruning and omitted transit-age subtraction. These are
  targeted reversals, not a claim to have rerun every test against the parent.
- The native database symlink case is skipped because this Windows token cannot
  create a symbolic link. Protected ACL and replacement-denial cases execute.
  Real laptop suspend/reboot remains untested and unapproved.
- Complete suite: **915 run, 914 passed, one skipped, 114.296 seconds**, using
  `python -B -m unittest discover -s tests -q`.
- Credential-free disabled preflight reports `live_ready=false` and false file,
  credential and network side-effect flags; expected native exit code **2**.
- Python syntax, changed-document relative links, whitespace and sensitive-marker
  checks pass. No configuration diff. No commit/push or repository-parity claim.

## Resource evidence and remaining limits

The 100-cycle run completed across four sessions. Terminal RESULT/exit counts,
released parent/child leases, bounded journals and bounded logs all passed its
assertions. Warmed-cycle deltas: **-2 native handles, -2 native threads, zero
Python threads**, with no retained supervisor/diagnostic threads. Whole-process
cleanup still reports **+13 handles** against the cold baseline; this is not
attributed, so warmed-cycle stability is not a claim of zero cold-start retention.

That aggregate run failed its CPU target: it reported parent 2.499% of one core,
child 1.458%, loop p99 16.634 ms, working set 39,731,200 bytes and backlog 1.
The native thread-enumeration diagnostics were inside its CPU measurement
boundary. Parent CPU sampling is now outside those expensive snapshots. Only
the idle measurement was rerun, not the full 100-cycle workload:

| Corrected idle sample (60.002 seconds) | Result |
|---|---:|
| Parent CPU | **2.135% of one core — fails <1% target** |
| Child CPU | 1.719% (reported separately) |
| Event-loop delay p99 | 16.475 ms |
| Policy latency p99 | 16.914 ms |
| Working set above parent-only baseline | 39,014,400 bytes |
| Python traced peak | 385,571 bytes |
| Maximum incoming backlog | 1 |

Thus CPU/resource acceptance remains open. The corrected sample was obtained
through `idle_measurement(60)`; its reporting call exits normally but does not
assert thresholds. That exit status is **not** a passed CPU target. Require
focused CPU and cold-handle attribution before claiming resource clearance.

A short attribution probe found repeated sidecar audits consume CPU, but reducing
their frequency did not establish the target. That experimental production-source
change was reverted. All file-security checks remain in the final source tested
by the complete suite. The benchmark timing correction does not change process
ownership or the bot's operating rules.

The resource harness now asserts terminal RESULT and exact exit counts, released
leases, bounded journals/logs, and records actual native thread counts. It no
longer queries private Popen fields. Its workload is one inert child, **not** a
30/120-market runtime or a matched unsupervised-runtime baseline. Do not turn its
working-set measurement or warmed-cycle baseline into those unmeasured claims.

## Handoff

Stop for independent Astra review of the D-057 diff and fault tests, with special
attention to retained teardown, conservative creation uncertainty, file security
and control/power ordering. CPU and cold-handle findings above remain explicit
follow-up work; do not extend this correction phase into S2B or relax security
checks to manufacture a passing benchmark.
Review documents from the preceding session are preserved. No live process,
configuration, account, credential, venue or Polymarket reference was touched.
No deployment or restart occurred; changes remain local until publication.
