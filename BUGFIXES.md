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
