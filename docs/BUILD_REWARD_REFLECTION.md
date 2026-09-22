# D-073 — Production reward reflection and checkpoint lifecycle

## Result

The existing estimate-only reward tracker now has one runtime-owned production
reflection source and one checkpoint lifecycle owner. It does not gain order,
exit, accounting or live-activation authority.

Kalshi's public book WebSocket is aggregate price-level data and does not carry
own-order identity. The private order WebSocket carries order identity but does
not prove that the same order is represented in a particular aggregate book
snapshot. The documented authenticated
`GET /portfolio/orders/queue_positions` endpoint fills only that missing identity
gap: Kalshi describes its response as queue positions for all resting orders.
One account-wide read is therefore joined to the current complete private
resting-order enumeration. No per-market reflection poller was added.

The join requires all of the following:

- the current, fresh reconciled private-account report and exact subaccount;
- exact equality between every private resting order ID/ticker and every queue
  response row, with duplicate, malformed and excess rows rejected;
- exact agreement between each tracked order's market, side, price, remaining
  quantity and exchange index in the private snapshot and durable inventory;
- fresh program, market terms and aggregate WebSocket book sources; and
- sufficient aggregate quantity at each exact own-order level when the existing
  scorer removes the owned quantity before computing the reference score.

The proof expires within five seconds and is revoked by account/order/source
changes, mismatch, malformed data, rate/quota failure, stopping or stale inputs.
The private snapshot, queue read and public stream are not one atomic venue
snapshot, so this remains a conservative sampled estimate. It is not reward
credit, payment, cash, P&L or permission to keep an unsafe position open.

## Runtime ownership

`RecoveryRuntime.attach_rewards` accepts an explicit JSON checkpoint path and
bounded engineering intervals. The runtime loads an existing checkpoint before
starting event tasks, supervises one reward service, stops it before reader/task
teardown and waits for its final checkpoint flush. A checkpoint parent directory
must already exist; construction creates no path or file.

The default account-wide reflection interval is four seconds, below the existing
five-second maximum source validity. Checkpoints coalesce to one write every 60
seconds plus one final joined flush. Both intervals are configurable within
bounded ranges. Atomic replacement and `WindowsLease` still prevent partial or
competing files from being accepted. Restored totals never restore a live sample;
downtime remains unknown.

Expected network/data failures revoke current estimated rates and appear in
status without interrupting inventory management. Unexpected service failure is
propagated through the runtime supervisor. Repeated cancellation cannot abandon
the owned service or checkpoint operation, and stopping during a queue read
cannot publish late proof.

## Source and rate-limit policy

The queue-position route is an authenticated, allowlisted `reflection` read in
the existing `RestReads` service. It uses the shared account quota/token budget,
in-flight coalescing and background headroom. There is no second REST budget and
no order-book REST duplication. Aggregate market state remains WebSocket-first.

Official sources inspected 2026-09-22:

- [aggregate order-book updates](https://docs.kalshi.com/websockets/orderbook-updates)
- [private user-order updates](https://docs.kalshi.com/websockets/user-orders)
- [all resting order queue positions](https://docs.kalshi.com/api-reference/orders/get-queue-positions-for-orders)

## Acceptance and limits

Focused coverage includes exact account/queue joins, structurally new management
plans, missing/extra/duplicate/malformed rows, account-source races, stop races,
service failure propagation, final checkpoint flush, restore-without-live-sample
and the narrow REST route contract. Existing tracker bounds remain: 30 actual
quote rows per sample, 16 programs per market and 4,096 retained programs.

Verification on native Windows:

- 47 reward/reflection/checkpoint tests pass; 196 focused reward, REST-budget,
  selection and recovery-runtime tests pass.
- Final full suite: 1,347 tests in 171.937 seconds; 1,346 pass and one expected
  Windows symlink-privilege test skips.
- Existing representative reward benchmark passes at 30 markets/300 updates
  (0.3906 CPU seconds, 157,633 peak bytes, 2.106 ms update p99) and 120
  markets/1,200 updates (1.3906 CPU seconds, 527,876 peak bytes, 1.990 ms
  update p99). Reflection adds one account-wide read rather than market tasks.
- Byte compilation, disabled preflight (`live_ready=false`, expected exit 2),
  whitespace, local-link, scoped secret and actual-diff checks pass.

No credential was opened, no account/venue request was sent, no bot was started,
and no order, risk setting or runtime configuration was changed by this build.
Personal paid reward reconciliation remains unavailable through the documented
API and must stay visibly unverified.
