# kalshi-bot

AI-maintained research to determine whether the working Polymarket US
liquidity-reward strategy can operate profitably on Kalshi.

**This is a measurement project. There is no Kalshi bot, and building the full
bot is not currently approved.**

The operator owns strategy, capital, risk, deployment, live-action, and scope
decisions. AI agents maintain the research, instruments, tests, and continuity
documents.

## Start every session here

| Order | File | Purpose |
|---:|---|---|
| 1 | `AGENTS.md` | AI operating contract and operator authority |
| 2 | `STATUS.md` | Current truth, blockers, and scope |
| 3 | `DECISIONS.md` | Accepted operator decisions |
| 4 | `NEXT.md` | Ordered active work queue |
| 5 | `EXPERIMENT.md` | Measurement stages and evidence gates |
| 6 | `BUILT.md` | What already exists and its verification state |
| 7 | `FINDINGS.md` | Durable evidence and corrections |

`docs/PLAN.md` is the historical full-build design. It is paused and is not the
active work queue.

## Current conclusion

Kalshi is **promising but unproven**. Existing replays show nominal headroom,
but the reward implementation conflicts with Kalshi's current help
documentation, the sizing sweep is not fixed-universe, and adverse selection is
not modeled credibly enough to establish live net profitability.

See `STATUS.md` for the bounded version of every current claim.

## Relationship to liquidity-bot

`D:\polybot\liquidity-bot` is the working Polymarket US reference strategy.
This project may reuse its venue-independent safety and accounting concepts.
Its calibrations—market selection, quote size, qualification behavior, queue,
fill hazard, exit timing, and fees—are hypotheses on Kalshi until re-measured.

The reference repository is read-only from this project.

## Existing read-only instruments

Nothing in `scripts/` is authorized to place an order.

| Script | Purpose |
|---|---|
| `record_books.py` | Store raw programs, books, trades, and status |
| `kalshi_auth.py` | Signed read-only account access |
| `analyze_capture.py` | Replay a specified reward interpretation |
| `markout.py` | Estimate fill incidence and post-fill markout |
| `sizing.py` | Reward-only portfolio replay |
| `pooled_markout.py` | Sign test and bootstrap on one-sided fills |
| `net_sizing.py` | Reward interruption and fills on one clock |
| `exit_cost.py` | Simulated exit path and fee/depth cost |

These scripts reproduce prior results, but several require correction before
their dollar outputs can drive a decision. Reproducibility is not validation;
see `STATUS.md` blockers B1–B3.

## Data and credentials

`.env`, private keys, and `data/` are gitignored. Do not display secret values.
Before broad staging, verify:

```powershell
git check-ignore -v kalshi-bot.txt .env data/capture.db
```

Environment variables take precedence over `.env`.
