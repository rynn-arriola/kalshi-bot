# Shared write-quota document ingestion — D-062, priority 4

Offline implementation, 2026-09-21. `WriteQuotaSource` consumes the existing
guarded `RestReads` control-plane pair; it does not issue its own requests,
poll per market, infer tier numbers or create an order transport. Mandatory
`offline_fixture=True`; no account requests/credentials are used in verification.

Attach once before reads are used. The existing refresh/supervisor reads costs
then limits through the same account-wide Read allowance, validates full write
method/path costs, installs the read lease and only then publishes the matching
write snapshot. The same write-budget object survives refresh with zero tokens,
revoked permits and preserved 429 pauses. Before initial publication, access is
blocked. Refresh starts by revoking write permission; malformed/failed pairs,
near-grant rollover, closed reads, stopped owners, changed scope/signers and
stale/clock-faulted read leases cannot leave old write authority available.
The dispatcher checks this source again at permit consumption. No second
scheduler, retry loop, listener or account owner is added.

## Sources and limits

Current public official documents checked on 2026-09-21:
[limits](https://docs.kalshi.com/api-reference/account/get-account-api-limits),
[endpoint costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs),
[rate limits](https://docs.kalshi.com/getting_started/rate_limits).
The local API reference's operations/response schemas were also checked.
Numeric write rate/capacity and method/path/default cost come from the same
bounded observation pair; explicit exchange routing retains existing shard
semantics. Read and Write allowances stay separate. No source establishes
available server tokens; local cold/refresh balances therefore start at zero.
TTL starts before collection and the guard's grant margin remains binding.
REST is required for these quota fields; no equivalent stream is documented.

Fee metadata already has an event/series/lifecycle producer. Real member-class
and rounding-profile verification remains required. Current
[fee rounding](https://docs.kalshi.com/getting_started/fee_rounding) distinguishes
member classes; decimal formatting alone is not membership evidence. This
milestone does not fabricate a fee profile or complete production fee readiness.

## Acceptance declared before measurement

Offline injected HTTP documents and actual read guard/write budget owners;
tests for exact costs, one coalesced pair, partial/malformed/failed refresh,
stale permits, TTL/grants/clocks, scope changes, stop, cancellation, shared
supervision and dispatcher send-edge failure. Resource fixture: 30/120 explicit
shards, eight refreshes, one reserve/consume per shard per refresh; 16 GETs
regardless of shard count, CPU <1 second, allocation <8 MiB, pair p99 <100ms,
event-loop lag p99 <50ms. Fixture counts are not live scale/latency promises.

## Verification

Native Windows commands:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bot_write_quota_source.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bot_quota*.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B scripts/benchmark_write_quota_source.py
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

28 new source/dispatcher tests and 62 existing quota/supervisor tests passed.
Actual dispatcher tests prove durable ACK on valid evidence, zero invocation
with UNKNOWN after quota expiry during SENDING, and old-permit rejection when
a new pair publishes during that handoff. Reader shutdown, consumer cancellation,
late publication, invalid cost routes, grant rollover, cached/future caller
clocks and replaced ownership are covered. An in-memory bypass of the source
fence makes the grant-margin regression fail; source files were not weakened.

Final-source resource results (eight observations per pair percentile; nearest
rank, so p95/p99 are the observed maximum, not a production-tail estimate):

| Shards / commands | Injected GETs | Pair p50/p95/p99 ms | Loop p50/p95/p99 ms | CPU / wall seconds | Peak bytes |
|---|---|---|---|---|---|
| 30 / 240 | 16 | 2.098 / 5.421 / 5.421 | 2.577 / 5.219 / 5.219 | .0312 / .0482 | 171,821 |
| 120 / 960 | 16 | 2.307 / 2.615 / 2.615 | 4.454 / 12.371 / 12.371 | .1094 / .1053 | 64,096 |

All declared component budgets passed. No real network latency/account data
was measured. Disabled preflight returned native exit 2, `live_ready=false`,
and no file creation, credentials or network access.

Actual diff review covered pair provenance, full versus GET-only cost
projection, snapshot immutability, permit expiry, refresh/close races and
existing supervisor ownership. Review added a sticky fence for replaced
reader/guard/source identities. No blocking issue remains in this offline
component scope. The final complete suite ran **1,130 tests: 1,129 passed and
one expected Windows symlink-privilege skip**, in 158.807s. Local links in all
nine changed Markdown files and whitespace checks passed. D-065 publication
requires scoped staged/secret review, commit, push and remote parity; it does
not deploy or restart a bot.

Follow-up: [owned mutation outcomes](BUILD_MUTATION_OUTCOMES.md) now connect
429 pauses and recovery requests while retaining durable UNKNOWN. Process-local
cooldowns, explicit resumption policy, fee-profile verification and supervised
trading-runtime composition remain separate readiness work.
