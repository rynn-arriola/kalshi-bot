# Windows foundation: first implementation milestone

Historical first-milestone record. The subsequent
[account-I/O milestone](BUILD_ACCOUNT_IO.md) adds a bounded writer, atomic fill/risk
commits, read-only REST fallback and account evidence guards, with 159 total tests.
The unimplemented-item list below describes this earlier milestone, not current scope.

2026-09-19. D-021 authorizes construction, **not live activation**.
This is a tested component foundation, not a finished autonomous trader.
No real credentials, exchange stream sessions, orders, cancellations or transfers
were used. No paper-trading process ran. Existing research scripts/data remain intact.

## Implemented and verified

| Component | Implemented scope |
|---|---|
| config.py / config/bot.json | Strict $500 / size 10 / max 30 / $25 settings; market-slot count null rather than invented; live flag cannot be enabled |
| values.py | Finite exact Decimal validation, quantity grid and explicit timezone-aware timestamps |
| ledger.py | SQLite WAL/FULL durability; idempotent fills; conflicting-fill rejection; candidate FIFO partial-close fee accounting; persisted intent state machine that cannot resend UNKNOWN |
| risk.py | Fixed ET windows including DST; realized-only loss input; 30/25/20/15/10/0 downward ratchet surviving restart; held-window release requires fresh flat proof; exposure admission and stale-state refusal |
| books.py | Ordered incremental books, bounded price ladders, explicit YES-frame prices, subscription-wide sequences and connection generations; gaps/replays/invalid state revoke proof |
| scheduler.py | Coalesced market wakeups and bounded timer heap; due deadlines run without book traffic |
| adapters.py | Validated canonical fills, band-specific tick validation and unsent V2 payload construction with exact reducers |
| transport.py | RSA-PSS read-only signing, stable two-way book partition plus account/lifecycle readers, bounded count/byte queues, serial callback delivery and fail-closed shutdown on stream failure |
| windows.py | Native Windows named-kernel-object single-instance lease, tested across processes; proposed LocalAppData path resolution without creating a runtime directory |
| cli.py | Credential-free policy display and preflight that explicitly refuses live readiness; no start/live command |
| PowerShell scripts | Test-Bot.ps1 and Get-BotPreflight.ps1 only; no trading launcher/service/task installed |

The new package is under src/kalshi_bot. A dedicated native .venv was created
and installed; requirements-lock.txt records exact installed dependencies.
The legacy analysis package is not imported into live-facing components.

## Commands

From the Windows project directory:

```powershell
.\.venv\Scripts\python.exe -B -m kalshi_bot policy
.\scripts\Get-BotPreflight.ps1
.\scripts\Test-Bot.ps1
.\.venv\Scripts\python.exe -B scripts/benchmark_core.py
```

Preflight intentionally exits **2**, reports live_ready=false and lists
unresolved gates. This is expected; never describe that refusal as a successful
live start. It opens no database, credentials or network connection.
To recreate the environment, create a Windows venv, install
requirements-lock.txt, then install this package with pip install -e .

## Precise limits of this milestone

- There is no connected production state coordinator, mutation executor,
  autonomous market selection/repricing/exit loop, or live launch path.
- The WebSocket read component is callable, but was tested with injected local
  fake sockets only. Simultaneous venue entitlement, account scope and stream
  recovery are unverified. For now one reader failure stops the whole group;
  per-book recovery remains future work, not silently claimed implemented.
- REST missing-information retrieval, token-cost budgets, shared cache and
  authoritative startup/reconnect reconciliation are not implemented yet.
- The ledger is synchronous and enforces SQLite single-thread ownership. Before
  integrating live callbacks, add a bounded single-writer worker with durable
  acknowledgements, so disk operations do not block the event loop. Durable
  intent is currently a stored state machine, not proof a real executor uses it.
- Candidate FIFO/receipt-time partial-close accounting and fee allocation are
  tested but still need the operator's final contract approval. Settlement,
  corrected/busted-fill replay and imported starting inventory need explicit
  handling before live use. Every closed-fill update must update the risk
  ratchet before processing a later fill; never batch away an intermediate stop.
