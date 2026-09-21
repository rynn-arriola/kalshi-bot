# Approved accounting milestone — September 20, 2026

D-024 authorizes this change. Native Windows, correct `Bots/kalshi-bot` project.
Build and offline correctness checks only; live execution remains disabled.

## Implemented contract

- One indexed weighted-average position row per market, in signed YES economics.
  Adding to either side averages the basis; partial reductions retain it; a flip
  opens the residual at the incoming fill price. No open-position marking.
- Each matched quantity realizes gross P&L immediately. Each fill charges its
  full actual fee immediately, even with unmatched/open inventory. This is the
  explicit D-024 change to D-017's old fee timing, not an accidental open-P&L stop.
- New `realized_events` records gross P&L, full fee and net delta for every fill.
  `Ledger.realized` sums that journal. `closes` is gross matched-detail only;
  `lots.fee` is zero, never a deferred-fee balance. Decimal working precision 40.
- Existing writer commits fill, position, journal, risk ratchet and owned-order
  settlement atomically off the event loop. Acknowledgement follows commit.
  Conflicting duplicate economics fail closed rather than modify history.
- First committed receipt stays fixed. Late events affect the receipt window,
  not the venue execution window. Duplicate delivery does not recharge a fee.
  The single writer's durable application order governs basis, including equal
  receipt timestamps. No sorting/replaying old fills by execution time is added.
- Store optional execution microseconds and source precision separately.
  WebSocket `ts_ms` is preferred over deprecated `ts`; if both exist they must
  agree at seconds precision. Missing time remains unknown, not fabricated.
  REST history retains `created_time`. Duplicate timestamp evidence can enrich
  unknown/coarse time without changing accounting; conflicting time fails closed.
  The stored values are source timestamp evidence, not proof of cross-feed order.
- Schema **2** refuses schema 1, unknown or unversioned nonempty databases before
  enabling WAL or applying DDL. No migration tool or deletion was performed.
  Do not bypass refusal by starting an empty ledger against existing exposure.
  Config format remains version 1; it is independent of ledger schema version.

Source: actual reference `src/liquidity_bot/pnl.py`, audit
[call paths](POLYMARKET_POLICY_CODE_AUDIT.md). Timestamp contracts checked against
the saved AsyncAPI `fillPayload` and REST history schemas; official
[user fills](https://docs.kalshi.com/websockets/user-fills) and
[REST fills](https://docs.kalshi.com/api-reference/portfolio/get-fills).
No venue API request or credential access was needed for this implementation.

## Verification

Native Python 3.14.7:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B scripts/benchmark_writer.py
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

306 tests passed in 11.345s: prior 280 plus 26 accounting regressions.
Tests cover both directions, weighted basis versus FIFO, fractional quantities,
partial/complete closes, reversals, full opening/closing fees, window edges,
late/duplicate receipts, timestamp enrichment/conflicts, restart, rollback,
sticky fee-triggered caps/holds and byte-unchanged refusal of old databases.
A 1,000-opening-fill test leaves one indexed position row.

Two intentional local reversals were tested then restored:

1. Removing actual fees from net realization caused 13 new tests to fail,
   including fee-triggered cap/hold tests.
2. Keeping the old basis instead of averaging additions caused four tests to fail.

After restoration the complete suite passed. Read-only preflight must still
report not live ready; no network or credentials. Live config remains false.

An independent, read-only comparison imported actual Poly `MatchedInventory`
from clean reference HEAD `54ac71a241d1ad6f02e3445655bb7115247bac02`.
Seed 24, 10,000 fills, 30 synthetic tickers, bid/ask directions, quantities
.01–10.00, YES prices .01–.99 and fees .000–.010. Applied the identical sequence
to both implementations; compared every per-fill net delta, position and basis.
Positions matched exactly. Maximum per-fill difference: 3.8830065389158e-27
dollars, under the 1e-24 diagnostic tolerance (reference default Decimal precision
28 versus Kalshi 40). This is arithmetic verification, not proof of parity in
recovery, correction handling or the full trading runtime. Poly was not edited.

## Measured resource scope and limits

Reused the existing sparse writer fixture: 30/120 synthetic tickers, four
open/close cycles each, size 10, identical prices, zero fees. Fresh temporary
SQLite WAL/FULL, one awaited acknowledgement at a time, tracemalloc enabled,
2ms heartbeat. Not a strategy/income simulation or a saturation test.

| Markets / fills | Wall / CPU seconds | Ack p50 / p95 / p99 ms | Loop-lag p50 / p95 / p99 ms |
|---|---|---|---|
| 30 / 240 | .5724 / .5156 | 1.932 / 3.614 / 4.656 | .860 / 2.831 / 10.172 |
| 120 / 960 | 3.8909 / 3.4688 | 3.086 / 8.402 / 10.172 | 1.302 / 6.052 / 8.066 |

419.3/246.7 fills per second; 179/958 heartbeat samples; traced peaks
1,193,946/128,687 bytes (first run includes initialization); backlog at each ack
zero by construction. These are observations, not approved live latency budgets.
Position lookup no longer scans historical FIFO lots, but risk-window totals
still scan indexed journal rows on the worker. Immediate fees mean a row for
every fill, not only closes. Larger-case latency increased versus the earlier
milestone; long-history aggregation/retention and mixed-feed load remain work.
No idle CPU, total-process memory, reconnect-storm or live scalability claim.

## Deliberately unfinished

History staging still does not import missing fills or prove starting basis.
Complete recovery needs ownership/coverage barriers, durable replay order,
correction/reversal/settlement handling, and separately reviewed migration of
existing databases. The reference's receipt/event/identity replay tiebreak is
not automatically imposed on previously committed Kalshi fills.
An execution timestamp report/query interface is not yet implemented.

No capacity/risk cap was invented, and no market selection, exit or restart
policy was changed. Limits-driven exposure integration, real reader/executor
integration, production supervision and separate live authorization remain.
No paper run, live process, orders/cancels, keys, historical-data deletion,
Polymarket mutation or WSL operation. Kalshi lacks usable Git metadata; no
commit/push/parity claim is made.
