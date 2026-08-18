# Where we are

Last updated 2026-08-17.

## One-paragraph orientation

Kalshi runs a self-serve Liquidity Incentive Program whose scoring formula is
`DiscountFactor^ticks x size` — the same formula `liquidity-bot/rewards.py`
already implements. The venue is materially better than Polymarket on the levers
that matter (roughly 10x the addressable universe, 5-15x lower qualification bar,
every program carrying an explicit clock). We are **collecting data, not building
a bot**, because several numbers the economics depend on are still inferred
rather than measured. No capital has been committed and no order has been placed.

## Confirmed so far

- Reward formula and the two-sided snapshot rule — from the CFTC filing, verbatim.
- **Taker fee**: `ceil(0.07 x C x P x (1-P) x 10000) / 10000`, proven against two
  real fills on this account.
- **Rate limits**: reads refill at 200/s (bucket 600), writes 100/s. Roughly 50x
  what liquidity-bot is architected around.
- **Two-sided rate: 85%** of snapshots across 40 markets — far better than the
  ~60% an 8-market sample suggested.
- **One tick inside the touch doubles the reward share**: median 1.987x over
  6,438 observations, p10 1.916, p90 1.999. The effect is `1/DiscountFactor` and
  DF is 0.50 in 99.96% of live programs.
- **There is no short.** Selling YES is executed as buying NO, and the order and
  fill records disagree about `side` for the same trade. See FINDINGS 6f.
- **The pair trade is not a revenue source.** Both sides filled nets a median
  $0.0379 on 5 contracts (6g), but completion is **0.7%** — 7 times in 1,064
  windows. 64.3% of hours see no trade at all and only 8.6% see both directions
  trade, which caps completion before price or queue matters. See FINDINGS 6h.
  **Reward is the only established revenue source.** (An earlier "zero times"
  from 140 windows was a sampling limit read as a fact — 6h records why.)
- **One-sided fills are adverse, and the drag is bounded.** Sign test
  p=0.0014 at 300s, mean −$0.1271 per fill at 5 contracts, 95% CI
  [−$0.2374, −$0.0369]. See FINDINGS 6i. This was the blocker; it is cleared.
- **Simulated together rather than added, net is $10–$26/day** at 25 contracts
  on $300 across 12 markets — roughly **40% below** what adding the reward and
  drag lines gave. Reward and fills were computed under contradictory
  assumptions; `net_sizing.py` runs them on one clock. See FINDINGS 10.
  **The dominant uncertainty is now the post-fill policy** (`flatten-seconds`),
  which spans the answer by 2.6x and is a design choice, not a market property.

## The largest lever found so far, not yet pulled

**The capture has been ranking markets by a metric anti-correlated with
revenue.** `reward/target` scores Spearman −0.150 against replayed $/day; its
top 12 markets earn $24.39/day where `reward/denominator` earns $158.61/day —
roughly **6.5x**, larger than any size, breadth or policy lever measured. The
denominator is stable enough to rank on (+0.818 first half to second half),
which closes open question 6. See FINDINGS 11.

**Nothing captured so far was selected well.** That does not invalidate the
measurements — share, drag and markout are all replayed per market — but it
means the 12 markets in every economics table are drawn from a badly chosen
pool, and the real top 12 has not been looked at yet.

## What is running now

**A 24h density-ranked capture into `data/capture_long.db`**, started
2026-08-18 18:26Z, 250 markets at 60s. First capture to use measured reward
density and the two-sided gate for selection, sticky tickers, terminal-state
program polling and change-only program storage. Ends ~18:26Z on 08-19.

## Still unknown, and blocking

1. ~~**`period_reward` scale.**~~ **Largely resolved 2026-08-17** — the 1e-4
   scale is corroborated across 2,940 programs: all 19 distinct values are
   clean dollars except `1000/7` and `1000/3`, the max is exactly the $1,000
   cap, and no market-day breaches it. Median pool is **$1.10/day per market**.
   Still wants a real payout to confirm, but it no longer blocks sizing or
   economics. See FINDINGS section 3.
2. ~~**What a fill costs in LOST REWARD.**~~ **Largely answered.** FINDINGS 10
   simulates reward and fills on one clock: uptime stays 88-100%, so the
   interruption is small; net is $10-$26/day. FINDINGS 12 then measured the
   exit: **92% of exits must cross**, at −$0.28 each, ~−$10/day — consistent
   with section 10's drag by an independent path. What remains is that the
   cross is priced at fill time rather than at deadline, which understates it.
3. **What a fill costs in LOST REWARD — superseded, kept for the trail.** 6i measured
   the markout half of the cost of being filled and it does not erase the
   revenue at 25 contracts. The other half is unmeasured and structurally
   larger: section 2's two-sided rule means pulling our quotes after a fill
   zeroes the snapshot on **both** sides, so a fill costs markout *and* the
   reward stream for as long as flattening takes. Answered by open question 3
   — must our own orders be on both sides, or merely *someone's*? Replayable
   against books already captured; needs no new data.
3. **Maker fee rate.** Both fills on this account were `is_taker: true`. One
   resting fill settles it — `fee_cost` and `is_taker` are per-fill.
4. **`revenue: 0` on a settled position that should have paid $14.91.** Do not
   build a P&L breaker until this reconciles.
5. **Post-only support.** Structural: without it there is no venue primitive for
   a building quote.

## What already exists

