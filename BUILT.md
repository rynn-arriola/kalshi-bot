# What exists

Inventory of everything built, what it does, and how it was verified. Updated
when something is finished — not when it is started.

Companion files: `NEXT.md` (what to do next), `FINDINGS.md` (what we learned),
`BUGFIXES.md` (what broke and why).

Last updated 2026-08-26.

Current authority and scope are in `AGENTS.md`, `STATUS.md`, and
`DECISIONS.md`. Reproducing an old table means an instrument is operational; it
does not validate the reward-rule interpretation or establish profitability.

---

## Status at a glance

| phase | scope | state |
|---|---|---|
| Research | Reward rules | **resolved — July filing is current** |
| Research | Fee model, universe shape | measured, with named gaps |
| Instruments | Raw capture, signed reads, formula replay | **done** |
| Analysis | Reward share, two-sided rate, tick effect | **done** |
| Analysis | Fill cost, integrated net, ranking metric | **done** |
| Analysis | Exit cost | **corrected later-book replay done** |
| Analysis | End-date concentration | **not started** |
| Experiment 0 | Rule and accounting audit | **done** |
| Experiment 1 | Fixed-universe replay | **active** |
| Experiment 2 | Read-only live shadow | gated |
| Experiment 3 | Minimal live evidence run | **not authorized** |
| Full bot phases | Package, executor, scheduler, deployment | **paused by D-001** |

The full-bot phases are deliberately not started. Current work is limited to
the evidence ladder in `EXPERIMENT.md`. See `STATUS.md` for blockers and
`NEXT.md` for the active queue.

---

## Instruments — built and working

### `scripts/strategy_policy.py`

Pure implementation of the current Polymarket entry-price rule, pinned to the
audited local/GitHub commit in `docs/POLYMARKET_REFERENCE.md`. It joins both
touches at a spread of at least 2¢ and otherwise centers an exact 2¢ window on
the price grid. No Polymarket API or project import is used at runtime.

**Verified:** seven unit fixtures plus a one-time read-only parity check against
the current reference function for wide, tight, locked, and half-cent books;
all quote pairs matched exactly.

### `scripts/record_books.py` — 547 lines

Raw capture of liquidity-incentive programs, order books, trades, and exchange
status. **Interprets nothing**: stores exact venue JSON with a timestamp.

| capability | detail |
|---|---|
| programs | all active liquidity programs, paginated, every ~15 min |
| books | `depth=100` (200 returns HTTP 400), per sweep |
| trades | 48h backfill on first sight, then overlapping windows, deduped on `trade_id` |
| exchange status | so closed-market gaps are not read as zero liquidity |
| errors | recorded as data, including sweep overruns |

Selection is capped per series (default 3) — without it the top 40 by
`reward/target` came back as 29 markets from one event.

**Verified:** running now, 40 markets across 18 series, 4,625 books and 2,531
trades, 1 non-fatal error (a sweep overrun, which is recorded deliberately).

**Revised 2026-08-18**, after two defects were measured (see `BUGFIXES.md`):

- **Sticky selection.** A ticker, once picked, is held until its program's
  `end_date` passes. Re-ranking from scratch every 15 minutes meant only **19 of
  82 markets survived a 20-hour run**, so churn was destroying period coverage
  faster than duration built it — and coverage is the guard that decides whether
  a market's share is trustworthy at all.
- **Terminal-state programs are polled too.** `status=active` was hardcoded, so
  a program's end state and any `paid_out` transition could never be observed.
  Checked live: `settled`/`ended`/no-filter return a different population.
- **`market_meta` refreshes** each program cycle instead of once on first sight,
  so a market settling mid-capture records its result.

**Known limits:** the ranking metric is **wrong and known to be wrong** —
`reward/target` is anti-correlated with revenue (FINDINGS 11). It is
scale-invariant, so an unconfirmed `period_reward` unit cannot corrupt it, but
that was never the problem. Replacing it needs an orderbook call per candidate
to measure the denominator. Real sample spacing is the sweep duration, not
`--interval` — read the timestamps.

### `scripts/kalshi_auth.py` — 127 lines

Signed read-only access. **No order function exists in this module and there is
no code path to an order endpoint.**

RSA-PSS/SHA-256 over `timestamp + METHOD + path`, where the signed path includes
the `/trade-api/v2` prefix and excludes the query string, timestamp in
milliseconds as a string, salt length = digest length. All four details are easy
to get wrong and fail identically with `token_authentication_failure`, so they
are documented in the module.

**Verified:** authenticated against the live account. Balance read, `/account/limits`,
positions, orders, fills, settlements all returning 200.

### `scripts/reward_rules.py` and `scripts/analyze_capture.py`

Pure, versioned reward arithmetic plus replay over captured raw books. The
default `july-2026-one-fifth` mode follows the July filing effective July 30;
the February best-bid mode remains for historical reproduction only. The
module has no network, credential, database, or order path.

