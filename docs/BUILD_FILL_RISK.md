# Queue depletion withdrawal — D-120

## Inputs and interpretation

The existing account-scoped `GET /portfolio/orders/queue_positions` reflection
read now retains exact `queue_position_fp` quantities and its monotonic request
start. No additional REST request, subscription, writer or database is added.
The identity join still requires all expected resting IDs, current account
report/generation/revision and exact order terms. Queue age is bounded to five
seconds from request start; a reconnect during a read cannot seed the new epoch.

### D-127 order-scoped observation after publication

The successful existing reflection read publishes a separate immutable queue
anchor to maintenance **before** optional reward/metadata joins. A later account
report replacement or reward-source gap does not erase this cancellation-only
observation. Its original wall-clock expiry and request-start monotonic age
(less than five seconds) are retained, never renewed by a cache read.

Each use still requires current writer-issued inventory, identical order IDs,
prices, remaining quantities and routes, the same writer/account/book epochs,
a fresh WebSocket book and no pending private processing or inventory blockers.
Foreign/reducing/terminal orders and fills cannot reuse the anchor; positions
hand back to the existing exit policy. Program binding changes invalidate it.
Queue anchors and depletion history are bounded by the existing 256-order
estimator capacity and replaced/pruned on successful queue publication.

Only detection and the existing exact-ID D-121 cancel path are independent of
report renewal. Ordinary repricing, reward accounting, terminal completion and
replacement entry retain their account/scoring gates. No new REST reads,
subscription, task, writer, threshold or ranking policy is introduced. This does
not provide monitoring before the first valid queue read, during expired/missing
queue or book evidence, or while private fills are pending. It cannot guarantee
avoiding an instantaneous sweep. See [bounded diagnostics](LOGGING_AND_ERRORS.md).

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

### D-121 cancellation scheduling correction

The exact latched risk pair now drains like the existing owned-entry stop path:
each ID obtains fresh durable ownership/route/revision evidence, with no full
account recovery required between its two cancellations. No other ID or reducer
is eligible. Entry authority is revoked immediately; ACK does not free capacity,
authorize a replacement or prove absence of a fill. After the bounded queue
drains, ordinary account recovery supplies those proofs. A 404, ambiguous result,
lost connection, changed cycle or writer failure still blocks or reconciles.
Actual fills continue through the existing inventory handler.

Recovery joins the sole dispatcher's outcome persistence before starting its
REST pass. Observation still revokes authority immediately; the two outcome
notifications coalesce instead of racing an unfinished durable write. Timing
samples retain the complete decision-to-ACK delay; the estimator is not clamped
to hide slow cancellations. This changes scheduling, not the risk threshold.

Successful recovery/renewal promotes the current maintenance market for fresh
evaluation, including a canceled owner now absent from active inventory. Its
terminal/fill proof must still pass before finishing withdrawal. Cooling or
otherwise maintenance-ineligible markets retain advisory priority memory but
cannot occupy pending priority-refresh slots or block other eligible markets.
Cooldown expiry restores ordinary revalidation; no stale hint authorizes entry.

### D-128 retained scheduling intent

A transient source/private-work fence may consume a dispatcher key without
submitting its cancellation. The source retains one current risk-cycle marker,
not a command/price/ownership lease. Private-event completion and the existing
half-second refresh owner requeue reevaluation with at least 250 ms backoff;
ordinary book wakes respect that backoff. Eight temporary blocks or five seconds
without progress hand back to bounded recovery. In-flight outcomes are joined
before escalation, and an ACK resets the per-leg retry window.

Routine renewal/post-drain recovery cannot treat the empty queue as completion
while that marker remains pending. A successful current durable no-candidate
read ends fast draining, not terminal/fill reconciliation. Replaced cycles,
stop, permanent rejection and UNKNOWN do not authorize retransmission. No new
REST polling, task or mutation owner is introduced. Deferred threat keys wake
after dispatch/cycle completion and must pass fresh observations again.

`risk_cancel_deferred` logs fixed blocker names at powers-of-two counts;
dispatch status exposes `risk_drain_pending` and `risk_cancel_deferrals`.
`risk_cancel_retry_exhausted` identifies bounded recovery escalation. Existing
`fill_risk_cancel_ack.elapsed_ms` includes first-warning-to-latch delay, not
just transport. Correlate withdrawal and submission events to separate stages.

## Verification

`tests/test_bot_fill_risk.py` covers bid/ask depletion, target-driven reference
changes, no invented queue protection, warmup, stale/long reads, reconnects,
bounded history and actual manager/dispatcher withdrawal. It verifies cancel
ACK vs terminal reconciliation, partial-fill handling, cooldown and replacement
ranking. Existing scoring/maintenance/reward/dispatch tests remain required.

`tests/test_bot_risk_observation.py` exercises D-127 report and metadata gaps,
runtime dispatch scheduling, exact pair cancellation without capacity release,
expiry/clock regression, source identity, pending fills/private backlog,
inventory handoff, bounded caches and sampled/correlated diagnostics. A same-
fixture replay of baseline `5cf92c5` misses the zero-depth warning during report
invalidation; the patched consumer latches withdrawal without changing inputs.

Resource acceptance: 30/120 synthetic orders, 100 levels per side, 20 evaluations
per order; p99 per estimate below 50 ms and traced peak below 4 MiB. These are
offline computation checks, not live escape-rate or profitability evidence.
Final test counts and publication/deployment state belong in STATUS.

`tests/test_bot_risk_dispatch_retry.py` reproduces the missing automatic second
key and covers private/source races, send-edge rejection, wake coalescing,
backoff, retry bounds, in-flight join, cycle/stop/disconnect changes, UNKNOWN,
permanent rejection, post-drain ordering and deferred threat wakeups. All venue
responses and ledgers are synthetic/disposable.
