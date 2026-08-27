# Current status

Last verified: 2026-08-26 (America/New_York).

## Executive state

**Phase:** measurement and model correction.

**Objective:** determine whether the Polymarket US liquidity-reward strategy has
a conservatively positive net expectancy on Kalshi before building a full bot.

**Current verdict:** promising but unproven. Existing Kalshi replays show enough
nominal reward to justify better measurement, but they do not establish live
profitability.

**Canonical repository:** `https://github.com/rynn-arriola/kalshi-bot.git`.
Credentials and captured market data remain ignored and local-only.

**Live state:** no Kalshi strategy order has ever been placed by this project.
There is no production bot, deployment, scheduler, reconciler, or authorized
write path.

## What is verified now

- The Polymarket US reference strategy was profitable under its six-day
  balanced-leg report for 2026-08-20 through 2026-08-25: trading
  `-$31.16/day`, venue reward `+$85.56/day`, reported net `+$54.40/day`.
- The reward rows were reproduced from the live venue earnings endpoint. The
  trading report is partial accounting: it excludes unbalanced markets and
  cannot allocate positions that settle instead of closing.
- Both venues reward resting size through a discounted, normalized share of
  qualifying book liquidity. The exact rule is **not currently safe to call
  identical**; see the blocker below.
- The existing capture and replay instruments run and reproduce their published
  tables. Reproducible output does not validate an outdated rule or a biased
  counterfactual.
- On thin books, adding size has diminishing marginal reward because our own
  score enters the denominator. This is arithmetic. The portfolio-level optimum
  has not been measured on a fixed universe.

## Active blockers

### B1 — Kalshi rule-source conflict (critical)

The February 2026 CFTC filing used by the code sets the highest bid as Reference
Price. Kalshi's current Help Center describes Reference Price as the first level
where cumulative size reaches one fifth of Target Size. The current Help Center
also says excluded snapshots reduce the payable pool.

`scripts/analyze_capture.py` uses the highest bid, and `scripts/net_sizing.py`
does not scale the pool by the fraction of non-excluded snapshots. Until this is
resolved or both interpretations are implemented as bounds, Kalshi reward-dollar
estimates are **INFERRED under a disputed model**, not verified economics.

### B2 — Adverse selection is not represented credibly (critical)

The Kalshi exit replay largely prices the exit against the book at fill time.
The Polymarket reference shows that the adverse move before exit is the dominant
loss term. A static book can measure fees and immediate depth while missing the
cost that decides profitability.

### B3 — Sizing sweep is not like-for-like

The published sizes fund different market portfolios under a fixed capital cap
and changing guards. The monotonic decline in aggregate reward per resting
contract is suggestive, but it does not establish an optimum near ten contracts.
A fixed-universe, per-market marginal curve is required.

### B4 — No payout calibration on Kalshi

`period_reward / 10_000` is strongly corroborated but has not been reconciled to
an actual strategy payout. The minimum is per individual program according to
current Kalshi help. A live experiment must be sized to clear it conservatively.

### B5 — No live Kalshi fill/exit sample

Maker fees, qualification uptime, queue position, fill rate, competitor
reaction, actual exit cost, and realized reward remain unobserved for this
strategy on Kalshi.

## Existing evidence, bounded correctly

- `capture_long.db`: density-selected capture used for the newest replay. It is
  short relative to many program periods and assumes captured competition is
  representative later.
- `net_sizing.py`: integrates reward interruption and simulated fills on one
  clock. It is still static-book, gross of maker fees (which remain
  unconfirmed), and affected by B1–B3.
- The size table in `FINDINGS.md` section 18 is a faithful report of the current
  script. Its `%/day` column includes simulated markout as well as reward and
  must not be described as reward return on collateral.
- The hypothesis that Polymarket's reward jump was caused by the listed August
  25 uptime fixes is unproven; the reward increase began on August 23–24.

## Current scope boundary

Approved now:

- Repair and test measurement instruments.
- Re-run read-only analysis and produce conservative bounds.
- Run verified read-only measurement on the existing server under the isolated
  boundaries in `docs/SERVER_MEASUREMENT.md`.
- Design a minimal one-market evidence probe and its safety case on paper.

Not approved now:

- Full Kalshi bot implementation.
- Live order code or authenticated write endpoints.
- Deployment, capital allocation, market selection for a live run, or an arming
  command.

The active work order is `NEXT.md`. Operator authority is in `DECISIONS.md`.
