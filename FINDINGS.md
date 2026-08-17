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

### The `period_reward` scale — strongly corroborated 2026-08-17, not yet paid

`period_reward` is an integer with no documented unit. Inferred scale is
**1/10 000 dollar** (divide by 10 000), matching the fixed-point convention the
rest of the API already uses — `discount_factor_bps: 5000` is basis points,
which is the same 1e-4, and `target_size_fp` / prices arrive as 4-decimal
strings.

Originally inferred from three examples. Re-tested 2026-08-17 across **2,940
distinct programs** in `data/capture.db`, and the evidence is now much stronger
than a band argument.

**All 19 distinct values, divided by 10 000:**

```
15  20  25  50  80  100  110  120  125  135  140  142.8571
170  200  240  285  333.3333  500  1000
```

Three things make this decisive:

1. **The two non-round values are exactly `1000/7` and `1000/3`.** Repeating
   decimals of that form are what you get by splitting a round $1 000 budget
   into 7 or 3 equal periods. Under any other scale they are meaningless
   numbers; under this one they are arithmetic.
2. **The maximum is exactly `1000.0`** — the filing's cap, hit precisely.
3. **Zero of 31 610 market-days exceed $1 000/day**, spreading each pool
   pro-rata across the calendar days it covers. Median **$1.10/day**, p90
   $14.29, max $285.00.

The cents hypothesis is dead: it puts the median at $357/market/day and breaks
the cap constantly.

**What this is not.** It is inference from the venue's own arithmetic, not a
confirmed payout — `paid_out` is `True` on only 28 of 2 940 programs and carries
no amount. It is now strong enough to size the business and to write economics
against, which it was not before. **A real payout still settles it**, and the
`revenue: 0` discrepancy in 6f is a standing reminder of what an unverified
money field costs.

**The number that matters: the median program pays a $1.10/day pool per
market**, and we earn a *share* of that, not the pool. Section 4's share
measurements are what turn this into revenue.

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

## 6g. The pair trade is a second revenue source, independent of the reward

Measured over 22,030 usable book snapshots, 44 markets, 2026-08-17.

A YES and a NO contract on the same market always settle to exactly $1.00
between them. So a maker resting a bid on both sides and getting **both** filled
has bought a guaranteed dollar for `yes_bid + no_bid`:

```
pair edge = 1.00 - (yes_bid + no_bid) - fees
```

This is the classic market-making trade, and it matters more than it first looks:
it is a return that **does not depend on the unresolved `period_reward` scale**.

| measure | value |
|---|---|
| gross pair edge, median | **0.0100** per contract — exactly one tick |
| gross, p10 / p90 | 0.0100 / 0.0500 |
| net after fees, 5 contracts, median | **$0.0379** |
| net, p10 / p90 | $0.0078 / $0.2106 |
| net > 0 | **98.2%** of snapshots |
| one-sided (unusable) | 3,419 of 25,449 |
| crossed (edge < 0) | **0** |

Fees are charged at each leg's own touch price. An earlier version of this
number priced both legs at 0.50 -- the peak of the `0.07·P·(1−P)` curve -- and
reported net $0.0062, making the pair trade look like it barely cleared its own
fees. These markets are mostly tail-priced, so that overstated cost by about 6x.
**Price the fee at the actual price, never at a representative one.**

### This creates a direct policy conflict with the one-tick rule

Section "Stepping one tick inside the touch DOUBLES the share" says to quote one
tick inside. The pair edge says the opposite:

- **Median pair edge is exactly one tick.** Stepping inside on one side consumes
  the entire typical edge; on both sides it consumes twice the entire edge.
- **Only 29.3% of snapshots leave more than 2 cents**, so 71% of the time
  stepping inside both sides would cross the book and is not even available.

So the two levers are in tension, and **which one wins is decided by the
`period_reward` scale** — the number that is still unconfirmed. If reward
dominates, quote inside and pay the spread. If the pair edge dominates, sit at
the touch and take 1x reward.

