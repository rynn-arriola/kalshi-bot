# D-068 — Operational accounting release

September 21, 2026. Implements the accepted
[design](DESIGN_OPENING_ACCOUNT_ACCOUNTING.md). Offline build only; no real
boundary approval, ledger migration, venue/account call, trading or restart.

## What now works

- `account_release.py` separates explicit approval of an exact immutable flat
  checkpoint from an ordinary review acknowledgement. Schema 5 stores its
  approval, per-exchange derived cash and command fee obligations. Cold startup
  reconciles cash against the retained opening/fill/close journal; no lease is
  restored. Schema 4 and older are refused before WAL/DDL changes.
- The existing account coordinator owns one retained reconciliation pass.
  Existing history/order recovery and snapshot auditing precede cash/source
  collection. The sole writer rechecks actual persisted history receipts,
  interval coverage, imported fills, current fully subscribed private epoch,
  exact owned order terms/counts, pending evidence and positions. Historical
  private gaps remain recorded; a fresh current pass may reconcile them.
  SENDING commands remain blocked; an uncertain create needs exact owned order
  evidence, while an uncertain cancel needs terminal order proof.
- `RecoveryRuntime(accounting_boundary=...)` explicitly opts into the final
  accounting stage of its existing bounded repair pass. Defaults and live-disable
  behavior are unchanged. The persisted baseline must already have separate
  explicit approval. No parallel account reader or periodic REST loop was added.
- Only source/observation holds in the explicit transient allowlist may clear.
  One transaction records the exact resolved hold instances and evidence before
  deleting them. Settlement, fill/correction conflict, unattributed funding,
  scope/boundary conflict, saturation and economic failures cannot auto-clear.
- A five-second, revocable in-process lease binds the checkpoint, cash, writer
  epoch, history and account generation/revision. Its clock starts with snapshot
  collection, not after the last read. Cancellation, ingress, reconnect and
  financial/source writes revoke it. Reservation recomputes cash obligations;
  queued SENDING and the synchronous injected send edge recheck authority.
  A committed release record does not itself authorize a later command.
- The cash limit is the minimum of fresh venue available cash and independently
  accounted cash minus working obligations, applied globally **and** per exchange.
  YES buys cost `q*p`, NO buys cost `q*(1-p)`, opposite inventory matches release
  `$1` per matched contract, and actual fill fees are charged once. This is not
  the realized-P&L meter. Pending rewards and unknown settlements/transfers are
  never credited. Precision is preserved through partial closes and reversals.
- Entry fee bounds are required fixture inputs saved with prepared proof.
  Reducer fees come from the existing owner-verified management terms. Missing
  passive fee metadata blocks later entry cash proof without blocking otherwise
  valid inventory exits. Cancels do not acquire an accounting-lease requirement.

## Limits and source map

The sources remain those in the accepted design: private user-order/fill and
position streams first; bounded current/archive orders and fills on recovery;
REST balance/breakdown and settlement/funding histories because the streams do
not supply complete cash activity. Existing shared read budgeting is unchanged.
Completed pagination is not a global watermark. The current history interval
must cover the approved boundary through the snapshot's bounded freshness
window; no future interval is credited. Old inspection reports never replace
the current recovery receipt.

Successful `ReleaseResult.released` means only **operational accounting
reconciled**. `venue_handoff_proven` and `live_ready` remain false. The persisted
accounting-status report cannot certify an in-process lease; reservation/send
owners must consume its current fence. Global silent REST/WS delay and offsetting
unobserved activity remain possible under D-068. A synthetic regression explicitly
preserves that limitation rather than pretending such an event is detected.

Production entry candidate/fee provenance, real write-quota ingestion, dispatch
integration, ranking/admission and supervised runtime readiness are subsequent
work. Production reservations still return `live_authorization_missing`, and
the only executor remains injected/offline. Real boundary approval and any
economic-hold reconciliation are separate operator actions. No real approval
reference or account data is included in this repository.

## Verification

The new `tests/test_bot_account_release.py` exercises the positive owner/runtime
path, exact hold audit, live gate, stale/frozen clocks, missing history/epoch,
reconnect/restart, cancellation before completion, ingress after commit, revoked
send edge, rollback/saturation, old receipt reuse, economic holds, late fills,
cash corruption, fractional fees, cash ceilings and independent cancel/reducer
safety. Existing recovery/archive/omission and command-risk tests remain active.

Commands (native Windows, repository virtual environment):

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B -m scripts.benchmark_account_release
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

Resource fixtures use 30/120 working markets and 128/50,000 retained synthetic
journal events. Budgets are declared before measurement in the benchmark:
release p99 <500ms, event-loop p99 <50ms, measured allocation peak <32MiB,
cash-check p99 <25ms and fixed-market history median ratio <2. These stress
fixtures do not approve 120 live orders or establish a whole-bot CPU budget.
Only cold validation scans retained accounting history; active obligations are
bounded at 4,096, and per-fill cold cash validation uses an indexed close lookup.
The existing 65,536-row/64MiB accounting journal saturates closed, never prunes.

Full suite: **1,074 run, 1,073 passed, one expected Windows privilege
skip**, 150.610 seconds. After the final unresolved-cancel guard, the focused
accounting-release/command-handoff run passed **53 tests**; the complete suite
was not repeated after that last guard. Native preflight returned exit 2 with `live_ready=false`,
no file creation, credential access or network access. Its static global-proof
wording is conservative legacy readiness text, not an assertion that D-068's
operational accounting criterion was unapproved or unimplemented.

| Working markets | Retained events | Release p99 ms | Loop p99 ms | Cash p99 ms |
|---|---|---|---|---|
| 30 | 128 | 24.41 | 16.88 | 2.34 |
| 30 | 50,000 | 16.57 | 14.93 | 4.34 |
| 120 | 128 | 70.38 | 25.54 | 11.65 |
| 120 | 50,000 | 47.78 | 15.30 | 10.61 |

All declared bounds passed after the last guard. Maximum measured allocation
peak was 1,152,081 bytes; CPU time over eight reconciliation iterations was
0.156–0.719 seconds per case. Large/small-history median cash-check ratios were
1.483 and 1.061.
These are local synthetic component measurements, not trading capacity/profit
or production latency promises.

Actual source/test diff review covered ownership, cancellation/commit races,
send-edge expiry, durable restrictions, fee/Decimal semantics and source bounds.
The cancel/reducer insertion mistake found during review was corrected and
regression-tested with an approved synthetic baseline. An in-memory mutation
check confirmed the send-edge regression fails when its accounting guard is
bypassed. No blocking finding remains in this offline component scope.
Local Markdown-link checks and whitespace/secret review precede the scoped
D-065 commit/push; publication does not imply runtime deployment.
