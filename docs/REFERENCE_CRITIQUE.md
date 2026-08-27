# liquidity-bot as a reference: what to copy, what to discard

> **Historical audit, read with `../STATUS.md`.** This was measured on
> 2026-08-17. Later venue earnings established that the Polymarket reference was
> profitable under its balanced-leg report for 2026-08-20 through 2026-08-25.
> Any statement below that the reference is currently loss-making is
> superseded. Architectural lessons remain useful; economic calibrations do not
> port without re-measurement.

Read of `D:\polybot\liquidity-bot` on 2026-08-17. Read-only; that repo is never
modified by this project.

Scope of the read: `reconciler.py` (the pure planner), `rewards.py`,
`shadow_math.py`, `risk.py`, `fill_hazard.py`, `market_selector.py`, the
runner's economic gate in `live_commissioning.py`, and
`docs/SAFETY_INVARIANTS.md`.

This file exists so the porting decisions are not re-derived. It records
judgements about a design, not measurements of Kalshi — measurements go in
`FINDINGS.md`.

---

## 1. What the reference actually does

Three layers, cleanly separated, and the separation is the best structural idea
in the repo:

| layer | module | property |
|---|---|---|
| selection | `market_selector.py` | read-only, no order client, cannot mutate |
| planning | `reconciler.py` | pure: `MarketFrame` in, `list[PlanAction]` out, no I/O |
| execution | `live_commissioning.py` | applies **one mutation per market per pass** |

The planner is a two-state machine on `position == 0`:

```
plan(frame)
├─ state unknown / book mismatch / book stale  → CRITICAL
├─ position == 0 → _flat_plan       (build, both sides)
└─ position != 0 → _inventory_plan  (reduce, one side)
```

Entry gating in `_flat_plan`, in order: market open and beyond the flatten
deadline → moneyline only → reward-eligible (with a 90s dwell before pulling a
*resting* side) → `expected_net > 0` → priceable book → per-market and
portfolio worst-loss budget → a stressed complete close must exist.

Exit in `_inventory_plan` is three tiers: cancel everything building; rest a
passive reducer at the touch with no cost-basis floor; then at the inventory
clock or the pre-kickoff deadline, cancel-confirm-then-IOC under a price cap
that the deadline overrides.

---

## 2. Ports close to unchanged

**The three-layer split, and the purity of the planner.** A planner that
performs no I/O is testable against recorded books, which is exactly the shape
of `data/capture.db`. Keep this.

**No cost-basis floor on the passive reducer** (their invariant 5), and more
importantly the evidence behind it: maker-lab ran a floor and reached
settlement 79% losers *by construction* — 234 settled positions cost $443.88
where crossing at T-15 would have cost $64.18. A floor only fills when the
market returns to entry, so it exits winners and strands losers. The reasoning
is venue-independent and transfers whole.

**Counting our own size in the depth denominator whether or not the order is
already resting** (`rewards.py:196`). Omitting it makes eligibility flip the
instant our order rests: they measured 1,817 place/cancel cycles in 5.7 hours
at one price. Making "worth placing?" and "worth keeping?" answer the same
question is the fix. `scripts/analyze_capture.py:50` already does this and
carries the note.

**Tick-space arithmetic, never float subtraction.** `41 * 0.01` is
`0.41000000000000003`; Decimal alignment validation rejects it and it retired a
market for a whole session. Nine of the ninety-nine cent prices land this way.
Kalshi prices arrive as decimal *strings* (`"0.9500"`), so parse to Decimal or
integer cents and stay there.

**Per-market fault isolation with bounded retirement** (their invariants
62/63). Three separate production incidents where one market's fault cancelled
every market's quotes. The bounding matters as much as the isolation:
retirement is opt-in by name so an unrecognised critical still fails closed;
ten rounds then abandon; more distinct retirements than `max_markets` is
systemic and stops the session.

**Absence is never read as cancellation.** Only a terminal state from the venue
resolves an order we lost sight of.