See `BUILT.md` for the full inventory. In short: six working instruments
(`record_books.py`, `kalshi_auth.py`, `analyze_capture.py`, `markout.py`,
`sizing.py`, `pooled_markout.py`) and the docs, plus `docs/REFERENCE_CRITIQUE.md` on what ports from
liquidity-bot. No package, no bot code, no tests, no order has ever been placed.

## What is running

**Two captures were started 2026-08-17. One is still running; one died.**
They write to separate database files on purpose — SQLite is in WAL mode, which
allows many readers but one writer, so a second capture into the same file
would have fought the first.

| database | markets | interval | started | purpose |
|---|---|---|---|---|
| `data/capture.db` | 40 | 15s | 17:15Z | **running**, ends 03:15Z; the original slate |
| `data/capture_wide.db` | 150 | 60s | 18:50Z | **DIED 23:07:58Z** at 4h17m of 10h |

The wide run was killed from outside the process — `capture_runs.ended_at` is
still NULL and the `errors` table is empty, so it neither finished nor caught a
failure. No log survived; the likely cause is the shell that launched it being
closed. Its data is intact (38,689 books, 214 markets, 543 market-hours, all
HTTP 200) and 6i is measured on it, so **nothing was lost except the hours it
did not run.**

The wide run existed to raise the one-sided fill count, and **that premise was
wrong** — see FINDINGS 6i. More markets made the sample quieter, not busier,
because `reward/target` ranking selects thin books. The sign was settled by
changing the statistic instead. **Restarting it is optional now**, and buys
tighter intervals rather than a blocked answer.

Check either, and stop everything:

```bash
python -c "import sqlite3;c=sqlite3.connect('file:data/capture_wide.db?mode=ro',uri=True);print(c.execute('SELECT COUNT(*) FROM books').fetchone())"
powershell -Command "Get-Process python | Stop-Process -Force"
```

Analysis scripts all take `--database`, so run them against either file. There
is **no merge step written yet** — if the two need pooling for one markout
sample, that is a small job and nobody has done it.

`--rps` is capped at 20 inside `record_books.py` and a request for 40 is
refused outright. That bound is deliberate (the venue allows 200/s); two
captures at 20 sit at 40/s, still 5x under. **Do not raise it to go faster.**

Captures are gitignored. Books cannot be recorded retroactively; trades and
1-minute candlesticks **can** be backfilled.

## Next actions, in order

1. ~~Two-sided spread analysis~~ **done** — FINDINGS 6g.
2. ~~Fill rates and markout~~ **done** — FINDINGS 6h, `scripts/markout.py`. The
   pair never completed in 140 market-hours, which resolved 6g's policy
   conflict by removing its premise: **quote one tick inside**, because there
   is no realised spread edge to give up and it doubles reward share. One-sided
   markout is negative but n=14 cannot establish its sign — left unresolved on
   purpose.
3. ~~Sizing~~ **done** — FINDINGS 9, `scripts/sizing.py`. Roughly **$24/day
   GROSS at 25 contracts on $243 of collateral**, capacity-limited and
   saturating above that.
4. **Bound the cost of being filled. This is the critical path.** The gross
   figure is not the business: applying 6h's measured fill rate and markout
   gives a drag of $2.88–$18.94/day at 25 contracts, so net is somewhere
   between $21/day and $5/day, and at 100 contracts the mean case is
   *negative*. Pool, share and scale are all measured now; the fill cost is
   not, and it is large enough to erase the revenue. It needs enough one-sided
   fills to establish the sign — currently n=17. Two known omissions both make
   it worse: partial fills are not counted, and a fill zeroes reward accrual on
   **both** sides under the two-sided rule (section 2).

   **Checked against the live reference 2026-08-17 and it argues the
   pessimistic end.** liquidity-bot planned for trading losses at 5% of reward
   and is now **loss-making**: reward $20.25 against trading −$27.58 on
   2026-08-16, break-even at best all-time, with crossed exits costing 4x
   passive ones. See `docs/REFERENCE_CRITIQUE.md` 4e. **Its exit cost is the
   thing we have not modelled at all** — our markout measures adverse
   selection, not what it costs to get out — and on thin Kalshi books that is
   the number most likely to be worse than theirs, not better.
5. **Widen the sample**, which is the same work as 4 by another route. Both 6h
   and 9 rest on 44 politics/economics markets and ~14 hours of books; only 10
   markets survived sizing's guards, at 10-25% period coverage. Sports are
   absent entirely and are where liquidity-bot's reference measurement lives.
6. Check whether reward concentrates near a program's `end_date`, the analogue
   of liquidity-bot's measured 6h -> 2h narrowing. Cheaper than it was —
   every program row carries `start_date`/`end_date`, and 1,048 of 2,940 run
   14-day periods.
7. Only then: the evidence run, which **the operator arms**. Claude prepares the
   command and analyses the result but does not place orders. **Not at one
   contract** — FINDINGS 9 shows that pays $0.00 on 9 of 10 markets because the
   $1.00 minimum forfeits it, so a one-contract run confirms nothing. Size it
   from the program's pool and period.

## Decisions already taken

- Copy portable modules from liquidity-bot rather than extracting a shared
  library. liquidity-bot is never modified.
- The Polymarket P&L bug is noted as a design lesson, not a blocker.
- Raw capture stores venue JSON uninterpreted, so analysis can be re-run as
  understanding improves rather than re-collected.
- Scope stops at measurement plus a small evidence run. Execution architecture
  is re-planned once real data exists. **Amended 2026-08-17:** the run is no
  longer "one contract" — FINDINGS 9 shows one contract is forfeited by the
  $1.00 minimum on 9 of 10 markets and would confirm nothing. Size it from the
  program.