Reports per `(ticker, side)`: two-sided rate, denominator, share at the touch,
share one tick inside, and a crowding flag when our own size would dominate the
side.

**Verified:** 11 hand-checkable unit tests cover both references, better levels,
Target Size failure, the two-sided gate, proposed-order insertion,
excluded-snapshot scaling, cent flooring, and the $1 minimum. On 58,453
`capture_long.db` snapshots, current mode gives a median inside/touch multiple
of **1.000x** over 112,492 sides; legacy mode gives **1.943x**. Every report
prints its rule mode, source date, effective date, status, and source URL.

### `scripts/markout.py` — 320 lines

Fill rates and markout for a resting two-sided quote, replayed over captured
books and the trade tape. Answers the half of `FINDINGS.md` 6g that the spread
analysis could not: whether the pair actually completes.

Reduces every trade to a signed YES-equivalent from the `yes_price_dollars` /
`no_price_dollars` pair and `taker_side`, never from `taker_book_side` — which
reports `bid` and `ask` in opposite frames for the same kind of trade. Queue
position follows from the quoting policy: joining a touch rests behind the
displayed depth, stepping a tick inside creates an empty level and is first in
line. Tick size is inferred per market from the observed price grid, because
market metadata carries no tick field and not every market is on a cent.

**Verified:** 140 non-overlapping one-hour windows, 44 markets. Produced the
near-zero-pair-completion result and the 8.6% both-directions-traded ceiling.
The fill detector was checked against a front-of-queue bound before the result
was trusted — it does produce fills and completed pairs when queue position is
removed, so the rate is a property of the tape rather than a broken predicate.

**Corrected 2026-08-17:** the headline "0 pairs" was a sample size, not a
property. At 1,064 windows the same code finds 7. See `pooled_markout.py` and
FINDINGS 6h.

**Known limits:** requires a full fill, counts no partials, gross of fees, and
assumes a static book — which is weakest exactly where the answer is most
favourable, since nothing models other makers stepping inside us.

### `scripts/sizing.py` — 250 lines

End-to-end revenue estimate: pool x our share, per market, with the filing's
two-sided rule and its $1.00 minimum payout applied. Reuses `analyze_capture`'s
`qualifying` and `share_with_order` rather than reimplementing the formula.

Encodes the payout chain's non-obvious steps: our fraction of the pool is the
**mean** of our two side shares, excluded snapshots scale down the payable pool
under the current rule, payout is floored to cents, and the $1 minimum applies
per program.

**Verified:** current-mode size-10 touch replay on `capture_long.db` reports
**$7.369/day** after the minimum across seven paid markets and $65.20 modeled
collateral. The legacy mode reports $93.414/day across 18 paid markets, which
demonstrates why the old rule cannot drive an August decision.

**Known limits:** only 10 of 52 markets survive the guards, at 10-25% period
coverage, so share is extrapolated 4-10x. Assumes continuous resting and a
static book.

### `scripts/pooled_markout.py` — 322 lines

Pools one-sided fills across every capture and settles their sign with a
**binomial sign test** and a **bootstrap CI on the mean**, at each size. Imports
`markout.py`'s fill predicate, queue model and YES-frame reduction rather than
reimplementing them.

Exists because the obvious approach failed. 6h said the sign needed a bigger n,
and widening the universe from 40 to 150 markets made the sample grow *slower*
— ranking by `reward/target` selects thin books, so added markets are quieter
than held ones. Accumulation is rate-limited by the same property that makes the
strategy work, so the fix was a better statistic, not more data.

The sign test is immune to the single −$1.75 outlier that made 6h's mean
useless; the bootstrap bounds the mean, which is what P&L is actually paid in.

**Verified:** produced FINDINGS 6i — drag −$0.1271/fill at 5 contracts, 95% CI
[−$0.2374, −$0.0369], sign test p=0.0014 at 300s. Re-measures fill rate and
markout independently at each size rather than scaling one number. Also
corrected two claims made from an earlier inline version of this analysis: the
captures are **not** independent (69 shared markets), and completed pairs are
7, not 0.

**Known limits:** pooled p-values are optimistic because of that market
overlap — the wide slate alone does not reach significance and its CI includes
zero. Reward per size is imported from FINDINGS 9 as a constant, not recomputed,
so the seam between the two measurements stays visible.

### `scripts/net_sizing.py` — 340 lines

Reward accrual and fill simulation on **one clock**, so the two stop
contradicting each other. `sizing.py` never reads the trade tape and assumes we
rest continuously; `markout.py` assumes we are filled. Adding their outputs
double-counts our presence during exactly the minutes a fill has our quotes
down. Here a fill takes the quotes down and the reward integral stops on both
sides, which is what section 2's two-sided rule requires.

