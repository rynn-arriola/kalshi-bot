# Bugfixes — kalshi-bot

Bugs that reached a running instrument. Symptom, mechanism, fix — written when
fixed, not at the end of a session. Companion to `FINDINGS.md`.

Nothing here has touched money: these are measurement bugs, and a measurement
bug that goes unrecorded becomes a "fact" in FINDINGS.

---

## 2026-08-17

### Trade capture recorded zero trades across 40 markets

**Symptom.** After adding trade capture, a 40-market sweep stored 0 trades with
no `fetch_trades` errors. Reads as "these markets never trade".

**Mechanism.** The window was `now - interval*3 - 30`, about 45 seconds. The
markets that rank highest on `reward/target` are thin *by construction* — that
thinness is why they rank — so almost none trade within any 45-second window.
The endpoint was fine; the question was too narrow.

**Fix.** Two modes. First sight of a market pages back `--trade-backfill-hours`
(default 48) with pagination; afterwards a deliberately overlapping window of at
least 300s. Trades dedupe on the venue's `trade_id`, so overlap costs bandwidth
and nothing else, while a gap loses fill signals permanently. Recovered 91
trades across 4 markets immediately, back to 2026-08-15.

### The per-market analysis reported a share that was arithmetically impossible

**Symptom.** `KXATPRETIRE-27DJO-Y` showed a 41% share against a denominator of
466. Five contracts against 466 cannot be 41%.

**Mechanism.** Yes and no medians were pooled into one row. That market's yes
side has a touch of **1.0 contract at 0.43** with the next level 13 ticks away
at 0.30 — and `0.5^13` is 0.0001, so the whole ladder below the touch is
arithmetically irrelevant. Its yes denominator is ~1.1 against ~990 on no. The
median of two numbers three orders of magnitude apart describes neither.

Worse, the "trust" flag divided our size by that pooled denominator, so the one
side where we would genuinely **be** the book was marked `ok`.

**Fix.** Report per `(ticker, side)`. Compute the crowding flag from the share
we would actually hold, not from the raw denominator.

**Kept as a finding, not just a fix:** a 0.50 discount factor makes any level
more than ~10 ticks from the touch worthless, so a book with a thin touch and
deep liquidity far away yields an enormous share. Those are exactly the books
where a static-book counterfactual is least trustworthy.

### The pair-trade net edge was understated 6x by pricing fees at 0.50

**Symptom.** `analyze_spread.py` reported a net pair edge of **$0.0062** on five
contracts against a gross of $0.0500, i.e. fees consuming 88% of the trade. The
conclusion drawn from that number -- reported to the operator before it was
checked -- was that the pair trade barely clears its own fees.

**Mechanism.** Both legs were priced at 0.50 as a "representative" price for the
fee curve. But `0.07·P·(1−P)` is a parabola with its **maximum** at exactly 0.50,
and the rewarded universe is mostly tail-priced -- KXRAIN's yes side sits at
0.08. Charging every leg at the single worst point of the curve overstated cost
by about six times. The correct figure is **$0.0379 net, positive in 98.2% of
snapshots**.

**Fix.** Charge each leg at its own touch price, per snapshot, rather than at any
representative value.

**The general rule this earns:** a fee, spread or slippage model must be
evaluated at the actual price, never at a stand-in. A "representative" value
sitting at the extremum of a curve is not conservative, it is simply wrong, and
it was wrong here in the direction that kills a viable strategy. Note the
asymmetry with liquidity-bot's habits: there, conservative stand-ins are correct
because they bound *risk*. Here the stand-in was applied to a *cost*, where the
same instinct destroys the result instead of protecting it.

### Two reported results were artifacts of sample size, not measurements

**Symptom.** Two claims were reported to the operator and one of them was
written into `FINDINGS.md`: that the pair trade **never** completes (0 in 140
windows), and that the one-sided markout sign was confirmed by "two independent
slates that agree exactly".

**Mechanism.** Different for each, same root.

*Zero pairs.* The true completion rate is 0.7%. In 140 windows the expected
count is 1.0, so observing zero is unremarkable — the sample could not
distinguish 0.7% from 0%. At 1,064 windows the same code finds 7. An
intermediate diagnosis, that zero was "a property of the politics slate", was
also wrong: the original slate produces pairs too once it has enough windows.
The variable was never the slate.

