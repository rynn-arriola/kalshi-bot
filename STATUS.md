# Current status

## Project progress kept; projects pass the $2 gate (built) — 2026-10-01

D-168 fixes the project list reset from the D-167 restart and lets committed
projects place orders during ranking refreshes (15 of 35 were working). Needs
the full test run and an operator "restart".

## 50 contracts per order, project list 35 (built) — 2026-10-01

D-167 after the operator's $490 deposit (account $1,090.25). Needs the full
test run and an operator "restart" to deploy.

## Project limit counts only working projects (built) — 2026-10-01

D-166: blocked projects no longer hold entry slots idle (18 of 25 pairs were
used). Needs the full test run and an operator "restart" to deploy.

## Bot running on 1f2a352 — 2026-10-01 02:13 UTC

Recovery repaired and entries resumed (10 resting, $124.50 exposure at 02:15;
24-hour realized −$21.17 of the $60 limit). Path there: D-165 combo record,
then Finding 227 fixes. **Process slip:** the 01:40 start never exited (flat,
stuck retrying recovery on old code) and canonical was fast-forwarded under it;
no harm (no orders, the new launch was blocked). Its stop then timed out
(`shutdown_timeout`); on the operator's "Restart" the exact child (PID 39456,
generation 234, verified) was terminated under D-112 and the fixed build
launched. Lesson: check `supervised_live status` shows no parent/child before
every canonical fast-forward, not just after a stop.

## Start blocked by the operator's combo trade; record step built — 2026-10-01

Two starts at 00:30 and 00:35 UTC failed recovery and stopped flat: the
operator's settled combo (−$79.98 incl. fee, shard 1) was unknown to the bot.
D-165 records it exactly as an operator trade; then start. Balance $600.25 on
the main shard (account $600.69).

## Capital setting $600 (built) — 2026-09-30

Config now matches the ~$600 account (D-164): 50 orders of 30 need about
$567; cash and the exposure cap limit the count automatically.

## Code review fixes (built) — 2026-09-30

Review of the D-162/D-163 commit found and fixed three bugs before deploy
(Finding 226): the middle exit chased its own order down to one tick from the
other side; a $60 loss hold would have stopped the bot instead of pausing it;
a project reaching $1.50 was not saved at once. Bot closed until start.

## Patient exit and new entry order (built) — 2026-09-30

Built and tested on the branch, not deployed (D-163): exits wait 15 minutes at
our best price, then 15 at the middle, and cross only from 30 minutes. Entry
order is now projects → finished markets with a good reward (≥ 5¢/hour) →
everything else by normal ranking. Bot closed until the operator says start.

## Loss limit: $60 per rolling 24 hours (built) — 2026-09-30

Built and tested on the branch, not deployed: the six-hour $25 windows are
replaced by one limit, a $60 net realized loss over the last 24 hours, with
automatic resume (D-162; resolves Finding 225). Also built: the $1.50 per
market target. Bot closed until the operator says start.

## Target raised to $1.50 per market (built) — 2026-09-30

Built and tested on the branch: projects now stay until each market has
earned $1.50 (was $1.25). The 2026-09-30 $4.22 credit traced to two Alaska
diesel contracts (estimate $4.30). Bot still closed (Finding 225 decision
pending).

## Bot closed; loss-stop release gap found — 2026-09-30

**Stopped** (operator "Close the bot"), disarmed, flat, no auto-start. Two
starts today exited at once because the tripped $25 window from last night is
never released (Finding 225). Build `6481b48` is deployed and ready.

## Bot stopped; sweep-prone market types excluded (built) — 2026-09-30

**Stopped** by the operator at 03:54 UTC ("Stop kalshi bot"), flat, after
−$28.72 since the 09-29 22:09 restart (four sweep fills). Read-only analysis
(Finding 224): most bad fills come from app rank, card spend, port TEU, diesel
and mortgage markets. Built and tested on the branch: projects exclude those
types. Also built: a results filter on the family memory (7 harmless
families reopen, 21 losing ones stay blocked); per-series quiet hours were
measured and not built (no edge on 4 days of data). The bot stays stopped
until the operator says start.

## Project list live — 2026-09-29

**Running** build `f79c316` since ~22:10 UTC (operator "Ok restart"; flat).
The list filled to 30 projects within ~2 minutes (fastest to $1.25 first);
entries refilled to 40+ in ~3 minutes; other contracts blocked
(`project_list_full` / `cannot_reach_payout_minimum`). First launch pinned 0
(the list did not exist yet); later restarts pin the saved projects.

## Project list built — 2026-09-29

Built and tested on the branch, not deployed: new entries go only to a saved
list of up to 30 "projects" that stay until each passes $1 (or becomes
impossible); projects stay watched across restarts; resting orders in
contracts that can no longer reach $1 are withdrawn; the morning report shows
projects and waste. Needs an approved restart.

## Phase 3 ($1 finish line) live — 2026-09-29

