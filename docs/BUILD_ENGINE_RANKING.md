# Quote/ranking and event/command milestone

Verified September 20, 2026, on native Windows. D-021 authorizes construction,
not activation. The operator also requested market rankings in this session.
**This remains an incomplete, execution-disabled build.**

## Implemented

- `quoting.py`: Decimal Reference Price and snapshot-share calculations, entire
  cutoff-level accounting, two-sided depth and 10-contract reference proposals.
  Proven reflected own orders are removed before proposed orders are added.
  The caller must prove public/private synchronization; arithmetic alone cannot
  establish which owned orders appear in a public-book version. Uniform grids
  only; variable-band reward ticks remain unconfirmed and blocked.
- `ranking.py`: bounded per-market views sorted explicitly by remaining gross
  reward, hourly gross reward or hourly gross reward per dollar committed.
  Different program quote proposals are not summed. Inventory blocks entries;
  expired/revoked data loses its ranking. Program account caps block estimates
  until accrual/cap semantics can be resolved. Always `trade_ready=False`.
- `metadata.py`: bounded keys/bytes, caller-supplied TTL, shared in-flight reads,
  copied returns, clock guards and revocation defeating late replies. Fetches
  are injected; no new polling loop or adopted refresh policy.
- `engine.py`: injected account handling, independent book shards, coalesced
  changed-market decisions and independent deadlines. Private events precede
  public/quote work; deadlines survive private floods. All deltas are applied.
  Decisions yield per market and stop for arriving private events/timers.
  Book overflow/gaps invalidate the shard and its rankings; private failure
  halts the owner. Reconnect epochs are explicit, not automatic recovery.
- `execution.py`: offline-injected create/cancel lifecycle with durable
  preparation and SENDING before invocation, immutable scoped requests,
  pre-send proof rechecks and ambiguity retention without blind retries.
  Flat V2 acknowledgements never invent order states, executions, fees or
  flat/cancellation proof. Unknown reservations persist across restart.
  **No authenticated write transport or production admission gate exists.**
- `windows.py`: native cross-process stop-request event, separate from the
  ownership mutex. Requests to an absent owner create no stale event. This
  primitive does not cancel venue orders, liquidate inventory, install services
  or provide a live launcher. Stop/join an owner before closing its handle.

The SQLite mutation journal is additive and limited to 4,096 attempts pending
an archival contract. No old database was opened/migrated. Metadata cache,
discovery, real reader generations and production risk reservations still need
runtime integration. Fill-before-order binding races still require recovery.

## Ranking interpretation

Rows show proposed Reference Prices, order dollars, snapshot share, gross hourly
flow and remaining-period arithmetic. Capital sums both orders conservatively,
not exchange-netted margin. Two proposals use two entry slots: 30 orders are not
30 two-sided pairs. One candidate program is shown per market in each view;
overlapping programs with incompatible prices are not added together.

These estimates assume unchanged competition, qualifying depth and continuous
resting orders. They are not earned/paid rewards or expected net profit. Fill
probability, loss, fees, qualification uptime, account eligibility, prior accrued
score, minimum payout and final rounding are not modeled. Net profit stays
unknown. A sub-$1 remaining estimate cannot determine the final program payout
without earlier accrual. Ranking views are not automatic allocation authority.
No current venue ranking was fetched or presented as real in this session.

## Sources rechecked

The local API reference's exact operations and schemas were consulted.
Current official pages rechecked September 20:

- [Liquidity scoring](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program):
  target/5 reference, full price weight distinct from pool share, two-sided depth.
- [V2 create](https://docs.kalshi.com/api-reference/orders/create-order-v2):
  acknowledgement identifiers/counts/timestamp, not a full legacy Order.
- [V2 cancel](https://docs.kalshi.com/api-reference/orders/cancel-order-v2):
  explicit account/shard routing and acknowledgement distinct from full order proof.

No keys, real account calls, live streams, venue writes or paper runs were used.
Polymarket remains clean at `54ac71a241d1ad6f02e3445655bb7115247bac02`.
Kalshi Git metadata remains unusable; no commit/push/parity claim.

## Verification

`python -B -m unittest discover -s tests -q`: **280 tests passed**, including
68 new checks and all 45 legacy regressions. Coverage includes quote/rank math,
expiry/caps/overlaps, cache races, priority/overflow/deadlines, ambiguous sends,
restart, Windows cross-process control, and a combined book -> ranking -> fake
create -> owned order -> partial fill -> cancel-required -> terminal proof ->
exact three-contract reducer fixture. This does not approve candidate accounting.

Two deliberate reversals failed focused tests: skipping removal of reflected
own size; permitting revoked metadata's late reply to publish. Both restored
before the complete suite. Dependency check passed; preflight remains blocked.
No live integration was tested.

### Resource checks

`scripts/benchmark_engine.py`: 30/120 synthetic markets, two shards, 40 levels
per side, initialization plus 20 delta bursts, one durable risk observation per
burst. Includes queue encoding, books, Decimal quote/ranking and local WAL/FULL
risk writes; excludes network/fills. Tracemalloc enabled; memory is incremental
allocation, not process RSS. Before execution, diagnostic budgets were set to
p99 event-to-rank <=500ms, loop lag <=100ms, private-to-durable-risk <=100ms and
<=32 MiB traced memory. These are development checks, not approved live SLAs.

| Metric | 30 markets | 120 markets |
|---|---:|---:|
| Events / ranking evaluations | 651 / 630 | 2,541 / 2,520 |
| Wall / CPU seconds | 1.5309 / 1.5156 | 8.1178 / 7.4062 |
| Event-to-rank p50/p95/p99 ms | 37.187 / 78.873 / 166.329 | 200.534 / 387.465 / 481.628 |
| Private-to-durable-risk p50/p95/p99 ms | 1.797 / 2.136 / 2.136 | 3.109 / 6.255 / 6.255 |
| Loop lag p50/p95/p99 ms | 5.095 / 7.568 / 13.276 | 6.335 / 10.844 / 15.102 |
| Heartbeat samples | 206 | 915 |
| Queue high-water | 31 | 121 |
| Incremental peak bytes | 1,900,887 | 3,136,375 |
| Diagnostic budgets | Pass | Pass |

The initial implementation failed lag/ranking budgets. Reusing validated
ladders, avoiding duplicate quote-book reconstruction and yielding bounded
decision batches corrected it. Early runs overlapped other test work, so this
is not a controlled before/after experiment; the final run was standalone.
The 120-market ranking result has little headroom and is not permission to scale.
No saturation, live capacity, reconnect-storm or long-history claim follows.
Default queues have separate 8,192-message/16MiB budgets per lane (one private,
two public); caches/storage have their own bounds. No unbounded queue was added.

## Remaining work / decisions

1. Approve partial-close/fee/late-fill attribution; complete replay, corrections,
   settlement, archived terminal orders and coherent startup/gap recovery.
2. Integrate atomic account-wide risk reservations, real reader generations,
   cache/discovery/ranking invalidation, control and read-budget bootstrap into
   a supervised runtime. Injected proof callbacks are not risk enforcement.
3. Decide market slots, automatic selection/repricing, Kalshi deadlines, expiry,
   IOC exits and resume rules. No undecided policy was inferred.
4. Complete write budgets/transport, outage protection and Windows launch/stop
   orchestration; review end-to-end recovery and obtain separate live authority.
   The stop primitive alone is not a graceful trading shutdown policy.
