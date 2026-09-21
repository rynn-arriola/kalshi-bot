# D-060 — Command capacity and atomic handoff implementation

**Historical initial build.** The
[independent review](REVIEW_D060_ASTRA.md) identified R1-R6 and invalidated the
resource acceptance below; the subsequent
[correction record](BUILD_COMMAND_CAPACITY_REVIEW_FIXES.md) supersedes those
gaps. This file preserves the original implementation evidence.

September 21, 2026. Implements the approved
[D-059 design](DESIGN_COMMAND_CAPACITY_HANDOFF.md) in disposable offline scope.
No authenticated transport, account access, ledger migration, deployment,
restart, configuration change or live order action occurred.

## Delivered contracts

- Schema 3 adds a persistent ledger identity, command episodes, explicit
  per-resource credits and reconciled held counters. Existing schema-2 ledgers
  are rejected before WAL/DDL writes; no automatic migration exists.
- Entry preparation now atomically performs risk checks, capacity funding,
  intent creation and PREPARED mutation insertion, returning one immutable
  post-commit receipt. The executor consumes that receipt and never reserves a
  second intent.
- Mutation retention remains bounded: 4,096 ordinary-entry high-water and
  8,192 total rows. Intents and order evidence remain bounded at 4,096. A first
  market episode reserves one passive plus three IOC reduction bundles, and
  every create reserves its future order evidence and cancellation mutation.
- A funded cancellation converts held mutation capacity to a used row in the
  same writer transaction, including at the exact hard bound. Expected capacity,
  stale-receipt and already-used denials do not poison the writer; immutable
  conflicts and broken accounting invariants remain fatal.
- Writer/ledger identity, epoch, revision, immutable terms, exact account/order
  scope and a sole executor owner gate dispatch. The final proof gate also
  detects a writer change after PREPARED becomes SENDING. Unknown sends remain
  held for reconciliation and are never retried automatically.
- Terminal order evidence releases unused client credits only after matching
  fills are durably accounted. Episode bundles retire only when no active intent,
  working order, pending fill or inventory remains.

Implementation is in `command_types.py`, `command_capacity.py`, `ledger.py`,
`portfolio.py`, `execution.py`, `orders.py` and `writer.py`. Runtime entry
inspection remains execution-disabled. Public market data remains WebSocket-first.

## Verification

- New focused boundary/handoff files: 21 tests passed.
- Impacted command/risk/exit/logging/accounting set: 244 tests passed in
  18.415 seconds.
- Complete native Windows suite: **936 run, 935 passed, one existing native
  symlink-privilege skip**, in 121.508 seconds.
- Real-size regressions read all 8,192 mutation rows, prepare a valid funded
  cancellation at 4,096 used rows, convert held cancellation capacity at an
  exact 8,192 `used + held` bound, reject missing credits, and reject a
  counter/credit mismatch at startup.
- Safeguard reversals cover omitted cancellation funding and tampered receipt
  identity/terms. Both fail closed with zero dispatch authority.
- Disabled credential-free preflight returns expected exit 2 with
  `live_ready=false`, `creates_files=false`, `credentials_accessed=false` and
  `network_accessed=false`.

The offline 30/120-market lifecycle harness ran small and 4,000-row histories,
30 valid entry/cancel lifecycles per case, at most 30 resting entries, and
synthetic accounted inventory for additional markets. All four original cases
reported pass, but their retained history lacks associated lifecycle evidence.
The review's complete-history replacement fails CPU; this table is historical
and must not be used as acceptance:

| Scope | History | Prepare p99 | Consume p99 | Cancel p99 | Capacity p99 | Loop p99 | Peak memory | CPU/command | Near/small CPU |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | 0 | 16.504 ms | 1.596 ms | 3.376 ms | 0.928 ms | 6.723 ms | 1,405,789 B | 0.014583 s | — |
| 30 | 4,000 | 13.299 ms | 1.366 ms | 2.572 ms | 0.391 ms | 6.021 ms | 90,747 B | 0.013021 s | 0.893x |
| 120 | 0 | 15.828 ms | 1.658 ms | 2.634 ms | 0.431 ms | 6.336 ms | 184,985 B | 0.015104 s | — |
| 120 | 4,000 | 15.161 ms | 1.486 ms | 3.060 ms | 0.472 ms | 5.999 ms | 160,325 B | 0.016667 s | 1.103x |

Writer backlog sampled after awaited operations was zero and each case added
exactly one writer thread. These limited offline measurements do not establish
concurrent backlog, full 120-market management, live latency or profitability.

## Remaining boundaries

Used history is intentionally not reclaimed. Archive/rollover policy remains a
separate design task. Existing user schema-2 ledgers require a controlled future
migration decision. Production account completeness, venue mutation transport,
exit orchestration, ranking/allocation, S2A resource review and S2B remain open.
R1-R6 are corrected in the linked follow-up. The remaining boundaries still
require separate authorization and evidence.
