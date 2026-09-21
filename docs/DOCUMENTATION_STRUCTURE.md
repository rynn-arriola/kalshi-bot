# Documentation model: Polymarket reference, Kalshi ownership

Read-only inspection, September 19, 2026:
`C:/Users/rynna/Bots/liquidity-bot`, clean Git HEAD
`54ac71a241d1ad6f02e3445655bb7115247bac02`.
The old OneDrive `Bots/liquidity-bot` had no root operating Markdown and was
not used as the working reference. No live process/account state was inferred
from documentation. No Polymarket file, setting or process was changed.

## Verified Polymarket pattern

AGENTS/CLAUDE point to `AI_OPERATOR.md`, which owns routing, authority and
handoffs. `AI_ENGINEERING.md` owns permanent rules. STATUS/DECISIONS/NEXT answer
different current questions. FINDINGS/BUGFIXES/WATCHLIST route into dated
`docs/history/`. Technical API, architecture, safety, commissioning and release
references live in `docs/`. Its `scripts/audit_docs.py` checks routes, context
line budgets and local links. This structure, not its risk settings, is our model.

## Kalshi ownership

| File | Purpose |
|---|---|
| [AI_OPERATOR.md](../AI_OPERATOR.md) | Single agent-neutral contract, model selection and session routing |
| [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md) | Thin compatibility pointers |
| [AI_ENGINEERING.md](../AI_ENGINEERING.md) | Permanent safety, WebSocket-first, CPU and scalability rules |
| [STATUS.md](../STATUS.md) | Current project truth and blockers |
| [DECISIONS.md](../DECISIONS.md) | Accepted choices, separated from proposals |
| [NEXT.md](../NEXT.md) | Active ordered work |
| [WATCHLIST.md](../WATCHLIST.md) | Unapproved ideas and questions |
| [FINDINGS.md](../FINDINGS.md) | Evidence and corrections, dated and sourced |
| [BUGFIXES.md](../BUGFIXES.md) | Defect, mechanism, repair and verification |
| [BUILT.md](../BUILT.md) | Existing artifact inventory |
| [README.md](../README.md) | Human overview and navigation |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Design boundaries, source map, acceptance requirements |
| [KALSHI_API_REFERENCE.md](KALSHI_API_REFERENCE.md) | Dated contract corpus; load exact relevant sections |
| [LIQUIDITY_REWARD_RESEARCH.md](LIQUIDITY_REWARD_RESEARCH.md) | Reward research and unresolved facts |
| [history/](history/README.md) | Preserved dated/superseded narratives |
| [EXPERIMENT.md](../EXPERIMENT.md), [PLAN.md](PLAN.md) | Historical inputs, not current permission |

## Maintenance rules

- One question, one canonical owner; link rather than duplicate.
- Load current routing first, then task-specific history/contracts. Search with
  `rg`, rather than loading every archive or the entire large API reference.
- Distinguish requirements, proposed designs, implementation, deployment and
  measured behavior. A document is not proof a control already works.
- Keep new root handoffs short. Preserve older evidence before compaction and
  audit moved links/section references.
- Existing long Kalshi STATUS/FINDINGS/BUGFIXES/BUILT history has **not** been
  wholesale reorganized in this task. Root compaction and an automated audit
  remain queued, not claimed complete parity with Polymarket.
- Before runtime implementation, add task-specific safety/acceptance documents
  without prepopulating claims that tests or live controls already pass.
- Never copy local secrets, databases, host settings or operational permissions.

## Changes made

The prior operating contract moved into `AI_OPERATOR.md`, adapted to current
decisions. AGENTS/CLAUDE now route there. Previous Claude text is
[preserved](history/CLAUDE_PRE_ROUTING_2026-09-19.md). Permanent engineering
rules, architecture and watchlist are explicit. Only Markdown changed; no
trading code, connection, deployment or paper run was created.
