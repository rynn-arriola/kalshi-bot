# D-081 — production supervisor connection

**Superseding repair:** all seven [end-to-end findings](REVIEW_D081_END_TO_END.md)
are fixed and verified offline. The historical verification below remains the
original D-081 record; current evidence is in that review's resolution section.

Implemented September 22, 2026 on native Windows. This connects the existing
foreground live runtime to the reviewed native supervisor; it does not authorize
or perform the first live run.

## Implementation

- `supervisor_launch.py` defines one exact production profile, fingerprints the
  complete package plus approved bot configuration, and resolves one-time
  initialization versus recovery-only restart.
- `process_supervisor.py` accepts only that concrete profile for the fixed
  production scope. Existing fixture behavior remains separate. Persisted
  recovery reasons force every replacement child into recovery-only mode.
- `supervised_live_child.py` authenticates the inherited parent/control handles,
  owns credentials and the existing account lease, publishes bounded runtime
  health, and joins the live runtime before reporting a result.
- `live.py` can set `entries_paused` before composition. Recovery therefore
  cannot create entries; it can only use existing reconciliation, cancellation
  and inventory-exit paths. A clean result still requires verified flatness.
- `supervised_live.py` and the three PowerShell scripts provide foreground
  start, durable stop and read-only saved status. No service or detached process
  was added.

The fixed financial path remains `data/trader/account.db`. An existing ledger
always suppresses initialization even when the original parent was started with
`--initialize`. Missing or ambiguous ledger/runtime evidence refuses startup or
enters bounded recovery/attention; it never creates a replacement risk baseline.

## Review fixes applied

The production diff review found and corrected four meaningful issues:

1. Arbitrary profile objects could have supplied a child command; the host and
   child factory now require the exact `ProductionLaunchProfile` type.
2. Final status incorrectly implied trading had started; it now reports only
   that launch was attempted.
3. A post-admission IPC/diagnostic failure could use a reserved startup-refusal
   exit code; possible runtime ownership now classifies as unexpected death.
4. Runtime-exception cleanup was being stated as confirmed. It is now explicitly
   unconfirmed, forcing recovery-only handling.

The inert child also lazily imports the offline runtime graph. This reduced its
working set enough to restore the unchanged native resource targets without
weakening any threshold.

## Verification

All checks were credential-free and offline:

- Final complete suite: **1,419 tests**, **1,418 passed**, one expected Windows
  privilege skip, no failures in 214.635 seconds.
- Final focused production/native/S2B suite: **57 tests**, 56 passed and one
  expected skip. A broader focused run before the lazy import passed 65 tests
  with the same expected skip.
- Native supervisor: 60.016-second idle run plus 100 lifecycle cycles. Parent
  CPU 0.937%, event-loop p99 15.882 ms, working set 39,817,216 bytes, backlog 1,
  warmed handle/thread deltas -2/-2/0, no retained supervisor threads. Every
  declared target passed.
- Offline S2B 30/120 markets: cleanup true, zero handle/thread/task deltas,
  event-loop p99 15.682/15.548 ms, memory target passed.
- Selection and admission 30/120-market representative gates passed.
- Production CLI help and all three PowerShell scripts parsed; Python compile,
  `git diff --check`, 607 tracked local Markdown links and private/runtime tracked
file checks passed. Final commit/push parity is recorded in the repository status.

No signer was loaded, no Kalshi endpoint was called, no account ledger/control
root was created, and no order or bot process was started. Live acceptance and
the separately authorized Windows host watchdog remain checklist items 7 and 8.