This raises the priority of resolving the scale: it is no longer just an
accounting question, it selects the quoting policy.

### What this does not measure

Whether both sides actually fill. The edge is only captured on a completed pair;
one side filling alone is directional risk, which is the failure mode
liquidity-bot spent its whole architecture on. Fill rates come from trades, and
that analysis has not been done yet.

**Answered in 6h, and the answer changes the conclusion above.** The pair
completes **0.7% of the time** — 7 times in 1,064 windows, revised up from a
reported zero once the sample grew. Read 6h before acting on any number in this
section: the edge is real when it lands and is far too rare to be a revenue
line.

## 6h. The pair trade does not complete — and that resolves the 6g conflict

Measured 2026-08-17 with `scripts/markout.py` over 140 non-overlapping
one-hour windows across 44 markets, quoting 5 contracts per side. This is the
fill-rate half that 6g left open.

### The result

A quote resting on both sides completed **zero pairs**, under either policy:

| policy | pair completed | one side only | neither |
|---|---|---|---|
| join both touches | **0** (0.0%) | 14 (10.0%) | 126 (90.0%) |
| one tick inside both | **0** (0.0%) | 16 (11.4%) | 124 (88.6%) |

Not one completed pair in 140 market-hours. 6g's `$0.0379` median is correct
arithmetic on the observed spread, but it prices an event that did not occur
once in this sample.

> **CORRECTED 2026-08-17 — "zero" was a sample size, not a property.** With
> 1,064 windows instead of 140, the pair completes **7 times (0.7%)**, median
> $+0.0500 on 5 contracts, positive on all seven. It is still far too rare to
> be a revenue line and none of 6h's conclusions change, but *never completes*
> was wrong and is now *completes 0.7% of the time*.
>
> An intermediate reading of this — that zero was "a property of the politics
> slate, not of Kalshi" — was also wrong, and wrong in the more interesting
> way. The original 40-market slate produces pairs too (2 of the 7) once it
> has enough windows. The variable was never the slate. **A rate of 0.7%
> cannot be distinguished from zero in 140 observations, and calling it zero
> was reading a sampling limit as a fact about the venue.**

### Why — it is the tape, not the queue

The obvious explanation is queue position: the median depth resting at the
touch is 655 contracts on the bid and 473 on the offer, so 5 contracts joining
behind that need an enormous amount of one-way flow. That is real, but it is not
the binding constraint, because stepping one tick inside creates an empty price
level where we are first in line — and pair completion is still zero.

The actual ceiling is that both directions have to trade at all:

| in a one-hour window | share |
|---|---|
| no trades whatsoever | **64.3%** |
| one direction only | 27.1% |
| both directions traded | **8.6%** |

So pair completion is capped at 8.6% before price or queue is considered, and
the realised figure is 0% because those trades must also occur *at our prices*.
Over five-minute windows only 7.8% contain any trade at all, mean 0.20 trades
per window.

These are quiet books. That is not incidental — it is the same property that
makes them pay, since reward share is our score over the competing score, so low
competition is the whole edge. **The books that pay best are the books that
trade least.**

### This resolves the policy conflict in 6g

6g framed stepping one tick inside as a trade-off: it doubles reward share but
consumes the entire median pair edge, and the winner was said to be decided by
the `period_reward` scale.

**On this evidence there is no pair edge to protect.** The spread is not being
captured, so giving up a tick of it costs nothing realised. Stepping inside buys
the measured 1.987x reward share and, additionally, moves us from behind ~655
contracts to the front of an empty level.

The conflict was real as posed; the premise turned out not to hold. Resolving
`period_reward` is still required to size the reward, but it is **no longer
needed to choose the quoting policy** — which reverts blocker 1 from a policy
question to an accounting one.

The 3-tick room requirement bites as 6g predicted: only **21.4%** of snapshots
leave enough spread to step inside both sides, and the rest join the touch. So
this is a policy, not a filter.

### ~~UNRESOLVED~~ RESOLVED in 6i: the sign of one-sided markout

