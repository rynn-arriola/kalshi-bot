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

## Still unknown, and blocking

1. **`period_reward` scale.** Every dollar figure depends on it. Four candidate
   endpoints 404'd, and integer money elsewhere in the API is *cents*, which
   cannot be true here without breaking the filing's $1,000/day cap. Probably
   needs an actual payout.
2. **Maker fee rate.** Both fills on this account were `is_taker: true`. One
   resting fill settles it — `fee_cost` and `is_taker` are per-fill.
3. **`revenue: 0` on a settled position that should have paid $14.91.** Do not
   build a P&L breaker until this reconciles.
4. **Post-only support.** Structural: without it there is no venue primitive for
   a building quote.

## What already exists

See `BUILT.md` for the full inventory. In short: three working instruments
(`record_books.py`, `kalshi_auth.py`, `analyze_capture.py`) and the docs. No
package, no bot code, no tests, no order has ever been placed.

## What is running

A capture may be in progress. Check and stop:

```bash
python -c "import sqlite3;c=sqlite3.connect('file:data/capture.db?mode=ro',uri=True);print(c.execute('SELECT COUNT(*) FROM books').fetchone())"
powershell -Command "Get-Process python | Stop-Process -Force"
```

Captures write to `data/capture.db` (gitignored). Books cannot be recorded
retroactively; trades and 1-minute candlesticks **can** be backfilled.

## Next actions, in order

1. Finish the two-sided spread analysis: measure `1 - (yes_touch + no_touch)`
   across captured books. If both quoted sides fill, that difference is locked
   profit — this is the actual market-making trade, with reward as a bonus.
2. Markout from the backfilled trades at 60/300/900s, to find whether adverse
   selection swamps the reward.
3. Check whether reward concentrates near a program's `end_date`, the analogue
   of liquidity-bot's measured 6h -> 2h narrowing.
4. Only then: the one-contract evidence run, which **the operator arms**. Claude
   prepares the command and analyses the result but does not place orders.

## Decisions already taken

- Copy portable modules from liquidity-bot rather than extracting a shared
  library. liquidity-bot is never modified.
- The Polymarket P&L bug is noted as a design lesson, not a blocker.
- Raw capture stores venue JSON uninterpreted, so analysis can be re-run as
  understanding improves rather than re-collected.
- Scope stops at measurement plus a one-contract run. Execution architecture is
  re-planned once real data exists.
