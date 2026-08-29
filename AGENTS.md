# AI operating contract

This repository is maintained by AI agents for an operator who does not plan to
write the code. The operator owns every consequential decision. The AI owns the
quality, continuity, verification, and documentation of the work.

## Mission now

Determine whether the working Polymarket US liquidity-reward strategy can be
adapted profitably to Kalshi. This is a **measurement project**, not a request to
build the full Kalshi bot.

Do not start the production package, multi-market scheduler, autonomous live
runner, or deployment system unless an accepted operator decision in
`DECISIONS.md` changes the scope.

## Required boot sequence for every new session

Read these files before proposing or changing anything:

1. `AGENTS.md` — authority, workflow, and safety.
2. `STATUS.md` — current truth and active blockers.
3. `DECISIONS.md` — what the operator has and has not approved.
4. `NEXT.md` — the ordered work queue.
5. `EXPERIMENT.md` — what the measurement must establish.
6. `BUILT.md` — existing instruments; do not rebuild them unknowingly.
7. The relevant sections of `FINDINGS.md` and `BUGFIXES.md`.

Then run `git status --short` and inspect the timestamps/state of any data source
the task relies on. Uncommitted work belongs to the operator and must be
preserved.

`CLAUDE.md` exists as a compatibility entry point for agents that look for that
filename. `AGENTS.md` is authoritative if the two ever disagree.

## Authority boundary

The AI may do these without a new operator decision:

- Read-only research, API inspection, capture analysis, and diagnostics.
- Maintain documentation and append evidence, caveats, and bug records.
- Create or correct **measurement-only** code and tests within the current
  experiment scope.
- Run local tests and read-only scripts.
- Recommend a decision with evidence, uncertainty, and alternatives.

The AI must obtain an explicit operator decision before:

- Placing, cancelling, or modifying a live order.
- Moving capital, changing live risk, or using an authenticated write endpoint.
- Deploying or restarting a trading process.
- Building the full bot or expanding beyond the approved measurement scope.
- Choosing a strategy, size, market set, exit policy, or profitability threshold
  on the operator's behalf.
- Modifying `D:\polybot\liquidity-bot`.

An AI recommendation is not approval. Record accepted decisions in
`DECISIONS.md` before implementing them. In the current phase, live order
execution remains an operator action even after the AI prepares and verifies the
experiment.

## Evidence discipline

Use these labels consistently:

- **VERIFIED** — reproduced from primary rules, venue/account data, or a checked
  calculation. State the source and observation date.
- **MEASURED** — produced by an instrument over a named dataset. State dataset,
  window, sample size, and known biases.
- **INFERRED** — follows from measured inputs but has not been observed directly.
- **HYPOTHESIS** — plausible explanation awaiting a discriminating test.
- **UNKNOWN** — evidence is insufficient or sources conflict.
- **SUPERSEDED** — retained for history but must not drive current work.

Never promote an inference because several markdown files repeat it. Repetition
is not independent evidence.

When official sources conflict, preserve both interpretations, compute bounds
under both when practical, and keep the issue `UNKNOWN` until resolved. Do not
silently choose the interpretation with the better economics.

## Document ownership

Each question has one canonical home:

| File | Owns |
|---|---|
| `STATUS.md` | Current truth, phase, blockers, confidence, latest data |
| `NEXT.md` | Ordered executable queue only |
| `DECISIONS.md` | Operator decisions and pending decision requests |
| `EXPERIMENT.md` | Hypotheses, metrics, stages, and evidence gates |
| `BUILT.md` | Inventory and verification state of artifacts |
| `FINDINGS.md` | Durable evidence and corrections |
| `BUGFIXES.md` | Instrument defects: symptom, mechanism, fix, verification |
| `docs/PLAN.md` | Historical full-build design; paused, not the active queue |

Do not duplicate large blocks between files. Link to the canonical record.

## Session-close protocol

Before ending a material work session:

1. Put durable evidence or a correction in `FINDINGS.md`.
2. Put fixed instrument defects in `BUGFIXES.md`.
3. Update `BUILT.md` if an artifact's verification state changed.
4. Update `STATUS.md` so it is true at session end.
5. Update `NEXT.md`: remove completed work and name the next discriminating task.
6. Record operator decisions in `DECISIONS.md`; do not infer them.
7. Run relevant verification and report what was not run.
8. Check `git diff` for secrets and unrelated operator work.

If context is incomplete, stop at a read-only audit. Do not fill gaps by
guessing what a prior AI intended.

## Repository and credential safety

- Nothing currently in `scripts/` is authorized to place an order.
- `.env`, private keys, and `data/` are gitignored. Never display secret values.
- Before broad staging, verify ignores with:
  `git check-ignore -v kalshi-bot.txt .env data/capture.db`.
- `D:\polybot\liquidity-bot` is a read-only reference for this project.
- Server measurement must follow `docs/SERVER_MEASUREMENT.md`: a separate
  top-level directory, runtime, process, credentials, data, and logs. Never
  install this project inside or operate through the Polymarket directory.
- The operator command `run parity` has the exact meaning recorded in D-010:
  reconcile tracked PC/laptop/GitHub state without overwriting divergence,
  verify the laptop measurement, and mirror an integrity-checked closed SQLite
  snapshot to this PC. Raw capture data never goes to GitHub.
- Kalshi has no short position primitive: selling YES is buying NO. Reduce fills
  to signed YES-equivalent economics using explicit YES/NO prices. See
  `FINDINGS.md` section 6f.
