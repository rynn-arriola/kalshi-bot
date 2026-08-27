# Active work queue

Last updated: 2026-08-27 06:50 America/New_York.

This file contains executable next work only. Current truth is in `STATUS.md`;
operator authority is in `DECISIONS.md`; the experiment contract is in
`EXPERIMENT.md`.

## 1. Keep the isolated server shadow healthy

The operator advanced the read-only shadow before the historical replay was
complete. The 14-day capture is active as
`kalshi-readonly-capture-14d` in `/root/kalshi-bot` at commit `c135242`.

Tasks:

1. Let the daily read-only capacity heartbeat check service health, newest-data
   age, errors, projected disk, memory, OOM events, and Polymarket process
   identity. It must alert rather than restart or modify either process.
2. At the seven-day checkpoint on 2026-09-03, preserve the exact capture window,
   row counts, error/gap rates, tracked universe, and resource use.
3. Do not treat partial data as profitability. Run current-rule reward, fill,
   and later-book exit analysis only over named complete windows.
4. Let the run finish on 2026-09-10 unless errors, disk pressure, or production
   interference require the documented stop command.
5. Quantify the hourly density-scan gaps in downstream analysis. The first
   eight hours showed a 60-second median sample gap, 108-second p95, and
   267-second maximum because each hourly candidate scan takes about 200
   seconds. Do not count the missing intervals as observed qualification.

Done when the 14-day dataset is closed cleanly or an evidence-backed stop is
recorded in `STATUS.md` and `FINDINGS.md`.

## 2. Build the fixed-universe size replay

**Why first:** the existing size sweep changes markets at every size, so it
cannot identify the per-market size response or a trustworthy optimum.

Tasks:

1. Split each capture into an earlier selection window and later evaluation
   window.
2. Produce two separately labeled universes: exact-transfer sports/day-of
   markets and an all-category Kalshi adaptation. Do not combine them.
3. Freeze candidates from the earlier window without future information.
4. Apply the audited 2¢ entry window, side-specific 10¢–90¢ filter, and
   stressed-complete-exit admission.
5. Evaluate every size on the same later snapshots and same market set.
6. Report per market:
   - competing discounted score;
   - our share and marginal reward at each size;
   - qualification fraction and score concentration;
   - collateral convention;
   - excluded-snapshot multiplier and payout-minimum effect.
7. Keep reward, realized/simulated trading P&L, fees, unknown exposure, and
   collateral in separate columns.

Done when:

- no size row changes the evaluated market set;
- selection and evaluation timestamps print in every report;
- `$ / contract`, reward/collateral, and bounded net/collateral are separate;
- `july-2026-one-fifth` and its source date print in the result.
- the audited Polymarket source commit prints in the result.

## 3. Integrate corrected later-book exits into the same clock

`exit_cost.py` now prices the first usable book at/after the deadline and labels
missing or thin books unknown. The final replay must use that path instead of
five-minute markout.

Tasks:

1. Carry the actual filled quantity and signed YES-equivalent position.
2. Report passive close, timed cross, settlement, and unknown separately.
3. Charge known taker fees at VWAP and keep maker fees explicitly unknown.
4. Stop reward accrual until each position is closed or settled.
5. Bound every unknown position at maximum loss, a stated central assumption,
   and zero-loss optimism; never silently drop it.
6. Add time splits and bootstrap/sign bounds where sample size permits.

Done when every simulated fill is priced, settled, or counted as unknown and
the conservative result follows `docs/PNL_ACCOUNTING.md`.

## 4. Run the corrected read-only decision replay

Combine tasks 1–2 on `capture_long.db` and at least one other capture.

Required report:

- selection and evaluation windows;
- frozen market universe;
- current reward rule and source date;
- conservative, central, and optimistic reward/cost/net;
- sensitivity to size, qualification uptime, and exit delay;
- count and contracts for every unknown exit;
- explicit reasons the result can or cannot support Stage 2.

Decision outcome:

- If the optimistic bound is negative, recommend stopping.
- If the conservative bound is positive across time splits, recommend designing
  the read-only live shadow.
- Otherwise name the cheapest measurement that separates the cases.

## 5. Design—not build—the minimal evidence probe

This task may produce a specification and safety review only. Live order code is
not authorized by D-004.

The design must fix one exact market/program, size, duration, predicted payout
margin, operator-selected maximum capital/loss, post-only behavior, durable
intent, unknown-order recovery, cancel/flatten procedure, complete accounting,
and success/stop/inconclusive criteria.

## Do not start

- Production package or autonomous market selector.
- Multi-market scheduler or live order adapter.
- Authenticated write endpoint.
- Trading deployment/supervision system.
- Capital sizing or a live candidate recommendation.

Those require a new operator decision after the experiment produces a
build/no-build recommendation.
