# D-072 entry-pair dispatch and mutation transport

Implemented on native Windows in `C:/Users/rynna/Bots/kalshi`. This work connects
the selected Kalshi quote pair to the existing risk, durability, quota and
recovery owners. It does not activate live trading.

## Contract

The runtime queues only a market reevaluation key. The dispatch source refreshes
the actual account report, managed plan, reward selection, market metadata and
writer view after quota reservation. It builds one immutable bid/ask pair for
the same ticker, subaccount and exchange route. The writer either reserves both
legs in one transaction or rolls back both; existing cash, fee, accounting,
stop-loss, exposure, 10-contract and 30-resting-entry checks remain authoritative.

The dispatcher then consumes one exact batch permit at the synchronous send
edge and performs one `POST /portfolio/events/orders/batched`. Official Kalshi
documentation charges batch creation per order and assigns batch endpoints to
the unscoped shard, so a two-leg pair consumes twice the observed endpoint cost
from shard 0. Safety cancels and reducers retain higher priority.

The venue batch is not promoted to an atomic result. Each response row is bound
by `client_order_id`. Two acknowledgements continue through normal order-stream
reconciliation. A documented per-row error becomes durable `REJECTED` evidence
for only that client. A mixed response latches the executor/dispatcher failed
and requests reconciliation. A row without client identity, timeout, HTTP
failure, cancellation or malformed response makes both legs `UNKNOWN`; no
automatic retry occurs.

The bounded V2 transport supports:

- single order creation for existing passive/IOC inventory reducers;
- single order cancellation with signed query scope;
- exact two-order batch creation for new entry pairs.

It follows no redirects or proxies, limits response bytes/time, emits numeric
HTTP status only, and never logs response bodies. `MutationSigner` signs only
those exact order operations. The production wire remains unavailable to the
autonomous runtime. D-076 now issues only a one-use canary
`MutationActivation` bound to an exact full batch digest, ticker, account route
and client IDs; normal runtime and offline paths still cannot open live
authority. Tests inject a non-network wire and ephemeral RSA key.

## Primary contract evidence

- [Batch Create Orders V2](https://docs.kalshi.com/api-reference/orders/batch-create-orders-v2)
- [Batch Cancel Orders V2](https://docs.kalshi.com/api-reference/orders/batch-cancel-orders-v2)
- [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2)
- [Cancel Order V2](https://docs.kalshi.com/api-reference/orders/cancel-order-v2)
- [Rate limits and tiers](https://docs.kalshi.com/getting_started/rate_limits)
- [Exchange sharding](https://docs.kalshi.com/getting_started/exchange_sharding)
- [Endpoint costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs)
- [Local complete reference](KALSHI_API_REFERENCE.md)

The V2 schema permits a nullable client ID on an errored batch row and does not
provide an identity guarantee through row position. The implementation therefore
does not infer identity from response order.

## Verification

Focused offline checks cover all-or-none pair reservation, one-batch submission,
two-unit unscoped quota charging, partial ACK/reject, unidentified errors,
HTTP 429 pause ownership, signed payload/path constraints, single reducer/create
and cancel transport, actual runtime selection handoff, runtime queueing and
cold restart of mixed outcomes. The dispatcher family and write-budget suites
also pass.

Final full suite: `python -B -m unittest discover -s tests -q` — 1,339 tests,
1,338 passed and one expected Windows privilege skip in 186.923 seconds.

`scripts/benchmark_entry_dispatch.py` uses disposable ledgers and injected local
I/O only:

| Markets/pairs | Prepare p99 | Abort p99 | Loop p99 | CPU/pair | Peak bytes | Backlog/held after |
|---:|---:|---:|---:|---:|---:|---:|
| 30 | 8.964 ms | 4.532 ms | 10.899 ms | 11.458 ms | 3,016,774 | 0 / 0 |
| 120 | 11.065 ms | 7.090 ms | 7.794 ms | 9.766 ms | 84,005 | 0 / 0 |

Both declared synthetic gates pass. These measurements cover local
prepare/abort handoff, not venue latency, profitability or production throughput.
Disabled preflight remains expected exit 2 with `live_ready=false`, no file
creation, credential access or network access.

## Remaining boundary

Priority #2 is complete in execution-disabled scope. Production own-order/public-
book reward reflection and checkpoint lifecycle (#3), verified real fee/timing/
account/quota evidence, native supervisor S2B/readiness and explicit launch
approval remain. No real database was opened and no venue/account operation,
bot process, order or cancel occurred.
