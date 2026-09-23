# Kalshi liquidity-reward research and API audit

Current implementation-focused follow-up:
[September 22 reward API re-audit](REWARD_API_REAUDIT_2026-09-22.md).
It confirms the existing larger-page contract, measures a five-page public
catalog read, and identifies unused WebSocket snapshot refresh. Historical
samples and planning constraints below retain their original date/scope.

Research date: **September 19, 2026**. Public API observation: **22:52:11-22:52:39 UTC (6:52pm EDT)**.

Scope: current rules, all publicly documented reward interfaces, a complete active-program inventory, and a one-time 40-book inspection. This is research, **not a trading bot, paper run, or profitability test**. No keys or private account data were accessed. No orders, cancellations, transfers, or deployments occurred.

Historical research constraints: **$500 capital ceiling; fewer than 10 contracts per order; planning only; no paper testing.** Whole-contract examples use 1, 3, 5 and 9, not 10. D-016 later approves 10-contract entries, a 30-resting-entry ceiling excluding position-management orders, and fixed six-hour $25 settled-loss stops. These historical calculations were not rerun at size 10. Inventory caps, exits, markets and duration remain undecided; examples are not orders.

## 1. Bottom line

**INFERRED recommendation:** pursue selective Reference Price quoting as a candidate, not broad reward farming and not a fixed number of ticks behind the best bid. Choose programs by conservative *remaining payable reward minus expected fill/exit cost*, subject to inventory and event-risk limits. Keep capital idle when no candidate passes. Nothing here proves positive live net profit.

The main findings:

- **MEASURED:** 5,251 active liquidity programs on 5,251 markets; every one had discount factor **0.50**. Target size was 1,000 in 5,197 programs, 500 in 19, and 300 in 35. There were no observed factor-1.00 programs to exploit by quoting far behind without a distance penalty.
- **VERIFIED rule:** Reference Price is a depth calculation, not fair value and not a universal offset from the best bid. Full weight means a 1.0 price multiplier, **not 100% of the pool**. [Kalshi scoring guide](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program)
- **VERIFIED correction:** the minimum is **$1 for each individual program**, not the sum across the account. Several sub-dollar programs cannot simply be added into an eligible payout. [Kalshi payment explanation](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them)
- **MEASURED:** 13 of 40 sampled books lacked target depth on at least one side. Of the other 27, only one 5-per-side example and five 9-per-side examples reached $1 from the remaining period in unchanged-book arithmetic. The sample is biased toward high pool/target ratios, short programs and gas markets; it is **not representative of all 5,251 markets**.
- **VERIFIED API coverage:** the only dedicated incentive operation in the published REST specifications is `GET /incentive_programs`. No documented personal liquidity-accrual, eligibility-check, scoring, claim, or reward-credit-history endpoint was found. Do not invent one.

Evidence files: [summary](../data/reward-research/20260919T225211Z/summary.json), [complete active inventory](../data/reward-research/20260919T225211Z/programs.json), [book arithmetic](../data/reward-research/20260919T225211Z/book-analysis.json), [102-request log](../data/reward-research/20260919T225211Z/requests.json). These are dated public observations, not current recommendations.

## 2. Which reward program are we discussing?

| Program | What it rewards | Relevance to this plan |
|---|---|---|
| General Liquidity Incentive Program (LIP) | Qualifying resting liquidity over time | Primary candidate; fills are not required |
| Volume Incentive Program | Eligible executed volume | Possible ancillary revenue, not a reason to manufacture turnover |
| Designated Liquidity Provider Program | Agreed quoting obligations, with auction-based designation | Separate institutional arrangement; not assumed available |
| Sports Prop Combo Component Legs program | Eligible maker executions in component markets | Different economics; not passive unfilled-order income |
| Margin maker/taker volume programs | Separate perpetual-futures activity | Present as API type filters; outside the approved event-contract strategy |