Models two things `markout.py` deliberately did not: **queue position persists**
across snapshots while our price is unchanged (a real quoter holds its place),
and **partial fills** under `--fill-model partial`.

**Verified:** produced FINDINGS 10 — net **$10-$26/day** at 25 contracts on
$300 across 12 markets, roughly **40% below** the $31.76 that adding sections 9
and 6i gave. Persistent queue raises the fill rate to ~37/day against the ~11/day
6i implied, so 6i's rate is a lower bound from a pessimistic queue assumption.

Carries a **concentration guard**: drop a market whose best 10% of snapshots
carry over 30% of its reward score. Without it, switching from `sizing.py`'s
median to the formally-correct mean moved reward 44% ($37.44 to $53.98) — because
ranking by mean selects markets whose mean is inflated by a few thin-touch
snapshots. With the guard, mean and median agree within $3.

**Known limits:** `--flatten-seconds` is unmeasured and spans the answer by a
factor of 2.6, so the post-fill policy is now the dominant uncertainty. Gross of
fees, static book, shares extrapolated from 10-33% period coverage.

### `scripts/exit_cost.py`

What it costs to get flat after a fill, as realised P&L rather than markout.
Simulates passive close, timed taker cross, and recorded settlement. A timed
cross walks the first usable book at or after the deadline for the whole size
and pays the proven fee formula at actual VWAP. Missing, stale, and thin books
without settlement are explicit unknown exposure.

**Verified:** six unit tests cover later-only book selection, capture-gap
rejection, YES/NO ladder direction, fee charging, settlement signs, and passive
pricing. On `capture_long.db`, size 10 under the current Polymarket entry policy
and a 900-second deadline produced 84 simulated fills: 11 passive, 56 fully
crossed, 17 unknown, total priced P&L **−$27.8505**, mean **−$0.4157**, median
**−$0.3070**.

**Known limits:** its fill detector requires whole-order tape volume and differs
from `net_sizing.py` partial mode. Passive maker fees are unmeasured. At 900
seconds, 20.3% of fills are unknown, so the priced total is not a conservative
portfolio loss bound until those exposures are bounded.

---

## Documentation — built

| file | purpose |
|---|---|
| `AGENTS.md` | authoritative AI contract, boot sequence, and authority boundary |
| `STATUS.md` | canonical current truth and blockers |
| `DECISIONS.md` | accepted operator decisions and pending decision requests |
| `EXPERIMENT.md` | active evidence ladder and reporting contract |
| `NEXT.md` | ordered executable queue only |
| `FINDINGS.md` | durable evidence, hypotheses, and corrections |
| `BUGFIXES.md` | instrument bugs: symptom, mechanism, fix, verification |
| `docs/PLAN.md` | paused historical full-build design |
| `docs/REFERENCE_CRITIQUE.md` | dated reference audit; architecture versus calibration |
| `docs/REWARD_RULES.md` | governing sources and hand-checkable fixtures |
| `docs/PNL_ACCOUNTING.md` | canonical definition of measured net and unknown exposure |
| `docs/POLYMARKET_REFERENCE.md` | versioned current reference behavior and fidelity gaps |
| `README.md` | project entry point |

---

## What explicitly does NOT exist

No production package, `pyproject.toml`, or `src/kalshi_bot/`; no live risk
model, ledger, reconciler, or order code. Tests cover measurement arithmetic
only.

Nothing has placed an order. Nothing has committed capital. `$22.64` sits
untouched in the account.

This is the intended state. The instruments answer questions; the bot gets built
from the answers.

---

## Answered by what we built

- Taker fee formula, proven against two real fills
- Rate limits — 200/s reads, ~50x the reference implementation's assumption
- Two-sided rate — 85%, versus ~60% from an 8-market hand sample
- Under the current July rule, one tick inside adds no reward share on the long
  capture: median/p10/p90 all 1.000x over 112,492 side observations
- No short exists: selling YES is executed as buying NO
- The pair trade effectively does not complete — 7 pairs in 1,064 windows
  (0.7%), so reward is the only established revenue source and quoting one tick
  inside costs nothing realised
- One-sided fills are adverse — sign test p=0.0014, mean −$0.1271/fill at 5
  contracts with a bootstrap CI excluding zero
- A later-book exit replay measures adverse trading losses and preserves
  missing/thin exits as unknown instead of zero

## Still unanswered, and why

| question | why the instruments cannot answer it |
|---|---|
| `period_reward` scale | no earnings endpoint exists; likely needs a real payout |
| maker fee rate | both account fills were `is_taker: true`; needs one resting fill |
| `revenue: 0` on a settled position | needs a second settlement to compare |
| post-only support | needs an order placement, which the operator must run |
| cost of a fill in *lost reward* | needs open question 3 resolved: must our own orders be on both sides, or merely someone's? |
| whether 6h generalises | 44 politics/econ markets, ~14h of books, no sports |
