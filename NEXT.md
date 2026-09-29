# Active work queue

## Pending work (2026-09-26; build 04ff303 live with D-151 and D-152)

**Dated follow-ups — do not drop:**

- **Finding 223 follow-ups:** explain why the recovery-only child could not
  read its pipe for > 4 s; decide whether an operator stop with a held
  position beyond the D-160 limit should time out to Command 1 instead of
  waiting indefinitely.

- **D-161 order of work (operator, 2026-09-29) — do not reorder:** (1) real-time
  LIP meter per contract, validated against payouts to within a few percent
  (LIVE since 2026-09-29 ~15:33 UTC; check "LIP meter per contract" in the
  calibration report after each payout morning; diagnose the ~1–2
  "unscored" contracts per sample: add the ticker and reason to status);
  (2) L2 order book recording for watched markets (size first); (3) phase 3
  ($1 finish line per contract) on top of the meter. The $1 floor is per
  contract, not per event.
- **Business plan (agreed 2026-09-27; decisions B1–B6 in WATCHLIST):**
  1. Measure — done: calibration report has "Fill losses before and after
     the loss filters" and "$1 finish line". Run it from the dev copy with
     `--db/--rewards/--ledger` pointing at `data/trader` until deployed.
  2. Learn — 09-28 and 09-29 payouts (B2); loss filters (B3) and stop rule
     (B1) on 09-30.
  3. Concentrate — build phase 3 after B2 (design below).
  4. Pull balance — phase 4, ≥ 3 days after phase 3.
  5. Scale — only after a full week net positive (B6).
- **Phase 3 design (PROPOSED, not built; operator decides at B4): $1
  finish-line selection.** Kalshi pays nothing for a program that ends under
  $1, so rank by expected *payout*, not reward rate:
  - Per program the bot keeps: earned so far (tracker estimate × the B2
    calibration), hours left, reward rate, and our measured resting share in
    that market (fallback: the global median, 12% on 2026-09-27).
  - Expected total = earned + rate × hours left × share. Enter or keep only if
    it clears $1 with margin (e.g. $1.25); its value is then that total, else
    zero (skip, and never re-enter a program that cannot reach $1).
  - Priority: (a) programs we have started that are on track, by $ unlocked
    per hour resting; (b) programs near $1 with little time left; (c) new
    programs by expected payout. The existing continuation credit in the
    entry gate is reused.
  - The full scan and launch scope (D-158/D-159) score markets the same way.
  - Unchanged: every loss check (downside cap, family memory, sweep filter,
    loss limits).
  - In-process resting-share counter: BUILT (measurement only,
    `resting_share.py`; per market, leg-time / 2 over time since first
    rested, 5 s samples, gaps > 30 s not counted, saved to
    `data/trader/resting_share.json` every 5 min). Status:
    `runtime.resting_share` (markets, median_share). Live since 2026-09-27
    23:43 UTC (`3412bfd`) sampling the strict snapshot join, which was
    unverified in ~43% of samples; fixed on the branch to read the live
    private order stream (`resting_entry_legs`), unknown only while
    disconnected. Fix live since 2026-09-28 00:05 UTC (`a11a944`): 1 unknown
    in the first 35 samples (the startup one); history kept across restart.

- **D-159 live since 2026-09-27 22:55 UTC (build `cec3b26`).** The deploy
  launch used a seeded top-200 scan (`scan_markets` 103). At the next restart
  check `candidate_scope_prepared`: `scan_markets` in the hundreds (up to
  896) and `scan_age_minutes` under 180.
- **Finding 220 option B (later, design first):** periodic shard-by-shard
  rescope of the non-held watch list from fresh scores, so the watch list
  follows the scan without a restart.

- **Finding 218 fixes live (build `cec3b26`).** Catalog and market
  metadata now retry after exhaustion; `entries_idle` warns after 15 minutes
  at 0 resting. Never run parallel public scans on the bot machine — use
  `scripts/market_scan.py` (paced) or the in-bot scan.

- **D-156/D-158 live since 2026-09-27 (build `669e1a2`).** Watch `full_scan`
  (a pass every 30 min, fresh, ~4,300+ scoring) and WATCHLIST 18–19.

- **Each payout morning (09-28, 09-29, 10-05, 10-07):** run the calibration
  report; compare "paid ÷ strict" and "paid ÷ resting-based" (D-157). Base
  reward decisions on whichever tracks payouts; if both are far off, fix the
  tracker before the ranker (D-156) uses its numbers.

- **Deploy D-156 at the next approved restart** (recording only; operator
  asked not to restart on 2026-09-27). Then check `candidates` every 15 min and
  `sweep_counts` hourly in research.db.
- **~2026-10-18 — market ranker (D-156).** With three weeks of payouts, build
  the ranker (reward × weighted paid/estimated − expected fill cost), backtest
  on recorded `candidates`/`sweep_counts`/fills, then shadow before any
  slot-order change. Until then, watch "paid ÷ estimate" in the report after
  each payout morning (next: 09-27, 09-28, then 10-04 with 70 programs).

- **D-155 follow-up (weekly with the calibration report):** blocks by the
  downside cap, family memory and sweep filter vs fills avoided and reward
  given up; pull trigger re-evaluated as more sweeps accumulate (Finding 216
  was balanced on 16 hours). Size stays 30 until payouts prove the reward side.
