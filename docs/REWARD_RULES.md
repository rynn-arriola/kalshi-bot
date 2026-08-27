# Kalshi liquidity-reward rule sources and fixtures

Last checked: 2026-08-26.

## Current governing implementation

The current measurement mode is `july-2026-one-fifth`.

Kalshi's [July 15, 2026 certified filing](https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizationRules/61766)
amended the liquidity program effective July 30. Its clean terms set the
Reference Price at the first price level where cumulative bid size reaches one
fifth of Target Size. Prices better than the reference receive full weight. It
also multiplies payout by the fraction of snapshots that were not excluded.

Kalshi's current [Liquidity Incentive Program help page](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program)
describes the same reference-price and payout-scaling rules.

The earlier [February 11, 2026 filing](https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizationRules/59670)
used the highest bid as Reference Price and did not contain the later pool
scaling term. The code retains this as
`february-2026-best-bid` for reproducing old reports only. It is
**SUPERSEDED** for the August captures in this repository.

## Hand-checkable scoring fixture

Parameters: Target Size 100, Discount Factor 0.50, tick size $0.01.

| Bid price | Size | Cumulative |
|---:|---:|---:|
| $0.60 | 10 | 10 |
| $0.59 | 10 | 20 |
| $0.58 | 80 | 100 |

Under the current rule, one fifth of Target Size is 20, so the reference is
$0.59. The $0.60 and $0.59 levels get full weight; $0.58 is one tick away:

```text
10 × 1.0 + 10 × 1.0 + 80 × 0.5 = 60 score
```

Under the superseded February rule, the reference is the $0.60 best bid:

```text
10 × 1.0 + 10 × 0.5 + 80 × 0.25 = 35 score
```

If the final level held only 79 contracts, cumulative size would be 99 and the
entire side would have zero qualifying bids. A snapshot counts only when both
YES and NO independently reach Target Size.

## Hand-checkable payout fixtures

Current rule, $100 pool, 20% Time Period score, 8,000 non-excluded snapshots of
10,000 total:

```text
0.20 × $100 × (8,000 / 10,000) = $16.00 payable
```

Minimum and rounding are applied per program. A raw result of $0.999 pays zero.
A raw result of $1.009 clears the minimum and is rounded down to $1.00.

These fixtures are executable in `tests/test_reward_rules.py`.
