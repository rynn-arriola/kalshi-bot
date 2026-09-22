# D-069: bounded reward-aware market selection

## Contract and scope

Offline construction only. Reuse `quoting.py`, `RankingBoard`, existing runtime
book/metadata/inventory owners and the single writer's portfolio/risk types.
No new venue command or authorization path. The selector returns advisory
additions, retained owners and explicit exclusions; the writer must recheck
cash, risk, source proof and command capacity before any future reservation.

Rank feasible size-10 two-sided reference quotes by gross dollars/hour, then
capital efficiency and stable identity. Bound remaining reward by the earliest
program/approved entry deadline. Warnings include sub-$1 remaining projection
(accrued earnings unknown), competition and reward qualification loss. A
resting order that no longer scores can still fill; it remains owned until
terminal/fill reconciliation. Never replace it just because a new hypothetical
quote would score. No estimated net P&L or invented fill probabilities.

The runtime attachment is explicit/offline and uses the existing event engine's
coalesced evaluations and invalidation. Program definitions are supplied with
bounded observation/expiry evidence; no extra REST poller or WebSocket. Working
orders without proven public-book reflection remain protected/unknown, not
double-counted. Snapshot assessment with explicit reflection proof is available
for future producers. Rankings are not account or execution authority.

## Resource/acceptance contract (declared before implementation)

- At most 128 markets by default (hard bound 1,024), 16 programs per market,
  4,096 levels per side and 30 quoted entries. No unbounded history, per-market
  task or polling loop. Invalidation O(1); re-evaluate only dirty markets.
- One bounded sort when proposing additions. No portfolio scan or database read
  added to the per-book ranking calculation. Reuse the management observation.
- Synthetic 30/120-market scopes: 10 updates/market at 20 levels/side, with
  event-loop yields between markets, p99 update and loop delay <50 ms,
  total CPU <5 seconds per scope and traced allocation peak <16 MiB.
  Also exercise 4,096-level input and 16-program bounds; report these separately
  from the representative-load target. No claim of live latency or profitability.
- Tests: competition vs headline pools, period normalization, actual orders
  discounted/excluded, two-sided qualification, own reflection, stable ties,
  deadline decay, caps/unknowns, capital and two-slot allocation, freshness,
  incumbent retention, source changes after awaits and no mutations.

## Verification

42 focused tests pass using synthetic books, accounts and disposable SQLite.
The runtime attachment is exercised through the real event engine, management
owner and writer. It adds no writer mutations or venue calls. Tests distinguish
full weight, discount, zero weight, cutoff exclusion and insufficient two-sided
depth; a discount factor of 1 does not reduce price weight behind reference.

Native Windows commands:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bot_selection.py -q
.\.venv\Scripts\python.exe -B scripts/benchmark_market_selection.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

Representative component resource results (not whole trading-runtime latency):

| Markets / updates | Update p50/p95/p99 ms | Loop p50/p95/p99 ms | CPU / wall seconds | Peak bytes |
|---|---|---|---|---|
| 30 / 300 | 1.067 / 1.462 / 2.301 | 2.286 / 7.702 / 8.373 | .4062 / .4138 | 428,434 |
| 120 / 1,200 | 1.026 / 1.378 / 2.275 | 2.141 / 4.024 / 25.078 | 1.5312 / 1.5512 | 471,902 |

Both representative gates pass. Independent maximum-input fixture: 4,096 levels
per side and 16 programs, 44.754 ms for one update. Shared book validation
reduced that same fixture from 465.737 ms in the initial implementation. These
are individual same-laptop observations, not statistical production guarantees.
The boundary fixture uses target 1,000 and 100 contracts per price; it does not
prove worst-case latency when every price level contributes to scoring.

Final full suite: **1,221 run, 1,220 passed, one expected Windows symlink-privilege
skip**, in 184.306 seconds. Disabled preflight returns exit 2, `live_ready=false`,
no file creation, no credentials and no network. Deliberately bypassing
`RuntimeSelection.current` in memory makes the pending-book-ingress regression
fail as expected; source files were not weakened. Exact diff/whitespace review,
315 local Markdown links and staged secret-pattern checks passed. No known
blocking issue within this advisory component's scope. D-065 publication is
source synchronization, not deployment.

## Implemented interfaces and review

- `quoting.program_plans`: validate the shared book once, then score independent
  program/quote copies. No hypothetical order accumulation between programs.
- `ranking.RankingBoard`: an explicit selection view (hourly, efficiency,
  identity), quote-level qualification, reference/cutoff diagnostics, independent
  earning deadline and dynamic payout warning. Existing views remain available.
- `selection.MarketSelector`: whole-pair affordability using the existing risk
  gate, retained exposure/unknown owners, and visible current-book exit losses.
  Capital estimate includes a conservative reserve for the supplied taker exit
  fee bound; this is not a verified entry-fee or venue buying-power calculation.
- `runtime.attach_selection(offline_fixture=True)`: optional event-driven
  attachment. `set_programs` accepts bounded scoped observations; program
  changes revoke old rows. `propose(window=..., free_cash=...)` reads one writer
  portfolio view, rechecks source identity after the await and returns a
  non-authorizing `SelectionReport`. Status distinguishes cached from current.

Review corrections: cleanup of per-program auxiliary caches on invalidation;
exact five-second expiry handling; retained metadata time high-water after bad
publication; foreign-order audit rejection; discount-factor-1 classification;
one-market unsupported-input exclusion instead of stopping the entire engine.
That exclusion has a deduplicated structured diagnostic; unexpected bugs still
propagate to the runtime's fail-closed supervisor. No raw venue data or exception
text is logged.

## Explicit remaining integration/readiness work

This completes the bounded selection component, not all priority-5/live work.
Selection currently covers the runtime's supplied subscribed universe.
[Bounded program discovery/refresh](BUILD_INCENTIVE_DISCOVERY.md) now supplies
that scope; rotating discovery subscriptions are not connected. Runtime
working-order reward share is intentionally unknown without
public-book reflection evidence; private receipts alone do not establish it.
Explicit-quote arithmetic is available, but is not an automatic repricing loop.

Reports do not reserve or dispatch entry pairs, release owners, cancel orders,
or claim paid earnings. The future admission/dispatch producer must revalidate
accounting leases, actual entry fees/cash, source revisions and both legs as
state changes; losing reward eligibility is never terminal cancellation proof.
Existing native S2B review/resource gates, production inputs and explicit launch
approval remain. No sports-only filter or new market-set approval was introduced.