**Superseded 2026-08-17 by section 6i.** The sign is established: one-sided
fills are adverse, by a sign test over a pooled sample, and the mean is bounded
by a bootstrap interval that excludes zero. The instruction below not to put an
adverse-selection term into the economics **no longer applies** — 6i supplies
the number and section 9 now uses it. The reasoning is kept because the
*method* is the finding: waiting for n was the wrong instrument, and the right
one did not need a larger sample.

One-sided fills are what actually happens, 10–11% of hours. Their markout is
consistently negative but **the sample cannot establish the sign**:

| horizon | n | median | mean | trimmed mean | positive |
|---|---|---|---|---|---|
| 60s | 14 | −$0.0063 | −$0.1293 | −$0.0488 | 36% |
| 300s | 14 | −$0.0200 | −$0.1654 | −$0.0513 | 29% |
| 900s | 12 | −$0.0050 | −$0.1681 | −$0.0167 | 42% |

The mean is dominated by a single −$1.75 observation; dropping the best and
worst sample moves it to roughly −$0.02 to −$0.05, and the median sits near
zero throughout. That spread between median and mean is the signature of
adverse selection — most fills harmless, a few badly wrong — but with n=14 it
is equally consistent with noise. **Recorded as unresolved.** Do not put a
`spread_capture` or an adverse-selection term into any economics on this.
*(Both sentences superseded by 6i — see the note at the head of this
subsection.)*

liquidity-bot hardcodes both `spread_capture` and `maker_rebate` to zero for
exactly this reason and never got evidence to turn them on
(`docs/REFERENCE_CRITIQUE.md` 3b). On this measurement zero is the right value
for us too, and now it is a measurement rather than a placeholder.

### Limits of this measurement

- **44 markets, all politics/economics event markets**, selected by
  `reward/target` ranking. Not a general sample of Kalshi, and sports markets
  are absent entirely.
- **~14 hours of book coverage** across two capture runs with a 5.5-hour gap.
  Trades are backfilled 48h but a fill needs book context on both ends.
- **Static-book assumption**, and it bites hardest on the policy that looks
  best: nothing here models other makers stepping inside us after we step
  inside them.
- Fills require the **whole** 5 contracts; partials are not counted, on the
  grounds that a partial carries the same directional risk with less spread to
  show for it.
- Gross of fees throughout. The maker fee rate is still unmeasured (6e).

## 6i. One-sided fills ARE adverse — the sign is established, the mean is bounded

Measured 2026-08-17 with `scripts/pooled_markout.py` over both captures pooled:
1,064 non-overlapping one-hour windows, 292 markets, 1,219 market-hours. This
closes the blocker 6h left open and supplies the drag term section 9 was
missing.

### Waiting for n was the wrong instrument

6h said the sign needed a bigger sample and the plan was to widen the universe
from 40 markets to 150. **That made the sample grow more slowly, not faster.**
One-sided fills arrive at 0.040/market-hour on the original slate and
0.048/market-hour on the wide one at 5 contracts — but the wide slate's
*windows* are far quieter, 3.7% one-sided against 7.3%. Ranking by
`reward/target` selects for thin books by construction, so every market added
is quieter than the ones already held.

**This is a structural property, not bad luck.** The books that pay best are
the books that trade least (6h), so the sample that measures fill cost is
rate-limited by the same thing that makes the strategy work. Accumulating n is
not a viable path to this answer.

What settles it is choosing statistics that survive a small, outlier-heavy
sample:

- A **sign test** asks only whether fills are negative more often than a coin
  says. The −$1.75 observation that destroyed the mean in 6h counts exactly as
  much as a −$0.001 one.
- A **bootstrap CI on the mean**, because P&L is paid in dollars and not in
  signs. If the interval excludes zero, the drag is bounded and can enter the
  economics.

### The result, at 5 contracts per side