*Independent slates.* `capture.db` and `capture_wide.db` share **69 markets** —
88% of the narrow slate — and overlap in time, so some fills are plausibly the
same event counted twice. Run separately the wide slate does not reach
significance and its CI includes zero; only pooling produces p=0.0014. The word
"independent" was assumed from the fact that the databases are separate files,
which is a property of the storage, not of the sample.

**Fix.** `pooled_markout.py` measures and prints the shared-market count on
every run, so the overlap cannot be assumed again. FINDINGS 6h and 6i carry both
corrections in place rather than silently updated numbers.

**The general rule this earns:** *a rate that is indistinguishable from zero at
the observed n must be reported as an upper bound, never as zero.* "0 pairs in
140 windows" was arithmetic; "the pair never completes" was an inference the
arithmetic did not support, and it was load-bearing — 6h used it to resolve the
6g quoting-policy conflict. The conclusion survived, but only by luck.

Note the pattern shared with the fee-pricing bug above: both took a convenient
point value — 0.50 for a price, 0 for a rate — and treated it as the measurement
instead of as one reading with an interval around it.


## 2026-08-18

### The capture ranked candidates by a metric anti-correlated with revenue

**Symptom.** Every market this project has ever recorded was chosen by
`period_reward / target_size`. Measured against replayed revenue over 74
markets, that ranking scores **Spearman −0.150** — its top 12 markets earn
**$24.39/day** where ranking by `reward / measured denominator` earns
**$158.61/day**.

**Mechanism.** The metric was ported from liquidity-bot's `rank_candidates` and
restated in `docs/PLAN.md` as *"exactly the right Kalshi metric"*. Its stated
premise, at `record_books.py:341`, is that *"target size is the denominator we
compete against"*. On Polymarket that holds — `target_size` runs 5,000-15,000
and really does measure required liquidity. On Kalshi it is **1000 in 99.2% of
programs**, so the ratio degenerates to ranking by pool, badly.

Meanwhile the quantity it stands in for varies enormously: the measured
denominator spans **629x** across the same sample. FINDINGS section 4 had
already recorded why — DiscountFactor 0.50 collapses the effective competition
to the top few ticks — and nobody connected it to the ranking.

**Fix.** FINDINGS 11 records the measurement and the replacement metric.
`docs/PLAN.md` line 212 is corrected in place rather than left to be re-read as
settled.

**The general rule this earns:** *a ported calibration is a hypothesis, not a
fact.* The top of `FINDINGS.md` already says liquidity-bot's calibrations "are
NOT valid here until re-measured", and that discipline was applied to
`fill_hazard`, the 900s clock and the 2-cent spread rule — but not to the one
line that decided which markets we looked at for two days. **It survived because
three documents agreed with each other and none of them tested it.**

### Selection churn was destroying the coverage it was meant to build

**Symptom.** `sizing.py` discards any market observed over less than 10% of its
program period, and that guard was excluding the large majority — 32 of 52 at
one point. The obvious reading is "capture for longer".

**Mechanism.** `rank()` re-picked the top N from scratch every 15 minutes with
no memory, so tracked markets rotated out mid-run. Measured across three runs:

| run | tracked | distinct seen | present for the whole run |
|---|---|---|---|
| capture.db, 8h | 40 | 44 | 36 |
| capture.db, 20h | 40 | 82 | **19** |
| capture_wide.db, 4h | 150 | 242 | 82 |

**Only 19 of 82 markets survived the whole 20-hour run.** Duration was building
coverage and churn was destroying it faster, so a longer capture would not have
fixed it — the wide run's 214 markets collapsing to 1 trustworthy market was
partly this, not only its short duration.

**Fix.** Sticky selection: once picked, a ticker is held until its program's
`end_date` passes. Also fixed while there: program polling was hardcoded to
`status=active`, so a program's terminal state and any `paid_out` transition
were never observable — checked against the live API, `status=settled`/`ended`
and no filter return a different population. And `market_meta` was fetched once
on first sight, so a market settling mid-capture recorded no result.

**The general rule this earns:** *when a guard rejects most of your data, check
whether your own collection caused it before concluding the data is thin.*

---

## 2026-08-26

### Reward replay used a superseded filing and omitted current payout scaling

**Symptom.** August analyses treated the best bid as Reference Price, reported
that stepping one tick inside nearly doubled reward share, and paid
`share × pool` without reducing the pool for excluded snapshots.

