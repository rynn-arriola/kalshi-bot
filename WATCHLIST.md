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
| 1 | **24/7 resilience build** (exchange-status pause/resume, supervisor self-heal, self-expiring orders, auto-start) | D-136–D-143 live since 05:10 UTC 2026-09-26 at 50 × 30 contracts | Built, tested, deployed | Offline exposure until self-expiring orders ship: up to ~$635 collateral |
| 2 | **Withdrawal lockout (D-135)** | 168 withdrawal events / 72 min in 30 markets; ~6.6 min out per episode; ~17% quoting time lost | Lockout downtime and repeat withdrawals well below baseline | Fill within ~2 min of re-entry, or noisy markets cycling faster than about every 5 min |
| 3 | **Own-order renewal** | 8 of 21 completed; all fallbacks unlabelled | Most complete; fallbacks mainly `order_not_visible` and then succeed | `position_changed`, `cash_changed` or `audit_blocked` appearing |
| 4 | **Full recovery time / chain reuse** | 4.28 s median before; 1.8–1.9 s after with 24 of 27 chained | Stays ≤ ~2 s; most passes chained | Median back above 3 s or chaining rare without fills |
| 5 | **Order-lookup 404s after cancels** | 1 in the first 10 min (pass retried fine) | Rare | More than ~3 per hour: add a short settle wait before re-checking just-cancelled orders |
| 6 | **30-contract result** (D-142) + scorecard what-if | 30 contracts × 50 orders from 05:10 UTC; ~$250 collateral at 20 orders | Reward $/hr up; fill losses small vs rewards | Any adverse fill > ~$3, or loss ratchet stepping down |
| 7 | **Startup time and public 429s** | 55.9–58.0 s to `runtime_started`; 4–7 `/markets` 429 retries | Comfortably inside the allowance | Approaching 180 s, or 429s growing |
| 9 | **External cash** (D-141) and **UNKNOWN resolution** (D-143) | $300 deposit credited; 2 phantom creates resolved | `cash_adjusted` only for real funding/rewards; `unknown_create_resolved` rare | Any `accounting_cash_unexplained`, repeated UNKNOWN, or safety pause |
| 10 | **D-145 fill protection** (after deploy) | Protection blind 27% of order time; 0 order groups | Groups `active` on every shard right after start; entries carry the group; `fill_protection.current` true; blind orders near 0 | Any shard group `missing` for > 5 min, `entry_order_group_unavailable` persisting, or a `blind` withdrawal storm |
| 11 | **Pull precision** (D-152, Finding 213) | 3% of pulls justified; 1 of 131 `time_to_fill` pulls trade-backed; ~60% of entries end pulled | Decision taken 2026-09-27 with a day of data | Any fill after a pull the trade rule would have skipped ("skipped but gone" > 0 with a fill) |
| 12 | **Entry gate** (D-152) | ~50% allowed: lease revoked by account writes, renewed seconds later; 49.6–49.9 of 50 resting | Explained (Finding 213); no fix needed | Average resting entries below ~45 of 50 |
| 13 | **Research dataset** (D-151) | 0 dropped; ~6 failures/hour, all `trades_read:QuotaUnavailable` (harmless) | `health_hourly` every hour; no new failure sites | `alive` false, drops, or a failure site that is a real bug |
| 14 | **D-152 deploy** | Deployed 21:51 UTC 2026-09-26 (build `04ff303`) | Deployed with one operator-approved restart; `entry_blocked_fraction` in the next `health_hourly` row and `research.failure_sites` in status | Still undeployed at the 2026-09-27 pull decision: bundle it into that decision's restart so there is only one |
| 15 | **Snapshot-lag full checks** (D-153) | 64–79 full recoveries/h, 4.8% of time; 40/h from own-renewal escalation; 150 terms mismatches in 4 h, 71 not near our own actions | `mismatch_kinds` and ages explain the mismatches after the 2026-09-27 deploy | Any `remaining_venue_*`, `price`/`side`/`ticker` label, or old evidence behind `terminal_but_resting` |
| 16 | **Post-fill cooldown** (D-154, Finding 214) | Live 03:04 UTC 2026-09-27; loaded at start, KXTXOIL/KXBROSFT cooling | `fill_cooldown.loaded` true within seconds of start; no market filled twice within 24 h | `loaded` false or `load_age_seconds` > 60 while running, or entries blocked everywhere |
| 17 | **Loss filters** (D-155) | Live 11:42 UTC 2026-09-27; before: 19 fills −$41.12 (Finding 215) | `sweep_filter.loaded` true, `poll_age_seconds` < 60; fills rarer; entries still near 50 | `sweep_filter` stale or failing (blocks all entries), entries well below 50 for long, or a fill in a market the filters should have blocked |
| 18 | **Full-market scan** (D-158, after deploy) | Discovery by pool hint; 1,024 of ~5,100 watched | `full_scan.fresh` true; ~5,000 markets per pass; top scored markets watched | `failures` rising, pass older than 45 min (falls back), read throttles, or CPU spikes every 30 min |
| 8 | **General health** | 0 positions; 1 ERROR (the 404) and ~23 WARNING per 10 min | No unexplained ERROR; entries allowed most of the time; loss window not held | Any position without an exit plan, writer/engine failure, or loss-window hold |
