# What exists

Inventory of everything built, what it does, and how it was verified. Updated
when something is finished — not when it is started.

Companion files: `NEXT.md` (what to do next), `FINDINGS.md` (what we learned),
`BUGFIXES.md` (what broke and why).

Last updated 2026-08-17.

---

## Status at a glance

| phase | scope | state |
|---|---|---|
| Research | Reward rules, fee model, universe shape | **done, ongoing refinement** |
| Instruments | Raw capture, signed reads, formula replay | **done** |
| Analysis | Reward share, two-sided rate, tick effect | **partial** |
| Phase 0 | Pure core (models, rewards, risk, fees) | **not started, deliberately** |
| Phase 1 | Read-only adapters + streams | not started |
| Phase 2 | Shadow measurement harness | not started |
| Phase 3 | One-contract evidence run | not started |

Phase 0 is deliberately not started. Several numbers the economics depend on
are still inferred, and code written now would bake them in permanently. See
`NEXT.md` "Still unknown, and blocking".

---

## Instruments — built and working

### `scripts/record_books.py` — 466 lines

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

**Known limits:** ranking is the only interpretation in the script, and it is
scale-invariant so an unconfirmed `period_reward` unit cannot corrupt it. Real
sample spacing is the sweep duration, not `--interval` — read the timestamps.

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

### `scripts/analyze_capture.py` — 216 lines

Replays Kalshi's published reward formula over captured raw books. Pure
arithmetic on recorded data — the CFTC filing fully determines each order's
score given the book and the program parameters.

Reports per `(ticker, side)`: two-sided rate, denominator, share at the touch,
share one tick inside, and a crowding flag when our own size would dominate the
side.

**Verified:** 3,786 snapshots analysed; produced the 85% two-sided rate and the
1.987x one-tick result. Two reporting bugs found and fixed — see `BUGFIXES.md`.

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

Encodes the payout chain's two non-obvious steps: our fraction of the pool is
the **mean** of our two side shares (each counting snapshot contributes 2.0 to
the denominator, one per side), and snapshots excluded for one-sidedness leave
both numerator and denominator, so the 85% two-sided rate does not scale
revenue.

**Verified:** produced FINDINGS 9 — roughly $24/day at 25 contracts on $243 of
collateral, saturating above that. Its first version reported **$2,175/day and
9,779%/day**; three guards were added after that output was disbelieved and
traced, and each is documented at its definition.

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

---

## Documentation — built

| file | lines | purpose |
|---|---|---|
| `FINDINGS.md` | 950 | established facts, each with its measurement |
| `docs/PLAN.md` | 299 | the approved end-to-end plan |
| `docs/REFERENCE_CRITIQUE.md` | 280 | liquidity-bot: what to copy, discard, invert |
| `NEXT.md` | 130 | session orientation: state, blockers, next actions |
| `README.md` | 60 | what the project is and what to read first |
| `BUGFIXES.md` | 110 | instrument bugs: symptom, mechanism, fix |

---

## What explicitly does NOT exist

No package, no `pyproject.toml`, no `src/kalshi_bot/`. No models, no reward
scorer, no risk model, no ledger, no reconciler, no order code, no tests.

Nothing has placed an order. Nothing has committed capital. `$22.64` sits
untouched in the account.

This is the intended state. The instruments answer questions; the bot gets built
from the answers.

---

## Answered by what we built

- Taker fee formula, proven against two real fills
- Rate limits — 200/s reads, ~50x the reference implementation's assumption
- Two-sided rate — 85%, versus ~60% from an 8-market hand sample
- One tick inside doubles reward share — 6,438 observations, p10 1.916, p90 1.999
- No short exists: selling YES is executed as buying NO
- The pair trade effectively does not complete — 7 pairs in 1,064 windows
  (0.7%), so reward is the only established revenue source and quoting one tick
  inside costs nothing realised
- One-sided fills are adverse — sign test p=0.0014, mean −$0.1271/fill at 5
  contracts with a bootstrap CI excluding zero
- Net is positive across the whole interval at 25 contracts ($11.30–$21.49/day)
  and straddles zero at 100

## Still unanswered, and why

| question | why the instruments cannot answer it |
|---|---|
| `period_reward` scale | no earnings endpoint exists; likely needs a real payout |
| maker fee rate | both account fills were `is_taker: true`; needs one resting fill |
| `revenue: 0` on a settled position | needs a second settlement to compare |
| post-only support | needs an order placement, which the operator must run |
| cost of a fill in *lost reward* | needs open question 3 resolved: must our own orders be on both sides, or merely someone's? |
| whether 6h generalises | 44 politics/econ markets, ~14h of books, no sports |