**Every constant carries its measurement and its counterfactual in a comment.**
`max_early_exit_loss = 4.0` lists all 17 observed crossed losses and explains
why $0.75 would be a policy of never crossing rather than trimming a tail. This
is the most valuable habit in the repo and costs nothing to adopt.

---

## 3. Do not port

### 3a. An EV gate that is switched off

`enforce_reward_cost_gate = False` in both the selector and the runner. With it
off, `expected = max(expected, 1e-9)`, so `expected_net_by_side` is positive for
every side always and the reconciler's `expected_net > 0` filter is vacuous. A
carefully built EV model whose output is discarded.

It got worse before it got noticed: the same field was the ranking key, so
switching the gate off silently switched the *ranking* off too and every market
tied on the primary sort. Nothing failed loudly. They caught it and now rank on
`projected_reward_total`.

**Why it is off is the lesson.** P&L is wrong by 3-10x, so the model cannot be
validated, so it cannot be trusted, so it was made advisory. **An EV model you
cannot measure against gets switched off, and then you are quoting whatever the
venue calls eligible.**

Consequence for us: `period_reward` scale is our version of the same hole. We
would ship a gate we cannot validate. That is the strongest argument for
treating blocker 1 as a policy question rather than an accounting one, which
`NEXT.md` already does.

### 3b. Revenue terms hardcoded to zero

`spread_capture = 0.0` and `maker_rebate = 0.0` (their invariant 34), because
attributable live evidence never arrived. The EV expression therefore carries
one revenue term against two cost terms:

```
reward × (1 − P_fill)  −  P_fill × unwind_loss  −  buffer
```

We have already measured the pair edge — median $0.0379 on 5 contracts,
positive in 98.2% of 22,030 snapshots (`FINDINGS.md` 6g) — so we start with a
revenue term they never turned on. **Keep the other half of their caution**:
that is the edge on a *completed* pair, and one side filling alone is
directional risk that 6g does not measure.

### 3c. One mutation per pass

`apply_one` executes a single mutation per market visit, so a cancel and its
replacement land on separate visits — median visit 35.2s, median re-price gap
69.4s. Reward is a time integral over resting orders, and the executor
deliberately dark-times itself between the two.

This is a workaround for a 4 req/s REST governor. **Kalshi reads refill at
200/s and writes at 100/s** (`FINDINGS.md` 6e), roughly 50x. The constraint
that forced this design does not exist for us, and cancel-then-replace can be
issued in one pass.

Their `NEXT.md` item 3 says not to pursue this, on a measurement showing the
cost was smaller than first thought. That is a measurement of one slate under
their rate limit, not a defence of the design.

### 3d. `book_stale` as a CRITICAL

No new data enters a fault path with escalating backoff. They found it *selects
against quiet books* — precisely the low-competition, high-reward-share markets
— and 30 of 31 retirements in one session were `unrecoverable_book_stale`.

Staleness should gate **new risk**, not trigger a fault. A market with nothing
to send is not a market that is broken, and on a strategy paid for resting
still, silence is the normal case.

### 3e. The fill-hazard model

The weakest empirical foundation in the repo, and it feeds the only term that
gates entry:

- calibrated from **one day** (2026-08-10), a **different bot** (maker-lab), on
  a **different venue**
- censored at first fill
- a `max` over *marginal* Wilson upper bounds, explicitly not a joint model
  (their invariant 43) — so the estimate is whichever single bin is highest,
  which is blunt and nearly constant

The companion `HISTORICAL_REWARD_YIELD_PER_CONTRACT_HOUR` table admits its own
units are wrong ("not the same quantity") and is fenced to ranking-only.

Do not port the numbers. The *shape* — a conservative upper bound so sparse
groups raise estimated risk rather than create false confidence — is worth
keeping once we have Kalshi fills to calibrate from.

### 3f. The 0.5 reward haircut

Arbitrary, and they say so: "still has no evidence behind it". It multiplies
into every projection. If we carry a haircut it needs a stated basis.

### 3g. Policy duplicated in two places

