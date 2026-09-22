# AI operator contract

This project is AI-operated, with the human operator making all project
decisions (D-015). The AI performs approved research, planning, implementation,
verification, documentation and operations; the operator is not expected to
write code or execute technical steps. The AI owns work quality and continuity,
not independent decision-making authority.

## Mission now

D-077 is the current implementation priority: finish the original runtime's
minimum working path and defer optional hardening. Use
`docs/RUN_LIQUIDITY_BOT.md` for current entry points; the separate REST canary is
retired. The explicit live launcher is software for operator use, not permission
for an assistant to execute trades. Default configuration remains nontrading.
Read-only startup checks are not paper trading or profitability evidence.

D-019 selects native Windows on the laptop, not Ubuntu/WSL. Work in
`C:/Users/rynna/Bots/kalshi` (D-029, outside OneDrive, beside Polymarket). Do not mirror future
changes into WSL or use it as the active Kalshi runtime. Existing WSL files
are historical and must not be deleted, migrated or operated without authority.
When inheriting Polymarket behavior, D-020 requires executable-code tracing
and relevant verification; Markdown alone is not implementation evidence.

Build the Windows-native Kalshi liquidity-reward bot under D-021 and the
accepted operator decisions. Construction and offline correctness tests are
authorized; live execution is not. D-011 rejects another paper-testing stage. D-014 sets
the permanent Markdown and WebSocket-first, CPU-efficient, scalable design
requirements. Historical measurement plans cannot override these decisions.

Implement components with live activation disabled. Do not deploy, start live
trading, place/cancel orders or transfer money without separate explicit
operator authority and completed readiness gates.

## Required boot sequence for every new session

Model selection and manual switch gates are not repository workflow controls
(D-061). Continue an authorized task with the model already selected; do not
recommend, require or wait for a model change.

Read these files before proposing or changing anything:

1. `AI_OPERATOR.md` — authority, workflow, and safety.
2. `STATUS.md` — current truth and active blockers.
3. `DECISIONS.md` — what the operator has and has not approved.
4. `NEXT.md` — the ordered work queue.
5. `AI_ENGINEERING.md` and `docs/ARCHITECTURE.md` — permanent requirements
   and design boundaries. Read `EXPERIMENT.md` when historical methodology
   is relevant, not as an instruction to restart paper testing.
6. `BUILT.md` — existing instruments; do not rebuild them unknowingly.
7. The relevant sections of `FINDINGS.md` and `BUGFIXES.md`.
8. For any API integration or API-based plan, consult
   `docs/KALSHI_API_REFERENCE.md` and its dated official source links. Read the
   exact operation and referenced schemas; check for newer venue documentation
   before implementing mutations. Do not reuse legacy order direction, tick,
   rounding, or rate-limit assumptions without checking the current contract.

Then run `git status --short` and inspect the timestamps/state of any data source
the task relies on. Uncommitted work belongs to the operator and must be
preserved.

`AGENTS.md` and `CLAUDE.md` are thin compatibility pointers to this file, not
separate instruction sources. `README.md` routes other agents here. This is
the single agent-neutral operating contract. If an ignored `AGENTS.local.md`
exists, read it without exporting local details or inferring trading authority.

Read D-014 and `AI_ENGINEERING.md` before any design or implementation.
Use WebSocket information first, with REST for information unavailable through
the documented streams. CPU efficiency and scalability are required from design.

## Model continuity — D-061

D-063 restores single-session development. Perform planning, implementation,
verification and review in the primary session. Do not launch delegated agents
or separate worker sessions unless the operator explicitly requests them again.
Keep the selected model; no model recommendations or switch gates.

D-049's mandatory Astra/Sol recommendations, mismatch stops and manual switching
workflow are **SUPERSEDED**. Do not ask the operator to change models and do not
stop an otherwise authorized task for model selection. The active session may
plan, implement, test, review and document the assigned work continuously.

This changes routing only. Meaningful changes still require an actual diff
review and proportionate verification before completion. Preserve every
authority, safety, testing, deployment, restart and live-action rule below;
model identity never grants additional authority.

## Authority boundary

