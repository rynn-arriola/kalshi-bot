# Active work queue

Last updated: 2026-08-28 23:45 America/New_York.

This file contains executable next work only. Current truth is in `STATUS.md`;
operator authority is in `DECISIONS.md`; the experiment contract is in
`EXPERIMENT.md`.

## 1. Keep the isolated laptop shadow healthy

The first server shadow ended after 9h51m on a transient TLS EOF. Its closed
dataset is preserved locally. The former server was destroyed, ending R3 and
resetting the collection clock. Retry-hardened laptop R1 is active at commit
`0043c3a`, with a seven-day checkpoint at 2026-09-05 03:39 UTC and planned
completion at 2026-09-12 03:39 UTC.

Tasks:

1. On each manual check, verify laptop R1 is active, data is current, exhausted
   transport failures are recorded as status 599 rather than fatal, and
   resource limits hold. Use SSH alias `poly-laptop` and WSL unit
   `kalshi-readonly-capture-14d-laptop-r1`; this task is Kalshi-only.
2. At the replacement run's seven-day checkpoint, preserve the exact capture
   window, row counts, error/gap rates, tracked universe, and resource use.
3. Do not treat partial data as profitability. Run current-rule reward, fill,
   and later-book exit analysis only over named complete windows.
4. Let the replacement run finish unless errors, disk pressure, or production
   interference require the documented stop command.
5. Quantify the hourly density-scan gaps in downstream analysis. The first
   eight hours showed a 60-second median sample gap, 108-second p95, and
   267-second maximum because each hourly candidate scan takes about 200
   seconds. Do not count the missing intervals as observed qualification.
6. At each checkpoint, use SQLite's online backup API to make a consistent
   snapshot on the laptop, integrity-check it, then copy the closed snapshot and
   matching log into this PC's ignored `data/` directory. Never copy the live DB
   file directly and never add runtime data to GitHub.

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
8. Report pure spread scalping separately: completed-pair spread, one-sided
   inventory, passive/crossed exit, fees, unknowns, and net. Then report the
   combined reward-plus-scalping strategy without mixing clocks or universes.
9. Within the pure-scalping report, compare join-the-touch and feasible 1¢,
   2¢, 3¢, 4¢, and 5¢ quote gaps on identical evaluation data. Print pair
   completion, one-sided fills, holding time, gross spread capture, maker/taker
   fees, realized or bounded exit loss, unknown exposure, net dollars, and
   net/collateral for every width. Do not include reward dollars.

Done when:

- no size row changes the evaluated market set;
- selection and evaluation timestamps print in every report;
- `$ / contract`, reward/collateral, and bounded net/collateral are separate;
- `july-2026-one-fifth` and its source date print in the result.
- the audited Polymarket source commit prints in the result.
- the recommended pure-scalping width, if any, remains positive under the
  conservative unknown-exit bound and across multiple time splits; otherwise
  the result says no tested spread is profitable rather than selecting the
  least-negative width.

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