The gate lives in `_evaluate_rewards` (runner) and
`evaluate_market_opportunity` (selector). Changing one alone does nothing,
because a market that never becomes viable in the selector is never bound for
the runner to see. It cost them a deploy cycle to discover. One function, called
twice.

---

## 4. What inverts on Kalshi

Four differences change the design rather than the parameters.

### 4a. The bid/offer model does not port — this is the dangerous one

liquidity-bot works in one outcome's frame, where `offer = 1 − the other
outcome's bid`, and `WorkingOrder.side ∈ {"bid", "offer"}` carries direction
implicitly. Kalshi's `orderbook_fp` has the identical structure — two bid
ladders, `yes_dollars` and `no_dollars` — so the *book* reduction ports.

**The order and fill records do not.** There is no short: selling YES is
executed as buying NO, and the order and fill records disagree about `side` for
the same trade (`FINDINGS.md` 6f). Every place the reference writes

```python
"bid" if position > 0 else "offer"
```

is a place that would silently invert. Direction must be a signed
YES-equivalent carried explicitly as a first-class field, derived from the
`yes_price_dollars`/`no_price_dollars` pair, never from `action`/`side`.

### 4b. Fees become exact

`cross_exit` approximates with `taker_theta = 0.06` as a fitted coefficient. We
have the proven formula, `ceil(0.07 × C × P × (1−P) × 10000) / 10000`, verified
against two real fills on this account (`FINDINGS.md` 6e). The exit
counterfactual can be exact rather than fitted.

Maker fee rate is still unmeasured — both account fills were `is_taker: true`.

### 4c. Reward projection works for every phase

`project_order_reward` returns `period_duration_unproven` for anything but
`day_of`, because only that period has a provable six-hour clock. Two-thirds of
the lifecycle is unprojectable in the reference. Kalshi carries an explicit
clock on every program, so that failure mode does not exist for us.

### 4d. DiscountFactor is effectively a constant

`DF = 0.50` in 99.96% of live programs (`FINDINGS.md` 4), so
`discount ** ticks` is exactly `2^-ticks` — reward share halves per tick, which
the measured 1.987x one-tick effect confirms empirically. The tick-space search
is tiny and the arithmetic is exact.

---

## 4e. How the reference is actually doing — checked 2026-08-17

The single most useful thing in that repo is not its code. It is that a
liquidity-reward market maker has been running live on a real account for a
week, and **the trading losses have overtaken the reward.**

Its founding economics were "~$25/day in rewards against about −$1.2/day in
trading P&L — losses are ~5% of reward", and its own FINDINGS now says in
terms: **"It is no longer true."**

Measured over 203 fills and 93 markets, on the `complete` column only (both
legs recorded, so it is the trustworthy half):

| day | reward | trading | net |
|---|---|---|---|
| 2026-08-15 | +$28.46 | −$11.22 | **+$17.24** |
| 2026-08-16 | +$20.25 | −$27.58 | **−$7.33** |
| 2026-08-17 | not posted | −$51.03 (half day) | — |

The loss rate runs −5.03, −11.22, −27.58, −51.03 across four days, and per
market it grows too: −$0.49/market on 08-15 against −$1.89/market on 08-17.

All-time, measured without the ledger at all (equity minus funding, the one
calculation that needs no attribution): reward received $140.70 since 08-10
against trading of **at least −$121.71**. Their conclusion: "roughly
break-even, likely slightly negative."

**The mechanism is crossed exits.**

```
exit crossed (TAKER)   55 markets   -85.19   median -1.21   worst -8.33
exit passive (MAKER)   11 markets    -9.67   median -0.31
```

A crossed exit loses four times what a passive one does, and there are five
times as many. The maker/taker mix inverted from 33% taker on 08-15 to 73% on
08-16 and after — almost every position is now exited by crossing rather than
resting out — and fees flipped from a rebate to $3.46 paid.

### What this means for our numbers