**Running** build `af06975` since ~18:11 UTC (operator "Deploy restart";
flat). New entries now finish started contracts past $1 first; in the first
two minutes about half of contract evaluations were skipped as unable to reach
$1.25 in time (planned 1,379 / blocked 1,230). Entries refilled to 30+ in about
two minutes; LIP meter tracking 127 live contracts, none past $1 yet.

## Phase 3 ($1 finish line) built — 2026-09-29

Built and tested on the branch, not deployed. New entries now go first to
contracts we have started until they pass $1, then to new contracts that
reach $1 fastest; contracts that cannot reach $1 in time are skipped. Every
loss check is unchanged. Deploy is the operator's call (the D-161 plan waits
for the meter to match a payout first).

## LIP meter live — 2026-09-29

**Running** build `f327638` since ~15:33 UTC (operator "Restart"; flat). The
D-161 meter samples every 5 s: first 9 minutes 102 samples, 25 contracts, 0
errors, about $0.04 earned in total (~1¢/hour per contract, i.e. ~100 hours of
resting per contract to reach $1). About 1–2 contracts per sample are
"unscored" (no book or tick bands found); to diagnose. Entry cap 25 from the
loss window (−$19.54 in 10:00–16:00 UTC).

## D-161 step 1: LIP meter built — 2026-09-29

Built and tested on the branch, not deployed: a per-contract reward meter that
samples every contract with our orders resting every 5 s in its live book and
adds up earnings against Kalshi's $1-per-contract floor. The old tracker
covered 0.7% of the time (it sampled only when a book changed). Needs an
approved restart; validation against payouts follows (WATCHLIST B9).

## D-160 live after a manual close and a recovery fix — 2026-09-28

**Running** build `d764db2` since 23:49 UTC. D-160 (exit after 15 min unless
worse than $0.80/contract) is live. The operator's manual close of KXUALCC
(−$8.60) is reconciled into the ledger; the late-pulse recovery crash is
fixed (Finding 223). Entries refilling under the loss window cap (41).

## D-160 exit rule built — 2026-09-28

Built and tested on the branch, not deployed: after 15 minutes a position is
closed unless the loss is worse than $0.80 per contract (Polymarket's $8 at
size 10; was a flat $8, Finding 222). Needs an approved restart; the open
KXUALCC short would then close at about −$8.70.

## Resting-share counter live — 2026-09-28

**Running** build `a11a944` since 00:05 UTC (operator-approved restarts at
23:43 and 00:05; flat both times). Launch watch list: 896 of 1,024 markets
from the saved full scan (D-159 working end to end). The per-market resting
counter reads the live order stream (1 unknown in 35 samples, was ~43%) and
kept its history across the restart. Entries back to 50 in ~3 minutes.

## Resting-share counter built (phase 3 measurement) — 2026-09-27

Built and tested on the branch, not deployed: the bot will measure, per
market, how much of the time since it first rested there it actually has
orders resting (the number phase 3 needs), saved across restarts. No trading
change. Needs one approved restart.

## Business plan and measurement added — 2026-09-27

Agreed plan: measure, learn from payouts, concentrate on the $1 finish line,
balance pulls, scale only when net positive. The calibration report (on the
branch; not a bot change) now shows fill losses before/after the loss filters
(before: 12 fills/day, −$10.26/day; after: 0 fills in the first 12 hours) and
each live program's path to Kalshi's $1 minimum (0 cleared, 54 on track, 126
need more resting, 7 cannot reach; resting share 12%). Pending business
decisions and their measures: WATCHLIST B1–B6.

## D-159 and Finding 218 fixes deployed — 2026-09-27