| horizon | n | median | mean | negative | sign test p | 95% CI on mean |
|---|---|---|---|---|---|---|
| 60s | 51 | −$0.0250 | −$0.1235 | 69% | **0.0038** | [−$0.2249, −$0.0403] |
| 300s | 51 | −$0.0250 | −$0.1271 | 71% | **0.0014** | [−$0.2374, −$0.0369] |
| 900s | 43 | −$0.0250 | −$0.0755 | 72% | **0.0054** | [−$0.1816, −$0.0028] |

The median is pinned at exactly −$0.0250 at every horizon — half a tick on 5
contracts. The CI excludes zero at all three. **One-sided fills are adverse and
the drag is roughly −$0.13 per fill at 5 contracts**, with the honest range
being −$0.04 to −$0.24.

### The independence caveat, and it matters

An earlier reading of this called the two captures "two independent slates that
agree exactly". **They are not independent.** `capture.db` and
`capture_wide.db` share **69 markets — 88% of the narrow slate and 32% of the
wide one** — and they overlap in time from 18:50Z onward, so some fills are
plausibly the same event sampled twice.

Run separately, the two do not carry the same weight:

| sample | n (300s) | median | mean | sign p | 95% CI on mean |
|---|---|---|---|---|---|
| `capture.db` alone | 27 | −$0.0250 | −$0.1424 | 0.0094 | [−$0.3017, −$0.0242] |
| `capture_wide.db` alone | 24 | −$0.0250 | −$0.1099 | **0.0931** | [−$0.2766, **+$0.0094**] |
| pooled | 51 | −$0.0250 | −$0.1271 | 0.0014 | [−$0.2374, −$0.0369] |

**The wide slate alone does not reach significance and its CI includes zero.**
The pooled p-values are therefore optimistic — the effective sample is smaller
than 51 by an unknown amount.

What survives the caveat is the part that does not depend on pooling: **both
slates give a median of exactly −$0.0250 and a negative mean of the same order,
derived from different market mixes.** The direction is consistent; the
strength of evidence is somewhere between the single-slate and pooled readings.
Recorded as *established but not airtight* — one more independent capture on a
disjoint market set would settle it properly.

### Drag scales with size; reward does not

Both fill rate and per-fill markout were re-measured at each size rather than
scaled from the 5-contract number:

| size | fills/market-hour | mean markout (300s) | 95% CI on mean |
|---|---|---|---|
| 5 | 0.0435 | −$0.1271 | [−$0.2374, −$0.0369] |
| 25 | 0.0385 | −$0.7536 | [−$1.3617, −$0.2594] |
| 100 | 0.0328 | −$3.4208 | [−$6.3403, −$1.0514] |

Per-fill markout grows very close to linearly in size, while section 9's reward
**saturates**. That asymmetry is the whole shape of the business.

### Net, and where it turns

`drag/day = 24h × fills/market-hour × mean markout × 10 quoted markets`, over
the 10 markets surviving `sizing.py`'s guards:

| size | reward/day | best (CI high) | central (mean) | worst (CI low) |
|---|---|---|---|---|
| 5 | $4.68 | $4.30 | **$3.35** | $2.20 |
| 25 | $23.89 | $21.49 | **$16.92** | $11.30 |
| 100 | $37.43 | $29.15 | **$10.50** | **−$12.48** |

**At 25 contracts the operation is positive across the entire interval** —
$11.30 to $21.49/day on $243 of collateral. **At 100 it straddles zero**, which
confirms the structural point from section 9 by measurement rather than by
argument: past the peak, size is a negative lever, because reward saturates
while fill losses do not.

### What these numbers still do not include

1. **Fees.** Gross throughout. The maker rate is still unmeasured (6e).
2. **The both-sides reward interruption.** Section 2's two-sided rule means
   pulling our quotes after a fill zeroes the snapshot on *both* sides, not
   just the filled one. That cost is in none of the above and is now the
   largest unmeasured term in the economics. See open question 3.
3. **Partial fills.** `markout.py` requires the whole order to fill, which is
   why the modelled fill rate *falls* with size (0.0435 → 0.0328). In reality a
   100-contract quote fills partially far more often than a 5-contract one
   fills completely, so **drag at large size is understated — worst exactly
   where the table already looks worst.**
