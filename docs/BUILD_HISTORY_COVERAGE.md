# D-035 — Durable history enumeration evidence

Build scope, September 20, 2026, native Windows. No account calls or live start.

## Contract and predeclared verification

Persist an immutable receipt only after every bounded history staging chunk was
acknowledged. Verify exact staged row identity/economics/scope before committing
the receipt. Interrupted staging may leave useful positive evidence, but must not
leave a completed interval. Repeated readings never delete old evidence or alter
financial accounting. A subsequent enumeration omitting remembered fills is an
explicit discrepancy, not a correction, cancellation or ownership waiver.

Retain requested half-open microsecond interval, archive cutoff, pages, excluded
other-account count, exact-record digest, source writer epoch and optional private
generation/revision. Bound interval credit at the read's start time, never credit
future time or infer an atomic snapshot. Union eligible intervals only within
the requested subaccount; report exact gaps. Restart reads inspect historical
receipts and never restore current stream/account authority.

Existing 10,000-row staging cap remains. Hot receipts cap at 4,096, with no
silent eviction. All SQLite work/hashing stays on the existing writer. No new threads,
polling, network calls or per-book scans. Control-plane inspection is explicit.

Planned tests: interruption, cancellation, conflict/rollback, empty reads, gaps,
overlap, adjacency, future intervals, scope, omitted old evidence, idempotency,
restart, stale account generations and runtime status; two in-memory safeguard
reversals. Scaling fixtures: 128/4,096 rows and 30/120 receipt reads; total staging
wall <3/15s, inspection p99 <250ms, event-loop lag p99 <50ms, incremental peak
<32MiB. Fixtures are correctness/load tests, not paper trading or income estimates.

## Source checks and unresolved guarantees

