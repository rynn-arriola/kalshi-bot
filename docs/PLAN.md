# kalshi-bot — historical end-to-end plan

> Current design authority: D-014 and [ARCHITECTURE.md](ARCHITECTURE.md).
> This old plan cannot override WebSocket-first data, CPU efficiency,
> scalability or the operator's planning-only/no-paper-testing boundaries.

> **PAUSED 2026-08-26 by operator decision D-001.** Do not execute the package,
> phase, or "first concrete steps" sections in this file. The current objective
> is to measure whether the Polymarket strategy can work on Kalshi without
> building the full bot. The active contract is `../EXPERIMENT.md`; current
> state and work are `../STATUS.md` and `../NEXT.md`. This file remains as design
> input if the operator later authorizes a full build.

## Context

`D:\polybot\liquidity-bot` is a working Polymarket US liquidity-reward market maker:
12,485 lines, 63 safety invariants, and a `FINDINGS.md` where nearly every entry was
bought with real money. Its readiness gate is still red (`DO_NOT_START_TRIAL`) and it
runs commissioning-only at 5 contracts across 20 markets.

Research (2026-08-16, recorded in `D:\polybot\kalshi-bot\FINDINGS.md`, committed at
`50405d6`) established that Kalshi runs a **self-serve Liquidity Incentive Program**
whose scoring formula is `DiscountFactor^ticks × size`, normalized per side —
**identical to what `rewards.py` already implements**. Authoritative source is the
KalshiEX CFTC filing of 2026-02-11, read verbatim; Kalshi's own help center
contradicted it on a material point and lost.

Kalshi is the better venue on the three levers liquidity-bot's own §6d identified as
dominant — *"breadth and period dominate size"*:

| lever | Polymarket | Kalshi |
|---|---|---|
| addressable universe | ~200, then **33** after spread filter | **2,328** active programs |
| period coverage | 218 markets in a 6h `day_of` window | every program carries explicit start/end |
| target size | 5,000–15,000 | **1,000** |

Polymarket's reward system is larger per market but ~0.24% reachable. Kalshi's is
smaller per market and almost entirely reachable.

**Outcome intended:** a read-only measurement system that produces real Kalshi data,
followed by a one-contract evidence run that settles the two questions measurement
cannot. No scaled capital until both are done.

---

## How we get real data

This is the crux, and most of it requires no capital.

**Tier 1 — exactly computed, no inference, no risk.**
The reward side needs no guessing. Given a book snapshot per second plus
`target_size_fp` and `discount_factor_bps` from the public API, we *replay Kalshi's
published formula* against real books. Exactly computable:
- our normalized share on each side, at any hypothetical price
- the competing denominator, and how it moves
- the two-sided gate (does each native ladder reach Target Size)
- **markout** — when a trade prints at price P, mark the book forward 60/300/900s

**Tier 2 — bounded inference.**
Only "would *we* have been filled" is unobservable, because queue position is. Report
a **pessimistic/optimistic interval**, never a point estimate. Mirrors the Wilson-bound
discipline already in `fill_hazard.py`.

**Tier 3 — ~$1.00 of real capital.**
Two things Tier 1/2 cannot answer: whether `period_reward` is really 1e-4 scale, and
whether Kalshi supports post-only. One contract, one market, both sides already
qualifying without us. A single paid reward settles the scale permanently.

**Known blind spot, to be flagged in the data itself:** our own quote changes the book.
At 5 contracts against a denominator of 5.1 we would *be* most of that side. This is
liquidity-bot FINDINGS §6e (*"our own quote makes the side uneconomic"*). Shadow
overestimates exactly the thinnest, highest-share markets — every such market must be
marked untrusted in the output, not silently averaged in.

---

## Decisions taken

- **Copy, don't extract.** Portable modules are copied into `kalshi-bot` and adapted.
  `liquidity-bot` is never modified. It has a red gate and an open P&L bug; shared code
  would mean a bug in either breaks both.
- **Polymarket P&L bug**: noted as a design lesson for the Kalshi ledger, not a blocker.
- **Scope**: Phases 0–2 plus a non-scalable one-contract evidence run. Execution
  architecture (Phases 3–5) is re-planned once real data exists.

---

## Design decisions that shape everything

### 1. The YES/NO model — the sharpest impedance mismatch

