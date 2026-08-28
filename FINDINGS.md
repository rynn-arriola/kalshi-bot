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

### Tested against 11 698 programs the venue says it PAID, 2026-08-18

The argument above runs over *active* programs. Once `record_books.py` began
polling terminal-state programs too (it had `status=active` hardcoded, see
`BUGFIXES.md`), the paid population jumped from **28 to 11 698** — and those
are programs Kalshi asserts it actually paid out on, which is a much sharper
test than an active-program band argument.

Every paid program must sit inside the filing's reward bound. Measured:

| scale | max $/calendar-day | paid programs breaching the $1 000 cap |
|---|---|---|
| **1e-4** | $345.00 | **0 of 11 698** |
| cents | $34 500 | **10 235 of 11 698** |
| whole dollars | $3 450 000 | all 11 698 |

**The cents hypothesis is refuted by the venue's own payout data**, not merely
made implausible. Under 1e-4 the median paid program is $20.00/calendar-day,
p10 $6.67, p90 $100.00, across 37 distinct `period_reward` values.

**One anomaly, recorded rather than explained away.** Under 1e-4, **1 218 of
11 698 paid programs fall BELOW the filing's $10/calendar-day floor** (minimum
$2.78). These are long multi-day programs with modest pools — e.g. $25 spread
over 9 calendar days. The most likely reading is that the $10–$1 000 bound
applies to the **Time Period Reward total**, not per calendar day, in which
case every paid program is comfortably inside it and the maximum total under
1e-4 is $100. That reading also happens to be what the filing's phrase
"per calendar day encompassed" was interpreted *away from* earlier in this
section. **Either reading refutes cents**, so the scale conclusion is
unaffected — but the floor discrepancy means our reading of the bound itself is
not settled, and section 9's cap arithmetic leans on it.

**What this is still not.** It remains inference from the venue's own
arithmetic and its own `paid_out` flag. **No payout amount is exposed
anywhere** — a paid program carries exactly the same eleven fields as an unpaid
one, with no earnings figure. So this cannot be reconciled against a number we
were actually paid.

**What this is not.** It is inference from the venue's own arithmetic, not a
confirmed payout — no program row carries an amount. It is now strong enough to size the business and to write economics
against, which it was not before. **A real payout still settles it**, and the
`revenue: 0` discrepancy in 6f is a standing reminder of what an unverified
money field costs.

**UNRECONCILED:** a recount on 2026-08-18 over 3 255 programs gave a median of
**$3.12/calendar-day**, not $1.10, and the paid-program population above gives
$20.00. The three differ by program set and by how days are counted (elapsed vs
distinct calendar dates). Nothing downstream uses the median — `sizing.py` reads
each program's own pool — but two measurements of one quantity disagreeing 3x
is recorded, not averaged.

**The number that matters: the median program pays a roughly $1-$3/day pool per
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
>
> **SUPERSEDED AGAIN by section 10.** Adding a reward line that assumes
> continuous resting to a drag line that assumes fills double-counts our
> presence. Simulated together, net falls ~40% to **$10-$26/day** on $300 at 12
> markets. Both tables above are upper bounds; use section 10.

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

## 10. Reward and fills in one simulation — the estimate falls ~40%

`scripts/net_sizing.py`, 2026-08-17. Sections 9 and 6i computed reward and drag
under **contradictory assumptions and then added them**: `sizing.py` never reads
the trade tape at all and assumes we rest continuously for the whole period,
while 6i's drag assumes we are filled and flattening. Both cannot be true of the
same minute.

This runs one clock per market. A fill takes our quotes down, and because the
filing excludes snapshots without two-sided liquidity (section 2), the reward
integral stops on **both** sides for as long as we are flat.

### The result at 25 contracts on $300, 12 markets

| flatten after fill | uptime | fills/day | reward/day | drag/day | **net/day** |
|---|---|---|---|---|---|
| 0s (never pull) | 100% | 45.1 | $38.98 | −$13.02 | **$25.96** |
| 300s | 98.0% | 36.9 | $37.53 | −$18.48 | **$19.05** |
| 900s | 95.2% | 30.0 | $35.22 | −$23.51 | **$11.71** |
| 3600s | 87.9% | 22.7 | $29.60 | −$11.16 | **$18.45** |

**Net is $10–$26/day, against the $31.76 that adding sections 9 and 6i
produced.** The integrated number is roughly 40% lower, and the honest range now
spans a factor of 2.6 driven by `--flatten-seconds`, which is unmeasured.

The non-monotonicity at 3600s is real but not a signal: pulling for an hour
avoids more fills than it forfeits reward, and the surviving fills are a
different sample. It is sample composition, not an optimum. Do not read
"flatten longer" as a policy from this table.

### Two model corrections, both of which make the answer worse

**1. Queue position persists, and that quadruples the fill rate.** `markout.py`
treats every snapshot as an independent experiment and puts us at the back of
the queue each time. A real quoter holds its place while its price is still the
one it wants, and volume trading through eats the queue ahead. Modelling that
gives **37 fills/day across 12 markets against the ~11/day** implied by 6i's
0.0385 fills/market-hour.

Fill cost is therefore a much larger line than 6i suggested, and 6i's fill rate
should be read as a **lower bound** produced by a deliberately pessimistic queue
assumption, not as a measurement of how often we get hit.

**2. Partial fills barely matter here.** Under `--fill-model partial` the fill
rate rises (45.1 vs 40-ish whole-order at 0s flatten) but net moves by under a
dollar. The concern recorded in 9 and 6i was correct in direction and small in
magnitude once the queue is modelled properly.

### The share statistic moved the answer more than anything else measured

`sizing.py` reduces per-snapshot share to a period fraction with the **median**.
Reward is a time integral, so the **mean** is the formally correct statistic —
and switching to it raised reward from $37.44 to $53.98, a **44% swing from a
one-line choice**, larger than the entire drag uncertainty in 6i.

Neither statistic is simply right. Measured across 77 markets:

- The typical market is **not** concentrated: its best 10% of snapshots carry a
  median of **16%** of its total reward score (uniform would be 10%), and the
  median mean/median ratio is **1.04x**. For most markets the choice is
  irrelevant.
- But the markets that **rank highest by mean are disproportionately the skewed
  ones** — `KXBILZERIANCONCEDE-26AUG18-SEP01` runs 42% in its top decile with a
  5.2x mean/median gap, `KXFISHBACKCONCEDE-26SEP01-AUG19` a 3.0x gap.

