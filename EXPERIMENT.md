# Kalshi strategy viability experiment

## Decision this experiment supports

Should the operator authorize building a Kalshi liquidity-reward bot based on
the working Polymarket US strategy?

This experiment does not choose the answer. It produces an evidence-backed
recommendation for the operator.

## Primary hypothesis

After actual qualification uptime, fills, exit losses, and fees, a deliberately
selected Kalshi portfolio can earn positive net reward:

```text
paid liquidity reward
- realized entry/exit trading loss
- maker and taker fees
- reward lost while not qualifying
= net strategy P&L
```

## Competing explanations that must remain separate

- Thin denominators may make initial contracts highly reward-efficient.
- The same thin books may create worse adverse selection and competitor
  reaction than the static replay observes.
- Breadth may scale the strategy better than per-market size.
- Operational resting time may matter, but market selection and pool size can
  dominate it; uptime must not be credited for reward changes without a
  controlled denominator.
- Kalshi's current rule may make stepping inside economically different from
  the Polymarket strategy even though both venues use discounted book share.

## Evidence ladder

### Stage 0 — Rule and accounting audit (completed 2026-08-26)

Read-only. Measurement-only strategy emulation; no production or live-order
code.

Deliverables:

- Reconciled the Help Center to the July 15 certified filing effective July 30.
- Implemented the current and superseded interpretations as named modes.
- Corrected excluded-snapshot pool scaling under the current rule.
- Defined complete P&L accounting in `docs/PNL_ACCOUNTING.md`.

Gate:

- **Passed:** hand-built scoring and payout fixtures execute in the unit suite.

### Stage 1 — Fixed-universe historical replay (current)

Read-only against captured books and trades.

Deliverables:

- Select the universe once, without using future outcomes.
- Sweep size on the same market/snapshot set.
- Report per-market marginal reward, qualification fraction, predicted fills,
  and conservative exit-cost bounds.
- Use time splits: select/rank on the earlier window, score on the later window.
- Use the July rule for the decision result and retain the February mode only
  as a clearly labeled historical comparison.

Gate:

- Stop if the optimistic bound is not positive after fees and conservative exit
  costs.
- Continue if the conservative bound is positive across multiple time splits.
- Otherwise report the strategy as unresolved and name the cheapest
  discriminating measurement.

### Stage 2 — Live read-only shadow

Observe current eligible markets without placing our orders.

This stage may run on the existing server under D-007, but only from the
separate project, process, credential, data, and resource boundaries in
`docs/SERVER_MEASUREMENT.md`. Sharing a host does not authorize touching the
Polymarket directory, service, credentials, or APIs.

Deliverables:

- Persist raw programs, books, trades, and exchange status.
- Generate hypothetical quotes without changing the venue.
- Track how often each quote would qualify and how quickly its economics decay.
- Measure candidate turnover and whether the selector remains predictive out of
  sample.

Limit:

Shadow data cannot prove our queue position, competitor response, actual payout,
or fill-driven adverse selection. It can reject a bad strategy and select a
safe live experiment; it cannot certify profitability alone.

### Stage 3 — Minimal live evidence run (not yet authorized)

One market at a time, intentionally non-scalable. This is not the full bot.

Required before an operator decision to arm it:

- Stage 0 and Stage 1 gates passed.
- Exact market, side policy, size, duration, and maximum loss printed.
- Predicted payout comfortably above the per-program $1 minimum under the
  conservative rule interpretation.
- Both sides of the market already meet Target Size without relying on us.
- Post-only behavior verified or a safe substitute explicitly approved.
- Durable intent written before mutation; unknown order state fails closed.
- Independent cancel/flatten path and a tested stop condition.
- Full accounting plan for paid reward, fills, fees, exits, and settlement.

Measurements:

- Actual paid reward versus each model prediction.
- Eligible resting side-hours and score-hours.
- Maker/taker classification and fee per fill.
- Fill probability and quantity per resting hour.
- Realized exit loss by holding time.
- Any competitor repricing after our order appears.
- Complete net P&L with no unpriced residual position.

The operator chooses the capital limit, loss limit, candidate, and arming
decision after reviewing the proposal.

### Stage 4 — Build/no-build recommendation

No automatic transition to building.

The AI presents:

- conservative, central, and optimistic net estimates;
- sample size and confidence limitations;
- capacity by breadth and by size;
- operational complexity and failure modes;
- what evidence would most likely reverse the recommendation.

The operator decides whether to stop, gather more evidence, or authorize a
separate full-bot plan.

## Reporting standard

Every result must include:

- rule interpretation and version/date;
- dataset and exact time window;
- selection window versus evaluation window;
- market count, snapshot count, and fill count;
- size, policy, capital convention, and fee assumptions;
- whether reward is predicted, pending, or paid;
- which P&L terms are missing;
- known direction of each bias.

No percentage return is reported without showing its numerator, denominator,
and whether simulated markout is included.