4. **Static book**, and non-independent samples as above.

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

## 9. What it would actually pay — first end-to-end sizing, 2026-08-17

`scripts/sizing.py`. The first estimate where every term is measured rather than
assumed: pool from the corroborated 1e-4 scale (section 3), share replayed from
captured books with our order inserted, the two-sided rule applied per snapshot,
and reward as the *only* revenue line because 6h showed the pair trade never
completes.

### The payout chain, and the two things that are easy to get wrong

```
SnapshotScore   = normalized_yes + normalized_no
TimePeriodScore = sum of our snapshots / sum of ALL users' snapshots
Payout          = TimePeriodScore x period_reward,  unpaid below $1.00
```

1. Normalized shares on a side sum to 1.00 across all participants, so **every
   counting snapshot contributes exactly 2.0 to the denominator** — one per
   side. Our fraction of the pool is therefore the **mean of our two side
   shares**, and quoting one side only halves it.
2. A snapshot excluded for one-sidedness pays nobody, so it leaves the
   numerator *and* the denominator. **The 85% two-sided rate does not dilute
   our share** — it only spreads the pool over fewer snapshots. An earlier
   intuition that it scaled revenue by 0.85 was wrong.

### The result, and it saturates

Ten markets survive the guards below. Quoting both sides at the touch:

| size | collateral | $/day | per $/day | median share | clears $1 |
|---|---|---|---|---|---|
| 1 | $9.72 | **$0.18** | 1.8% | 0.13% | **1 of 10** |
| 5 | $48.59 | $4.68 | 9.6% | 0.65% | 7 of 10 |
| 25 | $242.93 | $23.89 | **9.8%** | 3.15% | 10 of 10 |
| 100 | $684.70 | $37.43 | 5.5% | 5.14% | 7 of 7 |
| 500 | $1,489.00 | $48.43 | 3.3% | 20.35% | 3 of 3 |

**Return per dollar peaks around 5–25 contracts and decays after.** Our score
and the denominator both rise with size, so share is sublinear, while the pool
is fixed and capped at $1,000/day per market. Above 100 contracts most markets
fail the crowding guard entirely — at 500 only three survive, because we would
*be* the book.

**This is capacity-limited, not rate-limited.** The percentages look
extraordinary and the absolute numbers are small: the whole measurable
opportunity here is roughly $24/day. That is consistent with the program's
purpose — these are $150–$500 pools on small markets, too small to attract
anyone for whom $24/day matters.

### These are GROSS. Trading losses are the same order of magnitude.

`sizing.py` counts reward only. It contains no trading P&L term at all, and
that omission is not a rounding error.

Combining the measured one-sided fill rate and markout from 6h with the reward
above — `drag/day = 24 x P(one-sided fill per hour) x E[markout] x markets`:

| size | reward/day | drag (median) | drag (trimmed) | drag (mean) | net |
|---|---|---|---|---|---|
| 5 | $4.68 | −$0.64 | −$1.77 | −$3.88 | **$4.04 → $0.80** |
| 25 | $23.89 | −$2.88 | −$8.41 | −$18.94 | **$21.01 → $4.94** |
| 100 | $37.43 | −$5.71 | −$8.76 | −$38.84 | **$31.71 → −$1.41** |

**Which statistic you pick decides whether this is a business.** At 25
contracts it is either a $21/day operation or a $5/day one; at 100 contracts
the mean case is outright negative. 6h established that the sign of one-sided
markout **cannot be determined** from n=14–19 with one outlier dominating the
mean — so this range cannot currently be narrowed, and the honest reading is
that net revenue is unknown within a factor of four.

