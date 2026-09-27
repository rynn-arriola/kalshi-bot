# Active work queue

## Pending work (2026-09-26; build 04ff303 live with D-151 and D-152)

**Dated follow-ups — do not drop:**

- **Swept-market screen (Finding 214).** Stay out of a market for a while
  after a large one-sided sweep (e.g. ≥ 5× our size) on the side we quote; the
  research `trades` table has the data. Size the rule from the calibration
  report's sweep section at the 2026-09-27 review, together with the pull
  decision and the D-150 volume screen verdicts.

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
- **Research failures: answered.** All `trades_read:QuotaUnavailable` during
  read-quota refreshes; no data lost. Optional cleanup at a later deploy:
  count them as a skip, not a failure.
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