**Ranking by the mean selects markets whose mean is inflated by a minority of
snapshots** — the thin-touch books where section 4 already warns the
static-book counterfactual is least trustworthy. This is the same failure mode
as `sizing.py`'s first version reporting $2,175/day: a statistic choosing its
own outliers.

**Fix: a concentration guard.** Drop any market whose best 10% of snapshots
carry more than 30% of its reward score. With it, mean and median agree to
within $3/day ($38.98 vs $35.98) — the guard removes exactly the markets where
the statistic choice mattered, which is what a correct guard looks like.

### What this does and does not change

- **The strategy is unchanged.** Still positive, still 12 markets at 25
  contracts on $300, still capacity-limited.
- **The magnitude is 40% lower** and the dominant uncertainty is no longer the
  markout sign (6i settled that) but `--flatten-seconds`: the post-fill policy.
  That is a design choice, not a market property, so it is ours to pick — and
  picking it needs the exit-cost model that does not exist yet (NEXT item 4).
- **Still gross of fees**, still a static book, still shares extrapolated from
  10–33% period coverage, still politics/economics markets only.

## 11. The ranking metric is wrong, and it is the largest lever found so far

Measured 2026-08-18 over 74 markets in `data/capture.db`.

`record_books.py` ranks candidates by `period_reward / target_size`, and
`docs/PLAN.md` line 212 calls it *"exactly the right Kalshi metric"*. Both
inherit it from liquidity-bot's `rank_candidates`. **It was ported, not derived,
and on Kalshi it is worse than useless.**

The justification is stated at `record_books.py:341`: *"Target size is the
denominator we compete against, so reward/target is the natural density."*
**That premise is false**, and section 4 already contained the reason without
anyone connecting it: DiscountFactor 0.50 halves each tick's contribution, so
the effective competition is the top few ticks, not the full Target Size.

| quantity | spread across our sample |
|---|---|
| `target_size` | 3x (300, 500, 1000 — and 1000 in 99.2% of the live universe) |
| **measured denominator** | **629x** (105.2 to 66,144.5, median 726.8) |

Ranking by a quantity that barely varies, as a proxy for one that varies 629x,
cannot work.

### What each ranking actually earns

| ranking | Spearman vs measured $/day | $/day from its top 12 |
|---|---|---|
| `reward / target_size` (current) | **−0.150** | **$24.39** |
| pool alone | +0.114 | $74.03 |
| `reward / measured denominator` | +0.619 | **$158.61** |
| perfect foresight | — | $225.51 |

**The current metric is negatively correlated with revenue** — it is worse than
ranking by pool alone, and worse than picking at random. Switching to density is
worth roughly **6.5x** on the top 12, which is far larger than any size, breadth
or policy lever measured to date.

**Honest limit on that +0.619.** It is partly circular: our share is
approximately `q / (q + denominator)`, so revenue is already about
`pool / denominator` by construction, and the correlation largely confirms the
formula matches itself. **The non-circular finding is the 629x spread** — that
is a measurement, and it is what disqualifies `reward/target`. Treat the $158.61
as an upper bound too, since it ranks and scores on the same books.

### The denominator is stable enough to rank on — OPEN QUESTION 6 ANSWERED

Ranking uses the *past* denominator to earn on the *future* one, so the metric
is only usable if the denominator persists. Splitting each market's snapshots
into halves, over 71 markets with at least 200 qualifying snapshots each:

| measure | value |
|---|---|
| Spearman, first half vs second half | **+0.818** |
| per-market ratio second/first, median | 1.19x |
| within 2x of itself | 52 of 71 (73%) |
| top 12 that stay top 12 | 8 of 12 |

Section 7 question 6 asked *"whether reward density is stable enough over a Time
Period to rank on, or whether it must be re-measured continuously."*
**Answer: stable enough to rank on, but re-measure it** — a quarter of the top
12 rotates out within hours, and the worst market drifted 76.9x.

**Limit:** both halves come from one ~20h capture, so this establishes stability
over roughly ten hours, **not across a 7-14 day program period**, which is what
the question literally asked. A longer capture is needed to close it fully.

### How this was found, and the process point

The claim was inherited from a working implementation, restated in the plan as
settled, and repeated in the capture script's own docstring — three places, none
of which tested it. It survived because on Polymarket it is genuinely right:
there `target_size` ranges 5,000-15,000 and really does measure required
liquidity. On Kalshi it is a near-constant.

**A ported calibration is a hypothesis, not a fact** — the same rule the top of
this file already states about liquidity-bot's numbers. It was applied to
`fill_hazard`, the 900s clock and the 2-cent spread rule, and not to this.

## 12. You cannot rest out of these books — the exit is a taker path

`scripts/exit_cost.py`, 2026-08-18, 39 simulated fills at 25 contracts.

Every prior number charged a fill its **markout** — where the mid went
afterwards — which is a proxy for adverse selection, not a realised cost.
`net_sizing.py` takes quotes down and then assumes we are flat at **zero exit
cost**. `docs/REFERENCE_CRITIQUE.md` 4e says that omission is the whole story on
the only live instance of this strategy: crossed exits −$1.21 median against
passive −$0.31, five times as many crossed, turning a +$17.24 day into −$7.33.

| passive deadline | exits | passive | crossed | passive $ | crossed $ | blended $ |
|---|---|---|---|---|---|---|
| 300s | 39 | **0%** | 100% | — | −$0.2851 | −$0.2851 |
| 900s | 39 | 3% | 97% | +$0.2500 | −$0.2801 | −$0.2750 |
| 1800s | 39 | 3% | 97% | +$0.2500 | −$0.2801 | −$0.2750 |
| 3600s | 39 | **8%** | **92%** | +$0.2500 | −$0.2801 | −$0.2632 |

### This resolves the sharpest open question in the critique

`docs/REFERENCE_CRITIQUE.md` 4e item 4 posed it directly: our books barely trade
so we fill rarely and should bleed rarely — but thin quiet books are also the
ones you cannot exit passively, and *"rare fills that are each expensive to exit
is not obviously better than frequent fills that are cheap to exit."*

**Answer: the exit is a taker path, structurally.** Giving a reducing order a
full hour still leaves 92% of exits crossing. The same quietness that keeps our
fill rate low keeps the counter-flow that would let us rest out from ever
arriving. **The reference's 73% taker share is not a policy failure we can
avoid by being more patient — on these books it is closer to 100%.**

So the inventory clock is not a real lever. Extending the passive deadline from
300s to 3600s converts 8% of exits and improves the blended cost by 2.2 cents
per exit, while holding the position twelve times longer. **Do not port a
generous inventory clock; there is nothing for it to buy.**

### The cost itself is modest, and smaller than the markout implied