`models.py` has **no `outcome` field**: one `slug` = one book with bids and offers.
Kalshi is ticker + explicit YES/NO, and `orderbook_fp` returns `yes_dollars` and
`no_dollars` **both expressed as bids** (the CFTC text: *"a yes ask is counted as a bid
for no"*).

Resolution — keep both representations:

- **Native ladders** (`yes_bids`, `no_bids`) drive *reward scoring*. Each side is a
  walk down from its own best bid to Target Size. This is exactly what
  `evaluate_order_score` already does with `side="bid"` — the walk ports near-verbatim.
- **Derived YES-denominated book** drives *execution and exit pricing*:
  `yes_asks = [(1 - p, size) for p, size in no_bids]`. This yields a conventional
  two-sided `BookSnapshot`, so `cross_exit` and the reconciler work unchanged.

Getting this wrong is how you invert a price and mis-book a fill — which is precisely
the open Polymarket bug (FINDINGS §2: legs priced against the wrong outcome, ledger
reported +$1.34 on a trade that lost $0.30). **The inversion must live in exactly one
function, with tests asserting round-trip identity.**

### 2. The fee seam

`shadow_math.cross_exit` already models fees as `taker_theta * filled * average *
(1 - average)` with `θ=0.06` — structurally *identical* to Kalshi's `0.07·P·(1−P)`.
Replace the scalar with a **fee callable** taking `(contracts, price, liquidity_flag)`:

- taker: `ceil(0.07 × C × P × (1−P) × 100) / 100`
- maker: reported at 25% of taker — **UNVERIFIED**, fee schedule PDF is Cloudflare-blocked

`passive_close_pnl` currently assumes zero maker fee (correct on Polymarket, wrong here)
and must take the same callable.

Consequence to encode: at 50¢ the taker fee (1.75¢) **exceeds a full 1¢ tick**, so
crossing costs ~2.75¢ — roughly 3× the naive spread estimate. Any `max_exit_loss`
budget sized for Polymarket will refuse valid Kalshi exits and strand positions.

### 3. The two-sided gate — new, no Polymarket analogue

> "Snapshots will be excluded if there is not two-sided liquidity (i.e., resting orders
> sufficient to meet the Target Size on each side of the market)"

A new candidate-gate reason (`not_two_sided`). Measured on 8 sampled programs, **3 had
one side entirely empty** — this filter removes a large fraction of the universe cheaply
and must run before any economics.

### 4. Discovery is nearly free

`GET /trade-api/v2/incentive_programs?status=active&type=liquidity` is **public and
unauthenticated**, returning every parameter. Ranking the whole universe by
`period_reward / target_size` costs a handful of requests and accrues no cost.
**But that ranking is wrong — see FINDINGS 11.** The right metric needs one
orderbook call per candidate to measure the denominator; at 200 reads/s that is
still seconds for the whole universe, so discovery stays nearly free.

Liquidity-bot's invariant 51 (never scan while quoting) exists because Polymarket
discovery cost *31 minutes* for 7,443 markets. That constraint largely dissolves here —
but the invariant stays until measured, not assumed away.

---

## Phase 0 — pure core, no I/O

