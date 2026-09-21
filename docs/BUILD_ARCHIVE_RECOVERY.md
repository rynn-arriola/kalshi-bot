# Archived-order recovery — September 20, 2026

Native Windows implementation under existing D-021 authority. No new risk cap,
market set, correction/settlement policy or live activation was selected.

## Implemented

- Added authenticated GET-only `historical_orders` to the shared bounded REST
  service, including required cursor validation. No new polling loop or socket.
- Read and compare `orders_updated_ts` before/after archive enumeration. Use
  optional ticker narrowing, not guessed creation-time cutoff splitting. Retain
  the explicit limitation: stable cutoff plus pages is not an atomic snapshot.
- Require row subaccount evidence; never assume omitted scope means primary.
  Reject active rows, ticker conflicts, conflicting duplicate IDs, missing
  cursors and resource overflow. Explicit other-account rows are excluded/countable.
- Normalize at most 4,096 rows/8MiB by default, yielding every 32 rows; use the
  existing single writer in batches of at most 32. Network page/read/token limits
  and the existing five-second reconciliation token still apply. Timeout blocks
  completion rather than relaxing freshness.
- Bind only orders matching exact durable intent identity, market, direction,
  price, quantity, account and exchange shard. Unowned orders cannot create
  inventory or enter this bot's fill accounting. Missing/unaccounted fills keep
  reservations even if the venue order is terminal. Archive absence never cancels.
- A known order's direct HTTP 404 can now trigger ticker-scoped archive recovery.
  This uses a typed, sanitized HTTP failure, not error-text matching. Unknown
  order IDs, authentication errors, throttling, transport failures and server
  errors do not trigger that fallback. Explicit archive enumeration can recover
  an unbound order from its exact previously sent/unknown durable client intent.
- Reconnects/private events/superseding tokens revoke publication. Accepted
  evidence batches already committed remain durable; interrupted runs publish
  no completed report and do not claim entry readiness.
- History staging now rejects execution timestamps inconsistent with a durable
  fill, respecting source precision. Beginning reconciliation clears previous
  auxiliary reports. Neither change imports missing fills or modifies prior P&L.

No ledger schema migration was needed. Ledger stays schema 2, live config false.

## Source evidence

Rechecked current official [historical orders](https://docs.kalshi.com/api-reference/historical/get-historical-orders)
and [historical data routing](https://docs.kalshi.com/getting_started/historical_data).
The archive endpoint has ticker/time/pagination parameters, but no documented
subaccount parameter; terminal orders older than the cutoff move off the recent
order list. Cached exact operation, `GetOrdersResponse` and `Order` schemas were
also inspected in `docs/KALSHI_API_REFERENCE.md` and `docs/api-specs/openapi.yaml`.
Optional row account scope is not a guarantee that every real response will be
usable; missing scope deliberately blocks this implementation.

Actual reference `C:/Users/rynna/Bots/liquidity-bot` remained clean at
`54ac71a241d1ad6f02e3445655bb7115247bac02`. Re-read the execution-ledger snapshot
path near lines 1625–1675: missing active orders become `UNKNOWN_ABSENT`, not
canceled. This milestone preserves that existing safety principle; it does not
copy Polymarket API endpoints or claim new full-runtime parity. Reference tests
were not rerun this turn; earlier code-audit verification remains separately dated.

## Verification

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B scripts/benchmark_archive.py
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

335 tests passed in 13.981s: prior 306 plus 29 archive/timestamp regressions.
These cover pagination, bounds, duplicate conflicts, account scope, terminal
status, exact intent binding, unknown ownership, missing fills, 404 routing,
authentication/timeout rejection, restart, stale tokens, generation changes,
bounded batches, report invalidation and execution-time conflicts.

Two deliberate temporary reversals each failed a focused regression:

1. Removing 404-only fallback admitted an authentication failure into archive
   recovery; the authentication rejection test failed.
2. Removing terminal/fill-quantity agreement released a missing-fill reservation;
   its test failed.

Both guards were restored before the full passing suite. Preflight still says
not live ready, no credentials/network accessed and no files created.

## Offline resource diagnostic

`benchmark_archive.py` uses fresh temporary SQLite WAL/FULL ledgers, preseeded
sent intents outside measurement, injected read responses, zero-fill canceled
orders and no venue traffic. It measures normalization plus durable order binding.
Tracemalloc is enabled; heartbeat every 2ms. Budgets declared in the script:
finish within the existing five-second token, loop p99 <50ms, batch ack p99
<100ms, incremental Python peak <40MiB. These are diagnostic—not approved live—budgets.

| Orders / synthetic tickers | Wall / CPU s | Batch ack p50 / p95 / p99 ms | Loop lag p50 / p95 / p99 ms | Python traced peak |
|---|---|---|---|---|
| 128 / 30 | .0728 / .0625 | 14.487 / 14.613 / 14.613 | 5.911 / 7.760 / 7.760 | 263,916 bytes |
| 4,096 / 120 | 1.8863 / 1.7656 | 11.929 / 17.359 / 18.977 | 5.613 / 11.025 / 13.216 | 7,268,966 bytes |

Both completed and passed diagnostic budgets. Heartbeat samples 11/237;
maximum sampled writer backlog 1. No risk-window holds were reset. These sparse
injected runs do not establish network/token-budget performance, outage recovery,
mixed-feed saturation, idle CPU, total-process memory or live acceptance.
The earlier fill-journal long-history summation cost remains unresolved.

## Still unfinished / operator choice

The pending recovery-import question in DECISIONS asks whether automatic imports
may occur only with proven ownership and complete starting cost basis, while
corrections, settlement discrepancies and unexplained inventory stay blocked for
operator review. No answer was received during this work; no policy was assumed.

Complete history coverage/basis, fill-before-order orchestration, correction/
settlement handling, reader/executor integration and safe resumption are not done.
Archive reports always have `ready_for_entry=False`. Limits-driven market capacity
still needs a non-circular mapping of the slot-derived portfolio exposure limit;
no $400/$420/$500 replacement cap was silently chosen.

No keys, account calls, orders/cancels, paper trading, bot/service start,
historical deletion/migration, WSL execution or Polymarket modifications occurred.
Public documentation was the only network research. Kalshi still lacks usable
Git metadata; files were inspected directly, with no commit/push/parity claim.
