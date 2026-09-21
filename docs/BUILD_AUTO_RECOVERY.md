# D-025 automatic recovery — 2026-09-20

Native Windows component implementation; live activation remains disabled.
Operator instruction: "Just do something like polymarket." D-025 records the
accepted scope. No paper process, real account calls, credentials, orders,
services, historical migration/deletion or Polymarket edits occurred.

## Reference and venue evidence

Read-only reference: `C:/Users/rynna/Bots/liquidity-bot`, clean HEAD
`54ac71a241d1ad6f02e3445655bb7115247bac02` (rechecked this session).
The preceding code audit verified `live_commissioning.py:2641-2679` automatic
execution application, `execution_ledger.py:1804` immutable deduplication,
`inventory_basis`/`_venue_basis` around 1412/1467, and explicit trade-state
reversals around 1685. Its 68 execution-ledger tests passed in that preceding
audit, not rerun here. Executable fallback, not older strict-basis comments,
is the reference. Kalshi does not import its optional-history safety policy.

Official contracts rechecked this session:

- [Market positions stream](https://docs.kalshi.com/websockets/market-positions):
  signed quantity and `position_cost_dollars` current basis; fee cost separate;
  optional account scope and no documented shard field in this payload.
- [REST positions](https://docs.kalshi.com/api-reference/portfolio/get-positions):
  `market_exposure_dollars` describes aggregate position cost. Do not use total
  turnover as current basis. REST fills missing authoritative snapshot fields.
- [Fills](https://docs.kalshi.com/api-reference/portfolio/get-fills): immutable
  execution evidence. No matching Kalshi trade-bust lifecycle signal was
  established in the inspected contracts; do not fabricate one.

## Implemented boundaries

`account.py` fetches/stages bounded history, attempts at most 32 distinct missing
order bindings, uses 404-only archive fallback and caches only requested archive
identities. Exact durable intent terms establish ownership. Unbound/foreign
fills stay unimported. Conflicting identities/scope fail closed.

`writer.py` imports at most 32 fills per transaction on the single SQLite worker.
Each fill updates its own loss ratchet before the next fill. A later invalid fill
rolls back the whole chunk. Earlier committed chunks survive interrupted runs;
retry deduplicates them. Receipt time is taken after awaited reads, with stable
execution-time/identity order for newly observed history. Existing receipts and
already applied fill order are never rewritten. Recovery reports remain not ready.

`position_basis.py` keeps venue cost outside fills/lots/realized accounting. Fresh
coordinator evidence, explicit account/shard, exact net owned-order quantity and
no ambiguous intent are required. Local quantity-matching basis is preferred;
otherwise cost per contract supplies an exit-only YES-equivalent price (one
minus cost for NO inventory). This does not prove complete history or submit an
exit. First-observed age survives restarts/additions/partial closes, resetting
on observed flat/reversal. It is not a recovered historical acquisition time.
Matching fresh sufficient stream cost is retained over REST cost evidence.

Schema 2 gains optional observational `venue_costs` and derived `realized_totals`
tables. No old account database was opened; schema 1 is still refused. Derived
totals commit/rollback with risk and fills, scan a cold window once, then only
new append-only journal rows. Future journal pruning or economic corrections
need explicit atomic invalidation/rebuild, not silent edits under a cached total.

Bounds remain: history 10,000 rows/eight MiB, order evidence 4096, bindings 32,
replay chunks 32, observational retention 4096 with active-market capacity,
single bounded writer queue. Capacity exhaustion blocks; no automatic deletion.

## Verification

`python -B -m unittest discover -s tests -q`: 371 tests pass, 36 new.
New coverage includes deduplication/restart, post-read receipt windows, direct
and archived bindings, foreign orders, scope/economic conflicts, lookup bounds,
per-fill ratchets, chunk rollback, interrupted replay/retry, exit-only fallback,
NO conversion, missing ownership, staleness/disconnect, first-seen persistence,
stream cost preference, ambiguous intents and derived-total consistency.

Two temporary offline safety reversals were detected and restored:
removing net-owned-quantity agreement failed two tests; including the already
processed cursor row failed four tests. Final restored suite passes.
Credential-free preflight must remain `live_ready=false` (expected exit 2).

## Local resource diagnostic

`scripts/benchmark_auto_recovery.py`: injected reads, disposable seeded WAL/FULL
ledger, actual automatic coordinator recovery, tracemalloc and 2ms heartbeat.
Setup excluded. Declared before measurement: completion under existing five
seconds, replay-batch p99 below 100ms, loop-lag p99 below 50ms, incremental Python
peak below 40MiB. No budgets were relaxed. Synthetic orders are one contract,
not a change to the approved 10-contract entry policy.

| Workload | 128 fills / 30 markets | 1024 fills / 120 markets |
|---|---:|---:|
| Wall / CPU seconds | .2208 / .2031 | 1.6215 / 1.5625 |
| Batch ack p50/p95/p99 ms | 40.119 / 41.714 / 41.714 | 36.996 / 46.730 / 46.784 |
| Loop lag p50/p95/p99 ms | 11.518 / 14.976 / 14.976 | 11.967 / 14.867 / 15.626 |
| Incremental Python peak bytes | 625132 | 2095188 |
| Heartbeats / max sampled backlog | 19 / 1 | 125 / 1 |
| Diagnostic passed | yes | yes |

Initial larger run took 5.0559s (batch p99 253.152ms) and expired recovery.
Incremental sums alone completed in 3.1878s but still failed batch p99 at
140.442ms. Avoiding per-fill inventory allocations produced the table above.
Single local runs with tracing and Windows timer granularity, not a live SLA,
network latency test, maximum-capacity/long-history/reconnect acceptance or
profitability estimate. Cold totals still require an indexed window scan.

## Remaining work

Full historical coverage and stream continuity, starting-inventory completeness,
settlements/corrections, continuous fill-before-order recovery supervision,
retention and outage tests, production risk/execution wiring, approved deadline
mapping and limits-driven exposure integration. Unknowns still block new risk.
These components do not authorize live entry or prove the bot live-ready.
Kalshi has no usable Git metadata here; no Git diff/parity/commit claim is made.
