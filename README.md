# kalshi-bot

Research toward a Kalshi liquidity-incentive market maker.

**There is no bot here yet, and that is deliberate.** This repository currently
contains measurement instruments and the facts they produced. Code that encodes
a strategy is not written until the facts it would depend on are confirmed.

## Read these in order

| file | what it is |
|---|---|
| `NEXT.md` | **Start here.** Current state, what is running, what to do next. |
| `BUILT.md` | Inventory of what exists, what it does, and how it was verified. |
| `FINDINGS.md` | Established facts, each with the measurement that produced it. |
| `docs/PLAN.md` | The approved end-to-end plan. |
| `BUGFIXES.md` | Bugs that reached a running instrument: symptom, mechanism, fix. |

Standing rule, inherited from `D:\polybot\liquidity-bot`: **anything critical we
establish goes into `FINDINGS.md` immediately** — not at the end of a session, not
"if it comes up again". A fact that has to be re-derived costs hours and usually
comes back wrong the second time.

## Relationship to liquidity-bot

`D:\polybot\liquidity-bot` is a working Polymarket US liquidity-reward market
maker and the reference implementation for this project. Its 63 safety invariants
are venue-independent and are the main thing being carried across.

Its *calibrations* are not. `fill_hazard.py`, the 900-second passive wait, the
2-cent spread rule and the pre-kickoff flatten are all Polymarket measurements
and are invalid here until re-measured.

**liquidity-bot is never modified by this project.** The decision was to copy
rather than extract a shared library, because it has a red readiness gate and an
open P&L bug, and shared code would mean a defect in either breaking both.

## Instruments

Nothing in `scripts/` places an order. `kalshi_auth.py` signs reads only and has
no code path to an order endpoint.

| script | what it answers |
|---|---|
| `record_books.py` | raw capture; stores exact venue JSON and interprets nothing |
| `kalshi_auth.py` | signed read-only account access |
| `analyze_capture.py` | replays Kalshi's reward formula over captured books |
| `markout.py` | fill rates and markout for a resting two-sided quote |
| `sizing.py` | reward-only revenue estimate, with the $1.00 minimum applied |
| `pooled_markout.py` | sign test and bootstrap CI on one-sided fill cost |
| `net_sizing.py` | reward and fills on **one clock** — the integrated number |

```bash
# Raw capture, ranked by measured reward density (see FINDINGS 11).
python -B scripts/record_books.py --minutes 1440 --markets 250 --interval 60 --rps 20 --database data/capture_long.db

# The integrated economics: reward and fill cost simulated together.
python -B scripts/net_sizing.py --size 25 --fill-model partial
```

## Credentials

`.env` holds `KALSHI_API_KEY_ID`, and `KALSHI_PRIVATE_KEY_FILE` points at an RSA
private key PEM. Both are gitignored, along with `data/`. Verify before any
`git add -A`:

```bash
git check-ignore -v kalshi-bot.txt .env data/capture.db
```

Environment variables take precedence over `.env`.
