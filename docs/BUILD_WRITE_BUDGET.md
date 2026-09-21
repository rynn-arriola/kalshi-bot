# Offline write-budget primitive — D-062 / priority 4

September 21, 2026. [Design](DESIGN_WRITE_BUDGET.md). This is a local arithmetic
and evidence component, not production mutation transport or an exit dispatcher.

`write_budget.py` adds immutable full-document quota observations, normalized
method/path costs, explicit shard buckets and bounded single-use permits.
The caller supplies clocks and freshness; no I/O, tasks, sleeping, credentials,
ledger changes or runtime wiring exist. `offline_fixture=True` is mandatory.
Subaccounts share a configured account owner, and another budget instance is
not a coordinated global account allowance.

Cold start and refresh begin with zero local tokens. Outstanding reservations
count against burst capacity, preventing a second burst from accumulating behind
unconsumed permits. Exact rational arithmetic avoids granting tokens through a
floating-point tolerance. Consume checks issued-object identity and stored
immutable terms. Discard/failure does not refund. Expiry and clock rollback
invalidate permissions; rollback latches the instance closed. Refresh preserves
429 pauses, and a late old-revision 429 still invalidates the current shard.

Primary review found all-shard refills on every operation. The fix refills only
the addressed shard during healthy reserve/consume/discard; full telemetry may
scan the bounded set. Snapshot deadlines are cached once, route normalization
uses a bounded cache, identical validated clock samples are reused and reserve
shares a readiness pass. Scope, stale evidence, permit identity and exact token
checks are preserved. Retained dispatcher cleanup can discard an outstanding
permit without refund and treats a consumed/absent permit as a no-op.

## Verification and limits

- 33 deterministic budget tests pass after the hot-path corrections; combined
  dispatcher/budget focused run: 45 tests in 1.211s.
- Current combined source-tree suite: 1,013 run, 1,012 passed, one expected
  Windows symlink-privilege skip in 134.462s. Compilation and `git diff --check`
  pass. The earlier 999-run result covered the budget before dispatcher work.
- Tests cover method/default costs, document mutation, shard separation and
  shared-subaccount accounting, exact refill boundaries, hold capacity, copied/
  tampered/reused permits, TTL/grants, refresh, late 429, clock rollback, caps
  and explicit refusal of live, automatic-route and batch modes.
- The prior 12,000-command run missed the <250 ms total CPU target at 390.625
  ms; this original failure is retained here, not presented as clearance.
- `scripts/benchmark_write_budget.py` now runs five untraced synthetic workloads
  then a separate full-workload allocation trace. Latest 30/120-shard results:
  3,000/12,000 commands, maximum CPU 46.875/187.5 ms, wall 45.220/185.396 ms,
  peak Python allocation 7,140/22,572 B. Both pass <250 ms CPU and <8 MiB peak;
  no REST, 429, external shared usage or full-runtime performance is measured.

Follow-ups implemented: [source-bound candidates](BUILD_DISPATCH_SOURCES.md)
and [shared quota ingestion](BUILD_WRITE_QUOTA_SOURCE.md) now connect to the
[offline dispatcher](BUILD_WRITE_DISPATCHER.md). Next: owned 429/outcome recovery,
supervised lifecycle and receipt ownership. Transport, shared external
account usage, real grants/costs and production probe policy remain unbuilt or
unverified. No venue write or account request occurred.
