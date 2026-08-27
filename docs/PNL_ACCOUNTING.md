# Measurement P&L accounting contract

Last checked: 2026-08-26.

The transferability decision uses complete strategy economics, not liquidity
reward alone:

```text
paid liquidity reward
+ realized P&L from every filled position
- entry and exit fees
- reward lost while inventory prevents quoting
= measured net strategy P&L
```

`net` is reserved for a result in which every term above is priced or bounded.
Five-minute markout is a diagnostic for adverse selection; it is not realized
trading P&L and is labeled `proxy` in reports.

## Reward

- Score the actual two-sided book under `july-2026-one-fifth`.
- Insert the hypothetical order into the ladder before finding the reference
  and Target Size cutoff.
- Multiply the pool by the non-excluded snapshot fraction.
- Round down to cents and apply the $1 minimum per program.
- Accrue no reward while the simulated strategy is not resting.

The reward is **predicted**, not paid, until reconciled to an actual Kalshi
payout. The historical `february-2026-best-bid` mode is a regression comparison
only for captures on or after July 30, 2026.

## Filled-position P&L

Reduce every fill to signed YES-equivalent economics:

```text
direction = +1 for long YES, -1 for long NO / short-YES equivalent
trading P&L = direction × (YES exit price - YES entry price) × contracts
```

Each fill must end in exactly one category:

1. **Passive close:** a reducing maker order fills before its deadline.
2. **Timed cross:** the whole position is executable against the first usable
   book at or after the deadline; charge the taker fee at actual VWAP.
3. **Settlement:** a recorded YES/NO result prices the remaining position.
4. **Unknown:** the later book is missing, stale, or too thin and no settlement
   is recorded.

Unknown exposure is never assigned zero P&L. A report must show its count and
contracts. Conservative/central/optimistic bounds must state the explicit
price assigned to unknown exposure, including the maximum-loss bound when used.

## Fees and opportunity cost

- Taker fees use the filed/account-verified price-dependent formula at actual
  execution price and quantity.
- Maker fees remain `UNKNOWN` until measured from a Kalshi maker fill; do not
  silently assume zero.
- Time spent holding inventory removes the strategy's reward score. The replay
  must debit this by stopping reward accrual, not by adding an unrelated
  haircut after the fact.
- Collateral and open exposure are reported separately from P&L.

## Evidence gate

A historical result may be called a complete simulated net only when the fixed
market universe, selection/evaluation split, reward rule, fill model, every exit
category, all fee assumptions, unknown-exposure bound, and lost-reward interval
are printed with it. Live profitability remains unverified until paid rewards
and actual fills reconcile to the same ledger.
