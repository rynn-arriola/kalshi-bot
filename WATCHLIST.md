# Watchlist — ideas and questions, not authority

Accepted requirements belong in [DECISIONS.md](DECISIONS.md); active work in
[NEXT.md](NEXT.md). Nothing here authorizes trading or increased risk.

- Define CPU, memory and latency budgets against actual laptop capacity and
  operator-approved market count before implementation.
- Resolve field-level stream completeness, account bootstrap and gap recovery.
- Add CPU workers only if profiling establishes a bottleneck; not per-market
  threads/processes by default.
- Complete compact root indexes and a documentation audit while preserving
  historical evidence and links. See [layout](docs/DOCUMENTATION_STRUCTURE.md).

## Operator checks — say “check watchlist”

Standing checks on the running bot. Each check is a read-only look at logs,
status and a ledger copy; any action it suggests still needs operator
approval. Baselines are from Findings 203–207 (2026-09-26 UTC).

| # | Check | Baseline | Good | Act when |
|---|---|---|---|---|
| 1 | **Deploy D-136** (`8af73b2`: 180 s startup allowance, renewal fallback reasons) | Running build is D-135 (`0265983`); 60 s startup limit vs 56–58 s starts | Deployed at the next natural restart | Before any planned restart; sooner if the supervisor shows `startup_timeout` |
| 2 | **Withdrawal lockout (D-135)** | 168 withdrawal events / 72 min in 30 markets; ~6.6 min out per episode; ~17% quoting time lost | Lockout downtime and repeat withdrawals well below baseline | Fill within ~2 min of re-entry, or noisy markets cycling faster than about every 5 min |
| 3 | **Own-order renewal** | 8 of 21 completed; all fallbacks unlabelled | Most complete; fallbacks mainly `order_not_visible` and then succeed | `position_changed`, `cash_changed` or `audit_blocked` appearing |
| 4 | **Full recovery time / chain reuse** | 4.28 s median before; 1.8–1.9 s after with 24 of 27 chained | Stays ≤ ~2 s; most passes chained | Median back above 3 s or chaining rare without fills |
| 5 | **Order-lookup 404s after cancels** | 1 in the first 10 min (pass retried fine) | Rare | More than ~3 per hour: add a short settle wait before re-checking just-cancelled orders |
| 6 | **Contract-size analysis** (10 vs 20 vs 30) | 10 contracts, ~1% of 1,000-contract targets, ~$2–3 projected per market, ~$122 collateral | Analysis done after 1–2 h of data | Operator decides; any change is a D-level decision with its own restart |
| 7 | **Startup time and public 429s** | 55.9–58.0 s to `runtime_started`; 4–7 `/markets` 429 retries | Comfortably inside the allowance | Approaching 180 s, or 429s growing |
| 8 | **General health** | 0 positions; 1 ERROR (the 404) and ~23 WARNING per 10 min | No unexplained ERROR; entries allowed most of the time; loss window not held | Any position without an exit plan, writer/engine failure, or loss-window hold |
