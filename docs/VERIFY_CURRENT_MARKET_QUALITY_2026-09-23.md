# Current live market-quality check — 2026-09-23

## Result

At 10:47:46–10:49:21 UTC, the existing public-only broad census evaluated all
1,024 reviewed markets using fresh WebSocket books, current public incentive
programs and the production metadata/selection gates. It made 582 public REST
requests, no private REST requests and no order changes. The bot remained healthy
on the same child with 30 resting orders, no reported position and $127.60
reserved exposure after the check.

The census found 148 markets passing the $1, two-sided-depth and 70% retained-
value gates; 40 projected at least $2 remaining. All 15 currently owned markets
passed, but only four were in the $2+ tier. Diagnostic ordering applies the
production $2-first rule and then current gross hourly reward; it is not account
admission authority.

| Current market | Tier | Diagnostic rank / 148 | Remaining estimate | Hourly estimate | Minimum retained value | Existing vs current bid/ask reference |
|---|---:|---:|---:|---:|---:|---|
| KXAMZNCC-26OCT07-T112 | $1 | 116 | $1.140 | $0.0084 | 83.8% | exact |
| KXBROADLINEADS-26OCT06-T133 | $1 | 49 | $1.834 | $0.0146 | 92.9% | exact |
| KXBUDLIGHTPOS-26OCT03-T87 | $1 | 91 | $1.272 | $0.0102 | 98.7% | ask 48c vs 43c reference |
| KXCARTAPP-26OCT08-T124 | $1 | 64 | $1.602 | $0.0128 | 94.7% | exact |
| KXORBOFHARVEST-27NOV30-T180 | $2+ | 27 | $3.096 | $0.0120 | 97.7% | exact |
| KXPEPSIPOS-26OCT03-T97 | $1 | 75 | $1.647 | $0.0122 | 89.0% | exact |
| KXROGUEPOS-26OCT03-T73 | $1 | 42 | $1.887 | $0.0152 | 90.6% | exact |
| KXSPRITEPOS-26OCT03-T91 | $1 | 89 | $1.299 | $0.0105 | 81.4% | exact |
| KXTEENCLOTHADS-26OCT06-T144 | $1 | 121 | $1.041 | $0.0083 | 97.2% | exact |
| KXTGTFT-26OCT08-T92 | $1 | 105 | $1.166 | $0.0093 | 93.6% | exact |
| KXTOKENUSE-26SEP28-T138 | $1 | 50 | $1.303 | $0.0146 | 116.0% | bid 43c better than 39c reference; ask exact |
| KXTOKENUSE-26SEP28-T144 | $2+ | 7 | $3.089 | $0.0347 | 95.4% | exact |
| KXTOKENUSE-26SEP28-T150 | $2+ | 16 | $2.194 | $0.0246 | 102.4% | exact |
| KXTOKENUSE-26SEP28-T152 | $2+ | 17 | $2.079 | $0.0233 | 95.1% | exact |
| KXWIMILK-27FEB28-T33.25 | $1 | 130 | $1.733 | $0.0067 | 90.8% | exact |

Fourteen markets had both orders at or better than the sampled references:
13 exact pairs and one better bid. BUDLIGHT's ask was five ticks worse than the
sampled reference. Its current program has a 50% per-tick discount, so five ticks
would retain only 3.125% price weight on that side if still inside the cutoff;
outside the cutoff it receives no score there. The bot has no automatic repricing.

The current slate's sampled estimates total $26.38 remaining and $0.218/hour.
The diagnostic top 15 total $44.05 and $0.494/hour. These are sequential,
hypothetical-current-reference estimates, not simultaneous allocation proof,
guaranteed payment or net profitability. The census assumes a flat $500 account
to isolate market gates; it does not authorize replacement, prove queue position,
or include fill/trading-loss outcomes. Public books are aggregate and do not
identify our quantity, so the reference comparison is diagnostic rather than a
private/public reflection proof. The top 15 are also concentrated in related
Diesel/Token Use ladders; they are not a recommended account allocation or a
correlation-risk analysis. Current incumbents are deliberately not replaced by
later higher-ranked markets.
