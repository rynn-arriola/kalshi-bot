# Current status

Last verified: 2026-08-27 06:50 (America/New_York).

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

**Measurement state:** a 14-day read-only Kalshi capture is active on the
existing server in the isolated `/root/kalshi-bot` project at commit
`c13524201819c3f771b9b8193e168a9ae85e1372`. It started
2026-08-27 02:35:41 UTC and is scheduled through 2026-09-10 02:35 UTC, with a
seven-day checkpoint on 2026-09-03. The transient unit is
`kalshi-readonly-capture-14d`; its database is
`data/shadow-14d-20260827.db` and log is `logs/capture-20260827.log`.
At the eight-hour checkpoint the unit remained active with zero restarts.

## What is verified now

- The Polymarket US reference strategy was profitable under its six-day
  balanced-leg report for 2026-08-20 through 2026-08-25: trading
  `-$31.16/day`, venue reward `+$85.56/day`, reported net `+$54.40/day`.
- The reward rows were reproduced from the live venue earnings endpoint. The
  trading report is partial accounting: it excludes unbalanced markets and
  cannot allocate positions that settle instead of closing.
- The current reference code was re-audited without a Polymarket API call.
  Local/GitHub `main` match at `3134678`; its strategy files match reviewed
  deployed source `5825db8`. Exact behavior is versioned in
  `docs/POLYMARKET_REFERENCE.md`.
- Both venues reward resting size through a discounted, normalized share of
  qualifying book liquidity, but their implementations are not identical.
- Kalshi's July 15 certified filing, effective July 30, governs the August
  capture. It uses the one-fifth-of-Target-Size reference and scales the pool by
  the non-excluded snapshot fraction. The current Help Center agrees.
- On `capture_long.db` at size 10, the current rule gives a median one-tick
  reward-share multiple of `1.000x` over 112,492 side observations. The
  superseded February mode gives `1.943x`; prior "inside doubles reward" claims
  are superseded for this dataset.
- The existing capture and replay instruments run and reproduce their published
  tables. Reproducible output does not validate an outdated rule or a biased
  counterfactual.
- The isolated server recorder passed all 25 tests and a two-minute public-API
  canary before the long run. The canary recorded 65 book rows across 50
  candidate markets with zero HTTP failures, zero recorded errors, and a valid
  SQLite integrity check. The Polymarket supervisor/trader PIDs and start times
  were unchanged before and after it.
- At 2026-08-27 10:49 UTC, the long run contained 41,501 book rows, 5,241
  trades, 17,597 program rows, zero non-200 books, and zero recorded errors.
  The latest book was 30 seconds old and all 75 actively tracked tickers had
  books in the preceding five minutes.
- Server capacity is adequate for the two current processes: 461 MB memory was
  available, Kalshi used 105 MB with a 113 MB peak under its 256 MB cap, load
  averages were 0.00/0.03/0.00 on one core, no OOM event was recorded, and
  19.4 GB disk remained free. Linear capture growth projects to roughly 2.4 GB
  over 14 days, so no upgrade is currently indicated.
- The Polymarket supervisor and trader were restarted at 2026-08-27 04:02:57
  UTC after the launch check. Kalshi stayed active, no OOM event occurred, and
  host load was low at inspection. The cause of the Polymarket restart is
  **UNKNOWN**; do not attribute it to Kalshi without evidence.
- On thin books, adding size has diminishing marginal reward because our own
  score enters the denominator. This is arithmetic. The portfolio-level optimum
  has not been measured on a fixed universe.

## Active blockers

### B2 — Adverse selection is not represented credibly (critical)

`exit_cost.py` now prices against the first usable book at or after the exit
deadline and carries missing/thin books as unknown. Under the current
Polymarket entry policy at size 10 and a 900-second deadline, it fully priced 67
of 84 simulated fills for total P&L `-$27.85`; 17 remain unknown. This
corrected loss path is not yet integrated with the
fixed-universe reward replay, maker fees remain unknown, and missing exposure
still needs explicit conservative bounds.

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
- `reward_rules.py`: pure, versioned current/legacy reward arithmetic with
  hand-checkable fixtures and tests. Reports print the rule and source date.
- `net_sizing.py`: integrates reward interruption and simulated fills on one
  clock. Its `proxy` combines predicted reward with markout; it is not complete
  net P&L and remains affected by B2–B3.
- The size table in `FINDINGS.md` section 18 used the superseded reward rule and
  a portfolio-changing sweep. It is retained as history and must not drive a
  strategy or sizing decision.
- Reward-only `sizing.py` under the current rule reports `$7.369/day` after the
  per-program minimum for seven size-10 markets on `capture_long.db` under the
  audited entry-price policy. It is not fixed-universe and is not a net-profit
  result.
- The hypothesis that Polymarket's reward jump was caused by the listed August
  25 uptime fixes is unproven; the reward increase began on August 23–24.

## Current scope boundary

Approved now:

- Repair and test measurement instruments.
- Re-run read-only analysis and produce conservative bounds.
- Run verified read-only measurement on the existing server under the isolated
  boundaries in `docs/SERVER_MEASUREMENT.md`.
- Observe and analyze the active read-only server capture; stopping or
  correcting that measurement remains inside the same safety boundary.
- Design a minimal one-market evidence probe and its safety case on paper.

Not approved now:

- Full Kalshi bot implementation.
- Live order code or authenticated write endpoints.
- Deployment, capital allocation, market selection for a live run, or an arming
  command.

The active work order is `NEXT.md`. Operator authority is in `DECISIONS.md`.

The daily capacity heartbeat is paused at the operator's request to conserve
Codex usage. Capacity checks are manual when the operator opens this task and
asks for one; they remain read-only and are not authorized to restart anything.

## Resolved blocker

### B1 — Kalshi rule-source conflict

**Resolved 2026-08-26.** The later July filing supersedes the February filing
effective July 30 and matches the Help Center. Current August analysis defaults
to `july-2026-one-fifth`; the February mode remains comparison-only.