1. **It corroborates the drag, at the pessimistic end.** `FINDINGS.md` 9 put
   our trading drag somewhere between 12% and 79% of gross reward and could not
   narrow it. The only live instance of this strategy anywhere has a drag that
   went from a *planned* 5% to over 100% in six days. When our own range cannot
   be resolved, this is the prior to use, and it says the pessimistic end.

2. **"Size is not the lever" — but on Kalshi it is worse than that.** Their
   reasoning: reward scores `discount ** ticks * size` and losses scale with
   size too, so cutting quote size scales both equally and leaves the ratio
   unchanged. On Kalshi that symmetry breaks in the *wrong* direction. Our
   reward is a normalized *share*, so it saturates sublinearly as our size
   enters its own denominator, while a fill's loss stays linear in size. That is
   exactly why our sizing table turns negative at 100 contracts under the mean
   case. **Beyond the peak, size is a negative lever here, not a neutral one.**

3. **The exit is the whole story, and we have not modelled it at all.** Our
   markout is a proxy for adverse selection, not a realised exit cost. Their
   split — passive −$0.31 against crossed −$1.21 — says the number that matters
   is *how you get out*, and we have measured nothing about that.

4. **The quiet-book question cuts both ways.** Our markets barely trade (64% of
   hours see nothing), so we fill rarely, so we should bleed rarely — that is a
   genuine structural advantage over their busy sports books. But thin, quiet
   books are also the ones you *cannot exit passively*, which is precisely what
   drove their taker share to 73%. Rare fills that are each expensive to exit is
   not obviously better than frequent fills that are cheap to exit. **This is
   unresolved and is the sharpest open question we have.**

5. **Their day-4 pattern is a warning about measurement windows.** They were
   profitable on 08-15 and loss-making on 08-16. Any of our conclusions drawn
   from ~14 hours of one slate could be sitting on the same kind of window.

### One more transferable finding

Before relaxing their 900s inventory clock they checked, and P&L degrades
**monotonically** with holding time on clean data:

```
0-300s  +23.8c    300-900s  -5.1c    900-1800s  -4.5c
1800-3600s -13.2c    3600s+  -23.5c
```

Only the first bucket is positive. If we ever hold inventory on Kalshi, this is
the shape to expect and it argues for a tight clock, not a generous one. They
also note the right way to revisit it is a randomised A/B, because every
historical cut is confounded identically — what gets held longer is chosen by
the market, not by us.

**Limit of this check:** read from the repo at commit `68bfd88`, 2026-08-17.
The live droplet was not queried — connection details are deliberately not in
that repo, and the venue is the only authority on current positions. These are
their measurements, not an independent verification.

## 5. The ordering lesson

Their entire optimisation queue — resting fraction, exit policy, selection, the
900s inventory clock, riding vs crossing — is blocked behind a P&L defect. Each
item was measured against P&L and every one of those measurements is suspect.
The root cause is a single filter that cannot distinguish "the counterparty's
leg" from "our own fill we cannot attribute", so both are discarded.

Two structural consequences worth taking:

1. **The ledger needs a settlements table from the first commit.** They had
   none until 2026-08-16, so every position that resolved was booked as a total
   loss of its entry cost regardless of outcome. On a binary venue that is where
   the money is. Our `revenue: 0` on a position that should have paid $14.91
   (`FINDINGS.md` 6f) is the same defect surfacing early.
2. **Record every fill of ours, attributable or not**, flagged rather than
   dropped, so double-counting stays impossible while nothing of ours is lost.

Accounting is not the boring part that comes after the strategy. It is the
thing that decides whether any strategy question can be answered at all.

---

## 6. Small things noted in passing

Neither is urgent; both are in the reference, not here.

- `reconciler.py:117` has an unreachable `raise` after the
  `minimum_entry_spread` check — dead code from a removed validation. Already
  on their housekeeping list.
- `_flat_plan` computes `candidate_loss` from the **touch** rather than from
  `entry_prices[side]`, the price the quote will actually rest at — the same
  class of inconsistency they fixed everywhere else. On a backed-off book it
  comes out conservative on both sides, so it is a cleanup rather than a live
  defect.
