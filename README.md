# kalshi-bot

Active Windows folder: `C:/Users/rynna/Bots/kalshi` (D-029), beside Polymarket
and outside OneDrive. The old OneDrive project location is no longer active.
This folder tracks the [canonical GitHub repository](https://github.com/rynn-arriola/kalshi-bot)
on `master`; see [publication record](docs/GITHUB_PUBLICATION.md).

**AI operators:** begin with [AI_OPERATOR.md](AI_OPERATOR.md), then follow its
required routing. AGENTS/CLAUDE are compatibility pointers, not separate rules.
Permanent requirements: [AI_ENGINEERING.md](AI_ENGINEERING.md).
Design: [WebSocket-first architecture](docs/ARCHITECTURE.md).
Documentation layout: [Polymarket-derived structure](docs/DOCUMENTATION_STRUCTURE.md).

**Current phase (2026-09-20): Windows-native implementation, D-021.** The first
tested foundation is in `src/kalshi_bot`; see
[initial foundation](docs/BUILD_FOUNDATION.md) and the newer
[account-I/O milestone](docs/BUILD_ACCOUNT_IO.md), followed by
[owned orders and recovery evidence](docs/BUILD_RECOVERY_ORDERS.md), then
[event/command and quote/ranking components](docs/BUILD_ENGINE_RANKING.md)
(280 passing tests). It is not yet a complete
or live-ready trader. No paper trading, live launch or exchange writes occurred.

```powershell
.\.venv\Scripts\python.exe -B -m kalshi_bot policy
.\scripts\Get-BotPreflight.ps1
.\scripts\Test-Bot.ps1
```

Preflight deliberately reports not ready (exit 2), without keys or network access.

Start API work with [the complete local API reference](docs/KALSHI_API_REFERENCE.md).
It contains the dated official REST/WebSocket contracts, FIX tables, examples,
and implementation notes, with [a coverage audit](docs/API_REFERENCE_AUDIT.json).
Read `DECISIONS.md` for the $500 ceiling, 10-contract entries, 30 resting-entry
maximum and percentage-based six-hour realized-loss caps.

Current strategy research: [liquidity rules, reward APIs and live public-data
findings](docs/LIQUIDITY_REWARD_RESEARCH.md). This includes the per-program $1
minimum, Reference Price/cutoff mechanics, current competition, and API gaps.

AI-maintained research to determine whether the working Polymarket US
liquidity-reward strategy can operate profitably on Kalshi.

Historical measurement instruments remain intact. D-021 authorizes building
the bot; deployment and live execution still require separate authorization.

The operator owns strategy, capital, risk, deployment, live-action, and scope
decisions. AI agents maintain the research, instruments, tests, and continuity
documents.

## Start every session here

| Order | File | Purpose |
|---:|---|---|
| 1 | `AI_OPERATOR.md` | Single AI operating contract and authority |
| 2 | `STATUS.md` | Current truth, blockers, and scope |
| 3 | `DECISIONS.md` | Accepted operator decisions |
| 4 | `NEXT.md` | Ordered active work queue |
| 5 | `AI_ENGINEERING.md`, `docs/ARCHITECTURE.md` | Permanent design rules and architecture |
| 6 | `BUILT.md` | What already exists and its verification state |
| 7 | `FINDINGS.md` | Durable evidence and corrections |

`docs/PLAN.md` is the historical full-build design. It is paused and is not the
active work queue.
`EXPERIMENT.md` is historical methodology, not a request for more paper testing.

## Historical research conclusion — not live acceptance

Kalshi is **promising but unproven**. The current reward rule is now reconciled
and implemented, but the sizing sweep is not fixed-universe and corrected exit
losses are not yet integrated tightly enough to establish live net
profitability.

See `STATUS.md` for the bounded version of every current claim.

## Relationship to liquidity-bot

`C:/Users/rynna/Bots/liquidity-bot` is the verified Polymarket US reference.
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
| `reward_rules.py` | Pure, versioned reward scoring and payout arithmetic |
| `strategy_policy.py` | Audited current Polymarket entry-price policy |
| `analyze_capture.py` | Replay a specified reward interpretation |
| `markout.py` | Estimate fill incidence and post-fill markout |
| `sizing.py` | Reward-only portfolio replay |
| `pooled_markout.py` | Sign test and bootstrap on one-sided fills |
| `net_sizing.py` | Reward interruption and fills on one clock |
| `exit_cost.py` | Later-book passive/cross/settlement exit-loss replay |

These scripts produce measurements, but the fixed-universe net replay is not
complete. Reproducibility is not validation; see `STATUS.md` blockers B2–B5 and
the accounting contract in `docs/PNL_ACCOUNTING.md`.

## Data and credentials

`.env`, private keys, and `data/` are gitignored. Do not display secret values.
Before broad staging, verify:

```powershell
git check-ignore -v kalshi-bot.txt .env data/capture.db
```

Environment variables take precedence over `.env`.
