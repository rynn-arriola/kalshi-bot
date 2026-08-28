# Operator decision ledger

This is the authority record. AI agents may recommend decisions but may not mark
them accepted without an explicit operator instruction.

## Accepted decisions

### D-001 — Measure before building

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Do not build the full Kalshi bot yet. Determine whether the
  Polymarket US strategy can work profitably on Kalshi through measurement.
- **Consequence:** Production package, multi-market execution, deployment, and
  scaling work are paused.
- **Revisit when:** The experiment gates in `EXPERIMENT.md` have enough evidence
  to support a build/no-build recommendation.

### D-002 — AI-maintained repository

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Assume the operator will not write the code. AI agents maintain
  the code, tests, research, and handoff documentation.
- **Consequence:** Every material session must leave `STATUS.md`, `NEXT.md`, and
  the evidence trail usable by a fresh AI session.
- **Revisit when:** The operator changes the maintenance model.

### D-003 — Operator retains consequential decisions

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** The operator makes strategy, capital, risk, live-action,
  deployment, and scope decisions. AI agents investigate, recommend, implement
  approved work, and report results.
- **Consequence:** No AI may convert a recommendation into authorization.
- **Revisit when:** Only by explicit operator instruction.

### D-004 — No live mutation in the current phase

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator, preserving the existing project constraint
- **Decision:** Current work is read-only measurement and experiment design.
  Live order placement remains outside scope. A later minimal evidence run must
  receive a separate operator decision, and the operator performs the arming
  action unless this decision is explicitly amended.
- **Consequence:** Keep `kalshi_auth.py` read-only and add no order endpoint yet.
- **Revisit when:** Read-only gates justify a minimal live experiment.

### D-005 — Polymarket repository is a read-only reference

- **Status:** ACCEPTED
- **Date:** 2026-08-17
- **Decision owner:** Operator
- **Decision:** Do not modify `D:\polybot\liquidity-bot`; copy concepts only
  after separating venue-independent safety from venue-specific calibration.

### D-006 — Canonical GitHub repository

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Publish and maintain this project at
  `https://github.com/rynn-arriola/kalshi-bot.git`.
- **Consequence:** This remote carries measurement code, tests, and AI handoff
  documentation. Ignored credentials and captured data remain local only.
- **Revisit when:** The operator names a replacement repository.

### D-007 — Isolated server measurement is allowed

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Read-only Kalshi measurement may run on the server that hosts
  the Polymarket bot, but it must be installed in a new standalone Kalshi
  project folder and never inside the Polymarket folder.
- **Consequence:** Use a separate top-level directory, environment, process,
  configuration, data, and logs. Do not import from, write inside, restart, or
  make API calls through the Polymarket project. Read-only Kalshi API calls are
  permitted from that isolated project; authenticated writes and all live order
  actions remain prohibited by D-004. The boundaries in
  `docs/SERVER_MEASUREMENT.md` are mandatory.
- **Revisit when:** Measurement resource use interferes with production, or the
  operator selects a separate server.

### D-008 — Include spread scalping in the measurement

- **Status:** ACCEPTED
- **Date:** 2026-08-27
- **Decision owner:** Operator
- **Decision:** Measure whether two-sided spread capture is profitable on the
  current Kalshi data, both alone and combined with liquidity reward.
- **Consequence:** Offline/read-only replay may measure pair completion,
  one-sided inventory, fees, exits, and net. Keep pure scalping and reward
  separate before producing a combined result. This does not authorize live
  orders or a new strategy implementation.
- **Revisit when:** A fixed-universe replay provides a decision-grade estimate.

## Pending decisions

None. The next tasks are evidence work already inside D-001 and D-004.

When a decision becomes necessary, add a short request here containing:

- the exact choice;
- why progress depends on it;
- evidence and uncertainty;
- recommended option and alternatives;
- maximum capital/state impact;
- rollback or stop condition.