- Configured managed-market capacity remains undecided, distinct from the
  30 resting-entry ceiling. No automatic 32-slot/$420 choice was made.
- Entry expiry, exact Kalshi event-risk boundaries, inventory exit integration,
  eligibility and resume authority remain live gates. No purported stop-loss
  guarantee is inferred from the $25 trigger.
- Event/price-ladder counts and a 16 MiB queued-wire-byte budget are engineering
  bounds, not accepted market capacity or total-process-memory guarantees.
  JSON object overhead and socket buffers add memory beyond wire bytes.
- The five-second candidate risk-proof age is a conservative development gate,
  not a venue freshness guarantee or an operator-approved production SLA.

## Verification evidence

Native Windows / Python 3.14.7: **110 tests passed**, including all 45 existing
research tests and 65 new foundation tests. Offline tests generated ephemeral
test signing keys; no user key was loaded. A fixture subprocess proved Windows
ownership exclusion. These are correctness tests, not simulated trading income.

Two deliberate reversals produced the expected focused test failures:

1. Removing the persisted minimum cap allowed 20 to widen to 30 after recovery.
2. Removing sequence continuity allowed a missing book update to remain valid.

Both source protections were restored before the final complete suite.
Review also added explicit stale-window refusal, byte-budget enforcement,
subscription ownership and derived-fee-precision coverage.

### Offline microbenchmark, not live performance acceptance

30,000 deltas per case, one bid/ask level per market, synthetic scheduler work,
Python tracemalloc enabled; excludes sockets, signing, ledger, selector and exits.

| Managed fixtures | Wall / CPU seconds | Updates/sec | Sampled p50 / p95 / p99 microseconds | Incremental traced peak |
|---|---|---|---|---|
| 30 | 1.2998 / 1.2031 | 23,080 | 34.60 / 73.60 / 167.80 | 103,702 bytes |
| 120 | 1.3048 / 1.2656 | 22,992 | 35.30 / 76.70 / 156.70 | 119,926 bytes |

Numbers are one local instrumented run, not sustained capacity, total memory,
idle CPU or fill-to-exit latency. The sparse fixture does not prove behavior
at full-depth books or during simultaneous fills/reconnect/disk stalls.

## Contract provenance

Read local KALSHI_API_REFERENCE.md and rechecked official pages on 2026-09-19:
[V2 orders](https://docs.kalshi.com/api-reference/orders/create-order-v2),
[book feeds](https://docs.kalshi.com/websockets/orderbook-updates),
[direction](https://docs.kalshi.com/getting_started/order_direction),
[fills](https://docs.kalshi.com/websockets/user-fills).
Polymarket rules were traced through source and tests in
[the code audit](POLYMARKET_INVENTORY_CODE_AUDIT.md); no Polymarket files changed.

Before any future mutation implementation, recheck exact current operation
schemas and supported behavior. Payload builders in this milestone are not
an order sender, venue acceptance test or permission to trade.

## Final edge-case review

- Success and boundaries: exact fee-bearing long/short closes, partials,
  reversal inventory, price bands, tier edges, ET/DST and configured caps tested.
- Failure/ambiguity: conflicting duplicate fill, unknown intent, missing book
  sequence, malformed/over-capacity book and stream rejection revoke progress.
- Timing/ownership: old connection cannot overwrite new generation; shared
  sequence spans markets; restart cannot erase cap; separate process cannot own
  the same Windows identity; async cancellation closes fake sockets.
- Resource behavior: queue overflow does not discard safety events silently;
  timer heap and repeated dirty updates remain bounded. Complete end-to-end
  priority and backpressure validation awaits the integrated coordinator.
- Recovery/shutdown: core proof invalidation tested; no claim of successful
  venue cancellation, independent shard recovery or laptop-outage liquidation.
- Deployment/rollback: none performed. Existing instruments and captures are
  preserved; new code is isolated. Live exposure was not queried or changed.
- Secrets: no production key access or secret values added. This folder is not
  currently a usable Git checkout; no commit/push/parity claim is made.