Crossing costs **−$0.28 median per exit** at 25 contracts. Against
`net_sizing.py`'s ~37 fills/day across 12 markets that is roughly **−$10/day**,
which lands inside the −$13 to −$24/day drag range section 10 derived from
markout by a completely independent path. Two different methods agreeing to
within a factor of two is the strongest consistency check the economics have.

It is far cheaper than the reference's −$1.21 median. The likely reason is
FINDINGS 6c: the taker fee is parabolic and these markets are tail-priced, so
the fee is near its minimum, and 'thin' is 0 — the books absorbed 25 contracts
without walking.

### Limits, and one of them biases the answer

- **n=39.** The fill detector here is stricter than `net_sizing.py`'s (it wants
  one trade to clear depth plus our size, rather than accumulating volume), so
  it undercounts fills.
- **The cross is priced against the book AT FILL TIME**, not at the moment the
  deadline expires. A real cross after 900s of waiting meets a book that has
  moved — and moved against us, since that is what adverse selection means.
  **Crossed cost is therefore understated**, and understated most at the long
  deadlines that already look best.
- Passive exits show +$0.25 because `exit_quote_price` only improves the price
  while it still does not lose money against entry, so a passive fill is
  profitable by construction. That is the reference's rule, not a discovery.
- 25 contracts only; the walk cost grows with size and 'thin' would stop being
  zero.

## 13. Kalshi fees against Polymarket, priced on the reference's real fills

2026-08-26. Both fee schedules are verified against live fills on their own
venue, so this is arithmetic, not estimation.

```
Polymarket   taker  = 0.06   x qty x p x (1-p)   charged, rounds UP to cents
             maker  = 0.0125 x qty x p x (1-p)   CREDITED (rebate), rounds DOWN
Kalshi       taker  = ceil(0.07 x qty x p x (1-p) x 10_000) / 10_000   charged
             maker  ~ 25% of taker, CHARGED       UNVERIFIED (6c)
```

Applying the Kalshi schedule to `liquidity-bot`'s **1,847 real fills** (772
taker, 1,075 maker, 12 days to 2026-08-25, median fill price 0.510):

| | taker | maker | net | per day |
|---|---|---|---|---|
| Polymarket, actually charged | +$48.36 | **−$17.13** (rebate) | **+$31.23** | +$2.60 |
| Kalshi schedule, same flow | +$57.01 | **+$23.62** (charged) | **+$80.63** | +$6.72 |

**Kalshi costs 2.58x on identical flow.** The taker line alone is only **1.18x**
(0.07 versus 0.06) — *the entire gap is the maker side changing sign.*

Robust to the unverified maker rate. Even if Kalshi maker fees were **free**,
the same flow costs 1.83x, because Polymarket's rebate is a revenue line we lose
rather than a cost we pay:

| Kalshi maker assumption | net | vs Polymarket |
|---|---|---|
| free | $57.01 | 1.83x |
| 25% of taker (reported) | $80.63 | 2.58x |
| 50% of taker | $104.19 | 3.34x |
| maker = taker | $151.32 | 4.85x |

There is no maker rate at which Kalshi is cheaper on this flow.

**One place Kalshi is cheaper: rounding.** Kalshi ceilings at 4 decimals (6e),
Polymarket at whole cents and asymmetrically — taker up, rebate down. That is
what makes Polymarket per-contract economics ~37% worse at size 1. Kalshi has no
such size floor on fees, so small-size experiments are not fee-penalised here.

### The density-ranked pool sits where the fee is most expensive

Measured over the tracked markets of each capture (best bid/ask from
`orderbook_fp`):

| capture | ranking | median mid | median spread | p(1−p) | taker fee/contract |
|---|---|---|---|---|---|
| `capture.db` | reward/target | 0.360 | **1¢** | 0.1744 | $0.0122 |
| `capture_wide.db` | reward/target | 0.150 | 3¢ | 0.1131 | $0.0079 |
| `capture_long.db` | **density** | **0.495** | **6¢** | 0.2158 | **$0.0151** |

Section 12 explained its cheap −$0.28 exit partly by "these markets are
tail-priced, so the fee is near its minimum." **That is a property of the badly
ranked pool, not of the venue.** Ranking by density — the 6.5x revenue lever of
section 11 — lands on markets priced at the fee maximum (0.495, where p(1−p) is
0.216 of a possible 0.25) with spreads six times wider, and trade flow **2.0x
heavier** (1.49 versus 0.73 trades per market-hour, mean).

Back-of-envelope, the cross therefore costs roughly half-spread plus fee:
**3.0¢ + 1.5¢ = 4.5¢/contract** against the old pool's 0.5¢ + 1.2¢ = 1.7¢, i.e.
about **2.6x per exit**, on about **2x as many fills**. So section 11's 6.5x
revenue gain is bought against a drag that scales roughly 5x. Nominally still a
large win — $158.61/day of reward against a drag near $50/day rather than $10 —
but **the multiple is closer to 3x than 6.5x**, and section 12's known bias
(the cross is priced at fill time, not at deadline) cuts the same direction.

**This is an estimate, and it does not need to stay one.** `exit_cost.py` and
`net_sizing.py` both take `--database` and `capture_long.db` is on disk.

### The reference's own fee line has gone the wrong way

`docs/REFERENCE_CRITIQUE.md` 4e read the ledger at 203 fills. It now holds
1,847. Fees paid per day, net of rebate: **+$0.43 on 08-15, +$6.24 on 08-25**.
Taker fees alone ran $9.02 on 08-25 against $2.78 of maker rebate. The venue
that was supposed to pay us to make markets is now billing $6/day, and on
Kalshi's schedule the same flow would bill $12–$15.

---

## 14. The reward systems are the same rule; the venue is Polymarket US

2026-08-26. Confirmed the reference trades **Polymarket US**, the CFTC-regulated
entity — `api.polymarket.us`, `gateway.polymarket.us`, rules read at
`docs.polymarket.us/incentives/liquidity`. This matters: `polymarket.com` runs a
different scheme that is **quadratic in spread**, and liquidity-bot's FINDINGS
notes explicitly that it "came from the `.com` scheme and does not apply here."
Both venues in every comparison in this file are CFTC DCMs running the
discount-factor scheme, so the comparisons are like-for-like.

**Identical on both venues:** `Score = DiscountFactor ^ (ticks from best) × size`;
linear in size with no per-account cap; walk from the touch outward until
`targetSize`, beyond which orders score zero however close to the touch; payout
purely proportional to share of total score; each side normalized independently
per snapshot; rewards under $1.00 not paid; **spread does not enter the formula.**
This is why `rewards.py` ports with field renames.

