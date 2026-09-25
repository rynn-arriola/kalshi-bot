# Queue depletion withdrawal — D-120

## Inputs and interpretation

The existing account-scoped `GET /portfolio/orders/queue_positions` reflection
read now retains exact `queue_position_fp` quantities and its monotonic request
start. No additional REST request, subscription, writer or database is added.
The identity join still requires all expected resting IDs, current account
report/generation/revision and exact order terms. Queue age is bounded to five
seconds from request start; a reconnect during a read cannot seed the new epoch.

Current normalized WebSocket books provide aggregate volume at equal/better
prices, excluding this order. Between queue reads, observed decreases reduce
estimated protection; additions do not invent same-price priority. A fresh exact
queue read resets this conservative estimate. Aggregate decreases can include
cancellations behind us, and coalesced observations can miss transient changes.
This is a depletion scenario, never a probability of avoiding a fill.

The existing scoring function determines reference price at cumulative
`target_size / 5`. Status shows target, reference depth/price, actual estimated
ahead quantity and its ratio to reference depth. The target is **not** substituted
for actual volume ahead. Changing program/target, order size/price, book epoch,
account epoch, writer or a long observation gap resets the trend. Ordinary
selection retains its target-aware score and reward-quality filters.

Sources verified 2026-09-24:

- [Queue positions](https://docs.kalshi.com/api-reference/orders/get-queue-positions-for-orders)
  and the exact schemas in [API reference](KALSHI_API_REFERENCE.md).
- [Book updates](https://docs.kalshi.com/websockets/orderbook-updates) provide
  aggregate levels, not individual same-price queue priority.
- [Liquidity scoring](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program)
  defines the one-fifth reference and per-program target depth.

## Decision and lifecycle

Estimated seconds until our order is reached = estimated contracts ahead /
recent depletion contracts per second. Preserve the fastest observed rate for
ten seconds; zero protection triggers immediately, while positive protection
without a rate is `WARMING_UP`, not guaranteed safe.

Withdraw if that time is no greater than:

`max(2 seconds, decision-to-cancel-ACK p95) + reflection interval + queue age + 1 second`

Defaults live in `FillRiskPolicy`; samples retain at most 256 orders and 128
cancellation timings. Measure from the withdrawal decision through the durable
ACK, including dispatch/quota/reconciliation waiting, separately for each leg.
Only successful observations contribute; this is not a worst-case latency bound.

Either threatened leg withdraws the owned pair through existing QUOTE_CANCEL,
without the normal 30/90-second scoring dwell. An idle ordinary repricing cycle
can yield to risk withdrawal; no in-flight mutation is preempted. One risk pair
drains at a time, beneath safety cancels and inventory exits in dispatch priority.
The decision stays latched for exact IDs while cancellation reconciles; it does
not authorize new orders or cancel a foreign/reducing order. Partial fills hand
back to the existing inventory exit policy. ACK alone cannot release capacity.

After terminal/fill reconciliation, ordinary reward ranking selects another
eligible market ($2 priority, $1 fallback), under all existing limits. The old
market is excluded for five minutes after withdrawal finishes. Cooldown/trend
state is process-local and scoped to retained subscriptions, reset on restart;
it is not durable accounting. No position is force-closed by this feature.
Risk takes precedence over accumulating the $1 estimate on the withdrawn market.

## Verification

`tests/test_bot_fill_risk.py` covers bid/ask depletion, target-driven reference
changes, no invented queue protection, warmup, stale/long reads, reconnects,
bounded history and actual manager/dispatcher withdrawal. It verifies cancel
ACK vs terminal reconciliation, partial-fill handling, cooldown and replacement
ranking. Existing scoring/maintenance/reward/dispatch tests remain required.

Resource acceptance: 30/120 synthetic orders, 100 levels per side, 20 evaluations
per order; p99 per estimate below 50 ms and traced peak below 4 MiB. These are
offline computation checks, not live escape-rate or profitability evidence.
Final test counts and publication/deployment state belong in STATUS.
