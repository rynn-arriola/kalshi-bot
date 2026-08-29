# Current status

Last verified: 2026-08-28 23:45 (America/New_York).

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

**Measurement state:** laptop R1 14-day capture
`kalshi-readonly-capture-14d-laptop-r1` is active at deployed/tested commit
`0043c3a`. It started 2026-08-29 03:39:05 UTC in the laptop WSL path
`/home/polybot/kalshi-bot`, writing
`data/shadow-14d-laptop-r1-20260829.db` and
`logs/capture-14d-laptop-r1-20260829.log`. The seven-day checkpoint is
2026-09-05 03:39 UTC and planned completion is 2026-09-12 03:39 UTC. At the
03:44 UTC check it was active as PID 785 with zero restarts, 1,094 books, 5,407
trades, 16,859 program rows, 75 market-metadata rows, zero recorded errors and
zero non-200 book reads; the database quick check was `ok`.

The former server was destroyed by the operator, so its R3 process and unmirrored
R3 data are no longer the active evidence source. Historical R1 remains
preserved locally as `data/server-shadow-20260827-closed.db`. A two-minute
laptop canary closed cleanly at commit `0043c3a`; verified PC copies are
`data/laptop-canary-20260829.db` and `.log`. A consistent SQLite-backup snapshot
of laptop R1 at 03:44 UTC is mirrored on this PC as
`data/checkpoint-laptop-r1-start-20260829T0344Z.db` and `.log`.

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
- Laptop capacity is ample for the isolated Kalshi measurement. Windows reports
  16 logical CPUs, 31,866 MB total RAM with 17,522 MB free, and 706.8 GB free on
  C:. WSL reports 15,545 MB RAM with 14,782 MB available and 952 GB free. The
  long collector used about 79 MB with a 90 MB peak under its 256 MB cap and is
  limited to 20% of one CPU. The active Windows `Server Mode` plan disables
  sleep and hibernation on AC power; the laptop must remain plugged in because
  battery settings still permit sleep/hibernation. No upgrade is indicated.
- The Polymarket supervisor and trader were restarted at 2026-08-27 04:02:57
  UTC after the launch check. Kalshi stayed active, no OOM event occurred, and
  host load was low at inspection. The cause of the Polymarket restart is
  **UNKNOWN**; do not attribute it to Kalshi without evidence.
- The closed server dataset contains 50,038 books, 5,626 trades, and 17,672
  program rows with zero recorded HTTP errors/non-200 books before the fatal
  TLS disconnect. The database integrity check passes.
- On that 9h51m dataset, size-10 15-minute touch quotes completed both sides in
  11 of 8,620 windows (0.1%) and filled only one side in 88 (1.0%). Stepping
  inside completed 21 pairs (0.2%) and produced 140 one-sided fills (1.6%).
  Pure spread scalping therefore looks unfavorable: inventory is created about
  7–8 times more often than a spread is captured.
- A current-rule, same-clock proxy for the Polymarket entry policy modeled
  `$28.36/day` reward and `-$9.75/day` 300-second markout across 30 funded
  markets, proxy `+$18.61/day`. This is **not net P&L**: the corrected
  900-second exit replay priced 92 of 106 fills for `-$54.83` total with 14
  unknown, and the two instruments do not yet share a fixed universe or
  realized-exit clock.
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
- Compare pure spread-scalping quote gaps separately from rewards on identical
  data and assumptions; initially test join-the-touch and feasible 1¢–5¢ gaps.
- Run verified read-only measurement on the laptop under the isolated
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
Codex usage. Laptop checks and SQLite-backup mirrors to this PC are manual when
the operator opens this task and asks; they remain read-only with respect to
Kalshi and are not authorized to restart anything without an operator request.

## Resolved blocker

### B1 — Kalshi rule-source conflict

**Resolved 2026-08-26.** The later July filing supersedes the February filing
effective July 30 and matches the Help Center. Current August analysis defaults
to `july-2026-one-fifth`; the February mode remains comparison-only.

### B6 — Recorder retry resilience

**Resolved 2026-08-28.** At 10:27:03 UTC, R3 encountered a real `URLError`
caused by a connection reset on attempt 1/3. The request recovered within the
bounded retry path: the service retained PID 3898 with zero restarts, logged no
traceback, recorded no exhausted status-599 failure, and was still writing fresh
books at 12:58 UTC. This resolves transport survival, not the need to complete
the planned capture window.
