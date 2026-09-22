# D-075 — offline supervised runtime and recovery fence

Implemented September 22, 2026 on native Windows from the approved
[S2 design](DESIGN_WINDOWS_SUPERVISOR_S2.md). This connects the existing native
supervisor to one fixed, disposable `RecoveryRuntime` fixture and transfers
bounded recovery restrictions transactionally. It does **not** add a production
launcher, signer, credentials, venue connection, mutation authority, service,
automatic live restart or bot start.

## Runtime ownership

`recovery_fence.py` keeps bounded fence values free of runtime/ledger imports, so
the parent/control process remains financially inert. `supervised_runtime.py`
adds the fixed S2B adapter. Its context rejects execution,
credential and network flags. Construction uses only a fresh local ledger,
deterministic fake GET responses and in-memory readers. A validated persisted
fence is applied before the ledger or any fake read is created; quota tokens
always restart at zero. The adapter owns runtime start, useful-progress health,
stop and retained join. Cleanup evidence becomes complete only after runtime
reader/finalizer drain and ledger-writer close.

The existing fixed child entry has three finite S2B modes: normal, retained
write-quota/cooldown restriction and crash before fence acknowledgement. No
module name, command, ticker, signer or endpoint is supplied by the caller.
The source/config fingerprint now covers the adapter and recovery runtime.

## Transactional restriction transfer

Supervisor store schema 5 adds one bounded singleton `RecoveryFence` beside,
not inside, the financial ledger. A child FENCE carries an increasing revision,
at most 32 typed component holds, at most eight named cooldowns and terminal-
checkpoint completeness. The parent converts same-boot remaining durations to
its control time, validates the current bound child/session/generation, merges
holds and never shortens a known cooldown, commits the journal, then sends
FENCE_ACK. A clean RESULT is accepted only after a committed terminal fence and
native process exit.

Unexpected S2B death or a missing terminal checkpoint installs
`recovery_fence_unknown` and prevents automatic relaunch. A new parent session
cannot use wall-clock passage to expire an old cooldown; it adds
`recovery_fence_clock_untrusted`. Tokens, grants, snapshots, leases and source
freshness are never restored. Explicit resolution is childless, parent-session-
bound, current-generation/current-fence-revision checked and atomically removes
only named restrictions plus their S1 retry holds. ARM, heartbeat and ordinary
cleanup cannot clear them.

The protocol keeps retained controls and coalesced pulses on separate sequence
lanes. A pulse queued before a newer fence ACK is ignored for freshness rather
than accepted or treated as a missing control. During stop, only the terminal
FENCE_ACK may follow STOP_HINT; it confers no work authority.

## Verification

Focused verification passed:

- 58 supervisor/S2B tests, 57 passed and one expected Windows symlink-privilege
  skip, including 12 native process cases;
- 112 runtime, continuity, dispatch-lifecycle and quota-supervisor regressions;
- clean native runtime stop with terminal fence before RESULT/exit;
- write exhaustion plus shared-429 cooldown retained through terminal cleanup;
- abrupt exit before FENCE_ACK produces one attempt and
  `recovery_fence_unknown`, with no relaunch;
- exact identity/revision/bounds, atomic explicit resolution, cross-session
  clock uncertainty, zero restored tokens and clean private-epoch drain/reopen.

Complete suite: **1,362 run, 1,361 passed and one expected privilege skip in
199.588 seconds**.

The disposable 30/120-market adapter benchmark passed every declared target:

| Markets | startup | shutdown | loop p99 | added working set | handles/native/Python threads/tasks | epoch gaps |
|---:|---:|---:|---:|---:|---:|---:|
| 30 | 34.512 ms | 9.051 ms | 15.558 ms | 454,656 B | 0 / 0 / 0 / 0 | 0 |
| 120 | 49.521 ms | 14.630 ms | 15.482 ms | 417,792 B | 0 / 0 / 0 / 0 | 0 |

Both produced complete cleanup, six deterministic fake reads and traced peaks
below 0.21 MiB. The five-second process-CPU diagnostics were 0.624% and 0.312%;
they are reported but not used as the supervisor-parent CPU gate. The latter is
non-monotonic across the two scopes and includes the synthetic runtime process;
the separately measured S2A parent remains the accepted 60-second under-1%
result. This benchmark is software/resource evidence, not paper trading,
venue-load evidence or a profit estimate.

The disabled preflight, documentation/link checks and final staged secret/diff
review are recorded with the publication commit. Real suspend/reboot remains
unverified because it needs a separately approved manual laptop test.

## Remaining readiness boundaries

- The member direct/non-direct fee profile remains UNKNOWN. The current safe
  per-fragment fee bound remains unchanged pending the separate reviewed
  operator decision on the documented per-order accumulator correction.
- Selected-market timing/rule reviews and launch-boundary account, continuity
  and cash evidence still require current real inputs near an authorized launch.
- This phase supplies offline runtime ownership and restriction transfer only.
  Production runtime construction and any live start remain separately disabled
  and require explicit operator authority after all readiness gates pass.

No credential was read, no network or venue request was made, no order was
placed/cancelled, no live process was started, and no Polymarket file changed.
