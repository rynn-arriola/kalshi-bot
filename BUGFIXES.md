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
