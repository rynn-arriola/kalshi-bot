# Findings — kalshi-bot

Research pinned 2026-08-16. Ported context: `D:\polybot\liquidity-bot` (Polymarket US)
is the reference implementation. Its `SAFETY_INVARIANTS.md` (63 invariants) is the
asset being carried over; its *calibrations* are Polymarket measurements and are NOT
valid here until re-measured.

Primary sources are the CFTC rules filing and the live public API. Help-center
paraphrases proved unreliable (see section 2) and are not authoritative.

---

## 1. The reward program exists, is self-serve, and is formula-identical

Kalshi's **Liquidity Incentive Program** (LIP). Authoritative text: KalshiEX LLC
amendment filed 2026-02-11 with the CFTC, `rules02112639183.pdf`.

Eligibility, verbatim:

> "Eligible Participants are all Kalshi members, except the following: (i) affiliates
> of Kalshi; (ii) members who have executed a Market Maker Agreement with Kalshi;
> (iii) Introducing Brokers, Futures Commission Merchants, and customers thereof when
> transacting via the IB or FCM."

**Kalshi Pro does not affect eligibility.** Pro (`pro.kalshi.com/workspace`) is a
trading terminal with a fee discount, not a Market Maker Agreement. Confirmed it is a
sign-in product page, not an MM designation. The MM Agreement route is the separate
*Designated Liquidity Provider* program (auction-based, requires executing an
agreement) and it **excludes** you from the LIP.

The scoring formula:

```
Score(bid)      = DiscountFactor ^ (ReferencePrice − Price(bid)) × Size(bid)
Normalized(bid) = Score(bid) / Σ Score(b) over qualifying bids on that side
SnapshotScore(user) = Σ normalized yes scores + Σ normalized no scores
TimePeriodScore(user) = Σ user snapshots / Σ all users' snapshots
Payout(user)    = TimePeriodScore × TimePeriodReward     (≥ $1.00 or unpaid)
```

This is `discountFactor ^ ticks * size` — **exactly what `rewards.py` already
implements**. The pure reward core ports with field renames.

Regulatory bounds: Time Period ≤ 31 days; Target Size ∈ (100, 20 000); Discount
Factor ≤ 1.00; Time Period Reward ∈ [$10, $1 000] **per calendar day** encompassed.
Payout below $1.00 is not paid at all.

Snapshots are taken **once per second, at a uniformly random instant within the
second**. Reward is a time integral over resting orders — so liquidity-bot's
invariant 51 (never scan while quoting) carries over unchanged.

---

## 2. Two-sided liquidity is MANDATORY — this is the biggest design change

The stated purpose of the 2026-02-11 amendment:

> "exclude Snapshots where there are no qualifying 'Yes' bids or no qualifying 'No'
> bids. This serves to limit liquidity rewards to two-sided markets."

And in the terms:

> "Snapshots will be excluded if there is not two-sided liquidity (i.e., resting
> orders sufficient to meet the Target Size on each side of the market) at the time
> of the Snapshot."

**Consequences:**