**Mechanism.** The scorer implemented Kalshi's February 11 filing. A later July
15 certified filing, effective July 30, changed the reference to the first level
where cumulative size reaches one fifth of Target Size and added the
non-excluded-snapshot multiplier. The current Help Center matches the later
filing. The captured books are from August, after the change took effect.

**Fix.** Added pure versioned rules in `scripts/reward_rules.py`, made the July
mode the default, retained February only as a `SUPERSEDED` comparison, applied
pool scaling/cent flooring/the $1 minimum, and made every report print the mode
and source. Eleven unit tests and hand-calculated fixtures cover the divergent
rules.

**Verification.** Across 58,453 `capture_long.db` snapshots at size 10, current
mode reports inside/touch median `1.000x` (p10/p90 `1.000x`) over 112,492 sides;
legacy mode reports median `1.943x` (p10 `1.557x`, p90 `1.986x`). Current
reward-only portfolio output falls to `$7.369/day` after minimums versus
`$93.414/day` in legacy mode. The old one-tick and reward-dollar results are
therefore superseded, not alternative current estimates.

### Forced exits reused the entry book after waiting

**Symptom.** `exit_cost.py` claimed to wait 5–60 minutes before crossing, but
the deadline changed only the chance of a passive fill. Any forced cross was
priced from `series[index]`, the book associated with entry.

**Mechanism.** Reusing the entry snapshot erased the price move during the
holding period—the exact adverse-selection term the instrument was intended to
measure. Partial depth was also priced while the unfilled remainder silently
contributed zero.

**Fix.** Timed crosses now use the first captured book at or after the deadline
within an explicit tolerance. Missing, stale, and insufficient books are
`UNKNOWN` unless a recorded settlement prices the entire position. Passive
queue depth is zero when the reducer improves the touch and displayed size only
when it joins.

**Verification.** Six tests cover later-only selection, stale gaps, both exit
directions, actual-price fees, settlement signs, and passive pricing. On
`capture_long.db` at size 10 under the audited Polymarket entry policy and a
900-second deadline, 67 of 84 fills are priced for total P&L `-$27.8505`; 17
remain unknown and contribute no fake zero.

**The general rule this earns:** a clock parameter is not modeled merely
because it appears in a loop. Verify that the data used after the wait actually
comes from after the wait, and make every unpriced residual visible.

### Recorder selection retained the superseded scorer

**Symptom.** Reports used the corrected July reward module, but
`record_books.py --rank-by density` still calculated candidate density from a
private copy of the February best-bid formula.

**Mechanism.** The recorder intentionally duplicated the old scoring helper so
analysis changes could not break capture. Versioning the governing rule made
that safety argument backwards: the duplicate silently selected a different
market sample even though stored books remained raw.

**Fix.** Candidate ranking now calls the pure, network-free current rule module
and prints its source banner when capture starts. The recorder still stores
unaltered venue JSON.

**Verification.** A hand fixture that scores 60 under July and 35 under
February now asserts the recorder returns 60. The full measurement suite passes.

---

## 2026-08-27

### One transient TLS EOF ended the intended 14-day capture

**Symptom.** The isolated server recorder ended after 9h51m. Its SQLite run was
closed cleanly and contained zero recorded errors, while the log ended with
`urllib.error.URLError` wrapping an SSL EOF.

**Mechanism.** `get_json()` converted HTTP error responses into data but caught
no connection, TLS, timeout, or invalid-JSON exception. The outer `finally`
flushed and closed SQLite, but the transient transport failure still terminated
the process. Because failure occurred before an HTTP response, no status row
was available for the caller to record.

**Fix.** Public GETs now retry three times with 1s/2s bounded backoff. If every
attempt fails, `get_json()` returns local sentinel status 599 and the existing
caller records the missing observation instead of ending the run. It still
does not retry venue HTTP statuses or any write operation; no write endpoint
exists.

**Verification.** One fixture fails once then succeeds and asserts two limiter
calls plus one backoff. A second exhausts all attempts and asserts status 599,
three limiter calls, and two backoffs. All 27 tests pass locally and on the
server, the module compiles, and exact commit `b970654` passed the endpoint
scan. R3 then encountered a real connection-reset `URLError` at 2026-08-28
10:27:03 UTC on attempt 1/3. It recovered without a restart or traceback and
continued writing fresh books through at least 12:58 UTC, with zero recorded
errors and zero non-200 book rows. Real-failure survival is now verified.
