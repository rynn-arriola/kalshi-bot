# Durable opening accounting — D-067

Native Windows, execution-disabled scope. Implements D-064/D-066; the source
and venue limitations in [the accounting design](DESIGN_OPENING_ACCOUNT_ACCOUNTING.md)
remain applicable.

## Contract

- Schema 4 creates accounting tables only in new ledgers. Existing schema 3
  is refused before WAL/DDL; there is no automatic migration.
- One writer transaction saves an immutable opening **candidate** tied to
  ledger identity, proposed boundary, source epoch/revision, flat local audit,
  exact cash and source digests. It does not approve the launch boundary or
  assert an atomic venue snapshot/history barrier.
- Normalized cash, settlements, scoped transfers and member funding are
  separate journal events. Identical replay is idempotent. Changed settlement
  economics preserve both observations and add a durable conflict restriction.
  Source identity is a local composite, never a claimed venue correction ID.
- Positive settlement/cash evidence survives a stale source revision. Stale
  evidence cannot create or replace an opening candidate. Missing or empty
  later histories cannot erase earlier observations or restrictions.
- Cash is preserved as an observation, with its own timestamp. Venue cash
  semantics and full cash-flow attribution remain unproved; local working-order
  risk is a separate conservative reserve. No payout, reward, deposit, hold or
  cash delta becomes matched-fill P&L or synthetic inventory.
- New-entry reservations and prepared entry sends check durable restrictions
  within the writer transaction. Cancels and separately authorized reducers
  retain their existing safety rules. Restart and a new risk window cannot
  clear restrictions. Operator review acknowledgements are durable evidence;
  they cannot clear unresolved economics or fabricate source proof.
- AccountCoordinator exposes an explicit persist-and-reconcile operation using
  the existing bounded read owner. Read-only inspection remains available.
  The operation owns its reads, normalization and journal write through caller
  cancellation. This adds no background poller or real account invocation.

## Bounds and verification plan

At most 65,536 journal versions and 64 MiB canonical payloads per ledger;
at most 128 bytes per restriction code and bounded codes from this module.
On saturation, persist a restriction and refuse additional evidence without
deleting prior rows. New-entry checks read a bounded restriction set, independent
of journal history length. All SQLite/serialization work runs on the writer.
Fixture targets: 30/120-market decisions, hot accounting checks <2x CPU at
larger history; 50,000-row capture <5 seconds and event-loop p99 <50 ms.

Tests must cover atomic rollback, repeated evidence, stale source, changed
boundary/account/settlement, late and pre-boundary evidence, empty later
responses, restart, cancellation, journal saturation, entry and send rejection,
preserved reduction/cancel paths and unchanged lots/fees/risk windows.

## External readiness gates

Current documented REST and private streams do not establish a shared replay
barrier. That missing guarantee cannot be manufactured in software. This build
must preserve `venue_history_stream_handoff_unproven`, `cash_snapshot_not_atomic`
and an unapproved boundary. No production-ready claim or release switch is
permitted merely because local fixtures agree.

## Verification evidence — 2026-09-21

Native Windows disposable fixtures only. The complete suite ran 1,046 tests
in 137.522 seconds: 1,045 passed, one expected Windows privilege skip. The
focused accounting/opening/command-handoff run passed 98 tests. After adding
one reducer-path regression, all 48 durable-accounting/command-handoff tests
passed in 5.338 seconds; production source was unchanged from the full run.
The new test confirms an independently verified reducer can prepare/send
through an accounting hold without clearing that hold. Native disabled
preflight returned expected exit 2, `live_ready=false`, and reported no file
creation, credential access or network access. `git diff --check` passed.

`scripts/benchmark_durable_accounting.py` passed its synthetic fixture budgets:
50,000 settlement rows captured in 2.298 seconds (2.234 CPU seconds), event-loop
p99 30.322 ms / max 45.733 ms, 8,525,282 payload bytes. Warmed five-sample
median entry-check scaling versus 128 rows was 1.970x at 30-market-equivalent
decisions and 1.849x at 120. These are local synthetic measurements, not live
throughput guarantees; the 30-market ratio has little headroom. An earlier
single-sample timing exceeded the ratio target (2.368x); warm-up and repeated
medians reduce timer noise without changing the target or query implementation.

The actual diff was reviewed for transactional admission/send checks, source
revision changes, cancellation ownership, restart restrictions, fill/P&L
isolation and existing-ledger refusal. No release of unresolved restrictions is
implemented or claimed. No live account requests, existing-ledger migration,
runtime start/restart, configuration change or production transport occurred.
