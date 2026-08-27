# Current Polymarket reference strategy

Audited read-only: 2026-08-26.

This file owns the exact source version and behavior that the Kalshi
measurement calls "the Polymarket strategy." It prevents an old report or chat
summary from silently becoming the reference.

## Version proof

- Repository: `D:\polybot\liquidity-bot`
- Branch: `main`
- Local/GitHub HEAD: `3134678e9937881a4b890c500fd905efb28abad6`
- Commit time: 2026-08-26 20:49:23 ET
- Working tree: clean at audit
- GitHub `refs/heads/main`: exact same hash, checked with read-only
  `git ls-remote`
- Strategy files at HEAD are byte-identical in Git to reviewed deployed source
  `5825db8`:
  - `src/liquidity_bot/commissioning.py`
  - `src/liquidity_bot/market_selector.py`
  - `src/liquidity_bot/reconciler.py`
  - `src/liquidity_bot/rewards.py`

No Polymarket API call, server mutation, process action, or source modification
was made for this audit.

## Current strategy behavior

| Behavior | Current source truth | Kalshi measurement consequence |
|---|---|---|
| Quote size | 10 contracts | Primary transfer size is 10; size sweep remains diagnostic |
| Capacity | 20 market slots | Measure breadth separately from depth |
| Universe | Sports moneylines with active `day_of` incentives | Exact-transfer result must not silently use every Kalshi category |
| Entry horizon | Six hours before event | Time-split/filter must print its Kalshi analogue |
| Entry pricing | New selection requires at least 2¢ and joins the touches; if an already-bound book tightens, center an exact 2¢ window | Default policy is `polymarket-current`, not one-tick-inside |
| Entry price band | Refuse prices outside 10¢–90¢ | Fixed-universe replay must apply the side-specific filter |
| Entry order | Post-only | Historical fill replay assumes maker entry; no live path is built |
| Reward qualification | Proposed size counts toward Target Size and must remain inside the venue cutoff | Use Kalshi's current July scorer, not Polymarket's reward formula |
| Reward-vs-cost gate | Advisory/off | Do not reject solely because the old projected EV gate is negative |
| Exit-depth gate | Requires a stressed complete close before opening risk | Report capacity/unknown exits; do not pretend thin residuals are flat |
| On fill | Cancel the risk-building side and work a passive reducing order | Reward stops while inventory is open; model one-sided position economics |
| Passive exit | At touch, or one tick better only if it does not lock in extra loss | Keep separate from entry quote pricing |
| Forced exit | IOC after 900 seconds; event deadline overrides at T−300s | Sweep 900s and map event deadlines explicitly |
| Settlement | Must not intentionally hold through event settlement | Unknown historical exits need a worst-case bound |

The strategy can quote one eligible side when the other is blocked. A
two-orders-at-all-times simplification is therefore not exact.

## What is venue-specific

Do not copy the Polymarket reward arithmetic into Kalshi. Polymarket's current
scorer measures ticks from its best price, while Kalshi's July 2026 rule sets a
reference at one fifth of Target Size and scales payout for excluded snapshots.
The transferable strategy is the selection/quoting/inventory policy; venue
reward calculation, fee schedule, price grid, market lifecycle, and settlement
API remain Kalshi-specific.

## Remaining fidelity gaps

`scripts/strategy_policy.py` now reproduces the current entry-price rule and
prints the audited commit. Wide, tight, locked, and half-cent fixtures were
compared directly to the current reference function and matched exactly. The
fixed-universe replay still must add:

1. sports/day-of exact-transfer universe versus a separately labeled
   all-category Kalshi adaptation;
2. side-specific 10¢–90¢ entry filtering;
3. stressed complete-exit admission;
4. one-sided quoting when only one side qualifies;
5. the event-relative six-hour and T−300-second clocks;
6. the later-book 900-second exit path in the same reward clock.

Until those are integrated, current script output is component measurement,
not an exact whole-strategy profitability result.
