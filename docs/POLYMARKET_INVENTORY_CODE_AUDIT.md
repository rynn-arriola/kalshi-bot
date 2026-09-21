# Polymarket inventory: code verification

2026-09-19. Read-only reference checkout:
`C:/Users/rynna/Bots/liquidity-bot`, HEAD
`54ac71a241d1ad6f02e3445655bb7115247bac02`.
Claims below come from executable source paths and offline tests, not Markdown
assertions. This does not prove the settings of an already-running process.

September 20 follow-up: [expanded policy code audit](POLYMARKET_POLICY_CODE_AUDIT.md)
adds verified partial-close/fee/clock behavior, selection and restart tracing,
and the conditional one-tick passive-exit pricing detail. D-023 now directs
limits-driven capacity rather than choosing an arbitrary fixed slot count.

## Configuration reaches the engine

- `scripts/supervise_commissioning.sh:101` passes quote size and at line 104
  passes configured market slots to the runner.
- `src/liquidity_bot/live_commissioning.py:11210` builds CommissioningConfig
  from CLI arguments; source mode selects AccountSourceRunner, using the same
  reconciler. No 32-slot live value is hardcoded here.
- `src/liquidity_bot/commissioning.py:360` computes market exposure as
  `quote_size * 9`; line 366 computes portfolio exposure as
  `quote_size * (max_markets + 10)`.
- `live_commissioning.py:774` passes those computed values into the
  reconciler, along with inventory timeout and early-exit allowance.
- `reconciler.py:857` checks the proposed market's candidate loss against
  the market cap, and other-market exposure plus that candidate against the
  portfolio cap; refused candidates cannot become new entry actions.

At size 10 the market cap is $90. Portfolio examples: 20 slots = $300;
30 = $400; 32 = $420. The resting-entry-order ceiling is a separate setting.
The earlier Kalshi documentation prematurely treated $420 as a fixed adopted
limit without a selected market-slot count. Preserve the formula; resolve
Kalshi market capacity with the operator, not from the 30-order ceiling.

## Exposure accounting correction

`live_commissioning.py:4094` computes other-market worst loss across the
managed/owned scope, including:

- inventory valued using entry basis (full unit loss if basis is unknown);
- every returned working or unknown-absent order at remaining quantity;
- unresolved PLACE reservations without an order row, net of recorded fills.

It does not exclude reducing orders from this conservative dollar-exposure
sum. Avoid double counting row-backed intents. The 30-entry-order exclusion
for positioned-market orders is not an exclusion from dollar-exposure checks.
Do not describe the reference exposure meter as building orders only.

## Inventory handling and actual exceptions

- `reconciler.py:651` onward: exact absolute position is the reducer quantity;
  cancel the risk-building side and wrong/duplicate reducers before replacement.
  A valid exact reducer at the touch is kept; no fresh entry is planned in this
  positioned-market path. An entry-side order can remain while cancellation
  is pending; the policy is not a claim that cancellation is instantaneous.
- `commissioning.py:154`: 900-second inventory timeout.
- `commissioning.py:277`: early crossing allowance = `0.8 * quote_size`,
  or $8 at size 10.
- `reconciler.py:510` onward: five-minute pre-event, maintenance and HARD
  exits override ordinary waiting. Ordinary timeout crossing may defer for
  incomplete exit depth or projected loss beyond its allowance; retain the
  passive reducer. Cancel confirmation and exact remaining quantity precede
  IOC, with bounded attempts and escalation. Fifteen minutes is not a promise
  of flatness; illiquidity can prevent even a mandatory exit.
- The exact tradable fractional-residue exception and event clock remain
  Polymarket-specific until mapped to Kalshi contracts.

## Verification performed

On native Windows, the reference checkout's Python ran all tests in
`tests/test_commissioning.py` and `tests/test_reconciler.py`:
**104 tests passed**. Initial direct discovery lacked the source import path;
rerunning with `src` inserted into the interpreter path succeeded without
installing packages or changing code.

Coverage includes breadth-dependent exposure, first-fill building cancellation,
exact reducers, portfolio refusal, expensive early-cross deferral and the
event-deadline override. This is not the full Polymarket suite, an integration
test of Kalshi, or a check of live Polymarket deployment/account state.
No credentials or venue requests were used, and no trading process was changed.

## Percentage-based reduction: code verified, accepted by D-021

The operator subsequently requested "percentage position reducer." The
matching percentage mechanism found is the resting-entry cap, not partial
liquidation of an open position:

| Closed-trade net loss threshold | Budget remaining | Maximum resting entries |
|---|---|---|
| $0 | 100% | 30 |
| $5 | 80% | 25 |
| $10 | 60% | 20 |
| $15 | 40% | 15 |
| $20 | 20% | 10 |
| $25 or more | 0% or exhausted | 0 |

Sources: `config/risk_window_policy.json`,
`risk_windows.py:73` (cap calculation), and WindowRiskMeter.observe
(minimum of persisted and newly computed cap).
`live_commissioning.py:_observe_risk_window` supplies ledger realized P&L,
stores the resulting cap, and the overflow/admission paths enforce it.
This cap only tightens within a window, including after restart or subsequent
profit recovery. HARD requires later-window and fresh flat/account proof to
release. Positioned-market orders and reducers are excluded from entry count.
The entry quantity remains 10; the rule does not sell 20% of inventory.

All **22 tests in test_risk_windows.py passed** on Windows, in addition to the
104 configuration/reconciler tests. Tests use offline fixtures, not live orders.
D-021 accepts this as Kalshi's entry-cap policy. It does not authorize an
invented fractional-inventory liquidation strategy.