Reviewed current official [fills](https://docs.kalshi.com/api-reference/portfolio/get-fills),
[historical fills](https://docs.kalshi.com/api-reference/historical/get-historical-fills),
[cutoffs](https://docs.kalshi.com/api-reference/historical/get-historical-cutoff-timestamps),
[historical-data guide](https://docs.kalshi.com/getting_started/historical_data) and
[private fills](https://docs.kalshi.com/websockets/user-fills), alongside the exact
dated local OpenAPI/AsyncAPI operations, response schemas and parameters.

Recent and archive fill endpoints split at the trade-created cutoff. Recent reads
have explicit subaccount filtering; archive reads need per-row account evidence.
Neither inspected pagination nor private-fill contract supplies a shared
REST/stream snapshot watermark or bounded late-publication guarantee. These
remain UNKNOWN, not proof supplied by repetition or matching net positions.

D-030's 18 previously observed fills remain untouched. No actual launch timestamp
is selected or installed; a query's start is an inspection interval, not a reset.
Current balance, starting inventory, corrections/settlements, stream continuity
and explicit live authority remain separate readiness gates.

## Implementation

`history_coverage.py` owns immutable `EnumerationReceipt` and diagnostic
`EnumerationCoverage`. `LedgerWriter.audit_history` preserves its 256-row staging
chunks, then commits a receipt in one owner transaction after validating the
staged rows. One indexed range read replaces per-fill SQL calls. The version-1
SHA-256 digest uses sorted fill identities, length-prefixed UTF-8 identity/payload,
and fixed-width execution-time/account/shard integers. It is an integrity aid,
not a venue signature or proof of an unobserved execution's absence.

An additive `history_enumerations` table/index and staging account/time index are
created by the existing schema-2 initializer. Financial schema/accounting does not
change. No historical/runtime ledger was opened or migrated during this build;
all test databases were disposable. Old accounting schemas remain rejected.

Completion rechecks exact staged identity/economics/scope, retains omitted-row
counts, and never imports fills. `AccountCoordinator` carries the receipt's source
provenance in its recovery report. Runtime refuses to label a pass repaired when
its enumeration omitted remembered fills, even if positions are flat and no new
rows were returned. A missing row is unresolved evidence, not a venue-confirmed
correction. A completed receipt can survive a later failed import; those are
different facts. Old receipt omissions remain visible on historical inspection;
this build does not invent an automatic resolution/waiver policy.

Cancellation before all chunks finish leaves no receipt. Cancellation after
final submission may leave the valid committed receipt, consistent with existing
accepted-writer-command durability. Read generation loss invalidates the current
report even when its historical receipt was safely recorded. Repeat same-ID
commit is idempotent only for identical content; normal new readings append new
IDs. The original build made capacity exhaustion fail closed without deleting
evidence. D-100 later observed that deterministic limit in production and adds
transactional exact archival: all hot rows are validated and preserved in one
content-addressed compressed archive before they are removed, and the new
current receipt commits in the same transaction. Any failure rolls back. An
archive is historical audit evidence and explicitly cannot restore current
account/trading authority. See
[live maintenance reliability](BUILD_LIVE_MAINTENANCE_RELIABILITY.md).

`LedgerWriter.history_coverage(subaccount=..., start=..., end=...)` and runtime
`inspect_history_coverage(start=..., end=...)` are explicit local control-plane
queries. No network or periodic query is added. Runtime status uses the last
cached inspection, explicitly labelled historical-only; it does not read the DB
on a book event/status request. A full interval union never sets live readiness.
The only new diagnostics are safe `history_enumerated` and `history_omission`
events; raw execution data and credentials are not logged.

## Verification and resource results

All 670 tests pass in 48.627s, including 31 focused tests for insert rollback, provenance and payload-free
omission diagnostics. The existing staging-priority test still requires an
interleaved risk command between the 256/44-row chunks; only the expected final
completion command was appended. Two in-memory reversals were detected: crediting
time after the read started, and treating a pass with omitted prior fills as
repaired. No source files were changed by those fault injections.

`scripts/benchmark_history_coverage.py`: disposable WAL/FULL, 2ms heartbeat,
tracemalloc, fixture construction excluded. Both predeclared budgets pass:

| Rows / receipts / inspections | Wall / CPU s | Inspection p50 / p95 / p99 ms | Loop p99 ms | Peak bytes | Max finalization ms |
|---|---|---|---:|---:|---:|
| 128 / 30 / 30 | .1055 / .0938 | 1.412 / 1.640 / 1.898 | 7.046 | 108,331 | 9.868 |
| 4,096 / 120 / 120 | 1.6683 / 1.6094 | 5.709 / 8.865 / 9.315 | 29.716 | 2,504,801 | 215.938 |

The first 4,096-row implementation finalized in 340.425ms; the indexed batch read
and binary digest reduced that measured owner hold to 215.938ms. Finalization is
still a bounded owner transaction, not zero-latency work; maximum 10,000-row and
4,096-receipt saturation latency is not established by this diagnostic. No live
venue latency, account eligibility or profitability claim. Final full-suite
result is recorded in STATUS.md. Local preflight reports `live_ready=false`,
native exit 2, no credentials/network accessed and no files created.

## Remaining work

Bounded production metadata-refresh scheduling can proceed independently. Do not
keep rebuilding these history receipts or call them complete account proof.
Before live activation, establish the actual launch boundary/starting inventory
and resolve history/private-stream/cash completeness. Questions needing primary
venue evidence or clarification (not sent by this task):

- Is there a documented common watermark or replay mechanism tying private
  executions to REST fill/order/position/cash reads?
- Is history publication delay bounded, and how can a consumer know an interval
  is final, including reconnect gaps and late corrections?
- Which authoritative records and identity rules handle settlement/correction
  reconciliation, without inventing reversal fills or resetting receipt windows?

Keep missing answers explicit. No new baseline, old-fill classification, cash
policy, automatic correction, market selection, capital/risk change or live
process was installed. Polymarket was neither changed nor used to assert a new
inherited rule; this is Kalshi-specific evidence bookkeeping. Git metadata remains
unavailable in this folder; no commit/diff or remote parity is claimed.