**Running** build `cec3b26` since 22:55 UTC (operator-approved restart as part
of "Do recommendation"; stopped flat, no positions). The launch watch list came
from the saved scan (seeded from the 22:27 scan's top 200): 103 scanned
markets in scope, all Alaska diesel markets included and seeded first. Entries
refilled to 50 in ~4 minutes; sweep filter loaded; first scan pass saved 4,093
scoring markets to `market_scan.json`; catalog healthy (4,873 markets). The
next restart will build ~7/8 of the scope from the full saved scan.

## D-159 built: launch watch list from the saved scan — 2026-09-27

Built and tested on the branch, not deployed. Each full-scan pass saves its
scores; a restart then builds 7/8 of the 1,024-market watch list from the
latest scan (most reward left first) instead of the pool hint (Finding 220,
option A). Live build unchanged (`669e1a2`).

Also built: Finding 218 fixes (the reward-program catalog and market details
retry after giving up, instead of never; `entries_idle` warns after 15 minutes
at 0 resting). Both deploy at the next approved restart.

## Sweep-filter fix and full-scan retry deployed — 2026-09-27

**Running** build `669e1a2` since 20:44 UTC (operator-approved restarts:
"commans 1" at 20:22 for the scan retry fix, then "Ok" for the Finding 219
fix; flat each time). At ~20,000 Kalshi trades/min the sweep filter loaded 43 s
after start (was 18 min), entries refilled to 50 within 4 minutes, the full
scan's first pass succeeded (4,355 markets scoring) and feeds discovery. Entry
outages today: ~18:00–19:16 (Finding 218) and 20:22–20:40 (Finding 219).

## D-156 and D-158 deployed; entries restored — 2026-09-27

**Running** build `4b21bb0` since 19:16 UTC (operator "command 1"; flat, no
flatten trades). The restart also cleared a 75-minute entry outage caused by
an outside burst of public requests (Finding 218). Entries refilled (28+ and
rising), sweep filter loaded, no positions. First full-scan pass failed on a
read-quota refresh; the retry fix is built on the branch for the next restart.

## D-158 full-market scan built — 2026-09-27

Built and tested on the branch, not deployed (operator: no restart). Every
30 minutes the bot will score all ~5,100 rewarded markets (about 100 batched
reads, scored off the trading loop) and watch the best-scoring ones first;
entries keep every live check. Also on the branch awaiting the same restart:
D-156 ranker inputs, D-157 report (report runs now from the dev copy).

## D-156 ranker inputs and reward-truth report built — 2026-09-27

Built and tested on the branch, not deployed (operator: no restart). Report:
paid ÷ estimate per payout day (first: 3.9× on 2026-09-26) and the three-week
weighted factor. Research: `candidates` and `sweep_counts` for a later ranker
backtest (D-156). Running build stays `84399ef`.

## D-155 loss filters deployed — 2026-09-27

**Running** build `84399ef` since 11:42 UTC (clean stop while flat; full suite
2,083 OK, native supervisor gate twice OK). Live config loads with
`maximum_entry_downside` 0.80. Family memory loaded 14 families (74–162 h
left); sweep filter loaded 13 s after start, 0 failures, tracking 354–566
swept markets Kalshi-wide; entries refilling, 0 errors. Downside cap 0.80,
7-day family memory, big-sweep filter (≥150 contracts → 60 min out),
snapshot-lag retry, research trade-read skips.

## D-154 cooldown and D-153 diagnostic deployed — 2026-09-27

**Running** build `bdd183f` since 03:04 UTC (ordinary restart while flat; full
suite 2,068 OK; one native-supervisor test flaked once on timing and passed
4 reruns). Cooldown loaded within seconds: KXTXOIL blocked 23.4 h, KXBROSFT
3.5 h; entries refilling; loss ratchet at 41 until the 04:00 UTC window.

Earlier:

Operator-approved stop at 02:39 UTC while flat (0 orders, 0 positions) after
KXTXOIL filled us twice in 27 minutes (Finding 214; window realized −$6.89,
loss ratchet at 41). D-154 (24-hour post-fill cooldown from the ledger, research
fill backfill) and D-153 (audit mismatch labels) are built and tested; deploy
restarts the bot.

## D-153 audit-mismatch diagnostic ready — 2026-09-27

Built on the branch, not deployed (running build `04ff303`). Logs which
owned-order field differed from Kalshi's snapshot and how old our evidence
was, for the ~40/h renewal escalations (NEXT, WATCHLIST 15). Deploys with the
2026-09-27 pull-decision restart; no behavior change.

## D-152 measurement build deployed — 2026-09-26

**Running** build `04ff303` since 21:51 UTC (operator "command 1"; no positions,
so an ordinary clean stop and restart, no flatten trades; 0 orders and 0
positions at stop). First 3 minutes: healthy, entries refilling (34+), order
group active, 0 errors, research alive with `failure_sites` reporting. Adds `entry_blocked_fraction` to `health_hourly` and research failure sites to
status, plus the report's pull-vs-real-trades replay (works on data already
collected). Finding 213: pulls ~97% false alarms, but Finding 206 shows the one
real save came from cancels before a sweep, so no trigger change until the
2026-09-27 report. Tracked in NEXT (dated follow-ups) and WATCHLIST 11–13.

## D-151 research dataset deployed — 2026-09-26

**Running** build `32d1934` since 19:15 UTC (operator-approved stop: clean, zero
orders and positions; restart). First 4 minutes: healthy, 28+ entries, no
positions, order group active, 0 errors, read budget 0 throttles; research
writer alive, 0 drops, 0 failures (22 entries, 4 entry ends, 2 pulls, 379 reward
estimates; trades 0 because the quoted markets had no trades, confirmed against
Kalshi). Hourly health rows start at the next UTC hour. Adds `research.db`
beside the ledger, written by one background thread that never blocks or
raises into trading: entry lifecycles with screen context, fills with 1/5/30
minute mark-outs, protective pulls with a 30/60 s "was the level reached?"
check, public trades in quoted markets (one background read per market per
minute, at most 64), hourly health and counter deltas, hourly reward estimates
and reward-like cash credits; 120-day retention. `scripts/calibration_report.py`
writes the calibration report (goal: improve the bot; read-only). Review fixes: a
failing prune no longer ends the writer; a check with no book is unknown, not
"reached".

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
