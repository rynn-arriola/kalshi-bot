# Kalshi rate-limit handling — D-036, September 20, 2026

Review update: [Astra review](REVIEW_D036_ASTRA.md) reproduced priority admission
and head-wait reconfiguration gaps (R2/R4). Sol fixed these, added regressions
and reran the token resource checks. Critical reads retain two in-flight admission
entries when capacity permits; one-entry configurations cannot reserve a slot.
[Astra re-review](REVIEW_D036_ASTRA_R2.md) cleared these fixes in scope;
STATUS holds Sol's prior final full-suite result. Live readiness remains blocked.

Subsequent D-039 implementation: [quota freshness and grant expiry](BUILD_QUOTA_FRESHNESS.md).
Both design phases now exist as opt-in lease/dispatch enforcement and automatic
supervision. Independent review is pending. The D-036 history below describes
the earlier explicit/unmanaged path; it is not the full guarded-mode contract.

## Verified contracts and scope

Primary sources checked this session, alongside exact local OpenAPI operations,
`BucketLimit`, `GetAccountApiLimitsResponse` and endpoint-cost schemas:

- [Rate-limit guide](https://docs.kalshi.com/getting_started/rate_limits): token
  buckets, separate Read/Write budgets, REST/FIX sharing, 429 backoff and per-item
  batch charges. No documented Retry-After/rate headers on 429 at this check.
- [Account limits](https://docs.kalshi.com/api-reference/account/get-account-api-limits):
  authenticated GET supplies actual refill and capacity, plus tier/grants. Never
  derive capacity from tier name or treat capacity as current available tokens.
- [Endpoint costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs):
  public GET supplies default and method/path overrides. Default applies to routes
  not listed. Preserve method distinction and normalize the API prefix once.

The guide currently describes two seconds of Basic Read capacity; the earlier
September 20 account inspection returned 200/s and 600 capacity. Preserve that
dated observation, but do not hardcode either capacity: fresh account payloads
configure the limiter. No account call was made during this implementation.

## Implemented reads

`RestReads.refresh_budget()` performs one explicit coalesced pair of quota GETs
using the caller-supplied bootstrap budget/signer. Both responses must validate
before updating the existing shared budget. It never loads keys, upgrades tiers,
opens a bot or starts periodic account polling. Concurrent callers share that
refresh; a canceled caller cannot cancel the shared operation.

`TokenBudget.from_documents` now starts with zero locally available tokens by
default. Limits do not report server token balance. Explicit constructor/fixture
initial balances remain supported. Reconfiguration also starts empty, keeps any
429 pause, and preserves counters. Actual venue usage by other processes remains
unknown; this is a conservative LOCAL scheduler, not the server bucket itself.

Account/recovery reads take priority over waiting metadata/incentive work, FIFO
within each priority. No lock is held while sleeping for tokens. Followers wait
on queue-change events instead of polling. Default document-built background
headroom is one default-cost request, capped so an otherwise valid full-bucket
request can still fit. It is a local scheduling choice, not a venue entitlement.
With >=2 transport slots, background traffic cannot occupy the final slot;
concurrency=1 necessarily has no transport reservation. Priority cannot interrupt
an already dispatched request or guarantee account response latency.

Every retry/page spends tokens at its endpoint's cost. All 429s, including the
final rejected attempt and a response received after its caller deadline, clear
the local estimate and extend shared bounded
exponential backoff. This pause is a client choice, not a claimed venue penalty.
Tiny positive waits are rounded UP to a microsecond to avoid non-advancing float
clock loops; token grants are never rounded up. Failed/ambiguous requests are not
refunded. Waiters, in-flight requests, retries and transport slots remain bounded.

Runtime telemetry exposes local rate/capacity, spent tokens, queued requests,
background reserve, throttle count, configuration revision/age. Stable safe
`read_budget_updated`/`read_budget_failed` diagnostics contain no raw account
payload. Scheduler work reuses this service, never creates a per-market bucket.

## Writes and remaining launch work

Write limits returned by refresh are informational only; there is NO production
write limiter/transport enabled here. The current guide distinguishes explicitly
sharded single writes, unscoped shard 0, auto-routed writes and unscoped batch
charges. REST/FIX can share Write buckets. Do not multiply a global Read budget
by the number of sockets/shards, or bill a batch as one request. Exact write-cost,
shard routing and cancel/exit priority must be implemented with the eventual
mutation transport and reverified then. No upgrade endpoint was called.

Before production: supply a reviewed explicit bootstrap/probe quota, refresh actual
account documents and share one account-wide budget. D-039 adds optional supervised
refresh and quota-TTL/grant-expiry enforcement; production wiring/configuration
and independent review remain required. Account proof, market approvals and separate live authorization still
block trading. No new live request/market/risk capacity was selected.

## Verification plan and results

The initial 13 focused tests exercise priority, reserved transport/headroom, exact costs,
document coalescing, cold-start tokens, reconfiguration, malformed documents,
capacity/cancellation and terminal 429 handling. The existing concurrency test
still checks the same two-slot total bound, now with both background and priority
traffic. Its initial-burst cost fixture explicitly requests its initial tokens.

Predeclared additional token-only load fixture: 30/120 simultaneous acquisitions,
200 tokens/s, 600 capacity, zero initial tokens, cost 10, no wire calls; wall
<3/10s, CPU <1/3s, loop lag p99 <50ms, incremental peak <8MiB and spent tokens
bounded by generated tokens. Pending count cannot exceed the configured 128.
Token wait time is expected, not a network-latency benchmark.

`scripts/benchmark_rate_limits.py` results on native Windows:

| Requests | Tokens spent | Wall / CPU s | Peak bytes | Loop lag p50 / p95 / p99 ms | Token wait p50 / p95 / p99 ms |
|---:|---:|---:|---:|---:|---:|
| 30 | 300 | 1.5639 / 0.0781 | 115,881 | 13.799 / 14.340 / 15.400 | 757.439 / 1452.463 / 1499.711 |
| 120 | 1200 | 6.0652 / 0.5000 | 373,368 | 13.709 / 14.571 / 14.929 | 3005.063 / 5758.459 / 5948.466 |

Both fixtures pass every predeclared bound, including exact token spending.
Removing shared 429 throttling in memory makes its regression fail as intended;
the original implementation is restored. No live 429/capacity experiment or
account call. See `../STATUS.md` for final full-suite results and
[scheduler verification](BUILD_METADATA_SCHEDULER.md) for metadata workloads.

Sol reran this unchanged workload after R1-R4. For 30/120 requests, exactly
300/1200 tokens were spent. Wall time was 1.5513/6.0624s, CPU 0.0469/0.4375s,
peak Python bytes 120,519/376,456 and loop lag p99 15.127/15.187ms. Both pass
the original bounds. The rate focused suite now contains 18 tests.
