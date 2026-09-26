# Active work queue

## Pending work (2026-09-26; build 32d1934 live with D-151)

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