New package `D:\polybot\kalshi-bot\src\kalshi_bot\`. Copy and adapt:

| from liquidity-bot | to | change |
|---|---|---|
| `errors.py` | `errors.py` | verbatim |
| `settings.py` | `settings.py` | verbatim; drop the maker-lab clause |
| `risk.py` | `risk.py` | add the maker-fee term |
| `calibration.py` | `calibration.py` | `"PAID"` → Kalshi's `paid_out` bool |
| `rewards.py` | `rewards.py` | see below |
| `models.py` | `models.py` | YES/NO rework (decision 1) |
| `shadow_math.py` | `shadow_math.py` | fee callable (decision 2); drop ET reward-day slicing |

`rewards.py` specifics — `evaluate_order_score` (`liquidity-bot/src/liquidity_bot/rewards.py:142`)
ports with its walk intact. Changes:
- both sides walk **down from their own best bid**; there is no "offer" walk
- `IncentivePeriod` replaces `early/day_of/live` with explicit `start_date`/`end_date`,
  so `select_applicable_period` becomes a simple time-window test and
  `AmbiguousIncentiveError` may still fire on overlapping periods (the filing permits
  overlap explicitly)
- `project_order_reward`'s `period_duration_unproven` branch **disappears** — every
  Kalshi program has a real clock
- new: `snapshot_excluded` when either native ladder misses Target Size
- keep the comment at `rewards.py:180-195` about counting our own size in depth — that
  fix (1,817 place/cancel cycles in 5.7h) applies identically here

New `fees.py` — the Kalshi fee model, isolated and unit-tested, with the maker rate
marked unverified.

Tests mirror `tests/test_rewards.py` and `tests/test_shadow.py`: module-level frozen
clock, hand-built dataclasses, no mocking.

## Phase 1 — read-only adapters and streams

`adapters.py` — rewrite for Kalshi wire schema. Reuse `AsyncIntervalLimiter`
(`adapters.py:270`) unchanged, but note Kalshi uses **separate read/write token buckets**
(`GET /account/limits`), so the single-rate governor needs a second bucket eventually.
Endpoints: `incentive_programs`, `markets/{ticker}/orderbook` (**`depth=100` max —
`depth=200` returns HTTP 400**), `markets/{ticker}`.

`streams.py` — copy structurally. Per the exploration, it never mentions Polymarket and
needs only 8 duck-typed socket methods and 4 event names. Preserve the load-bearing
policies: bad-book tolerance (`streams.py:48-76`), scope-violation-is-fatal
(`:71-75`), and refuse-before-connect on subscription overflow (`:197-200`).
`MAX_PRIVATE_SUBSCRIPTIONS=10` / `MARKETS_PER_PRIVATE_CONNECTION=8` are **measured
Polymarket numbers and must be re-derived** — Kalshi documents far higher orderbook
subscription limits, and its WebSocket is **read-only** (all order management is REST).

`runtime_secrets.py` — Kalshi uses RSA-PSS SHA-256 over `timestamp + METHOD + path`
(path excludes query params). So `secret_key` becomes a **PEM file path**, not a secret
string. Keep the paired-credential rule (`runtime_secrets.py:134`) and `repr=False` on
secrets; add a PEM validator that loads once at startup and fails closed. `.env.example`
gains `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_FILE`, and a **demo-vs-production base
URL axis that has no Polymarket counterpart**.

New `tests/fixtures/*.json` captured from the live public API — these are the port's
real deliverable. Reuse the `FakeSocket`/`FakeClient` pattern (`tests/test_streams.py:25-78`).

## Phase 2 — shadow measurement

`shadow_store.py` — schema ports with two changes: every table keyed on `market_slug`
gains a **side/outcome dimension**; `shadow_incentive_periods` becomes Kalshi program
rows (`program_id`, `target_size`, `discount_factor`, `period_reward`, `start`, `end`);
`shadow_score_daily` keys on **program period**, not ET calendar day. Fix while porting:
it commits on every write (one fsync per book message) — batch it.

`shadow_engine.py` — port the fill inference at `shadow_engine.py:243-259` verbatim in
structure (trade print + synthetic queue: same-price prints eat `queue_ahead` first,
trade-throughs fill fully). Add, per Tier 2, **both** a pessimistic and optimistic
queue assumption per observation rather than a single number. Add the `not_two_sided`
candidate gate. Add markout recording at 60/300/900s — observable, no inference.

`shadow_run.py` — port the run loop. Replace the Polymarket slug archaeology
(`shadow_run.py:35-45`, `WINNER_SUFFIXES` / `is_two_way_slug`) with the Kalshi program
filter. `rank_candidates` (`:48-71`) already ranks by `reward_pool / target_size` —
~~that is exactly the right Kalshi metric and ports directly.~~

> **WRONG, corrected 2026-08-18. See FINDINGS 11.** That metric is
> **anti-correlated** with revenue on Kalshi (Spearman −0.150) because
> `target_size` is 1000 in 99.2% of programs while the denominator we actually
> compete against spans 629x. Rank by `period_reward / measured denominator`
> instead — worth ~6.5x on the top 12. It ports *syntactically* and loses all
> its discriminating power, which is the most dangerous kind of port.

New `shadow_report.py` output must separate:
- **computed** (reward share, denominator, two-sided rate, markout) — trustworthy
- **inferred** (fill rate) — always an interval
- **untrusted** — markets where our hypothetical size is a large fraction of the
  denominator (decision: the §6e blind spot)

## Phase 3 — evidence run

Explicitly non-scalable, modelled on liquidity-bot's commissioning exception.

> **REVISED 2026-08-18. This section said "one-contract" and "$23 available";
> both are stale.** FINDINGS 9 measured that at one contract only 1 of 10
> markets clears the $1.00 minimum payout — and a payout below it is
> **forfeited, not deferred** — so a one-contract run would very likely produce
> $0.00 of reward and could not distinguish "the scale is wrong" from "we were
> under the threshold". **Size the run from the program**, not from a habit of
> starting at one. Operator capital is now **$300**, and FINDINGS 10 puts the
> efficient unit at **25 contracts across ~12 markets** (~$25 collateral each).

**Operator-armed.** Claude builds the tooling, selects and justifies the candidate
market, and analyses the resulting data. **The operator runs the arming command and
places the order.** This mirrors liquidity-bot, where `live_commissioning.py` requires
four explicit acknowledgements and the operator runs `start_commissioning.sh` — the
human is already in the arming loop by design, not by exception.

Hard limits: **enough size to clear the $1.00 minimum over the program period,
1 market, both sides already qualifying without us**, a market chosen for *low*
fee (tail-priced) and *adequate* exit depth — deliberately not the highest-share
thin book. On measured pools that means roughly 5-25 contracts and a program
short enough to pay out inside the run.

Deliverables Claude produces for this phase:
- a ranked candidate list with the exact reason each market was chosen or rejected
- the arming command, with every parameter fixed and printed for review before it runs
- a pre-flight check (both sides qualify, exit depth adequate, fee at this price)
- a manual cancel/flatten command that works independently of the runner
- post-run analysis comparing the actual payout against the Tier-1 computed share

Answers, and nothing more:
1. `period_reward` scale — confirmed by an actual payout
2. post-only support — structural for the reconciler's `PLACE_POST_ONLY`
3. order mechanics, RSA-PSS signing, rate-limit behavior in practice

Requires before arming: the durable-intent discipline from `execution_ledger.py`
(intent committed *before* any mutation, ambiguous creates never retried), and a manual
kill path. Full ledger port is **not** in scope — a minimal intent log is.

## Explicitly NOT in this plan

Phases 4–5 (reconciler, armed multi-market commissioning) are re-planned once shadow
data exists. Every economic number in `FINDINGS.md` §4 rests on the unverified
`period_reward` scale, and designing an execution path on top of that would be building
on an inference.

**The expiry-flatten policy** — Kalshi's replacement for invariants 55/56 — is a
prerequisite for Phase 4 and must be designed from Phase 2 markout data. There is no
kickoff to anchor to, and this is the mechanism that cost liquidity-bot $88.20.

---

## Verification

Per phase, in order:

**Phase 0** — `$env:PYTHONPATH="src"; python -B -m unittest discover -s tests -v`.
Specific assertions: reward score against a hand-built book matches a
manually-computed CFTC-formula result; YES/NO inversion round-trips
(`invert(invert(x)) == x`); fee model reproduces 1.75¢ at 50¢ and the ceiling rounding.

**Phase 1** — a bounded read-only probe (mirroring `probe.py`) against the live public
API, asserting parsed output matches raw JSON for a named ticker. No auth needed for
discovery, so this runs immediately. Signed-request path verified separately once
credentials exist.

**Phase 2** — the real check: run the shadow harness against live Kalshi markets for a
multi-hour session, then confirm from `shadow_report.py` that (a) computed reward shares
are reproducible from stored books, (b) the two-sided rate matches the ~60% seen in the
8-market sample, (c) markout is populated at all three horizons, (d) fill intervals are
reported as intervals.

**Phase 3** — the order rests, is observed in `GET /portfolio/orders`, is cancelled
cleanly, and a reward payout appears. Compare the paid amount against the Tier-1
computed share to **confirm or refute the 1e-4 scale**.

## First concrete steps

1. `cd D:/polybot/kalshi-bot; git init` is already done (`50405d6`) — add `pyproject.toml`
   (src layout, `requires-python>=3.11`, mirroring liquidity-bot's minimal setuptools
   config) and the package skeleton.
2. Copy `errors.py` and `settings.py` verbatim; confirm the test harness runs green empty.
3. Write `fees.py` + tests — smallest self-contained unit, and it gates the risk model.
4. Port `models.py` with the YES/NO decision and its round-trip tests.
5. Port `rewards.py` and validate against the live books already sampled
   (KXRAIN-26AUG17-DEN yes side: denominator 71.8, 5-contract share 6.51%).