**Four differences that decide the design:**

1. **The two-sided gate.** Kalshi voids the *entire snapshot* if either side
   lacks `targetSize` (section 2). Polymarket US normalizes each side
   independently, so one qualifying side still pays. This is why invariant 4
   cannot port.
2. **The $1.00 minimum inverts.** Polymarket US's threshold is an **aggregate
   settlement threshold that accumulates across markets** — their $0.007 per
   market-period eventually pays. Kalshi's filing reads as per Time Period, which
   is why section 9 measured one contract paying **$0.00 on 9 of 10 markets**:
   forfeited, not banked. **UNVERIFIED whether Kalshi aggregates across
   programs** — and this is exactly the mistake liquidity-bot made in the
   opposite direction ("applying it per side per market was wrong, and was
   removed").
3. **Kalshi is projectable everywhere.** Polymarket US keys early/day_of/live to
   event start and only `day_of` has a reliable clock; `live` carries 8x the pool
   and their pregame design forbids it. Every Kalshi program carries explicit
   `start_date`/`end_date`.
4. **Different parameter regimes.** Kalshi DF 0.50 (99.96%), target 1000
   (99.2%), median pool $1.10/day/market. Polymarket US DF 0.30–0.50, target
   5,000–15,000, pools $30–$200/period. Kalshi's target barely varies while the
   **measured denominator varies 629x** (section 11) — and Kalshi books are thin
   enough to own, where Polymarket US has "7,500–15,000 contracts sitting at
   these touches against our 10."

### Reward rate per contract-hour is WORSE on Kalshi, not better

The reference's realised earnings, size 10, one clean day: **$0.230 per resting
order-hour** = ~$0.023 per contract-hour. Our best-case Kalshi replay (section
15) runs 12 markets × 2 sides × 24h at 25 contracts for $87/day = **$0.0060 per
contract-hour** — roughly **a quarter of Polymarket US's rate**, and that is our
upper bound against their realised figure.

**Kalshi's advantage is breadth and thin denominators, not rate.** More markets
whose denominator we can dominate, not more dollars per contract resting.

---

## 15. First profitability estimate on a well-selected pool — and why to halve it twice

2026-08-26, `capture_long.db` (250 density-ranked markets, 3.76h, 46,973 books).
This is the first economics run on markets chosen by the ranking section 11
established, rather than the anti-correlated one.

`net_sizing.py --size 25 --fill-model partial`, policy touch, gross of fees:

| flatten | markets | uptime | fills/day | reward$ | collat$ |
|---|---|---|---|---|---|
| 0s | 12 | 100.0% | 19.3 | 91.73 | 300 |
| 900s | 12 | 98.3% | 19.3 | 87.01 | 300 |
| 3600s | 12 | 93.7% | 21.0 | 102.48 | 300 |

`exit_cost.py --size 25` on the same pool: **59 exits, 92–97% must cross,
median −$0.4313** including the taker fee at VWAP — against **−$0.28** on the
old pool, confirming section 13's prediction that density ranking buys more
expensive exits.

Charging the realised exit rather than the markout proxy (they are two
accountings of the same fill and must not be added):

```
reward                    +$87.01/day
exit cost   19.3 x -0.43   -$8.32/day
entry maker fee (UNVERIFIED 25% rate)  -$1.82/day
                          -----------
net                       ~+$77/day on $300 collateral  =  ~26%/day
```

**26%/day is not a forecast. It is a measurement of how much the model assumes.**

### The correction that matters: uptime

The simulation rests on 24 quoted sides at **98% uptime**. The only live instance
of this strategy anywhere achieved **135–187 order-hours/day against ~960
possible — 14–19%**. Reward pays for resting, and nothing in our capture tests
whether we can actually hold 24 sides continuously; `record_books.py` itself did
not survive four hours.

Applying the reference's realised uptime to our own reward line:

```
$87/day x 0.25  ~  $22/day net on $300  =  ~7%/day
```

**That lands inside section 10's $10–$26/day**, derived on the old pool by a
different route. Two independent paths agreeing is the strongest thing this
estimate has going for it — and it is the number to plan against, not the $77.

### Both instruments disagree with themselves on this pool — do not trust the detail

1. **`--policy inside` reports 0.0 fills/day in `net_sizing.py`** at flatten
   0/300/900, while `exit_cost.py` finds **156 fills** on the same data and the
   same policy — 2.6x the touch policy's 59, which is the expected direction. A
   quote one tick inside the touch cannot fill *less* than one at it. One of the
   two fill detectors is wrong under `inside`, and `inside` is the policy section
   4 recommends.
2. **Markout is POSITIVE on this pool** (+$26.53/day, mean), contradicting
   section 6i's adverse result (p=0.0014) measured on `capture_wide.db`. Either
   density-ranked markets have genuinely two-way flow, or the statistic is
   outlier-driven. Unresolved. The estimate above ignores markout entirely and
   charges the realised exit instead, which is the conservative choice.

### Everything above still sits on an unconfirmed scale

`period_reward` is inferred at 1e-4 (section 3, corroborated across 2,940
programs but never confirmed by a payout). If that scale is wrong, every dollar
figure in this file moves by the same factor. It remains the cheapest single
thing a real evidence run would settle.

---

## 16. The reference's losses are PRICE, ours are FEE — and that is a warning, not a comfort

2026-08-26. Checking section 15's drag against the only live instance of this
strategy, and repricing its flow on Kalshi's schedule.

### On Polymarket US, the fee is 5% of a crossed exit

772 real taker fills from the reference ledger, median 5 contracts at p=0.510:

| | median fee per taker fill |
|---|---|
| Polymarket US, actually paid | **$0.0600** |
| same fills on Kalshi's schedule | **$0.0699** |

Against their published median crossed exit of **−$1.21**, the fee is **5%** of
the loss — **6%** if repriced on Kalshi. Kalshi's 2.58x fee multiple (section 13)
therefore moves their damage by about **one percent**. Their loss is not fees.
It is price: the market moved against the position before they got out.

### On our simulated Kalshi exits, the fee is ~90% of the cost

`exit_cost.py` on `capture_long.db`, 900s deadline, crossed path:

| size | n | crossed $ | per contract |
|---|---|---|---|
| 5 | 78 | −$0.0810 | **−$0.0162** |
| 25 | 59 | −$0.4348 | −$0.0174 |
| 50 | 45 | −$0.9221 | −$0.0184 |
| 100 | 33 | −$1.8895 | **−$0.0189** |

**Per-contract cost is nearly constant across a 20x size range** (+17% from 5 to
100). A walk-the-ladder cost grows with size; a fee does not. The Kalshi taker
fee at this pool's median `p(1−p)` of 0.2158 is **$0.0151/contract** — which
alone explains **93%** of the size-5 cost. The book absorbs 100 contracts with
almost no walk (`thin=0` at every size).

So the two venues' exit costs are made of different things:

```
Polymarket US crossed exit   -$0.242/contract    5% fee,  95% price
Kalshi simulated exit        -$0.0174/contract  ~90% fee, ~10% price
```

### Their exit is 14x more expensive per contract, and that is the real finding

−$0.242 against −$0.0174. **This is not evidence that Kalshi is cheaper. It is
evidence that our model does not contain the term that costs them the money.**

Section 12 already named the mechanism as a known bias: **the cross is priced
against the book AT FILL TIME, not when the deadline expires.** A real cross
after 900s of waiting meets a book that has moved, and moved adversely — that
is what adverse selection means. Our simulation therefore measures the fee
almost exactly and the adverse move almost not at all, and the reference's data
says the adverse move is 95% of the damage.

**CORRECTED 2026-08-26.** An earlier version of this section built the bound on
**−$0.242/contract**, taken from the published *median crossed exit* (−$1.21 at
median qty 5). That is the median of the **worst subset** — crossed exits only —
used as if it were the average over all flow. It overstated the drag by 4x.

### The reference's realised economics, by quote-size era

Derived from 1,847 fills with `accounting.py`'s own closed-pair logic (long and
short legs pair and settle at exactly 1.00; fees tracked separately), on a copy
of the production ledger. Markets are assigned to the era of their first fill.

