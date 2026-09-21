# D-032 — Inventory exit planning, execution disabled

Verified 2026-09-20 in `C:/Users/rynna/Bots/kalshi`, native Windows.
The operator approved this build milestone, not starting a trader. No credentials,
private venue calls, real orders/cancels, ledger imports or paper process used.

## Source and API trace

Read-only Poly checkout: `C:/Users/rynna/Bots/liquidity-bot`, clean HEAD
`51cf59548b8e339be790e0662b6594ff0af77ddc`. Executable `reconciler.py`
(`exit_quote_price`, `_passive_inventory_plan`, inventory exit planning) and
`commissioning.py` supply the rules below; 104 relevant reference tests pass.
No Poly file changed. Kalshi has no Git metadata: no commit/diff/parity claim.

Rechecked official [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2)
and [Get Market](https://docs.kalshi.com/api-reference/market/get-market), with
the exact local OpenAPI request/market schemas in `api-specs/openapi.yaml`.
V2 uses YES-book bid/ask direction. IOC cannot carry `expiration_time`; this
adapter uses `post_only=false`, `reduce_only=true` and exact remaining quantity.
`close_time` is a trading boundary. `expected_expiration_time` and
`latest_expiration_time` do not establish an event-risk start. Early-close risk
must be resolved by a verified market-specific producer, not inferred away.

## Implemented behavior

- `exits.py`: pure bounded advisory plans. A long reducer joins the ask, or
  improves one valid tick only if still at/above basis and strictly above bid;
  the inverse applies to short YES-equivalent inventory. Losing inventory joins
  touch without an entry-price floor. Preserve an already exact touch reducer.
- Cancel inventory-building orders before replacing reducers. All reducers use
  exact remaining inventory, including fractional contracts; no imported Poly
  tiny-residue exception and no percentage liquidation.
- Ordinary evaluation at 900 seconds. Estimate displayed executable depth with
  a 50% haircut and the supplied per-contract fee upper bound. Defer while depth
  is insufficient or projected P&L is below -$8 at the approved size-10 setting.
  This is a projected exit threshold, not the separate six-hour $25 stop and
  not a guarantee of realized loss.
- A verified event-risk time minus five minutes, or explicit maintenance/HARD
  flatten time, can override ordinary deferral. Trading close bounds deadlines;
  at/after close the planner requests attention, never assumes trading remains
  possible. Forced evaluation may use full displayed depth after haircut failure.
  Insufficient full depth requests attention; no guaranteed flattening claim.
- Cancel one working owned order at a time, building orders first. Cancel ACK,
  disappearance and restart do not prove terminal/fill completion. Five-second
  cancellation attention and ten-second IOC confirmation attention operate even
  when account proof is incomplete. At most three IOC attempts in thirty seconds;
  unknown submissions cannot be blindly retried.
- `portfolio.py` derives basis and attempt state in the single writer, from
  existing durable lots/intents/order/mutation evidence. An additive ticker/time
  index bounds the query; its 4,096-row cap fails closed. Partial fills keep the
  episode clock; confirmed partial IOC completion replans only the remainder.
- `management.py` binds plans to account/writer/book revisions and immutable,
  expiring exit terms; replacements invalidate outstanding plans. Existing
  bounded timers wake deadline evaluation without market updates. `engine.py`
  stamps public messages at ingress; delayed dequeues cannot freshen old books.

All plans have `authorized=false`. Existing mutation execution is injected and
offline-fixture gated; request validation now accepts only reducing IOC in
addition to existing passive GTC. No authenticated write transport was added.
The planner's passive sub-plan alone must never bypass its mode/proof blockers.

## Verification and measured limits

`python -B -m unittest discover -s tests`: **569 pass in 45.424s**.
The exit-focused module contributes 59 executed cases (including inherited
management regressions), not 59 unique new behavioral scenarios. Coverage:
pricing/band boundaries, depth/loss/fees, exact IOC shape, cancel/fill races,
partial fills, unresolved restart, stale queue ingress, replaced terms and
independent timers. Two in-memory safeguard reversals were detected: removing
pending-cancel proof and disabling IOC reduce-only. Disposable process only.
CLI preflight still exits 2 with `live_ready=false`.

Predeclared planner diagnostic: 30/120 markets, 64 levels per side, ten
evaluations per market, wall budgets 2/8 seconds, per-plan p99 <=50ms.

| Markets | Evaluations | Wall seconds | CPU seconds | Plan p99 ms |
|---|---:|---:|---:|---:|
| 30 | 300 | 0.064680 | 0.062500 | 0.398500 |
| 120 | 1,200 | 0.279580 | 0.281250 | 0.437900 |

Existing disposable WAL/FULL inventory diagnostic also passes unchanged budgets:
local read p99 <100ms, portfolio p99 <250ms, loop-lag p99 <50ms, incremental
traced peak <40MiB. At 30/120 markets respectively: local p99 1.241/1.111ms,
portfolio p99 6.646/24.947ms, loop-lag p99 15.650/14.027ms, peak
1,133,998/258,601 bytes. Small single-host fixtures, not production service
latency, exchange throughput, memory-residency or reward profitability evidence.

## Remaining work

`ExitTerms` is a validated input contract, NOT a verified production feed.
Implement market-specific event/early-close provenance, current tick bands and
conservative live fee bounds, WebSocket first with missing-field REST fallback.
Missing timing/fees block taker proposals; missing/stale terms block exit planning.
Then complete account history/private continuity/cash proof and the accepted
pre-bot-history launch boundary. Connect mutation transport, budgets and all
proof gates; complete selection/ranking integration and Windows supervision.
Keep $500 capital, $300 aggregate/$90 market exposure, size 10, 30 resting
entries and the accepted percentage-cap/six-hour accounting rules unchanged.
Separate explicit live-run authorization is still required.
