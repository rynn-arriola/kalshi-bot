# Current status

## Architecture review deployed — 2026-09-26

**Running** build `ac4ff9f` since 16:36 UTC (operator-approved stop: clean, zero
orders and positions; restart). First minutes: order group active, fill
protection current, routine telemetry only in `telemetry.jsonl`, 0 errors;
first 56 `entry_screen_shadow` verdicts: 36 reward_risk, 10 both, 6 volume,
4 pass (remaining reward ~$2–3 vs worst single-fill loss ~$18–23). Contents:
D-149 separate telemetry log (events.jsonl ~6 days), D-150 shadow-only
fill-avoidance screen, and behavior-preserving refactors (unsent-abort helper,
hot-path validators −37% / evaluation −16%, runtime `__dict__` defaults,
`account_proof.py` extraction, named writer branches). Exception audit and CPU
profile: Finding 212. Workspace: 11 merged worktrees and 15 merged branches
removed; loose files in `data/worktree-archive-2026-09-26/`; `command1-dev`
kept (uncommitted draft, backed up). Full suite 2,011 tests and native gate pass.

## D-147 and D-148 running — 2026-09-26

**Running** build `3223f7a` since 13:53 UTC (operator-approved stop: clean, zero
orders and positions; restart). First 6 minutes: 50 orders at 30 contracts, no
positions, order group active, 7 protective pulls. After drains, 6 lighter
own-order renewals versus 1 full recovery (was one full recovery per drain);
2 routine renewals handed over to own renewal; own renewals 35 of 36 completed
with 0 escalations. Full recoveries: 6 in ~6 min (≈18 per 6 min before).
Earlier today: D-145 (fill protection), D-146 (send-edge crash fix), manual
close reconciled (net −$18.3604). Autostart task `KalshiLiquidityBot-Autostart`
registered at the operator's request (runs 2 minutes after sign-in; Windows
automatic sign-in is the operator's own setting).

## Bot stopped after an adverse fill; D-145 fill protection ready — 2026-09-26

**Stopped (operator request, ~06:32 UTC).** 05:52:16.9 UTC a one-shot 488-contract
sweep filled a 30-contract bid at 0.82 in KXBROSFT-26OCT08-T107 (Finding 210).
The operator stopped the bot: all 50 entries cancelled; the stop reached
`shutdown_timeout` because the position remained. The operator then sold the 30
manually at 0.22 (06:35:17 UTC, fees $0.36; position loss ≈ $18.36) and the
exit order was cancelled. The child (PID 51884) is still alive in
`attention_required` with zero orders; it cannot see the manual sale as its own,
so it cannot prove flat. Before the next start: end that exact child (operator
approval), record the manual close with the existing operator-close adoption,
then deploy D-145.

**D-145 built, not deployed:** continuous queue tracking with short-queue and
blind triggers (Unit A) and Kalshi order groups at limit 31 per shard (Unit B).
Full suite and native supervisor gate pass; 44/44 mutations killed.

## D-136–D-143 deployed; trading at 50 × 30 contracts — 2026-09-26

**Running** (build `f45d9a4`, trading child run `cce01ccf`). Sequence: the
$300 deposit blocked D-135 (Finding 208); the operator stopped the bot; D-141
deployed and credited the deposit (`cash_adjusted` $300.00), but the first
30-contract pair hit a hard-coded size gate and became UNKNOWN (Finding 209);
D-143 was deployed after an operator-approved restart (stop timed out; exact
child PID 50596 terminated). The recovery-only child resolved both phantom
creates (`unknown_create_resolved` ×2) and proved the account; the trading
child started 05:10:34 UTC (56 s startup).

First minute: 20 resting entries at 30 contracts, $249.60 collateral,
13 acknowledgements, own-order renewal 9/10, full recovery ~2.0 s, no
positions, no ERROR, no accounting blockers. Backups:
`data/trader/d142-backup-20260926T044034Z/`, `d143-backup-20260926T050814Z/`.

## Earlier history

Every earlier status section is preserved verbatim in [docs/history/STATUS_ARCHIVE_2026-09-26.md](docs/history/STATUS_ARCHIVE_2026-09-26.md).