| era | days | fills | markets closed | price P&L | fees | net trading | **per contract** |
|---|---|---|---|---|---|---|---|
| size 5, 08-14..08-20 | 7 | 742 | 238 | −$49.16 | −$7.76 | −$56.92 (−$8.13/day) | **−$0.0417** |
| **size 10, 08-21..08-25** | 5 | 1,105 | 313 | −$181.68 | −$23.47 | **−$205.15 (−$41.03/day)** | **−$0.0586** |

**Doubling quote size made per-contract economics 40% worse**, not neutral —
−$0.0417 to −$0.0586. Their own reasoning was that reward and losses both scale
with size so the ratio holds; on the loss side it did not hold. Section 4e's
point 2 predicted this asymmetry for Kalshi and it turns out to be true on
Polymarket US as well.

**The corrected bound.** Their realised −$0.0586/contract against our modelled
−$0.0174/contract is a gap of **3.4x**, not 14x:

```
19.3 fills/day x 25 contracts x -$0.0586  =  -$28.3/day   against reward +$87/day
                                          =>  net +$59/day
at the reference's realised uptime (x0.25) =>  net +$15/day
```

**So the stress case is positive, not negative.** Even if Kalshi flow behaved
exactly like Polymarket US's at its current size, section 15's estimate survives
— it falls from ~$22/day to ~$15/day. The earlier "−$117/day, net −$30/day"
claim was an artifact of the wrong statistic and is withdrawn.

**Repricing their flow on Kalshi's fee schedule**, for completeness: their
size-10 fees of −$4.69/day become **−$11.81/day** (section 13), so the same
strategy on Kalshi's schedule loses −$48.15/day rather than −$41.03/day — **17%
worse**, entirely on the fee line.

### What this does to the estimate

Section 15's $22/day survives only if Kalshi's quiet books really do avoid the
adverse move. The reference planned for trading losses at 5% of reward and
measured over 100%. **Our drag is currently 10% of reward.** That is the same
shape of assumption at the same point in the project, and it is the assumption
that broke there.

**This is measurable without new data.** Repricing the cross at deadline rather
than at fill time is a change to `exit_cost.py` against books already captured.
Until that is run, treat the exit cost as a floor.

---

## 17. The reference is PROFITABLE at size 10 — the pessimistic prior is withdrawn

2026-08-26, operator-supplied venue figures for Polymarket US at `quote_size`
10, `max_markets` 20 ($200 worst-case exposure). These come from the venue, and
they supersede every reward figure derived in this file from the repo copy —
the production ledger available here carries only 13 `execution_reward_earnings`
rows, and `docs/REFERENCE_CRITIQUE.md` 4e read the trading side at 203 fills.

| date | trading | reward | net |
|---|---|---|---|
| 2026-08-20 | −$17.99 | $22.21 | +$4.22 |
| 2026-08-21 | −$30.52 | $32.79 | +$2.27 |
| 2026-08-22 | −$24.19 | $25.64 | +$1.45 |
| 2026-08-23 | −$42.88 | $85.09 | **+$42.21** |
| 2026-08-24 | −$43.42 | $174.74 | **+$131.32** |
| 2026-08-25 | −$27.95 | $172.90 | **+$144.95** |
| 2026-08-26* | −$57.10 | pending | — |

Six complete days: trading −$31.16/day, reward **+$85.56/day**, net **+$54.40/day**.
Last three days: net **+$106.16/day**.

### Reward scaled 8x while trading losses stayed flat

This is the finding, and it contradicts the reasoning both projects have been
using ("reward scores `discount^ticks x size` and losses scale with size too, so
the ratio is unchanged" — 4e point 2):

```
                    08-20..08-22 mean     08-23..08-26 mean     ratio
reward                    $26.88               $144.24          5.4x
trading                  -$24.23               -$42.84          1.8x
drag as % of reward   81%, 93%, 94%  ->  50%, 25%, 16%
```

**CORRECTED: the loss line is not flat.** An earlier version of this section
said trading stayed "flat, inside its own daily noise". It grew **1.8x** while
reward grew 5.4x. The ratio improved enormously and the conclusion stands, but
losses track the reward line rather than being independent of it, and 2026-08-26
posted **-$57.10**, the worst trading day recorded, against a unified daily loss
limit of $80.

Neither `quote_size` (10 since 08-20) nor `max_markets` (20) changed across this
window. **The scaling did not come from size or breadth.** The commits landing
over exactly these days are uptime and slot-utilisation work — `fix live
resting-hours telemetry`, `Persist daily score hours across restarts`, `Make
incremental market top-up transactional`, `Fix recovery visibility and slot
release stalls`. **Hypothesis, from commit titles rather than measurement: the
8x is recovered resting time.** The operator can confirm or refute this directly.

If that is right it is the most transferable result either project has produced,
because reward is a time integral over resting orders on **both** venues, and
resting time is an engineering variable, not a market property.

### What this does to our Kalshi numbers

1. **Section 15's uptime haircut (x0.25) was calibrated on their BROKEN uptime.**
   It came from 135-187 order-hours/day against ~960 possible. If the fix
   recovered that, the haircut is too harsh and $22/day is understated.
2. **The reward-per-fill advantage shrinks.** Their $172.90/day over ~150 maker
   fills is **$1.15/fill** against our modelled $4.51 — **3.9x**, not the 19x
   claimed earlier today off the stale $29.54 figure.
3. **Their drag is now 16-25% of reward.** Ours is modelled at 10% (own exit
   cost) or 33% (their per-contract rate applied). **We are in the same regime,
   not a better one.**
4. **Every argument in this file that leans on "the only live instance is
   loss-making" is withdrawn.** That includes 4e's instruction to take the
   pessimistic end when our own range cannot be resolved. The live instance is
   making money, and the prior should be neutral.

### The strategic question this opens

A working, profitable liquidity-reward market maker exists **today** on
Polymarket US, earning ~$106/day net over the last three days on 20 markets and
$200 of worst-case exposure. Kalshi remains unbuilt, has never placed an order,
and its reward scale is still inferred.

**"Is Kalshi better than scaling what already works?" is now a live decision, and
nothing in this file answers it.** Kalshi's case was breadth (~10x the
addressable universe) and a lower qualification bar. Its case was never a better
reward rate — section 14 measures the rate as *worse* per contract-hour. If the
reference's constraint was resting time rather than market count, breadth may
not be the binding lever at all.

