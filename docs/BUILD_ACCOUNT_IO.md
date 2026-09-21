# Account evidence and durable I/O milestone

Historical milestone record. The subsequent
[owned-order/recovery milestone](BUILD_RECOVERY_ORDERS.md) supersedes the
unimplemented projection/history items below where explicitly described.

2026-09-19–20; handoff completed September 20. Continues D-021 on native Windows.
**No live activation.**
The earlier [component foundation](BUILD_FOUNDATION.md) remains in place.
This milestone connects injected account reads/fills to durable local state;
it is not a complete trader or a complete account-recovery algorithm.

## Implemented

| Module | Verified behavior |
|---|---|
| `writer.py` | One bounded queue and one SQLite-owning thread; construction/use/close on that thread; async durable acknowledgements; caller cancellation cannot silently cancel an accepted fill; errors/overflow poison the owner and reject later work |
| `ledger.py` / `risk.py` | Composable transactions/savepoints; each writer fill commits its lots, close P&L and risk-window ratchet together, before the next command; later profits cannot erase an intermediate loss tier |
| `account.py` | Single-loop owner, connection generations, revision/token barriers, exact REST normalization, local inventory comparison and explicit mismatch/unknown-order blockers |
| `rest.py` | Fixed-host GET allowlist; required fallback reasons; shared read-token budget and in-flight requests; bounded workers/retries/pages/bytes; authentication signing, blocking HTTP and JSON decode off the event loop |

Intent reservation and transitions also use the writer. Acknowledgement follows
commit, UNKNOWN cannot return to SENDING, and queued intent payloads are frozen.
There is still no executor: durable-before-send integration cannot be claimed
until an executor actually uses those acknowledgements.

Account reconciliation explicitly selects a caller-specified subaccount, all
exchange shards and no market filter. It exhausts resting-order/nonzero-position
pages and reads balance, then compares inventory against the local ledger.
It never imports unexplained inventory as zero-cost lots, turns absent orders
into confirmed cancellations, or substitutes balance/P&L fields for closed-fill
accounting. Aggregated balance is not proof of collateral on a particular shard.

Any account event invalidates the snapshot token before awaiting disk work.
An event/reconnect during either REST retrieval or the subsequent ledger read
prevents publication of that snapshot. Both UTC and monotonic age checks apply;
five seconds remains a conservative development gate, not an accepted live SLA.

## REST source and trigger map

All calls are explicit library invocations: **no background poller or live CLI**.

| Read | Reason / trigger | Current limitation |
|---|---|---|
| `/portfolio/orders`, `/portfolio/positions` | Startup, gap evidence or explicit reconciliation because updates do not enumerate all existing state | Enumerated pages are not an atomic account snapshot |
| `/portfolio/fills`, `/historical/fills`, `/historical/cutoff` | Missing execution history/gaps | Raw retrieval only; no complete history merge, replay or proof of subaccount scope for historical fills |
| `/portfolio/balance` | Missing cash information or reconciliation | Not a trading-loss meter or shard-local buying-power proof |
| `/account/limits`, `/account/endpoint_costs` | Explicit rate-budget discovery | Caller must provide a bootstrap budget; no account tier is assumed, no automatic budget increase |
| `/incentive_programs` | Incentive definitions absent from streams | Uses `next_cursor`, not portfolio `cursor`; definitions are not personal paid-reward evidence |
| `/markets/{ticker}` | Full metadata/ticks missing from streams | Raw metadata retrieval; no quote selector or versioned TTL cache yet |

Read budgets use tokens and endpoint route costs, not requests/sec copied from
Polymarket. The parser accepts the published `read.refill_rate`,
`read.bucket_capacity`, `default_cost` and GET overrides. The service has no
write/mutation method. Authenticated requests require an explicitly supplied
signer; imports and constructors never load files or credentials.

