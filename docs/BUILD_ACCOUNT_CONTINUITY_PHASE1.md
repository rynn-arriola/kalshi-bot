# D-045 — Account continuity Phase 1 implementation

Independent review update: [R1-R5 require fixes](REVIEW_D045_ASTRA.md).
Shutdown delivery and cancelled-open gap caching are not cleared; the reconnect
burst below ran before resource instrumentation, so those numbers measure only
the assessment/candidate loop. Preserve the implementation-run evidence below
as history, not current review clearance. D-046 subsequently implemented the
[review fixes and corrected measurement](BUILD_ACCOUNT_CONTINUITY_REVIEW_FIXES.md),
pending Astra re-review.

Date: September 20, 2026. Native Windows; execution disabled. Implements only
Phase 1 of [D-044](DESIGN_ACCOUNT_CONTINUITY.md), following the operator's
explicit assignment and confirmation of the 5.6 Sol switch. Independent Astra
review is next. No real Kalshi account, credentials, WebSocket or live orders
were used.

## Source contract

- `continuity.py` defines immutable `PrivateEpoch`, `StartingAccountCandidate`
  and `ContinuityAssessment` records and a pure local-evidence assessment. A
  proposed starting boundary needs a current scoped report and matching writer
  revision. `approved=False` and `venue_handoff_proven=False` are invariant.
- `private_epoch_store.py` persists bounded local reader markers through the
  existing `LedgerWriter` and schema-2 SQLite owner. All four private channels
  must ACK before a marker opens. A clean local close requires orderly stop,
  reader join, empty reader queue, idle private queue and no
  writer/engine/scope failure. Crash,
  cancelled run, reader failure or failed close stays a durable gap. Markers
  contain IDs, counters, times and reason codes only—no raw payloads or secrets.
  A 4,096-marker cap fails closed and requires explicit archival; nothing is
  pruned automatically.
- `RecoveryRuntime` retains its one account owner and bounded recovery worker.
  Fill staging still precedes queue admission; a fill before all ACKs is staged
  and the reader reconnects without a clean epoch. Status computes an O(1)
  local assessment from existing report/receipt/marker references; explicit
  inspection is a control-plane read, not book-tick work. A private position
  update without subaccount invalidates current evidence, installs no cost or
  quantity, requests one coalesced scoped reconciliation and keeps the account
  feed for later fill evidence. Scope ambiguity cannot report repaired status.
- `RestReads.collect('positions')` now requires a cursor field on every page.
  An absent cursor means incomplete pagination, not empty final page. The
  [official positions response](https://docs.kalshi.com/api-reference/portfolio/get-positions)
  describes an empty cursor value as the end of the result. The
  [market-position stream example](https://docs.kalshi.com/websockets/market-positions)
  omits subaccount; its scope is not guessed.

The writer's existing history receipts, fill accounting, cash/risk windows and
order authority are unchanged. Entry/readiness remains false regardless of
the new assessment. No additional REST loop, per-market task, live action or
legacy migration was added. An old invalid epoch is not cleared by a new ACK.

## Verification

The 16 new focused tests pass: open/clean/invalid/crash markers, restart gap,
writer close failure, subscription ACK and pre-ACK fill, cancelled run, reader
backlog and engine failure, unscoped/mismatched position, partial positions cursor, candidate
revision binding and the local-vs-venue proof boundary. Two process-local fault
reversals confirm the tests detect a suppressed persisted-gap query and a
weakened required-channel set. Existing recovery tests cover fill-before-order,
duplicate/conflicting fill, late stream/history overlap, changed cutoff,
foreign orders, old-generation tails and omitted known fills.

The five directly affected modules pass 168/168 tests. One earlier exact
`unittest discover -s tests -p test_*.py -q` run passed 792/792. The final
source/test-state run executed 794 tests and failed one existing, unrelated
`test_pending_boundary_does_not_retain_candidate_or_traceback` quota-supervisor
weak-reference assertion. Its 24-test module failed the same assertion on two
isolated reruns. No quota source/test file was changed in D-045, and this
verification gap must be reviewed; do not report the complete suite as
consistently green. `scripts/benchmark_continuity.py` uses disposable WAL/FULL ledgers,
30/120 markets, 128/4,096 synthetic receipt IDs, 30/120 cached assessments and
an eight-epoch reconnect burst. Both predeclared budgets pass:

| Markets / IDs / cached | Assessment p99 ms | Loop p99 ms | Incremental peak |
|---|---:|---:|---:|
| 30 / 128 / 30 | 0.108 | 0.195 | 95,286 B |
| 120 / 4,096 / 120 | 0.131 | 0.330 | 1,174,700 B |

The inherited `benchmark_history_coverage.py` also passes its 128/4,096-row
staging budgets: 0.112/1.622 s wall, 2.661/9.782 ms inspection p99,
9.0/29.777 ms event-loop lag p99 and <2.5 MiB peak. These are local fixtures,
not measured Kalshi venue or production throughput. Execution-disabled
preflight returns native exit 2, `live_ready=false`, no credential/network use
and no file creation.

## Remaining gate

No published shared private/REST watermark, replay contract or bound on fill
publication has been established. A locally clean epoch or completed history
enumeration is not a complete-account proof. Starting lot basis, account
exclusivity, corrections/settlements, transfers/cash and an operator-approved
launch boundary remain undecided. Phase 2/3 and live integration require new
design/decisions. Astra should review this source and Git diff for races,
authorization leaks, schema and lifecycle edge cases before any further work.