---

## 18. Size is the wrong lever on Kalshi — measured, not argued

2026-08-26. `net_sizing.py --fill-model partial`, flatten 900s, on
`capture_long.db` (density-ranked pool). Contracts resting = markets x size x 2
sides.

| size | markets | contracts | reward/day | **$/contract** | %/day on collateral |
|---|---|---|---|---|---|
| 3 | 6 | 36 | $28.96 | **$0.804** | 185% |
| 5 | 7 | 70 | $50.77 | $0.725 | 164% |
| 10 | 11 | 220 | $88.37 | $0.402 | 91% |
| 15 | 11 | 330 | $55.00 | $0.167 | 43% |
| 20 | 14 | 560 | $78.19 | $0.140 | 36% |
| 25 | 12 | 600 | $87.01 | $0.145 | 38% |
| 40 | 7 | 560 | $58.65 | $0.105 | 36% |

**Reward per contract falls 8x from size 3 to size 40, monotonically.** That is
the reliable statistic here and it is the saturation of `q / (q + Σ)` showing up
in dollars: the density ranking selects small denominators, so our own size
enters its own denominator early.

**Do not read the reward column as a size-response curve.** It is not monotonic
(size 15 earns less than size 10) because **the funded market set changes with
size** — collateral guards fund different markets at each size, so each row is a
different portfolio. Only `$/contract` compares like with like.

### What this means

- **Quantity is not irrelevant.** Total reward does rise with size up to ~10
  ($28.96 -> $88.37). Below that the `$1.00` minimum payout is a real floor —
  section 9 measured one contract paying **$0.00 on 9 of 10 markets**.
- **Past ~10 contracts, additional size buys almost nothing** on this pool while
  consuming collateral linearly. Return on capital falls from 91%/day at size 10
  to 36-38% at size 20-25.
- **The lever is breadth, not depth.** Capital spent on depth in one market is
  capital not spent on a second market, and share saturates while market count
  does not.
- **This is the opposite of the reference's situation.** On Polymarket US their
  10 contracts sit against 7,500-15,000, so they never saturate and their
  measured 5->10 doubling returned a clean 1.89x per resting hour (section 17).
  Same formula, different position in the denominator (section 14).

**Limits.** Static book — our size entering its own denominator is modelled, a
competitor *reacting* to us is not, and reacting is exactly what a competitor
does when we take 80% of a side. Small sizes also fund fewer markets, so the
top rows are not simply "better"; they are a different and narrower portfolio.
The `%/day` figures are absurd on their face and inherit every caveat in
section 15, above all the unconfirmed `period_reward` scale.

---

## 19. Audit correction: profitability is promising, but the Kalshi replay is not decision-grade

2026-08-26. Reproduced the reference P&L against its latest production ledger
and the live Polymarket US earnings endpoint, then checked the Kalshi replay
against the current first-party rule descriptions.

### The six-day Polymarket result reproduces, under partial trading accounting

For 2026-08-20 through 2026-08-25, `liquidity-bot/scripts/daily_pnl.py`
reproduces every row in section 17. The arithmetic is exact: trading
**−$31.16/day**, paid reward **+$85.56/day**, reported net **+$54.40/day**;
the final three days are **+$106.16/day**.

The qualification matters: `daily_pnl.py` prices balanced-leg markets only. At
the verification run it excluded 38 unbalanced markets and stated that it
cannot see positions that settled rather than closing. Section 17's number is
therefore a **verified report result, not audited full-account daily P&L**.

Reward rose 7.78x from $22.21 to $172.90, but losses were not literally flat.
The first three complete days averaged −$24.23/day and the last three
−$38.08/day, a 57% increase. They grew far more slowly than reward. The listed
August 25 uptime fixes cannot by themselves explain reward that had already
jumped on August 23–24. `max_markets=20` is a capacity ceiling, not proof that
twenty markets were occupied and resting. The uptime explanation remains a
**HYPOTHESIS**.

### First-party Kalshi sources conflict with the implemented replay

The February 2026 CFTC filing used by `analyze_capture.py` assigns the highest
bid as Reference Price. Kalshi's current Help Center instead describes the
Reference Price as the first level where cumulative size reaches one fifth of
Target Size. The Help Center also says the payable reward is multiplied by the
fraction of non-excluded snapshots.

The current code uses the highest bid and computes `share * pool` without that
non-excluded-snapshot multiplier. Until a controlling source is identified, or
both interpretations are implemented and reported as bounds, sections 14–18
are **INFERRED under a disputed rule model**. "Formula-identical" is too strong;
the venues share a scoring family but not a verified identical implementation.

### The denominator example has one arithmetic correction

For competing score `Σ=4,703.8`, the exact reward-share multiple from size 5
to 100 is **19.6x**, not 21x. Under `q/(q+Σ)`, a 20x increase in `q` cannot
produce more than 20x reward. `Σ` is competing **discounted score**, not raw
contracts, unless every competing contract has multiplier 1.

### Section 18 reproduces the script but does not identify a size optimum

All seven rows reproduce from `net_sizing.py`. They are not a controlled size
sweep: the capital and crowding guards fund a different portfolio at each
size. Consequently neither total reward nor `$ / contract` is a like-for-like
size response. A fixed market set, selected on an earlier window and evaluated
on a later one, is required.