Official pages rechecked for this implementation:
[positions](https://docs.kalshi.com/api-reference/portfolio/get-positions),
[orders](https://docs.kalshi.com/api-reference/orders/get-orders),
[fills](https://docs.kalshi.com/api-reference/portfolio/get-fills),
[balance](https://docs.kalshi.com/api-reference/portfolio/get-balance),
[incentives](https://docs.kalshi.com/api-reference/incentive-programs/get-incentives),
[limits](https://docs.kalshi.com/api-reference/account/get-account-api-limits),
[costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs),
[rate rules](https://docs.kalshi.com/getting_started/rate_limits), and
[private positions](https://docs.kalshi.com/websockets/market-positions).
The [local complete reference](KALSHI_API_REFERENCE.md) and exact cached operation
schemas were also consulted. Public documentation checks did not access an account.

## Resource and failure behavior

- Default writer queue: 256 commands; configured range 1–8192. One worker per
  ledger, not per market. Default inventory capacity 128 is a development
  ceiling, not an approved managed-market count. Intent payloads max 16 KiB.
- On queue overload, the caller receives a failure and the owner is poisoned.
  An already-running transaction may commit; queued work is explicitly rejected.
  Never assume every submitted command committed or every failed caller did not.
  Reconcile persisted IDs before resuming. No unsafe automatic replay occurs.
- Default REST concurrency 2 (max 4), at most 32 distinct in-flight requests
  (configurable max 128), 2 MiB per body (max 4 MiB), 50 pages, 10,000 rows and
  8 MiB per enumeration. Parsed-object memory is additional to wire bytes.
- Three total attempts only for 429/500/502/503/504; 429 drains/pauses the shared
  bucket with bounded exponential backoff/jitter. Auth/client/redirect failures
  are not retried. Body/error text is not included in raised transport errors.
- GET transport disables redirects and proxy auto-discovery. Body reads have
  socket and elapsed-time checks; requests/enumerations have deadline checks.
  Blocking OS DNS/TLS calls are not forcibly preempted: deadlines reject late
  results, not a hard process-level cancellation guarantee.
- Cancellation of one REST waiter does not cancel a shared request or free a
  worker slot early. `close()` drains outstanding reads. There is no persistent
  response cache or independent automatic retry/poll/reconnect loop.
- Shutdown drains accepted writer work unless poisoned; concurrent close callers
  wait for the same thread. Cancelled startup cleans up its non-daemon worker.
  Unexpected worker termination resolves waiting commands as failed.

## Verification

**159 tests passed** on native Windows/Python 3.14.7: original 110 plus 49 new
integration/fault tests. `pip check` passed. Fixtures use temporary SQLite files,
injected HTTP responses and local concurrency barriers; no real account keys,
exchange socket sessions, orders, cancellations or transfers were used.

Two deliberate offline reversals verified detection, then were restored:

1. Removing the outer fill+risk transaction caused the injected risk-failure
   test to find an incorrectly committed flat position instead of the original
   10-contract lot.
2. Removing both reconciliation-token checks caused a stale flat snapshot to
   publish after a fill; the stale-response regression failed as intended.

Additional coverage includes loss-before-profit ratchets across restart,
duplicate/conflicting fills, writer overflow/failure/cancellation, intent
ambiguity, excessive inventory, REST concurrency and cancellation sharing,
malformed/oversized JSON, pagination cycles/bounds, token costs/backoff,
missing account scope, delayed storage and mismatched positions.

### Offline writer benchmark, not live performance acceptance

Run with `.\.venv\Scripts\python.exe -B scripts/benchmark_writer.py`.
Four open/close cycles per synthetic ticker, size 10, equal prices and zero fees;
one durable acknowledgement awaited at a time. Fresh temporary WAL/FULL SQLite,
tracemalloc enabled, 2ms heartbeat. No income/reward/trading strategy simulation.

| Synthetic tickers / fills | Wall / CPU seconds | Fills/sec | Durable ack p50 / p95 / p99 ms | Loop lag p50 / p95 / p99 ms |
|---|---|---|---|---|
| 30 / 240 | 0.4903 / 0.4219 | 489.5 | 1.655 / 2.925 / 3.719 | 0.790 / 2.322 / 9.223 |
| 120 / 960 | 2.2077 / 1.9375 | 434.9 | 2.097 / 3.634 / 4.339 | 0.667 / 2.394 / 3.379 |

Heartbeat sample counts: 160 and 767. Traced incremental peaks: 1,196,457 and
112,789 bytes; first-case one-time initialization affects that comparison.
Backlog at each awaited acknowledgement was zero by construction. Overflow is
tested separately; this is not a saturation/backlog benchmark. The larger case
also has more retained closes, so it is not an isolated market-count comparison.
Window P&L is still scanned on the worker; long-history optimization and
retention remain future work. No total-process memory, idle CPU, network
throughput, simultaneous feed/disk load or fill-to-exit latency claim is made.

## Still blocked / next integration

Reconciliation reports **always have `ready_for_entry=False`**. Matching current
positions does not prove complete execution history, absence of unseen delayed
events, or private-stream continuity. Private order/position/group messages
currently invalidate evidence; they do not yet maintain full owned-order
projections. The coordinator requires explicit fill subaccount information;
the optional field's absence blocks processing rather than guessing primary.

Still needed: confirmed stream/account entitlement and scope; complete history
bootstrap and gap replay; cross-channel state barriers and owned-order terminal
proof; buffered stream integration and independent recovery; priority scheduling
across readers/REST/safety deadlines; metadata cache invalidation; an injected
executor; exact quote/exit integration and Windows graceful operational control.
The existing named Windows lease is not yet wired into a runtime launcher.

Operator decisions on market slots, partial-close/late-fill/fee attribution,
event deadlines, expiry and resume remain unchanged. No new policy was selected.
No deployment, auto-start, paper run, old-data deletion, WSL operation or
Polymarket edit occurred. This Kalshi folder still is not a usable Git checkout;
no commit/push/parity claim is made.