The designated program requires a Market Maker Agreement and series-specific requirements. Its advertised provider counts are **designated providers**, not the number of competing ordinary orders. [Official LPP description](https://help.kalshi.com/en/articles/15410219-liquidity-provider-program)

Volume rewards have a published **$0.005 per-contract ceiling**, eligible-price and maker/taker restrictions, and program-specific timing. A 9-contract execution therefore cannot earn more than $0.045 under that ceiling; price loss and fees can exceed it. Do not assume it stacks on a particular LIP market without an overlapping eligible volume program. [Volume rules](https://help.kalshi.com/en/articles/13823850-what-is-the-kalshi-volume-incentive-program)

### New sports-component filing: keep separate

The CFTC record lists the September 2 sports-component filing as certified September 16, with a September 15 modification attached. Certification is not proof of a specific Exchange launch notice. [Filing record](https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizationRules/63562)

Its clean text uses a 25% combo-fee fraction, maker-volume shares, a multiplicative score `product(1 + component_share) - 1`, a 0.01 minimum individual score, and monthly bonus credits. For ongoing events, qualifying maker volume is restricted to after the scheduled start. It is not the general LIP snapshot formula. Exact launch, account eligibility and operational reporting remain unverified. No dedicated public API for its component-score/fee-pool reconciliation was found. **Exclude this revenue from our base case.** [Modified filing, clean appendix](https://www.cftc.gov/filings/orgrules/rules09152626159.pdf)

## 3. General LIP rules that affect quoting

**VERIFIED, September 19:** the current help page lists an end date of January 1, 2027, subject to change or termination. Most ordinary U.S. members are eligible; international users and IB/FCM routes are excluded by the help guidance. Tax-verification requirements can also prevent credits. Our account's eligibility has not been checked. [Current help](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program)

The July filing's clean appendix provides the detailed procedure:

1. For each YES/NO bid ladder, walk from highest price downward. The first level reaching **T/5** cumulative contracts sets that side's reference.
2. Continue until reaching **T**. Include **the entire final price level**, not only the quantity needed to reach T. Deeper levels do not qualify.
3. If either side cannot reach T, the snapshot is excluded. The market must also be open.
4. Score qualifying orders by size and tick distance; normalize each side separately. Snapshots occur once per second at randomized instants.
5. Period rewards are reduced for excluded snapshots, thresholded at $1 and rounded down to cents.

[July filing, clean pages 7-9](https://www.cftc.gov/filings/orgrules/rules07152610358.pdf)

### Implementation mathematics

Let `d = discount_factor_bps / 10,000`, `q` be remaining resting quantity, and `k` be valid price-grid ticks worse than the reference, floored at zero:

```text
raw_score(order) = q * d^k                         if qualifying, otherwise 0
side_share(user) = own_raw_score / total_raw_score on that side
snapshot_score  = yes_share + no_share
```

For `N` scheduled snapshots, the published normalization simplifies algebraically to:

```text
raw_period_reward = pool_dollars / (2*N) * sum(snapshot_score over valid snapshots)
paid_reward      = floor_to_cents(raw_period_reward), only if raw_period_reward >= $1
```

This simplification assumes the two valid sides normalize to a combined score of 2. Zero valid snapshots imply zero reward. Apply any explicit account cap and program-specific restrictions separately; cap ordering is not specified in the generic API schema.

**INFERRED consequences of the formula:**

- You do not personally have to supply both sides. A one-sided quote can score if the *market* has sufficient two-sided depth. One side supplies at most half of an otherwise valid snapshot's overall share.
- A 200-contract reference threshold usually means **1,000 / 5 cumulative contracts from everyone**, not a requirement for our order to contain 200 contracts. A 300 target instead gives a 60-contract reference threshold.
- A best bid can be several ticks above the reference. Joining the reference may have the same price multiplier with a less aggressive price; it can still be hit when better orders disappear.
- More quantity increases numerator and denominator and can move the reference/cutoff. Doubling size is not automatically double reward. Recalculate with the proposed order included.
- Joining a level containing 8,000 contracts does not earn `q / target` just because the target is 300. All qualifying quantity at the crossing level counts.
- Canceling stops future snapshots; it does not mathematically erase already recorded contribution. A small accumulated amount can nevertheless remain below the final minimum. This is a formula interpretation, not an account payout verification.

### Distance example with the observed factor 0.50

| Ticks behind reference | Raw size multiplier | Other qualification conditions |
|---:|---:|---|
| 0 or better | 100% | Must qualify and have valid two-sided book |
| 1 | 50% | Can instead become zero if below cutoff |
| 2 | 25% | Same cutoff condition |
| 3 | 12.5% | Same cutoff condition |
| 4 | 6.25% | Same cutoff condition |

These are raw multipliers, **not exact payout ratios**, because denominators can change. Tick distance follows the market's price grid, not a count of nonempty book levels. Variable-band reward tick interpretation remains a venue-confirmation question; do not use the smallest tick globally. [Price representation and grids](https://docs.kalshi.com/getting_started/fixed_point_migration)

### Payout and website reconciliation

Paid totals and provisional estimates are different. Signed-in market popovers can show timestamped estimates; reward/activity history shows credits after processing. The active table can aggregate pools across markets in an event. Blue/gray order indicators are guides, not final accounting. Payment is not immediate and no fixed payment-delay guarantee was found. Use exact market/program IDs. [Official rewards UI explanation](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them)

## 4. Every documented reward API

### Dedicated endpoint: GET /incentive_programs

Production root: `https://external-api.kalshi.com/trade-api/v2`.

Operation ID: `GetIncentivePrograms`. Public GET succeeded without authentication. The published operation has no security requirement. This retrieves **definitions**, not personal earnings. [Official endpoint](https://docs.kalshi.com/api-reference/incentive-programs/get-incentives)

| Query parameter | Contract |
|---|---|
| `status` | Optional: `all`, `active`, `upcoming`, `closed`, `paid_out`; default `all` |
| `type` | Optional: `all`, `liquidity`, `volume`, `margin_maker_volume`, `margin_taker_volume`; default `all` |
| `incentive_description` | Optional exact string match; not a fuzzy search or formal category enum |
| `limit` | Optional integer, 1-10,000; default 100 |
| `cursor` | Optional pagination token from `next_cursor` |

There is no documented ticker, program-ID, start/end-date, account or personal-earnings query parameter. Filter ticker/ID locally after pagination. Do not mistake the response's `next_cursor` for the `cursor` response field used by many other endpoints.

| Response field | Meaning / handling |
|---|---|
| `incentive_programs` | Required array |
| `next_cursor` | Optional next-page string; stop on absent/empty |
| `id` | Required program identifier; preserve across snapshots |
| `market_id`, `market_ticker` | Required exact market identity |
| `incentive_type` | Required one of the four program types above |
| `incentive_description` | Required text; observed empty strings as well as labels |
| `start_date`, `end_date` | Required date-times; retain UTC precision |
| `period_reward` | Required integer **centi-cents**; divide by **10,000** for dollars, not 100 |
| `paid_out` | Required program-level boolean; does not say this account received money |
| `discount_factor_bps` | Optional/nullable integer; divide by 10,000 |
| `target_size_fp` | Optional/nullable decimal quantity string; preserve fractional precision |
| `max_reward_per_account` | Optional/nullable integer centi-cents; absent is not zero |

Published statuses: 200 success, 400 parameter error, 500 server error. Also handle general transport failures and throttling. Full exact schemas are retained in [our API reference](KALSHI_API_REFERENCE.md) and [published OpenAPI](https://docs.kalshi.com/openapi.yaml).

Read-only examples:

```http
GET /trade-api/v2/incentive_programs?status=active&type=liquidity&limit=10000
GET /trade-api/v2/incentive_programs?status=upcoming&type=liquidity&limit=100
GET /trade-api/v2/incentive_programs?status=paid_out&type=liquidity&limit=100
GET /trade-api/v2/incentive_programs?status=active&incentive_description=series_lip&limit=100
```

Observed filter tests:

| Test | Result |
|---|---|
| All five status values | Each returned HTTP 200; two-row samples returned cursors |
| All five type filters | HTTP 200; active volume returned one row; both margin types empty |
| Two pages with limit 2 | Two rows each, no overlapping IDs in this check |
| Exact description filter | Returned descriptions matched `series_lip` |
| Full active enumeration | 5,252 programs, 5,252 unique IDs, empty terminal cursor |

The other statuses were **sampled**, not exhaustively downloaded. No undocumented private website routes were probed. Empty margin results today do not imply those interfaces are obsolete.

### Supporting interfaces the strategy needs

All paths below are documented; their complete field contracts are in the local API reference. `Read checked` means an unauthenticated public GET in this research, not an account capability test.

| Endpoint / interface | Why it matters | Verification / boundary |
|---|---|---|
| `GET /markets`, `/markets/{ticker}` | Trading state, rules, times, grids, shard | Individual market reads checked |
| `GET /markets/{ticker}/orderbook` | Full YES/NO depth for reference, cutoff, score | 40 books checked, `depth=0` |
| `GET /markets/orderbooks` | Batch depth, up to 100 tickers | Two-ticker request checked |
| `GET /markets/trades` | Public executions; not resting reward scores | Read checked |
| `GET /events/{event_ticker}` | Parent series, event risks, fee overrides | Read checked |
| `GET /series/{series_ticker}` | Fee type/multiplier, rules, prohibited participants | Read checked |
| `GET /series/fee_changes`, `/events/fee_changes` | Fee changes and overrides | Read checked; empty sampled histories do not prove universal zero fees |
| `GET /exchange/status` | Market-wide pause/availability | Read checked |
| `GET /exchange/schedule` | Exchange schedule and maintenance planning | Documentation checked, not invoked; read regulatory notices separately |
| `GET /portfolio/orders`, `/portfolio/orders/{order_id}` | Actual own remaining size/status | Auth required; not invoked |
| `GET /portfolio/orders/queue_positions`, `/portfolio/orders/{order_id}/queue_position` | Own execution queue | Auth required; not a reward-score endpoint |
| `GET /portfolio/fills`, `/portfolio/positions` | Inventory and actual execution economics | Auth required; not invoked |
| `GET /portfolio/settlements` | Settled market P&L | Auth required; **not** incentive-credit history |
| `GET /portfolio/balance`, `/portfolio/subaccounts/balances` | Cash/equity; shard/subaccount reconciliation | Auth required; cash change alone cannot identify rewards |
| `GET /account/limits`, `/account/endpoint_costs` | Account token budget and endpoint costs | Auth required; not invoked |
| `GET /historical/cutoff`, historical orders/fills/markets | Complete old execution reconciliation | Cutoff read checked; no private history requested |
| Predictions WS `orderbook_delta`, ticker/trade, own orders/fills/positions | Timely book and own-state updates | Documented; no reward stream found; not connected here |
| `/portfolio/events/orders` create/amend/decrease/cancel and order groups | Eventual execution and containment | Documentation only; **no writes authorized or attempted** |

Sources: [markets](https://docs.kalshi.com/api-reference/market/get-market), [single book](https://docs.kalshi.com/api-reference/market/get-market-orderbook), [API index](https://docs.kalshi.com/llms.txt), [WebSocket specification](https://docs.kalshi.com/asyncapi.yaml).

The orderbook schema advertises authentication, but the 40 single-book requests and batch request worked without keys in this observation. Treat that as observed behavior, not a guarantee that authentication will never be required. Also, live ladders arrived ascending despite narrative descriptions suggesting best-first; the research explicitly sorts them. The schema returns aggregate quantities, **not participant counts or a full per-order queue**.

### Negative findings: what is not in the published API

The audit covered 116 Predictions, 48 margin and 27 clearing-member REST operations, both WS specs, and the cached FIX documentation. Only `GetIncentivePrograms` was a dedicated reward operation. Fee-rounding rebates are ordinary fee accounting, not LIP reward credits.

No documented API was found for: personal pending LIP earnings; a final per-program reward ledger; claiming rewards; a definitive account-eligibility flag; the venue's recorded one-second reward snapshots; qualifying participant identities; a personal score/rank; exact competitor count; or sports-component incentive reconciliation. This is a bounded statement about **public documentation**, not a claim that Kalshi has no internal APIs.

The signed-in Rewards/Activity UI is the documented payment evidence. Do not infer rewards by subtracting two balances without reconciling fills, fees, settlements, funding and transfers.

## 5. Current program universe and practical examples

**MEASURED:** snapshot totals (program pools are collective, not ours):

| Metric | Observation |
|---|---:|
| Active LIP programs / unique markets | 5,251 / 5,251 |
| Active volume programs | 1 |
| Active margin maker/taker programs | 0 / 0 |
| LIP pool min / median / max | $20 / $100 / $500 per whole period |
| Period duration min / median / max | 15 minutes / 126.96 hours / 691.27 hours |
| Pool normalized to 24 hours, median | $15.19 collective pool, not expected personal reward |
| Explicit account caps in active LIP rows | None present |
| Discount factor | 0.50 in all 5,251 |

The maximum normalized 24-hour pool rate was $2,491.26, but this extrapolates a short program. It is **not** a $2,491 daily pool or a guarantee of renewal. The filing limits relate to calendar days encompassed, not simply a prorated 24-hour rate.

The one volume row was `KXRAINDNYC-260919-0`, program `336141f0-a3da-4924-a7ac-1f7a3c2368a3`, with a $500 whole-period pool ending September 20 at 03:59 UTC. This does not establish account eligibility, a $500 personal payment or future continuation.

### Small-order arithmetic on actual sampled books

For each example: fresh hypothetical entrant, 5 contracts on each side at the observed reference; proposed size included in scoring; unchanged competition and prices; continuous qualifying uptime; no fills, fees, losses, early closure or account restrictions. **Not a forecast.** Values below are raw rewards before the minimum and cent rounding.

| Market ticker | Period pool | Hours left | Gross for remaining period: 5/side | Gross remaining: 9/side | 5/side one tick behind |
|---|---:|---:|---:|---:|---:|
| `KXMLBSEASONGAMES-27-1215` | $500 | 23.91 | $1.466 | $2.631 | $0.597 |
| `KXMLBSEASONGAMES-27-600` | $500 | 23.91 | $0.992 | $1.782 | $0.000 |
| `KXTTELITEMATCH-26SEP191920WMABSU-BSU` | $20 | 1.46 | $0.852 | $1.463 | $0.359 |
| `KXTRUMPAPPROVE-26SEP20-E39.5` | $300 | 15.41 | $0.725 | $1.302 | $0.189 |
| `KXAAAGASDSC-26SEP20-4.0650` | $100 | 5.11 | $0.617 | $1.092 | $0.312 |

Do not round $0.992 up to an eligible dollar. These examples would be stale before any live launch. Markets in the same event are correlated and cannot be treated as independent opportunities.

For the first row, reference bids were YES $0.78 and NO $0.21. At 5 per side, the two shares were approximately 0.1102% and 0.4786%; averaging gives 0.2944% of valid snapshot pool flow. The YES qualifying level contained 4,532 contracts: the 1,000 target did not cap competition. Moving one tick lower lost YES qualification entirely.

That pair would reserve approximately $4.95 before any venue netting/fees. **Only the YES side filling can expose $3.90 of principal**, larger than the $1.466 static remaining reward. Both sides are not guaranteed to fill together. Low order collateral is not low aggregate bot risk.

The table-tennis example normalizes to $13.97 per 24 hours at size 5 but has only $0.852 of remaining reward arithmetic. Calling it a '$14/day opportunity' would be misleading.

Sampling limitations: two 20-market selection strata ranked pool/time/target and pool/time, with one ticker-prefix series per stratum. Gas-state series dominate; some series repeat across strata. All 40 sampled grids were single-band cent grids. Excluded books were not filled in with our small orders. This inspection does not measure future depth, actual reward snapshots, fill probability, adverse selection or executable exits.

## 6. Best candidate approach for our constraints

Everything in this section is an **INFERRED recommendation**, not approval or a proven optimum.

### Select markets before choosing prices

1. Require a current general LIP program, sufficient remaining time, known rules and confirmed account eligibility.
2. Require both sides to meet target, with a cushion: a book exactly at target can lose qualification on one cancellation.
3. Calculate the actual score denominator and the complete cutoff level. Do not rank solely on pool dollars, target or best-price queue.
4. Require conservative remaining reward comfortably above $1. A proposal could require at least $2 in static remaining arithmetic, then apply a 50% contribution haircut; this is a screening example, **not** an agreed threshold or statistical confidence interval.
5. Reject near-term binary news/event jumps, markets about to close, stale books, unverified fee exceptions and correlated overexposure. Public news risk is not eliminated by apparently quiet recent trading.
6. Choose whether to quote one side or both based on inventory and marginal net value. Do not quote a bad side merely to look balanced.

### Choose the least aggressive price consistent with acceptable net economics

The initial candidate is the **Reference Price**, recomputed after including our proposed quantity. It is the least aggressive full-price-weight level for the observed book. Do not move above it solely to improve reward weight: the multiplier cannot exceed 1.0. A better price might change fill economics or future qualification, which requires a separate justification.

Compare deeper qualifying prices only if the expected reduction in fill/exit loss outweighs lost *payable* reward. At the observed 0.50 discount factor, a one-tick move can be expensive, particularly if it drops below the cutoff or the final dollar minimum. There is no universal 'always one tick back' answer.

Avoid chasing tiny reference changes blindly. Repricing should react to material score loss, adverse information, inventory, cutoff movement and program changes. Hysteresis may reduce churn, but no fixed refresh interval is validated by this research. Queue position affects executions, not reward numerator at the same price/quantity.

### Net economics, not reward-only economics

```text
net result = paid liquidity rewards + separately verified other incentives
             + trading P&L - actual trading fees - applicable operating costs
```

Pending estimates are not cash. For an open position, report both mark-to-liquidation value and terminal-risk exposure rather than hiding losses until settlement. Preserve the distinction between a realized loss, an unrealized loss, and reserved collateral.

General event taker fees use the published quadratic schedule, and maker fees depend on exceptions. Resting does not mean fee-free if the order later fills in a maker-fee market; cancellations themselves have no trading fee. [Fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)

Actual fees also involve fill-level precision, rounding and accumulated rebates; use returned fee data rather than repeatedly rounding each partial fill to cents. [Fee rounding](https://docs.kalshi.com/getting_started/fee_rounding)

Illustrative execution cost: 5 contracts losing $0.05 each costs $0.25 before fees. Twenty such losses cost $5. A five-contract taker exit at $0.50 has a base fee of $0.0875 at multiplier 1 before balance alignment. These are arithmetic scenarios, not measured loss rates. **We do not yet know daily trading loss or daily net reward.** The historical +$0.51/day size-5 replay is not a reliable live-income forecast; see [current status](../STATUS.md).

### Controls required in a later approved implementation

- Treat $500 as a ceiling, not a deployment target. Count open-order reserves, filled positions and fees; do not spend pending rewards.
- The per-order limit does not cap accumulated inventory. Require per-market, correlated-event, total-inventory and outstanding-order limits, plus a separately approved maximum loss.
- Use post-only for intended resting entries; it prevents immediate taking, **not subsequent fills**. Reconcile partial fills and cancellation races before replacements. [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2)
- On fills, stop automatic replenishment until the inventory/exit policy permits it. Decide whether to hold, passively exit or cross; none is inherently loss-free.
- Stale data, WS sequence gaps, clock drift, heartbeat failure, program edits, pauses and disconnections need fail-closed handling. Venue-side expiry can help during laptop sleep, but expiry does not exit filled inventory.
- Use own-order IDs and correctly scoped cancels. A blanket cancel-all can affect other account trading. Order groups limit filled contracts over a window, **not dollar losses**. [API safeguards](KALSHI_API_REFERENCE.md)
- No wash trades, self-matching, spoofing or orders we are unwilling to honor. Rewards are for real liquidity and do not remove market-abuse rules. [General program oversight](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program)

## 7. Discrepancies and questions we must not paper over

| Issue | Evidence | Conservative handling |
|---|---|---|
| Eligibility text differs | July clean appendix excludes IB/FCM routes; current help additionally excludes affiliates/employees and non-U.S. users. Older project prose says MM agreements always exclude general LIP | Do not reuse the old blanket claim. Confirm account-specific eligibility with Kalshi if relevant |
| Fractional program timestamps | 4,383 active LIP rows had fractional-second boundaries; July clean text says whole-second boundaries | Preserve API timestamps; exact boundary snapshot treatment unknown |
| Reward ticks across changing grid bands | Rules say ticks; API has market price bands | Do not use minimum step everywhere. This sample only calculates single-band grids |
| Per-account cap semantics | API exposes nullable `max_reward_per_account`; no active LIP row had it | If present, obtain program-specific treatment before using an estimate |
| Public book auth and sorting | Schema security and narrative order differ from observed unauthenticated ascending responses | Implement documented auth when needed; sort explicitly; do not rely on incidental behavior |
| New sports program launch | Certified filing plus later attachment; no verified Exchange effective notice obtained | Keep separate and count no forecast income |
| Final personal earnings | No published reward-credit ledger endpoint found | Reconcile the documented Rewards/Activity credits; do not label models 'earned' |

No definitive later amendment replacing the general July scoring procedure was found in the reviewed sources. This is not a guarantee that notices cannot change tomorrow. Recheck program definitions, official help, filings and fee terms before approving a live plan.

## 8. What remains before building, without another paper phase

1. Confirm account reward eligibility and how we will obtain final credit evidence. Keys can support private balance/fill checks when needed, but will not invent a missing reward API.
2. Agree maximum loss and inventory/exit limits. The assistant's earlier $10 suggestion was never accepted.
3. Review a small, fresh candidate list with time-to-threshold, correlated risks, fees and permitted entry prices. Do not place orders based on this dated sample.
4. Specify the operational stop/reconciliation/expiry behavior, then request explicit build and live-execution approval.

No recommendation to collect another long dataset or run paper trading is made. Existing captures are preserved because they still establish historical failure modes and help prevent incorrect assumptions.

## 9. Reproducibility and source map

- [Public API inspector](../scripts/inspect_reward_apis.py): GET-only, no credentials, one shot; saves separate dated evidence directories. Run with `.docs-venv/Scripts/python.exe scripts/inspect_reward_apis.py`. This is a research utility, not bot implementation.
- The recorded run made **102 successful GETs, zero HTTP failures**. Manual preliminary inventory/book reads and later two fee-context reads occurred outside this 102-request manifest; no account reads occurred.
- Offline verification independently recomputed **252 scenarios with Decimal arithmetic**, checked every local report link, and hashed the evidence. See [verification audit](LIQUIDITY_REWARD_AUDIT.json) and [audit utility](../scripts/audit_reward_research.py). All 45 existing unit tests passed. These checks validate arithmetic and artifacts, not future payouts or execution safety.
- [Full API contract reference](KALSHI_API_REFERENCE.md), [coverage audit](API_REFERENCE_AUDIT.json), and [source manifest](API_REFERENCE_MANIFEST.json) cover the earlier 240-page documentation snapshot.
- Rule sources: [general LIP help](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program), [July filing](https://www.cftc.gov/filings/orgrules/rules07152610358.pdf), [UI/payment explanation](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them), [regulatory notices](https://kalshi.com/regulatory/notices).
- Other programs: [volume](https://help.kalshi.com/en/articles/13823850-what-is-the-kalshi-volume-incentive-program), [designated providers](https://help.kalshi.com/en/articles/15410219-liquidity-provider-program), [sports original](https://www.cftc.gov/filings/orgrules/rules09022622944.pdf), [sports modification](https://www.cftc.gov/filings/orgrules/rules09152626159.pdf).

Evidence labels: VERIFIED = checked primary documentation or reproduction; MEASURED = named public observations; INFERRED = recommendation or algebra under stated assumptions; UNKNOWN = unresolved. No current personal reward earnings or profitability are claimed.