> **SUPERSEDED 2026-08-17 by 6i.** The range *was* narrowed, by changing the
> statistic rather than by waiting for n. Using the bootstrap interval on the
> mean instead of picking between median/trimmed/mean, the table becomes:
>
> | size | reward/day | best | central | worst |
> |---|---|---|---|---|
> | 5 | $4.68 | $4.30 | **$3.35** | $2.20 |
> | 25 | $23.89 | $21.49 | **$16.92** | $11.30 |
> | 100 | $37.43 | $29.15 | **$10.50** | **−$12.48** |
>
> **At 25 contracts the operation is positive across the whole interval.** The
> factor-of-four uncertainty is gone at that size; it survives at 100, where
> the interval straddles zero. The two missing effects listed below are still
> missing, and item 2 is now the largest unmeasured term in the economics.

**Two effects are missing, and both make it worse:**

1. **Partial fills are not counted.** `markout.py` requires the *whole* order
   to fill, so the modelled fill rate *falls* with size (10.7% at 5, 6.8% at
   100). That is an artifact of the predicate, not a property of the market: in
   reality a 100-contract quote fills partially far more often than a
   5-contract one fills completely. Drag at large size is understated,
   and understated worst exactly where the table already looks worst.
2. **A fill interrupts reward accrual on BOTH sides.** Section 2: the two-sided
   rule means pulling our building orders after a fill zeroes the snapshot, not
   just the filled side. So a fill costs markout *and* the reward stream for as
   long as flattening takes. Neither number above includes it.

**Consequence for the order of work.** The binding constraint is no longer the
pool, the share, or the scale — all three are now measured. It is the **cost of
being filled**, which is unmeasured and large enough to erase the revenue.
Getting enough fills to establish that sign is the critical path.

> **Updated 2026-08-17.** 6i measured the markout half of the cost of being
> filled, and it does not erase the revenue at 25 contracts. The binding
> constraint moved again, to the half 6i could not measure: **a fill zeroes
> reward accrual on both sides while we flatten** (item 2 above). That is now
> the critical path, and it is answered by open question 3 — whether our own
> orders must be on both sides, or merely *someone's* — which is replayable
> against books already captured and needs no new data.

### OPERATIONAL: a one-contract evidence run would confirm nothing

At one contract only **1 of 10 markets clears the $1.00 minimum**, and a payout
below it is not paid at all — not deferred, forfeited. So the Phase 3
one-contract run as currently planned would very likely produce **$0.00 of
reward**, which cannot confirm the `period_reward` scale, cannot produce a
payout row, and cannot distinguish "the scale is wrong" from "we were under the
threshold".

**The evidence run needs enough size to clear $1.00 over the program period, or
it is not evidence.** On these pools that means roughly 5 contracts in a market
whose period is short enough to pay out inside the run. Size the run from the
program, not from a habit of starting at one.

### Guards, and why each exists

Three exclusions, all of which an earlier version of this script lacked — it
reported **$2,175/day and 9,779%/day** before they were added:

- **crowded** (2 markets): our size over 25% of the qualifying score. There the
  static-book assumption fails and we are measuring ourselves. Same guard and
  threshold as `analyze_capture.py`.
- **shorter than a day** (8 markets): a 1-hour index program with a $285 pool
  annualizes to $7,105/day, which is arithmetic, not revenue. The market does
  not exist for a day.
- **under 10% period coverage** (32 markets): the largest single correction. A
  share measured over twenty minutes and projected across a 1.8-day period
  assumes no competitor ever arrives. `KXBILZERIANCONCEDE` showed a 23% share
  from 46 snapshots and alone contributed $36/day.

### Limits

- **10 of 52 markets survive**, and their coverage is only 10–25% — share is
  still extrapolated 4–10x across each period.
- Assumes we rest **continuously** for the whole period. Any downtime cuts the
  share proportionally, since reward is a time integral.
- Static book: nothing models competitors responding to our presence, and at
  larger sizes we would certainly move it.
- Politics/economics markets only, ~14 hours of books, no sports (6h).
- **Reward only — gross.** See "These are GROSS" above: the trading drag is the
  same order of magnitude and cannot currently be bounded. Fees are additional
  again on top, and the maker rate is still unmeasured (6e).

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
