# Archived Claude instructions — September 19, 2026

Historical text below is preserved, not active authority. Follow the current
[AI operator contract](../../AI_OPERATOR.md) and accepted decisions instead.

# kalshi-bot — compatibility entry point

**Read `AGENTS.md` first.** It is the authoritative AI operating contract and
boot sequence. Then read `STATUS.md`, `DECISIONS.md`, `NEXT.md`, and
`EXPERIMENT.md` in that order.

If older instructions below conflict with those files, follow `AGENTS.md` and
the accepted operator decisions. The detail below is retained for historical
context and venue-specific safety reminders.

# Historical project instructions

Research toward a Kalshi liquidity-incentive market maker. **There is no bot
here yet, and that is deliberate.**

## Navigation

The current boot sequence is at the top of this file and in `AGENTS.md`.
`docs/PLAN.md` is a paused historical design, not an approved active plan.

## Standing rules

**Anything critical we establish goes into `FINDINGS.md` immediately** — not at
the end of a session, not "if it comes up again". Every bug that reaches a
running instrument gets a `BUGFIXES.md` entry when fixed, with symptom,
mechanism and fix. Inherited from `D:\polybot\liquidity-bot`, where the cost of
not doing this was measured in re-researched questions.

**Do not build ahead of the data.** Several numbers the economics depend on are
still inferred — the `period_reward` scale above all. Code written now bakes
them in permanently. Raw capture stores venue JSON uninterpreted so analysis can
be re-run as understanding improves; a book we failed to record is gone.

**Record what is unresolved as unresolved.** `revenue: 0` on a settled position
that should have paid $14.91 is written down rather than explained away, because
liquidity-bot's loss stop once returned +3.26 on a trade that lost $1.55 by
reading a field nobody had verified.

## Hard constraints

**Claude does not place orders.** Executing a trade is the operator's action.
Claude prepares the command with every parameter fixed and printed for review,
and analyses the result. `scripts/kalshi_auth.py` signs reads only and has no
code path to an order endpoint — keep it that way.

**Credentials.** `.env` holds `KALSHI_API_KEY_ID`; `kalshi-bot.txt` is an RSA
private key PEM. Both are gitignored along with `data/`. Verify before any
`git add -A`:

```bash
git check-ignore -v kalshi-bot.txt .env data/capture.db
```

**`D:\polybot\liquidity-bot` is never modified by this project.** It is the
Polymarket reference implementation, currently with a red readiness gate and an
open P&L bug. Portable modules are copied, not shared — a defect in shared code
would break both.

## The one thing most likely to be got wrong

Kalshi has no short. Selling YES is executed as **buying NO**, and the order and
fill records disagree about `side` for the same trade. Never derive direction
from `action`/`side`; reduce everything to a signed YES-equivalent using the
explicit `yes_price_dollars`/`no_price_dollars` pair, which always sums to 1.00.
See `FINDINGS.md` section 6f.
