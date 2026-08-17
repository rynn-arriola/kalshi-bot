# What exists

Inventory of everything built, what it does, and how it was verified. Updated
when something is finished — not when it is started.

Companion files: `NEXT.md` (what to do next), `FINDINGS.md` (what we learned),
`BUGFIXES.md` (what broke and why).

Last updated 2026-08-17.

---

## Status at a glance

| phase | scope | state |
|---|---|---|
| Research | Reward rules, fee model, universe shape | **done, ongoing refinement** |
| Instruments | Raw capture, signed reads, formula replay | **done** |
| Analysis | Reward share, two-sided rate, tick effect | **partial** |
| Phase 0 | Pure core (models, rewards, risk, fees) | **not started, deliberately** |
| Phase 1 | Read-only adapters + streams | not started |
| Phase 2 | Shadow measurement harness | not started |
| Phase 3 | One-contract evidence run | not started |

Phase 0 is deliberately not started. Several numbers the economics depend on
are still inferred, and code written now would bake them in permanently. See
`NEXT.md` "Still unknown, and blocking".

---

## Instruments — built and working

### `scripts/record_books.py` — 466 lines

Raw capture of liquidity-incentive programs, order books, trades, and exchange
status. **Interprets nothing**: stores exact venue JSON with a timestamp.

| capability | detail |
|---|---|
| programs | all active liquidity programs, paginated, every ~15 min |
| books | `depth=100` (200 returns HTTP 400), per sweep |
| trades | 48h backfill on first sight, then overlapping windows, deduped on `trade_id` |
| exchange status | so closed-market gaps are not read as zero liquidity |
| errors | recorded as data, including sweep overruns |

Selection is capped per series (default 3) — without it the top 40 by
`reward/target` came back as 29 markets from one event.

**Verified:** running now, 40 markets across 18 series, 4,625 books and 2,531
trades, 1 non-fatal error (a sweep overrun, which is recorded deliberately).

**Known limits:** ranking is the only interpretation in the script, and it is
scale-invariant so an unconfirmed `period_reward` unit cannot corrupt it. Real
sample spacing is the sweep duration, not `--interval` — read the timestamps.

### `scripts/kalshi_auth.py` — 127 lines

Signed read-only access. **No order function exists in this module and there is
no code path to an order endpoint.**

RSA-PSS/SHA-256 over `timestamp + METHOD + path`, where the signed path includes
the `/trade-api/v2` prefix and excludes the query string, timestamp in
milliseconds as a string, salt length = digest length. All four details are easy
to get wrong and fail identically with `token_authentication_failure`, so they
are documented in the module.

**Verified:** authenticated against the live account. Balance read, `/account/limits`,
positions, orders, fills, settlements all returning 200.

### `scripts/analyze_capture.py` — 216 lines

Replays Kalshi's published reward formula over captured raw books. Pure
arithmetic on recorded data — the CFTC filing fully determines each order's
score given the book and the program parameters.

Reports per `(ticker, side)`: two-sided rate, denominator, share at the touch,
share one tick inside, and a crowding flag when our own size would dominate the
side.

**Verified:** 3,786 snapshots analysed; produced the 85% two-sided rate and the
1.987x one-tick result. Two reporting bugs found and fixed — see `BUGFIXES.md`.

---

## Documentation — built

| file | lines | purpose |
|---|---|---|
| `FINDINGS.md` | 520 | established facts, each with its measurement |
| `docs/PLAN.md` | 299 | the approved end-to-end plan |
| `NEXT.md` | 75 | session orientation: state, blockers, next actions |
| `README.md` | 60 | what the project is and what to read first |
| `BUGFIXES.md` | 49 | instrument bugs: symptom, mechanism, fix |

---

## What explicitly does NOT exist

No package, no `pyproject.toml`, no `src/kalshi_bot/`. No models, no reward
scorer, no risk model, no ledger, no reconciler, no order code, no tests.

Nothing has placed an order. Nothing has committed capital. `$22.64` sits
untouched in the account.

This is the intended state. The instruments answer questions; the bot gets built
from the answers.

---

## Answered by what we built

- Taker fee formula, proven against two real fills
- Rate limits — 200/s reads, ~50x the reference implementation's assumption
- Two-sided rate — 85%, versus ~60% from an 8-market hand sample
- One tick inside doubles reward share — 6,438 observations, p10 1.916, p90 1.999
- No short exists: selling YES is executed as buying NO

## Still unanswered, and why

| question | why the instruments cannot answer it |
|---|---|
| `period_reward` scale | no earnings endpoint exists; likely needs a real payout |
| maker fee rate | both account fills were `is_taker: true`; needs one resting fill |
| `revenue: 0` on a settled position | needs a second settlement to compare |
| post-only support | needs an order placement, which the operator must run |
