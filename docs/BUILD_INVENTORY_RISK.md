# D-027 inventory/risk integration

Completed scoped integration, 2026-09-20. No live activation or venue writes.

## Before-build scope and verification budgets

Connect per-market passive management to private fills/orders, recovery, changed
books and independent deadlines. Source existing exact-quantity/cancel-confirm
behavior from Poly code; no invented IOC/deadline or portfolio-cap default.
Maintain a bounded local plan board, invalidated by source revision/generation,
never an order dispatcher. Missing account/book proof blocks replacements.

Add a single-writer account-wide exposure projection and atomic offline entry
reservation using current durable inventory, active orders and ambiguous sends.
Deduplicate intent/order identity, retain risk until terminal/fill agreement,
include reducers in dollar exposure but not entry count. Compare/reject stale
writer epochs/revisions after awaits and across restart. No independent per-market
allowance or reset of loss-window holds. Default production authority stays false.

Tests: partial fills, canceled/unknown orders, reducers, duplicate exposures,
competing reservations, restart/stale proof, capacity/cash/window limits, source
invalidation, filled markets without book changes, and deadline service. Two
offline safeguard reversals; restored full suite and blocked preflight.

Resource diagnostic planned before implementation: 30/120-market disposable
WAL/FULL fixtures, 120/480 per-market management reads and 30/120 global risk
projections, tracemalloc plus 2ms heartbeat. No networking. Budgets: market-read
p99 <100ms, global-projection p99 <250ms, event-loop lag p99 <50ms, incremental
Python peak <40MiB. Retained-intent cap 4096 and registered-market cap apply;
no all-account projection on each public-book tick. Offline diagnostic, not live SLA.

## Built and verified

- `portfolio.py`: immutable bounded account exposure from inventory basis,
  conservative venue cost, working orders and unresolved sends. Bound intent and
  order counted once. Reducers exempt from entry count only. Missing terminal
  fills retain risk; venue absence cannot release it. Positive entry reservations
  require the explicit offline fixture flag and recompute inside the owner
  transaction; stale epochs/revisions fail. Production inspection always denies.
- `management.py` / runtime: advisory exact passive cancel/keep/reducer plans
  refresh on private events, recovery, books and independent timers. Fresh
  per-market enumeration is not full account/history proof. Account/book/writer
  changes invalidate published and awaited plans. No command dispatch.
- Persistent position clocks retain original age through partial closes and
  restart; flips reset it, flats clear it. Old missing clocks remain unknown.
  At 900 seconds the timer exposes the unfinished timed-exit mapping; it neither
  sends an IOC nor loops on an immediately overdue timer. Earlier deadlines win.
- Indexed per-market intent/pending-fill reads; bounded global projections only
  when requested. No new venue endpoint, socket or REST polling was introduced.

Read-only source trace, Poly HEAD `580dcc9f49a7f8fb58c8ebff4708d2904786e9ad`:
`live_commissioning.py:_portfolio_worst_loss` sums basis loss, working orders and
unbound PLACE intents without duplicate row-backed intents. `commissioning.py`
retains the slot-dependent portfolio formula. `reconciler.py:_passive_inventory_plan`
confirms exact quantities/cancel-first behavior. `exit_quote_price` conditionally
improves a profitable passive exit one tick without crossing; this Kalshi build
still uses its existing touch-only advisory plan and does NOT claim pricing parity.
No Poly files were edited. Its 76 reconciler tests pass in 0.686s with `src`
explicitly on the test import path; the first default discovery attempt could
not import its uninstalled package. Final Poly Git status was clean.

Native Windows full suite: **450 tests pass**, 28.389s (40 new). The recovery
benchmark ran concurrently, so suite elapsed time is not an isolated baseline.
Two temporary offline reversals failed as intended, then were restored:
omitting writer revision comparison accepted both competing candidates (2 vs 1);
exempting reducers from dollars produced zero exposure instead of $4. Preflight:
`live_ready=false`, native exit 2, no files/credentials/network accessed.

## Measured resource diagnostic

`scripts/benchmark_inventory_risk.py`, temporary WAL/FULL ledgers, one inventory
and one owned reducer per market, tracemalloc and 2ms heartbeat, setup excluded:

| Markets | Market/global reads | Wall / CPU s | Market p99 ms | Global p99 ms | Loop p99 ms | Peak bytes |
|---|---|---|---|---|---|---|
| 30 | 120 / 30 | .2076 / .1875 | .937 | 6.238 | 4.950 | 353271 |
| 120 | 480 / 120 | 2.0731 / 2.0469 | 1.001 | 23.952 | 15.836 | 259323 |

Both pass the predeclared budgets. The existing recovery-engine diagnostic also
passes with management enabled: 128/1024 fills, 30/120 markets, .6754/7.7487s wall,
fill processing p99 8.552/13.354ms, loop lag p99 3.191/5.526ms, all 8/64 requested
deadlines serviced. That run overlapped the test suite. This is disposable
engineering verification, not paper trading or production performance acceptance.

## Boundaries / next work

Live authorization stays false. The fixture-only cash bound subtracts all current
working risk, conservatively, from supplied cash; it is not coherent production
balance/hold accounting. Complete starting history and stream continuity,
corrections/settlements, production cash/reservation authority and non-circular
portfolio-cap mapping remain unfinished. No market-slot cap was selected.
Conditional passive-price improvement, forced IOC/event/expiry mapping,
automatic selection/repricing, mutation transport and supervised launch remain
separate work. Unsubscribed held markets are reported as unmanaged, not assigned
a guessed book. No live account files, keys or historical trading data were used.