- **Reward tracker `source_lost`: answered, no fix.** It means "no current
  sample": every program in a market without our resting orders. All
  programs with our orders show `observed_orders` (25 of 25 quoted markets).
  It only makes the tracker's observed fraction look low.


- **2026-09-27 ~20:00 UTC — pull retune decision (D-152, Finding 213).** Run
  `python -B scripts/calibration_report.py --days 2`. Read "Protective pulls"
  precision and "Pull trigger vs real trades": trade-backed share and
  **skipped but gone** (a trade-only rule's misses; Finding 206's KXWMTCC save
  was exactly such a case). Then choose with the operator: (a) trade-evidence
  trigger (needs a separate `trade` feed), (b) stricter thresholds (e.g.
  sustained depletion over longer than the 10 s trend), or (c) short-queue +
  blind only, relying on the 31-contract cap. Run the new rule in shadow first.
- **Entry gate: answered (Finding 213).** Lease revoked by each account write
  and renewed seconds later; resting entries 49.6–49.9 of 50, so no fix
  needed now. Recheck only if average resting falls below ~45.
- **Full account checks from snapshot lag (measured 21:55–02:00 UTC).** 64–79
  full recoveries/hour, 4.8% of the time; the largest cause is own-order
  renewal escalating (40/h). `order_not_visible`: 265 of 290 within 2 s of
  our own placement/cancel, i.e. Kalshi's REST snapshot lags the stream.
  Candidate fix (bundle with the 2026-09-27 restart): when a renewal fails
  only on orders we changed in the last ~3 s, wait ~1.5 s and retry once
  before a full recovery (also WATCHLIST 5's 404s).
  `owned_order_terms_mismatch` (150): only 79 within 5 s of our own action;
  71 are not explained by our lag. D-153 (built, deploys with the 2026-09-27
  restart) logs which field differs and how old our evidence is; decide the
  retry change from that, after the pull change has settled. Note: a venue
  showing *less* remaining without a fill is already rejected earlier as
  `invalid_data`, so those 71 are not that case.
- **Research failures: answered and cleaned up (D-155).** Trade reads that
  overlap a read-quota refresh now count as `trade_read_skips`, not failures;
  the window does not advance, so no data is lost.
- **Storage (operator phrase "run storage management").** Run every 1–2 days
  until the backlog clears (~13 Polymarket daily backups and ~80k test
  folders; 8 GB per run). Daily schedule declined 2026-09-26. The 4.5 GB old
  OneDrive copy is in the Recycle Bin (operator empties it).
- **Cross-project, operator's call:** (1) Polymarket test leak, a one-line fix
  in `liquidity-bot/tests/test_live_commissioning.py:478` (declined for now);
  (2) Polymarket runner crash 20:24 UTC 2026-09-26, `RuntimeInvariantViolation:
  working order has no owned place intent` after "Order not found" 404s from
  19:56, to hand to that project's operator.


00. **Check D-151 after a few hours:** `health_hourly` rows each hour,
    `withdrawal_marks` after pulls, research status `alive` with no drops.
    First 22 min: 482 rows, 0 dropped; `failures_in_runtime` 3 (one of 380
    programs had no computable estimate; 2 unattributed). Small follow-up for
    the next deploy: count research failures by site and exception type in
    status. Trades 0 is real (one trade in 30 min across pulled markets); the
    13 pulls were driven by cancellations ahead, not trading.
    First `health_hourly` row (19:15–20:00): entries allowed only 51% of
    samples, yet 48.1 of 50 entries resting on average. `runtime_health` shows
    the same ~40–50% all day on the previous build too (not a D-151
    regression). Remaining causes are the accounting result not released or
    its lease fence not current, i.e. likely the proof renewal cycle. Next
    deploy: sample which `entry_allowed` term is false, then decide whether
    refills after pulls are being delayed enough to matter.
0. **Shadow screen evaluation (D-150):** after 1–2 days, run
   the calibration report, `scripts/calibration_report.py` (verdict × fills × reward); the 25%
   reward-to-risk cut flags ~80% of entries at 30 contracts, so it needs
   calibration first.
1. **Measure D-145–D-148 over hours** (WATCHLIST item 10): fills, protective
   pulls per market-hour, blind withdrawals, order-group state, full recoveries
   vs `post_drain_renewals` / `routine_own_fallbacks` (first 32 min: 24 full
   recoveries, 59 post-drain renewals, 17 routine hand-overs, 72 pulls, 0 fills).
2. **Reward payout reconciliation** when Kalshi pays: profitability is unproven
   (realized −$31.94 since 2026-09-22 incl. the 2026-09-26 manual close).
3. **Fill avoidance (strategy, operator decision):** reward-vs-risk rule and
   the ~2,000 contracts/week volume screen (Finding 210) in shadow mode first;
   post-fill market cooldown (WYCOAL was swept twice in one day).
4. **Contract-size result** at 30 vs 10 (item 0c below), after enough hours.
5. Optional: order-group fire drill (empty group, manual trigger); a real
   reboot test of the autostart chain (task + auto sign-in + Claude startup).
6. Polymarket handover note if the operator wants auto-resume after reboot
   (that project flattens and stays paused by design).
7. Finish the line-by-line review of modules listed in Finding 200.

## Earlier queues

Completed and superseded queues are preserved in [docs/history/NEXT_ARCHIVE_2026-09-26.md](docs/history/NEXT_ARCHIVE_2026-09-26.md).
