# D-092: measure discovery alternatives before choosing an implementation

## Conclusion

**Recommendation, not production implementation:** maintain broad rewarded-book
coverage over the existing WebSocket transport and load shared metadata in bulk.
Keep discovery scope separate from order/account ownership and the 30-order cap.
Do not build a slow rotating scanner merely because D-091 currently rotates 16
markets at a time. The measured feed supports the current reviewed universe;
its full-runtime integration and longer-load behavior still need verification.

This narrows the earlier recommendation: a separate discovery *responsibility*
is useful; a separate service, new bot, perpetual cold scan or extra connection
per market is not justified by these results. No runtime source/configuration,
ledger, order or bot process was changed or started.

## Current official API options

Sources checked September 23, 2026:

| Option | Documented capability | Assessment for this bot |
|---|---|---|
| [WS books](https://docs.kalshi.com/websockets/orderbook-updates) | Multiple named markets; initial snapshots, deltas, add/delete and get_snapshot | Preferred primary depth source; measured below. No documented 128-market limit established. |
| [WS ticker](https://docs.kalshi.com/websockets/market-ticker) | All markets when scope omitted; bid/ask/size, prices and statistics on changes | Possible prioritization hint, not complete depth, reference price or competition proof. Deeper changes can matter without top-price movement; retain exploration if used. Not live-benchmarked here. |
| [REST multiple books](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks) | Authenticated GET /markets/orderbooks, 1–100 tickers | Possible bootstrap/recovery alternative, not selected for routine polling under WS-first policy. Not live-benchmarked here. Verify endpoint costs, completeness and freshness first. |
| [REST markets](https://docs.kalshi.com/api-reference/market/get-markets) | Up to 1,000/page, ticker filters, full market fields; min_updated_ts tracks non-trading changes with filter restrictions | Candidate bulk metadata source. Price summaries are not a substitute for depth. Actual parser checks below. |
| [REST events](https://docs.kalshi.com/api-reference/events/get-events) | Up to 200/page, ticker filter, nested markets and milestones | Stronger observed bulk metadata candidate: four bounded requests covered our saved scope. |
| [REST series list](https://docs.kalshi.com/api-reference/market/get-series-list) | Fee settings and min_updated_ts | Potential shared series baseline, not tested for complete current fee-schedule equivalence. |
| [FIX market data](https://docs.kalshi.com/fix/market-data) | Dedicated KalshiMD snapshot/update session; up to 1,000 symbols/request, 100,000 subscriptions/session; no message retransmission | Documented alternative, not evidence of account access or need. Adds a new protocol/recovery implementation; no advantage demonstrated for our scale. Not connected/tested. |

The [rate-limit guide](https://docs.kalshi.com/getting_started/rate_limits) describes
shared token budgets and non-default endpoint costs. Do not assume a bulk call
is free, costs one market's tokens or saves quota. Actual authenticated costs and
account headroom were not queried in this public-data experiment. No alternative
is declared fastest across all conditions; only the WS and metadata paths below
were measured. A performance comparison cannot authorize a transport-policy change.

## Experiment A: staged WebSocket coverage

Instrument: `scripts/probe_book_capacity.py`. Command:

```powershell
.\.venv\Scripts\python.exe -B scripts/probe_book_capacity.py --read-only-live-check --source-root C:\Users\rynna\Bots\kalshi --seconds 45
```

Local artifact: `data/book-capacity/b188a5a819d047d9b63d965e7f54773e/result.json`.
Book stages observed 04:16:40–04:19:41 UTC; final connection cleanup completed
04:19:46 UTC. Each stage used two existing hash-partitioned book connections,
the production WebSocket transport, quiet-book snapshot controller, exact book
parser and existing independent reference-price comparison. Scopes were saved
reviews intersected with the current supported active reward catalog: 1,013.
This is not all rewarded markets on Kalshi.

Diagnostic targets set before measurement: complete initial coverage within 15s;
at least 99% books fresh (ingress age <=5s) at every steady sample after 10s;
CPU <=50% of one core, sampled working set <=512 MiB, event-loop and ingress-to-
callback p99 <=100ms, no reference mismatches or reader errors. Stop escalating
on any failed stage. These are experiment targets, not accepted trading budgets.

| Markets | Time to all first books | CPU, % one core | Peak sampled RSS, MiB | Loop lag p99, ms | Ingress-to-callback p99, ms | Minimum sampled fresh |
|---:|---:|---:|---:|---:|---:|---:|
| 128 | 0.319s | 1.81 | 58.29 | 14.35 | 17.88 | 100% |
| 256 | 0.449s | 3.12 | 60.44 | 15.01 | 18.78 | 100% |
| 512 | 0.474s | 6.48 | 63.07 | 26.87 | 27.67 | 100% |
| 1,013 | 0.560s | 10.37 | 67.19 | 17.37 | 60.78 | 100% |

All four stages met targets; no reader faults or reference mismatches. At the
largest scope, shard sizes were 520/493; 15,775 messages, including 2,000 deltas
and 12,760 quiet-book refresh snapshots, traversed the parser. Normalized JSON
volume was 7,939,513 bytes over 45.032s; not measured network wire bytes.
Freshness therefore includes real requested WS snapshots, not fake heartbeat
refresh. Reference equality was checked on each market's first snapshot only.

Largest-scope event-loop maximum was 117.29ms despite p99 17.37ms; callback queue
maximum was 413 events. The diagnostic has one shared 8,192-event / 16-MiB queue,
not production's per-book-reader 256-event / 2-MiB configuration. Do not infer
that production can be widened by changing one capacity number. CPU includes
instrument overhead, but excludes full ranking, metadata, ledger and private
account processing. Initial coverage excludes prior incentive/catalog loading.
Sampling at about 0.5s cannot exclude every shorter freshness dip. Late-night
45-second observations do not prove sustained peak-event or reconnect capacity.

## Experiment B: bulk metadata and actual parser compatibility

Instrument: `scripts/probe_bulk_metadata.py`, same explicit read-only flag and
source root. Local artifact:
`data/bulk-metadata/f2c724ec0e71480ea7c118cef8921aba/result.json`.
04:20:02–04:20:09 UTC, 14 unauthenticated public GETs, no retries, at most two
requests/second. Run separately after WS completion to avoid distorting its load.

- `/markets`: two filtered list requests returned all 100 sampled markets;
  every row passed the existing `parse_market` validator. Elapsed 0.732s.
- `/events?with_nested_markets=true&with_milestones=true`: four filtered requests
  returned all 188 reviewed events and all 1,024 requested market definitions.
  Every requested market parsed; 1,013 active. All 1,024 rules hashes matched the
  saved reviews and all reviewed milestone IDs/types/primary-event bindings
  were present. Elapsed **2.228s**, including local request pacing and parsing.
- Five individual market reads matched the fields used by `parse_market` in
  both list and nested responses. Three individual event reads matched the
  list's `parse_event` output. Moving prices are not compared. This is a sample
  equivalence check, not proof all fields/endpoints always agree atomically.
- Series baselines, future fee-change schedules, member fee profile, lifecycle
  invalidation and source-generation publication were NOT rebuilt or verified.
  Bulk metadata therefore does not itself authorize selection or an order.

## Code diagnosis and proposed next scope

The earlier [market-gate census](VERIFY_MARKET_GATES_2026-09-23.md) used two metadata
workers, constructed a new service for every 128-market batch and made 2,563
public REST requests. `ExitInputService.refresh` follows market -> event ->
series/fee changes -> milestone, with a shared two-slot loader and <=60s evidence
TTL. It already coalesces dependencies within its scope; saying it has no cache
would be incorrect. Cache retention/pruning and live subscription scope are
coupled. D-091 also imposes 16 replacements/30s. Neither delay is a documented
requirement to retrieve the entire reviewed book universe.

Recommend an implementation proposal with these boundaries, requiring operator
acceptance before runtime edits:

1. Broader continuously maintained public books, with measured per-reader
   queue/refresh budgets and no link to 30 resting-order occupancy.
2. Bulk event/market/milestone bootstrap feeding a shared versioned metadata
   cache; retain complete fee schedules, review hashes, expiry and stream
   generation checks. Reuse existing validators; do not extend TTL blindly.
3. Event-driven ranking of changed candidates, fresh evidence required at entry;
   existing $2 priority/$1 fallback, 70% value and risk limits remain unchanged.
4. Validate cold and warm time-to-qualified-slate plus coverage, fee-source
   completeness, cancellation/account scheduling under synthetic peak load,
   and bounded reconnect recovery. Public read-only acceptance before restart.

A broad-book component test is successful. End-to-end fast economic ranking,
live account admission, profitability and restart readiness remain unverified.

## Instrument verification and safety

Verification: **110 relevant offline tests passed in 5.268s** (nine new
instrument tests plus existing transport, refresh, reference, census and
selection tests). No new complete-suite run is claimed; runtime code is unchanged.

New tests cover coverage tracking, sequence gaps, percentile calculations,
failed reader cleanup/classification, resource targets, exact bulk identity
coverage, private/book endpoint rejection, refusal latching and unexhausted
pagination. Existing transport/reference/snapshot tests are run as relevant.
Only aggregate evidence is documented; per-run artifacts and credentials stay
ignored. No live writable database, account REST, mutation client, trading bot
or production configuration was opened/changed by either instrument.