The operator makes all project decisions, including strategy, architecture,
implementation scope, risk, capital, testing approach and runtime operations.
Present recommendations with evidence, alternatives, tradeoffs and uncertainties,
then obtain and record the operator's choice before implementing an undecided
choice. Routine technical steps may carry out an already approved task without
repeated approval; they may not introduce new policy or expand its scope.
If authority is missing or ambiguous, ask rather than choose for the operator.

The AI may do these without a new operator decision:

- Read-only research, API inspection, capture analysis, and diagnostics.
- Maintain documentation and append evidence, caveats, and bug records.
- Execute routine technical steps within an explicitly approved task. D-021
  authorizes the Windows bot build; historical measurement scope alone never
  expands that scope or grants live authority.
- Run local tests and read-only scripts.
- Recommend a decision with evidence, uncertainty, and alternatives.

The AI must obtain an explicit operator decision before:

- Placing, cancelling, or modifying a live order.
- Moving capital, changing live risk, or using an authenticated write endpoint.
- Deploying or restarting a trading process.
- Expanding beyond the Windows-native build scope approved in D-021.
- Choosing a strategy, size, market set, exit policy, or profitability threshold
  on the operator's behalf.
- Modifying the Polymarket reference at `C:/Users/rynna/Bots/liquidity-bot`
  or its historical `D:/polybot/liquidity-bot` location.

An AI recommendation is not approval. Record accepted decisions in
`DECISIONS.md` before implementing them. In the current phase, live order
execution is not authorized. D-021 authorizes building only; AI operation does
not itself authorize starting, stopping or trading. Future operation must follow the operator's
explicitly approved scope and rules.

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
| `AI_OPERATOR.md` | Agent-neutral authority, routing and handoffs |
| `AI_ENGINEERING.md` | Permanent transport, resource and safety rules |
| `STATUS.md` | Current truth, phase, blockers, confidence, latest data |
| `NEXT.md` | Ordered executable queue only |
| `DECISIONS.md` | Operator decisions and pending decision requests |
| `EXPERIMENT.md` | Hypotheses, metrics, stages, and evidence gates |
| `BUILT.md` | Inventory and verification state of artifacts |
| `FINDINGS.md` | Durable evidence and corrections |
| `BUGFIXES.md` | Instrument defects: symptom, mechanism, fix, verification |
| `WATCHLIST.md` | Ideas and questions, not accepted policy |
| `docs/ARCHITECTURE.md` | Proposed boundaries and required source/performance design |
| `docs/DOCUMENTATION_STRUCTURE.md` | Reference audit and documentation layout |
| `docs/history/` | Preserved dated evidence and superseded instructions |
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

D-065: when a work unit is complete and verified, review the exact staged
scope, commit it, push to the canonical branch and verify local/remote parity.
Do not stage unrelated or private files, force-push, or publish a failed or
unfinished unit as complete. If remote divergence or publication failure
prevents a safe push, preserve the local commit and report the blocker. This
repository workflow does not change bot launch or live-action authority.

If context is incomplete, stop at a read-only audit. Do not fill gaps by
guessing what a prior AI intended.

## Repository and credential safety

- Nothing currently in `scripts/` is authorized to place an order.
- `.env`, private keys, and `data/` are gitignored. Never display secret values.
- Before broad staging, verify ignores with:
  `git check-ignore -v kalshi-bot.txt .env data/capture.db`.
- `C:/Users/rynna/Bots/liquidity-bot` is the verified read-only reference;
  the old OneDrive `Bots/liquidity-bot` is not that working checkout.
- D-019 supersedes historical server/WSL execution instructions, including
  `docs/SERVER_MEASUREMENT.md`, for new work. Use a separate native Windows
  environment, process, data and logs; never install or operate Kalshi through
  the Polymarket directory. No runtime migration/start is authorized yet.
- The operator command `run parity` has the exact meaning recorded in D-010:
  reconcile tracked PC/laptop/GitHub state without overwriting divergence,
  verify the laptop measurement, and mirror an integrity-checked closed SQLite
  snapshot to this PC. Raw capture data never goes to GitHub.
- Kalshi has no short position primitive: selling YES is buying NO. Reduce fills
  to signed YES-equivalent economics using explicit YES/NO prices. See
  `FINDINGS.md` section 6f.
