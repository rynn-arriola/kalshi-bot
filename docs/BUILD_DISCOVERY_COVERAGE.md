# D-091: admission-aware exploration and bounded refill

## Scope and mechanism

The [investigation](INVESTIGATION_LIVE_EXIT_2026-09-22.md) reproduced a cursor
advancing across a proposed slate while admission consumed only 16 additions.
Proposal-only tests missed that consumer mismatch. This repair changes discovery
progress, refill scheduling and diagnostics; not reward economics or order limits.

`CandidateDiscovery` now keeps an ordered pending universe, bounded by the
existing 10,000-program-market catalog bound (the current reviewed live scope is
at most 1,024). Each call removes no-longer-eligible tickers, appends new ones,
and moves **actually subscribed** tickers behind unvisited ones. Merely proposing
a candidate does not advance it. Partial/rejected joins therefore leave its
place intact. Catalog refresh preserves the order of still-eligible candidates.
Protected owners, current selected incumbents and the cheap ranked head retain
their previous priority; the remaining subscription slots draw from the queue.
This is in-memory subscription coverage, not proof of economic eligibility,
successful evaluation, reward accrual or payment.

`RuntimeSelection` passes the actual engine subscription scope, not the proposed
slate. It marks a scheduling-only refill hint when a current released risk window
and portfolio view allow another two-order pair. Capped, held, stale or absent
window evidence does not enable fast refill. `MarketAdmission` uses 30 seconds
after successful/stable refill work instead of the catalog's 300-second interval;
the catalog itself remains on its existing schedule. Other normal discovery uses
the existing interval and transient readiness failures keep the one-second retry.
The timer starts after a cycle finishes. A 30-second minimum post-commit dwell
also applies to catalog-triggered requests, preventing immediate repeated joins.

All existing source/ownership checks before and after awaits remain. Only one
book shard changes at a time, with at most 16 additions/removals and 128 active
markets. Shared quota/metadata concurrency, reader failure budgets, fresh
snapshots, owned-order retention, 70% value, $1 minimum/$2 priority, reference
prices, size ten and the 30-order ceiling are unchanged. There is no REST book
scanner, added connection, order command, ledger migration or automatic restart.
Thirty seconds is a minimum observation opportunity, not proof metadata is ready;
normal metadata/book/account checks still decide whether a market can rank/trade.

## Diagnostics

Saved selection status now includes a timestamped proposal summary, exclusion
counts and at most eight sample markets. Dispatch retains its last non-IDLE
outcome and last entry-source blocking stage instead of losing all reasons at
IDLE. Admission reports refill mode and time until its next attempt. These are
bounded historical diagnostics, explicitly labeled as such, not fresh authority
or independent process-liveness proof. No raw payloads or credentials are logged.

## Verification

- Six offline breadth checks pass. The formerly failing 1,024-market / 14-owner /
  two-shard reproduction reaches all 1,024 in 56 partial rotations, none skipped.
- Automated composed regressions cover 0/14/30 protected markets, deferred joins,
  scope bounds, and an economically viable fifteenth pair outside the initial
  128 reaching the real selector with 28 entries already counted. Synthetic
  immediate joins isolate discovery/selection; existing runtime handoff tests
  independently cover fresh snapshots, ownership and revocation races.
- Additional tests cover uncommitted proposals, catalog churn, risk-window refill
  conditions, minimum dwell, saved proposal reasons and retained dispatch results.
- Counterfactual: replacing only discovery with the prior implementation makes
  the new composed coverage test fail (692/1,024 with 14 owners). No source file
  or production process was modified for that temporary in-memory test.
- Resource check: 1,024 candidates, 128 active, 56 synthetic cycles; all covered,
  0.672 CPU seconds, 382,527 traced peak bytes, maximum cycle 15.254 ms. Existing
  30/120-market scope-commit benchmarks pass their CPU/memory/50-ms p99 budgets.
  These exclude actual network, metadata, account and ledger latency, not live
  throughput or time-to-fill evidence.
- Complete suite: 1,492 tests in 234.396 seconds; 1,491 passed and one expected
  Windows symlink-privilege skip. Actual diff review found no blocking issue.
  Local-link and whitespace checks are part of publication; see current STATUS.

## Polymarket comparison (read-only code check)

`C:/Users/rynna/Bots/liquidity-bot/src/liquidity_bot/market_selector.py` screens
the catalog, chooses a bounded detailed batch, opens `book_scope`, then evaluates
each market in that batch. `selection_books.py` supplies a concurrent public
book reader capped at 100 markets per scan; `live_commissioning.py` wires it into
the gateway. Thus broad catalog filtering and concurrent book collection are
distinct from evaluating the entire universe simultaneously. Kalshi already
watches 128 books across two readers; this patch repairs how candidates reach
that set without copying Poly's fee, reward, REST-fallback or trading policies.

## Remaining boundary

Offline coverage is verified; live slot occupancy, current eligible-market counts
and profitability are not. The precise historical final-pair rejection remains
unknown. Process-host continuity/status truthfulness and reconciliation of the
operator's manual cancellations remain separate pre-restart work. Bot stays stopped.