- Liquidity-bot **invariant 4** ("after the first fill, all risk-building orders for
  that market are cancelled") zeroes reward accrual on *both* sides here. It cannot
  port as written. This is the single largest policy rewrite.
- Liquidity-bot **invariant 8** (each side independently eligible) is false on Kalshi.
- A market whose opposite side is short of Target Size pays **nothing**, no matter how
  good your share on your own side. Measured: this is common (section 4).
- At 5 contracts you **cannot rescue a short side yourself** — Target Size is 1000 in
  99.2% of live programs. Both sides must already qualify without you.

### Correction: Reference Price is the best bid

An earlier help-center reading claimed Reference Price is "the first price level at
which cumulative resting size reaches one fifth of the Target Size." **That is wrong
and does not appear in the filing.** The rules text:

> "If the highest yes bid price exists and is less than the highest possible price, it
> is assigned to the Reference Yes Price."

Reference Price = the touch. The walk then descends, accumulating size, until
cumulative ≥ Target Size; those levels form the Qualifying Bids. If bids run out
first, **the whole side is cleared** (no qualifying bids at all).

Note "a yes ask is counted as a bid for no" — both sides are expressed as bids, which
matches the `orderbook_fp` API shape exactly.

---

## 3. The API is public and unauthenticated for discovery

```
GET https://api.elections.kalshi.com/trade-api/v2/incentive_programs
      ?status=active&type=liquidity&limit=200[&cursor=…]
GET https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook?depth=100
```

Both work with **no auth**. `external-api.kalshi.com` returns identical data.

Field mapping to the existing Polymarket adapters:

| liquidity-bot | Kalshi | note |
|---|---|---|
| `discountFactor` | `discount_factor_bps` | bps; 5000 = 0.50 |
| `targetSize` | `target_size_fp` | string decimal |
| pool | `period_reward` | integer, scale inferred — see below |
| `IncentivePeriod` start/end | `start_date` / `end_date` | RFC3339 |
| PAID | `paid_out` | bool; feeds `calibration.py` paid-only discipline |
| slug | `market_ticker` | |

Orderbook response is `{"orderbook_fp": {"yes_dollars": [[px,size],…],
"no_dollars": […]}}`, price ascending, both sides as bids.

**`depth=200` returns HTTP 400. `depth=100` is accepted.** Cap requests at 100.

### UNVERIFIED: the `period_reward` scale

`period_reward` is an integer with no documented unit. Inferred scale is
**1/10 000 dollar** (divide by 10 000), because only that scale puts all observed
values inside the regulatory $10–$1 000/day band:

- `3333333` over ~21 days → $333.33 total → $15.87/day ✓
- `1250000` over 7 days → $125 → $17.86/day ✓
- `800000` over a 1-hour period → $80 for one calendar day ✓

At 1e-6 scale these become $0.16/day, below the $10 regulatory floor — so that scale
is wrong. **Confirm against a real payout before trusting any EV number in section 4.**

---

## 4. Live universe measurement, 2026-08-16

2 328 active liquidity programs. Distribution:

- **Target Size: 1000 contracts in 2 309 of 2 328 (99.2%)**. Also 300 (×17), 2500, 500.
- **Discount Factor: 5000 bps = 0.50 in 2 327 of 2 328**. One at 4000.
- Period rewards (raw): 150000 (×1105), 250000 (×520), 1000000 (×514), 500000 (×125).

Top series by program count: `KXFEDFUNDSYEAR`, `KXH200MS`, `KXNOMGDPGROWTH`,
`KXUSCPIYEAR`, `KXB200MS`, `KXH100MS`, `KXROLEATEVENTCOACHELLA`, `KXRTX5090MS`,
`KXYTVIEWSW`, `KXRAIN`, `KXTRUMPSAY`.

**No sports in the rewarded top series.** The Polymarket bot is sports-pregame only
(invariant 40, moneyline V2). That entire gate has no counterpart here — the rewarded
Kalshi universe is weather, rates/macro, GPU benchmarks, YouTube views, events. See
section 5 for what this breaks.

### DiscountFactor 0.50 collapses the denominator — this is the key economics

Because each tick away halves the score, the effective competition is only the top few
ticks, **not** the full 1000-contract Target Size. Measured shares for a resting order
at the touch:

| market | side | denom | 5 ct | 25 ct | 100 ct |
|---|---|---|---|---|---|
| KXSOFRD-26AUG17-T3.62 | no | 5.1 | **49.5%** | 83.1% | 95.2% |
| KXSOFRD-26AUG17-T3.62 | yes | 13.4 | **27.2%** | 65.1% | 88.2% |
| KXTEMPMIAH-…-T84.99 | yes | 15.5 | 24.4% | 61.7% | 86.6% |
| KXRAIN-26AUG17-DEN | yes | 71.8 | 6.5% | 25.8% | 58.2% |
| KXRAIN-26AUG17-DEN | no | 233.5 | 2.1% | 9.7% | 30.0% |
| KXH100MON-…-2.310 | yes | 261.5 | 1.9% | 8.7% | 27.7% |
| KXEOWEEK-26AUG22-0 | yes | 546.0 | 0.9% | 4.4% | 15.5% |
| KXAAAGASD-…-4.0550 | yes | 4703.8 | 0.1% | 0.5% | 2.1% |

Illustrative payout, KXRAIN-26AUG17-DEN ($100 program, both sides qualify):

```
SnapshotScore = 0.0651 (yes) + 0.0210 (no) = 0.0861
TimePeriodScore = 0.0861 / 2.0 = 4.31%      (max total across all users is 2.0)
Payout ≈ 4.31% × $100 = $4.31
```

**Caveat — these are instantaneous book snapshots, not earnings.** They assume the
book is unchanged, you are never filled, and no competitor reacts. A denominator of
5.1 is an extremely thin book, which is exactly where a fill is most likely and most
adverse. liquidity-bot FINDINGS §6h found the same thing on Polymarket: reward
concentrates in thin books. Same trap, same mitigation needed.

### Stepping one tick inside the touch DOUBLES the share

Measured 2026-08-16 across 8 series, 15 qualifying sides. Resting 5 contracts at the
touch versus one tick inside it:

| market | side | at touch | 1 tick in | gain |
|---|---|---|---|---|
| KXVOTEPRIMARY-…-12 | yes | 2.64% | 5.14% | 1.95× |
| KXSHELTERCPI-…-T430.7 | no | 2.87% | 5.59% | 1.94× |
| KXPOWERKWH-…-T20.4 | no | 0.62% | 1.23% | 1.99× |
| KXCPICOMBO-26AUG-0503 | no | 0.46% | 0.92% | 1.99× |
| KXATPRETIRE-27DJO-Y | yes | 82.93% | 90.67% | 1.09× |

**The gain is `1 / DiscountFactor` per tick**, and DF is 0.50 in 99.96% of live
programs — so one tick is worth exactly 2×.

Mechanism: the Reference Price *is* the best bid (section 2). Becoming the best bid
puts us at zero ticks with multiplier 1.0 *and simultaneously demotes every other
resting order one tick*, halving each of their contributions to the denominator. We
gain nothing and lose nothing on our own numerator; the entire effect is on everyone
else's. Formally, with our size `q` and competing score `Σ`:

```
share_at_touch  = q / (q + Σ)
share_one_in    = q / (q + DF·Σ)
gain            → 1/DF   when q << Σ
```

The KXATPRETIRE outlier confirms the model rather than contradicting it: at 82.93% we
already dominate the denominator, so `q << Σ` fails and the gain collapses toward 1.

**Cost:** one tick. At 5 contracts that is $0.05 of worse entry price, against a
doubling of reward share.

**Constraint:** we cannot step inside on both sides without eventually crossing.
`yes_bid + no_bid` must stay below 1.00, exactly the "never price through the opposite
touch" rule in liquidity-bot's `exit_quote_price` (`reconciler.py`, added 2026-08-16).
A post-only order that would match is rejected outright.

**UNVERIFIED:** this is a static-book calculation. Being the best bid raises fill
probability and invites others to step ahead. Whether the 2× survives contact with a
moving book and reacting competitors is a Phase 2 measurement, not a result.

### Two-sided failure is common

Of 8 sampled programs, **3 had one side entirely empty** — `KXDIESELD` (yes),
`KXYTVIEWSHIGH` (no), `KXTEMPMIAH` (no). Those pay zero regardless of the other
side's share. KXTEMPMIAH shows a 24.4% share on a side that earns nothing.

**The dominant selector filter is therefore: both sides reach Target Size without us.**
Cheap to check — one orderbook call per candidate — and it eliminates a large fraction
of the universe before any economics run.

---

## 5. What ports, what rewrites, what must be re-measured

### Ports close to unchanged
`execution_ledger.py` (durable intent, exact Decimal, ambiguous-create resolution),
`runtime_safety.py` (lease, session risk guard), `reconciler.py` planner *structure*,
`risk.py` framing, `shadow_*` measurement harness, `AsyncIntervalLimiter`, the
fail-closed adapter discipline, and most of the 63 invariants.

### Rewrites (venue surface)
`adapters.py` (Kalshi REST, RSA-PSS SHA-256 over `timestamp + METHOD + path`, path
excludes query params), `streams.py`, `models.py` (ticker/series/event taxonomy, not
slugs), `venue_state.py`, `live_orders.py`.

Kalshi's WebSocket is **read-only — all order management is REST**. This removes the
private-mutation-stream complexity that liquidity-bot invariants 17/18/20 exist to
manage. Simpler, but re-verify what replaces those guarantees.

### Invariants that DO NOT port as written
- **4** (cancel building orders after first fill) — kills both-side accrual. Rewrite.
- **8** (independent side eligibility) — false on Kalshi.
- **40** (sports moneyline V2 gate) — no rewarded sports universe.
- **55/56** (900s passive wait; pre-kickoff flatten) — these are keyed to a sports
  `game_start`. Weather/CPI/rates markets have `close_time` / `expiration_time` with
  different dynamics. The *principle* (never let a position ride to settlement) holds;
  the clock does not.
- **34** (maker rebate = 0) — **sign flips**. Kalshi charges maker fees.

### Must be re-measured, cannot port
`fill_hazard.py` calibration, the 900s wait, the 2-cent spread rule (Kalshi is
1-cent linear_cent tick), `max_inventory_age`, the 6-hour pregame window.

---

## 6. Fees run the wrong direction

Kalshi charges **maker** fees, where Polymarket did not. Taker is
`ceil(0.07 × P × (1−P) × 100)/100` per contract — max 1.75¢ at 50¢, smaller in the
tails. Maker is reported at ~25% of taker (~0.44¢ at 50¢).

**Kalshi Pro reduces fees** — this is the reason to use it, and it feeds directly into
the EV gate. `risk.py` needs a new negative term: every reward must clear the maker fee
before it is profit.

UNVERIFIED: exact Pro fee schedule. `kalshi.com/docs/kalshi-fee-schedule.pdf` returned
HTTP 429; retry and pin the real numbers before sizing anything.

---

## 6b. Program renewal — an earlier expiry scare was wrong

The 2026-02-11 filing sunsets the Program on **2026-09-01**, and an earlier reading of
this file treated that as an imminent shutdown. **That was wrong.** The per-market end
dates cluster before September 1 because these are short-dated events (a weather market
for Aug 17 ends Aug 17), not because the program stops.

Evidence pointing to routine renewal:

- Kalshi **refiled its Volume Incentive Program on 2026-08-04, extending to September
  2027**, in response to CFTC Division of Market Oversight staff asking every DCM to
  review and amend incentive filings by 2026-09-14. The September dates are a review
  deadline, not a cliff.
- Kalshi is already scheduling liquidity programs **past** September 1 — 43 of 2,328,
  running to September 5.
- The Program has run continuously since August 2025 and was already extended once.

Not proven: the liquidity refiling itself was not located, only the volume one. Treat
renewal as likely, not certain. Do not plan around a deadline.

## 6c. Fees — confirmed, and where they actually bite

Kalshi help center, verbatim: *"Maker fees are charged for orders placed that are not
immediately matched and are instead left as resting orders on the orderbook."* Maker
fees are real. Fees are charged **only when a trade executes** — cancelling a resting
order is free.

`kalshi-fee-schedule.pdf` is Cloudflare-blocked (persistent 429 with an HTML body, not
a real rate limit), so the 25%-of-taker maker rate remains **UNVERIFIED**.

**The maker fee is not the problem.** Reward is earned by resting; fees are paid on
fills. At 5 contracts and 50¢, a fill costs ~$0.022 — about 0.5% of a $4.31 program
reward. Noise.

**The taker fee is the problem**, because Kalshi's tick is 1¢ and the taker fee at 50¢
is 1.75¢ — *larger than the entire spread*:

```
crossing the spread   1.00¢
taker fee             1.75¢
                      -----
true cost to cross    2.75¢     ≈ 3× the naive spread estimate
```

The hard-exit path is a taker path, so `cross_exit`, `max_exit_loss` and the stressed
margin all need a fee term. This compounds section 4's thin-book trap: the markets
paying the best share are the ones where crossing out is required and most expensive.

The fee is parabolic (`0.07·P·(1−P)`), maximal at 50¢ and near zero in the tails —
0.74¢ at 12¢ versus 1.75¢ at 50¢. **Tail-priced markets are fee-advantaged**, at the
cost of tail risk. That is a real selector input.

## 6e. Authenticated account facts, measured 2026-08-17

Signed read-only access working via `scripts/kalshi_auth.py`. RSA-PSS/SHA-256 over
`timestamp + METHOD + path`, where the signed path **includes** the `/trade-api/v2`
prefix and **excludes** the query string, and the timestamp is milliseconds as a
string. Salt length is the digest length. Both mistakes fail identically with
`token_authentication_failure`, which is why they are written down here.

Balance: **$22.6439**.

### The taker fee formula is CONFIRMED — and my earlier rounding was wrong

Two real taker fills on this account, `KXITFWMATCH-26AUG16DASNEP-DAS`:

| action | C | P | `0.07·C·P·(1−P)` | ceil 4dp | actual `fee_cost` |
|---|---|---|---|---|---|
| sell/no | 14.91 | 0.53 | 0.2599857 | 0.2600 | **0.260000** |
| buy/yes | 14.91 | 0.32 | 0.2271091 | 0.2272 | **0.227200** |

```
fee = ceil(0.07 × C × P × (1−P) × 10_000) / 10_000
```

**Ceiling is at four decimal places — one hundredth of a cent — not at whole cents.**
The second fill disambiguates: ceil-to-cents gives 0.23 and does not match; ceil-to-4dp
gives 0.2272 and matches exactly. An earlier note in this file said whole cents. It was
wrong, and it mattered in the pessimistic direction: small orders lose far less to
rounding than claimed.

The per-contract headline is unchanged: 1.75¢ at 50¢, and the crossing cost of ~2.75¢
against a 1¢ tick still stands.

**Maker fee remains UNVERIFIED.** Both fills carry `is_taker: true`. The `fee_cost`
field is reported per fill and `is_taker` distinguishes them, so **one resting fill
settles the maker rate definitively** — no reward payout needed for this particular
question.

### Rate limits are ~50× more generous than assumed

`GET /account/limits`, tier `basic`:

```
read   refill 200/s   bucket 600
write  refill 100/s   bucket 100
```

liquidity-bot's entire discovery architecture is shaped by a **4 requests/second**
governor — invariant 51 (never scan while quoting) exists because a full Polymarket
metadata pass took 31 minutes. At 200/s a 40-market book sweep costs well under a
second, so **1-second book resolution is achievable**, matching the rate at which
Kalshi itself samples. The scan-versus-quote tradeoff that shaped much of the reference
architecture largely does not exist here.

### Fractional contract sizes exist

`count_fp: "14.91"` on both fills, and `target_size_fp: "1000.00"`. Sizes are not
integers. Any size model, loss budget, or tick arithmetic that assumes whole contracts
is wrong. Unresolved: whether a resting order may be placed in fractional size or
whether this is an artifact of dollar-denominated entry.

### No incentive-earnings endpoint was found

`/portfolio/incentives`, `/incentive_earnings`, `/portfolio/incentive_earnings`, and
`/incentive_programs/earnings` all return 404. Reward payouts are not obviously exposed
as their own resource, so **the `period_reward` scale probably cannot be settled without
actually earning a payout** — unlike the maker fee, which one resting fill answers.

One counter-signal on scale: `/portfolio/balance` returns `balance: 2264` beside
`balance_dollars: "22.6439"`, so integer money elsewhere in this API is **cents**. If
`period_reward` were also cents, the observed `800000` would be $8,000 for a one-hour
program, far outside the filing's $10–$1,000 per-calendar-day band. Cents and the
regulatory cap cannot both hold, so the field is either scaled differently or the cap
is applied in a way not yet understood. **Do not treat 1e-4 as settled.**

## 6f. There is no short on Kalshi — selling YES is executed as buying NO

Decoded from a completed round trip on this account, `KXITFWMATCH-26AUG16DASNEP-DAS`,
2026-08-16.

```
15:14:31  action=buy   side=yes  yes_price=0.32  ->  yes_total_cost 14.91 x 0.32 = $4.7712
15:18:46  action=sell  side=yes  yes_price=0.53  ->  no_total_cost  14.91 x 0.47 = $7.0077
```

Selling YES at 0.53 did **not** book proceeds of `14.91 x 0.53 = $7.90`. It booked a
**cost** of `14.91 x 0.47 = $7.0077`, and the settlement carries *both*
`yes_count_fp: 14.91` and `no_count_fp: 14.91`. Going short YES is buying NO, and the
venue rewrites the order to say so.

### The same trade is described three ways

| record | fields |
|---|---|
| order | `side: yes`, `action: sell`, `outcome_side: no` |
| fill | `side: no`, `action: sell`, `outcome_side: no` |
| settlement | both `yes_count_fp` and `no_count_fp` populated |

**The order says `side: yes` while the fill says `side: no` for the same trade.**
Deriving direction from `action`/`side` books it backwards. This is the same defect
class as liquidity-bot FINDINGS section 2, where legs priced against the wrong outcome
made the ledger report +$1.34 on a trade that actually lost $0.30, in the direction
that hides losses.

### Kalshi gives us the fix Polymarket withheld

Every record carries **both** `yes_price_dollars` and `no_price_dollars`, always summing
to exactly 1.00. The price frame is therefore never unrecoverable, unlike Polymarket's
bare `lastPx` with no record of the outcome it was quoted against.

**Design rule: never derive direction from `action`/`side`. Reduce every order, fill and
position to a signed YES-equivalent from the explicit price pair, in exactly one
function, with round-trip tests.**

### UNRESOLVED: `revenue: 0` does not reconcile

The settlement reports `market_result: "yes"`, `value: 100`, and `revenue: 0`. Holding
14.91 YES into a YES resolution should pay $14.91. Either `revenue` excludes settled
pairs, or the paired position is netted somewhere not visible in this record.

Do not guess this one. `revenue` is the kind of field a P&L breaker reads, and
liquidity-bot's $40 stop returned **+3.26 for a trade that lost $1.55** because a
closing fill was never booked. Resolve it against a second settlement before any ledger
depends on it.

## 6d. liquidity-bot reference values, corrected 2026-08-16

The reference implementation changed after this file was first written. Current values
(liquidity-bot `3dca27c`), which supersede anything earlier in this document:

- **Invariant 13**: 5 contracts per quote across 20 markets (was 1 × 8).
- **Invariant 25**: **$40** loss stop, **$45** hard stop (was $30/$35).
- **Invariant 57 superseded**: the 8-market private-WebSocket ceiling was *disproved* —
  29 subscriptions were later sustained. Eight was one connection's cap, not the
  account's; connections are independent and each carries its own quota. **This removes
  the main reason to expect a low Kalshi subscription ceiling**, though Kalshi's own
  limits still must be measured.
- **New `selection_horizon_seconds = 7200`** (was six hours). Measured: the 120+ minute
  bucket pays a median projected reward of 0.000022 with only 67% of markets paying
  anything, against 0.000313 and 100% at 15–30 minutes. **Reward concentrates hard near
  the event.** Kalshi's analogue — whether reward concentrates near a program's
  `end_date` or near market close — is a Phase 2 measurement and a likely large win.
- **New `max_early_exit_loss = 4.0`**, split from `max_exit_loss`. The two shared one
  number, wired to the $40 session stop, so the exit half *could never fire*: five
  contracts cannot lose $40. Chosen from 17 observed crossed losses; $4.00 blocks 3 and
  defers $16.96 of $41.96 — 40% of the damage from 18% of events. **This is exactly the
  failure mode to avoid in the Kalshi port**: an entry gate and an exit cap that read
  the same field silently disable one of them.
- **New `exit_quote_price()`**: a reducing quote steps one tick inside the touch, but
  only while the improved price still does not lose money. Measured: exits ending in a
  taker cross were **-$30.22 across 28 markets, ~76% of all real recorded losses**, with
  losers clustering at 911s and 966s of hold — right on the 900s inventory clock. On
  Kalshi, where crossing costs ~3×, this is worth more, not less.

## 7. Open questions

1. **`period_reward` scale** — confirm 1e-4 against an actual payout. Everything in
   section 4 depends on it.
2. **Pro fee schedule** — exact maker/taker rates with the Pro discount.
3. **Does a fill on one side end both sides' accrual in practice?** The rules say the
   snapshot needs two-sided liquidity; they do not say your *own* orders must be on
   both. Re-read: your score sums normalized yes + normalized no, so a one-sided quote
   still scores — provided *someone* holds the other side to Target Size. This changes
   invariant 4's rewrite substantially. **Resolve before designing the fill policy.**
4. **Post-only order support** — not yet confirmed in the Kalshi API. Without it the
   reconciler's `PLACE_POST_ONLY` has no venue primitive.
5. **Rate limits** — separate read/write token buckets; `GET /account/limits` reports
   live refill rates. Tier-dependent, needs an authenticated read.
6. Whether reward density (`period_reward / effective_denominator`) is stable enough
   over a Time Period to rank on, or whether it must be re-measured continuously.

---

## 8. Recommended order of work

1. Port `shadow_run.py` + `shadow_store.py` first. Read-only, zero risk, and it
   answers Q1, Q3, and Q6 with real Kalshi data.
2. Resolve Q4 (post-only) — it is structural for the reconciler.
3. Only then port the economics, and only then the execution path.

This is the same order that got liquidity-bot to a working state. Do not skip the
shadow phase: every number in section 4 is a single instantaneous snapshot.