The `%/day on collateral` column is also not reward divided by collateral.
`net_sizing.py` computes `(reward + simulated markout) / collateral`; markout is
positive on this capture despite contradicting the adverse result on the wider
capture. At size 10, reward/collateral is 80.3%, not the displayed 91.1%; at
size 25 it is 29.0%, not 37.8%. Keep reward return and simulated net return in
separate columns.

**Decision consequence:** none of these corrections proves Kalshi is
unprofitable. The nominal headroom still justifies measurement. They do mean
the current tables cannot authorize capital or a full build. The active
experiment and operator boundary are now recorded in `EXPERIMENT.md` and
`DECISIONS.md`.

---

## 20. Current-rule and current-strategy correction

2026-08-26. This section supersedes the reward-rule assumptions behind
sections 4, 9, 11, 14, 15, and 18. Those sections remain historical evidence
of why the instruments changed; their reward dollars and one-tick conclusions
must not drive the current decision.

### VERIFIED — the July filing governs the August capture

Kalshi's July 15 certified filing, effective July 30, supersedes the February
best-bid rule. It sets Reference Price at the first level where cumulative size
reaches one fifth of Target Size, gives full weight to better prices, multiplies
payout by the non-excluded snapshot fraction, rounds down to cents, and retains
the per-program $1 minimum. The current Help Center describes the same rule.

The implementation defaults to `july-2026-one-fifth`; the February mode is
explicitly `SUPERSEDED` and exists only to reproduce old output. Independent
hand fixtures execute in `tests/test_reward_rules.py`.

### MEASURED — stepping inside no longer increases reward share here

Dataset `data/capture_long.db`, August 17–18 capture, size 10, 58,453 usable
snapshots, 56,246 countable (96.2%), 112,492 side comparisons:

| rule mode | inside/touch median | p10 | p90 |
|---|---:|---:|---:|
| July current | **1.000x** | 1.000x | 1.000x |
| February superseded | 1.943x | 1.557x | 1.986x |

Under the current reference, a price better than Reference Price already gets
full weight. Moving one more tick toward the market does not improve score on
these observations. It can still change queue position and fill risk; that is a
different measurement.

Reward-only `sizing.py`, current July rule, current Polymarket entry-price
policy, size 10, $300 cap: seven of 36 trustworthy candidates clear the payout
minimum, modeled reward is **$7.369/day** on $65.20 modeled collateral. The
legacy mode produced $93.414/day. The current number is still not a
fixed-universe result and contains no trading P&L, so it is not profitability.

### VERIFIED — the reference strategy was re-read from current code

The Polymarket repository was inspected read-only with no venue API request.
Local HEAD and GitHub `main` are identical at
`3134678e9937881a4b890c500fd905efb28abad6`; the working tree was clean and the
strategy files match reviewed deployed source `5825db8`.

The actual entry policy is size 10 across 20 sports/day-of slots: join both
touches when spread is at least 2¢, otherwise center an exact 2¢ quote window.
Entries are post-only, constrained to 10¢–90¢ and a stressed complete exit.
After a fill, cancel the risk-building side, work a passive reducer, and force
an IOC after 900 seconds or at T−300 seconds before the event. The reward/cost
gate is advisory/off. See `docs/POLYMARKET_REFERENCE.md` for source mapping and
remaining fidelity gaps.

### MEASURED — later-book loss replay is adverse, with material unknowns

`exit_cost.py`, same capture, size 10, audited Polymarket entry-price policy,
60-second maximum capture gap:

| deadline | fills | passive | timed cross | unknown | priced P&L | mean priced |
|---:|---:|---:|---:|---:|---:|---:|
| 300s | 84 | 5 | 65 | 14 | −$30.4411 | −$0.4349 |
| 900s | 84 | 11 | 56 | 17 | **−$27.8505** | **−$0.4157** |
| 1800s | 84 | 13 | 52 | 19 | −$26.7601 | −$0.4117 |
| 3600s | 84 | 17 | 33 | 34 | −$20.8166 | −$0.4163 |

Timed crosses use the first book at or after the deadline and include the
Kalshi taker fee at actual VWAP. The falling total at longer deadlines is not
evidence that waiting is safer: priced coverage falls from 83.3% to 59.5%.
Unknown fills are not assigned zero, and no complete net can be calculated
until they are bounded and this loss path shares the fixed reward clock.

---

## 21. The isolated read-only server shadow is operational

### VERIFIED — deployment did not share the Polymarket project or process

On 2026-08-27 UTC, tracked commit
`c13524201819c3f771b9b8193e168a9ae85e1372` was installed at
`/root/kalshi-bot` with its own virtual environment, database, logs, and
transient service. The recorder source scan found only the public
`api.elections.kalshi.com` base and default-method `urllib` requests; it found
no order/portfolio endpoint or write HTTP method. All 25 measurement tests
passed on the server.

The pre-canary and post-canary Polymarket supervisor/trader PIDs and start times
were identical. This verifies process separation for the deployment/canary; it
does not prove that future resource use can never interfere, which is why the
service is capped at 20% CPU and 256 MB RAM and remains monitored.

### MEASURED — two-minute canary, not strategy economics

Dataset `data/canary-20260827.db`, run
`cap-20260827T023150Z-a419d203`, 2026-08-27 02:31:50–02:34:07 UTC, five tracked
markets and 50 density candidates:

- 65 raw book snapshots and five market-metadata rows;
- zero non-200 book responses and zero recorded errors;
- SQLite integrity check `ok`;
- 16,371 first-seen program rows and one exchange-status row.

This canary verifies collection mechanics only. It contains no strategy fills
and cannot support a reward, trading-loss, or profitability claim.

### VERIFIED — 14-day collection started

The read-only service `kalshi-readonly-capture-14d` started at
2026-08-27 02:35:40 UTC, using run id
`cap-20260827T023541Z-dcee8aea`, 75 tracked markets, 60-second sweeps, at most
five public reads per second, and hourly density scans. Planned checkpoints are
2026-09-03 and completion on 2026-09-10. The initial service state was active
with one process and about 16 MB memory. This is an operational observation,
not evidence that the strategy is profitable.

### MEASURED — eight-hour operational checkpoint

Dataset `data/shadow-14d-20260827.db`, run
`cap-20260827T023541Z-dcee8aea`, observation window 2026-08-27
02:36:20–10:49:22 UTC:

