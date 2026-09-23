### Reward API recheck — September 22, 2026

[Re-audit](REWARD_API_REAUDIT_2026-09-22.md): fresh public specifications still
expose one dedicated reward-definition operation, `GET /incentive_programs`.
Its 10,000 maximum page size and response schemas are unchanged from the saved
reference. Our 100-row runtime setting underuses that contract; a research-only
1,000-row enumeration retrieved 4,981 programs in five pages / 1.986 seconds.
Documented WS `get_snapshot` is another unused implementation option. No personal
reward-credit API or reward stream was found. No runtime change is included.

### Dated contract update — September 21, 2026

The current official [historical fills operation](https://docs.kalshi.com/api-reference/historical/get-historical-fills)
now documents `subaccount` (0 primary, 1–63 numbered; omitted means all). A
restricted key must match the requested scope. This supersedes only the missing
historical-fill parameter in the September 19 captured reference and D-044's
dated description. Recovery now sends the scope and rejects conflicting row
scope. Cursor exhaustion still establishes enumeration only, not continuity.

The [balance contract](https://docs.kalshi.com/api-reference/portfolio/get-balance)
reports integer cents alongside precise `balance_dollars`, without specifying
legacy rounding. Opening evidence preserves both, rejects differences of one
cent or more, and labels smaller differences unverified rather than rounding
cash or assuming a conversion rule. Aggregate exchange breakdowns must agree.
The [settlement contract](https://docs.kalshi.com/api-reference/portfolio/get-settlements)
allows absent/null `value`; it is a per-YES-contract payout in cents, not total
revenue. Cash-history inspection requires explicit terminal cursors even where
the schema marks them optional; missing cursors are incomplete evidence.

### How to use this reference

Start from the method/path index, read the operation and its referenced schemas,
then check the linked official page for changes. Required fields, nullable fields,
default values, enums, numeric limits, content types, status codes, examples,
deprecation flags, and vendor extensions are retained in the specification blocks.
An omitted constraint is not permission to invent one. A published endpoint does
not establish that this account has the required tier, entitlement, or key scope.

The reference covers public documentation, not undocumented private website APIs.
Predictions, perpetuals, clearing-member APIs, REST, WebSocket, and FIX must remain
distinct. Institutional endpoints are included for completeness, not selected for
the liquidity-reward bot.

### Environments and authentication

Use `https://external-api.kalshi.com/trade-api/v2` for production REST and
`wss://external-api-ws.kalshi.com/trade-api/ws/v2` for production WebSocket.
The older shared `api.elections.kalshi.com` hosts remain documented. Demo credentials
are separate from production credentials. Sources:
[environments](https://docs.kalshi.com/getting_started/api_environments.md),
[WebSocket overview](https://docs.kalshi.com/websockets.md).

Authenticated Trade API calls use `KALSHI-ACCESS-KEY`,
`KALSHI-ACCESS-TIMESTAMP`, and `KALSHI-ACCESS-SIGNATURE`. Construct the signed payload
from the millisecond timestamp, uppercase method, and full URL path including the
API prefix but excluding query parameters. Sign using RSA-PSS/SHA-256 with digest-length
salt, then base64 encode. Do not double the `/trade-api/v2` prefix in the URL.
Source: [authenticated requests](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md).

The clearing-member specification has its own server and bearer-token scheme;
do not send ordinary Trade API credentials to that service. See its global
settings and security schemes in this reference.

### Current event-order interface

Event-order writes use `/portfolio/events/orders`, with separate read endpoints
under `/portfolio/orders`. Creation requires `ticker`, `side`, `count`, `price`,
`time_in_force`, and `self_trade_prevention_type` in the captured V2 schema.
Quantities and prices are fixed-point strings. `side=bid` buys YES;
`side=ask` sells YES, economically buying NO at the complementary price.
For example, buying NO at $0.30 is an ask at YES price $0.70.
Source: [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2.md).

Creation supports `post_only`, `reduce_only`, `cancel_order_on_pause`, and
`order_group_id`. For timed expiry, use `time_in_force=good_till_canceled` with
`expiration_time` in epoch seconds. `GTT` is not an accepted API enum and IOC
cannot be combined with that expiration field. These are documented capabilities;
this project has not verified them by placing an order.

Amend `count` is total allowable fills, including already-filled quantity, not
just new remaining quantity. Decrease requires exactly one of `reduce_by` and
`reduce_to`. V2 cancellation returns identifiers and `reduced_by`, not the full
legacy order object. Sources:
[amend](https://docs.kalshi.com/api-reference/orders/amend-order-v2.md),
[decrease](https://docs.kalshi.com/api-reference/orders/decrease-order-v2.md),
[cancel](https://docs.kalshi.com/api-reference/orders/cancel-order-v2.md).

### Direction, ticks, and fractional fills

Canonical response direction is `outcome_side` or `book_side`; YES corresponds
to bid and NO to ask. Public trades use the `taker_*` versions. Legacy
`action`, `side`, `is_yes`, `purchased_side`, and `taker_side` are deprecated.
WebSocket book pricing needs explicit attention: the documented default uses
NO-leg prices on the NO side; `use_yes_price=true` requests a common YES-price
scale. A later default change and eventual flag removal are announced without
fixed dates in the captured guide. Do not infer this convention from a side name.
Source: [order direction](https://docs.kalshi.com/getting_started/order_direction.md).

Read each market's `price_ranges` and choose the band containing the proposed
price. Do not infer the tick from gaps in resting depth, use a single minimum
step for every band, or hardcode the `price_level_structure` label.
Contract counts support 0.01-contract granularity, including fills of otherwise
whole-contract orders. Use decimal arithmetic. Sources:
[fixed-point representation](https://docs.kalshi.com/getting_started/fixed_point_migration.md),
[Market schema](https://docs.kalshi.com/api-reference/market/get-market.md).

The guide discusses four-decimal quote prices while `FixedPointDollars` in the
current operation schemas permits responses with up to six decimals. Preserve
response precision rather than truncating all monetary fields to four places.

### Fee accounting

The rounding guide describes six-decimal trade fees plus a balance-alignment
adjustment and an order-level accumulated rebate. Balance precision differs
between direct and non-direct members. Preserve actual returned fee amounts
and partial-fill accounting; a simple per-order ceiling is insufficient for
general reconciliation. Source:
[fee rounding](https://docs.kalshi.com/getting_started/fee_rounding.md).

Series and event fee configuration can differ and change over time. Inspect
the documented series/event fee fields and fee-change endpoints. An old blanket
maker rate or a historical replay assumption is not current account evidence.

### Rate limits and exchange shards

Rate limits are token budgets, not raw request counts. The captured guide sets
the ordinary request cost at 10 tokens, with exceptions obtained from
`GET /account/endpoint_costs`. Read and Write buckets are separate; REST and FIX
share applicable budgets, while perpetuals have separate budgets. Batch requests
charge per item. Read current account limits rather than reusing a historical tier.
The guide reports no `Retry-After` or `X-RateLimit-*` headers on 429 responses.
Source: [rate limits](https://docs.kalshi.com/getting_started/rate_limits.md).

Read the market's `exchange_index`; ticker syntax alone does not identify its
shard. Automatic routing for cancellation needs `market_ticker`; an order ID
alone is insufficient. Balance and subaccount collateral can be shard-local.
Order groups do not span shards. Transfers and target-allocation changes are
separate account mutations, not an implied prerequisite to a documentation read.
Source: [exchange sharding](https://docs.kalshi.com/getting_started/exchange_sharding.md).

Source discrepancy: the FIX connectivity page says RFQ quote accepts bill the
unscoped Write bucket; the general rate-limit guide says RFQ writes bill shard 1.
Both statements are retained in the source cache. Confirm the applicable policy
before implementing RFQ traffic; do not silently select one.

### Cancellation, pauses, groups, and reconciliation

An event-market cancel-all operation may span every shard and, without a
subaccount filter, all subaccounts. Its documented cancellation window can also
catch newly created orders. It is not equivalent to canceling only this bot's IDs.
Source: [cancel all](https://docs.kalshi.com/api-reference/orders/cancel-all-orders.md).

During a trading pause, cancellation remains available; during an exchange pause
it does not. Resting orders normally survive unless configured to cancel on pause.
The published maintenance window is Thursday 03:00–05:00 Eastern; consult the
exchange status and schedule rather than relying on a fixed timetable.
Source: [maintenance](https://docs.kalshi.com/getting_started/maintenance_and_pauses.md).

Order groups count filled quantity over a rolling 15-second window and can cancel
group orders and block further placement. This is not a dollar-loss stop. The
guide alternates between reaching and exceeding the threshold; boundary semantics
must not be inferred. Reset enables new orders and clears the rolling counter.
Source: [order groups](https://docs.kalshi.com/getting_started/order_groups.md).

The user-data timestamp endpoint explicitly warns of delayed read visibility.
Reconcile mutation responses, private order/fill events, and account reads. A
missing order immediately after a timeout does not prove placement failed.
Source: [user-data timestamp](https://docs.kalshi.com/api-reference/exchange/get-user-data-timestamp.md).

### WebSocket integration

Both full AsyncAPI specifications are included below: handshake requirements,
control frames, subscribe/unsubscribe/update commands, stream payloads, enums,
examples, and errors. Predictions and margin have different payload contracts.
For the event order book, subscribe using market tickers, initialize from the
snapshot, then apply deltas. The channel supports requesting a new snapshot
without altering the market subscription. Source:
[order-book updates](https://docs.kalshi.com/websockets/orderbook-updates.md).

Authentication is required during connection setup even for some public-data
channels. Use the specified stream sequence fields and refresh state when continuity
cannot be established. Example code is illustrative; it is not this project's
implemented reconciler.

### Historical queries and pagination

Retrieve `/historical/cutoff` and use the cutoff for the requested data type.
Live endpoints do not guarantee all older fills, completed orders, or settled
positions. Resting orders and unsettled positions remain live. Events and series
remain on their original endpoints. Complete history may require both live and
historical endpoints, pagination, and deduplication. Source:
[historical data](https://docs.kalshi.com/getting_started/historical_data.md).

### CF Benchmarks REST passthrough — outside the OpenAPI inventory

Kalshi also documents `GET /cfbenchmarks/{upstream_path}` relative to the Trade
API base. Examples are `/cfbenchmarks/values` and `/cfbenchmarks/history/values`.
It requires Kalshi authentication and a suitable entitlement; responses wrap
upstream data in `data`. `includeVerification` is ignored. Other supported query
parameters are passed through. The documented cost is 50 Read tokens. A SHIB
index value is not automatically rescaled to kSHIB or a contract size.
Kalshi does not enumerate every upstream path/schema; the external upstream
reference remains necessary. Source:
[passthrough](https://docs.kalshi.com/cfbenchmarks/rest-passthrough.md),
[upstream REST reference](https://docs.cfbenchmarks.com/api/category/rest/).

### FIX transport and access

Predictions production order entry uses `mm.fix.elections.kalshi.com`; market data
uses `marketdata.fix.elections.kalshi.com`. Margin uses
`margin-mm.fix.elections.kalshi.com` and `margin-marketdata.fix.elections.kalshi.com`.
Use TLS 1.2 or later, FIXT.1.1, and FIX50SP2. The technical material below preserves
port/TargetCompID mappings and message-tag tables. One connection is allowed per
API key; concurrent sessions require separate keys. Some services require
institutional entitlement. Sources:
[Predictions FIX](https://docs.kalshi.com/fix/connectivity.md),
[margin FIX](https://docs.kalshi.com/fix-margin/connectivity.md).

### Changelog and dated statements

The fetched changelog includes a future-dated September 24, 2026 entry about the
orders cutoff. This snapshot was retrieved September 19, so do not treat that
entry as proof of an already-deployed behavior. September 17 entries describe
WebSocket schema corrections, historical `min_ts` support, and FIX replay
allowlisting. Fetch the current contract before use. Source:
[changelog](https://docs.kalshi.com/changelog/index.md).

### Project decisions remain separate

The operator requested planning only, no bot construction or paper-testing stage,
a $500 capital ceiling, and fewer than 10 contracts per order. A $10 loss stop
was suggested by the assistant, not accepted by the operator. Credential use
has been authorized when needed, but documentation retrieval does not need it.
This reference makes no live order, transfer, or arming decision.
