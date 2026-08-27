# Active work queue

Last updated: 2026-08-26.

This file contains executable next work only. Current truth is in `STATUS.md`;
operator authority is in `DECISIONS.md`; the experiment contract is in
`EXPERIMENT.md`.

## 1. Reconcile or bound the Kalshi reward rule

**Why first:** every reward dollar, density ranking, one-tick claim, and sizing
result depends on it.

Tasks:

1. Archive the exact current Kalshi Help Center language and governing filing
   date used for analysis.
2. Confirm whether a newer governing notice supersedes the February 2026 filing.
3. Write hand-calculated book fixtures covering:
   - a thin best level below one fifth of Target Size;
   - several levels above the proposed reference price;
   - a side that fails Target Size;
   - a two-sided snapshot and an excluded snapshot;
   - a payout just below and just above $1.
4. Implement the filed-best-bid and current-help-one-fifth interpretations as
   explicit modes if the conflict remains.
5. Under the current-help mode, scale the payable pool by the fraction of
   non-excluded snapshots.
6. Never label one mode `correct` until the source conflict is resolved.

Done when:

- fixtures are independently checkable from the markdown explanation;
- both modes are tested and produce named, intentionally different results;
- every report prints its rule mode and source date.

## 2. Replace the portfolio-changing size sweep

**Why second:** section 18 changes markets at every size, so it cannot identify
the per-market size response or a trustworthy optimum.

Tasks:

1. Freeze a candidate universe using an earlier selection window.
2. Evaluate all sizes on the same later snapshots and the same market set.
3. Report per market:
   - competing discounted score;
   - our share and marginal reward at each size;
   - qualification fraction;
   - collateral convention;
   - payout-minimum effect.
4. Separate reward return from simulated markout return.
5. Show capacity gained by size versus capacity gained by adding a market.

Done when:

- no size row changes the evaluated market set;
- `$/contract`, `reward/collateral`, and `net/collateral` are separate columns;
- the result is reported under every retained reward-rule mode.

## 3. Bound adverse selection using the later book

**Why third:** the current exit model captures immediate depth and fees but can
miss the price move that dominates the reference strategy's loss.

Tasks:

1. Reprice forced exits using the first usable book at the intended exit time,
   not the book at fill time.
2. Report passive close, timed cross, settlement, and unavailable-book outcomes
   separately.
3. Carry unpriced outcomes as missing exposure, not zero cost.
4. Use time splits and bootstrap/sign bounds where sample size permits.
5. Stress with the Polymarket reference's realized per-contract loss without
   claiming venue equivalence.

Done when:

- every simulated fill ends in a priced exit, settlement, or explicit unknown;
- the conservative net bound includes fees and lost reward while unquoted;
- the direction of static-book bias is stated.

## 4. Run the corrected read-only decision replay

Combine tasks 1–3 on `capture_long.db` and at least one other capture.

Required report:

- selection window and evaluation window;
- fixed market universe;
- result under both rule interpretations if still unresolved;
- conservative, central, and optimistic reward/cost/net;
- sensitivity to size, qualification uptime, and exit delay;
- explicit reasons the result can or cannot support Stage 2.

Decision outcome:

- If the optimistic bound is negative, recommend stopping.
- If the conservative bound is positive across time splits, recommend designing
  the read-only live shadow.
- Otherwise name the cheapest measurement that separates the cases.

## 5. Design—not build—the minimal evidence probe

This task may produce a specification and safety review only. Live order code is
not authorized by D-004.

The design must fix:

- one market, exact program, rule interpretation, size, and duration;
- predicted payout above the per-program minimum with margin;
- maximum capital and maximum loss for operator selection;
- post-only behavior;
- durable intent and unknown-order recovery;
- independent cancel/flatten procedure;
- complete reward/fill/fee/settlement accounting;
- success, stop, and inconclusive criteria.

The next operator decision request is created only after the preceding read-only
gates justify it.

## Do not start

- Package skeleton for a production bot.
- Multi-market scheduler or autonomous selector.
- Live order adapter or authenticated write endpoint.
- Deployment/supervision system.
- Capital sizing or a live candidate recommendation.

Those require a new operator decision after the experiment produces a
build/no-build recommendation.
