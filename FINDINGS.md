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