- 41,501 raw book rows across 1,262 density-candidate tickers;
- 75 active tickers in the preceding five minutes and 5,241 captured trades;
- zero non-200 book responses and zero recorded errors;
- 60.0-second median active-market sample gap, 107.9-second p95, and
  267.1-second maximum over the preceding two hours;
- database plus WAL about 58 MB after 8.2 hours.

The service had zero restarts and its newest book was 30 seconds old. The
longer gaps coincide with hourly density scans that take about 200 seconds.
Those gaps are a known capture bias: downstream reward/fill analysis must mark
them missing rather than infer continuous qualification or no trades.

**VERIFIED capacity observation:** 461 MB host memory was available; Kalshi
used 105 MB with a 113 MB peak under its 256 MB cap; the one-core load averages
were 0.00/0.03/0.00; 19.4 GB disk remained; and the kernel recorded no OOM
event. Linear storage growth implies roughly 2.4 GB for 14 days. No server
upgrade is indicated at this checkpoint.

**UNKNOWN process event:** the Polymarket supervisor/trader observed at launch
were replaced by processes started at 04:02:57 UTC. The Kalshi unit did not
restart, there was no kernel OOM event, and later host load was low. Those facts
do not identify the restart's cause, so it must not be attributed to Kalshi
without additional evidence.

---

## 22. Current server data rejects broad pure spread scalping

### MEASURED — closed 9h51m server dataset

Dataset `data/server-shadow-20260827-closed.db`, run
`cap-20260827T023541Z-dcee8aea`, 2026-08-27 02:35:41–12:27:03 UTC, 50,038
books, 5,626 trades, size 10. The run ended early on a transient TLS EOF; it is
not a complete day and contains hourly density-scan gaps.

Non-overlapping quote windows produced:

| policy/window | windows | pairs | one-sided | neither | one-sided:pairs |
|---|---:|---:|---:|---:|---:|
| touch / 900s | 8,620 | 11 (0.1%) | 88 (1.0%) | 8,521 | 8.0:1 |
| inside / 900s | 8,620 | 21 (0.2%) | 140 (1.6%) | 8,459 | 6.7:1 |
| touch / 3600s | 6,574 | 12 (0.2%) | 48 (0.7%) | 6,514 | 4.0:1 |
| inside / 3600s | 6,574 | 26 (0.4%) | 70 (1.1%) | 6,478 | 2.7:1 |

Completed pairs earned positive gross spread, but they are too rare to define
the economics. At 900 seconds, a realized-exit replay priced 86 of 100 touch
fills for `-$50.9463` total and 236 of 277 inside fills for `-$108.7736`;
14 and 41 exits respectively remain unknown. The exit replay is not on the
same non-overlapping sampling clock, so these totals must not be subtracted
from pair edge as if they formed one portfolio. Directionally, however, both
instruments agree: broad pure spread scalping creates inventory much more often
than it captures both sides, and getting flat is adverse.

### INFERRED — reward may rescue selected markets, but this is not net yet

The current-rule same-clock proxy for the audited Polymarket entry policy,
size 10 and `$300` modeled capital, selected 30 markets and reported 93.1%
uptime, 201.3 partial fills/day, `$28.36/day` modeled reward,
`-$9.75/day` 300-second markout, and `+$18.61/day` proxy. Reward-only selection
of 20 markets reported `$25.385/day` after minimums on `$189.30` collateral.

These positive figures are **INFERRED**, not profitability: they extrapolate
partial program coverage, include sparse hourly candidate samples, use markout
instead of realized exit, omit maker/exit fees, and do not bound unknown exits.
The corrected current-policy exit replay found 106 fills, priced 92 for
`-$54.8268` total, and left 14 unknown. A fixed-universe replay that puts
reward, pair completion, realized exits, and unknown bounds on one clock is
still required.

### VERIFIED — retry-hardened replacement capture started

Commit `b97065485cbcf10b6c7c0a34d23c0d8c090e4f5e` passed the read-only endpoint
scan and all 27 tests on the server. Replacement run
`cap-20260828T003459Z-44ea69de` started at 2026-08-28 00:34:59 UTC as
`kalshi-readonly-capture-14d-r2`, with the same 20% CPU quota, 256 MB memory
limit, five-read/s limiter, and separate database/log. The Polymarket process
was absent and was not touched. This verifies deployment and start, not yet
survival of a real transport failure.

### VERIFIED — host reboot stopped R2; R3 restarted from a fresh database

The host shut down at 2026-08-28 01:22 UTC and booted again at 01:24 UTC.
Systemd recorded R2 stopping cleanly with an 87.6 MB memory peak and no kernel
OOM event. Because R2 was a transient unit, it no longer existed after boot;
this was a host-lifecycle interruption, not a recorder exception.

After all 27 tests and the read-only endpoint scan passed again at deployed
commit `b970654`, run `cap-20260828T021706Z-2e9d1d6b` started at 02:17:05 UTC
as `kalshi-readonly-capture-14d-r3`. It uses the same 20% CPU, 256 MB memory,
five-read/s, 75-market, 60-second-sweep boundaries and writes a fresh database
and log. At 02:19:17 UTC it was active as PID 3898 with zero restarts; the
database quick check was `ok`, 450 book rows, 17,069 program rows and one
exchange-status row were present, and zero errors were recorded. The live
Polymarket trader remained PID 2251 across the R3 start.

### VERIFIED — R3 survived a real transient network failure

At 2026-08-28 10:27:03 UTC, R3 logged an attempt-1/3 `URLError` caused by a
connection reset by peer. At the 12:58 UTC inspection it retained PID 3898 with
zero restarts and no traceback, its newest book was about 11 seconds old, and
the database had zero recorded errors and zero non-200 book rows. The bounded
retry fix has therefore survived a real transport interruption of the same
general class that ended the first capture. This verifies recorder resilience;
it does not turn the partial capture into profitability evidence.

---

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
6. ~~Whether reward density is stable enough over a Time Period to rank on.~~
   **ANSWERED 2026-08-18 in section 11.** Stable enough to rank on — first-half
   vs second-half Spearman +0.818, 73% of markets within 2x — but re-measure
   continuously: a quarter of the top 12 rotates out within hours. Established
   over ~10 hours only, not over a full 7-14 day period.

---

## 8. Recommended order of work

1. Port `shadow_run.py` + `shadow_store.py` first. Read-only, zero risk, and it
   answers Q1, Q3, and Q6 with real Kalshi data.
2. Resolve Q4 (post-only) — it is structural for the reconciler.
3. Only then port the economics, and only then the execution path.

This is the same order that got liquidity-bot to a working state. Do not skip the
shadow phase: every number in section 4 is a single instantaneous snapshot.
