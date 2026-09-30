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

## Business decisions pending — what we measure for each

Agreed plan (2026-09-27): measure → learn from payouts → concentrate on the
$1 finish line → balance pulls → scale only when net positive. Numbers come
from the calibration report (`scripts/calibration_report.py`, live data) and
the ledger. Each decision is the operator's; this table says what evidence
decides it and when. Baselines 2026-09-27 23:30 UTC.

| # | Decision | Measure (report section) | Baseline | Decide when | Rule of thumb |
|---|---|---|---|---|---|
| B1 | **Keep running or pause** (stop rule) | Trading $ after the loss filters ("Fill losses", after row) + rewards paid ("Business summary") | Net −$40 since 09-23; after filters 0 fills in 0.5 day. 2026-09-28 12:45 UTC: −$19.63 after filters (Finding 221); operator chose to keep running | 2026-09-30, or earlier if hit | Pause and rethink if trading loses more than $20 after the filters by 09-30 and rewards are not clearly above estimates |
| B2 | **Which reward estimate to trust** (sets phase 3 numbers) | "Reward truth": paid ÷ strict and paid ÷ resting-based per payout day | One payout: $1.22 = 3.9× strict (09-27) | After the 09-28 and 09-29 payouts (149 programs end 09-29) | Use the estimate closest to what Kalshi paid; if neither is within ~2×, fix the estimate before phase 3 |
| B3 | **Are the loss filters working** (keep, tighten, loosen) | "Fill losses": fills per day and $ per fill, before vs after 09-27 11:42 UTC | Before: 12 fills/day, −$0.86/fill, −$10.26/day | 2026-09-30 (3 days after) | Keep if $/day loss falls by more than half; tighten if big losses repeat; loosen only if fills near 0 and rewards starve |
| B4 | **Build phase 3: $1 finish-line selection** | "$1 finish line": verdict counts, earnings not on track, median resting share; live per-market share in status `resting_share` (after deploy) | 0 cleared, 54 on track, 126 need more resting, 7 cannot; $6.00 not on track; share 12% | After B2 | Go if payouts confirm estimates and many programs end under $1; design in NEXT.md |
| B5 | **Pull trigger balance** (phase 4) | Pull precision ("Protective pulls"), resting share, $ per fill | ~64% of legs pulled after ~3.6 min; share 12% | ≥ 3 days after phase 3 is live | More patience only where a lot is at stake (near $1 or big pools), and only if $ per fill stays down |
| B7 | **Contract size per order** (now 30) | Median reward share per entry (research `entries.snapshot_share`), "$1 finish line" earned per market, $ per fill and worst fills ("Fill losses", ledger) | Share 6.7% median (p90 9.4%): reward ~proportional to size; worst 3 of 48 fills = 52% of trading loss (worst −$12.85) | With phase 3, after B3 (09-30) | Keep 30 while measuring. Larger (e.g. 50) on top markets gets more programs past $1 but enlarges each fill loss: only if $ per fill is under control. Smaller size lowers reward per market and hurts the $1 minimum; only for thin books where our share would exceed ~30% |
| B8 | **Exit loss limit** (Finding 222) — DECIDED: D-160, $0.80/contract (Polymarket rule); watch after deploy | Positions held past 15 min (status `positions`, ledger `lots`), their outcome vs an immediate close (research fill marks at 300/1800 s vs exit) | 1 held: KXUALCC short 30 @ 0.30, close would be −$8.10+fees | Next few held positions, or with phase 3 | Scale per contract ($0.80 → $24) if waiting mostly ends worse than closing; keep holding if prices usually recover |
| B9 | **LIP meter accuracy** (D-161 step 1) | Meter's cumulative earned per contract vs Kalshi's payout for the same ET day (calibration report "Reward truth") | Strict tracker paid 3.9× (one day); 09-27 and 09-28 paid $0 as predicted by the $1 floor | First payout day after the meter is live | Trust the meter for phase 3 only when within a few percent of payouts; otherwise fix the scoring replica first |
| B10 | **L2 recording size** (D-161 step 2) | Bytes per day recorded, disk free (storage guard) | Not recorded | Before enabling | Keep only what fits the disk budget with the storage guard; drop resolution before dropping markets we rest on |
| B13 | **Sweep-prone types and hours** (Finding 224) | Fills per day by market type and UTC hour (`scratchpad/fill_analysis.py` approach); losses per fill | 20 fills 09-27→09-30; 9 bad, ~8 in avoided types; sweeps peak 13:00, 08:00, 03:00 UTC | After ~a week of fills with the exclusion live | Add a type if it produces repeated bad fills; consider a 13:00 UTC pull window if bad fills cluster there; consider resting a tick back only if losses stay high (halves reward) |
| B12 | **Project list** (D-161, after deploy) | Status `finish_line` (active projects, each earned / to $1 / hours left, cleared_total, dropped_total); report "Projects" and "Waste" | Before: 131 contracts in 3.1 h, 0.27 resting h each | Daily | Working if projects gain hours daily and clear $1 within ~1-2 days; act if waste stays above zero, projects stall (blocked by filters for long), or entries sit far below the cap |
| B11 | **Phase 3 effect** (live 2026-09-29 18:11 UTC) | Meter `cleared_live` and contracts past $1 per day; calibration "LIP meter per contract"; payouts; resting entries; fills per day | 0 contracts past $1 at deploy; 127 live contracts metered | Daily, first read 2026-09-30 | Working if contracts clear $1 and payouts appear; act if entries stay far below the cap for hours (too strict: lower COMMIT_SHARE / TARGET) or fills rise |
| B6 | **Add capital / more slots** | Net $ per day ("Business summary") | −$8/day | Only after a full week net positive | No new capital while net per day is negative |

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
| 18 | **Full-market scan** (D-158; launch scope D-159) | Watch list from the pool hint (Finding 220) | `full_scan.fresh` true; ~5,000 markets per pass; `save_failures` 0; after a restart `candidate_scope_prepared` shows `scan_markets` ~896 and a recent `scan_observed_at` | `failures` or `save_failures` rising, pass older than 45 min, `scan_markets` 0 after a restart (fell back), read throttles, or CPU spikes every 30 min |
| 19 | **Entries resting at all** (Finding 218) | 0 resting for 75 min on 2026-09-27 while status said healthy | Resting entries near 50 whenever entries are allowed | Any `entries_idle` event or `entries_idle_seconds` ≥ 900, or `selection_evidence_unavailable` on all candidates: check 429s, `incentives.exhausted`/`cooldown_retries`; restart only if still stuck 10 min after 429s stop (should self-heal now) |
| 8 | **General health** | 0 positions; 1 ERROR (the 404) and ~23 WARNING per 10 min | No unexplained ERROR; entries allowed most of the time; loss window not held | Any position without an exit plan, writer/engine failure, or loss-window hold |
