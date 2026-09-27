# Findings — kalshi-bot

## 216. Calibration report, 16 hours: pulls rarely right at 60 s, but staying out helped; first payout — 2026-09-27

**MEASURED (research.db 2026-09-26 19:15 → 2026-09-27 11:00 UTC, Kalshi trades).**
`time_to_fill` 1,241 pulls, 2% with our level gone 60 s later; 5 trade-backed.
Of the 19 pulls whose level was gone, 18 had no trade through our price within
90 s (cancels or quote moves); the 19th was KXTXOIL 02:14:19, the same second
the sweep filled us, so the pull did not prevent it. `short_queue` 9 pulls, 0
justified. 60–78% of entry orders ended by being pulled. Three fills in the
window, all single sweeps with no trade on our side in the 30 s before. Fill
rates by shadow verdict, 24-h volume and depth ahead: too few fills (3) to
separate them.

**First reward-like credit:** $1.22 unattributed credit at 10:13 UTC
(6:13 AM ET), consistent with a program that ended 2026-09-26. Our per-program
estimates (tracking since 2026-09-26 19:00 only) are all under $1 for programs
ending by 2026-10-04, so they understate full-period earnings.

**Correction:** the dataset covers ~16 hours (2026-09-26 19:15 → 2026-09-27
11:00 UTC), not 40.

**MEASURED — deeper look (same window, Kalshi trades).**
- *Cost of pulls:* after a pull we stayed out of that market a median 8.8 min
  (p75 22, p90 61); 545 market-hours out in 15.8 h (about 34 markets out at
  any time) while the 50 slots stayed full elsewhere (average resting 49.8).
  The pulled markets' own estimated reward while out was at most $13.88
  (~$0.88/h); the true loss is the gap to the lower-ranked replacements.
- *Hidden benefit:* in 3 pulls (KXC4POS ask 0.79, KXMONSTERPOS ask 0.89,
  KXKSWHEAT bid 0.73), a sweep of 105–298 contracts went through our old price
  while we were out (within 60 min); staying in would likely have filled us.
  Pulls act as an activity filter even though the 60-s prediction is 2%.
- *Downside cap trade-off (2,079 entry pairs, 154 markets):* capping the worse
  leg's loss per contract at 0.60 removes 54% of entries and ~53% of estimated
  reward (avoids $21.45 of past loss); 0.75 removes 19% / 17%, 0.80 removes
  9% / 8%, and both still avoid KXBROSFT's −$18.36 (45% of all losses).
- *Near misses among quoted markets:* no large sweep missed us by luck; the
  only sweeps ≥150 in quoted markets were the ones that filled us.

**Implication:** turning off `time_to_fill` would save churn and some reward
but lose the stay-out effect; the evidence is balanced, so test it rather than
switch. A 0.75–0.80 downside cap is cheap relative to the loss it avoids;
0.60 is not.

## 215. Loss review: 19 round trips, −$41.12; about a third was predictable — 2026-09-27

**MEASURED (ledger fills 2026-09-23 11:29 → 2026-09-27 05:36 UTC, Kalshi public
trades).** 19 entry fills, each closed ~15 min later by the exit rule; 18 lost,
one made $0.10. Net −$41.12: −$13.56 over 15 trips at 10 contracts, −$27.56 over
4 trips at 30 (KXBROSFT alone −$18.36, a 0.82 bid swept to ~0.2). Every fill was
one taker sweep of 58–819 contracts.

- **Predictable from recent trades (6 fills, −$12.46):** a same-side sweep of
  ≥150 contracts had hit that market 1–49 minutes before our fill (KXTRUEV,
  KXTXOIL ×3, KXZYNPOS, KXKSWHEAT).
- **Repeat series (5 fills, −$9.68):** a second or later fill in a series that
  had already filled us (KXTOKENUSE, KXCTMFPERMITS, KXWYCOAL, KXTXOIL ×2). The
  24-hour market cooldown (D-154) covers only the two same-market repeats within
  a day (−$6.23); KXTXOIL came back after 3.2 days.
- **Large downside per contract:** KXBROSFT's 0.82 bid could lose up to 0.82 per
  contract and lost 0.60; 45% of all losses.
- **Not predictable (the rest):** quiet markets (no trades in the prior hour),
  then one sweep.

Union of the first two filters: 9 fills, −$15.24 (37%); adding a downside cap
around 0.6/contract adds KXBROSFT and two small ones (≈ 84% in total). This is
fitted in hindsight on 19 fills and every filter also removes reward-earning
markets, so it is a HYPOTHESIS until the calibration report weighs the excluded
markets' reward.

**Rewards side.** Estimated ~$0.58/h gross at the current rate (~$14/day), but
only 25 of 395 tracked programs are on course for Kalshi's $1 minimum and none
has reached it; 369 show `source_lost` (no longer tracked, e.g. after restarts).
No payout has arrived yet. Profitability is unproven: recent losses run about
$9/day at 30 contracts excluding KXBROSFT.

## 214. Swept twice in one market 27 minutes apart; the bot walked back in — 2026-09-27

**MEASURED (ledger + Kalshi public trades).** KXTXOIL-27MAR31-T5.8 (Texas crude
production, ~4,660 contracts/24 h). 01:34:20 UTC a single seller swept about
3,700 YES at 0.64 (every bid). 01:47:07 a 263-contract sweep at 0.58 filled our
30-contract bid (maker, no fee); the 15-minute exit rule sold 20 at 0.58 and 10
at 0.53 at 02:02:15 (−$1.02 with taker fees). 02:14:19 the bot had re-entered
the same market and a ~560-contract sweep at 0.51–0.53 filled 30 at 0.53; 8 s
later trades printed at 0.21. The exit rule sold 30 at 0.35 at 02:29:38.
Window realized −$6.89; the loss ratchet cut entries to 41. The 31-contract
order group capped each hit as designed.

**Causes.** (1) No re-entry lockout after a fill: the market was eligible again
as soon as the position was flat (Finding 210 had proposed a post-fill
cooldown). (2) No "recently swept" screen: the first fill came 13 minutes after
a 3,700-contract sweep. (3) The D-150 volume screen (shadow only) would have
flagged this market (> 286/day). Every fill was again a single sweep with no
warning trade, so no cancel trigger could have helped.

**Also found:** these fills reached the ledger during a concurrent renewal /
recovery, not through the stream fill hook, so the D-151 research `fills`
table missed them.

**Repair:** D-154 (24-hour post-fill cooldown from the ledger; research fills
backfilled from the ledger). The swept-market screen is a follow-up.

## 213. D-145 pulls are still ~97% false alarms; entries closed about half the time — 2026-09-26

**Scope:** first 1.6 h of the D-151 research dataset (build `32d1934`, 19:15–20:55
UTC), the calibration report and `runtime_health` since 13:21 UTC.

**MEASURED — pulls.** 121 protective pulls; 3 of 115 checked (3%) had our price
level gone 60 s later. Replayed against Kalshi's own trade records, 1 of 131
`time_to_fill` pulls had any trade on our side of the book in the 30 s before;
the rest were driven by other makers cancelling ahead. About 60% of entry
orders ended by being pulled. No fills in the window.

**Caution (Finding 206):** the one real save measured before D-145 (KXWMTCC)
fired on makers pulling liquidity *before* a sweep, with no trade first. A
trade-only trigger would have missed it. Cancels ahead are mostly noise but
sometimes the only warning, so the trade-evidence rule is a HYPOTHESIS until a
day of data shows how many skipped pulls preceded a real sweep ("skipped but
gone" in the report).

**MEASURED — entry gate.** `entry_allowed` true in ~40–50% of `runtime_health`
samples all day, on the previous build too; first `health_hourly` row 51%, yet
48.1 of 50 entries resting on average. Session, pause, venue and stop were
ruled out from status; the remaining terms are the accounting proof not
released or its lease not current. D-152 samples which one.

**MEASURED after D-152 (22:00–00:00 UTC, 441 samples).** Entries allowed 49–52%.
Closed by the accounting lease: `lease_missing` 30–32% and `lease_stale`
16–22% of samples; `accounting_unreleased` under 0.5%. By design the writer
revokes the lease on every external account write (order update, ack,
cancel, fill) and a proof renewal re-issues it seconds later, so the gate
flickers with order churn rather than staying shut. Average resting entries
49.6–49.9 of 50, so the coverage cost is negligible; refills wait a few
seconds. Fewer false pulls would also mean fewer revocations. Research
failures: all 19 are `trades_read:QuotaUnavailable` (`quota_revision_changed`,
a trades read overlapping a read-quota refresh). The window does not advance
on failure, so no trades are lost.

## 212. Architecture review 2026-09-26: exception audit and CPU profile

**VERIFIED (static audit + profiling).** Broad handlers in `src/kalshi_bot`: 115
`except Exception/BaseException` blocks; 61 re-raise, 44 record the failure
(counter, diagnostics, failure flag), 10 swallow silently. All 10 are
best-effort secondary actions (diagnostics emission, a secondary UNKNOWN
persistence attempt, child-result IPC) inside a path that re-raises the primary
error; none hides a safety fault. If a secondary UNKNOWN write fails the command
stays durably SENDING, which recovery already treats as unresolved.

CPU (live, generation 188 child): 0.58–0.70 of one core, ~320 book events/s,
backlog 0. Profile of the 1,024-market load test: per-evaluation cost 0.84 ms;
about half is selection re-ranking on every book change, a quarter inventory
plans; hot-path validators rebuilt constants on every call. Review #5 cut
evaluation cost to 0.70 ms (validators −37%). Remaining lever: coalescing
selection re-ranking per market, a behavior change needing a decision.

## 211. Quota refresh at the send edge crashed the runtime; D-145 first hours — 2026-09-26

**VERIFIED (live logs, generation 188).** 10:38:09 UTC a write-quota refresh
began while an entry pair was SENDING; the send-edge budget check raised
`QuotaUnavailable` before any transport call, the pair was recorded UNKNOWN and
the runtime failed. The supervisor's recovery-only child waited the D-143
600-s absence rule, resolved both phantom creates and trading resumed 10:49
(~11 min lost). Nothing reached Kalshi. Fixed by D-146.

D-145 since 06:46 UTC: zero fills; 237 protective withdrawals in the 1 h 50 min
after 10:49 (236 time-to-fill, 1 short-queue, 0 blind); order group active, never
triggered; queue reader 43 failures in 6,072 reads. Full account recoveries
took ~810 s of 7,000 s (~12%); 208 of 319 followed a protective cancel drain
(`post_drain`, median 2.3 s) — a candidate efficiency change (own-order renewal
instead of a full pass), not yet made. Routine renewal fell back 83 times on a
concurrent source change; `audit_blocked` renewals (6) did not log which audit
check failed (now logged, D-146).

## 210. Every entry fill this week was a one-shot sweep; heavy markets get swept — 2026-09-26

**VERIFIED (public trades + ledger).** 05:52:16.9 UTC one taker sold 488 YES
contracts in KXBROSFT-26OCT08-T107, taking every bid from 0.82 to 0.77 in one
match. Our 30-contract bid at 0.82 was 200 behind (reading steady, depletion 0
for 86 s). Afterwards the best bid was 0.06; the exit rests at 0.90 and the
D-exit rule holds rather than cross at a loss above $8. Across all 16 entry
fills since 2026-09-23, each was one taker order spanning 1–4 levels (59–1,810
contracts); 15 of 16 markets had no trade in the preceding 60 s. No reactive
cancel logic can avoid these. Realized P&L since 2026-09-22: −$13.58 (fees
$1.40); no reward payout reconciled yet.

Pre-quote history (the week before each market's first entry, 220 markets):
swept markets median 2,418 contracts traded vs 400 for the rest. Skipping
markets above ~2,000/week would have kept 170/220 markets and avoided 8 of 15
swept markets; lower thresholds removed markets without avoiding more. Four
swept markets had no prior trades (not predictable by volume). One week, small
sample: a recommendation, not an accepted rule.

## 209. First 30-contract entry refused by a third hard-coded size gate — 2026-09-26

**VERIFIED.** 04:43:19 UTC, first entry pair (KXBKFT-26OCT08-T99, 30 each side):
`LiveSession.check` still required count 10 and raised after the commands were
durably SENDING; both were recorded UNKNOWN (no response, no venue order ever
enumerated), the runtime failed, and every later recovery was blocked by the
unresolved mutations while the safety pause held entries off. Offline tests
never exercised the real live-session gate. A sweep found one more (reprice
completeness required quantity 10). Repairs: D-143; a regression test now uses
the real `LiveSession.check`.

## 208. The $300 deposit blocked trading and left entries unprotected — 2026-09-26

**VERIFIED.** A $300 applied deposit at 03:33:26 UTC raised venue cash to
$786.85 while expected cash stayed $486.85. Release reported
`accounting_cash_unexplained` and `cash_activity_unattributed`; recovery
exhausted at 03:34:05 and entries stayed blocked. Design review: no supported
path accepted post-baseline funding (baseline immutable), and reward payouts
(no API record) would block identically. Fill-risk sampling stopped (zero
samples after 03:34), so 30 resting entries were unprotected; the operator
stopped the bot (all 30 canceled by 03:40:49). The stop could not prove flat
without a current account and reached `shutdown_timeout`; only the exact
verified child PID 43064 was then terminated with operator approval.
Repairs: D-141 (cash attribution, safety pause, self-recovery) and D-142.

## 207. Startup allowance and own-order renewal fallbacks — 2026-09-26

**MEASURED — startup margin.** Child start to `runtime_started` took 55.9 s
(gen 172) and 58.0 s (run `bbc9c839`, stopped by the supervisor's 60 s
`startup_timeout` although it recovered normally); the successful retry took
56 s. Time is candidate discovery with 4–7 public `/markets` 429 retries plus
a 16–20 s quota refresh. Automatic crash restarts share the same margin.

**MEASURED — own-order renewal (run `c4cd469d`, first 10 min).** 21 attempts,
8 completed, 13 escalated, all logged `source_changed` with no retry, so the
snapshot was not explained, yet positions were flat. The log did not say which
condition failed. INFERRED: the just-acknowledged order was not yet listed by
REST, which the writer audit reports as a missing owned order/unbound intent.

**OBSERVED, no change:** one `rest_failed` 404 for a single-order lookup
02:20:17 during a post-drain recovery; that pass stopped (`missing_orders`)
and the next succeeded. Faster recovery now reaches the venue while a cancel
is still settling; 404 is still never treated as canceled.

**Repair (D-136):** supervisor startup allowance 180 s (work-deadline cap kept
at 60 s as its own field). Own-order renewal logs a fixed reason
(`position_changed`, `cash_changed`, `position_mismatch`,
`order_not_visible`, `audit_blocked`); only `order_not_visible` (audit
blockers limited to a missing owned order or unbound intent) retries, at most
three times, before full recovery.

## 206. Protective withdrawals: mostly false alarms, cost is the lockout — 2026-09-26

**Scope:** Generation 172 child log (00:20–01:35 UTC), a read-only ledger copy
and Kalshi's public trade history (unauthenticated `GET /markets/trades`, 14
requests) for the markets behind the 34 withdrawal cancels still in the hot
ledger.

**MEASURED.** 168 withdrawal events in 30 markets (bursts of about three per
episode); the same markets repeat every 8–15 minutes. Of 12 re-entries, 11
returned at the same price after a median 6.6 minutes. In 12 of 13 withdrawn
markets there were no public trades at all from 2 minutes before to 15 minutes
after the withdrawals (one market had none in 24 hours). The depletion
signal came from other makers cancelling, which the book feed cannot tell
apart from trades.

**MEASURED — one real save.** KXWMTCC: the 0.90 ask was withdrawn at
01:32:44; 6.6 s later a buyer swept 110 contracts at 0.90, then 100 at 0.97.
The trigger fired on makers pulling liquidity before any trade, so a
trade-only depletion model would have missed the only real threat. The trigger
is therefore kept.

**Cost:** each withdrawal locked the market for a fixed 300 s plus ~1.6 min of
cycle/refill, roughly 17% of quoting time across the 30 markets in this
window, almost all after false alarms. The real sweep came within seconds.

**Repair (D-135):** an adaptive lockout: 60 s after the first withdrawal in
a market, doubling for each repeat within the hour (60→120→240→300 s cap), and
reset after an hour without withdrawals. Trigger, cancel path, dwell and
ranking are unchanged. The live effect on downtime, churn and adverse fills
is a HYPOTHESIS until measured.

## 205. Own-order renewal and chained recovery (D-134 items 1, 4) — 2026-09-26

**Root cause (VERIFIED in code):** every private event and every command
acknowledgement advanced the account revision, and release accepted only
history receipts bound to the current revision. Each accepted order therefore
discarded the whole receipt chain and forced a full recovery that re-enumerated
fills from the opening boundary (Finding 203: median 4.28 s, ~27% of time).

**Repair:**
- *History floor.* The account owner keeps the revision of the last economic
  invalidation. Only an order update whose durable receipt is owned and has
  no fill gap, and the transport acknowledgement of the bot's own command
  (every leg of a batch), advance the revision without moving it. Fills,
  positions, foreign/unsettled orders, rejected/uncertain outcomes,
  reconnects and every other invalidation move it. Release accepts receipts
  from source revisions in [floor, current]; generation, writer epoch,
  private-epoch and all coverage checks are unchanged.
- *Own-order renewal (item 1).* After an acknowledged own command, the live
  refresh owner waits 0.3 s for the venue's order updates, then runs the
  existing routine renewal from the last released proof: fresh snapshot,
  empty history tail from the chain end, fresh cash/settlement/transfer
  sources and the unchanged writer release. Positions must equal the proof's,
  only working orders (and cash only with them) may differ, and the writer
  audit must be consistent. A changed position or cash, a nonempty tail or a
  rejected release escalates to full recovery immediately; a racing
  non-economic update retries at most three times.
- *Chained recovery (item 4).* While the floor is unchanged, full recovery
  enumerates only after the last released chain instead of from the opening
  boundary. Chains are capped at 100 receipts; a failed chained pass always
  restarts from the boundary; economic events always re-prove from it.

**Residual (unchanged class, D-068):** a fill hidden from both the private
stream and REST history can go unnoticed until either reports it; the old rule
re-read history after each own order but could not detect a fill neither
source reported either.

**Verification:** 16 focused tests (renewal success, changed position with and
without ledger agreement, cash without order change, bounded race retries,
floor movement per event kind, release rejection of pre-floor receipts,
chained and failed-chained recovery, batch acknowledgement ordering); five
guard mutations each caught. Live effect is a HYPOTHESIS until measured.

## 204. Ledger query cost and recovery overlap (D-134 items 2, 3, 5) — 2026-09-26

**Scope:** Read-only copy of the live `account.db` (1,581 orders, 3,183
command authorizations, 3,163 mutation attempts) and offline tests.

**MEASURED — order settlement scan (item 2).** Every account snapshot settles
all stored orders: 0.09 s per scan, three to four scans per full recovery,
growing with order history. Most cost was re-validating unchanged stored order
text and three queries per order. Now: validated payloads are reused
(bounded, process-local), orders/intents/fill totals are read once per scan,
and credit/episode cleanup is skipped only for clients a start-of-scan
superset proves cannot need it. 0.09 → 0.03 s; receipts and all ledger effects
are byte-identical to the per-order path on the production copy.

**VERIFIED defect — missing indexes (item 5).** A sweep of every SQL statement
against the production copy found full-table scans on hot paths:
- managed-exit lookup per active order (market inventory, single-order
  settlement, reducer checks): 9.6 ms per market query → 0.02 ms;
- release check of sending/unknown mutations: 2.4 → 0.02 ms;
- orders by market (exit basis, position-cost stream): 1.0 → 0.02–0.05 ms;
- managed-exit classification per scan: 4.2 → 0.13 ms.
Market inventory for 14 markets: 117 → 13 ms. Four indexes were added; results
are identical; integrity check ok. An account-scope expression index was
rejected because it misled the planner on another query. Remaining scans are
deliberate whole-ledger audits/archival.

**Item 3.** The history download (pure REST) now starts concurrently with the
first recovery snapshot. Its import still runs afterwards under the ordinary
reconciliation token and records the real read start, so receipt coverage is
honest; any private event or reconnect in between discards it and downloads
again; a failed/stale first snapshot never leaves it running.

**Found while designing items 1 and 4:** every private event (including the
bot's own order acknowledgements) advances the account revision, and release
accepts only history receipts bound to the current revision (D-068). That is
why every accepted order forces re-enumeration from the opening boundary.

## 203. Full recovery after accepted orders — where the time goes — 2026-09-26

**Scope:** Generation 172 child log (first ~15 minutes after deployment, 35
repaired passes), saved status and a read-only copy of `account.db`.

**MEASURED.** Full recovery (every accepted create/cancel still requires it,
per D-113) took median 4.28 s: 1.22 s to the first `history_enumerated`
(first venue snapshot plus full history from the opening boundary), 2.69 s
(p90 3.10 s) between the two history events, 0.30 s to release. One
annotated pass: pending fills/order lookups/second venue snapshot ~1.8 s,
management refresh ~0.4 s, tail snapshot with financial sources ~0.9 s.
Routine renewal's joined snapshot-and-tail took 1.19 s. On the ledger copy
(1,581 orders), the full order settlement scan run inside every snapshot
takes ~0.09 s; the audit scan is of the same order. No pending fills and no
missing-order lookups occurred in the sampled passes.

**VERIFIED redundancy.** After the first snapshot, history recovery always
clears the account report, so a pass read the venue a second time before
management even when only local history/settlement work had happened. The
tail snapshot read afterwards already must match that report's signature
before any release.

**Repair (D-133):** when no pending fill, no missing-order lookup and no
private event, reconnect or other reconciliation occurred since the first
snapshot, that snapshot (still inside its original 5 s bound) is re-audited
against the repaired ledger instead of re-read. Any blocker, mismatch, age or
source change falls back to the ordinary read. The tail snapshot is required
and must match the first snapshot, so the unchanged-venue window is now
first→tail rather than second→tail. Expected saving is one venue snapshot and
its writes per pass (INFERRED ~0.5–1 s); new status `recovery_phase_ms` and
`recovery_final_reaudits` measure it after the next deployment.

**Not changed:** accepted orders still force full recovery. Letting routine
renewal absorb changes explained exactly by the bot's own acknowledged orders
would remove most of the remaining recovery time but changes D-113's
"source changes require ordinary recovery" boundary; that needs an operator
decision.

## 202. Final pre-restart review and live-log check — 2026-09-25

**Scope:** Read-only analysis of generation 170's retained child log
(18:15–23:46 UTC, 265,848 events: 0 ERROR, 123 WARNING), parent log, saved
status and a read-only ledger copy; final review of all D-129–D-131 changes.

**VERIFIED defect — passive exit churn.** The first live fill-and-exit cycle
(`KXWYCOAL-27APR01-T210`: bought 10 YES at 0.33 at 22:51:42; exited by taker IOC
at 0.31 at 23:07:18 after the 900 s age limit; −$0.35 incl. $0.15 fee) shows
the passive reducer (ask 10 @ 0.33) placed and canceled 16 times in 15 minutes,
each copy living 10–50 s and losing queue priority. Only one reducer existed at
a time. Offline replay of the real planner reproduces a cancel whenever the
target moves off 0.33 (e.g. a competing ask flickering at 0.32); the book
states were not logged, so the flicker is a HYPOTHESIS. Repaired (D-132): a
lone exact reducer is kept until a new target has persisted 5 s; IOC/deadline
modes and all other cancels are unchanged; status reports hold/release counts.

**MEASURED, not a code defect — sweep fill.** For a minute before the fill the
order had 250 contracts ahead, depth 251 and zero depletion; within 6 s the
level was swept and the order filled. A depletion-rate estimate cannot foresee
a single sweep. The same market filled adversely earlier (15:32→15:48, −$0.95)
and remains in priority candidate memory; any post-fill cooldown is a strategy
decision.

**Other log observations:** 41 routine renewals failed on source change and 17
on read-quota rollover waits (both escalate to full recovery; the first class
is addressed by D-130); entries were allowed in a minority of health samples
(recovery churn); engine backlog median 20.5, max 623; no reader, writer,
engine, quota, REST or mutation failure; supervisor parent log clean.

**Final review:** my own reprice edit had displaced the Command 1
`flatten_at` initializer below a `return`, breaking 52 tests and hanging one
suite; the release gate caught it before publication and it is fixed. A
package-wide scan finds no other unreachable statements. Complete release
suite: 1,877 tests in 293.6 s, no failures, one expected Windows skip.
Production-ledger copy: archival 194 rows in 216 ms, integrity ok, financial
hash unchanged, cold writer start ok.

## 201. D-131 items 7–9: concurrent withdrawals, repeat tracking, Command 1 — 2026-09-25

**Item 7:** a threatened market now latches immediately as a secondary
protective cycle (at most 4 cycles total) instead of waiting for the primary
cycle's full terminal/fill reconciliation. Each latched cycle keeps its own
D-128 retry/backoff/escalation record; cancels still dispatch one at a time;
post-cancel reconciliation and every recovery pass wait until no latched pair
has a cancelable leg (bounded 5 s). Durable per-order cancel checks prevent any
duplicate send. Secondary cycles end when durable inventory no longer holds
their IDs, or hand over to inventory policy on a fill. Two-market synthetic
test: both pairs' four cancels ACK, none sent twice, reconciliation starts only
after both drains complete. Existing single-cycle D-128/D-127 suites unchanged.

**Item 8:** per-market withdrawals in the last hour are counted (bounded) and
reported in status and on each `fill_risk_withdrawal` event. Measurement only;
no threshold, cooldown or ranking change (operator decision after data).

**Item 9 (D-116 Command 1):** the preserved `data/command1-dev` work (left
untouched) was ported onto current code: generation-bound flatten request,
immediate exit deadline applied to current and refreshed terms of an
entry-paused owner, existing exact reduce-only IOC path, correlated
verified-flat receipt, supported relaunch and readiness check, bounded
timeouts with explicit blockers. Review fix: a malformed/unreadable request
file no longer crashes a draining owner (treated as no flatten). Status-field,
stop-receipt and launch-receipt contracts verified against current code.
Operational note: `Restart-LiquidityBot.ps1 -Flatten -Live` closes open
inventory at available prices; ordinary stop/start does not.

**Verification:** complete release suite 1,873 tests in 284.5 s, no failures,
one expected Windows symlink-privilege skip. Synthetic fixture 30 orders in
8.465 s, refill 0.538 s, risk refill 1.580 s (offline only).

## 200. D-131 items 2–6: fixes, remaining-code review and a clock bug — 2026-09-25

**MEASURED/VERIFIED — quota clock drift would stop all reads after ~31 h.**
Child log timestamps (run `587e5d6e…`) show wall minus monotonic time
drifting linearly by −316 ms over 4.95 h (~64 ms/h, ~18 ppm). `QuotaGuard`
compared each sample with its construction anchor against a 2 s tolerance, so
any run lasting ~31 h would enter the sticky `clock_fault` state: no reads,
no account proof, no recovery. Earlier runs restarted before that. Fixed by
comparing successive samples; a real step is still a sticky fault (existing
test kept). The supervisor's own clock check uses its last persisted sample,
refreshed by heartbeats, so it does not accumulate drift; a large time-sync
step still stops it for attention (fail-closed by design).

**Items 2–3 (history proof cost/limits):** full recovery must re-prove fills
from the opening boundary because release requires receipts from the current
account source revision (D-035/D-068). Moving that start forward is an
operator decision. Implemented within the rules: fills already stored with
exact time are no longer replayed through the writer each pass (staging still
compares every enumerated fill); `history_scope` status and a sampled
`history_scope_high` warning at 5,000 rows or 2.5 s, versus the 10,000-row and
5 s limits. At ~11 fills/day the hard limit is years away.

**Item 4 (entry churn):** a standing rule forbids sending on a book changed
since pricing, so the send-edge check is unchanged. D-130 removed the recovery
churn that caused most aborts; every block detail reason is now counted
exactly in status for post-deploy attribution.

**Item 5 (unbounded rows):** v2 command archives now move the episode row
itself out of the hot table (4,263 orphan fee rows and 3,124 episode rows
observed live); orphan fee bounds (no remaining intent) are swept in bounded
batches during reclamation. Production-copy check: archival 225 rows in
287 ms, integrity ok, financial hash unchanged, cold writer start ok.

**Item 6 (review coverage):** read in full this pass: transport, book
refresh, quota, write budget, management, selection, selection runtime (part),
live startup/supervise, supervised child (part), process supervisor (part).
Whole-package scans for naive time, float money, unbounded long-lived state
and capacity-raise patterns found no further defect (position updates are
bounded by the 1,024-market scope; the metadata cache is unused in
production). Not read line by line: supervision/store/control/protocol,
Windows IPC, incentives, ranking, admission (unused in broad mode), reward
tracker/checkpoint, opening account, candidate preparation, bulk inputs,
metadata scheduler, REST remainder.

**Verification:** complete release suite 1,857 tests in 340.3 s, no failures,
one expected Windows symlink-privilege skip; each new regression fails with its
change reverted.

## 199. Pre-deployment review of D-129/D-130 — 2026-09-25

**Scope:** Exact review of every source change since `b8ef3a8`, plus a fresh
disposable copy of the live ledger. No live action; the canonical runtime
checkout was not modified.

**Defects found and fixed (each reproduced by a failing test first):**
- The busy-shard catch-up ran the engine's fail-closed owner check before the
  existing stop/private deferral, so a normal stop landing during a market
  evaluation would have been recorded as an engine failure. The deferral now
  precedes catch-up.
- Command-archive housekeeping ran inside the entry reservation; any
  unexpected validation error would have poisoned the sole ledger writer and
  stopped the bot. It now runs in its own savepoint; a failure rolls back only
  the archive attempt, is counted process-locally, emits
  `command_reclaim_failed`, retries after 60 s, and ordinary capacity limits
  still bound entries.
- After a rebase, reward-scoring joins (bound to the exact report object)
  would read UNKNOWN until the next timer; the rebase now requests an
  immediate rejoin, as routine renewal does. Fill-risk queue anchors were
  already independent of report identity.

**Checked, no change needed:** rebase never extends the accounting lease or
the snapshot's 5 s bound; the report is already non-current between prepare
and abort, so deferring the fallback recovery to the post-turn step exposes
no stale proof; routine renewal/recovery in progress owns the gap; transport
invocations, failed owners and ACK/REJECTED/UNKNOWN turns keep the old path;
archived episodes carry no fills, positions or pending evidence, so cash,
settlement, history and audit paths are unaffected.

**Deployment constraints (VERIFIED):** the supervisor recomputes the build
fingerprint from the package files and refuses an automatic child respawn on
mismatch, and the running child imports some modules lazily. Updating the
canonical checkout while the bot runs could therefore mix code versions or
turn an automatic crash recovery into an attention stop. Deploy only through
the supported stop → fast-forward → start path. Once a version-2 archive or
`ARCHIVED` episode exists, pre-D-129 code cannot open the ledger; take the
usual integrity-checked backup before the first start, and treat rollback
after trading as unsupported.

**Verification:** fresh production-ledger copy (3,990/2,119/1,981 hot use):
first pass archived 182 rows in 248 ms; `integrity_check` ok; financial,
risk, accounting and history hash unchanged; cold writer start validated.
Complete release suite: 1,853 tests in 340.7 s, no failures, one expected
Windows symlink-privilege skip. Synthetic fixture: 30 orders in 10.094 s,
refill 0.829 s, risk refill 0.992 s, cancel-pair gap 0.03 s (offline only).

## 198. Recovery churn blinded fill-risk checks; D-130 repairs — 2026-09-25

**Scope:** Read-only analysis of generation 170's retained child log (run
`587e5d6e…`, 17:51:44–22:19:41 UTC, 230,105 records) plus offline repairs.

**MEASURED — recovery occupied 37% of the run.** 1,121 full-recovery starts
(907 `mutation_persisted`) and 1,048 repaired passes totalling 6,011 s of
16,077 s. Of the 907 `mutation_persisted` passes, 606 followed a command that
never reached transport (pre-send proof denial) and 33 a post-send proven
abort; only 268 followed an ACK. 436 commands reached SENDING. VERIFIED code
path: every non-failed denial called `after_outcome` → `_revoke()` +
`request_recovery('mutation_persisted')`, and any prepare/abort advances the
writer revision, which invalidates the account report.

**VERIFIED — why threats latched late.** At 18:06:34.015 both legs of one
market showed zero protection ahead (`fill_risk_sample` threat), but four
back-to-back ~5.5 s recoveries followed and the withdrawal latched only at
18:06:59.911 (25.9 s). Queue-position reflection requires a current account
report; each recovery removes it, and the 5 s queue proof then expires
(`queue_expired`/`queue_missing` gaps). `_start` also refused to latch any
withdrawal while any command (e.g. another market's entry) was in flight.

**D-130 repairs (offline, verified by regressions that fail when reverted):**
1. After a turn with no transport call, the dispatch owner re-audits the
   unchanged venue snapshot at the new writer revision (new read-only writer
   command) and re-anchors routine renewal. Original observation time and
   5 s bound are kept; any private ingress, reconciliation, stale snapshot,
   interleaved write or transport call falls back to the old full recovery.
2. Every recovery cause joins a pending protective drain before starting a
   pass (bounded 5 s; never suppressed).
3. A fill-risk withdrawal latches during another market's command (it still
   joins a command for its own market).
4. A continuously busy book shard no longer defers all of its markets'
   evaluations: one bounded catch-up is applied and the market evaluated
   only if that drains the queue.
5. Diagnostics: batch `order_count`/`rejected_count` and two entry-block
   reasons are retained (a static test now rejects any dropped literal field);
   maintenance cycle start/finish events with a fixed reason vocabulary;
   owned markets stay visible (UNKNOWN) while plans are rebuilt, with a
   coverage summary; routine metadata publications (58% of all log records)
   are sampled with exact per-market counts.

**Verification:** complete release suite 1,851 tests in 331.1 s, no failures,
one expected Windows symlink-privilege skip. Synthetic four-shard/1,024-market
fixture: 30 orders in 10.351 s, refill 0.805 s, risk refill 0.931 s,
cancel-pair gap 0.040 s (offline only). Three existing tests that encoded the
old behavior were updated deliberately (engine stale-book wait, send-edge
UNKNOWN, recovery request timing).

**Reviewed, no change:** the lost entry retry (existing recovery, renewal,
dispatch-result and maintenance wakes re-arm it; blocked proposals are
intentionally not hot-looped); five startup `/markets` 429s (adaptive pacer
recovered within 6 s; no documented unauthenticated limit to target).

**Open (not fixed):** full recovery still re-enumerates all fills since the
opening boundary inside a 5 s evidence token; fine at 34 fills, unbounded over
time. Remaining modules (supervisor/Windows IPC, selection/ranking, rewards,
incentives, REST/quota internals, startup wiring) were not all read line by
line. Live effect of these repairs is a HYPOTHESIS until measured after an
authorized deployment.

## 197. D-129 repairs for Finding 196 — 2026-09-25

**P0 capacity:** Reproduced offline: a tiny-policy ledger with two terminal,
zero-fill episodes denied the next entry with `capacity_entries_held` before the
repair and admits it after, reducing hot mutation/intent/order use to 1/1/0.
On a disposable copy of the running production ledger (hot use 3,957/2,111/1,955
at copy time), ten bounded passes archived 1,280 episodes and 72 proven-unsent
creates in 169–250 ms each and stopped at 3,029/1,611/1,527, below the 75%
trigger. `integrity_check` passed, a hash over every financial, risk,
accounting and history table was unchanged, and a cold writer start validated
all archives (full capacity validation about 0.4 s). MEASURED on that copy only;
live timing will vary. Episodes with any fill, pending fill or position stay hot.

**P1 fill-risk budget:** The regression starts a warning ten seconds before
latching; the budget sample is now 0.25 s (latch-to-ACK) and the budget stays
at its 2-second floor, while `elapsed_ms` still reports ≥10,250 ms and a new
`latch_ms` field reports 250. The live effect on withdrawal frequency is a
HYPOTHESIS until measured after deployment.

**P2 order projection:** 5,000 resting-then-canceled receipts leave the
projection empty (it raised at 4,096 before the repair); working and
fill-pending orders stay visible.

**P3 send edge:** A lease lost after quota consumption now records `NOT_SENT`
without entering the transport, matching the batch path; the executor is not
held. The prior regression expecting `UNKNOWN` was updated deliberately.

Each new regression fails with its source change reverted (P0 by the boundary
denial, P2 and P3 checked by reverting the file). Complete release suite:
1,836 tests in 279.6 s, one expected Windows symlink-privilege skip.

## 196. Source review: command-ledger entry capacity will run out again — 2026-09-25

**Scope:** Read-only source review plus read-only (`mode=ro`) SQLite counts from
the live ledger and saved `status.json` at 21:48 UTC. Read in full: `values`,
`ledger`, `accounting`, `account_release`, `risk`, `orders`, `portfolio`,
`exits`, `adapters`, `books`, `quoting`, `execution`, `writer`,
`command_capacity`, `dispatch`, `dispatch_sources`, `runtime`,
`quote_maintenance`, `fill_risk`, `engine`, `mutation_outcomes`,
`mutation_transport` and `account.py` lines 1–420. Selection/reward/metadata,
REST/quota/write budget, transport, supervisor/Windows IPC and live composition
were checked only by targeted search for capacity-failure sites, not line by
line. No code, configuration, order, restart or test run.

**P0 — entries will block on `capacity_entries_held` within hours.** VERIFIED
counts; INFERRED timing. `reserve_entry_capacity` blocks every entry once hot
`mutation_attempts` reaches the 4,096 ordinary-entry boundary; D-125 archives
only `NOT_SENT` creates. At 21:48:08 UTC hot mutations were 3,905 (140 held).
Of these, 3,867 are not archivable: 1,947 ACK creates, 1,793 ACK cancels, 121
rejected and 6 unknown; only 38 are `NOT_SENT`. Non-archivable rows added per
UTC hour 15–21 were 166, 160, 232, 160, 128, 94 and 78 (48 minutes). The 229-row
headroom implies exhaustion around 23:00–01:00 UTC at these rates. Pre-funded
cancel/reducer credits remain, so existing orders still drain, but no new pair
can be admitted and occupancy decays silently — the Finding 188 symptom again.
Further walls follow: `order_evidence` 1,947 used + 56 held and `intents`
2,069 + 56 against 4,096 each (about 1–2 days at today's ~980 orders), and
`command_history_archives` 9/128 at roughly one per hour (about 5 days), after
which even `NOT_SENT` reclamation stops. Keeping all ACK/rejected/unknown rows
hot is incompatible with continuous churn. Raising limits only delays this;
archiving exact terminal evidence of retired episodes would need its own
operator decision and digest/validation contract.

**P1 — fill-risk cancel budget absorbs serialization delay.** VERIFIED code;
MEASURED live value; HYPOTHESIS effect. `QuoteMaintenance` holds one global
`cycle`; `_fill_risk` returns without latching a second threatened market while
a withdrawal cycle exists, and the cycle ends only after terminal/fill proof
plus a current account report. `_start` sets `_cycle_started` to the first
warning (`_risk_since`), and `dispatch_result` feeds warning-to-ACK time into
`FillRisk.cancel_seconds`, whose p95 (floor 2 s, last 128) sets every order's
withdrawal horizon. Waiting behind another market's cycle/recovery therefore
widens all horizons. Saved status at 21:43 UTC: `cancel_budget_seconds` 8.667,
horizons 16.3–17.5 s. Wider horizons can cause more withdrawals and more
serialization. This is a plausible contributor to the 25.9-second latch delay
and repeated withdrawals in Findings 194–195; replay two concurrent threats and
compare budgets measured from latch versus warning before changing policy.

**P2 — account order projection is never pruned.** VERIFIED code; INFERRED
timing. `AccountCoordinator.order_states` clears only on account reconnect.
`_store_order` raises at 4,096 distinct orders inside `on_event` /
`apply_pending_fill`; that exception leaves the engine's private handler, fails
the engine and ends the runtime. The current account epoch (opened 17:52:36 UTC)
holds 268 orders; at roughly 70/hour, about 2.4 days of continuous connection
would trigger it. Frequent restarts currently mask it.

**P3 — lower-severity observations:**

- `execution.py:857` raises `CommandDenied('accounting_lease_stale')` after
  SENDING without the proven-unsent abort used by the adjacent checks and the
  batch path; the command is recorded UNKNOWN and the executor stays held. The
  window is synchronous and narrow.
- `_ranked_entry_turn` clears `_entry_dirty` before `propose` and does not
  restore it on a blocked proposal; this confirms the existing refill item.
- `EventEngine.step` re-marks evaluations while their shard queue is nonempty;
  a continuously busy shard can starve evaluations (HYPOTHESIS contributor to
  `book_queue_pending`).
- `WindowRisk.release_previous` commits with `with ledger.connection` rather
  than `ledger.transaction()`; callers were not checked for nesting.

No defect was found in matched P&L/cash arithmetic, order-version regression
checks, exit crossing/IOC direction or the pair reservation transaction.

## 195. Overall generation-170 log review — 2026-09-25

**Scope:** Local read-only review of child run
`587e5d6eaf2044afbff1ae5ba6632f3b`, frozen at sequences 1–112,742,
13:51:44.724–16:07:03.743 ET. All 112,742 sequences were present, with no
malformed records: 112,684 INFO, 58 WARNING, zero ERROR/CRITICAL. Later status
samples below are separate observations. No venue requests, financial-ledger
inspection, order actions, source changes or restart were performed.

**Observed working:** Both exact managed processes remain present in generation
170; supported local supervisor status reports current presence and a recent
saved heartbeat, no attention reason/holds and one launch attempt. Parent run
`bca43cfc747946ef8ed36a6717718ac9` contains startup and no failure/exit event.
All six child readers remain subscribed on their first connections, all four
book failure counts are zero, dispatcher/engine are nonfailed, and logging has
zero drops. All 39 quota refreshes completed; incentive discovery has no failure.
The initial ranking covered 1,024/1,024 selected markets. These observations
establish current operation, not tested crash recovery or perpetual uptime.

**P1 — protective scheduling still has a recovery-entry race:** All 78 logged
protective withdrawals have 156 cancel ACKs. Across these legs, recorded
first-warning-to-ACK median/p95/max is 1.220/11.100/27.478 seconds;
latch-to-ACK is 1.099/3.787/4.602 seconds; submission-to-ACK is
0.215/0.353/0.510 seconds. Warning timestamps can span unknown intervals and do
not prove a continuous threat. The first zero-ahead sample at sequence 11,325
is followed by several recoveries before the withdrawal latches at 11,732,
about 25.9 seconds later. Preserve fresh revalidation while investigating the
time before latching, not just cancel transport or the second-leg retry.

There is also a concrete scheduling overlap: first cancel ACK at sequence
100,272 (15:52:00.952 ET), routine-refresh failure at 100,279, full recovery
start at 100,280 (15:52:01.238), second cancel ACK at 100,300
(15:52:02.638). Twelve of the 78 pairs have recovery-start events between their
two ACKs: ten `routine_refresh_failed`, one `quota_restored` and one
`mutation_persisted`. `_refresh_routine_account` requests recovery on failure;
`_recover` joins the dispatcher's current active operation but does not inspect
`source.risk_drain_pending` before starting. An isolated invocation of that
actual method with an idle mocked dispatcher and pending risk drain reaches
`recovery_started`; the probe stops there without I/O. D-128 protects the
watchdog/post-drain request path, but not this alternate entry to full recovery.
Replay the real dispatcher plus an already-running routine renewal before
repairing; preserve bounded escalation for ambiguous/permanent cancel outcomes.
This overlap is verified, but it does not by itself explain all pre-latch delay.

**P2 — recovery/refill cost remains:** The frozen window has 653 recovery-start
events, 612 repaired passes, 33 incomplete warnings, 19 proven-unsent mutations
and no unknown-mutation event. Repaired-pass duration median/p95/max is
5.471/6.519/7.572 seconds. The 20 routine-refresh warnings comprise 18 source
changes and two quota waits; every one is followed by a repaired pass within
5.255–10.574 seconds. The 134 periodic health samples show entry allowed in 46
and unavailable in 88; 72 omit order counts. These samples are not an exact
time-weighted availability measure. Existing Findings 193–194 own slow refill
and missing batch-result detail; counts cannot replace stage timing.

**P2 — reward visibility and reference-price coverage are incomplete:** Reward
reflection reports 1,466 completed joins, zero failures, 148 superseded joins,
766 deferrals and three quota deferrals; 134 checkpoints saved with no failures.
Those counters do not prove continuous per-order reward evidence. In 16 local
status samples at 16:08:15–16:08:45 ET, reward progress reported 0–13 rows while
26–28 entries were reported; only two samples had any ESTIMATING row (one/two),
the rest reported UNKNOWN rows or none. `RuntimeRewards._progress_status` walks
the transient management-plan cache, so a missing plan can omit an owner from
the report. Historical checkpoint totals span earlier runs and idle intervals;
do not interpret accumulated UNKNOWN seconds as this run's lost income.

A separate 12-sample check at 16:10:33–16:10:55 ET reported 28 entries with
7–13 maintenance rows. Available quote-status fields said full price weight,
but some rows' validity had expired and several owners had no current scoring
row. These explicitly historical samples cannot prove all orders are currently
at reference price. No drift dwell was present in those samples. Logs do not
identify ordinary maintenance-cycle reasons and completion well enough to prove
an actual cancel/reprice/reentry cycle. Keep unknown owners visible, add bounded
source-gap/coverage and cycle diagnostics, and exercise expiry/drift/reentry
with current proofs before claiming complete repricing coverage. UNKNOWN is
neither zero rewards nor permission to assume a scoring quote or change prices.
No paid reward/payout reconciliation or profitability is established here.

**P3 — startup throttle and diagnostic load:** All five REST retry warnings are
HTTP 429 on public `/markets`, confined to 13:51:51–13:51:57 ET; initial discovery
subsequently completed. Authenticated read-budget status shows zero throttles;
that does not cover this public startup client or local write-budget waiting.
The run emits 64,503 `exit_inputs_published` events (57.2% of records) and 18,976
inventory-plan changes. This suggests a targeted review of repeated publication
and log volume, not proof of wasted REST requests or CPU saturation. Retain
bounded disk use, safety-event visibility and source-expiry semantics.

**Unexercised paths:** Every logged inventory-plan mode is `flat`; known health
samples have no positions, and the 16:07 status reports no positions or risk/
accounting holds and zero realized P&L for its current window. Without financial
ledger/venue reconciliation this does not establish that no fill ever occurred.
The run supplies no affirmative completed fill-to-passive-exit/IOC evidence,
loss-stop test, native crash/reconnect recovery test or reward payment evidence.
Record these as unverified live paths, not failures and not reasons to trigger
real fills/crashes for this review.

## 194. Refill review: logging omissions and evidence limits — 2026-09-25

**VERIFIED offline:** A disposable `Diagnostics` sink given a synthetic mixed
batch ACK (`order_count=1`, `rejected_count=1`) discards both fields because
`observability.NUMBERS` lacks them. `execution.py` emits these counts after
`record_batch_outcome`; a batch-level `mutation_ack` therefore does not prove
that both orders were accepted. The same sink removes `candidate_not_selected`
and `proposal_blocked` because `observability.BLOCKERS` omits them, retaining
only `unknown_blockers=2`. Actual run logs show the corresponding missing detail.
This is a diagnostic defect, not evidence of lost durable financial outcomes.
Add fixed-vocabulary fields and mixed-result regression coverage in later work.

**REVIEW CORRECTIONS:** Finding 193 previously mixed successive live log reads.
Reanalysis bounded to sequences 1–90,380 gives 67 withdrawals, 134 protective
ACKs and 13 repeated markets, rather than 68/136/14. All sequences are present.
Its 81 batch-shaped ACKs cannot establish 162 accepted orders because of the
logging omission above. The apparent `81*2-138=24` agreement is not a verified
order reconciliation. The saved three-candidate proposal is explicitly
`historical_only`; at the reported instant current account proof was absent.
It shows recently identified candidates, not three immediately executable pairs.
Zero read throttles and connected readers do not exclude local write-budget
waiting, scheduler load or proof starvation on busy shards.

**HYPOTHESIS TO TEST:** `runtime._ranked_entry_turn` clears `_entry_dirty` before
awaiting the proposal and leaves it cleared on several temporary failure paths.
However market evaluations, maintenance completion and dispatch-result wakes
already rearm work. This is not a reproduced lost-wake defect or established
cause of the live delay. Test a recovered vacancy without a new book tick,
alongside active public/private traffic, before changing retry behavior. Retain
bounded event-driven work and never retry an ambiguous submitted command.

**STRATEGY LIMIT:** Repeated withdrawals are measured, but a ranking penalty's
benefit is unproved. Withdrawal ETA uses conservative aggregate-depth depletion;
same-price cancellations behind us and temporary depth changes can overstate
loss of queue protection. Compare each warning's original queue age, depth,
depletion rate and cancellation horizon before recommending threshold or ranking
changes. Fresh cancellation priority remains required. These are saved future
work items; this review changes documentation only.

## 193. Eligible-market supply is not the resting-order bottleneck — 2026-09-25

**MEASURED:** Generation 170 run `587e5d6eaf2044afbff1ae5ba6632f3b`
produced 90,380 retained structured events from 13:51:44 through 15:39:53 ET.
Bounded reanalysis of sequences 1–90,380 finds 67 protective pair withdrawals
(134 correlated cancel ACKs) across 31 market references. Thirteen markets
recurred; the most repeated market was withdrawn eight times. There are 81
batch-shaped ACKs and 138 single-order ACKs. Batch accepted/rejected counts were
discarded by logging (Finding 194), so these events cannot reconstruct exact
occupancy. Saved status at 15:40:19 ET reported 24 resting entries, no positions
and a recent historical proposal containing three two-sided additions, while
current account proof was absent. Startup and withdrawals overlapped.

For 66 withdrawals with a correlated two-cancel completion and a later entry
batch, monotonic time from the second cancel ACK to the next *any-market*
batch-shaped ACK was median 46.084 s, p95 210.915 s and maximum 344.001 s.
Concurrent withdrawals and missing per-leg batch counts make this an optimistic
refill-attempt marker, not proof of restored slots. All 67 protective pairs have
two distinct cancel ACKs before their next same-market withdrawal; latch-to-last
ACK was median 1.439 s, p95 3.902 s, maximum 4.519 s. This excludes the earlier
warning-to-latch wait and is not a bound on total protective response time.

At 15:40:19 ET, all six readers remained on their first subscribed connection,
the shared read budget had zero throttles, dispatch and logging were nonfailed,
and logging had zero drops. The selector retained 30 priority-candidate hints
and its last proposal contained three `$2+` additions with no proposal blocker.
The runtime was instead in account recovery with entry authority revoked. The
latest candidate had then failed its send fence because its book revision changed.
This supports recovery and proof freshness as immediate entry blockers. It does
not prove all remembered candidates remain eligible, exclude local write-quota
waiting or establish whether more shards would improve processing latency.

**VERIFIED in source:** Admission ranks current candidates by gross hourly reward
and then capital efficiency; it does not include pre-entry depletion/fill-risk
history. A protective withdrawal applies only a 300-second market cooldown.
Ranked scheduling submits `proposal.additions[0]`, so vacant pairs are filled
serially. Ordinary entry mutation callbacks revoke entry authority and request
account recovery; latched protective cancels defer full recovery until their pair
drains. Dispatch then reproposes and rechecks management, account,
metadata, book and selection proof before send. By the 15:40 sample this had
produced 421 management-proof blocks, 319 send-proof changes, 135 proposal
changes, 10 missing-account-report blocks and one authority block, alongside
532 recovery starts, 499 completed repairs and 27 incomplete passes.

**INFERRED:** Frequent intentional fill-risk withdrawals create the vacancies;
serial recovery/revalidation and moving-book proof loss determine how long those
vacancies remain. Re-admitting repeatedly withdrawn markets is a candidate for
churn reduction, whose benefit needs testing. A repair must preserve current account/book
proof and cancellation precedence: first attribute the 46-second refill path by
stage, then keep bounded vacancy demand armed through recovery, and separately
evaluate a fill-risk/depth stability input to ranking. That ranking change is a
strategy decision and is not authorized by this diagnosis. No live action,
configuration change, restart or venue request was performed.

## 192. Lost protective-cancel key lets recovery overtake the pair — 2026-09-25

**MEASURED:** Generation 168's local structured events, 12:41:15–13:06:35 ET,
contain 20,374 records (30 WARNING, no ERROR/CRITICAL) and 36 correlated risk
cancel ACKs. Submission-to-durable-ACK median is 0.229 s, p95 0.394 s, maximum
0.563 s; this includes transport and persistence, not pure venue latency.
Withdrawal-latch-to-submission median is 1.768 s, p95 11.389 s, max 12.619 s.
The existing `elapsed_ms` starts at the first observed threat, including time
before a cycle can latch: median 2.220 s, p95 19.410 s, maximum 31.665 s.

The worst pair first warned at 12:49:42.273, latched at 12:50:01.116, submitted
its first cancel at 12:50:01.472 and ACKed at 12:50:01.683. A `post_drain`
recovery ran 12:50:01.953–12:50:07.231 with the second cancel still outstanding.
That cancel submitted at 12:50:13.735 and ACKed at 12:50:13.938. This locates
the delay mainly before transport; it does not prove every slow case has one cause.

**VERIFIED offline:** The real source/dispatcher fixture ACKs the first leg and
automatically queues the second. A temporary `account._processing` fence then
returns `current_candidate_missing`; the dispatcher consumes the key. Baseline
`47a0a92` treats the empty queue as drained and requests recovery, despite a
fresh source lookup still returning the second cancel. Earlier tests manually
submitted both keys and therefore did not exercise this lost-wake path.

D-128 retains cycle-scoped scheduling intent across temporary blocks, wakes it
from private-event completion or the existing refresh watchdog, and prevents
routine/post-drain recovery from mistaking an empty queue for a finished drain.
Every retry obtains new durable evidence and uses the existing quota/send fences.
ACK/UNKNOWN orders are never blindly resent. Source changes, cycle replacement,
terminal/fill handling, stop and bounded retry exhaustion are covered offline.
Warnings deferred by another mutation/cycle are marked for fresh reevaluation
at completion; old queue observations never become fresh authorization.

The actual supervisor and half-second watchdog replay resumes a temporarily
blocked second leg without manually submitting another key: ACK-pair gap
0.510 s, two transport calls, no duplicate and no intervening recovery. This is
a synthetic scheduler measurement, not a live venue latency guarantee.

**INITIAL LIVE CONTROL:** After Command 1 deployed `15b710e`, generation 170
completed three risk withdrawals. All six legs have correlated submission and
durable ACK records; warning-to-ACK ranges 0.345–2.037 seconds and
submission-to-ACK 0.193–0.238 seconds. Six temporary deferrals were retained,
the final status has no pending risk drain, and the run has no ERROR/CRITICAL
event through 13:57:04 ET. This demonstrates the repaired path operating in the
initial live window, not a future latency bound or fill-avoidance rate.

**Correction/limits:** Observation-gap emission counts are not seconds of blind
monitoring and do not directly prove the cause of churn. Missing observations
block that detection path; they do not automatically cancel resting orders.
Successful queue publication still requires the existing account join, with
original five-second expiry. D-128 does not loosen it or change reward ranking,
thresholds, capacity or the latency-based protection horizon. Sparse health
records with missing order counts are UNKNOWN, not zero occupancy. No absence
of ERROR logs alone proves cancellation efficiency. Initial live control evidence
is recorded above; sustained improvement remains unmeasured. STATUS owns
deployment and final verification.

## 191. Order-scoped warning survives report/reward renewal — 2026-09-25

**VERIFIED offline:** A synthetic real-writer/manager fixture seeds an exact
500-contract queue observation, invalidates the account report, refreshes owned
inventory and reduces visible protection to zero. Replaying baseline `5cf92c5`'s
maintenance method produces no withdrawal. The patched method, with unchanged
inputs, latches the exact owned pair. Both cancellations ACK through the existing
D-121 dispatcher without a report between legs; durable remaining quantity is
still 20 and entry stays blocked until terminal/fill reconciliation.

The 16 new observation regressions also cover missing reward metadata at queue
publication, WebSocket evaluation scheduling, original wall/monotonic expiry,
clock regression, changed writer/account/book/program/order identity, absent
book/inventory proof, private backlog, pending fills, position handoff, cache
capacity, cycle cleanup and bounded/correlated diagnostic events. Logging tests
check fingerprint correlation and unknown-value exclusion; a canceled-before-
submission fixture emits no transport-attempt event.

**Boundary:** Successful queue publication still requires the existing complete
account join; no extra read or longer lease is introduced. The consumer only
removes unnecessary dependencies *after* that publication. Missing/expired queue
or book evidence remains unknown. No live action, restart, ranking or threshold
change was performed. This repair does not prove the cause of Finding 190's
historical fill or promise avoidance of a future sweep. STATUS records final
suite results and publication/deployment state.

## 190. Fill diagnosis recheck: causation unproved; report coupling reproduced — 2026-09-25

**MEASURED:** Read-only ledger evidence for the generation-166 coal-market bid
shows a post-only ten-contract order at $0.41 acknowledged at 15:29:10.218 UTC,
filled at 15:32:36.510456 UTC (206.292 seconds later), and received durably at
15:32:36.642097 UTC. Its recorded fee is zero. There is no cancellation attempt
for that exact bid. This proves execution before a submitted cancellation, not
why protection failed to request one or whether cancellation could have won.

**CORRECTION:** The prior explanation attributed the fill to absent pre-entry
queue scoring and called 117 seconds of `incomplete_order_scope` logs unprotected
time. Neither causal claim is established. That logged field belongs to the
managed exit plan; maintenance checks inventory blockers and current source
joins separately. Two disposable real-owner probes demonstrate the distinction:
adding only that plan blocker still allows zero-depth withdrawal; invalidating
the account report suppresses a new withdrawal despite a fresh zero-depth book.
The latter is a verified coupling, not proof of this particular fill's cause.

**VERIFIED code/API:** Maintenance obtains queue evidence through reward-source
joins, which require current account, management, metadata and book evidence.
Exact queue evidence also binds the current report object. Previously latched
D-121 cancels have a separate exact-order drain path; these probes concern
detection before latching. The official [queue endpoint](https://docs.kalshi.com/api-reference/orders/get-queue-positions-for-orders)
returns positions for existing resting orders. Pre-entry protection can only be
estimated from visible depth, with a race before acceptance. Reference quoting
already uses cumulative target/5 depth; it does not guarantee continued queue
protection. More competing full-weight volume can reduce our normalized reward
share under the [official scoring rules](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program).
Both sources were rechecked on September 25.

**Recommendation, not an accepted strategy change:** First design and reproduce
an order-scoped risk-observation path that is not unnecessarily coupled to reward
or whole-account renewal, preserving fresh book/queue identity, exact ownership,
fill/reconnect handling and the sole cancellation writer. Add bounded evidence
for detection gaps, queue/depth observations and decision-to-send/ACK timing.
Then evaluate an advisory depth/stability tie-breaker within existing reward
tiers. Do not introduce an uncalibrated hard depth threshold or rank by raw
queue size alone. Greater competition and uncertain depth persistence are real
tradeoffs. Historical pre-fill queue trajectories were not retained, so a sudden
sweep versus missed earlier warning remains UNKNOWN.

**Verification:** Both new in-memory probes pass, and all 25 existing fill-risk
tests pass against disposable synthetic fixtures. No trading code, configuration
or process was changed. At 12:13:47 ET, saved live telemetry reported RUNNING,
28 resting entries, no positions, a nonfailed engine and healthy logging.

## 189. Full-cap snapshot refresh bypasses accounting renewal — 2026-09-25

**MEASURED, read-only local telemetry:** At 11:07 ET, generation 164 reported
30 resting entries, all six readers subscribed, 783 completed routine renewals,
235 completed steady snapshot refreshes, three reward-reflection failures and
52 superseded reflections. The retained errors identify `QuotaUnavailable`.
Recovery totals include ordinary mutation reconciliation and cannot alone prove
a fault, a crash or the cause of 28/30 occupancy changes.

**VERIFIED offline:** `_live_refresh` selected the full-cap snapshot-only path
before `_refresh_routine_account`. Snapshot reconciliation advances writer
revisions without releasing a new accounting lease, invalidating the retained
renewal proof and forcing a subsequent full repair. A failing-before timer test
reproduces that branch. D-126 prioritizes the existing accounting renewal and
still records the full-cap scope for optional market scheduling. A real-owner
fixture builds 30 durable orders and exercises two timer-driven renewals without
a full recovery request. Changed cash, private/writer revision, funding, stale
reads, stop and nonempty history tails retain the existing rejection behavior.

**VERIFIED diagnostic gaps:** Recovery causes were hashed despite being static
codes; incomplete passes omitted their stage; `book-2`/`book-3` were absent from
the stream allowlist. Reward quota loss was classified as a conflicting-data
failure and destroyed the interpolation endpoint. D-126 logs only fixed cause,
stage and outcome vocabularies, records checkpoint failures and samples repeated
entry blocks. Quota deferral removes operational reflection proof but retains
the old bounded endpoint; a six-second gap test remains entirely UNKNOWN.

**MEASURED deployment:** A later, separately authorized Command 1 operation
drained 28 orders to zero with no position, deployed `1777e41`, and started
generation 166. Its first observed 30 routine refreshes completed with zero
escalations. All six readers subscribed, 1,024 markets were ranked and 28 orders
were rebuilt with zero positions. Six startup REST 429 retries recovered; no
ERROR/CRITICAL event was present at the observation time.

**Limitations:** The initial source task left the live bot untouched; the later
Command 1 provided distinct deployment authority. Early live evidence is not
proof of indefinite uptime, fill avoidance, minimum reward attainment, actual
payouts or constant 30-order occupancy. Historical generic logs cannot attribute
every prior recovery request. STATUS owns final verification and publication
state.

## 188. Deferred command-history rollover blocked every new entry — 2026-09-25

**MEASURED:** After D-124 deployment, generation 162 had zero orders and zero
positions while all entry attempts returned `capacity_entries_held`. The ledger
held 4,124 mutations: 2,510 ACK, 1,487 NOT_SENT, 121 rejected and six unknown.
The fixed ordinary-entry ceiling is 4,096; total safety-command capacity remains
8,192. All 1,487 NOT_SENT rows are creates with unique client IDs, aborted
authorizations/intents, null responses, no order evidence and retired episodes.

**VERIFIED:** The command-capacity design intentionally retained all history and
deferred rollover. Raising limits or starting a fresh ledger would violate its
safety/accounting boundaries. D-125 instead archives only venue-unsent evidence
with exact intents, authorizations and owned credits. A stopped-ledger copy
archived 512 rows in 0.249s, passed digest/schema/counter/integrity/cold-reopen
validation and preserved the financial/risk/accounting table hash. Hot mutation
and intent counts fell to 3,612 and 2,374; order evidence remained 1,315.

**Boundary:** Proven-unsent means the transport was never submitted; cancellation
or absence is not enough. Active episodes, ACK, rejection, unknown sends, orders,
fills and economics are ineligible. The copy measurement is not live refill or
profitability evidence; STATUS owns final deployment observations.

## 187. Replacement selection freezes price proof before redundant risk reads — 2026-09-25

**MEASURED, read-only local evidence:** Generation 160 had 28 resting entries
and no positions at 07:31 ET. Its retained account inspections include 30 orders
at 06:27:00.966 and 07:29:18.011 ET: it reached the cap but did not consistently
retain it. Sixteen of 777 inspection samples contained 30 orders; these are
event-biased observations, not a time-at-cap percentage. At the 07:30 audit,
current-run mutation records contained 86 accepted creates, 354 NOT_SENT creates
and 58 acknowledged cancels, with no received fills since startup. These are
individual order records, not pair attempts. The roughly 07:20–07:30 interval
had eight accepted creates versus 60 NOT_SENT creates. Candidate proposals
included $2+ replacements. The earlier explanation that cooldowns alone account
for the vacancies was incomplete.

**VERIFIED offline:** Dispatch scored a book, awaited a portfolio read inside
selection, then awaited another portfolio read after capturing the selection
proof. A valid book update during either avoidable await could discard the
candidate. A real-owner/injected-wire regression changes the candidate book on
every portfolio read: old source rejects it at `entry_proposal_missing_or_changed`;
D-124 submits once at the latest .52 bid, never the superseded .50/.51 prices.
Each dispatch refresh now reads risk before management/price proof capture and
uses the same current view for synchronous ranking. Two refreshes remain around
quota reservation, with two total portfolio reads rather than four. Writer
reservation, account age/revision, ranking and final send fences remain intact.

**VERIFIED offline safety:** Updates after preparation or SENDING, sequence
gaps, malformed books, pending private work, deadlines, oversized pending batches,
expired account proof and mismatched portfolio revision still block submission.
A newly ineligible thin book is not replaced by the older eligible quote.
Detailed fixed-code diagnostics now distinguish a candidate missing from the
ranked slate and changed sources at send time. Existing NOT_SENT recovery is
unchanged: an aborted durable reservation still requires existing reconciliation.

**Limitation:** Generic historical send failures do not identify their exact
source, so this reproduction does not prove that every historical NOT_SENT
attempt has the same cause. Synthetic 1,024-book verification reaches 30 and
refills through normal recovery; STATUS owns the final suite and measurements.
The running build remains unchanged. Live improvement and sustained occupancy
remain unverified until a separately authorized deployment/restart.

## 186. Recovery progress, deadline logging and cleanup handoff stop the run — 2026-09-25

**MEASURED:** Generation 158's diagnostic run `3e12e4a4a5fd44ef9fe305f46c49d4f5`
exhausted recovery at 00:28:12 ET. Its last two incomplete passes overlapped
durable cancellation and passive-reducer ACKs. The old progress condition only
recognized a completed account pass, so it erased the new recovery request.
A 10-contract fill was durably received at 00:28:00.653 ET. Logging ended at
00:42:59.888 and the parent recorded unexpected death at 00:43:01.395.

**VERIFIED reproduction / INFERRED historical death cause:** The existing
15-minute inventory recovery path emits `safety_recovery_rearmed`, missing
from the diagnostic event registry. With the real logging sink, that path
sets `invalid_event` and `ensure_healthy()` raises. Its timing matches the live
exit, but the failed sink could not record a traceback and the old parent did
not retain the native exit code. Do not claim a captured historical exception.
A static audit finds this is the only unregistered literal event in the package.

**VERIFIED control history:** Recovery-only cleanup subsequently closed inventory,
canceled entries and reported STOPPED_FLAT at 00:44:12 ET. Its CLEAN handoff
still consumed incident attempt three, so the next tick refused the normal
child as `restart_budget_exhausted`. A new signed GET-only account check at
06:00:56 ET returned zero resting orders and zero nonzero positions.

**VERIFIED offline:** Failing-before tests reproduce lost durable-action progress,
logging failure and the last-slot cleanup handoff. D-123 preserves fresh account
and terminal/fill proof, recognizes only durable safety-action ACK progress,
registers the deadline event, records native exit codes and charges verified
cleanup/normal handoff as one restart slot. Rejections, uncertainty, ambiguous
scope, failed cleanup, stops and genuine retry exhaustion remain blocked.
STATUS owns final verification/deployment results.

**Correction:** The preceding Command 1 status claimed no ERROR events using
the live-session ID to filter diagnostic logs. These are separate run IDs.
Use `runtime.logging.run_id` for log correlation; that earlier filter did not
establish the claimed absence of errors.

## 185. Live withdrawal triggered, but quota refresh ended the run — 2026-09-24

**MEASURED:** Current supervisor-run logs from 22:40:11 to 23:34:39 ET contain
24 `fill_risk_withdrawal` events (7 in the first trading child, 17 in the last).
The final child's historical telemetry contains 36 cancellation samples and a
157.989-second p95 decision-to-ACK budget. These samples include scheduling and
reconciliation delay, not just venue/network time. The signed account read at
23:40:06 ET found no fills since that run start, 28 resting entries and no
nonzero positions. No observed fills is not proof that withdrawal prevented
them, a calibrated escape probability, or profitability evidence.
Across 131 matched mutation send/ACK events (all command types, not cancels
alone), the median is 0.258 seconds, p95 0.362 seconds and maximum 0.503 seconds.
That interval excludes earlier scheduling and later reconciliation; it must not
be substituted for the much larger decision-to-cancel budget.

**VERIFIED source reproduction; live attribution supported by timing/frames:**
At 22:54:40.697 ET quota refresh completed; at 22:54:41.147 the first trading
child failed in `check_permit`'s missing-permit branch. At 23:34:33.638 another
refresh started; at 23:34:33.891 the last child failed in the quota-unavailable
branch before transport. The guard intentionally revokes outstanding permits
during refresh. The dispatcher only handled base expiry/429, not observed-source
refresh states or a completed replacement. Actual owner/writer fixture tests
reproduce both failures before the fix and pass after it. The production ledger's
last two creates were already NOT_SENT; it was not modified during investigation.
Raw exception reasons are not logged, so the exact historical reason text is
inferred from the source/timeline, not claimed as a captured log field.

**VERIFIED cancellation, separately authorized:** With the bot stopped and all
three account/process ownership leases held, an exact owned-order cancel-only
operation acknowledged 28 cancellations (each reduced by 10 contracts). The
first-to-last send interval was 31.985 seconds, including deliberately conservative
one-request/second pacing after fresh quota/cost verification. The immediate list
still returned one row; a separate signed enumeration at 23:46:07 ET returned
zero resting and zero nonzero positions. Do not attribute the entire operator
workflow delay to venue reconciliation. No entry, liquidation, restart, ledger
write or Polymarket operation occurred. Private operation evidence stays ignored.
The mutation contract was checked against the current official
[Cancel Order V2 documentation](https://docs.kalshi.com/api-reference/orders/cancel-order-v2).

**Deployment limitation:** This run used canonical `31950e1`/D-120, not the
published D-121 speed repair `bb1003f`. Those earlier fixes and D-122 remain
undeployed at the audit. The operator subsequently authorized cumulative source
deployment while keeping the bot stopped; live latency after a future restart
remains unverified. STATUS owns release and deployment checks.

## 184. Startup and risk refill contain avoidable scheduling delays — 2026-09-24

**Correction to Finding 183:** Reaching 30 eventually did not establish an
efficient startup/refill path. Generation 152's local timeline began at 22:40:12
ET, started its runtime at 22:40:59, acknowledged its first pair at 22:42:40,
completed historical 1,024-market coverage at 22:43:32, and first showed 30 in
the sampled snapshots at 22:48:36. Public startup logged 22 REST 429 retries.
Risk pairs showed a fast first cancellation followed by roughly 6–13 seconds
before the second. Decision-to-ACK telemetry includes those scheduling waits;
it must not be reported as network-only latency or hidden by reducing the
estimator's horizon. This evidence is historical, not current account state.

**VERIFIED, offline source reproduction:** Holding durable batch-result
persistence allowed recovery to start reading before the result was stored.
Three regression cases failed with the original handoff. Recovery now joins the
sole dispatcher's result. Exact latched risk-entry IDs reuse durable cancel
ownership/route/revision checks, then share the ordinary final reconciliation;
no ACK releases capacity or authorizes entry. The integrated withdrawal test
also exposed a flat maintenance owner delayed behind catalog work. Recovery
and renewal now promote that owner without relaxing its source proof.

A separate failing-before regression showed that a cooling priority-market
hint blocked an eligible fallback. Such hints now retain advisory memory but
leave the pending revalidation set until admission permits them again. Public
discovery no longer banks 100 startup requests and halves its local pacing
after each shared 429 pause. Authenticated account budgets are unchanged.
The [official rate-limit guide](https://docs.kalshi.com/getting_started/rate_limits)
documents token costs and 429 backoff, not a public 50-requests/s entitlement;
this pacer is explicitly a local ceiling, not an exchange-limit claim.

**Verification discipline:** The first extended 1,024-book run exposed the
withdrawal/refill timeout above. Subsequent standalone stress runs missed the
unchanged 150-second initial-fill bound. These failures are retained in local
logs, not relabeled success or addressed by lengthening the deadline. Final
release results and deployment state belong in STATUS. A controlled follow-up
disabled only unittest's asyncio debug instrumentation: the same fixture reached
30, recovered and refilled within roughly 14 seconds, then failed an older test
assumption requiring the routine refresh counter specifically. At full cap the
valid steady-account refresh path had run instead. The timing fixture now uses
the production non-debug loop and accepts either actual refresh counter; every
production gate and the 150/30/45-second timing bounds are unchanged. Focused
race/failure tests retain debug instrumentation. This is a synthetic scheduler
measurement, not a promise of live startup or network latency.

**MEASURED, corrected production-loop fixture:** 1,024 books/four shards reached
30 entries in 11.505 seconds, replenished two independently terminal cancellations
in 0.757 seconds, then withdrew a threatened pair and refilled in 1.157 seconds.
The two cancels were 0.041 seconds apart with no intervening full recovery;
the replacement used a different market and the victim remained in cooldown.
One full-cap steady renewal completed, with no book/dispatch failure. The
fixture now waits for completed renewal evidence rather than assuming a fixed
sleep after wire ACK includes durable recovery and the next refresh. Raw ignored
artifact: `data/startup-recovery-risk-load-v5.log` in the canonical checkout.

**Test-environment correction:** The initial complete run used the shared live
virtual environment with a worktree `PYTHONPATH`. Native children intentionally
discard that variable, imported the canonical package and rejected its differing
source identity. These failures do not establish a supervisor regression. A
separate `data/startup-recovery-venv` now installs only this worktree; its five
dependency versions match the live environment. The live installation was not
changed. The clean release run must use this isolated installation without
`PYTHONPATH`; AI_OPERATOR records the requirement for future sessions.

The corrected complete run passes 1,759 tests (one expected Windows privilege
skip), including native supervisor cases, in 348.955 seconds. Its four-shard
fixture fills 30 in 15.004 seconds, refills terminal cancellations in 1.064
seconds, and completes withdrawal/replacement in 2.043 seconds with a
0.045-second gap between cancels. No code/configuration was deployed and no
venue operation was performed by this task.

## 183. D-120 live acceptance preserves safety at the cost of transient slots — 2026-09-24

**VERIFIED, live Command 1:** The supported stop removed 30 entries and exited
both exact managed processes in about 13 seconds. Independent signed account
reads returned zero resting orders and zero positions before deployment. Release
`3e0a346` then started as generation 152 with all six readers subscribed and
complete 1,024/1,024 initial market coverage.

The new fill-risk status loaded and recorded eight cancellation samples during
the acceptance window. The bot reached the 30-order cap more than once, then
moved between 28 and 30 as estimated-reachable orders were canceled and fresh
replacement/account proofs were obtained. This is the designed safety tradeoff:
30 is a cap, not a promise to retain a risky order. Zero positions, healthy
logging/quota and no ERROR/CRITICAL event were observed. Startup REST 429 retries
and incomplete first recovery passes recovered. Live observation does not prove
that every withdrawal avoided a fill, that every order scores, or that rewards
exceed trading losses and fees.

## 182. Queue depletion estimates require actual protection, not reward target — 2026-09-24

**VERIFIED, source and official documentation:** Reference uses target/5,
already implemented by `quoting._reference`; a 1,000-contract target places
the reference at 200 cumulative contracts, but does not guarantee 200 ahead of
our order. The queue endpoint supplies actual preceding quantity. The old
reflection parser validated then discarded this number. D-120 retains it,
combines it with existing books and implements bounded withdrawal/cooldown.
See [field ownership, caveats and test design](docs/BUILD_FILL_RISK.md).

**MEASURED, historical generation-150 local logs:** 18 mixed order mutations
between 22:00:08 and 22:14:50 ET had median send-to-durable-ACK 283.1 ms and
maximum 367.2 ms. These omit detection/pre-send waiting and are not cancel-only
performance. The new model measures decision-to-ACK and uses a two-second floor
plus observation age/cadence and margin. No measured escape probability exists.

**VERIFIED, offline:** The 22 new tests pass, including real manager/dispatcher
withdrawal, racing partial fill and replacement ranking. Removing the withdrawal
decision causes its regression to fail. The complete 1,747-test gate passes with
one expected Windows privilege skip. Estimator 30/120-order p99 is 0.409/0.503 ms;
the existing 1,024-book fixture reaches 30 entries in 89.044 seconds and refills
two slots in 4.470 seconds. These are synthetic correctness/resource measurements.

**LIMITATION:** Aggregate depth decreases may be behind us, and a large trade
can sweep our order before any warning arrives. The estimate may overreact or
miss a burst. It cannot promise no fills, $1 eligibility or positive net profit.

## 181. Refill was coupled to shared queues and catalog scheduling — 2026-09-24

**VERIFIED, local telemetry/source:** Generation 148 showed 14 resting entries
at 21:14/21:17 ET with the cap still 30, no economic holds, remembered $2+
candidates, and `entry_sources_changed_after_risk_read` / proposal-change
deferrals. At 21:35:32 its matching PID-18684 snapshot showed 22 entries, no
positions, current account proof and the same source-change deferral. This is
slow refill, not evidence that only seven markets qualify. No venue operation
or live source update was performed in this investigation.
The 21:47:25 follow-up again showed 22 entries, zero positions and current
account proof. A bounded local sample of 1,502 current-run events covering
21:45:06–21:47:25 contained no WARNING/ERROR/CRITICAL events. Informational
metadata/plan activity was present; absence of errors does not prove refill
health. This observation does not assess older rotated logs or profitability.

**VERIFIED, synthetic production-mode entry graph:** A baseline pair ACKed.
Queuing an unrelated market's frame on its shared shard during the second risk
read left the candidate's own revision unchanged, yet blocked it with zero wire
calls. The same shared-queue rule affected inventory/ranking reads across their
writer awaits. This guard predates the recent patches; historical generation
116 reached 30 on `f46c23c`. No single new regression commit is established.

Priority revalidation had a second scheduling defect: `mark()` coalesced an
already-dirty market without promoting it ahead of the catalog. Thus account
renewal could invalidate all proofs while priority candidates waited behind
hundreds of ordinary evaluations. Catch-up alone still failed the initial
capacity gate in a 150-second synthetic run (26 remembered priority candidates,
23 pending refreshes); that run is diagnostic, not a controlled speed benchmark.

D-119 shares the engine's bounded ordered parser at proof reads and promotes
pending priority keys with discovery fairness. It does not suppress real book
changes or extend freshness. Explicit regressions cover unrelated frames during
inventory reads, proposal/risk reads, preparation and SENDING; candidate changes,
sequence gaps, malformed ladders, pending private events, due safety timers,
stale books and bursts above 64 remain unsent. Scheduler tests cover promotion,
bounded duplicate coalescing, unregistration and ordinary-work progress.
Restoring the old no-catch-up behavior in isolated tests reproduces four
failures across the risk, inventory, proposal and SENDING edges, with no test
errors or real transport. The repaired versions pass.

**MEASURED, disposable synthetic ledger/wires, Windows, four shards / 1,024
books:** The combined repair reached 30 resting entries in 110.384 seconds from
composition, all in the $2+ tier. After two simulated terminal cancellations,
real full recovery and dispatch restored 30 in approximately 4.61 seconds;
the test then remained at cap for 3.5 seconds. Sixteen pairs were acknowledged,
12 routine renewals completed, and the engine processed 22,527 events with zero
book failures. All quantities remained ten; no competing writer, venue traffic,
fixture authorization bypass or live data was used. This is correctness/load
evidence, not predicted production latency, guaranteed occupancy or earnings.
The clean full-release rerun also passed: cold population took 133.576 seconds,
two-order refill 5.113 seconds, with 19 routine renewals and 26,874 processed
events. Both runs use the same unchanged production repair; timings vary with
Windows scheduling and the debug-enabled synthetic workload.
STATUS owns the final release gate and deployment state.

## 180. Redundant metadata refresh and unsent quota expiry — 2026-09-24

**VERIFIED:** A priority revalidation request removed still-fresh exit terms;
republishing equal terms invalidated their management/entry proof by identity.
The isolated pre-fix regressions reproduced both defects without venue calls.
Preserving a publication requires identical generation, provenance revisions,
values and original validity bounds; real changes/expiry still revoke it.
Priority revalidation explicitly queues account/book reevaluation, so preserving
fresh metadata cannot strand the candidate waiting for a publication callback.

The generation-144 shutdown stack ended in `check_permit` after preparation.
The offline reproduction proved zero transport calls and durable NOT_SENT,
yet the dispatcher failed. D-118 keeps only this proven-unsent temporary expiry
recoverable; clock faults, used receipts and ambiguous sends remain fatal.
These findings explain reproduced deferrals, not every unfilled live slot.

**VERIFIED exit observation:** The current ZYNPOS T109 position first filled
at 20:37:11.854 ET. Its 900-second age deadline was 20:52:11.854 ET. Read-only
ledger evidence shows the passive exit canceled and all ten contracts executed
on an ask at .08 by 20:52:18.056 ET (6.202 seconds after the deadline).
The opening basis was .11. These order prices are not an audited net-P&L/fee
calculation. Direct read-only venue inspection at 20:53:21 ET confirmed zero
positions and 16 resting entry orders. No manual close or restart was performed;
this observed exit followed existing policy, not a newly deployed fix.

## 179. A market-local reprice imposed an account-wide entry gate — 2026-09-24

**VERIFIED:** `QuoteMaintenance.entry_allowed` admitted only the active cycle's
ticker/program. That predicate runs in ranked selection, dispatch preparation
and the final selection-proof fence, so WebSocket shards could not isolate it.
Generation 144's 20:17 ET telemetry still showed the AALCC T104 replacement
cycle with `entry_proposal_missing_or_changed`; direct venue evidence at 20:14 ET
had 20 resting orders in ten markets and no positions. This does not establish
the total number of currently eligible markets or explain every source deferral.

D-117 allows unrelated tickers through this predicate only; their normal source,
reward, cash, account and writer risk checks still apply. Same-ticker gates and
terminal/fill reconciliation are unchanged. One maintenance cycle remains;
this is admission isolation, not concurrent repricing workers or more shards.
Four regressions failed on the old gate, including an actual production-mode
entry graph with synthetic transport. The repaired selector fills ten available
slots from 20 to 30 in a synthetic fixture, not a live occupancy guarantee.
Release verification and deployment state belong in STATUS.

## 178. Manual close used three fills — 2026-09-24

Fresh read-only venue inspection confirmed zero orders and positions after the
operator closed `KXTOKENUSE-26SEP28-T138`. The 10 NO contracts closed through
YES-equivalent buys: one at .83 and nine at .84, against .63 opening basis.
Gross trading loss was $2.09; actual fees total $0.0946; net loss $2.1846.
The single-fill operator-adoption primitive could not represent this real order.
Its bounded multi-fill repair passes 39 accounting tests and the complete
1,703-test release gate, with one expected Windows symlink-privilege skip.
The stopped-owner reconciliation dry-run independently matched venue cash.
Application/restart results remain owned by STATUS.

### D-115 manual-close handoff — 2026-09-24 19:49 ET

No one-off IOC was submitted. Exact generation 141/PID 44492 was reverified
immediately before D-112 termination. Subsequent status showed both managed
processes absent, control generation 143 stopped/disarmed and recovery required.
The last runtime still showed the -10-contract position and zero entries; venue
exit/position state must be reconciled after the operator's manual close.
Ignored `data/close_D115.py` was import/deadline-adapter checked only, not run
against the venue and is not a supported operating command.

## 177. Background advisory replacement races entry dispatch — 2026-09-24

**VERIFIED offline:** With unchanged account, book, program and metadata, an
engine evaluation during the dispatcher's risk-view await replaced its pinned
management/selection objects. The actual entry graph then returned
`current_candidate_missing`. Repeating evaluation after writer preparation
returned `risk_account_book_proof_stale`. A third regression reproduced an
advisory inventory read begun before dispatch but completed during that await.
These artificial invalidations contribute to live refill deferrals; they are
not evidence of changed prices or insufficient rewarded markets.

Only background evaluation for the exact active entry ticker is deferred.
The inventory manager rechecks that ownership after an awaited read, preventing
late publication. The dispatch result requeues the market even after a blocked
attempt. Private ingestion, book application, metadata invalidation, deadlines,
other markets and final send fences remain active. A real changed book still
blocks transport; no source timestamp or monetary rule is relaxed.

Generation 139's saved status stopped updating at 19:26:00 ET and both managed
processes were absent when checked before the 19:31 stop request. The last
snapshot had 22 entries and zero positions, not a flat shutdown. Windows recorded
an application event from `CodexSandboxService.OpenAI.Codex` at 19:26:02, coincident
with the last heartbeat. Causation is unproved; no bot exception/clean shutdown
was logged. Restart must reconcile durable state, not assume venue cancellation.

**MEASURED live cancellation:** After the dead-owner record was released,
generation 141 was explicitly stop-latched during startup. It obtained 21 cancel
ACKs in 7.351 seconds first-to-last (19:40:56.212–19:41:03.563 ET), with zero
resting entries afterward. One earlier entry had filled; a -10-contract position
remained under the existing passive/timed exit policy. That inventory wait must
not be presented as slow cancellation. The normal refill fix still needs a
post-drain live acceptance run; synthetic tests do not establish that result.

## 176. Historical order classification dominates recovery latency — 2026-09-24

**MEASURED on an isolated copy of the stopped production ledger.** Enumerating
935 retained orders called `settle_order` 935 times. Each non-legacy reducer
classification scanned `command_authorizations` for the same `managed_exit`
proof type. Profiling measured 2.427 seconds per enumeration, including 2.200
seconds inside SQLite execute calls. Full recovery repeats this enumeration.
The earlier explanation attributing the whole delay to API latency was
incomplete: serial local database work is a measured major contributor.

A shared classification query inside the existing writer transaction reduced
the same pass to 0.146 seconds; a second run with exact old/new comparison took
0.281 seconds and returned identical receipts, including all 37 reducers.
These are offline timings, not a promise about venue response or total restart
latency. The live database was opened read-only for the snapshot and was not
modified by profiling. No schema migration or evidence deletion is needed.

Stop scheduling also waited for a current management plan even though the
existing paused cancel sender can validate exact durable ownership independently.
The repair queues known owned-entry market keys directly on stop, retains final
writer validation, shares financial collection with full recovery's final
snapshot, and leaves a fresh flat report available to shutdown before renewing
an unnecessary entry lease. Live acceptance belongs in `STATUS.md`.

**MEASURED after deployment:** Generation 139's first 26 completed repair passes
averaged 3.650 seconds (3.165–4.339 seconds); 72 routine renewals completed with
zero escalations. The old two-order stall was passed, reaching 12 entries in the
observed window, all from $2+ selections. Broad ranking still took 152.8 seconds
and entry evidence changes still deferred refill. This corrects recovery latency,
not every source of startup/refill delay. A separate profile on the retained
stopped-generation fixture measured flat portfolio/market reads at approximately
2/1 ms; that flat fixture does not model the current active-order workload.
Live cancellation latency has not been benchmarked on this release.

## 175. Routine freshness recovery starves startup and refill — 2026-09-24

**Repair follow-up:** D-113 is implemented in source, not yet deployed. Routine
renewal reuses a bounded history chain while acquiring new empty-tail, exact
snapshot and cash/funding/settlement evidence through existing release checks.
The real writer is exercised at 0, 2 and 28 orders; successful renewal funds an
offline entry reservation. Changed economics/source, nonempty/omitted history,
stop, cancellation and a 17-second stale snapshot reject renewal. A separate
17-second full-repair fixture verifies that its next routine refresh does not
replay startup. These are deterministic correctness checks, not a measured
production speedup. Current verification/deployment state is in `STATUS.md`.

VERIFIED from generation 131's local telemetry, source tracing and offline
synthetic fixtures. The original investigation below preceded D-113.

`RecoveryRuntime._live_refresh` requests full recovery when an account report
is missing or three seconds old unless an exact steady-refresh scope exists.
Both steady-scope methods require `coverage_complete`; recording additionally
requires a flat account and every resting-entry slot occupied. Consequently
neither startup/refill nor `priority_capacity_met` can use the shortcut. Full
recovery rebuilds account/history/accounting evidence and revokes current
selection evidence. The metadata scheduler defers new jobs during recovery;
`SelectionRuntime.refresh` also requires a current account report and management
plan before producing candidates. Reader health cannot overcome these gates.

MEASURED over generation 131 events from 17:17:37 through 17:46:53 ET in
`data/trader/supervisor/child-logs/events.jsonl` (logging run
`dcf705aeb2934660807c89a3d9635e4b`): 65 recovery starts and 62 successful repairs
preceded the first order at 17:39:55. Successful recovery duration had a median
of 17.4 seconds; the median repair-to-next-start gap was 2.5 seconds. All six
readers connected once, with no reader reconnect event. The 22 observed REST
429 retries ended at 17:17:59, so they do not explain the later persistent loop.
Recovery events lack trigger-reason attribution: these counts do not prove
every individual recovery had the timer as its cause.

A separate live sample at 17:48 ET showed 12 entries and zero positions
throughout: metadata activity rose from zero to four after repair, current
candidates reached 23, then another recovery reduced current candidates to zero
and deferred new metadata jobs again. This is scheduling starvation, not proof
that only six markets qualify. Zero metadata retry exhaustion is not evidence
that all pending markets are in cooldown. Earlier market-shortage/cooldown
explanations were unproven.

VERIFIED offline: the actual refresh loop requested recovery at report age
3.0 seconds, but not 2.9 seconds, without a socket event or order change.
The actual steady-scope recorder accepted full-cap/full-coverage state and
rejected a vacancy and early priority release. A real account reconciliation
against synthetic reads revoked a previously current accounting source fence.
Thus merely widening the steady-scope condition is insufficient: the existing
snapshot-only shortcut does not renew the entry accounting lease.

Four existing steady-scope/refresh regression tests passed (0.343 seconds).
All reproductions used synthetic reads and temporary ledgers; no production
database or venue API was accessed by the investigation. No full-suite or
post-fix live acceptance is claimed.

Original recommendation, now accepted as D-113: separate routine bounded account and
accounting-evidence renewal from full recovery, including startup/refill, and
allow advisory market discovery/ranking to progress while account checks run.
Final admission must still require fresh exact account, ownership, book, cash
and risk evidence; owned-order subtraction cannot use unverified state.
Preserve full recovery for gaps, unknown/changed economics and invalid proof.
Test realistic recovery latency across freshness deadlines and account-change
races. Add trigger/phase timing to distinguish costs before tuning. More book
shards or enlarged freshness limits do not repair the demonstrated coupling.

## 174. Observation timestamps are not reward-universe identities — 2026-09-24

VERIFIED LIVE from generation 125 and VERIFIED offline. The loaded checkpoint
included `catalog.observed_mono` in its source identity. Periodic refreshes of
unchanged active reward programs therefore cleared all accumulated startup
coverage. Current scan speed exceeded the five-minute refresh interval; eight
resets occurred while the bot stayed flat and retained only non-authoritative
priority hints. The original recovery timeout was already repaired and was not
the cause of this ranking loop.

The stable identity is the catalog's semantic content: program and market
identity, exact reward terms, eligibility interval, payout state and exclusions.
Refreshing observation age alone must re-age selection evidence but need not
erase historical proof that each market was examined under the same semantic
universe. A changed semantic digest still resets coverage, and a missing catalog
still blocks selection entirely.

## 173. Full recovery can outlive an individual five-second proof — 2026-09-24

VERIFIED LIVE from generation 116's retained receipts and diagnostics and
VERIFIED offline by a wall-clock regression. Each failing pass enumerated
history from the approved opening boundary, then spent enough time on later
order-management work that the receipt was about nine seconds old at release.
The final account report itself was current. Operational release therefore
correctly emitted `accounting_history_receipt_invalid` and
`accounting_history_interval_gap`; the problem was capture order, not missing
venue history, a damaged ledger, reader loss or a reason to enlarge freshness.

The first source correction used the safe logical ordering—repair/import,
management refresh, fresh history, fresh account snapshot, immediate release—
but generation 119 proved that repeating the complete opening-to-now scan can
exceed the existing 20-second whole-pass deadline. The child remained flat and
recovery-only while transient retries continued.

The efficient proof keeps the early complete pass, then enumerates only the
elapsed tail from its exact eligible right edge concurrently with the final
account snapshot. An empty omission-free completion does not advance authority;
any new or omitted fill rejects the shortcut and returns to full recovery.
Release uses both receipts as one gap-free interval, validates every receipt's
provenance and omissions, and requires the tail's right edge to be fresh for the
final account observation.
The final pair cannot be reused if its account signature changes. Existing
five-second freshness, source-revision and whole-pass limits remain intact;
steady full-cap refresh is unchanged.

## 172. Paused entry draining must hand off to reducer cleanup — 2026-09-24

VERIFIED LIVE from generation 113/114 diagnostics and VERIFIED offline by a
focused regression. Recovery canceled all 26 stale entry orders, but retained
one owned passive reducer for the 10-contract short position in
`KXCTMFPERMITS-27MAY03-T4000`. The paused fast path then repeatedly reported
`current_candidate_missing`: its selector deliberately excludes reducers, and
the empty result prevented the normal source-verified plan from issuing the
already-due cancel-before-IOC operation.

The repair makes an empty fast-path result continue to the existing account and
management plan. It does not classify reducers as entries, bypass current venue
evidence, weaken cancellation identity checks or create new trading authority.
The old child could not load source changes in place, but it eventually filled
flat and exited naturally before authorized exact-PID termination was needed.
Generation 116 then loaded the published repair, completed recovery flat, ranked
1,024/1,024 markets and rebuilt 30 entries with no position or persistent hold.

## 171. A zero-revenue settlement can describe a market already closed by fills — 2026-09-24

VERIFIED LIVE from generation 111's retained account evidence and VERIFIED
offline against a read-only SQLite online backup. Kalshi returned one settlement
for `KXTRUEV-26SEP23-T1258.69`: 10 YES costing $2.00, 10 NO costing $9.80,
result NO, $0 revenue and $0.0138 fees. The ledger contains exactly two owned
terminal fills before settlement: buy 10 YES at $0.20 and sell 10 YES at $0.02.
It has no remaining lot or venue-cost quantity, and matched-fill accounting had
already recorded `-$1.8138` net. Therefore the settlement is evidence of the
completed market history, not a second economic close.

The correction is deliberately not a generic automatic settlement policy. The
exact release requires agreement across current account state, retained fill and
order ownership, execution time, YES/NO transformation, costs, fees, realized
closes and the normalized settlement row. Open/scalar/revenue-bearing,
incomplete, external, corrected or conflicting rows remain manual economic
holds. See [the build record](docs/BUILD_CLOSED_SETTLEMENT_RECONCILIATION.md).

## 170. Kalshi may enrich an unchanged applied deposit after approval — 2026-09-24

VERIFIED LIVE during the generation-108 incident and generation-111 recovery.
Kalshi added a `finalized_ts` to the already approved $500 ACH deposit; the new
timestamp equaled its original pre-boundary creation time, while ID, status,
method, amount and fee remained unchanged. Boundary-relevant filtering then
omitted the fully pre-boundary row, so exact matching needs the complete
cursor-exhausted funding source to distinguish lifecycle enrichment from an
absent or changed event. This does not justify accepting a new row, changed
economics/status, later finalization or incomplete history.

The published repair at `ba3c19c` cleared only the false
`cash_activity_unattributed` hold in a recovery-only child. That child proved
current flat state and stopped; the supervisor then launched a fresh normal
child. Generation 111 ranked 1,024/1,024 markets and rebuilt 30 entries across
15 priority markets with a minimum projected remaining reward of $2.158. Two
20-second-apart samples had current account proof, zero positions, six subscribed
readers, no risk/accounting holds, no exhausted retry round and healthy logging.
Both live SQLite databases passed `quick_check`. Startup 429 retries and temporary
incomplete-recovery warnings cleared; no ERROR/CRITICAL event was observed. A
later one-order vacancy refilled normally from 29 to 30 and remained full for
three consecutive current-account samples.

## 169. Unattended reward-uptime review: recovery does not imply quote resumption — 2026-09-23

VERIFIED against `79a4b1d` (runtime source `b75ea57`), with fake readers,
disposable SQLite and pure supervisor transitions. Review only: no production
code/configuration, orders, database contents or process state changed.

Priority findings, not authorization to remove safety gates:

1. **P1 — account/book readers can retire for the remainder of a runtime.**
   `runtime.py:818-849,1046-1052,1380-1400`: unlike lifecycle, these readers get
   one three-attempt round. Successful subscriptions/long healthy connections
   do not reset that round. After three disconnects, the reader returns normally
   and the main runtime continues without it. Offline reproduction observed
   three account attempts, `retry_exhausted`, and a still-running runtime task.
   Add classified transient recovery with bounded cooldown rounds and genuine
   healthy-state criteria; never reset on ACK alone or retry integrity ambiguity.
   `supervised_live_child.py:82-95` only projects accounting/risk blocker arrays:
   a synthetic exhausted reader/recovery with those arrays empty is labeled
   healthy. Report persistent reader/recovery failure separately from ordinary
   short reconciliation gaps, and make it actionable rather than heartbeat-only.
2. **P1 — a transient account-repair outage can remain latched after recovery.**
   `runtime.py:1228-1234,1265-1285`: three failed passes clear the request and
   enter `blocked_retry_exhausted`; periodic live refresh only services the
   repaired state. A fake OSError on three passes followed by a restored source
   produced no further calls absent a new external recovery trigger. Some events
   can request recovery, but restored network availability alone is insufficient.
   Distinguish transient transport/quota failures from ownership/economic
   conflicts; add a supervised cooldown retry only for the former. Test this
   while flat with resting orders and with no intervening stream event.
3. **P1 capability/policy gap — crash recovery does not automatically rebuild.**
   `supervisor_launch.py:111-112`, `supervision.py:703-705,749-752`: unexpected
   death produces a recovery-only replacement; successful CLEAN recovery
   disarms it. A pure-policy crash/recovery reproduction confirmed this exact
   sequence. This is the existing intentional safety contract, not an accidental
   regression. Unattended quote resumption needs an explicitly accepted policy
   and tests: original arm authority remains valid, exact recovery completes,
   all current account/risk/market checks pass, then rebuild through the existing
   ranked dispatcher. Manual stop, loss/integrity holds and ambiguous orders
   must never be automatically cleared.
4. **P2 — compressed retention postpones, but does not eliminate saturation.**
   `accounting.py:25,127-131`: 64 archives is a hard ceiling; the next required
   archive raises `InvalidData` demanding external archival. A disposable fixture
   with the limit scaled to one confirmed that the second archive refuses.
   The immediate D-109 hot-journal repair is valid, but continuous service needs
   measured capacity alerts and a supported, audited retention/rollover path.
   No time-to-full estimate is established; never delete economic evidence or
   enlarge limits blindly as a substitute for a lifecycle.

MEASURED LIVE: generation 106 at 22:33:51 ET had 30 resting orders, zero
positions, current account proof, six subscribed readers, no accounting/risk
blockers and 154 completed steady refreshes. At 22:37:06 ET it still had 30
orders/zero positions and six readers; refresh 204 was in flight (203 complete),
so `account_current=false` in that snapshot is not evidence of persistent failure.
The scanned generation log contained 11,453 events, no ERROR/CRITICAL records,
19 startup REST retries and one reward-reflection `QuotaUnavailable` warning.
Later mutation ACKs exist, but they alone do not prove every refill/exit path.

Non-finding clarified: D-109's light reconciliation revokes/expires the entry
lease at full capacity. That is not itself a refill defect: maintenance cancels
use their own current proof; mutations/vacancies invalidate the steady scope and
request full recovery before new entries. Do not renew authority merely to make
`entry_allowed` green. Existing tests cover exact-scope and changed-snapshot
escalation, not an uninterrupted multi-hour production guarantee.

Verification: `scripts/Test-Bot.ps1 -Fast` **257 passed**; durable-accounting
suite **26 passed**. Ignored local `data/review-uptime/probe.py` reproduced the
two parked recovery paths, crash-to-disarmed policy, archive ceiling and health
projection. No live fault injection, restart, full-suite rerun or long soak was
performed. Passing tests affirm existing behavior, not the desired new uptime
contract. Proposed acceptance: repeated healthy/disconnect rounds, temporary
REST outage/restore, child crash to verified recovery to ranked refill, manual
stop/ambiguous-outcome non-resumption, fill/exit/vacancy refill and compressed
retention rollover, all with synthetic sources before an authorized deployment.

## 168. D-109 recovered the full journal; Kalshi persistence remains heavier than Poly — 2026-09-23

MEASURED LIVE on the operator-authorized generation-102 to generation-106
restart. The supported stop canceled all 30 orders and observed zero positions
and zero exposure. The old loaded child could not append terminal flat proof
after journal saturation, reached `shutdown_timeout`, and was force-terminated
only after separate authorization and exact PID/generation verification. The
next recovery-only generation archived 8,192 superseded events, cleared the
capacity hold through successful accounting release and stopped flat before the
normal live generation was launched.

Generation 106 completed 1,024/1,024 initial ranking in 196.08 seconds and
reached 30 resting orders across 15 markets with zero positions. All six readers
are subscribed and no accounting hold remains. A later sample recorded 52
completed bounded steady refreshes, zero escalations and 71,777 suppressed
optional evaluations. SQLite integrity is OK; 15,977 hot events use 47,656,154
payload bytes, while four exact archives compress 8,192 older events from
19,774,412 bytes to 1,040,549 bytes.

VERIFIED FROM CODE: both bots use a single-writer SQLite financial ledger and
current venue state outranks saved state. Polymarket's execution ledger stores
normalized orders, fills and positions and keeps account-event payload hashes;
Kalshi's accounting journal stores fuller exact reconciliation payloads. D-109
compresses superseded Kalshi evidence but does not make that persistence model
identical or permanently size-free. Archive growth therefore remains a measured
follow-up, not a reason to delete financial or conflict evidence from the live
ledger.

## 167. Full recovery cadence exhausted the accounting journal — 2026-09-23

MEASURED LIVE on generation 102 using read-only status, logs and SQLite. The
three-second account refresh initiated a complete recovery about every 5.56
seconds; each pass took roughly 3.15 seconds median, reread account/history/cash
sources and dirtied all 1,024 markets. The process consumed about 90.9% of one
CPU core while applying roughly 370 book events and 494 decisions per second.
A stable reward sample observed 39 of 275 program-seconds (14.18%).

At 21:29 ET, the 64 MiB hot accounting limit latched. SQLite integrity remained
OK and exact counters matched 23,975 rows / 67,101,670 payload bytes. The journal
contained 8,051 inspections, 8,054 cash observations and 7,867 operational
releases, versus three other records. This proves repetitive recovery evidence,
not a new fill or position, caused saturation. The runtime correctly disabled
entry, but the 30 resting orders remained under a stale account proof.

The offline repair uses a narrow exact account refresh only at the proven flat
30-order cap, suppresses optional deep work for the 1,009 unowned markets while
still applying every WebSocket delta, and archives only superseded steady-state
observations into bounded exact audit blobs. Any changed economic/source state
falls back to full recovery. Live effectiveness is not claimed before an
authorized supported restart.

## 166. Generation 97 exposed two cadence/control defects — 2026-09-23

MEASURED LIVE before the supported stop: generation 97 was stable at 30 resting
orders with no position, but a 30-second sample observed only 10.606 of 183.601
aggregate active-program seconds (5.78%). Reward reflections succeeded; the
dominant mechanism was timing. Account proof is refreshed at about three
seconds, a pass takes about three seconds, and reward queue proof expires at
five seconds. Consecutive complete joins therefore arrive around six seconds
apart, so retaining an endpoint alone cannot bridge them.

VERIFIED from durable supervisor events and child diagnostics: external STOP
advanced generation 97 to 98 and signaled the latch. A stale parent snapshot
then applied STOP again, advancing to 99. The exact child remained bound to
generation 97, reached `STOPPED_FLAT`, but classified its cleanup control as
revoked because control generation no longer equaled child generation. Its exit
was consequently recorded as unexpected rather than clean. This was a control-
plane classification failure after flat runtime shutdown, not evidence of a
remaining order or position.

The source repair keeps STOP's generation fence but treats it as authority
revocation rather than child-identity revocation for cleanup-only traffic.
Telemetry separately uses only the unexpired prior queue lease during an exact
normal reconciliation; it never grants current authority or extends freshness.
Both repairs are offline-verified. Live reward coverage and a production clean
stop remain unverified until a separately authorized deployment.

## 165. An uneconomic orphan had no maintenance transition — 2026-09-23

VERIFIED from generation-92 ledger/status evidence and reproduced synthetically.
One side of `KXROGUEPOS-26OCT03-T67` received a confirmed cancel ACK while its
10-contract bid remained resting. The survivor retained full price weight, but
a fresh two-sided target no longer cleared the $1 projected-reward gate. After
more than 90 seconds of fresh joined evidence, `QuoteMaintenance.refresh` could
neither select `restore_reference_pair` (target false) nor
`persistently_unscoring` (actual blockers empty), so the slot could remain stuck.

The corrected transition cancels an incomplete incumbent without re-entry after
the existing 90-second dwell when the current target is below minimum. It does
not restore an uneconomic pair or replace a qualifying owner for rank. This is
verified source behavior; live deployment evidence remains in `STATUS.md`.

## 164. Account refresh was deleting safe reward interpolation endpoints — 2026-09-23

VERIFIED SYNTHETICALLY after the generation-92 audit. The three-second account
refresh deliberately removes the current report while rebuilding it. Reward
telemetry responded by deleting both current authority and the prior sample, so
the following exact queue join had no endpoint from which to measure an interval.
That converted ordinary refresh cadence into mostly unknown time even when the
same orders remained resting.

The repair distinguishes suspension from invalidation. Suspension removes all
current reward and queue authority but retains the old in-memory endpoint. The
existing tracker may bridge only when a new exact observation arrives within
five seconds, both validity leases overlap, source continuity matches and the
owned-order identity hash is unchanged. A six-second gap is recorded wholly
UNKNOWN; explicit book/account epoch changes, program publication changes,
queue disagreement, unsupported data, checkpoint failure and shutdown still
hard-invalidate. No endpoint is persisted across restart.

Generation 92 also produced about 786 KiB of child logs in 204 seconds. At that
measured rate, its old 768 KiB production bound retained about 3.4 minutes. The
new bounded 96 MiB child configuration projects about 7.2 hours at the same
rate; this is a capacity estimate, not guaranteed duration. Live coverage and
retention remain unverified until a separately authorized deployment/restart.

## 163. Live flow audit: executions work; reward observation coverage is poor — 2026-09-23

MEASURED on generation 92, source `9fad565`, approximately 18:34–18:36 ET.
Read-only process/status, SQLite `mode=ro` and retained structured logs were
used; no orders, runtime settings or processes were changed.

- Ranking completed 1,024/1,024. All 30 active entry orders joined to admission
  evidence: 28 priority and two fallback, across 15 markets. No active intent
  lacked resting order evidence. There were no active reducers or positions at
  the final ledger check, no pending fills or accounting holds, and $128 exposure.
- The oil episode sold 10 YES-equivalent at $0.47, maintained exact passive
  reducers, then canceled the reducer and bought 10 at $0.53 using reduce-only
  IOC at 22:03:41 UTC, about 15 minutes after first durable fill receipt.
  Gross loss was $0.60 plus $0.1744 fee, net -$0.7744. This is the only completed
  fill episode since generation 92 started; it is not profitability evidence.
- This run recorded 58 acknowledged creates, 26 acknowledged cancels and 15
  proved-unsent creates. No new UNKNOWN mutation remained. Repricing/re-entry
  occurred on multiple incumbents. Four book readers plus account/lifecycle
  remained subscribed without reconnect rounds or book failures; quota reported
  no throttles, and the live log sink reported no dropped records.
- A 24.6-second status window (22:35:26–22:35:51 UTC) retained 30 entry orders.
  Across 15 tracked markets only about 4.7% of aggregate elapsed market time
  became observed/qualifying time; the rest was unknown. This measures local
  telemetry coverage, not venue non-qualification or unpaid rewards. Fresh
  maintenance samples did show all 15 pairs at full price weight during the
  window, but historical maintenance samples cannot prove continuous coverage.
- Source tracing shows periodic account refresh starts once its report reaches
  three seconds; reward reflection is bound to exact account report/revision
  and at most five seconds. Interrupted sample continuity is booked as unknown.
  This explains a recurring source-loss mechanism; isolating the contribution
  of each invalidation needs a focused reproduction before changing behavior.
- At audit time the three rotating child log files contained 1,795 records
  covering only about 204 seconds (22:31:28–22:34:52 UTC), with no warnings or
  errors in that retained window. The durable financial ledger covers the whole
  run, but these logs cannot rule out earlier transient errors.

The earlier statement that paid rewards were the only remaining uncertainty
was too strong. Improve reward-source continuity and diagnostic retention before
claiming reliable earnings measurement. Crash recovery, hard stop triggering,
partial fills and disconnect handling were not deliberately induced in this
live audit.

## 162. Restart latency was ranking work, not a hung process — 2026-09-23

VERIFIED LIVE in generation 92: the supervisor became healthy, all four book
readers subscribed, and initial ranking advanced continuously to 1,024/1,024.
The 120-second diagnostic timeout did not grant authority; the gate later
released safely on complete coverage (an earlier observed run released on
enough current priority capacity at about 145 seconds). Generation 92 then grew
from 2 to 22 resting orders, reported 25 remembered priority candidates, a
current account, zero positions and no book, dispatch or logging failure. Normal
startup therefore takes roughly two to three minutes for the current universe;
the preceding longer delay came from code and ledger verification, not restart.

## 161. The manual close was real venue loss, not a fee-only discrepancy — 2026-09-23

VERIFIED FROM AUTHENTICATED ACCOUNT HISTORY: the bot bought 10 YES at $0.67 and
the operator sold 10 at $0.62 with a $0.165 fee. The exact realized result is
-$0.665: $0.50 gross trading loss plus $0.165 fee. Fresh venue reads showed zero
orders and positions. After exact reconciliation, the durable target position
and lots are zero, SQLite integrity and cold cash validation pass, and accounting
cash is $495.101 for exchange index 0. This does not prove reward payout or
profitability.

## 160. Priority memory needs resolution classes and outcome correlation — 2026-09-23

VERIFIED SYNTHETICALLY: fresh hard ineligibility and unavailable proof cannot use
the same retention rule. `market_inactive` must retire an obsolete $2 hint so
fallback can proceed; `metadata_retry_exhausted` must preserve the hint and defer
fallback until proof is available. A bounded work window also has to refill as
members resolve—waiting for an entirely empty set lets one stalled candidate
starve every later candidate. Finally, candidate preparation is not evidence of
admission: a revoked `NOT_SENT` attempt produces no admission record, while an
ACK is correlated to its exact batch, client IDs and venue order IDs. These are
offline source/runtime results; generation 76 still runs older code and no live
behavior is inferred.

## 159. Complete historical coverage can still admit fallback prematurely — 2026-09-23

VERIFIED SYNTHETICALLY: with unchanged books/rewards, the real selector proposes
a $2.475 candidate ahead of a $1.485 candidate. Invalidating only the better
candidate leaves historical coverage complete and selects the fallback; refreshing
the better candidate restores priority. Discovery memory and current permission
were erased together in source through `dd601d1`. D-105 now preserves bounded
advisory memory and defers fallback until a remembered priority batch is freshly
resolved; current evidence remains the only order authority. Four outer metadata workers also share only one
background REST slot in live composition. The [investigation and recommendation](docs/INVESTIGATION_PRIORITY_ADMISSION_2026-09-23.md)
records code evidence, Poly comparison and correction of the unproven 5/10
live-tier claim. No REST-concurrency or live-runtime change occurred.

## 158. Four book shards cover all markets; metadata priority was separate — 2026-09-23

VERIFIED LIVE in generation 72: all four book readers plus account and lifecycle
subscribed, initial ranking reached 1,024/1,024 reasoned markets, and 30 orders
rested across 15 markets with no reported position. A public-only audit found
all 15 selected pairs still met their reward target; 13 exactly matched the
later sequential reference and the other two still qualified. This proves
transport/ranking coverage for the run, not paid reward or profitability.

The maintenance source remained intermittently unknown because its separate
metadata scheduler had two workers and equal FIFO treatment for all 1,024
candidates. This, not another WebSocket shortage, was the demonstrated owner-
freshness bottleneck. The controlled stop reached `STOPPED_FLAT`, zero entries
and zero positions, but an in-flight parent pulse after the stop latch prevented
the terminal fence and produced a false supervisor `unknown_failure`. D-104
repairs both mechanisms without expanding trading authority.

VERIFIED LIVE after D-104: recovery-only generation 75 stopped flat and disarmed
without the false failure. Normal generation 76 reached metadata high-water four,
1,024/1,024 reasoned coverage and 30 orders across 15 markets. After admission
settled, all 15 owners were simultaneously observed and retained with full price
weight on both sides; 14 pairs exactly matched their references and one bid was
better than reference. No position or runtime error was reported at acceptance.

## 157. Initial books are fast; 512-market freshness fails on two shards — 2026-09-23

VERIFIED READ-ONLY: the production transport/parser received all initial books
in 0.34 seconds at 128 markets, 0.56 seconds at 256 and 0.45 seconds at 512.
CPU remained below 4% of one core, memory below 66 MB and p99 ingress latency
below 34 ms. At 512, however, five-second fresh coverage temporarily fell to
61.1%, below the 99% target, so the bounded probe did not proceed to 1,024.
The likely next comparison is refresh scheduling with two versus four shards;
initial WebSocket delivery itself is not the demonstrated bottleneck.

An unrelated live ask filled 0.27 seconds before the probe began. The probe made
no account/order request. The fill left a -10 KXONPOS lot; three passive
reduce-only bids were rejected with HTTP 400. Safety stop canceled the other 29
entries. Recovery exhausted and prevented the overdue IOC from dispatching.
Recovery-only generation 71 then reconciled the preserved position, bought 10
YES at 89 cents, recorded a $0.80 gross loss plus $0.0686 fee, and exited
`STOPPED_FLAT`. Independent venue reads confirmed zero orders and positions.

## 156. Generation 68 live-verifies owner-bound reference repair — 2026-09-23

VERIFIED LIVE: reviewed D-101 source reached 30 resting orders across 15 markets
with no reported position. Two natural same-market maintenance cycles canceled
and restored exact pairs: MONSTER moved `0.69/0.83` to `0.69/0.82`, and TOKENUSE
T144 moved `0.10/0.58` to `0.10/0.56`. Four cancel ACKs and four replacement
create ACKs were recorded, with no current-generation fill, pending fill or lot.
Account authority recovered after each cycle and the bot returned to 30 orders.

The public-only census found 286 $1-pass and 38 $2-priority markets among 1,024.
All 15 selected markets passed its later sequential sample. Owner-bound live
samples distinguished a better-than-reference full-weight pair from an actually
outside-cutoff quote, so a raw price/reference mismatch is not itself a repair
condition. One quota warning overlapped the separate census; reflections later
completed. This proves the exercised source join and two repair cycles, not paid
reward, profitability or a simultaneous globally optimal portfolio.

## 155. Generation 66 repricing stalled; final drain also lost its wake — 2026-09-23

VERIFIED from local ledger/status: 30 entries acknowledged after 15:23 UTC,
one maintenance cancellation at 15:30:17, no replacement through the later
stop. Ten samples at 16:24:44–16:25:29 retained 29 entries and no maintenance
cycle; most reward joins were unknown. The public census examined 1,024 markets
at 16:23:56–16:25:39: 181 passed $1, 20 passed $2. All 15 incumbent markets
passed at hypothetical reference quotes, four were $2-priority; four actual
orders lagged the sampled reference. This was not a lack of available markets.
Sequential public samples include our aggregate liquidity and are not owner-
adjusted simultaneous rankings, actual earnings or account admission proof.

REPRODUCED: queue proofs were published only if an independently refreshed
management plan already existed; temporary source loss and even status reads
could then delete the still-current queue proof. Three focused reversal checks
detect the old queue-join, proof-retention and final-drain behavior. Details and
verification: [D-101](docs/BUILD_REPRICING_SOURCE_JOIN.md).

On explicit stop, 29 exact cancellation ACKs were recorded in an approximately
nine-second drain. Recovery exhausted while those outcomes changed its account
snapshot; the paused-cancel path never requested the final reconciliation.
A separate complete authenticated GET enumeration verified **zero venue orders
and positions at 16:35:52 UTC**. Only the correlated parent/child were then
terminated; native presence confirmed both absent at 16:36:11. No fill or pending
fill was recorded in this generation. No restart occurred.

## 154. D-100 archives the live history boundary and restarts normally — 2026-09-23

VERIFIED LIVE: after complete GET-only evidence showed zero venue orders and
positions, recovery-only generation 65 archived all 4,096 exact hot history
receipts in one compressed ledger archive, retained one current hot receipt,
reconciled the account and stopped flat. Normal generation 66 then reached
healthy current authority, four subscribed readers and 30 resting orders with
no reported position. Startup 429 retries and account-reconciliation races were
bounded and later repaired. This verifies the observed capacity-crash repair and
restart path, not payout, profitability, future rejection backoff or future
live-drain latency.

## 153. Per-recovery immutable receipts exhausted their hot table — 2026-09-23

VERIFIED read-only: production `history_enumerations` contained exactly 4,096
rows, all subaccount 0, all omission-free, all sharing one start and successively
later ends. Their payloads totaled 1,836,852 bytes and their coverage union was
one interval. The next `history_complete` raised the documented capacity error,
failed the writer and caused the supervisor's automatic recovery-only child.
This was deterministic growth, not storage latency or an API outage.

Polymarket executable code keeps durable fills as long-term truth and uses
bounded recent venue history as positive recovery evidence rather than writing a
per-poll permanent receipt. D-100 adapts that principle without discarding
Kalshi's stronger exact receipts: old rows are transactionally archived, while
only fresh hot evidence can participate in current continuity. The replacement
child's 48 line-634 errors were overtaken metadata publications; four additional
dependency errors were quota deferrals. Both classifications are repaired.

## 152. One live reducer produced 79 deterministic rejects before IOC — 2026-09-23

VERIFIED read-only from generation 63 ledger/status: a +10 YES-equivalent TRUEV
position filled at 13:51:45 UTC. Its passive reducer was rejected 39 times at
40c, 22 at 39c, once at 38c and 17 times at 37c through 14:05:03; attempts were
often about two seconds apart. One reduce-only IOC acknowledged at 14:07:38 and
the current account report is flat. No UNKNOWN mutation remains. The old scalar
transport retained status 400 but discarded the error body, so the exact venue
reason is unknowable after the fact.

The current log rotation retained 1,895 rows spanning only 9.99 seconds: 1,815
were inventory-plan changes across empty broad-discovery markets and 73 were
metadata publications; no retained WARNING/ERROR appeared. D-100 adds bounded
error-code evidence, a durable 10/20/40/60-second identical reducer circuit and
material-only plan logs. This reduces duplicate writes/log loss; it does not
prove the venue's original rejection reason or change the hard-exit deadline.

## 151. Maintenance dwell can starve under normal evidence gaps — 2026-09-23

[Read-only investigation](docs/INVESTIGATION_MAINTENANCE_DWELL_2026-09-23.md):
Oregon harvest retained its 52-cent bid despite production outside-cutoff
observations. In 90 live status samples, 83 were unknown/missing and no cycle
started. Two distinct valid observations were 5.236 seconds apart; gaps over
five seconds reset the 30-second repricing dwell. Unchanged real-owner fixtures
reproduce no repricing after 180 seconds of consistently bad fresh samples six
seconds apart; two/four-second samples do start it. All 21 existing tests pass.
Timing starvation is verified synthetically and strongly supported live; exact
internal live resets are not observable. D-100 implements evidence-covered
accumulation and fresh send leases in isolation; production remains unchanged.

## 150. Recovery-only fencing and normal restart succeed after D-099 — 2026-09-23

VERIFIED LIVE: after a fresh 0-order/0-position venue check, generation 62
completed recovery-only as `STOPPED_FLAT`, cleared its recovery reasons and
disarmed without the prior shutdown timeout. Normal generation 63 then became
healthy and reached 30 resting orders/no reported position with a current
account snapshot and $118.20 reserved exposure at 13:23:56 UTC. Initial ranking
released at 120.14 seconds with 794/1,024 evaluated. This proves the terminal
fence and restart path for this run, not accelerated live-drain latency, payout
or profitability.

## 149. Per-order recovery made shutdown slow, then terminal fencing failed — 2026-09-23

VERIFIED LIVE: the normal stop path canceled 30 resting entries one at a time
from approximately 12:40:38–12:41:48 UTC. Each acknowledged cancellation
revoked continuity and required a full recovery before the next exact owned
entry could be selected. Local cleanup reached `STOPPED_FLAT` at 12:41:51, but
the stop latch then rejected the child's terminal `FENCE_ACK`; the supervisor
therefore recorded a false child failure/shutdown timeout after flatness.

Under explicit emergency authority the exact protected processes were stopped,
the official account-wide cancel returned HTTP 204, and a fresh GET-only check
at 12:43:19 UTC established zero resting orders and zero nonzero positions. No
fill occurred in that generation. The active settled six-hour result remains
-$1.551600. The implemented fast path is limited to paused, owned, nonreducing
entry orders with exact durable evidence and no prior submitted/uncertain cancel.
It removes repeated recovery waits, not mutation or transport proof.

## 148. Existing live run entered recovery during isolated verification — 2026-09-23

VERIFIED local status at 11:37:15 UTC: generation 49 recovering, new entries
paused, `blocked_retry_exhausted`, `ambiguous_send`, 8 reported resting entries
and one reported 10-contract position. No current account proof, so counts are
not independently reconciled venue facts. Retained diagnostics show repeated
recovery exhaustion; original child-death cause remains UNKNOWN. Canonical
source is still clean `221dacc`; D-098 remains isolated and undeployed. STATUS
owns the operational blocker; no production action was taken to suppress it.

## 147. Actual-code comparison identifies three lifecycle gaps — 2026-09-23

VERIFIED from Kalshi `221dacc` and read-only Poly `acba287f`: passive-deferred
plans could not obtain reducer dispatch/writer authorization; ordinary passive
cancels sorted by ID rather than building direction; reduced entry caps blocked
additions but did not drain overflow. Existing owners stayed but reward quotes
were not maintained, despite an existing tracker. The
[D-098 audit/build](docs/BUILD_ORDER_MAINTENANCE.md) records corrections, regression
reversals and comparison paths. Poly's 76 pure reconciler tests pass.

Qualifying owners remain even above estimated $1; a richer spare is not a
replacement trigger. Same-program estimates plus remaining projection are not
assured payment. The earlier hypothetical-reference census does not prove actual
order earnings. No production mutation/restart occurred in this unit.

## 146. Current slate is eligible but materially below the sampled best slate — 2026-09-23

MEASURED PUBLIC-ONLY over 1,024 reviewed markets from 10:47:46–10:49:21 UTC:
148 passed current $1/depth/70% market gates and 40 were in the $2+ priority tier.
All 15 live-owned markets passed, but only four were $2+; their diagnostic ranks
ranged from 7 to 130. Fourteen markets had orders at or better than sampled
references. `KXBUDLIGHTPOS-26OCT03-T87` had an ask at 48c versus a 43c reference;
its 50% per-tick program discounts five ticks to 3.125% price weight if the order
remains inside the cutoff. Automatic repricing is disabled.

The sampled owned slate totals $26.38 projected remaining / $0.218 per hour,
versus $44.05 / $0.494 for the diagnostic top 15. This is a sequential public
census with hypothetical flat-account admission, not guaranteed rewards,
private/public reflection proof, simultaneous replacement proof or net-profit
evidence. The top set is concentrated in related ladders and is not an allocation
recommendation or correlation-risk analysis. Existing no-replacement
policy explains why later superior rows do not displace incumbents. Full table
and limitations: [current market-quality check](docs/VERIFY_CURRENT_MARKET_QUALITY_2026-09-23.md).

## 145. D-097 survives standard status reads during live refill — 2026-09-23

VERIFIED LIVE: generation 49 restarted the preserved ledger on runtime
`fdda4cd9036a43cf90a4cf6c33e65d60`, child PID 29288. The initial checkpoint
released after 120 seconds with 801/1,024 historically evaluated. Standard status
commands were invoked repeatedly while paired entries increased from 22 to 30.
At 10:43:46 UTC the same child/run remained healthy with 30 orders, no reported
position, $127.60 exposure, all four readers subscribed and no engine, dispatch
or logging failure. A further 30-second observation retained the same identity.
No WARNING/ERROR event appeared from launch through acceptance.

This is operational acceptance of the observed transient status-contention fix,
not a proof against every external file-lock duration or permanent storage error.
Permanent publication failure still propagates and must remain fail-closed.

## 144. Status publication recurred after delete-sharing monitoring — 2026-09-23

VERIFIED: normal child failure at 06:09:22 UTC and recovery-child failure at
06:10:53 both record `PermissionError`, errno 13, at `startup.save_result`'s
`os.replace` (line 83). Ordinary Python diagnostic monitors had already ended;
the replacement monitor used ReadWrite|Delete sharing and also ended before
the normal failure. The exact interfering handle/cause remains UNKNOWN.
The prior hypothesis does not establish a fix or blame a particular reader.

Existing bounded recovery ultimately verified STOPPED_FLAT at 06:11:55 UTC:
zero orders, no positions, zero exposure. Read-only protected-role inspection
found no parent/child; control generation 48 is disarmed with no recovery holds.
No manual ledger/hold reset or force-kill was used. D-096's ranking acceptance
below is historical evidence, not a claim of continued operation.

## 143. Startup coverage and current eligibility are separate — 2026-09-23

VERIFIED LIVE in run `8e905c9477a34c8484c55ab32be5144d`: zero entries during
waiting; release at 120.132s with 864/1,024 evaluated; then 30 acknowledged orders
by 06:08:37 UTC. At 06:09:15, no fills/positions and $126 reserved exposure.
Matched selection-time samples put seven owned markets in $2+ and eight in
$1–<$2. Not a payout guarantee or simultaneous/global-optimum comparison.

The first attempt's `startup.save_result` failed at `os.replace` with Windows
PermissionError; it placed no orders and automatic recovery verified flat.
Standard diagnostic opens may deny delete-sharing (exact interfering handle
unidentified). A synthetic open-reader replacement passed with explicit
ReadWrite|Delete sharing, used during the later monitoring. Runtime
publication was not modified; general reader/writer hardening remains separate.

VERIFIED OFFLINE: D-096's opposite-shard fixture holds an early $1 fallback,
waits for a later $2 candidate, then ranks the $2 row first. Timeout does not
admit stale evidence, and direct dispatch cannot bypass the initial checkpoint.
Known economic exclusions count as evaluated; missing inputs do not. Inventory
cancellations remain independent. [Contract and limitations](docs/BUILD_INITIAL_RANKING.md).

Coverage is cumulative within source epochs, not proof that all metadata/books
are current simultaneously. The 120-second bounded wait may release partially;
current-source gates remain mandatory. No guaranteed payout or incumbent upgrade.

## 142. Reference pricing works; steady-state $2 priority does not — 2026-09-23

VERIFIED LIVE at 05:28:31–05:28:35 UTC: all 15 resting two-sided markets matched
fresh public bid/ask reward references exactly and scored at full price weight.
The ledger recorded 30 create ACKs, four create NOT_SENT attempts, and no cancel
or replacement mutation since restart. Runtime also reports
`automatic_repricing=false`. The bot placed at reference and has not repositioned.

MEASURED: those 15 programs projected $1.02–$1.90 remaining; none reached the
$2 priority threshold. A subsequent 96-second public-only broad census examined
1,024 reviewed markets: 174 passed the $1 gate and 30 sampled at $2+, with no
owned-market overlap. This census assumes a flat $500 account and samples markets
sequentially, so it is not simultaneous admission proof or payout evidence.

VERIFIED CODE MECHANISM: `MarketSelector.propose` sorts currently ranked $2 rows
ahead of $1 fallbacks. Runtime metadata/ranking arrives incrementally, however;
fallback entries can fill all 30 order slots before the broad board converges.
The entry cap then blocks additions and no incumbent upgrade/repricing policy
exists. Thus the configured sort is real, but the final live slate is not
globally $2-prioritized.

## 141. Normal restart reached the 30-order live limit — 2026-09-23

VERIFIED LIVE under D-095: after public candidate refresh and fresh account
reconciliation, runtime `e6b52e1b72ff496ab4b5d0eaf3925f46` placed 30 resting
orders across 15 two-sided markets with $126.10 reserved exposure and no observed
position by 05:22 UTC. Both book shards, account and lifecycle readers were
subscribed; engine, dispatch and logging had no reported failure or hold.

MEASURED over 15 one-second local snapshots: account/live-ready authority was
present for 9 samples and fail-closed during periodic reconciliation for six,
then restored. The orders remained at 30. This establishes restart and capacity,
not fills, exit quality, reward payment or profitability.

## 140. Host lifetime verified independently; manual cancellations reconciled — 2026-09-23

VERIFIED: [D-094 evidence](docs/BUILD_HOST_CONTINUITY.md) demonstrates inert
supervisor survival after launcher/job teardown and normal controlled shutdown.
Protected role absence correctly overrides old saved health. The cause of the
previous production disappearance remains inferred, not proved.

VERIFIED at 05:01:38 UTC: 28 exact canceled orders, zero fills in the bounded
history interval, zero resting orders and zero nonzero-position rows. Existing
order validators imported the terminal evidence after consistent backups;
financial/risk/history tables stayed unchanged. Bot remains stopped/disarmed.
These dated reads do not replace fresh startup/private-stream proof.

## 139. Integrated broad books and bulk metadata reduce census cost — 2026-09-23

MEASURED: [D-093 acceptance](docs/BUILD_BROAD_DISCOVERY.md) examines 1,013 markets
in 90.073 seconds / 570 public REST requests, versus 415.320s / 2,563 previously.
150 pass unchanged market gates, including 28 $2-priority candidates. No source
errors in the final run; the earlier three-expiry-failure run remains recorded.
The 4.6x timing improvement is not a controlled reward comparison; source times
and queue ordering differ. No actual account admission or profitability claim.

VERIFIED OFFLINE: 1,024-book engine/management/selection fixture proposes at most
15 pairs, retains writer/account bounds and coalesces entry scheduling. Exact
inventory revision reuse reduces repeated database work; current source checks
remain mandatory. Public data breadth is independent of resting-order capacity.
Sustained real account/fill/cancel latency remains unmeasured. Bot stays stopped.

## 138. Broad books and bulk metadata remove assumed API bottlenecks — 2026-09-23

MEASURED: all 1,013 currently reviewed/rewarded books arrived in 0.560s over two
WS connections; four 45-second scope stages met diagnostic resource/freshness
targets. Four bulk event requests returned 1,024 reviewed definitions and
milestone bindings in 2.228s; rules matched and sampled parser/detail comparisons
agreed. The venue does not force our observed 128/16/30s discovery schedule.

LIMITS: diagnostic queues differ from production; full economics/fee schedules,
account/ledger contention, sustained peak load and reconnects were not tested.
This supports proposing broad WS books plus shared bulk metadata, not widening
the live bot immediately or claiming subsecond complete ranking. Research also
evaluates ticker hints, REST book snapshots and FIX as alternatives, without
claiming unmeasured access/performance. [Evidence](docs/RESEARCH_DISCOVERY_OPTIONS_2026-09-23.md).

## 137. Passing markets exist beyond seeds; discovery remains rate-limited by design — 2026-09-23

MEASURED PUBLIC CENSUS: 1,013 current reviewed/rewarded markets examined in
415.320 seconds; 156 pass current market gates, including 32 $2+ priorities.
Only 15 passes (four priority) are in the 127 still-current saved seed markets;
141 passes (28 priority) lie outside. Actual private account admission is not
assessed. This does not establish the historical 28-order rejection cause.

VERIFIED CODE: D-091 preserves 128 book slots, at most 16 additions per change
and 30-second dwell. It fixes starvation, not fast universe-wide selection.
The synthetic 56-rotation coverage result implies roughly 28 minutes of dwell
for the additional 896 candidates, before source/ownership delays. These are
software settings, not a verified Kalshi limit. [Method, counts and next recommendation](docs/VERIFY_MARKET_GATES_2026-09-23.md).

## 136. Actual-scope progress restores bounded exploration coverage — 2026-09-22

VERIFIED SYNTHETIC: D-091 reaches all 1,024 candidates in 56 partial rotations
with 14 protected markets; old discovery reaches only 692 under the regression.
Deferred joins no longer consume unjoined candidates. A candidate outside the
initial 128 reaches the actual selector and supplies the fifteenth two-order
pair under a synthetic 28-entry view. This is not current venue eligibility or
profitability evidence. Minimum dwell and risk-aware refill are 30 seconds;
existing economic, source and capacity gates remain. [Evidence](docs/BUILD_DISCOVERY_COVERAGE.md).

## 135. Partial admission loses exploration coverage — 2026-09-22

VERIFIED CODE/SYNTHETIC: discovery advances across its proposed tail while
admission subscribes at most 16 additions. A composed frozen-input reproduction
with 1,024 programs, two shards and 14 protected markets visits 692, permanently
missing 332; full state repeats at cycles 119/189. Candidate-only coverage tests
missed this consumer mismatch. Six offline breadth diagnostics pass, including
this expected-bug characterization; production repair remains pending.

VERIFIED LOCAL: 128 seeds and two completed rotations bound the final live run
to at most 160 distinct subscriptions. The earlier 50 $2+ candidates were found
across 1,024, not the same live scope. UNKNOWN: exact historical last-pair blocker;
per-stage exclusions and the earlier per-ticker scan were not retained/located.
The operator prioritizes this coverage investigation. [Detailed evidence and
first repair](docs/INVESTIGATION_LIVE_EXIT_2026-09-22.md#priority-1-candidate-coverage-before-ranking).

## 134. Saved healthy state outlived the process; final-pair reasons unretained — 2026-09-22

VERIFIED: production parent/child are absent and the last heartbeat/runtime file
froze at 23:22:32 Eastern. Neither run recorded a terminal shutdown result.
The operator reports manual cancellation of all orders; current venue state was
not independently checked. Foreground process-tree loss is a possible cause,
not an established termination trigger. Saved status does not check liveness.

VERIFIED SYNTHETIC: selector and writer permit 28-to-30 entries. VERIFIED LEDGER:
28 ACK creates, four NOT_SENT creates, and no later create attempt after 23:18:10.
Repeated account refresh is observed, but per-entry rejection causes are lost
when dispatch status advances to IDLE. The exact plateau cause remains UNKNOWN.
The native parent-death test expects child exit, not continuous unattended
operation. Forty-eight existing focused tests and synthetic capacity checks pass.

CORRECTION: section 133's 5,018/5,060 counts came from the REST incentive catalog,
not captured lifecycle frames. Queue overflow is verified; snapshot size/cause
is not. [Evidence and repair priorities](docs/INVESTIGATION_LIVE_EXIT_2026-09-22.md).

## 133. Lifecycle reconnect loop was a deterministic 256-row overflow — 2026-09-22

VERIFIED LIVE/CODE: the normal post-D-089 restart reached 14 resting orders and
zero positions, then repeatedly failed only `lifecycle`. Every retained stack
ends at `transport._receive` line 152, the `asyncio.QueueFull` branch. Production
catalog enumeration observed 5,018 rows while `readonly_reader_factory` assigned
that connection only 256 queue entries / 2 MiB. Each reconnect replayed the full
unscoped snapshot, so retry policy alone could not converge.

Controlled stop canceled seven orders within five seconds and all fourteen by
the next eight-second observation; saved account state is `STOPPED_FLAT`, zero
positions/exposure. D-090 restores the transport's existing bounded defaults only
for lifecycle. After deployment, the normal child loaded 5,060 markets on
lifecycle attempt one and remained subscribed with no retry round. The accepted
snapshot was live-ready with 28 orders, zero positions and zero dropped logs.
[Build](docs/BUILD_LIFECYCLE_SNAPSHOT_BUFFER.md).

## 132. SENDING preceded transport and created false cancellation uncertainty — 2026-09-22

VERIFIED LIVE/CODE: the two remaining `UNKNOWN` ledger rows are cancels created
at 01:58:46.915618Z and 02:20:03.490654Z. The only matching retained
`mutation_unknown` events occur milliseconds later and contain `CommandDenied`
at the old `execution._execute_prepared` line 715, the explicit
`proof_changed_before_submission` branch. Both still correspond to the two saved
resting orders; no position is saved and no transport call is recorded.

VERIFIED CODE/SYNTHETIC: D-089 moves only that proven pre-invoke branch to
transactional `NOT_SENT`/`ABORTED`, preserves true UNKNOWN outcomes after invoke,
and re-signals recovery. Single and batch regressions cover ownership, atomicity,
capacity and zero transport. [Build](docs/BUILD_PRETRANSPORT_ABORT.md).

## 131. Successful safety cancels consumed the failure budget — 2026-09-22

VERIFIED LIVE/CODE: the authorized stop acknowledged two cancels before one stale
pre-transport proof stopped the old child. The first recovery-only child then
acknowledged three more cancellations, reducing the saved count to nine. Each
successful reconciliation/cancel cycle incremented `recovery_passes` and queued
fresh proof, but `_recover` counted it as an incomplete failed attempt. At three,
it latched `blocked_retry_exhausted`; the child correctly stayed alive because
the account was not flat, and the parent reported `shutdown_timeout` rather than
force-killing it. The child later exited; no force-stop command reached it.

D-088 separates verified forward progress from no-progress failures while
preserving one fresh proof per safety mutation. [Build](docs/BUILD_GRACEFUL_DRAIN_RECOVERY.md).

## 130. Reference-price path matches unified YES-price wire mode — 2026-09-22

VERIFIED OFFICIAL/CODE: book subscriptions explicitly set
`use_yes_price=true`. Kalshi therefore reports NO-side snapshot/delta levels in
YES-leg coordinates; the internal ask ladder must use those prices directly and
must not complement them again. The scorer walks YES bids downward and unified
YES asks upward until cumulative depth first reaches one fifth of Target Size,
then proposes the two reference levels. This matches Kalshi's current liquidity
rule and order-direction guide.

MEASURED LIVE/READ-ONLY at 21:45 Eastern: 128 current rewarded seed books
produced 128 unified-ladder checks and 128 program/reference comparisons; 246
sides reached one-fifth depth, with zero mismatches. Requested refreshes kept all
128 books fresh in every steady sample. No private REST or order mutation ran.
Gemini and Polymarket code independently use the same common YES/LONG economic
frame, but Kalshi's official mode plus live wire evidence—not cross-venue analogy
—is the authority. [Evidence](docs/VERIFY_REWARD_SOURCE_LIVE.md).

## 129. Lifecycle channel works; finite retry permanently retired it — 2026-09-22

VERIFIED LIVE/READ-ONLY: production PID 46576 reported `lifecycle=retry_exhausted`
after three attempts while other readers stayed connected. The old error detail
had rotated out, so its exact cause is UNKNOWN. A separate bounded lifecycle-only
subscription acknowledged the current `market_lifecycle_v2` channel and joined
cleanly, with no account endpoint, ledger or order access.

VERIFIED CODE/SYNTHETIC: all readers previously returned permanently after one
three-attempt round. D-087 continues only the advisory lifecycle source on capped
retry waits while revoking terms and increasing generations. A three-failure/
fourth-success regression and 160 existing focused checks pass. The active
process is unchanged; [implementation](docs/BUILD_LIFECYCLE_RECONNECT.md).

## 128. Live snapshot refresh keeps 128 sampled rewarded books fresh — 2026-09-22

MEASURED: [read-only source probe](docs/VERIFY_REWARD_SOURCE_LIVE.md), 21:19
Eastern, 30 seconds. Complete catalog: 5,006 programs in six requests / 5.376 s.
Two public-book connections validate 128 initial and 1,135 correlated refresh
snapshots. After warmup, the same-feed baseline without refresh timestamps
averages 4.81 fresh books versus 128 with refresh; final counts are 2 and 128.
This is source coverage, not 128 economically eligible markets or an earnings
claim. No private REST, ledger access, order action, restart or deployment.
The existing production catalog/lifecycle retry holds remained unchanged.

## 127. Reward-source omissions repaired offline — 2026-09-22

VERIFIED CODE/SYNTHETIC: D-086 implements the two actionable audit findings:
1,000-row complete catalog pages and quiet-book WS snapshot refresh. Existing
freshness, byte/row/time bounds, retry holds and economic gates remain intact.
The actual runtime/selector regression restores eligibility from a fresh
same-generation snapshot, while an old queued snapshot remains ineligible.
No order or live source was changed by verification. Source-sync into the active
checkout is deferred because it changes the recovery-child fingerprint.

MEASURED SYNTHETIC: 5,000/10,000 catalog rows take five/ten requests and pass the
existing resource gates. This does not establish live venue timing, broader
occupancy or earnings. [Implementation and evidence](docs/BUILD_REWARD_SOURCE_REFRESH.md).

## 126. Reward endpoint is correct; page size and WS refresh are underused — 2026-09-22

VERIFIED DOCS/CODE: [fresh reward API audit](docs/REWARD_API_REAUDIT_2026-09-22.md)
searches all 191 published REST operations and both WS schemas. There is still one
dedicated incentive-definition endpoint and no documented personal reward ledger.
Its 10,000-row maximum was already recorded September 19, while runtime and
preparation explicitly selected 100 rows per request. Roughly 50 sequential pages
inside 30 seconds is unnecessary overhead; exact production latency attribution
remains unmeasured. The existing read client caps each response at 2 MiB.

MEASURED: a bounded unauthenticated research read with 1,000-row pages retrieved
4,981 active liquidity programs in five pages / 1.986 seconds at 20:37:59 Eastern.
It used 1,894,742 total wire bytes, did not load keys or modify the live catalog,
and was not measured under production account/metadata contention. Recommend
testing 1,000-row pages first, preserving the existing resource/freshness contract;
do not assume a maximum-size request always fits or that this fixes every blocker.

VERIFIED DOCS/CODE: `update_subscription` supports `get_snapshot` without reader
replacement. Our reader currently only sends initial subscriptions. Optional own
order annotations also exist in book deltas, but are not full ownership/earnings
proof. These are implementation opportunities, not authority to relax freshness
or remove reflection/recovery checks. The $1 threshold remains per program.
This task changed documentation only; the fixes remain pending.

## 125. Low order breadth: catalog timeout plus freshness/discovery limits — 2026-09-22

VERIFIED LIVE: the unchanged normal run grew from 10 to 14 resting orders.
At 20:30:30 Eastern, child 46576 remained healthy/account-current with no
positions or accounting/risk blockers. Incentive refresh had exhausted three
attempts and had no current catalog. Retained diagnostics identify TimeoutError
inside the complete-enumeration 30-second deadline, not a zero-market response.
The shared read-budget status recorded zero throttles; the exact network/queue
latency responsible for missing that deadline was not measured. No fresh catalog
means no new selection authority, even while process/account status is healthy.

VERIFIED SYNTHETIC/CODE: [breadth probe](scripts/diagnose_selection_breadth.py)
reproduces five behaviors without credentials, venue calls or the live ledger:

- The same eligible pair is selectable with fresh sources, disappears after its
  book ages six seconds despite refreshed account/risk/reward/metadata, and
  returns after an identical fresh snapshot. `InventoryManager._book` rejects
  per-market ingress older than five seconds. A quiet connected book is therefore
  not sufficient under current policy; this test does not authorize changing it.
- The production writer uses its default 128-market capacity. A synthetic 1,024
  market catalog yields 128 discovery candidates and defers 896. This working set
  is separate from the 30 resting-order ceiling and is not itself a five-market cap.
- Actual admission adds at most 16 new markets per successful cycle and normally
  schedules its next cycle 300 seconds later; requests can wake it sooner.
- Three injected catalog timeouts remove selection source authority and exhaust
  automatic retries. This reproduces the live failure mode, not its network cause.
- Forty fresh qualifying fixture markets yield 15 pairs / 30 orders, with $138
  estimated capital. There is no hidden 10-order selector cap.

INFERRED: five-second book expiry combined with delayed metadata and slow scope
rotation limits practical discovery. The live status repeatedly had 126 pending
metadata refreshes with two active workers and only zero/one current selection
proof. These snapshots are not a cumulative rejected-market census. Existing
diagnostics do not establish how many live markets failed each economic gate;
do not claim all 1,024 reviews qualify or that 30 orders are guaranteed.

Verification: all five explicit characterization probes and 136 existing tests
(47 selection, 36 admission, 27 metadata, 26 incentive discovery) pass. These
passes confirm behavior, not production readiness. No runtime logic/configuration,
live process, order, limit or ledger was changed by this diagnostic task. The
catalog failure and selection-throughput work remain open; no fix is claimed.

# 124. Six live markets were an admission handoff failure, not the eligible universe — 2026-09-22

VERIFIED from generation 12 status and executable control flow: discovery held
1,024 reviewed candidates and the incentive catalog held roughly 5,000 current
markets, but admission completed zero rotations. `MetadataScheduler.step()`
continuously launched up to two refreshes, while `MarketAdmission.removable()`
required the scheduler and its shared dependency reads to be completely idle.
The required idle instant was therefore not a reliable handoff protocol.

The repair adds one bounded exact-scope reservation: active reads finish, queued
metadata remains queued, and admission retries through its existing one-second
backoff. The reservation cannot authorize a scope change, expires after five
seconds, and is canceled on successful rebind or stop. All existing account,
inventory, source, timing, capacity and ownership proofs remain in force. The
full suite ran 1,453 tests: 1,452 passed and one expected skip.

VERIFIED OPERATIONAL FOLLOW-UP: D-085 approved the exact pre-transport cancel
attempt retained at 23:34:25 UTC. With parent/child/account ownership held and
processes stopped, a SQLite backup and transactional audit preserved the original
rows before UNKNOWN became NOT_SENT and the matching authorization ABORTED. The
retained CommandDenied stack points to the pre-transport proof-change branch;
this is not permission to retry other UNKNOWN commands. The backup, one-off
script and ledger audit remain ignored under `data/trader/`.

Recovery generation 25 canceled the two remaining orders and terminated
STOPPED_FLAT at 20:17:22 Eastern with no positions or holds. The normal run
started at 20:17:44; at 20:23:48 the fresh local status recorded 10 resting
orders, zero positions and two completed admission rotations (previously zero).
The catalog contained 5,024 current rewarded markets and candidate reviews
covered 1,024; neither count establishes current entry eligibility. Continued
expansion beyond six occupied markets and actual reward profitability are not
yet verified. No filter, loss/capital limit or accounting baseline was changed.

## 123. First live opening retained exact personal cash but could not attribute it — 2026-09-22

VERIFIED LIVE ACCOUNT / ZERO MUTATIONS: the first explicitly authorized
supervised initialization observed a flat primary account with zero orders,
positions and exposure. Its immutable opening evidence retained an applied $500
personal deposit and a completed $0.4417 intra-exchange transfer, both created
before the boundary but lacking venue completion timestamps. The generic D-068
policy therefore retained `cash_activity_unattributed`; opening approval failed
before dispatch and bounded supervisor recovery ended in `attention_required`.
No order endpoint was invoked. D-084 records the operator attribution and the
narrow recovery correction; this is startup evidence, not profitability or
payout evidence. [Build and runtime record](docs/BUILD_FIRST_LIVE_OPENING_RECOVERY.md).

## 122. Current-path findings are repaired without weakening create proof — 2026-09-22

VERIFIED CODE/SYNTHETIC: R1–R4 from finding 121 are connected to their actual
consumers. A durable hard loss hold now drains exact owned entries and blocks
entry/admission; cancellation retains account/order/writer/quota proof while
dropping irrelevant price/terms freshness; the exact selected reward program is
pinned through both send fences; and every overlapping program is qualified and
tiered before one is selected per market. New production-path regressions and
30/120 resource gates pass. This does not change lower loss-tier rotation,
inventory exit policy, live authorization or profitability evidence. Full
mechanisms: [build report](docs/BUILD_CURRENT_PATH_REPAIRS.md).

## 121. Final live-path review finds four missing integration cases — 2026-09-22

VERIFIED CODE/SYNTHETIC at `4818612`: a held loss window leaves flat-market entry
orders resting; incentive revocation after reservation still reaches a fake
production-mode batch transport; a six-second-old book blocks otherwise valid
paused-entry cancellation; and a short overlapping program hides a $3.521
remaining-reward alternative. These are current-path repair findings, not
requests for optional hardening. The [canonical review](docs/REVIEW_CURRENT_LIVE_PATH_2026-09-22.md)
contains priority, source locations, reproductions and repair acceptance criteria.
No live order, account request, production ledger or runtime mutation was used.

## 120. Current scope supports a $2 priority tier with a $1 fallback — 2026-09-22

MEASURED PUBLIC SNAPSHOT / VERIFIED CODE: a sequential credential-free snapshot
of the 1,024 reviewed candidates joined 4,919 active incentive rows and found
992 valid two-sided scoring pairs. At size 10 on both reference-price sides, 596
passed a 70% per-side retained-value test, 218 also projected at least $1 through
the bounded earning horizon, and 50 projected at least $2. All 50 $2 candidates
also passed the retained-value gate. This supports a priority/fallback selector
for the current maximum 15 two-order markets without removing the $1 fallback.

D-083 implements that policy in the actual selection path. Remaining reward is
recomputed as time decays; source revisions are still checked before dispatch.
The counts are a non-simultaneous snapshot and do not guarantee later
eligibility, $1 payment, fills or profitability. [Contract and boundaries](docs/BUILD_ENTRY_QUALITY_GATES.md).

## 119. Scheduled-release candidates unblock preparation; sports remain unknown — 2026-09-22

VERIFIED CODE/PUBLIC DATA: the pre-fix public candidate loop accepted zero
markets because 2,878 reached the blanket early-close exclusion. D-082 now
recognizes one exact Kalshi family: economic-data releases whose early-close
condition, occurrence time, reviewed milestone type and sole future primary
milestone all agree. Occurrence time is included in the rules digest and the
timing relation is rechecked from current metadata before entry.

The post-fix public refresh prepared 1,024 bounded candidates and 128 initial
books from 4,923 incentive rows and 4,917 markets. It still blocked 1,505 unknown
early-close rules, 1,960 missing primary milestones and 38 ambiguous bindings.
These candidates remain subject to current incentive-catalog membership, fresh
WebSocket-book ranking, metadata, account, risk and dispatch checks; preparation
does not prove reward payment or profitability.

Poly's executable sports path still requires supported structure, scheduled
time, fresh parent-event evidence, durable started state and send-time rechecks.
Kalshi related-event links alone do not establish safe timing or reward
eligibility. A table-tennis provider sample had unresolved freshness semantics,
so D-082 does not approve sports or any other unknown early-close family. See the
[candidate timing audit](docs/REVIEW_CANDIDATE_TIMING_POLY.md).

## 118. D-081 lifecycle blockers are repaired offline — 2026-09-22

VERIFIED CODE/SYNTHETIC: all seven findings in the
[end-to-end review](docs/REVIEW_D081_END_TO_END.md) now have production-path
repairs and regressions. Restriction transitions persist atomically before their
component continues and are transferred through authenticated fences; inherited
cooldowns wait under parent heartbeat/stop supervision. A new explicit arm may
retry exhausted quota but must obtain fresh quota proof before runtime. Temporary
risk/accounting health remains diagnostic rather than a durable retry hold.

The final complete suite ran 1,428 tests: 1,427 passed and one expected Windows
privilege test skipped. Supervisor idle/resource, offline S2B, selection and
admission gates pass. No production data, credential, venue request, bot process
or live order was used. This closes software review findings, not live acceptance
or profitability evidence.

## 117. Production wiring passed tests but missed lifecycle guarantees — 2026-09-22

VERIFIED CODE/SYNTHETIC: [D-081 end-to-end review](docs/REVIEW_D081_END_TO_END.md)
finds seven unresolved defects; six are reproduced with isolated offline probes.
Passing 7 production and 26 live-runtime tests did not cover account-lease
release during exception drain, stalled preparation supervision, sticky health
holds, lost terminal status, expired-candidate recovery or exit-27 mismatch.
Actual cooldown/exhaustion restoration is also absent in the production path.
Finding 116's entry-pause wiring exists, but its implied recovery readiness is
withdrawn. No live run or implementation fix occurred. Repair checklist 2–6
before supervised live acceptance; full evidence and acceptance cases are linked.

## 116. Production restarts must be recovery-only — 2026-09-22

VERIFIED CODE/SYNTHETIC: the production host now launches only the fixed
`supervised_live_child` profile. A normal child may use the existing entry gates;
after an unexpected exit, persisted `recovery_reasons` force every bounded
replacement into recovery-only mode. That mode pauses entries before runtime
composition, reuses `data/trader/account.db`, and cannot replay initialization.
A verified-flat result disarms instead of resuming entries. Parent credentials,
arbitrary child commands and fixture-scope promotion remain unavailable.

The start/stop/status scripts use the protected supervisor journal. Status labels
its PID/runtime material as saved evidence rather than current liveness. The
complete offline suite passes 1,419 tests with one expected privilege skip. No
live process, venue call, ledger or order was created during verification.
[Contract and failure boundary](docs/DESIGN_PRODUCTION_SUPERVISOR.md).

## 115. Supervisor connection requires a recovery-policy bridge — 2026-09-22

PRE-D-081 VERIFIED CODE, now superseded: `scripts/Start-LiquidityBot.ps1` invoked `kalshi_bot.live`
directly. `supervisor_control.ScopeSpec` only accepts test account scopes and
`supervisor_fixture.fixture_path` points to a fixed test child. The S2B contract
holds after an incomplete terminal fence rather than automatically relaunching.
Consequently production integration requires explicit recovery semantics as well
as launcher wiring. [The ordered checklist](docs/history/NEXT_ARCHIVE_2026-09-26.md#production-supervisor-connection--ordered-checklist)
tracks that work; an implementation time estimate is not completion evidence.

Polymarket source comparison: `scripts/supervise_commissioning.sh` distinguishes
clean exit, startup refusal, non-flat/integrity failure and recoverable failure;
its host recovery-only path exits after recovery and leaves trading paused.
`scripts/install_host_watchdog.ps1` registers an at-logon interactive task, so its
existence does not prove unattended pre-login reboot recovery. These are source
findings from the local read-only reference, not a current process/task audit.

## 114. A rules hash is not an early-close timing review — 2026-09-22

VERIFIED CODE/SYNTHETIC: the first automatic preparation revision set
`early_close_reviewed` for every candidate after hashing its rules. The digest
could detect later text changes but could not prove what a natural-language
early-close condition meant. It also filtered imminent milestones before
checking uniqueness, registered no schema entry for its launch log, and could
overfill restart subscriptions by unioning 128 seeds with a rotated owner.

Automatic preparation now excludes early-closing markets, resolves milestone
uniqueness before T-5, logs through a registered bounded event and gives durable
owners subscription priority over optional seeds. The old ignored automatic
input is deliberately rejected until initialization refreshes it. Synthetic
regressions and the 1,412-test offline suite pass; this is safety/operability
evidence, not profitability or a live-launch result. [Correction record](docs/BUILD_AUTOMATIC_CANDIDATES.md).

## 113. Ranking existed, but one input ticker made it meaningless — 2026-09-22

VERIFIED CODE/READ-ONLY: the selector already ranks gross hourly reward from
fresh order-book competition and then capital efficiency. Its launch authority,
however, contained one timing review, so no cross-market ranking was possible.
D-079 now prepares a bounded broad scope from current public incentives, complete
rules and unique future primary milestones. A real refresh produced 1,024
candidates and 128 initial books without account or mutation access.

The cheap reward/target hint is known not to identify actual revenue. It is now
limited to a 30-market head while a stratified event-diverse tail preserves
exploration; final selection still requires WebSocket books. This improves the
candidate universe but does not prove the globally best market, paid reward or
profitability. [Evidence](docs/BUILD_AUTOMATIC_CANDIDATES.md).

## 112. Reviewed candidates and subscribed books are different scopes — 2026-09-22

VERIFIED CODE/SYNTHETIC: D-071 admission was built but absent from D-077's
composition. Merely attaching it would discover candidates without their timing
reviews or matching live-session permission. D-078 carries an explicit reviewed
registry, filters discovery, restores reviews on admission and requires fresh
metadata/book evidence before dispatch. A fixture now takes B from an A-only
seed through actual joined scope replacement, metadata, ranking and pair ACK.
Unsupported fees and unreviewed candidates do not dispatch. Source review also
found that entry dispatch did not explicitly test metadata result blockers;
that check is now retained at the handoff.

D-079 subsequently replaces the one-market operational limitation with bounded
public rules/primary-milestone preparation. Neither implementation is a
profitability result. [Evidence and boundaries](docs/BUILD_LIVE_SELECTION.md).

## 111. Component tests did not establish an operable composition — 2026-09-22

VERIFIED CODE/SYNTHETIC: full original-owner composition exposed three real gaps:
accounting release advanced the writer revision and made its own account report
unusable; inventory book/deadline/fill callbacks did not request exit dispatch;
the shared quota listener cap allowed four consumers while the full graph needs
five. Corrections retain the original proofs and ownership. The complete graph
now reaches a synthetic entry ACK without any `offline_fixture=True` switch.
An explicit bootstrap supplies the shared write bucket before runtime start.

Repeated composition checks also reproduced a periodic refresh racing the
command's own writer revision. Refresh now waits for an active dispatch;
private ingress and outcome reconciliation are unchanged. Ten consecutive
synthetic startup-to-ACK runs passed after this fix. The flat shutdown check
uses read-only evidence, not the revision-changing order-settlement method.

VERIFIED READ-ONLY: real account/book/lifecycle subscriptions, reward catalog,
metadata and current quotas are accessible. A fresh startup history scope must
not adopt old manual trades into a new bot ledger. A past successful recovery
label is not a current account snapshot; startup now checks both. No real order,
baseline approval, net profit or reward payout was produced. [Evidence and limits](docs/RUN_LIQUIDITY_BOT.md).

VERIFIED INPUTS, 15:15–15:19 UTC: after the operator confirmed a direct personal
member account, the selected `KXAAAGASD-26SEP23-4.4750` scope passed exact rules,
primary milestone, early-close review, shard and fee-bound validation through the
real metadata adapter with no blockers. Its event-risk milestone begins at 02:00
UTC on Sep. 23 and the market closes at 03:59 UTC. The observed-book estimate was
$1.06 remaining reward on $9.60 combined quoted collateral. A subsequent bounded
startup run on this exact ticker connected all required readers and stopped cleanly.
The estimate is time-sensitive and unpaid; the startup run had no mutation owner.

## 110. A bounded same-day canary can clear the estimated $1 gate — 2026-09-22

VERIFIED ACCOUNT READ: primary cash was $500.4268 with zero nonzero positions
and zero resting orders. MEASURED LIVE PUBLIC SNAPSHOT: the strict short-market
scan rejected current sub-$1 opportunities, then a six-hour bounded scan found
a same-day gas-price program quoting YES $0.71 / NO $0.25. At size 10 its static
current-book estimate was $1.49, maximum combined entry cost $9.60 and maximum
one-sided contract loss $7.10. The plan expired without submission. These are
selection estimates, not paid rewards, realized P&L or profitability evidence.

## 109. Runtime restart may transfer restrictions, never authority — 2026-09-22

VERIFIED CODE/OFFLINE: the fixed native S2B child applies a validated bounded
recovery fence before creating its disposable ledger or issuing any fake read.
The parent ACKs only after committing increasing component holds, non-shortening
cooldowns and terminal-checkpoint state for the exact child/session/generation.
Unexpected death or missing terminal state installs `recovery_fence_unknown`;
a new parent session retains cooldown uncertainty as a hold. Tokens, quota
grants, snapshots, leases and source freshness always restart empty. Explicit
resolution is childless and current-revision scoped; heartbeat/ARM cannot clear
it. MEASURED: native clean/crash/exhaustion cases, 170 focused/regression tests,
the 1,362-test complete suite and 30/120-market resource fixtures pass. This is
supervision evidence, not account recovery or live authority. [Exact evidence](docs/BUILD_WINDOWS_SUPERVISOR_S2B.md).

## 108. S2A idle cost was redundant security traversal plus no-op durability — 2026-09-22

VERIFIED CODE/MEASURED: reopening and retraversing protected SQLite sidecars on
each serialized command plus FULL commits for timestamp-only timer ticks kept
the inert parent above its CPU target. Retained non-delete-sharing sidecar
handles preserve exact DACL revalidation and prevent replacement. Timer-specific
coalescing occurs only after trusted clock and full policy evaluation and never
suppresses an action or material transition. The complete 60-second/100-cycle
fixture now passes at 0.781% parent CPU with -2 warmed handles, -2 native threads
and no retained Python/supervisor thread. [Exact evidence](docs/BUILD_WINDOWS_SUPERVISOR_RESOURCE_FIXES.md).

VERIFIED ACCOUNT READ: bounded authorized verification beginning
2026-09-22T05:13:56Z used two limits/cost pairs plus one costs-only inspection
and validated read 200/600, write 100/100 and default cost 10.
The real document's `:order_id` and `*endpoint` forms exposed and now regress a
parser incompatibility; supported single cancel costs 2, while creates use the
default 10. This is current quota input, not token balance or permanent
entitlement. Member fee class, selected-market timing and launch-boundary account
state remain UNKNOWN.

## 107. Reward estimates require exact short-lived cross-source reflection — 2026-09-22

VERIFIED CODE/OFFLINE: production estimate publication now requires exact equality
between the fresh private resting-order set, account-wide queue-position rows and
the expected exchange-indexed aggregate WebSocket level. Any missing, extra,
stale or raced identity revokes the sample to UNKNOWN. Checkpoints preserve
bounded historical estimates but never restore live proof or claim payment.
Runtime owns load-before-observation, periodic coalesced save and final joined
flush. [Exact contracts and tests](docs/BUILD_REWARD_REFLECTION.md). No account
call, order action or live process was used for this implementation evidence.

## 106. A local atomic pair does not make the venue batch atomic — 2026-09-22

VERIFIED DOCS/CODE: Kalshi V2 batch create returns per-order rows, permits a
nullable client ID on an error row, charges create cost per order and bills the
batch endpoint to the unscoped shard. D-072 therefore makes only local
risk/intent preparation atomic. Response rows bind by client ID, never position;
mixed outcomes latch recovery, while an unidentified error makes both legs
UNKNOWN. No timeout/HTTP failure is rejection proof and no pair is retried.
MEASURED: synthetic 30/120-pair prepare/abort gates pass with zero retained
active entries or held capacity. [Sources, exact workload and limits](docs/BUILD_ENTRY_DISPATCH_TRANSPORT.md).
Live activation and production reward reflection remain separate.

## 105. Market rotation must retain ownership through reader teardown — 2026-09-21

VERIFIED CODE/OFFLINE: candidate ranking now reaches actual runtime subscription
scope through a joined book-reader replacement. Account/catalog/writer evidence
is rechecked after teardown; removal requires exact flat/clear inventory, not a
zero aggregate balance or missing cached plan. New scope must resnapshot before
ranking. A canceled request is rechecked after final writer awaits to prevent
late commits. The in-memory guard reversal reproduces that race.
MEASURED: 30/120-market scope commits have p99 1.057/1.546 ms in ten synthetic
cycles; not reader/venue latency. [Workload, tests and limits](docs/BUILD_MARKET_ADMISSION.md).
Live transport activation, entry dispatch and readiness are separate work.

## 104. Qualifying time is not a guaranteed dollar — 2026-09-21

VERIFIED CODE/OFFLINE: Poly uses bounded detailed discovery, refreshed cached
replacement candidates and flat/clear ownership before release; its projection
is not proof of personal accrued rewards. D-070 adopts these mechanics without
a fixed market pool. Kalshi estimates now use actual quotes, separate program
identities and sampled intervals; stale/unknown/restart intervals add no assumed
income. Neither elapsed time nor crossing an estimated $1 proves a payout.
UNKNOWN: no production own-order/public-book reflection producer is verified.
Positive integration tests use explicit fixtures, not inferred venue evidence.
MEASURED: shared validation handles 16 overlapping programs/4,096 levels per side
in 42.427 ms in the named synthetic boundary case; representative 30/120-market
gates pass. [Source links, tests and remaining wiring](docs/BUILD_REWARD_TRACKER.md).

## 103. A complete incentive catalog is not market admission — 2026-09-21

VERIFIED CODE/OFFLINE: complete active-liquidity cursor enumeration now feeds
the existing subscribed selection scope. Unsupported reward terms exclude the
identified market; duplicates/incomplete scope reject the entire publication.
Freshness starts before enumeration, and distinct refresh attempts cannot
re-age a retained older wire call. Catalog disappearance never releases an
inventory owner. Cursor exhaustion is not an atomic exchange snapshot.
MEASURED: 5k/10k synthetic catalogs satisfy the declared component CPU, memory
and loop-delay budgets; [scope and evidence](docs/BUILD_INCENTIVE_DISCOVERY.md).
Subscription rotation and entry dispatch remain separate build work.

## 102. A good replacement quote does not prove a resting order earns — 2026-09-21

VERIFIED CODE/OFFLINE: explicit quote sets can be discounted or pushed beyond
the reward cutoff while newly calculated reference quotes still score. Keep
these assessments separate; retain working/unknown owners and never infer that
an unscored order cannot fill. Program start/end and the earlier entry/exit
deadline are independent clocks; hourly rate uses the full program duration.
MEASURED: shared book validation reduced the named 4,096-level/16-program
fixture from 465.737 to 44.754 ms; not a production latency guarantee. See
[tests, resource scope and limitations](docs/BUILD_MARKET_SELECTION.md).

## 101. Reuse selection mechanics, not Poly economics — 2026-09-21

VERIFIED CODE/OFFLINE: Poly's detailed ordering uses projected own reward within
viability/phase groups, with bounded scans and cached-candidate revalidation.
Its positive economic floor and eligible-but-not-necessarily-viable side sum
must not become Kalshi's net-profit or admissible-quote score. Kalshi already
has venue-specific reference/share arithmetic and separate ranking views.
The [audit](docs/POLYMARKET_RANKING_AUDIT.md) records source revision, current
official reward constraints, 124 passing focused tests and proposed adaptation.
Selection policy and integration remain pending; no profitability was measured.

## 100. Dispatch lifetime must outlast accepted outcomes — 2026-09-21

VERIFIED CODE/OFFLINE: source revocation alone is not a completed shutdown.
The runtime now fences dispatch synchronously and joins the accepted outcome
before cancelling reader peers or returning to the writer owner. Cancelling
the parent repeatedly does not detach that work. A fresh fixture writer/runtime
with restored synthetic sources still cannot replay a durable UNKNOWN command.
MEASURED: 30/120 keys with 10,000 duplicates coalesce within declared scheduling
budgets and cause no idle service polling. [Evidence and exclusions](docs/BUILD_DISPATCH_LIFECYCLE.md).
This is not proof of production process restart or real-account reconciliation.

## 99. Write outcomes must re-signal after durable recording — 2026-09-21

VERIFIED CODE/OFFLINE: recovery can consume an early outcome notification while
the writer commit is awaited. Revoke and re-signal after retained persistence,
including failure, to avoid losing the final recovery request. A regression
fails when that post-persistence fence is bypassed in memory. HTTP 429 does not
release durable authority or justify retry; only the original exchange shard
is paused. One scalar notice contains no raw body/exception. See
[tests, official source links and resource scope](docs/BUILD_MUTATION_OUTCOMES.md).
These checks do not prove successful real-account reconciliation or live readiness.

## 98. One observed quota pair for separate read/write budgets — 2026-09-21

VERIFIED CODE/OFFLINE: full write method/path costs now flow from the existing
guarded document refresh rather than the read-only projection. A cached budget
cannot outlive the source's grant margin, reader identity or freshness. Source
checks at consumption block dispatch even after durable SENDING. The
[build record](docs/BUILD_WRITE_QUOTA_SOURCE.md) includes tests and measurements:
eight refreshes use 16 injected GETs at both 30 and 120 shards. This is not
real account quota evidence or production transport clearance. Member rounding
profile remains an explicit verified input; it is not inferred from decimals.

## 97. Source-bound cancel/reducer dispatch — 2026-09-21

VERIFIED CODE/OFFLINE: existing inventory strategy can feed exact candidates
through the durable writer and sole injected dispatcher with current account,
book and terms proof. Source expiry or replacement between preparation and
submission prevents invocation. Cancel ACK remains nonterminal; ambiguity
never becomes an automatic retry. Review closed stop-during-handoff and
retained-permit gaps. [Evidence and resource scope](docs/BUILD_DISPATCH_SOURCES.md).
This establishes neither real fee/quota inputs nor a production trading path.

## 96. Operational reconciliation without claiming a venue barrier — 2026-09-21

VERIFIED CODE/OFFLINE: D-068's new positive path releases only transient holds
after actual writer-owned audits, current history receipts/private epoch and a
separately approved synthetic baseline. Local cash accounts for YES/NO buys,
matched collateral and actual fees. Global and per-exchange cash ceilings are
independent; working obligations are not deducted twice from venue availability.
The [build record](docs/BUILD_ACCOUNT_RECONCILIATION.md) records tests and resource
measurements. The actual Poly reference uses exact owned-order reconciliation,
freshness gates and local buying-power decrements, not a stronger venue guarantee.

LIMITATION: a common REST/WS delay is explicitly not detected by agreeing stale
sources; the test preserves `venue_handoff_proven=false` even on successful
operational release. D-068 approves this criterion. Economic settlement/funding/
correction restrictions still require their cause resolved. No real-account
verification, trading, runtime changes or boundary approval occurred.

## 95. Release policy, not an undocumented timestamp guarantee — 2026-09-21

VERIFIED SOURCE: [Get User Data Timestamp](https://docs.kalshi.com/api-reference/exchange/get-user-data-timestamp)
is an approximate API validation indicator. Neither it nor repeated agreeing
snapshots establishes a shared REST/private-stream checkpoint. VERIFIED CODE:
the current accounting capture installs `opening_proof_unresolved`; its review
operation cannot release it. Polymarket's `account_snapshots.py:426` brackets
cash reads, but does not supply the missing Kalshi guarantee.

PROPOSAL: reconcile the exact bot-owned order/fill universe and use the lower
of current venue cash and independently accounted cash after obligations.
This avoids subtracting the same inferred venue hold twice, but depends on a
reviewed starting balance, exact owned cash flows and verified fee bounds.
No claim is made that common REST/stream delay is detectable. D-068 asks for
the policy choice before implementation; [design](docs/DESIGN_OPENING_ACCOUNT_ACCOUNTING.md).
No trading/runtime code or account state changed during this investigation.

## 94. Accounting restrictions now reach durable command gates — 2026-09-21

VERIFIED OFFLINE: D-067 adds persistent restrictions checked during atomic entry
reservation and prepared-entry dispatch. A fresh report, caller account-known
flag, empty settlement page, next risk window or writer restart cannot bypass
them. Snapshot/cash/history observations do not manufacture fills, lot basis or
settlement P&L. Boundary-ambiguous fills stay in a separate durable journal.
Current official [balance](https://docs.kalshi.com/api-reference/portfolio/get-balance),
[settlement](https://docs.kalshi.com/api-reference/portfolio/get-settlements) and
[position stream](https://docs.kalshi.com/websockets/market-positions) contracts
were rechecked; a shared replay barrier and exact cash/hold attribution remain
UNKNOWN. See [build evidence](docs/BUILD_DURABLE_ACCOUNTING.md).

## 93. D-066 settlement pause rule is accepted, not runtime-integrated — 2026-09-21

OPERATOR POLICY: unexpected settlement of a bot-owned open position pauses
new entries pending reconciliation; it does not automatically enter the
six-hour matched-fill loss meter. VERIFIED OFFLINE: the opening-account
assessment flags a retained settlement after its proposed boundary, keeps
prior-boundary rows historical, and does not mutate the risk window. This
is not bot-ownership proof or a durable runtime hold. Kalshi's documented
settlement history is REST and has no shared private-stream replay barrier or
stable correction ID in its published row schema; [accounting design](docs/DESIGN_OPENING_ACCOUNT_ACCOUNTING.md)
records the remaining gate.
The focused 25 tests and 1,024-test full suite pass (one expected Windows
privilege skip); the opening benchmark and disabled preflight pass their
offline gates.

## 92. Opening-account assessment remains local evidence — 2026-09-21

VERIFIED OFFLINE: a revision/scope-matched flat account snapshot can be
classified without treating it as an approved opening basis. The new pure
assessor preserves the venue handoff, non-atomic cash and operator-boundary
blockers. Focused tests cover primary/nonprimary, open positions/orders,
changed cash, settlement presence, pending fills and report/revision conflicts.
Polymarket's checked source separates pre-bot history and account-wide equity
from bot P&L, and treats unknown position basis as unknown; those boundaries
inform this design, but no venue-specific Poly accounting was copied. No live
account read or ledger write occurred. The full 1,022-test suite passes with
one expected native privilege skip; opening benchmark passes all three fixture
sizes and disabled preflight remains blocked as intended.

## 91. Offline write permit is checked at the send edge — 2026-09-21

VERIFIED OFFLINE: the previous dispatcher consumed the local write permit
before awaiting the writer's SENDING transition. It now checks the still-held
permit before that transition and consumes it synchronously after SENDING,
immediately before the injected transport call. A synthetic expiry during the
await results in zero injected sends and a durable UNKNOWN outcome; it cannot
be retried as proven unsent. This addresses only the injected path. It does
not establish a production write budget, account scope, actual 429 behavior
or live order authority. The full 1,018-test suite passes (one expected native
privilege skip); disabled preflight remains side-effect-free and blocked. See
[build evidence](docs/BUILD_WRITE_DISPATCHER.md).

## 90. Scoped cash observations do not establish an opening ledger — 2026-09-21

D-064 OPERATOR POLICY: use primary subaccount 0 exclusively for this bot and
start only after verifying zero nonzero positions and zero resting orders.
The offline evidence reader now labels nonprimary scopes and nonflat inventory;
a zero-quantity position row is not itself open inventory. This policy does not
prove current account state, venue history/stream continuity or a launch time.
The 1,015-test suite passes (one expected Windows privilege skip); the renewed
50,000-row synthetic evidence fixture meets its declared bounds. No account
request or ledger/baseline mutation occurred.

VERIFIED OFFLINE: D-062's evidence reader retains source/query provenance,
cash precision, optional settlement payout and pre-boundary pending/unknown-time
funding. It cannot approve a baseline or entries. Current historical-fill docs
now publish a subaccount filter; the [dated update](docs/API_REFERENCE_NOTES.md)
supersedes that one captured-contract omission. No shared REST/private-stream
barrier or atomic cash snapshot is established.

MEASURED: initial synthetic 50,000-row normalization used about 14.2 MB and
338 ms, but loop p99 61.2 ms missed <50 ms. Sequential 512-row worker batching
now passes the same fixture: 379.857 ms wall, 14.2 MB, p99 9.349 ms and maximum
41.341 ms, with global duplicate checks and unchanged source evidence. This is
not full REST/runtime acceptance. The [build record](docs/BUILD_OPENING_ACCOUNT_CASH_EVIDENCE.md)
owns details and limitations. No account/credential/trading action occurred.

Priority 4's [offline write budget](docs/BUILD_WRITE_BUDGET.md) passes 33 exact
fixture tests. Local estimates start empty; permits cannot outlive observations,
survive refresh/429 invalidation, or be reused/copied. Scope identity alone is
not a cross-process account allowance. Primary review corrected O(shards) hot
refills to addressed-shard-only work. After bounded route caching, paired-clock
reuse and a single readiness pass, five-sample synthetic 30/120-shard workloads
pass <250 ms CPU and <8 MiB peak; the 12,000-command maximum was 187.5 ms CPU,
22,572 B peak in the latest run. This is local arithmetic, not venue rate-limit
verification. The [offline dispatcher](docs/BUILD_WRITE_DISPATCHER.md) now
prioritizes safety cancellations and connects injected candidates to one durable
writer/executor; 45 focused tests pass. It cannot supply production account,
transport, or live readiness authority.

## 89. D-060 R1-R6 corrected under complete-history acceptance — 2026-09-21

VERIFIED OFFLINE: original authorization epoch/revision and immutable command
terms now survive relabelling attempts and restarts; reducer preparation derives
one current route and requires a current exact management/exit decision plus
terminal, fully accounted inventory evidence;
proven-unsent cancellation/reducer work reuses its funded logical slot with at
most eight retained authorizations; every failure after SENDING retains the
executor recovery hold. Trigger-maintained used counters remove full-history
scans from hot preparation while startup still performs complete integrity
reconciliation; legacy writer mutations cannot exceed configured capacity.
Queued reducer preparation is rechecked after commit and stale account/book/
management authority is durably aborted before a receipt can be used. The
focused 258-test set and complete 950-test suite pass (one existing privilege
skip). MEASURED on valid retained histories: worst near/small CPU growth is
1.429x at 30 markets (0.798x at 120), reducer p99 12.983 ms, loop-lag p99 8.209
ms, peak backlog 1. See
[correction evidence](docs/BUILD_COMMAND_CAPACITY_REVIEW_FIXES.md). This supersedes
section 88's pre-fix state, not the remaining production-readiness blockers.

## 88. D-060 review finds dispatch, recovery and resource gaps — 2026-09-21

VERIFIED OFFLINE: relabelling a stale/restarted receipt authorizes its old
PREPARED row; a proof callback changes dispatched size/price without changing
the journal; reducer preparation accepts caller-selected wrong routing with a
working entry; proven-unsent cancels/IOCs wedge recovery; a post-SENDING proof
exception leaves no executor failure hold. The
[independent review](docs/REVIEW_D060_ASTRA.md) owns R1-R6 reproductions and fixes
required for acceptance. MEASURED: replacing incomplete benchmark history with
complete terminal lifecycle evidence gives 10.429–14x CPU versus small history,
failing <2x. Existing 244 focused tests still pass (16.486 seconds). Disabled
preflight remains side-effect-free; full 936-test suite was not rerun here.
Section 87's broad identity, resource and closure claims are superseded by this
review. No source/config/runtime/account changes; next phase is Sol corrections.

## 87. Reserved command capacity and atomic receipts remove both reproduced blockers — 2026-09-21

VERIFIED OFFLINE under D-060: a funded owned-order cancellation prepares with
4,096 retained mutation rows, and a held cancellation converts to a used row at
the exact 8,192 hard bound without increasing `used + held`. A new entry is
denied at the ordinary high-water mark without poisoning the writer. Entry risk,
capacity, intent and PREPARED evidence now commit once; the executor consumes the
returned post-commit receipt without a second reservation. Original tests deny
unchanged cross-ledger/epoch/stale receipts and selected tampering; section 88
reproduces bypasses outside that coverage.

The complete native suite ran 936 tests: 935 passed and one existing symlink-
privilege test skipped. Four 30/120-market lifecycle measurements met latency,
loop, memory, backlog/thread and near-capacity CPU targets on the original
incomplete fixture; this acceptance claim is superseded by section 88. See
[build evidence](docs/BUILD_COMMAND_CAPACITY_HANDOFF.md). Overall-review items
1/2 remain open after independent review. This evidence does not prove account
continuity, live mutation transport, complete exits, archive rollover or live
readiness.

## 86. Safety headroom must cover adjacent evidence and post-commit identity — 2026-09-21

VERIFIED SOURCE at `8c03aa0`: intents, order evidence and account/basis readers
also have 4,096-row bounds; exempting only cancellation preparation would leave
reducer/evidence capacity failures. The writer increments revision after entry
reservation, so a coherent dispatch receipt must identify the committed result,
not reuse the caller's earlier portfolio revision. D-059's
[design](docs/DESIGN_COMMAND_CAPACITY_HANDOFF.md) specifies bounded durable credits,
atomic preparation and nonfatal expected denials. These are proposals, not fixes
or measured resource results. No source/runtime or historical ledger changed.

## 85. Overall triage identifies order-lifecycle integration blockers — 2026-09-21

VERIFIED OFFLINE at `8c03aa0`: an in-memory journal with 4,096 mutation rows
refuses a safety cancellation for an owned resting order. A successful atomic
fixture entry reservation followed by `InjectedExecutor` preparation attempts
to reserve the same identity again: writer faults, zero gateway calls. The
second case is an incompatibility between presently separate components, not
an already connected live trading defect. See the
[review and ordered actions](docs/REVIEW_OVERALL_2026-09-21.md).
Fresh targeted verification passes 267 tests; both extra probes reproduce and
disabled preflight has no file/credential/network side effects. Account
continuity/opening cash, production writes/exits, rank-to-allocation and S2B
remain unfinished. No fixes, live use or independent D-057 clearance claimed.

## 84. S2A review corrections have native regression evidence — 2026-09-21

VERIFIED OFFLINE under D-057: targeted barriers now retain process/lease ownership
through repeated cancellation and pending spawn/bind/IPC/control closure. Clock
denial cannot launch, uncertain creation keeps its reservation, terminal controls
have completed-write receipts, and parent/child identity/power and file-security
checks refuse invalid authority. Diagnostics and native/session journals remain
bounded. See [implementation evidence](docs/BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md).

The final complete suite ran 915 tests: 914 passed, one native symlink-privilege
skip (114.296 seconds). Three process-local safeguard reversals were detected.
This is implementation evidence, not an independent re-review or production
readiness claim. Native symlink creation and actual sleep/reboot remain unverified;
resource scope must not be inflated to a 30/120-market runtime comparison.
MEASURED: 100 cycles pass result/exit/lease and bounded-log/journal assertions,
with warmed handle delta -2 and no retained supervisor/diagnostic threads. A
correctly timed 60-second idle sample still misses the parent CPU target:
2.135% versus <1%; loop p99 16.475 ms and 39,014,400 working-set bytes pass their
inert-fixture targets. Cold-baseline +13 handles remain unattributed. Resource
acceptance is therefore **not cleared**; the evidence record preserves both runs.
No live process, account, credential, configuration or Polymarket reference use.

## 83. Native S2A failure paths do not yet satisfy the design — 2026-09-21

VERIFIED OFFLINE at `6992fed`: [Astra review](docs/REVIEW_D056_ASTRA.md)
reproduces a spawn call after durable clock-denial with no child reservation;
host completion while an inert child remains alive after repeated cancellation
or wrong-identity STATUS; cold-parent completion while the old lease remains;
discarded queued RESULT; child acceptance of wrong/stale parent messages; a leaked
inherited duplicate on setup failure; and 300 retained session events at limit
256. Native inspection also finds an unprotected database DACL; source inspection
finds missing child/power invalidation and D-033 diagnostic integration.

All 81 existing focused tests pass, demonstrating missing failure-sequence
coverage rather than clearance. Section 82's broad correctness/resource conclusion
is qualified: its measurements are historical Sol results for one inert workload,
not proof of complete ownership/security or all D-055 acceptance cases. No long
benchmark/full-suite rerun or live access was needed in this review. R1-R8 define
the bounded Sol correction phase; S2B remains blocked.

## 82. S2A native ownership is implemented and meets resource targets — 2026-09-21

VERIFIED OFFLINE under D-056: one native parent and one fixed inert child now use
protected account-scoped role objects, an OS-thread-owned serialized control
mutex, explicit inherited child/stop/parent handles, a schema-4 transactional
reservation and strict bounded local pipe frames. Parent death makes the child
exit through its retained parent handle; a cold parent never adopts by PID and
clears only a lease-proven orphan while remaining in attention. Crash attempts
remain durable, hung shutdown never starts a replacement, permissive named-object
squatting is rejected, and no operational path force-kills a child.

MEASURED on native Windows with the fixed inert fixture: 60.002 seconds idle and
100 exact child cycles produced parent CPU 0.990% of one core, child CPU 0.651%,
event-loop p99 16.372 ms, policy p99 7.491 ms, 34,140,160 added working-set bytes,
backlog 1, handle delta -2 and no retained supervisor thread. See
[D-056 evidence](docs/BUILD_WINDOWS_SUPERVISOR_S2A.md). This proves S2A software
correctness/resource bounds only. All 81 focused and 885 complete tests pass;
disabled preflight remains side-effect-free. S2B runtime/fence transfer, real suspend/reboot,
production launch and live readiness remain unimplemented/unverified; Astra review
is next.

## 81. S2 needs native ownership and cross-process restriction contracts — 2026-09-21

VERIFIED SOURCE at `ebb9892`: current Windows lease is presence-based, not a
transaction mutex; the supervisor journal has no native parent/session model;
runtime teardown is retained, while quota cooldown/retry evidence is local to
its process. Official Windows/Python contracts were checked for mutex ownership,
handle inheritance, pipe access, overlapped cancellation and power callbacks.
The [D-055 S2 design](docs/DESIGN_WINDOWS_SUPERVISOR_S2.md) proposes explicit
interfaces and native acceptance tests. These are design requirements, not
measured implementation behavior. No source, runtime or configuration changed;
S2A/S2B implementation and any live operation remain unapproved.

## 80. D-048 retained connection finalization passes review — 2026-09-21

VERIFIED OFFLINE: independent review of `b27cb0c` against `ecf04c3`, unchanged
in current `ebb9892`, clears D-047 R1. All 868 full tests and 205 targeted tests
pass, plus nine repeated shutdown regressions. Two independent writer-command
failure probes retain the error through stop/repeated cancellation and preserve
an open durable gap after reopening. Both disconnect regressions detect the
parent defect. See [review evidence and limits](docs/REVIEW_D048_ASTRA.md).
This completes the D-048 gate, not venue continuity or live readiness. S2 still
needs separate assignment. Only review documents changed.

## 79. D-054 clears both supervisor clock findings — 2026-09-21

VERIFIED OFFLINE at `ebb9892`: independent Astra review clears D-053 R1/R2
with no new blocking findings in the diff. All 64 focused and 868 full tests
pass (78.100 seconds), plus 48 independent transactional fault sequences;
four regressions reproduce the parent defects. Preflight stays disabled.
See [review evidence and limits](docs/REVIEW_D054_ASTRA.md). Supervisor S1
review is complete, not native process/reboot or live-readiness proof. D-048
review and a separate operator assignment remain S2 gates. No source/runtime
changes or live action occurred.

## 78. D-053 clock findings are fixed offline — 2026-09-21

VERIFIED OFFLINE under D-054: independent local clock distrust now takes safety
precedence over stale child filtering, persists `ATTENTION_REQUIRED`, requests
stop for an owned child and still journals the ignored payload as stale. The
default clock path treats wall-minus-monotonic as tolerant continuity evidence,
retains the persisted identity across trusted samples and rejects forward,
backward or monotonic discontinuity. Sixty-four focused and exact 868 full tests
pass (76.297 seconds), with 10/10 focused repeats. Four new tests detect the
parent commit's defects when its policy/store are loaded in memory. The 60.006-
second persisted-work fixture recorded 124 events at 0.4427% of one core. See
[D-054 evidence](docs/BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md). This is Sol
evidence pending Astra re-review; no runtime or live action occurred.

## 77. D-053 clock validation has two remaining gaps — 2026-09-21

VERIFIED OFFLINE at `b051067`: a stale child event detects an untrusted local
clock but returns before applying the hold; the journal replaces its checkpoint
and a subsequent tick/start is permitted, including after reopen. The same
sequence leaves an active child HEALTHY. Separately, the default quantized
wall-minus-monotonic boot ID changes across a bucket boundary under only 2 ms
of sampling skew, falsely requiring attention. See
[D-053 Astra review](docs/REVIEW_D053_ASTRA.md) for reproductions and acceptance.
D-052 R1/R2/R3/R5 are cleared in S1; R4 remains partly open. Fifty-nine focused
and 863 full tests pass (79.900 seconds), so these additional event/default-clock
cases are missing from coverage. This records the `b051067` review state;
D-054/section 78 implements both fixes and awaits Astra review.

## 76. D-052 supervisor follow-ups are fixed offline — 2026-09-21

VERIFIED OFFLINE under D-053: the five section 75 reproductions now pass.
Repeated STOP advances generation even while already stopping; startup/progress
expiry is checked against prior state before accepting status; failed-spawn
release commits while preserving the existing attention reason; SQLite stores
one transactional cross-instance clock checkpoint and holds on discontinuity;
and child events without complete identity are stale. The control schema is now
version 3 and deliberately refuses the undeployed S1 v2 database. Fifty-nine
focused and exact 863 full tests pass (79.164 seconds), with 10/10 focused repeats,
resource checks and disabled preflight. See
[D-053 evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md). This is Sol
evidence pending Astra re-review; no runtime or live action occurred.

## 75. Supervisor sequence and clock gaps remain after D-052 — 2026-09-21

VERIFIED OFFLINE at `7bf5241`: a second STOP does not fence an intervening
prepared ARM; late status can erase startup/progress expiry and refund attempts
after a 600-second observation gap; failed-spawn completion after startup
timeout raises and rolls back; a new store anchor accepts a forward wall jump
as elapsed cooldown; and identityless child results mutate childless state.
See [D-052 Astra re-review](docs/REVIEW_D052_ASTRA.md) for exact probes and
acceptance. All 46 focused and 850 full tests pass (79.093 seconds), but these
additional sequences are missing. Original D-051 R4/R6/R7 are cleared in S1.
This records the `7bf5241` review state and qualifies section 74's broader claims.
D-053/section 76 now implements the fixes; Astra re-review, S2 and D-048 remain
outstanding.

## 74. Supervisor review findings are fixed offline — 2026-09-21

VERIFIED OFFLINE under D-052: R1-R7 from the
[D-051 review](docs/REVIEW_D051_ASTRA.md) now have deterministic regressions and
corrected contracts. Stale child payloads cannot trigger current clock faults;
STOP and safety disarms fence prepared arms; late lifecycle events cannot release
or renew a confirmed child; work/startup deadlines remain bounded by fresh useful
progress; persisted holds block launch until explicit resolution; and confirmed
OS exit is distinct from cleanup evidence while unresolved recovery reasons stay
visible. The idle fixture performs real SQLite policy/journal work. Forty-six
focused and exact 850 full tests pass, focused tests pass 10/10 repeatedly, and
the 60-second fixture recorded 124 policy/journal events at 0.3385% of one core.
Disabled preflight stays false with no side effects. See
[fix evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md). This is Sol
implementation evidence, not Astra clearance; S2 remains blocked.

## 73. Supervisor S1 has untested control and recovery gaps — 2026-09-21

VERIFIED OFFLINE at `7b8d6cd`: delayed STOP skips generation fencing; stale child
timestamps stop the current child; out-of-phase spawn failure releases active
ownership; a silent child with a work deadline refunds its retry budget; holds
do not gate spawn and ARM deletes them; startup timing is inconsistent; real
unexpected death lacks the claimed recovery path without cleanup proof. The idle
CPU fixture runs no supervisor policy or journal work. See
[D-051 review](docs/REVIEW_D051_ASTRA.md) for reproductions and acceptance.
All 32 focused and 836 full tests pass, so section 72's general safety/resource
claims are qualified by these uncovered cases. Live authority remains false.
This section records the original `7b8d6cd` review evidence. D-052/section 74 now
implements the fixes; Astra re-review is next and S2 remains blocked.

## 72. Supervisor S1 is fail-closed and execution-disabled — 2026-09-21

VERIFIED OFFLINE under D-051: immutable policy and a separate transactional
SQLite control journal persist stop/generation state, reject stale children,
commit attempt reservations before spawn requests, bound restart budgets and
distinguish heartbeats from useful progress. Every state/decision keeps
`entry_allowed=false` and `live_ready=false`; no process, runtime, account,
credential or network path is connected. Thirty-two focused tests and all 836
tests pass. The 30/120-label policy benchmark stayed below 0.094 ms p99 and
169 KiB peak; the 60-second parent-idle fixture passed its one-percent CPU bound.
See [build evidence](docs/BUILD_WINDOWS_SUPERVISOR_S1.md). Independent Astra
review is next; D-048 and S2/runtime gates remain open.

## 71. Polymarket supervisor recovery has explicit limits — 2026-09-21

VERIFIED SOURCE / OFFLINE: clean Poly `c5029321` separates process restart from
host recovery, persists stop/generation/attempt state, and refuses some exits.
Its restartable exit 5 can also mean a startup transport failure; it is not
flat-account proof. Six isolated host-recovery tests pass in 0.056 s using fake
launches/temporary state. Bash/POSIX supervision was inspected, not run on WSL.
Kalshi's quota supervisor is not process supervision; current runtime liveness
does not prove readers recovered or entries are safe. D-050's
[Windows design](docs/DESIGN_WINDOWS_SUPERVISOR.md) records proposed adaptation
and limits. No runtime or Poly files changed; D-048 review is still outstanding.

## 70. Two-model routing has one canonical owner — 2026-09-21

VERIFIED DOCUMENTATION: D-049 records the operator's new model-selection rule.
`AI_OPERATOR.md` owns the detailed routing and exact recommendation format;
DECISIONS owns acceptance, while STATUS/NEXT/BUILT only summarize or route to
it. D-037 is marked superseded where its blanket flow differs. No bot logic,
configuration, data, process or runtime state changed.
Verification: `git diff --check` and the repository Markdown local-link audit pass.
Astra review found two stale D-037 citations in the active STATUS/NEXT handoffs;
both now cite D-049. Historical D-037 records remain unchanged.

## 69. Disconnect finalization survives stop/cancellation offline — 2026-09-21

VERIFIED OFFLINE under D-048: one retained connection finalizer now owns reader
join, bounded queue/byte drain, valid fill staging, marker close and gap refresh
through ordinary stop and repeated cancellation. The review's actual transport
case retains all 3/3 fills and leaves no queue bytes or tasks. Three regressions,
231 focused tests, all 804 tests, resource checks and disabled preflight pass.
Both disconnect regressions fail on the prior runtime. See
[build evidence](docs/BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md). This does not
prove venue continuity or authorize trading. No live use.

## 68. Stop can interrupt an already-active disconnect drain — 2026-09-21

VERIFIED OFFLINE at `ecf04c3`: retained runtime shutdown still cancels connection
finalization already running after a disconnect. Actual WebSocket consumer
probes left 1/3 valid fills buffered, an open epoch and cached/durable gaps 0/1;
ordinary stop returned success. Both stop and cancellation reproduced 3/3.
See [D-047 R1](docs/REVIEW_D047_ASTRA.md) for mechanism and acceptance. All 228
focused tests pass and the three new regressions fail against the old runtime,
so the exact earlier fixes are verified but section 67's ownership claim is
qualified by this overlap. No source/test edits or live use during review.

## 67. Repeated-cancel and drain-error ownership fixed offline — 2026-09-20

VERIFIED OFFLINE under D-047: one retained runtime shutdown owner survives
repeated caller cancellation, joins the account reader, preserves queued fills,
finalizes the epoch/gap and publishes false liveness before returning. Buffered
malformed or staging failures are recorded per item while later valid fills are
still staged; cleanup failure reaches the caller after reconciliation. Three
regressions pass, along with 199 focused and all 801 tests. Continuity/history
resource checks and disabled preflight pass. See
[build evidence](docs/BUILD_ACCOUNT_CONTINUITY_SHUTDOWN_FIXES.md). These local
results do not prove venue continuity or authorize trading. No live use.

## 66. D-046 shutdown still loses ownership on repeated cancel/drain error — 2026-09-20

VERIFIED OFFLINE at `1753a23`: a second cancellation during the in-flight wait
finishes the runtime task with its account reader still alive, one tail fill
queued and an open marker. A separate orderly-stop probe with malformed then
valid buffered fills returns successfully after the malformed input aborts the
drain, leaving the valid tail unstored. See
[D-046 R1/R2 reproduction and handoff](docs/REVIEW_D046_ASTRA.md). These qualify
section 65's broad shutdown claims. Original epoch-open/status/test/measurement
fixes check out; 196 focused tests, 10 retention repetitions, the corrected
benchmark and disabled preflight pass. No implementation changes or live use.

## 65. Reviewed continuity races are fixed offline — 2026-09-20

VERIFIED OFFLINE under D-046: controlled reader teardown retains queued fills,
gives in-flight delivery a bounded join and records interrupted spans invalid.
Runtime owns marker identity before awaiting its accepted open and reloads
durable gaps after an uncertain acknowledgement; reconnect cannot hide the old
marker. Quota transition now precedes status capture. New regressions reproduce
the reviewed boundaries and pass; 196 focused and all 798 tests pass. The quota
weak-reference test passes 10/10 after its legitimate callback turn. The newly
instrumented eight-epoch reconnect fixture passes at 30/120 markets with p99
3.141/3.062 ms, loop p99 0.970/0.886 ms and <1.5 MiB peak. See
[build evidence](docs/BUILD_ACCOUNT_CONTINUITY_REVIEW_FIXES.md). These results
remain local engineering evidence, not a venue continuity or live-readiness
claim. No account, credential, network, order or Polymarket action.

## 64. Continuity review exposes local delivery/gap races — 2026-09-20

VERIFIED OFFLINE at `07e8984`: stop can discard a queued fill yet persist a
clean marker (3/3 probes); a handshake timeout after durable epoch-open can
leave an orphan marker while cached gap count stays zero. Quota expiry can
also return stale continuity in one status response. See canonical
[R1-R5 review and reproduction evidence](docs/REVIEW_D045_ASTRA.md).
The prior quota weak-reference failure was traced to a queued task callback:
10/10 original failures, 10/10 process-local passes after callback drain; no
lasting production retention demonstrated. Review suites passed 192 focused
and 794 full tests, but did not cover these races. The continuity benchmark's
reconnect burst precedes its instrumentation, so only its assessment-loop
resource numbers are measured. These findings qualify section 63's earlier
verification claims. No source fixes, live account/credential use or trading.

## 63. Local continuity evidence is built, venue handoff remains unknown — 2026-09-20

VERIFIED OFFLINE: D-045 opens a durable local reader marker only after all four
private ACKs; a crash/open marker, failed reader/close or scope ambiguity remains
a gap across restart. A position update without subaccount is an invalidation,
not cost/quantity proof. Missing positions pagination cursor fails closed.
Candidate starting inventory is unapproved and source-revision-bound. All 168
directly affected tests and resource fixtures pass; one complete 792-test run
passed, but the final 794-test run failed an unrelated existing quota
weak-reference assertion reproduced in isolation. No real account event or
venue replay guarantee was tested. Two process-local guard reversals were detected. See
[build evidence](docs/BUILD_ACCOUNT_CONTINUITY_PHASE1.md) and the current
[official position stream](https://docs.kalshi.com/websockets/market-positions)
and [REST positions](https://docs.kalshi.com/api-reference/portfolio/get-positions).
No credential/account call, trading or Polymarket change.

## 62. Starting-account/private-stream continuity design — 2026-09-20

SOURCE/CODE REVIEW: the current official user-fill and user-order stream pages
do not document a shared REST/history replay checkpoint, and the live/archive
fill pages do not establish bounded publication delay. The market-position
stream example omits subaccount, while current `AccountCoordinator.on_event`
requires it. Current `RestReads.collect` does not require an explicit positions
cursor before accepting enumeration end. These are proof/handling gaps, not
evidence of missed account events. D-044 specifies evidence-only local epoch and
baseline-candidate assessment while keeping entry/live gates false. No venue
account read, credential use, implementation or test run was performed. See
[design and source links](docs/DESIGN_ACCOUNT_CONTINUITY.md).

## 61. Canonical GitHub now carries the Windows project — 2026-09-20

VERIFIED: the old default `master` tree contained 31 files; the initial published
replacement tree contained 170. Every staged file matched the active Windows
source byte for byte before commit. The prior `main` history was joined to
`master`, then the obsolete branch was deleted. The active folder now tracks
`origin/master`. Credential, capture, backup, log, environment and transfer
artifacts were excluded. [Publication record](docs/GITHUB_PUBLICATION.md).
No bot/account operation occurred.

## 60. Quota follow-ups cleared by independent review — 2026-09-20

VERIFIED: 62 focused quota tests pass; reverting each D-042 fix in memory makes
its regression fail without teardown errors. An additional injected probe
confirms the frozen boundary preserves pending timing and failure count while
retaining no exception and leaving the caller's original traceback intact.
Both D-041 P3 findings are cleared; no new findings in the reviewed scope.
No source/test edits or live account use. The 778-test full-suite and resource
results remain implementation evidence. [Review](docs/REVIEW_D042_ASTRA.md).

## 59. Review follow-ups fixed, pending independent re-review — 2026-09-20

D-042 stores only validated rollover boundary/provenance scalars and reports
`running=False` in an unconditional final path after repeated cancellation.
Injected regressions verify the deferred candidate is garbage collected and the
late-429 worker remains owned until drain. All 62 focused and 778 full-suite
tests pass; quota 30/120 and idle resource checks pass. This is offline evidence,
not live-readiness approval. See [implementation](docs/BUILD_QUOTA_REVIEW_FOLLOWUPS.md).

## 58. Quota fixes pass re-review with two small follow-ups — 2026-09-20

VERIFIED: the original three failure cases are fixed; current review's 60 focused
and 776 complete tests pass. A repeated-cancellation probe retains physical wire
ownership and applies a late 429, but leaves running=True after drain. A separate
probe shows pending rollover holds the caught exception and its raw quota pair
frames after garbage collection. These are P3 lifecycle/retention follow-ups;
neither restores read/trading authority. See [review](docs/REVIEW_D041_ASTRA.md).
No implementation or test edits, private account use or live actions in review.

## 57. Reviewed quota gaps are fixed in source pending re-review — 2026-09-20

D-041 adds a one-time grant-boundary deferral without extending the old hard
deadline; keeps actual wire ownership across cancelled close; and releases
explicit refresh waiters on terminal clock/service state. The full 776-test suite
and 60 focused quota tests pass. New rollover fixtures make six quota GETs for
bootstrap, deferral and boundary at both 30/120 market counts; idle remains
zero extra GETs. Two process-local guard reversals were detected. See
[build evidence](docs/BUILD_QUOTA_REVIEW_FIXES.md). This is offline code evidence,
not observed Kalshi entitlement or approval to trade. Astra re-review pending.

## 56. Grant-boundary deferral must not certify quota — 2026-09-20

D-040 design correction: a valid but non-installable near-expiry pair needs a
distinct scheduling result, not a successful lease or ordinary failure. Proposed
one-deferral bound preserves the original hard cutoff and real failure count;
post-boundary reads still require completely new validated evidence. Changed
read evidence revokes the old lease. Cancellation-safe drain and terminal waiter
contracts are specified alongside it. [Design and acceptance](docs/DESIGN_QUOTA_REVIEW_FIXES.md).
Current code and public limit/cost documentation were inspected; no new tests,
implementation or account observations. R1-R3 remain open. Exact policy awaits
the operator's implementation handoff; it is not a new live quota allowance.

## 55. Quota review exposes grant rollover and cancellation gaps — 2026-09-20

VERIFIED with injected clocks/transports: a valid unchanged finite grant exhausts
automatic refresh before expiry; cancelling shutdown during timeout drain loses
ownership of an actual worker and drops its late 429; clock fault during retry
cooldown leaves an explicit refresh waiting indefinitely. The first issue is an
inherited Astra design conflict, not an implementation deviation. Section 54's
ownership claim covers tested ordinary consumer cancellation, not cancelled close.
See [review evidence and acceptance](docs/REVIEW_D039_ASTRA.md).
46 focused tests pass, but this review's full 762-test run has one wire-entry
timeout; the affected 31-test module passes on rerun. Scheduling sensitivity is
suspected, not established. STATUS owns timings and the next handoff. No source
or test fixes, new design approval, account use or trading occurred in review.

## 54. Quota holds can preserve stream processing and retry ownership — 2026-09-20

VERIFIED in injected tests under D-039: expired or superseded quota evidence
blocks unsent REST work and cannot certify a late response. Pair timeout/caller
cancellation retains actual worker ownership until drain. Shared 429 pauses and
token spending remain intact. Healthy private-stream fills still enter the durable
inbox during an authentication/quota outage; quota restoration does not reset
independent recovery/metadata exhaustion or grant entry authority.
MEASURED: 30/120 explicit and automatic quota fixtures pass unchanged resource
budgets, with two coalesced bootstrap GETs, zero leftover tasks and explicit
admission refusal under saturation. Ten idle seconds cause ten health wakes and
zero extra GETs. 46 focused tests and two guard reversals pass; STATUS owns the
final full-suite result. [Details and limits](docs/BUILD_QUOTA_FRESHNESS.md).
No actual account quota, server token balance or live behavior is inferred.

## 53. Quota freshness needs source age and a bounded recovery path — 2026-09-20

VERIFIED in current `rest.py`: explicit refresh installs numeric settings but
does not retain grant expiry or an observation-age lease. Configuration age alone
cannot revoke an old entitlement. Cancellation leaves actual wire work owned by
RestReads, so a future timeout must also prevent late installation.

VERIFIED from the official limits/cost pages and local exact schemas: grants are
lane-scoped; account limits and endpoint costs are separate documents. UNKNOWN:
null expiry semantics (schema permits null; the guide defines absent expiry as
permanent), server snapshot/version consistency and any guaranteed validity TTL.
No current account quota was fetched. Proposed strict lease/probe handling,
sources, interfaces and phased acceptance are recorded in
[quota design](docs/DESIGN_QUOTA_FRESHNESS.md). Design only, no new test results.

## 52. D-036 review found four gaps outside the existing tests — 2026-09-20

Update after Astra review: Sol implemented R1-R4 with nine focused regressions;
both 30/120 resource fixtures pass. Independent Astra re-review cleared R1-R4
without new blocking findings in scope. All 87 focused tests and a combined
REST/service/scheduler reconnect probe passed. See
[re-review evidence](docs/REVIEW_D036_ASTRA_R2.md); STATUS records Sol's prior
716-test full-suite outcome. The original reproduction evidence follows.

VERIFIED with isolated injected probes: a valid milestone-review replacement
exceeds the lifetime dependency-key cap even after reconnect; background read
admission can reject a critical request while a reserved transport slot is free;
a new metadata generation waits on old work and charges its stale rejection to
the new retry budget; quota reconfiguration cannot interrupt the head token wait.
All four were open P2 findings, with precise reproduction and fix acceptance in
[Astra review](docs/REVIEW_D036_ASTRA.md). No source/test fixes applied in review.
At the original review, the 707-test suite passed in 54.564s, confirming missing
scenarios rather than existing failing regressions. Preflight remains false
(native exit 2). No account use, trading or Polymarket changes. Git metadata is
unavailable, limiting review to present source rather than a verified Git diff.

## 51. Quota capacity is not current tokens; metadata needs bounded refresh ownership — 2026-09-20

VERIFIED from current official rate/limits/cost documentation: account payloads
supply actual refill/capacity and separate Read/Write limits; endpoint overrides
must be charged. The guide's Basic capacity description differs from the earlier
dated account observation. Preserve both, configure from fresh documents, and
never infer available tokens or entitlement from tier name. No new account call.
Source links and exact implementation boundaries: [rate limits](docs/RATE_LIMITS.md).

D-036 adds an optional runtime-owned metadata coordinator, shared priority reads,
explicit atomic quota refresh and final/late-429 handling. Automatic quota-age /
grant-expiry enforcement and write-side transport remain unfinished. Fixture
bootstrap exposed a book-before-snapshot race, now guarded. MEASURED: 30/120-market
scheduling uses exactly 35/125 cold reads and zero extra warm reads; workers <=2.
30/120-request token fixtures spend exactly 300/1200 tokens and pass CPU, memory
and loop-lag budgets. 24 scheduler and 13 quota tests, plus two in-memory fault
reversals, verify the new components. No live capacity/profitability claim.
[Scheduler evidence and boundaries](docs/BUILD_METADATA_SCHEDULER.md).

## 50. Completed history reads need durable scope and omission checks — 2026-09-20

VERIFIED locally: staged fill evidence previously survived restart, but completed
read intervals/source provenance did not. An empty later response could leave
no newly missing keys and allow a locally repaired label despite retained unknown
fills. D-035 persists complete enumeration receipts and blocks that label on known
omissions, without reclassifying or deleting fills. Future requested time is never
credited. Current official pagination/private-fill docs still do not establish a
shared stream/REST watermark; full continuity remains UNKNOWN.
MEASURED: 128/4,096-row fixtures with 30/120 receipts and inspections pass bounded
resource checks; indexed batch validation reduces the larger finalization from
340.425ms to 215.938ms. All 670 tests (31 focused) and two guard reversals pass. No account
use or actual launch baseline. [Evidence and sources](docs/BUILD_HISTORY_COVERAGE.md).

## 49. Event timing needs reviewed bindings; fee rounding depends on membership — 2026-09-20

VERIFIED in current official API docs: lifecycle carries tick/close/state and
event-fee updates; event overrides supersede series fees. Milestone primary and
related events differ; expected expiry is not universal event start. Rounding
guidance distinguishes direct/non-direct precision and fractional-fill effects.
D-034 implements source-bound adapters with explicit review/profile gaps, not
guessed live facts. Pending/expired-baseline REST cannot erase stream observations.
MEASURED: shared 30/120-market fixtures used exactly 35/125 reads with no extra
reads for warm/stream-supported updates; both resource budgets pass. 41 focused
tests and two reversals verified. No account use or live execution.
[Exact source links, fee-bound derivation and scope](docs/BUILD_MARKET_INPUTS.md).

## 48. Diagnostic causes retained without raw exception text — 2026-09-20

VERIFIED: writer and REST sanitization previously discarded useful causes;
reader/recovery catches exposed state but no structured failure trace. D-033
records stable codes, typed safe stacks and bounded context before sanitization.
The standard rotating handler can suppress I/O failures, so the dedicated sink
overrides that behavior and latches failure. Secret, saturation and fault tests
exercise these paths; two in-memory safeguard reversals are detected.
MEASURED: 3,000/12,000-event diagnostics pass predeclared limits with zero drops
and producer p99 0.414/0.408ms. All 598 tests pass. No account access, third-party logger interception,
live execution or maximum-throughput claim. [Details](docs/LOGGING_AND_ERRORS.md).

## 47. Exact exit plans now preserve cancellation and fill proof — 2026-09-20

VERIFIED against current Poly source at `51cf59548b8e339be790e0662b6594ff0af77ddc`:
conditional one-tick improvement, 900-second evaluation, size-10 $8 ordinary
projected-loss threshold, depth haircut and bounded IOC confirmation/retry rules.
Kalshi adaptation keeps quantity exact and rejects IOC expiry; expected/latest
expiration is not a verified event-risk clock. The new planner remains advisory.
569 local tests and 104 reference tests pass. MEASURED 30/120-market diagnostics
pass their predeclared budgets. Production fee bounds, event-time provenance,
account completeness and live execution remain UNKNOWN/unimplemented, not proved
by fixtures. [Trace, measurements and boundaries](docs/BUILD_INVENTORY_EXITS.md).

## 46. Poly exposure follows configured reference, not occupancy — 2026-09-20

VERIFIED at current local Poly HEAD `51cf59548b8e339be790e0662b6594ff0af77ddc`:
source and launchers default to 20 slots; no local runtime override. Actual
diagnostic config at Kalshi size 10 yields $300 portfolio/$90 market exposure.
This is not running-process evidence. D-031 follows that calibration rather than
the proposed fixed $400. Actual Kalshi breadth stays limits-driven and the dollar
budget never grows with occupancy. Config/default/CLI now agree; 510 Kalshi tests,
104 reference tests and two fault reversals verified. No account use or trading.
[Trace and exact boundaries](docs/BUILD_POLY_EXPOSURE.md).

## 45. Private subscriptions and re-subscription accepted — 2026-09-20

VERIFIED on the actual account from 21:56:59 to 21:57:30 UTC: `user_orders`,
`fill`, `market_positions` and `order_group_updates` acknowledged on two
sequential connections, closing the first before opening the second. Aggregate
acknowledgment latency 263.521/256.770 ms; 15 seconds observation per session.
No actual account events arrived. This establishes access/re-subscription only,
not event economics, gap recovery, stream/history continuity or reward eligibility.
No concurrent four-socket bot, orders, cancellations or trading ledger was used.

D-030 accepts keeping prior fills separate while preserving reconciliation
evidence; not a reset, ownership waiver or installed launch boundary. Fixed $400
portfolio exposure remains a proposal awaiting the operator; configuration is
unchanged. 498 tests pass and two in-memory guard reversals are detected.
[Exact artifact, limits, evidence and unfinished scope](docs/BUILD_PRIVATE_STREAM_CHECK.md).

## 44. Matching ID accepted; bounded account inspection — 2026-09-20

VERIFIED: the new `kalshi-bot.txt` contains a valid UUID-form API-key ID.
Together with `Kalshi-Bot2.txt`, it authenticated a successful production
`GET /portfolio/balance`, followed by a bounded inspection from
2026-09-20 21:32:07.641695 to 21:32:15.862745 UTC (17:32 Eastern).
Credentials were read into memory, not printed, copied into documentation,
edited or installed into environment configuration. Both filenames already
have explicit `.gitignore` entries. Section 43's missing-ID blocker is superseded.

Observed using the existing GET-only signer/transport against
`https://external-api.kalshi.com/trade-api/v2`, with redirects/proxies disabled:

| Read | Scope / result |
|---|---|
| Balance | Primary account, all shards; `balance_dollars=500.4268`, legacy integer cents `balance=50042`, `portfolio_value=0`. Same monetary values before/after inspection; update timestamps differed. Actual cash is separate from the unchanged $500 strategy ceiling. |
| Resting orders | Explicit `subaccount=0`, `status=resting`; zero rows, one page, cursor exhausted. |
| Nonzero positions | Explicit `subaccount=0`, `count_filter=position`; zero rows, one page, cursor exhausted. Other subaccount positions were not inspected. |
| Recent fills | Explicit `subaccount=0`, no time filter; 18 rows, one page, cursor exhausted. Returned timestamps range from `2026-08-16T15:14:31.096698Z` to `2026-09-15T00:31:54.862931Z`. |
| Archived fills | Member-wide endpoint has no subaccount filter; zero rows, one page, cursor exhausted. |
| Historical cutoffs | All four supplied cutoff fields were `2026-07-22T00:00:00Z`, unchanged before/after enumeration. |
| API limits | Basic tier; read refill 200 tokens/s, capacity 600; write refill/capacity 100 tokens. Reading write limits did not test write permission. |
| Endpoint costs | Default 10 tokens; returned GET overrides parsed successfully. No runtime budget configuration changed. |

All 18 recent fills carried subaccount 0 and the canonical fields checked:
`fill_id`, `trade_id`, `ticker`, `market_ticker`, `book_side`,
`yes_price_dollars`, `count_fp`, `fee_cost`, `created_time`, `exchange_index`.
Field presence alone does not validate aliases, economics or recovery import.
No raw fills or account identifiers were persisted; no trading ledger was opened.

Enumeration limits: 10 pages / 1,000 rows / 4 MiB per endpoint, existing
30-second enumeration deadline and transport/retry bounds; conservative shared
one-request-per-second diagnostic throttle. No limit was reached. Live account
limits/costs were obtained, but this was not a production rate-budget exercise.
REST was used for one-time cash/bootstrap/history information not supplied as
a complete account snapshot by private update streams; no polling service or
WebSocket/trading process was started.

UNKNOWN: atomic account/private-stream continuity, lifetime history completeness,
other subaccount inventory, corrections/settlements, order ownership and a
human-approved starting baseline. Empty inventory and exhausted cursors do not
establish those guarantees. The final fill timestamp is not a bot stop time.
No profit/reward or trading-loss figure is inferred from the cash balance.
No write permissions tested, account mutations, ledger imports or live activation.
Next decision remains the starting-account/history coverage policy, not a key fix.

Contracts checked against the local API operation/schema snapshot and current
official [balance](https://docs.kalshi.com/api-reference/portfolio/get-balance),
[recent fills](https://docs.kalshi.com/api-reference/portfolio/get-fills) and
[historical fills](https://docs.kalshi.com/api-reference/historical/get-historical-fills)
documentation on September 20. Only documentation changed; no test suite rerun.
Prior 479-test result remains historical, not a new result. Git status/diff is
unavailable because this relocated directory has no `.git` metadata.

## 43. Supplied credential is a private key only — 2026-09-20

VERIFIED locally: `Kalshi-Bot2.txt` contains one parseable 2048-bit RSA private
key and no text outside the PEM block. No project `.env` or process/user/machine
`KALSHI_API_KEY_ID` configuration was present. Only booleans/type/size were
reported; secret contents stayed undisclosed and the file was unchanged.
Matching API-key ID is required before the read-only account check can proceed.
Venue acceptance and account state remain UNKNOWN; no network calls were made.

## 42. Windows relocation verified — 2026-09-20

VERIFIED: `C:/Users/rynna/Bots/kalshi` is now the active project, alongside
`liquidity-bot`. Tree SHA-256 matched for 3,453 transferred files, including
historical data; separate credential content also matched. The old OneDrive
project now contains only routing notices. Relocated virtual environments
required regeneration of activation/launcher and editable-install paths.
Pinned runtime versions retained; 479 tests pass from the new directory and
preflight remains blocked. Polymarket stayed clean. Credential presence is not
proof of key validity, API-key ID availability or account access; inspection pending.

## 41. Local account agreement is now explicit and atomic — 2026-09-20

VERIFIED locally: D-028 compares exact owned resting terms, foreign/absent
orders, all retained owned order fill totals, unbound intents, pending inbox,
position quantities and account/shard scope in one writer transaction. Matching
flat net inventory cannot hide opposite unaccounted fills. Subsequent local
mutations revoke reports. Recovery retains interval/source provenance without
claiming a documented venue watermark. 479 tests pass; two reversals detected.

MEASURED: batching capacity validation reduced the 120-market diagnostic from
16.4618s to 5.6195s wall, inspection p99 174.951ms to 71.887ms; unchanged workload
and safety limits. This is local engineering evidence only. Published fill/order
updates and balance timestamps do not establish complete cross-source proof;
starting basis, history continuity and production cash authority remain UNKNOWN.
[Primary links, trace, exact conditions and blockers](docs/BUILD_ACCOUNT_VERIFICATION.md).

## 40. Shared exposure and advisory inventory integration — 2026-09-20

VERIFIED from current Poly executable source: inventory basis risk, working
orders (including reducers) and unbound PLACE intents share the portfolio sum;
row-backed intents are not added twice. Exact passive reducers require confirmed
removal of incompatible orders. Poly's conditional one-tick improvement is a
distinct unfinished Kalshi pricing step, not implicit in touch-only plans.
D-027 adds single-writer projections/offline reservations and event-driven
advisory management, never live authority. 450 tests pass; two reversals detected.
MEASURED on disposable 30/120-market fixtures: market-read p99 .937/1.001ms,
global projection p99 6.238/23.952ms, loop-lag p99 4.950/15.836ms. Not a live SLA,
fill-probability estimate or reward forecast. [Evidence/boundaries](docs/BUILD_INVENTORY_RISK.md).

## 39. Recovery connected without blocking book/deadline processing — 2026-09-20

VERIFIED locally: D-026 durable pending fills survive disconnect/restart;
WebSocket order evidence can complete their ownership without REST. Missing
terminal-order updates require positive GET/archive evidence, not an absence
inference. Account evidence is revoked at ingress before disk/queue waits.
One coalesced recovery worker and independent connection retries remain bounded.
410 tests pass, including 39 new tests; two temporary safety reversals detected
and restored. Entry authorization remains false even after successful repairs.

MEASURED: 128/1024 injected fills, 30/120 synthetic markets; wall .5940/4.4918s,
durable processing p99 5.834/6.496ms, loop-lag p99 3.747/3.372ms. All 8/64
scheduled deadlines ran. This is not network latency, production load acceptance
or profitability evidence. [Conditions and gaps](docs/BUILD_RECOVERY_ENGINE.md).
No real keys/account requests/orders, historical migration or Poly edits.

## 38. Poly-style recovery is positive evidence, not full account proof — 2026-09-20

VERIFIED: the reference automatically applies backfilled executions, rejects
immutable conflicts, and has executable venue-cost basis fallback despite older
strict-basis comments. Kalshi D-025 now adopts those concepts with explicit
order ownership/scope, separate cost observations and no fabricated correction
signal. Matching quantities or cursor exhaustion still cannot authorize entries.

371 local tests pass, including 36 new tests. Two intentional safety reversals
were detected and restored. MEASURED: 128/1024 fills across 30/120 synthetic
markets complete in .2208/1.6215 seconds; replay-batch p99 41.714/46.784ms;
loop-lag p99 14.976/15.626ms. Initial larger run exceeded the five-second token;
transactional incremental sums and unique-lot counting fixed the measured work.
[Evidence, exact budgets and remaining gaps](docs/BUILD_AUTO_RECOVERY.md).
No keys, account calls, live changes, data migration/deletion or Poly edits.

## 37. Archived terminal orders no longer fall outside recovery — 2026-09-20

VERIFIED: current official archive contract supplies canceled/executed orders
missing from recent order routes. It has no documented subaccount filter, so
recovery requires explicit row scope. Cursor exhaustion and stable cutoff do not
prove atomic account state. Exact durable intent terms establish bot ownership;
terminal status without accounted fills still holds the reservation.

335 local tests pass; intentional removal of the 404-only fallback guard and
terminal-fill agreement each caused a regression failure; both restored.
Also fixed history staging's previously unchecked execution-time conflicts and
cleared stale auxiliary reports when starting a new reconciliation.

MEASURED: 128/4096 synthetic owned terminal orders; .0728/1.8863 seconds wall;
loop-lag p99 7.760/13.216ms; batch-ack p99 14.613/18.977ms. Local diagnostic
budgets passed, not network/recovery-completeness/live scalability acceptance.
[Source links, conditions and pending decisions](docs/BUILD_ARCHIVE_RECOVERY.md).
No real account reads/writes, credentials, data deletion or Poly changes.

## 36. Approved partial-close accounting implemented — 2026-09-20

VERIFIED locally under D-024: weighted-average basis, immediate observed fees,
partial-match gross realization, receipt-window late-fill attribution and
restart-persistent risk caps/holds. 306 tests pass. Seeded comparison against
actual Poly `MatchedInventory.apply` over 10,000 fills/30 synthetic markets:
exact positions and max per-fill numerical difference 3.8830065389158e-27 dollars
(Kalshi precision 40 versus reference default 28; tolerance 1e-24).
This verifies arithmetic for identical application order, not historical replay
or live-runtime equivalence. Schema 1 is refused, not automatically converted.

MEASURED: existing sparse WAL/FULL writer fixture, 240/960 fills; durable-ack p99
4.656/10.172ms. The larger run is slower than the earlier milestone; window sums
still scan indexed journal rows on the worker, now including opening fees.
Do not claim long-history scalability or live acceptance. [Full report](docs/BUILD_ACCOUNTING.md).
No real keys, account calls, orders, historical deletion or Poly edits occurred.

## 35. Poly accounting is not FIFO/prorated fees or execution-time risk — 2026-09-20

VERIFIED from executable call paths and 216 passing reference tests: Poly realizes
matched partial quantities immediately, uses weighted-average basis and incurs
all observed fill fees immediately. Its six-hour stop meter uses durable receipt
time; historical reports may use venue execution time. The earlier proposed
execution-time late-fill allocation was not a verified Poly copy. Kalshi candidate
accounting remains unchanged pending approval, especially unmatched entry fees.

Selection filters precede projected-reward ranking and restrained per-slot top-up;
restart does not clear ownership or loss holds. Passive reducer pricing also has
a conditional one-tick improvement, while existing exact touch orders are kept.
[Source locations, detailed limits and verification](docs/POLYMARKET_POLICY_CODE_AUDIT.md).
D-023 accepts limits-driven capacity, not any invented fixed slot/exposure value.

## 34. Quote/ranking and event/command components — 2026-09-20

VERIFIED locally: 280 tests pass, including 68 new checks. Current official
scoring and V2 create/cancel contracts rechecked. Snapshot math preserves whole
cutoff levels, own-order replacement and separate sides. Rankings never claim
net profit or automatic permission to trade. The V2 acknowledgement journal
does not fabricate terminal state, executions or fee accounting.

MEASURED: bounded 30/120-market injected workloads passed diagnostic budgets
after fixing long synchronous batches and redundant validation. Final 120-market
p99 loop lag: 15.102ms; event-to-rank: 481.628ms. Limited ranking headroom means
no live scaling claim. [Full scope, results and unfinished work](docs/BUILD_ENGINE_RANKING.md).
No keys, venue sessions/orders, paper run, historical deletion or Poly edits.

## 33. Owned orders and bounded recovery evidence — 2026-09-20

VERIFIED locally: 212 tests pass; 53 new recovery/order checks establish exact
intent ownership, stale/terminal-state protection, terminal-fill accounting
agreement, history boundary/scope checks and bounded evidence staging. Removing
terminal-fill and required-cursor guards caused focused tests to fail; restored.
The passive reducer path was rechecked against executable Polymarket code,
including the no-touch branch; the reference checkout is unchanged.

MEASURED: short 30/120-market injected account-event workloads and 1,000/4,000-row
history staging. Exact numbers and exclusions are in the
[recovery/order report](docs/BUILD_RECOVERY_ORDERS.md). No live performance or
profitability claim follows. Staged missing fills do not alter P&L; replay needs
the operator's accounting decision. No real keys, account calls or writes used.

## 32. Durable account-I/O milestone verified — 2026-09-20

VERIFIED locally: 159 tests pass (49 new integration/fault tests), including
atomic fill+risk rollback, restart-persistent intermediate loss tiers, bounded
writer/REST failure behavior and rejection of REST snapshots overtaken by account
events. Reversing the transaction and generation guards caused expected failures.
MEASURED: sparse local WAL/FULL writer fixture, 30/120 synthetic tickers; exact
workloads, latency percentiles and limitations in [the milestone report](docs/BUILD_ACCOUNT_IO.md).
This is software correctness/performance evidence, not profitability or live readiness.

Current-position agreement and cursor exhaustion do not establish execution-history
completeness or private-stream continuity. The new reconciliation report keeps
those blockers and cannot enable trading. No policy decisions, real key access,
venue account calls, historical data deletion or Polymarket changes occurred.

## 31. First Windows foundation verified — 2026-09-19

Implemented D-021's initial component milestone. 110 tests passed on native
Python 3.14.7, including the 45 existing research regressions. Deliberate removal
of persisted-cap and sequence-gap guards caused their focused tests to fail;
restored before final verification. No user credentials or venue calls used.
A sparse offline book/scheduler fixture measured about 23k updates/sec for
30 and 120 synthetic markets; excludes network/storage/strategy and is not
live-capacity proof. Exact scope and remaining integration:
[build report](docs/BUILD_FOUNDATION.md). No paper-trading or production start.

## 30. Direct inventory code audit and native Windows verification — 2026-09-19

Traced CLI configuration -> computed exposure -> reconciler admission and
portfolio reservations, plus positioned-market cancellation/reduction and exit
branches. Corrected section 29's shorthand: $420 is conditional on 32 slots;
the code counts reducer exposure as well as building orders. All 104 tests
in test_commissioning.py/test_reconciler.py passed on Windows after supplying
the source import path. No live runtime state or full-suite result is claimed.
Details: [code audit](docs/POLYMARKET_INVENTORY_CODE_AUDIT.md).
D-019 makes future Kalshi work Windows-native; this update was not mirrored
to WSL, and no old data or processes were touched.

## 29. Polymarket inventory reference verified — 2026-09-19

Read-only code/policy review at unchanged clean reference HEAD
`54ac71a241d1ad6f02e3445655bb7115247bac02` verifies $90 market/$420
portfolio exposure in its documented size-10/32-slot setup, exact reducing
management after fills, a 900-second exit evaluation, and a five-minute
pre-kickoff override. `reconciler.py` can defer ordinary IOC for depth or
projected loss beyond its configured early-exit allowance ($8 at size 10);
15 minutes is not guaranteed liquidation. D-018 records the user's instruction
to follow these inventory rules, with Kalshi-specific contracts still to map.
This is code/document evidence, not a live process/account check.

## 28. Multi-WebSocket design review — 2026-09-19

Read-only Polymarket history/code review at unchanged clean
`54ac71a241d1ad6f02e3445655bb7115247bac02` found documented shared-recovery
fanout, private-state proof gaps, read backpressure, self-chasing reducers,
cash-timing P&L errors and host-outage resting-order exposure. These are
historical records, not current live observations. Relevant Kalshi stream
pages were rechecked publicly; no numeric simultaneous-connection allowance
was established. Sources, limits and the proposed four-socket/one-engine
response are in [the design review](docs/MULTI_WEBSOCKET_DESIGN.md).
D-016 records the operator's accepted size/count/window parameters separately.
No credentials, runtime changes, trading or performance measurements occurred.

## 27. Polymarket documentation pattern inspected — 2026-09-19

**VERIFIED read-only:** the working reference is
`C:/Users/rynna/Bots/liquidity-bot`, clean HEAD
`54ac71a241d1ad6f02e3445655bb7115247bac02`. Its AGENTS/CLAUDE files route to
one `AI_OPERATOR.md`; `AI_ENGINEERING.md` owns permanent rules, current state
and decisions are separate, and dated history is routed by indexes. It also
has a documentation audit for routes, line budgets and links. The old OneDrive
folder lacked those root documents. No live runtime claim follows from this.

Kalshi adopted the core routing pattern under D-014. WebSocket-first data,
REST for unavailable information, and CPU-efficient scalable design are now
standing operator requirements. Polymarket's REST account mode, risk settings,
capacity and numeric API budgets are not Kalshi defaults. No source, account,
runtime or strategy mutation occurred. See `docs/DOCUMENTATION_STRUCTURE.md`.

**Current source note (2026-09-19):** use section 26 and
`docs/LIQUIDITY_REWARD_RESEARCH.md` for current liquidity rules and API evidence.
Older eligibility, best-bid reference, post-only, reward-unit and mandatory
paper-stage statements below are historical, not current authority.

## 26. Current liquidity research and public reward API audit — 2026-09-19

**VERIFIED:** official help explicitly applies the $1 minimum per individual
program. The July clean filing defines the reference at one fifth of target,
includes the entire cutoff price level, and scales for excluded snapshots.
Full price weight is not full pool ownership. Current help and clean filing
eligibility wording differ; the old blanket MM-agreement exclusion must not be
reused as established current general-LIP policy.

**MEASURED:** at 22:52 UTC, the complete active listing had 5,251 liquidity
programs, one volume program and no margin programs. All LIP rows used discount
0.50. Of a purposive 40-book sample, 27 met both-side target depth. A static
new-entrant calculation cleared $1 remaining gross reward on one size-5 pair
and five size-9 pairs. Neither sample selection nor assumptions establish
profitability. A $13.97/day-normalized example had only $0.85 remaining reward.

**VERIFIED API SCOPE:** 191 REST operations, two WS specs and cached FIX docs
revealed only `GET /incentive_programs` as a dedicated reward endpoint. All
documented type/status filters, exact description and cursor pagination were
checked; 102 logged public GETs succeeded. No documented personal earnings or
reward-credit-history endpoint was found. Program `paid_out` is not a personal
payment receipt. 4,383 LIP rows had fractional-second boundaries, differing
from the filing's whole-second wording; exact edge treatment remains unknown.

**INFERRED:** Reference Price is the initial candidate rather than a fixed
best-bid offset, but selection must include the individual payout minimum,
remaining time, whole-level competition, costs and correlated inventory risk.
No additional paper run is required or proposed. No keys/account APIs/orders
were used; no strategy or exit policy was approved by this research.

Canonical details, primary citations and dated evidence:
[liquidity-reward research](docs/LIQUIDITY_REWARD_RESEARCH.md).

Research pinned 2026-08-16. Ported context: `D:\polybot\liquidity-bot` (Polymarket US)
is the reference implementation. Its `SAFETY_INVARIANTS.md` (63 invariants) is the
asset being carried over; its *calibrations* are Polymarket measurements and are NOT
valid here until re-measured.

Primary sources are the CFTC rules filing and the live public API. Help-center
paraphrases proved unreliable (see section 2) and are not authoritative.

---

## 1. The reward program exists, is self-serve, and is formula-identical

Kalshi's **Liquidity Incentive Program** (LIP). Authoritative text: KalshiEX LLC
amendment filed 2026-02-11 with the CFTC, `rules02112639183.pdf`.

Eligibility, verbatim:

> "Eligible Participants are all Kalshi members, except the following: (i) affiliates
> of Kalshi; (ii) members who have executed a Market Maker Agreement with Kalshi;
> (iii) Introducing Brokers, Futures Commission Merchants, and customers thereof when
> transacting via the IB or FCM."

**Kalshi Pro does not affect eligibility.** Pro (`pro.kalshi.com/workspace`) is a
trading terminal with a fee discount, not a Market Maker Agreement. Confirmed it is a
sign-in product page, not an MM designation. The MM Agreement route is the separate
*Designated Liquidity Provider* program (auction-based, requires executing an
agreement) and it **excludes** you from the LIP.

The scoring formula:

```
Score(bid)      = DiscountFactor ^ (ReferencePrice − Price(bid)) × Size(bid)
Normalized(bid) = Score(bid) / Σ Score(b) over qualifying bids on that side
SnapshotScore(user) = Σ normalized yes scores + Σ normalized no scores
TimePeriodScore(user) = Σ user snapshots / Σ all users' snapshots
Payout(user)    = TimePeriodScore × TimePeriodReward     (≥ $1.00 or unpaid)
```

This is `discountFactor ^ ticks * size` — **exactly what `rewards.py` already
implements**. The pure reward core ports with field renames.

Regulatory bounds: Time Period ≤ 31 days; Target Size ∈ (100, 20 000); Discount
Factor ≤ 1.00; Time Period Reward ∈ [$10, $1 000] **per calendar day** encompassed.
Payout below $1.00 is not paid at all.

Snapshots are taken **once per second, at a uniformly random instant within the
second**. Reward is a time integral over resting orders — so liquidity-bot's
invariant 51 (never scan while quoting) carries over unchanged.

---

## 2. Two-sided liquidity is MANDATORY — this is the biggest design change

The stated purpose of the 2026-02-11 amendment:

> "exclude Snapshots where there are no qualifying 'Yes' bids or no qualifying 'No'
> bids. This serves to limit liquidity rewards to two-sided markets."

And in the terms:

> "Snapshots will be excluded if there is not two-sided liquidity (i.e., resting
> orders sufficient to meet the Target Size on each side of the market) at the time
> of the Snapshot."

**Consequences:**

- Liquidity-bot **invariant 4** ("after the first fill, all risk-building orders for
  that market are cancelled") zeroes reward accrual on *both* sides here. It cannot
  port as written. This is the single largest policy rewrite.
- Liquidity-bot **invariant 8** (each side independently eligible) is false on Kalshi.
- A market whose opposite side is short of Target Size pays **nothing**, no matter how
  good your share on your own side. Measured: this is common (section 4).
- At 5 contracts you **cannot rescue a short side yourself** — Target Size is 1000 in
  99.2% of live programs. Both sides must already qualify without you.

### Correction: Reference Price is the best bid

An earlier help-center reading claimed Reference Price is "the first price level at
which cumulative resting size reaches one fifth of the Target Size." **That is wrong
and does not appear in the filing.** The rules text:

> "If the highest yes bid price exists and is less than the highest possible price, it
> is assigned to the Reference Yes Price."

Reference Price = the touch. The walk then descends, accumulating size, until
cumulative ≥ Target Size; those levels form the Qualifying Bids. If bids run out
first, **the whole side is cleared** (no qualifying bids at all).

Note "a yes ask is counted as a bid for no" — both sides are expressed as bids, which
matches the `orderbook_fp` API shape exactly.

---

## 3. The API is public and unauthenticated for discovery

```
GET https://api.elections.kalshi.com/trade-api/v2/incentive_programs
      ?status=active&type=liquidity&limit=200[&cursor=…]
GET https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook?depth=100
```

Both work with **no auth**. `external-api.kalshi.com` returns identical data.

Field mapping to the existing Polymarket adapters:

| liquidity-bot | Kalshi | note |
|---|---|---|
| `discountFactor` | `discount_factor_bps` | bps; 5000 = 0.50 |
| `targetSize` | `target_size_fp` | string decimal |
| pool | `period_reward` | integer, scale inferred — see below |
| `IncentivePeriod` start/end | `start_date` / `end_date` | RFC3339 |
| PAID | `paid_out` | bool; feeds `calibration.py` paid-only discipline |
| slug | `market_ticker` | |

Orderbook response is `{"orderbook_fp": {"yes_dollars": [[px,size],…],
"no_dollars": […]}}`, price ascending, both sides as bids.

**`depth=200` returns HTTP 400. `depth=100` is accepted.** Cap requests at 100.

### The `period_reward` scale — strongly corroborated 2026-08-17, not yet paid

`period_reward` is an integer with no documented unit. Inferred scale is
**1/10 000 dollar** (divide by 10 000), matching the fixed-point convention the
rest of the API already uses — `discount_factor_bps: 5000` is basis points,
which is the same 1e-4, and `target_size_fp` / prices arrive as 4-decimal
strings.

Originally inferred from three examples. Re-tested 2026-08-17 across **2,940
distinct programs** in `data/capture.db`, and the evidence is now much stronger
than a band argument.

**All 19 distinct values, divided by 10 000:**

```
15  20  25  50  80  100  110  120  125  135  140  142.8571
170  200  240  285  333.3333  500  1000
```

Three things make this decisive:

1. **The two non-round values are exactly `1000/7` and `1000/3`.** Repeating
   decimals of that form are what you get by splitting a round $1 000 budget
   into 7 or 3 equal periods. Under any other scale they are meaningless
   numbers; under this one they are arithmetic.
2. **The maximum is exactly `1000.0`** — the filing's cap, hit precisely.
3. **Zero of 31 610 market-days exceed $1 000/day**, spreading each pool
   pro-rata across the calendar days it covers. Median **$1.10/day**, p90
   $14.29, max $285.00.

The cents hypothesis is dead: it puts the median at $357/market/day and breaks
the cap constantly.

### Tested against 11 698 programs the venue says it PAID, 2026-08-18

The argument above runs over *active* programs. Once `record_books.py` began
polling terminal-state programs too (it had `status=active` hardcoded, see
`BUGFIXES.md`), the paid population jumped from **28 to 11 698** — and those
are programs Kalshi asserts it actually paid out on, which is a much sharper
test than an active-program band argument.

Every paid program must sit inside the filing's reward bound. Measured:

| scale | max $/calendar-day | paid programs breaching the $1 000 cap |
|---|---|---|
| **1e-4** | $345.00 | **0 of 11 698** |
| cents | $34 500 | **10 235 of 11 698** |
| whole dollars | $3 450 000 | all 11 698 |

**The cents hypothesis is refuted by the venue's own payout data**, not merely
made implausible. Under 1e-4 the median paid program is $20.00/calendar-day,
p10 $6.67, p90 $100.00, across 37 distinct `period_reward` values.

**One anomaly, recorded rather than explained away.** Under 1e-4, **1 218 of
11 698 paid programs fall BELOW the filing's $10/calendar-day floor** (minimum
$2.78). These are long multi-day programs with modest pools — e.g. $25 spread
over 9 calendar days. The most likely reading is that the $10–$1 000 bound
applies to the **Time Period Reward total**, not per calendar day, in which
case every paid program is comfortably inside it and the maximum total under
1e-4 is $100. That reading also happens to be what the filing's phrase
"per calendar day encompassed" was interpreted *away from* earlier in this
section. **Either reading refutes cents**, so the scale conclusion is
unaffected — but the floor discrepancy means our reading of the bound itself is
not settled, and section 9's cap arithmetic leans on it.

**What this is still not.** It remains inference from the venue's own
arithmetic and its own `paid_out` flag. **No payout amount is exposed
anywhere** — a paid program carries exactly the same eleven fields as an unpaid
one, with no earnings figure. So this cannot be reconciled against a number we
were actually paid.

**What this is not.** It is inference from the venue's own arithmetic, not a
confirmed payout — no program row carries an amount. It is now strong enough to size the business and to write economics
against, which it was not before. **A real payout still settles it**, and the
`revenue: 0` discrepancy in 6f is a standing reminder of what an unverified
money field costs.

**UNRECONCILED:** a recount on 2026-08-18 over 3 255 programs gave a median of
**$3.12/calendar-day**, not $1.10, and the paid-program population above gives
$20.00. The three differ by program set and by how days are counted (elapsed vs
distinct calendar dates). Nothing downstream uses the median — `sizing.py` reads
each program's own pool — but two measurements of one quantity disagreeing 3x
is recorded, not averaged.

**The number that matters: the median program pays a roughly $1-$3/day pool per
market**, and we earn a *share* of that, not the pool. Section 4's share
measurements are what turn this into revenue.

---

## 4. Live universe measurement, 2026-08-16

2 328 active liquidity programs. Distribution:

- **Target Size: 1000 contracts in 2 309 of 2 328 (99.2%)**. Also 300 (×17), 2500, 500.
- **Discount Factor: 5000 bps = 0.50 in 2 327 of 2 328**. One at 4000.
- Period rewards (raw): 150000 (×1105), 250000 (×520), 1000000 (×514), 500000 (×125).

Top series by program count: `KXFEDFUNDSYEAR`, `KXH200MS`, `KXNOMGDPGROWTH`,
`KXUSCPIYEAR`, `KXB200MS`, `KXH100MS`, `KXROLEATEVENTCOACHELLA`, `KXRTX5090MS`,
`KXYTVIEWSW`, `KXRAIN`, `KXTRUMPSAY`.

**No sports in the rewarded top series.** The Polymarket bot is sports-pregame only
(invariant 40, moneyline V2). That entire gate has no counterpart here — the rewarded
Kalshi universe is weather, rates/macro, GPU benchmarks, YouTube views, events. See
section 5 for what this breaks.

### DiscountFactor 0.50 collapses the denominator — this is the key economics

Because each tick away halves the score, the effective competition is only the top few
ticks, **not** the full 1000-contract Target Size. Measured shares for a resting order
at the touch:

| market | side | denom | 5 ct | 25 ct | 100 ct |
|---|---|---|---|---|---|
| KXSOFRD-26AUG17-T3.62 | no | 5.1 | **49.5%** | 83.1% | 95.2% |
| KXSOFRD-26AUG17-T3.62 | yes | 13.4 | **27.2%** | 65.1% | 88.2% |
| KXTEMPMIAH-…-T84.99 | yes | 15.5 | 24.4% | 61.7% | 86.6% |
| KXRAIN-26AUG17-DEN | yes | 71.8 | 6.5% | 25.8% | 58.2% |
| KXRAIN-26AUG17-DEN | no | 233.5 | 2.1% | 9.7% | 30.0% |
| KXH100MON-…-2.310 | yes | 261.5 | 1.9% | 8.7% | 27.7% |
| KXEOWEEK-26AUG22-0 | yes | 546.0 | 0.9% | 4.4% | 15.5% |
| KXAAAGASD-…-4.0550 | yes | 4703.8 | 0.1% | 0.5% | 2.1% |

Illustrative payout, KXRAIN-26AUG17-DEN ($100 program, both sides qualify):

```
SnapshotScore = 0.0651 (yes) + 0.0210 (no) = 0.0861
TimePeriodScore = 0.0861 / 2.0 = 4.31%      (max total across all users is 2.0)
Payout ≈ 4.31% × $100 = $4.31
```

**Caveat — these are instantaneous book snapshots, not earnings.** They assume the
book is unchanged, you are never filled, and no competitor reacts. A denominator of
5.1 is an extremely thin book, which is exactly where a fill is most likely and most
adverse. liquidity-bot FINDINGS §6h found the same thing on Polymarket: reward
concentrates in thin books. Same trap, same mitigation needed.

### Stepping one tick inside the touch DOUBLES the share

Measured 2026-08-16 across 8 series, 15 qualifying sides. Resting 5 contracts at the
touch versus one tick inside it:

| market | side | at touch | 1 tick in | gain |
|---|---|---|---|---|
| KXVOTEPRIMARY-…-12 | yes | 2.64% | 5.14% | 1.95× |
| KXSHELTERCPI-…-T430.7 | no | 2.87% | 5.59% | 1.94× |
| KXPOWERKWH-…-T20.4 | no | 0.62% | 1.23% | 1.99× |
| KXCPICOMBO-26AUG-0503 | no | 0.46% | 0.92% | 1.99× |
| KXATPRETIRE-27DJO-Y | yes | 82.93% | 90.67% | 1.09× |

**The gain is `1 / DiscountFactor` per tick**, and DF is 0.50 in 99.96% of live
programs — so one tick is worth exactly 2×.

Mechanism: the Reference Price *is* the best bid (section 2). Becoming the best bid
puts us at zero ticks with multiplier 1.0 *and simultaneously demotes every other
resting order one tick*, halving each of their contributions to the denominator. We
gain nothing and lose nothing on our own numerator; the entire effect is on everyone
else's. Formally, with our size `q` and competing score `Σ`:

```
share_at_touch  = q / (q + Σ)
share_one_in    = q / (q + DF·Σ)
gain            → 1/DF   when q << Σ
```

The KXATPRETIRE outlier confirms the model rather than contradicting it: at 82.93% we
already dominate the denominator, so `q << Σ` fails and the gain collapses toward 1.

**Cost:** one tick. At 5 contracts that is $0.05 of worse entry price, against a
doubling of reward share.

**Constraint:** we cannot step inside on both sides without eventually crossing.
`yes_bid + no_bid` must stay below 1.00, exactly the "never price through the opposite
touch" rule in liquidity-bot's `exit_quote_price` (`reconciler.py`, added 2026-08-16).
A post-only order that would match is rejected outright.

**UNVERIFIED:** this is a static-book calculation. Being the best bid raises fill
probability and invites others to step ahead. Whether the 2× survives contact with a
moving book and reacting competitors is a Phase 2 measurement, not a result.

### Two-sided failure is common

Of 8 sampled programs, **3 had one side entirely empty** — `KXDIESELD` (yes),
`KXYTVIEWSHIGH` (no), `KXTEMPMIAH` (no). Those pay zero regardless of the other
side's share. KXTEMPMIAH shows a 24.4% share on a side that earns nothing.

**The dominant selector filter is therefore: both sides reach Target Size without us.**
Cheap to check — one orderbook call per candidate — and it eliminates a large fraction
of the universe before any economics run.

---

## 5. What ports, what rewrites, what must be re-measured

### Ports close to unchanged
`execution_ledger.py` (durable intent, exact Decimal, ambiguous-create resolution),
`runtime_safety.py` (lease, session risk guard), `reconciler.py` planner *structure*,
`risk.py` framing, `shadow_*` measurement harness, `AsyncIntervalLimiter`, the
fail-closed adapter discipline, and most of the 63 invariants.

### Rewrites (venue surface)
`adapters.py` (Kalshi REST, RSA-PSS SHA-256 over `timestamp + METHOD + path`, path
excludes query params), `streams.py`, `models.py` (ticker/series/event taxonomy, not
slugs), `venue_state.py`, `live_orders.py`.

Kalshi's WebSocket is **read-only — all order management is REST**. This removes the
private-mutation-stream complexity that liquidity-bot invariants 17/18/20 exist to
manage. Simpler, but re-verify what replaces those guarantees.

### Invariants that DO NOT port as written
- **4** (cancel building orders after first fill) — kills both-side accrual. Rewrite.
- **8** (independent side eligibility) — false on Kalshi.
- **40** (sports moneyline V2 gate) — no rewarded sports universe.
- **55/56** (900s passive wait; pre-kickoff flatten) — these are keyed to a sports
  `game_start`. Weather/CPI/rates markets have `close_time` / `expiration_time` with
  different dynamics. The *principle* (never let a position ride to settlement) holds;
  the clock does not.
- **34** (maker rebate = 0) — **sign flips**. Kalshi charges maker fees.

### Must be re-measured, cannot port
`fill_hazard.py` calibration, the 900s wait, the 2-cent spread rule (Kalshi is
1-cent linear_cent tick), `max_inventory_age`, the 6-hour pregame window.

---

## 6. Fees run the wrong direction

Kalshi charges **maker** fees, where Polymarket did not. Taker is
`ceil(0.07 × P × (1−P) × 100)/100` per contract — max 1.75¢ at 50¢, smaller in the
tails. Maker is reported at ~25% of taker (~0.44¢ at 50¢).

**Kalshi Pro reduces fees** — this is the reason to use it, and it feeds directly into
the EV gate. `risk.py` needs a new negative term: every reward must clear the maker fee
before it is profit.

UNVERIFIED: exact Pro fee schedule. `kalshi.com/docs/kalshi-fee-schedule.pdf` returned
HTTP 429; retry and pin the real numbers before sizing anything.

---

## 6g. The pair trade is a second revenue source, independent of the reward

Measured over 22,030 usable book snapshots, 44 markets, 2026-08-17.

A YES and a NO contract on the same market always settle to exactly $1.00
between them. So a maker resting a bid on both sides and getting **both** filled
has bought a guaranteed dollar for `yes_bid + no_bid`:

```
pair edge = 1.00 - (yes_bid + no_bid) - fees
```

This is the classic market-making trade, and it matters more than it first looks:
it is a return that **does not depend on the unresolved `period_reward` scale**.

| measure | value |
|---|---|
| gross pair edge, median | **0.0100** per contract — exactly one tick |
| gross, p10 / p90 | 0.0100 / 0.0500 |
| net after fees, 5 contracts, median | **$0.0379** |
| net, p10 / p90 | $0.0078 / $0.2106 |
| net > 0 | **98.2%** of snapshots |
| one-sided (unusable) | 3,419 of 25,449 |
| crossed (edge < 0) | **0** |

Fees are charged at each leg's own touch price. An earlier version of this
number priced both legs at 0.50 -- the peak of the `0.07·P·(1−P)` curve -- and
reported net $0.0062, making the pair trade look like it barely cleared its own
fees. These markets are mostly tail-priced, so that overstated cost by about 6x.
**Price the fee at the actual price, never at a representative one.**

### This creates a direct policy conflict with the one-tick rule

Section "Stepping one tick inside the touch DOUBLES the share" says to quote one
tick inside. The pair edge says the opposite:

- **Median pair edge is exactly one tick.** Stepping inside on one side consumes
  the entire typical edge; on both sides it consumes twice the entire edge.
- **Only 29.3% of snapshots leave more than 2 cents**, so 71% of the time
  stepping inside both sides would cross the book and is not even available.

So the two levers are in tension, and **which one wins is decided by the
`period_reward` scale** — the number that is still unconfirmed. If reward
dominates, quote inside and pay the spread. If the pair edge dominates, sit at
the touch and take 1x reward.

This raises the priority of resolving the scale: it is no longer just an
accounting question, it selects the quoting policy.

### What this does not measure

Whether both sides actually fill. The edge is only captured on a completed pair;
one side filling alone is directional risk, which is the failure mode
liquidity-bot spent its whole architecture on. Fill rates come from trades, and
that analysis has not been done yet.

**Answered in 6h, and the answer changes the conclusion above.** The pair
completes **0.7% of the time** — 7 times in 1,064 windows, revised up from a
reported zero once the sample grew. Read 6h before acting on any number in this
section: the edge is real when it lands and is far too rare to be a revenue
line.

## 6h. The pair trade does not complete — and that resolves the 6g conflict

Measured 2026-08-17 with `scripts/markout.py` over 140 non-overlapping
one-hour windows across 44 markets, quoting 5 contracts per side. This is the
fill-rate half that 6g left open.

### The result

A quote resting on both sides completed **zero pairs**, under either policy:

| policy | pair completed | one side only | neither |
|---|---|---|---|
| join both touches | **0** (0.0%) | 14 (10.0%) | 126 (90.0%) |
| one tick inside both | **0** (0.0%) | 16 (11.4%) | 124 (88.6%) |

Not one completed pair in 140 market-hours. 6g's `$0.0379` median is correct
arithmetic on the observed spread, but it prices an event that did not occur
once in this sample.

> **CORRECTED 2026-08-17 — "zero" was a sample size, not a property.** With
> 1,064 windows instead of 140, the pair completes **7 times (0.7%)**, median
> $+0.0500 on 5 contracts, positive on all seven. It is still far too rare to
> be a revenue line and none of 6h's conclusions change, but *never completes*
> was wrong and is now *completes 0.7% of the time*.
>
> An intermediate reading of this — that zero was "a property of the politics
> slate, not of Kalshi" — was also wrong, and wrong in the more interesting
> way. The original 40-market slate produces pairs too (2 of the 7) once it
> has enough windows. The variable was never the slate. **A rate of 0.7%
> cannot be distinguished from zero in 140 observations, and calling it zero
> was reading a sampling limit as a fact about the venue.**

### Why — it is the tape, not the queue

The obvious explanation is queue position: the median depth resting at the
touch is 655 contracts on the bid and 473 on the offer, so 5 contracts joining
behind that need an enormous amount of one-way flow. That is real, but it is not
the binding constraint, because stepping one tick inside creates an empty price
level where we are first in line — and pair completion is still zero.

The actual ceiling is that both directions have to trade at all:

| in a one-hour window | share |
|---|---|
| no trades whatsoever | **64.3%** |
| one direction only | 27.1% |
| both directions traded | **8.6%** |

So pair completion is capped at 8.6% before price or queue is considered, and
the realised figure is 0% because those trades must also occur *at our prices*.
Over five-minute windows only 7.8% contain any trade at all, mean 0.20 trades
per window.

These are quiet books. That is not incidental — it is the same property that
makes them pay, since reward share is our score over the competing score, so low
competition is the whole edge. **The books that pay best are the books that
trade least.**

### This resolves the policy conflict in 6g

6g framed stepping one tick inside as a trade-off: it doubles reward share but
consumes the entire median pair edge, and the winner was said to be decided by
the `period_reward` scale.

**On this evidence there is no pair edge to protect.** The spread is not being
captured, so giving up a tick of it costs nothing realised. Stepping inside buys
the measured 1.987x reward share and, additionally, moves us from behind ~655
contracts to the front of an empty level.

The conflict was real as posed; the premise turned out not to hold. Resolving
`period_reward` is still required to size the reward, but it is **no longer
needed to choose the quoting policy** — which reverts blocker 1 from a policy
question to an accounting one.

The 3-tick room requirement bites as 6g predicted: only **21.4%** of snapshots
leave enough spread to step inside both sides, and the rest join the touch. So
this is a policy, not a filter.

### ~~UNRESOLVED~~ RESOLVED in 6i: the sign of one-sided markout

**Superseded 2026-08-17 by section 6i.** The sign is established: one-sided
fills are adverse, by a sign test over a pooled sample, and the mean is bounded
by a bootstrap interval that excludes zero. The instruction below not to put an
adverse-selection term into the economics **no longer applies** — 6i supplies
the number and section 9 now uses it. The reasoning is kept because the
*method* is the finding: waiting for n was the wrong instrument, and the right
one did not need a larger sample.

One-sided fills are what actually happens, 10–11% of hours. Their markout is
consistently negative but **the sample cannot establish the sign**:

| horizon | n | median | mean | trimmed mean | positive |
|---|---|---|---|---|---|
| 60s | 14 | −$0.0063 | −$0.1293 | −$0.0488 | 36% |
| 300s | 14 | −$0.0200 | −$0.1654 | −$0.0513 | 29% |
| 900s | 12 | −$0.0050 | −$0.1681 | −$0.0167 | 42% |

The mean is dominated by a single −$1.75 observation; dropping the best and
worst sample moves it to roughly −$0.02 to −$0.05, and the median sits near
zero throughout. That spread between median and mean is the signature of
adverse selection — most fills harmless, a few badly wrong — but with n=14 it
is equally consistent with noise. **Recorded as unresolved.** Do not put a
`spread_capture` or an adverse-selection term into any economics on this.
*(Both sentences superseded by 6i — see the note at the head of this
subsection.)*

liquidity-bot hardcodes both `spread_capture` and `maker_rebate` to zero for
exactly this reason and never got evidence to turn them on
(`docs/REFERENCE_CRITIQUE.md` 3b). On this measurement zero is the right value
for us too, and now it is a measurement rather than a placeholder.

### Limits of this measurement

- **44 markets, all politics/economics event markets**, selected by
  `reward/target` ranking. Not a general sample of Kalshi, and sports markets
  are absent entirely.
- **~14 hours of book coverage** across two capture runs with a 5.5-hour gap.
  Trades are backfilled 48h but a fill needs book context on both ends.
- **Static-book assumption**, and it bites hardest on the policy that looks
  best: nothing here models other makers stepping inside us after we step
  inside them.
- Fills require the **whole** 5 contracts; partials are not counted, on the
  grounds that a partial carries the same directional risk with less spread to
  show for it.
- Gross of fees throughout. The maker fee rate is still unmeasured (6e).

## 6i. One-sided fills ARE adverse — the sign is established, the mean is bounded

Measured 2026-08-17 with `scripts/pooled_markout.py` over both captures pooled:
1,064 non-overlapping one-hour windows, 292 markets, 1,219 market-hours. This
closes the blocker 6h left open and supplies the drag term section 9 was
missing.

### Waiting for n was the wrong instrument

6h said the sign needed a bigger sample and the plan was to widen the universe
from 40 markets to 150. **That made the sample grow more slowly, not faster.**
One-sided fills arrive at 0.040/market-hour on the original slate and
0.048/market-hour on the wide one at 5 contracts — but the wide slate's
*windows* are far quieter, 3.7% one-sided against 7.3%. Ranking by
`reward/target` selects for thin books by construction, so every market added
is quieter than the ones already held.

**This is a structural property, not bad luck.** The books that pay best are
the books that trade least (6h), so the sample that measures fill cost is
rate-limited by the same thing that makes the strategy work. Accumulating n is
not a viable path to this answer.

What settles it is choosing statistics that survive a small, outlier-heavy
sample:

- A **sign test** asks only whether fills are negative more often than a coin
  says. The −$1.75 observation that destroyed the mean in 6h counts exactly as
  much as a −$0.001 one.
- A **bootstrap CI on the mean**, because P&L is paid in dollars and not in
  signs. If the interval excludes zero, the drag is bounded and can enter the
  economics.

### The result, at 5 contracts per side

| horizon | n | median | mean | negative | sign test p | 95% CI on mean |
|---|---|---|---|---|---|---|
| 60s | 51 | −$0.0250 | −$0.1235 | 69% | **0.0038** | [−$0.2249, −$0.0403] |
| 300s | 51 | −$0.0250 | −$0.1271 | 71% | **0.0014** | [−$0.2374, −$0.0369] |
| 900s | 43 | −$0.0250 | −$0.0755 | 72% | **0.0054** | [−$0.1816, −$0.0028] |

The median is pinned at exactly −$0.0250 at every horizon — half a tick on 5
contracts. The CI excludes zero at all three. **One-sided fills are adverse and
the drag is roughly −$0.13 per fill at 5 contracts**, with the honest range
being −$0.04 to −$0.24.

### The independence caveat, and it matters

An earlier reading of this called the two captures "two independent slates that
agree exactly". **They are not independent.** `capture.db` and
`capture_wide.db` share **69 markets — 88% of the narrow slate and 32% of the
wide one** — and they overlap in time from 18:50Z onward, so some fills are
plausibly the same event sampled twice.

Run separately, the two do not carry the same weight:

| sample | n (300s) | median | mean | sign p | 95% CI on mean |
|---|---|---|---|---|---|
| `capture.db` alone | 27 | −$0.0250 | −$0.1424 | 0.0094 | [−$0.3017, −$0.0242] |
| `capture_wide.db` alone | 24 | −$0.0250 | −$0.1099 | **0.0931** | [−$0.2766, **+$0.0094**] |
| pooled | 51 | −$0.0250 | −$0.1271 | 0.0014 | [−$0.2374, −$0.0369] |

**The wide slate alone does not reach significance and its CI includes zero.**
The pooled p-values are therefore optimistic — the effective sample is smaller
than 51 by an unknown amount.

What survives the caveat is the part that does not depend on pooling: **both
slates give a median of exactly −$0.0250 and a negative mean of the same order,
derived from different market mixes.** The direction is consistent; the
strength of evidence is somewhere between the single-slate and pooled readings.
Recorded as *established but not airtight* — one more independent capture on a
disjoint market set would settle it properly.

### Drag scales with size; reward does not

Both fill rate and per-fill markout were re-measured at each size rather than
scaled from the 5-contract number:

| size | fills/market-hour | mean markout (300s) | 95% CI on mean |
|---|---|---|---|
| 5 | 0.0435 | −$0.1271 | [−$0.2374, −$0.0369] |
| 25 | 0.0385 | −$0.7536 | [−$1.3617, −$0.2594] |
| 100 | 0.0328 | −$3.4208 | [−$6.3403, −$1.0514] |

Per-fill markout grows very close to linearly in size, while section 9's reward
**saturates**. That asymmetry is the whole shape of the business.

### Net, and where it turns

`drag/day = 24h × fills/market-hour × mean markout × 10 quoted markets`, over
the 10 markets surviving `sizing.py`'s guards:

| size | reward/day | best (CI high) | central (mean) | worst (CI low) |
|---|---|---|---|---|
| 5 | $4.68 | $4.30 | **$3.35** | $2.20 |
| 25 | $23.89 | $21.49 | **$16.92** | $11.30 |
| 100 | $37.43 | $29.15 | **$10.50** | **−$12.48** |

**At 25 contracts the operation is positive across the entire interval** —
$11.30 to $21.49/day on $243 of collateral. **At 100 it straddles zero**, which
confirms the structural point from section 9 by measurement rather than by
argument: past the peak, size is a negative lever, because reward saturates
while fill losses do not.

### What these numbers still do not include

1. **Fees.** Gross throughout. The maker rate is still unmeasured (6e).
2. **The both-sides reward interruption.** Section 2's two-sided rule means
   pulling our quotes after a fill zeroes the snapshot on *both* sides, not
   just the filled one. That cost is in none of the above and is now the
   largest unmeasured term in the economics. See open question 3.
3. **Partial fills.** `markout.py` requires the whole order to fill, which is
   why the modelled fill rate *falls* with size (0.0435 → 0.0328). In reality a
   100-contract quote fills partially far more often than a 5-contract one
   fills completely, so **drag at large size is understated — worst exactly
   where the table already looks worst.**
4. **Static book**, and non-independent samples as above.

## 6b. Program renewal — an earlier expiry scare was wrong

The 2026-02-11 filing sunsets the Program on **2026-09-01**, and an earlier reading of
this file treated that as an imminent shutdown. **That was wrong.** The per-market end
dates cluster before September 1 because these are short-dated events (a weather market
for Aug 17 ends Aug 17), not because the program stops.

Evidence pointing to routine renewal:

- Kalshi **refiled its Volume Incentive Program on 2026-08-04, extending to September
  2027**, in response to CFTC Division of Market Oversight staff asking every DCM to
  review and amend incentive filings by 2026-09-14. The September dates are a review
  deadline, not a cliff.
- Kalshi is already scheduling liquidity programs **past** September 1 — 43 of 2,328,
  running to September 5.
- The Program has run continuously since August 2025 and was already extended once.

Not proven: the liquidity refiling itself was not located, only the volume one. Treat
renewal as likely, not certain. Do not plan around a deadline.

## 6c. Fees — confirmed, and where they actually bite

Kalshi help center, verbatim: *"Maker fees are charged for orders placed that are not
immediately matched and are instead left as resting orders on the orderbook."* Maker
fees are real. Fees are charged **only when a trade executes** — cancelling a resting
order is free.

`kalshi-fee-schedule.pdf` is Cloudflare-blocked (persistent 429 with an HTML body, not
a real rate limit), so the 25%-of-taker maker rate remains **UNVERIFIED**.

**The maker fee is not the problem.** Reward is earned by resting; fees are paid on
fills. At 5 contracts and 50¢, a fill costs ~$0.022 — about 0.5% of a $4.31 program
reward. Noise.

**The taker fee is the problem**, because Kalshi's tick is 1¢ and the taker fee at 50¢
is 1.75¢ — *larger than the entire spread*:

```
crossing the spread   1.00¢
taker fee             1.75¢
                      -----
true cost to cross    2.75¢     ≈ 3× the naive spread estimate
```

The hard-exit path is a taker path, so `cross_exit`, `max_exit_loss` and the stressed
margin all need a fee term. This compounds section 4's thin-book trap: the markets
paying the best share are the ones where crossing out is required and most expensive.

The fee is parabolic (`0.07·P·(1−P)`), maximal at 50¢ and near zero in the tails —
0.74¢ at 12¢ versus 1.75¢ at 50¢. **Tail-priced markets are fee-advantaged**, at the
cost of tail risk. That is a real selector input.

## 6e. Authenticated account facts, measured 2026-08-17

Signed read-only access working via `scripts/kalshi_auth.py`. RSA-PSS/SHA-256 over
`timestamp + METHOD + path`, where the signed path **includes** the `/trade-api/v2`
prefix and **excludes** the query string, and the timestamp is milliseconds as a
string. Salt length is the digest length. Both mistakes fail identically with
`token_authentication_failure`, which is why they are written down here.

Balance: **$22.6439**.

### The taker fee formula is CONFIRMED — and my earlier rounding was wrong

Two real taker fills on this account, `KXITFWMATCH-26AUG16DASNEP-DAS`:

| action | C | P | `0.07·C·P·(1−P)` | ceil 4dp | actual `fee_cost` |
|---|---|---|---|---|---|
| sell/no | 14.91 | 0.53 | 0.2599857 | 0.2600 | **0.260000** |
| buy/yes | 14.91 | 0.32 | 0.2271091 | 0.2272 | **0.227200** |

```
fee = ceil(0.07 × C × P × (1−P) × 10_000) / 10_000
```

**Ceiling is at four decimal places — one hundredth of a cent — not at whole cents.**
The second fill disambiguates: ceil-to-cents gives 0.23 and does not match; ceil-to-4dp
gives 0.2272 and matches exactly. An earlier note in this file said whole cents. It was
wrong, and it mattered in the pessimistic direction: small orders lose far less to
rounding than claimed.

The per-contract headline is unchanged: 1.75¢ at 50¢, and the crossing cost of ~2.75¢
against a 1¢ tick still stands.

**Maker fee remains UNVERIFIED.** Both fills carry `is_taker: true`. The `fee_cost`
field is reported per fill and `is_taker` distinguishes them, so **one resting fill
settles the maker rate definitively** — no reward payout needed for this particular
question.

### Rate limits are ~50× more generous than assumed

`GET /account/limits`, tier `basic`:

```
read   refill 200/s   bucket 600
write  refill 100/s   bucket 100
```

liquidity-bot's entire discovery architecture is shaped by a **4 requests/second**
governor — invariant 51 (never scan while quoting) exists because a full Polymarket
metadata pass took 31 minutes. At 200/s a 40-market book sweep costs well under a
second, so **1-second book resolution is achievable**, matching the rate at which
Kalshi itself samples. The scan-versus-quote tradeoff that shaped much of the reference
architecture largely does not exist here.

### Fractional contract sizes exist

`count_fp: "14.91"` on both fills, and `target_size_fp: "1000.00"`. Sizes are not
integers. Any size model, loss budget, or tick arithmetic that assumes whole contracts
is wrong. Unresolved: whether a resting order may be placed in fractional size or
whether this is an artifact of dollar-denominated entry.

### No incentive-earnings endpoint was found

`/portfolio/incentives`, `/incentive_earnings`, `/portfolio/incentive_earnings`, and
`/incentive_programs/earnings` all return 404. Reward payouts are not obviously exposed
as their own resource, so **the `period_reward` scale probably cannot be settled without
actually earning a payout** — unlike the maker fee, which one resting fill answers.

One counter-signal on scale: `/portfolio/balance` returns `balance: 2264` beside
`balance_dollars: "22.6439"`, so integer money elsewhere in this API is **cents**. If
`period_reward` were also cents, the observed `800000` would be $8,000 for a one-hour
program, far outside the filing's $10–$1,000 per-calendar-day band. Cents and the
regulatory cap cannot both hold, so the field is either scaled differently or the cap
is applied in a way not yet understood. **Do not treat 1e-4 as settled.**

## 6f. There is no short on Kalshi — selling YES is executed as buying NO

Decoded from a completed round trip on this account, `KXITFWMATCH-26AUG16DASNEP-DAS`,
2026-08-16.

```
15:14:31  action=buy   side=yes  yes_price=0.32  ->  yes_total_cost 14.91 x 0.32 = $4.7712
15:18:46  action=sell  side=yes  yes_price=0.53  ->  no_total_cost  14.91 x 0.47 = $7.0077
```

Selling YES at 0.53 did **not** book proceeds of `14.91 x 0.53 = $7.90`. It booked a
**cost** of `14.91 x 0.47 = $7.0077`, and the settlement carries *both*
`yes_count_fp: 14.91` and `no_count_fp: 14.91`. Going short YES is buying NO, and the
venue rewrites the order to say so.

### The same trade is described three ways

| record | fields |
|---|---|
| order | `side: yes`, `action: sell`, `outcome_side: no` |
| fill | `side: no`, `action: sell`, `outcome_side: no` |
| settlement | both `yes_count_fp` and `no_count_fp` populated |

**The order says `side: yes` while the fill says `side: no` for the same trade.**
Deriving direction from `action`/`side` books it backwards. This is the same defect
class as liquidity-bot FINDINGS section 2, where legs priced against the wrong outcome
made the ledger report +$1.34 on a trade that actually lost $0.30, in the direction
that hides losses.

### Kalshi gives us the fix Polymarket withheld

Every record carries **both** `yes_price_dollars` and `no_price_dollars`, always summing
to exactly 1.00. The price frame is therefore never unrecoverable, unlike Polymarket's
bare `lastPx` with no record of the outcome it was quoted against.

**Design rule: never derive direction from `action`/`side`. Reduce every order, fill and
position to a signed YES-equivalent from the explicit price pair, in exactly one
function, with round-trip tests.**

### UNRESOLVED: `revenue: 0` does not reconcile

The settlement reports `market_result: "yes"`, `value: 100`, and `revenue: 0`. Holding
14.91 YES into a YES resolution should pay $14.91. Either `revenue` excludes settled
pairs, or the paired position is netted somewhere not visible in this record.

Do not guess this one. `revenue` is the kind of field a P&L breaker reads, and
liquidity-bot's $40 stop returned **+3.26 for a trade that lost $1.55** because a
closing fill was never booked. Resolve it against a second settlement before any ledger
depends on it.

## 6d. liquidity-bot reference values, corrected 2026-08-16

The reference implementation changed after this file was first written. Current values
(liquidity-bot `3dca27c`), which supersede anything earlier in this document:

- **Invariant 13**: 5 contracts per quote across 20 markets (was 1 × 8).
- **Invariant 25**: **$40** loss stop, **$45** hard stop (was $30/$35).
- **Invariant 57 superseded**: the 8-market private-WebSocket ceiling was *disproved* —
  29 subscriptions were later sustained. Eight was one connection's cap, not the
  account's; connections are independent and each carries its own quota. **This removes
  the main reason to expect a low Kalshi subscription ceiling**, though Kalshi's own
  limits still must be measured.
- **New `selection_horizon_seconds = 7200`** (was six hours). Measured: the 120+ minute
  bucket pays a median projected reward of 0.000022 with only 67% of markets paying
  anything, against 0.000313 and 100% at 15–30 minutes. **Reward concentrates hard near
  the event.** Kalshi's analogue — whether reward concentrates near a program's
  `end_date` or near market close — is a Phase 2 measurement and a likely large win.
- **New `max_early_exit_loss = 4.0`**, split from `max_exit_loss`. The two shared one
  number, wired to the $40 session stop, so the exit half *could never fire*: five
  contracts cannot lose $40. Chosen from 17 observed crossed losses; $4.00 blocks 3 and
  defers $16.96 of $41.96 — 40% of the damage from 18% of events. **This is exactly the
  failure mode to avoid in the Kalshi port**: an entry gate and an exit cap that read
  the same field silently disable one of them.
- **New `exit_quote_price()`**: a reducing quote steps one tick inside the touch, but
  only while the improved price still does not lose money. Measured: exits ending in a
  taker cross were **-$30.22 across 28 markets, ~76% of all real recorded losses**, with
  losers clustering at 911s and 966s of hold — right on the 900s inventory clock. On
  Kalshi, where crossing costs ~3×, this is worth more, not less.

## 9. What it would actually pay — first end-to-end sizing, 2026-08-17

`scripts/sizing.py`. The first estimate where every term is measured rather than
assumed: pool from the corroborated 1e-4 scale (section 3), share replayed from
captured books with our order inserted, the two-sided rule applied per snapshot,
and reward as the *only* revenue line because 6h showed the pair trade never
completes.

### The payout chain, and the two things that are easy to get wrong

```
SnapshotScore   = normalized_yes + normalized_no
TimePeriodScore = sum of our snapshots / sum of ALL users' snapshots
Payout          = TimePeriodScore x period_reward,  unpaid below $1.00
```

1. Normalized shares on a side sum to 1.00 across all participants, so **every
   counting snapshot contributes exactly 2.0 to the denominator** — one per
   side. Our fraction of the pool is therefore the **mean of our two side
   shares**, and quoting one side only halves it.
2. A snapshot excluded for one-sidedness pays nobody, so it leaves the
   numerator *and* the denominator. **The 85% two-sided rate does not dilute
   our share** — it only spreads the pool over fewer snapshots. An earlier
   intuition that it scaled revenue by 0.85 was wrong.

### The result, and it saturates

Ten markets survive the guards below. Quoting both sides at the touch:

| size | collateral | $/day | per $/day | median share | clears $1 |
|---|---|---|---|---|---|
| 1 | $9.72 | **$0.18** | 1.8% | 0.13% | **1 of 10** |
| 5 | $48.59 | $4.68 | 9.6% | 0.65% | 7 of 10 |
| 25 | $242.93 | $23.89 | **9.8%** | 3.15% | 10 of 10 |
| 100 | $684.70 | $37.43 | 5.5% | 5.14% | 7 of 7 |
| 500 | $1,489.00 | $48.43 | 3.3% | 20.35% | 3 of 3 |

**Return per dollar peaks around 5–25 contracts and decays after.** Our score
and the denominator both rise with size, so share is sublinear, while the pool
is fixed and capped at $1,000/day per market. Above 100 contracts most markets
fail the crowding guard entirely — at 500 only three survive, because we would
*be* the book.

**This is capacity-limited, not rate-limited.** The percentages look
extraordinary and the absolute numbers are small: the whole measurable
opportunity here is roughly $24/day. That is consistent with the program's
purpose — these are $150–$500 pools on small markets, too small to attract
anyone for whom $24/day matters.

### These are GROSS. Trading losses are the same order of magnitude.

`sizing.py` counts reward only. It contains no trading P&L term at all, and
that omission is not a rounding error.

Combining the measured one-sided fill rate and markout from 6h with the reward
above — `drag/day = 24 x P(one-sided fill per hour) x E[markout] x markets`:

| size | reward/day | drag (median) | drag (trimmed) | drag (mean) | net |
|---|---|---|---|---|---|
| 5 | $4.68 | −$0.64 | −$1.77 | −$3.88 | **$4.04 → $0.80** |
| 25 | $23.89 | −$2.88 | −$8.41 | −$18.94 | **$21.01 → $4.94** |
| 100 | $37.43 | −$5.71 | −$8.76 | −$38.84 | **$31.71 → −$1.41** |

**Which statistic you pick decides whether this is a business.** At 25
contracts it is either a $21/day operation or a $5/day one; at 100 contracts
the mean case is outright negative. 6h established that the sign of one-sided
markout **cannot be determined** from n=14–19 with one outlier dominating the
mean — so this range cannot currently be narrowed, and the honest reading is
that net revenue is unknown within a factor of four.

> **SUPERSEDED 2026-08-17 by 6i.** The range *was* narrowed, by changing the
> statistic rather than by waiting for n. Using the bootstrap interval on the
> mean instead of picking between median/trimmed/mean, the table becomes:
>
> | size | reward/day | best | central | worst |
> |---|---|---|---|---|
> | 5 | $4.68 | $4.30 | **$3.35** | $2.20 |
> | 25 | $23.89 | $21.49 | **$16.92** | $11.30 |
> | 100 | $37.43 | $29.15 | **$10.50** | **−$12.48** |
>
> **At 25 contracts the operation is positive across the whole interval.** The
> factor-of-four uncertainty is gone at that size; it survives at 100, where
> the interval straddles zero. The two missing effects listed below are still
> missing, and item 2 is now the largest unmeasured term in the economics.
>
> **SUPERSEDED AGAIN by section 10.** Adding a reward line that assumes
> continuous resting to a drag line that assumes fills double-counts our
> presence. Simulated together, net falls ~40% to **$10-$26/day** on $300 at 12
> markets. Both tables above are upper bounds; use section 10.

**Two effects are missing, and both make it worse:**

1. **Partial fills are not counted.** `markout.py` requires the *whole* order
   to fill, so the modelled fill rate *falls* with size (10.7% at 5, 6.8% at
   100). That is an artifact of the predicate, not a property of the market: in
   reality a 100-contract quote fills partially far more often than a
   5-contract one fills completely. Drag at large size is understated,
   and understated worst exactly where the table already looks worst.
2. **A fill interrupts reward accrual on BOTH sides.** Section 2: the two-sided
   rule means pulling our building orders after a fill zeroes the snapshot, not
   just the filled side. So a fill costs markout *and* the reward stream for as
   long as flattening takes. Neither number above includes it.

**Consequence for the order of work.** The binding constraint is no longer the
pool, the share, or the scale — all three are now measured. It is the **cost of
being filled**, which is unmeasured and large enough to erase the revenue.
Getting enough fills to establish that sign is the critical path.

> **Updated 2026-08-17.** 6i measured the markout half of the cost of being
> filled, and it does not erase the revenue at 25 contracts. The binding
> constraint moved again, to the half 6i could not measure: **a fill zeroes
> reward accrual on both sides while we flatten** (item 2 above). That is now
> the critical path, and it is answered by open question 3 — whether our own
> orders must be on both sides, or merely *someone's* — which is replayable
> against books already captured and needs no new data.

### OPERATIONAL: a one-contract evidence run would confirm nothing

At one contract only **1 of 10 markets clears the $1.00 minimum**, and a payout
below it is not paid at all — not deferred, forfeited. So the Phase 3
one-contract run as currently planned would very likely produce **$0.00 of
reward**, which cannot confirm the `period_reward` scale, cannot produce a
payout row, and cannot distinguish "the scale is wrong" from "we were under the
threshold".

**The evidence run needs enough size to clear $1.00 over the program period, or
it is not evidence.** On these pools that means roughly 5 contracts in a market
whose period is short enough to pay out inside the run. Size the run from the
program, not from a habit of starting at one.

### Guards, and why each exists

Three exclusions, all of which an earlier version of this script lacked — it
reported **$2,175/day and 9,779%/day** before they were added:

- **crowded** (2 markets): our size over 25% of the qualifying score. There the
  static-book assumption fails and we are measuring ourselves. Same guard and
  threshold as `analyze_capture.py`.
- **shorter than a day** (8 markets): a 1-hour index program with a $285 pool
  annualizes to $7,105/day, which is arithmetic, not revenue. The market does
  not exist for a day.
- **under 10% period coverage** (32 markets): the largest single correction. A
  share measured over twenty minutes and projected across a 1.8-day period
  assumes no competitor ever arrives. `KXBILZERIANCONCEDE` showed a 23% share
  from 46 snapshots and alone contributed $36/day.

### Limits

- **10 of 52 markets survive**, and their coverage is only 10–25% — share is
  still extrapolated 4–10x across each period.
- Assumes we rest **continuously** for the whole period. Any downtime cuts the
  share proportionally, since reward is a time integral.
- Static book: nothing models competitors responding to our presence, and at
  larger sizes we would certainly move it.
- Politics/economics markets only, ~14 hours of books, no sports (6h).
- **Reward only — gross.** See "These are GROSS" above: the trading drag is the
  same order of magnitude and cannot currently be bounded. Fees are additional
  again on top, and the maker rate is still unmeasured (6e).

## 10. Reward and fills in one simulation — the estimate falls ~40%

`scripts/net_sizing.py`, 2026-08-17. Sections 9 and 6i computed reward and drag
under **contradictory assumptions and then added them**: `sizing.py` never reads
the trade tape at all and assumes we rest continuously for the whole period,
while 6i's drag assumes we are filled and flattening. Both cannot be true of the
same minute.

This runs one clock per market. A fill takes our quotes down, and because the
filing excludes snapshots without two-sided liquidity (section 2), the reward
integral stops on **both** sides for as long as we are flat.

### The result at 25 contracts on $300, 12 markets

| flatten after fill | uptime | fills/day | reward/day | drag/day | **net/day** |
|---|---|---|---|---|---|
| 0s (never pull) | 100% | 45.1 | $38.98 | −$13.02 | **$25.96** |
| 300s | 98.0% | 36.9 | $37.53 | −$18.48 | **$19.05** |
| 900s | 95.2% | 30.0 | $35.22 | −$23.51 | **$11.71** |
| 3600s | 87.9% | 22.7 | $29.60 | −$11.16 | **$18.45** |

**Net is $10–$26/day, against the $31.76 that adding sections 9 and 6i
produced.** The integrated number is roughly 40% lower, and the honest range now
spans a factor of 2.6 driven by `--flatten-seconds`, which is unmeasured.

The non-monotonicity at 3600s is real but not a signal: pulling for an hour
avoids more fills than it forfeits reward, and the surviving fills are a
different sample. It is sample composition, not an optimum. Do not read
"flatten longer" as a policy from this table.

### Two model corrections, both of which make the answer worse

**1. Queue position persists, and that quadruples the fill rate.** `markout.py`
treats every snapshot as an independent experiment and puts us at the back of
the queue each time. A real quoter holds its place while its price is still the
one it wants, and volume trading through eats the queue ahead. Modelling that
gives **37 fills/day across 12 markets against the ~11/day** implied by 6i's
0.0385 fills/market-hour.

Fill cost is therefore a much larger line than 6i suggested, and 6i's fill rate
should be read as a **lower bound** produced by a deliberately pessimistic queue
assumption, not as a measurement of how often we get hit.

**2. Partial fills barely matter here.** Under `--fill-model partial` the fill
rate rises (45.1 vs 40-ish whole-order at 0s flatten) but net moves by under a
dollar. The concern recorded in 9 and 6i was correct in direction and small in
magnitude once the queue is modelled properly.

### The share statistic moved the answer more than anything else measured

`sizing.py` reduces per-snapshot share to a period fraction with the **median**.
Reward is a time integral, so the **mean** is the formally correct statistic —
and switching to it raised reward from $37.44 to $53.98, a **44% swing from a
one-line choice**, larger than the entire drag uncertainty in 6i.

Neither statistic is simply right. Measured across 77 markets:

- The typical market is **not** concentrated: its best 10% of snapshots carry a
  median of **16%** of its total reward score (uniform would be 10%), and the
  median mean/median ratio is **1.04x**. For most markets the choice is
  irrelevant.
- But the markets that **rank highest by mean are disproportionately the skewed
  ones** — `KXBILZERIANCONCEDE-26AUG18-SEP01` runs 42% in its top decile with a
  5.2x mean/median gap, `KXFISHBACKCONCEDE-26SEP01-AUG19` a 3.0x gap.

**Ranking by the mean selects markets whose mean is inflated by a minority of
snapshots** — the thin-touch books where section 4 already warns the
static-book counterfactual is least trustworthy. This is the same failure mode
as `sizing.py`'s first version reporting $2,175/day: a statistic choosing its
own outliers.

**Fix: a concentration guard.** Drop any market whose best 10% of snapshots
carry more than 30% of its reward score. With it, mean and median agree to
within $3/day ($38.98 vs $35.98) — the guard removes exactly the markets where
the statistic choice mattered, which is what a correct guard looks like.

### What this does and does not change

- **The strategy is unchanged.** Still positive, still 12 markets at 25
  contracts on $300, still capacity-limited.
- **The magnitude is 40% lower** and the dominant uncertainty is no longer the
  markout sign (6i settled that) but `--flatten-seconds`: the post-fill policy.
  That is a design choice, not a market property, so it is ours to pick — and
  picking it needs the exit-cost model that does not exist yet (NEXT item 4).
- **Still gross of fees**, still a static book, still shares extrapolated from
  10–33% period coverage, still politics/economics markets only.

## 11. The ranking metric is wrong, and it is the largest lever found so far

Measured 2026-08-18 over 74 markets in `data/capture.db`.

`record_books.py` ranks candidates by `period_reward / target_size`, and
`docs/PLAN.md` line 212 calls it *"exactly the right Kalshi metric"*. Both
inherit it from liquidity-bot's `rank_candidates`. **It was ported, not derived,
and on Kalshi it is worse than useless.**

The justification is stated at `record_books.py:341`: *"Target size is the
denominator we compete against, so reward/target is the natural density."*
**That premise is false**, and section 4 already contained the reason without
anyone connecting it: DiscountFactor 0.50 halves each tick's contribution, so
the effective competition is the top few ticks, not the full Target Size.

| quantity | spread across our sample |
|---|---|
| `target_size` | 3x (300, 500, 1000 — and 1000 in 99.2% of the live universe) |
| **measured denominator** | **629x** (105.2 to 66,144.5, median 726.8) |

Ranking by a quantity that barely varies, as a proxy for one that varies 629x,
cannot work.

### What each ranking actually earns

| ranking | Spearman vs measured $/day | $/day from its top 12 |
|---|---|---|
| `reward / target_size` (current) | **−0.150** | **$24.39** |
| pool alone | +0.114 | $74.03 |
| `reward / measured denominator` | +0.619 | **$158.61** |
| perfect foresight | — | $225.51 |

**The current metric is negatively correlated with revenue** — it is worse than
ranking by pool alone, and worse than picking at random. Switching to density is
worth roughly **6.5x** on the top 12, which is far larger than any size, breadth
or policy lever measured to date.

**Honest limit on that +0.619.** It is partly circular: our share is
approximately `q / (q + denominator)`, so revenue is already about
`pool / denominator` by construction, and the correlation largely confirms the
formula matches itself. **The non-circular finding is the 629x spread** — that
is a measurement, and it is what disqualifies `reward/target`. Treat the $158.61
as an upper bound too, since it ranks and scores on the same books.

### The denominator is stable enough to rank on — OPEN QUESTION 6 ANSWERED

Ranking uses the *past* denominator to earn on the *future* one, so the metric
is only usable if the denominator persists. Splitting each market's snapshots
into halves, over 71 markets with at least 200 qualifying snapshots each:

| measure | value |
|---|---|
| Spearman, first half vs second half | **+0.818** |
| per-market ratio second/first, median | 1.19x |
| within 2x of itself | 52 of 71 (73%) |
| top 12 that stay top 12 | 8 of 12 |

Section 7 question 6 asked *"whether reward density is stable enough over a Time
Period to rank on, or whether it must be re-measured continuously."*
**Answer: stable enough to rank on, but re-measure it** — a quarter of the top
12 rotates out within hours, and the worst market drifted 76.9x.

**Limit:** both halves come from one ~20h capture, so this establishes stability
over roughly ten hours, **not across a 7-14 day program period**, which is what
the question literally asked. A longer capture is needed to close it fully.

### How this was found, and the process point

The claim was inherited from a working implementation, restated in the plan as
settled, and repeated in the capture script's own docstring — three places, none
of which tested it. It survived because on Polymarket it is genuinely right:
there `target_size` ranges 5,000-15,000 and really does measure required
liquidity. On Kalshi it is a near-constant.

**A ported calibration is a hypothesis, not a fact** — the same rule the top of
this file already states about liquidity-bot's numbers. It was applied to
`fill_hazard`, the 900s clock and the 2-cent spread rule, and not to this.

## 12. You cannot rest out of these books — the exit is a taker path

`scripts/exit_cost.py`, 2026-08-18, 39 simulated fills at 25 contracts.

Every prior number charged a fill its **markout** — where the mid went
afterwards — which is a proxy for adverse selection, not a realised cost.
`net_sizing.py` takes quotes down and then assumes we are flat at **zero exit
cost**. `docs/REFERENCE_CRITIQUE.md` 4e says that omission is the whole story on
the only live instance of this strategy: crossed exits −$1.21 median against
passive −$0.31, five times as many crossed, turning a +$17.24 day into −$7.33.

| passive deadline | exits | passive | crossed | passive $ | crossed $ | blended $ |
|---|---|---|---|---|---|---|
| 300s | 39 | **0%** | 100% | — | −$0.2851 | −$0.2851 |
| 900s | 39 | 3% | 97% | +$0.2500 | −$0.2801 | −$0.2750 |
| 1800s | 39 | 3% | 97% | +$0.2500 | −$0.2801 | −$0.2750 |
| 3600s | 39 | **8%** | **92%** | +$0.2500 | −$0.2801 | −$0.2632 |

### This resolves the sharpest open question in the critique

`docs/REFERENCE_CRITIQUE.md` 4e item 4 posed it directly: our books barely trade
so we fill rarely and should bleed rarely — but thin quiet books are also the
ones you cannot exit passively, and *"rare fills that are each expensive to exit
is not obviously better than frequent fills that are cheap to exit."*

**Answer: the exit is a taker path, structurally.** Giving a reducing order a
full hour still leaves 92% of exits crossing. The same quietness that keeps our
fill rate low keeps the counter-flow that would let us rest out from ever
arriving. **The reference's 73% taker share is not a policy failure we can
avoid by being more patient — on these books it is closer to 100%.**

So the inventory clock is not a real lever. Extending the passive deadline from
300s to 3600s converts 8% of exits and improves the blended cost by 2.2 cents
per exit, while holding the position twelve times longer. **Do not port a
generous inventory clock; there is nothing for it to buy.**

### The cost itself is modest, and smaller than the markout implied

Crossing costs **−$0.28 median per exit** at 25 contracts. Against
`net_sizing.py`'s ~37 fills/day across 12 markets that is roughly **−$10/day**,
which lands inside the −$13 to −$24/day drag range section 10 derived from
markout by a completely independent path. Two different methods agreeing to
within a factor of two is the strongest consistency check the economics have.

It is far cheaper than the reference's −$1.21 median. The likely reason is
FINDINGS 6c: the taker fee is parabolic and these markets are tail-priced, so
the fee is near its minimum, and 'thin' is 0 — the books absorbed 25 contracts
without walking.

### Limits, and one of them biases the answer

- **n=39.** The fill detector here is stricter than `net_sizing.py`'s (it wants
  one trade to clear depth plus our size, rather than accumulating volume), so
  it undercounts fills.
- **The cross is priced against the book AT FILL TIME**, not at the moment the
  deadline expires. A real cross after 900s of waiting meets a book that has
  moved — and moved against us, since that is what adverse selection means.
  **Crossed cost is therefore understated**, and understated most at the long
  deadlines that already look best.
- Passive exits show +$0.25 because `exit_quote_price` only improves the price
  while it still does not lose money against entry, so a passive fill is
  profitable by construction. That is the reference's rule, not a discovery.
- 25 contracts only; the walk cost grows with size and 'thin' would stop being
  zero.

## 13. Kalshi fees against Polymarket, priced on the reference's real fills

2026-08-26. Both fee schedules are verified against live fills on their own
venue, so this is arithmetic, not estimation.

```
Polymarket   taker  = 0.06   x qty x p x (1-p)   charged, rounds UP to cents
             maker  = 0.0125 x qty x p x (1-p)   CREDITED (rebate), rounds DOWN
Kalshi       taker  = ceil(0.07 x qty x p x (1-p) x 10_000) / 10_000   charged
             maker  ~ 25% of taker, CHARGED       UNVERIFIED (6c)
```

Applying the Kalshi schedule to `liquidity-bot`'s **1,847 real fills** (772
taker, 1,075 maker, 12 days to 2026-08-25, median fill price 0.510):

| | taker | maker | net | per day |
|---|---|---|---|---|
| Polymarket, actually charged | +$48.36 | **−$17.13** (rebate) | **+$31.23** | +$2.60 |
| Kalshi schedule, same flow | +$57.01 | **+$23.62** (charged) | **+$80.63** | +$6.72 |

**Kalshi costs 2.58x on identical flow.** The taker line alone is only **1.18x**
(0.07 versus 0.06) — *the entire gap is the maker side changing sign.*

Robust to the unverified maker rate. Even if Kalshi maker fees were **free**,
the same flow costs 1.83x, because Polymarket's rebate is a revenue line we lose
rather than a cost we pay:

| Kalshi maker assumption | net | vs Polymarket |
|---|---|---|
| free | $57.01 | 1.83x |
| 25% of taker (reported) | $80.63 | 2.58x |
| 50% of taker | $104.19 | 3.34x |
| maker = taker | $151.32 | 4.85x |

There is no maker rate at which Kalshi is cheaper on this flow.

**One place Kalshi is cheaper: rounding.** Kalshi ceilings at 4 decimals (6e),
Polymarket at whole cents and asymmetrically — taker up, rebate down. That is
what makes Polymarket per-contract economics ~37% worse at size 1. Kalshi has no
such size floor on fees, so small-size experiments are not fee-penalised here.

### The density-ranked pool sits where the fee is most expensive

Measured over the tracked markets of each capture (best bid/ask from
`orderbook_fp`):

| capture | ranking | median mid | median spread | p(1−p) | taker fee/contract |
|---|---|---|---|---|---|
| `capture.db` | reward/target | 0.360 | **1¢** | 0.1744 | $0.0122 |
| `capture_wide.db` | reward/target | 0.150 | 3¢ | 0.1131 | $0.0079 |
| `capture_long.db` | **density** | **0.495** | **6¢** | 0.2158 | **$0.0151** |

Section 12 explained its cheap −$0.28 exit partly by "these markets are
tail-priced, so the fee is near its minimum." **That is a property of the badly
ranked pool, not of the venue.** Ranking by density — the 6.5x revenue lever of
section 11 — lands on markets priced at the fee maximum (0.495, where p(1−p) is
0.216 of a possible 0.25) with spreads six times wider, and trade flow **2.0x
heavier** (1.49 versus 0.73 trades per market-hour, mean).

Back-of-envelope, the cross therefore costs roughly half-spread plus fee:
**3.0¢ + 1.5¢ = 4.5¢/contract** against the old pool's 0.5¢ + 1.2¢ = 1.7¢, i.e.
about **2.6x per exit**, on about **2x as many fills**. So section 11's 6.5x
revenue gain is bought against a drag that scales roughly 5x. Nominally still a
large win — $158.61/day of reward against a drag near $50/day rather than $10 —
but **the multiple is closer to 3x than 6.5x**, and section 12's known bias
(the cross is priced at fill time, not at deadline) cuts the same direction.

**This is an estimate, and it does not need to stay one.** `exit_cost.py` and
`net_sizing.py` both take `--database` and `capture_long.db` is on disk.

### The reference's own fee line has gone the wrong way

`docs/REFERENCE_CRITIQUE.md` 4e read the ledger at 203 fills. It now holds
1,847. Fees paid per day, net of rebate: **+$0.43 on 08-15, +$6.24 on 08-25**.
Taker fees alone ran $9.02 on 08-25 against $2.78 of maker rebate. The venue
that was supposed to pay us to make markets is now billing $6/day, and on
Kalshi's schedule the same flow would bill $12–$15.

---

## 14. The reward systems are the same rule; the venue is Polymarket US

2026-08-26. Confirmed the reference trades **Polymarket US**, the CFTC-regulated
entity — `api.polymarket.us`, `gateway.polymarket.us`, rules read at
`docs.polymarket.us/incentives/liquidity`. This matters: `polymarket.com` runs a
different scheme that is **quadratic in spread**, and liquidity-bot's FINDINGS
notes explicitly that it "came from the `.com` scheme and does not apply here."
Both venues in every comparison in this file are CFTC DCMs running the
discount-factor scheme, so the comparisons are like-for-like.

**Identical on both venues:** `Score = DiscountFactor ^ (ticks from best) × size`;
linear in size with no per-account cap; walk from the touch outward until
`targetSize`, beyond which orders score zero however close to the touch; payout
purely proportional to share of total score; each side normalized independently
per snapshot; rewards under $1.00 not paid; **spread does not enter the formula.**
This is why `rewards.py` ports with field renames.

**Four differences that decide the design:**

1. **The two-sided gate.** Kalshi voids the *entire snapshot* if either side
   lacks `targetSize` (section 2). Polymarket US normalizes each side
   independently, so one qualifying side still pays. This is why invariant 4
   cannot port.
2. **The $1.00 minimum inverts.** Polymarket US's threshold is an **aggregate
   settlement threshold that accumulates across markets** — their $0.007 per
   market-period eventually pays. Kalshi's filing reads as per Time Period, which
   is why section 9 measured one contract paying **$0.00 on 9 of 10 markets**:
   forfeited, not banked. **UNVERIFIED whether Kalshi aggregates across
   programs** — and this is exactly the mistake liquidity-bot made in the
   opposite direction ("applying it per side per market was wrong, and was
   removed").
3. **Kalshi is projectable everywhere.** Polymarket US keys early/day_of/live to
   event start and only `day_of` has a reliable clock; `live` carries 8x the pool
   and their pregame design forbids it. Every Kalshi program carries explicit
   `start_date`/`end_date`.
4. **Different parameter regimes.** Kalshi DF 0.50 (99.96%), target 1000
   (99.2%), median pool $1.10/day/market. Polymarket US DF 0.30–0.50, target
   5,000–15,000, pools $30–$200/period. Kalshi's target barely varies while the
   **measured denominator varies 629x** (section 11) — and Kalshi books are thin
   enough to own, where Polymarket US has "7,500–15,000 contracts sitting at
   these touches against our 10."

### Reward rate per contract-hour is WORSE on Kalshi, not better

The reference's realised earnings, size 10, one clean day: **$0.230 per resting
order-hour** = ~$0.023 per contract-hour. Our best-case Kalshi replay (section
15) runs 12 markets × 2 sides × 24h at 25 contracts for $87/day = **$0.0060 per
contract-hour** — roughly **a quarter of Polymarket US's rate**, and that is our
upper bound against their realised figure.

**Kalshi's advantage is breadth and thin denominators, not rate.** More markets
whose denominator we can dominate, not more dollars per contract resting.

---

## 15. First profitability estimate on a well-selected pool — and why to halve it twice

2026-08-26, `capture_long.db` (250 density-ranked markets, 3.76h, 46,973 books).
This is the first economics run on markets chosen by the ranking section 11
established, rather than the anti-correlated one.

`net_sizing.py --size 25 --fill-model partial`, policy touch, gross of fees:

| flatten | markets | uptime | fills/day | reward$ | collat$ |
|---|---|---|---|---|---|
| 0s | 12 | 100.0% | 19.3 | 91.73 | 300 |
| 900s | 12 | 98.3% | 19.3 | 87.01 | 300 |
| 3600s | 12 | 93.7% | 21.0 | 102.48 | 300 |

`exit_cost.py --size 25` on the same pool: **59 exits, 92–97% must cross,
median −$0.4313** including the taker fee at VWAP — against **−$0.28** on the
old pool, confirming section 13's prediction that density ranking buys more
expensive exits.

Charging the realised exit rather than the markout proxy (they are two
accountings of the same fill and must not be added):

```
reward                    +$87.01/day
exit cost   19.3 x -0.43   -$8.32/day
entry maker fee (UNVERIFIED 25% rate)  -$1.82/day
                          -----------
net                       ~+$77/day on $300 collateral  =  ~26%/day
```

**26%/day is not a forecast. It is a measurement of how much the model assumes.**

### The correction that matters: uptime

The simulation rests on 24 quoted sides at **98% uptime**. The only live instance
of this strategy anywhere achieved **135–187 order-hours/day against ~960
possible — 14–19%**. Reward pays for resting, and nothing in our capture tests
whether we can actually hold 24 sides continuously; `record_books.py` itself did
not survive four hours.

Applying the reference's realised uptime to our own reward line:

```
$87/day x 0.25  ~  $22/day net on $300  =  ~7%/day
```

**That lands inside section 10's $10–$26/day**, derived on the old pool by a
different route. Two independent paths agreeing is the strongest thing this
estimate has going for it — and it is the number to plan against, not the $77.

### Both instruments disagree with themselves on this pool — do not trust the detail

1. **`--policy inside` reports 0.0 fills/day in `net_sizing.py`** at flatten
   0/300/900, while `exit_cost.py` finds **156 fills** on the same data and the
   same policy — 2.6x the touch policy's 59, which is the expected direction. A
   quote one tick inside the touch cannot fill *less* than one at it. One of the
   two fill detectors is wrong under `inside`, and `inside` is the policy section
   4 recommends.
2. **Markout is POSITIVE on this pool** (+$26.53/day, mean), contradicting
   section 6i's adverse result (p=0.0014) measured on `capture_wide.db`. Either
   density-ranked markets have genuinely two-way flow, or the statistic is
   outlier-driven. Unresolved. The estimate above ignores markout entirely and
   charges the realised exit instead, which is the conservative choice.

### Everything above still sits on an unconfirmed scale

`period_reward` is inferred at 1e-4 (section 3, corroborated across 2,940
programs but never confirmed by a payout). If that scale is wrong, every dollar
figure in this file moves by the same factor. It remains the cheapest single
thing a real evidence run would settle.

---

## 16. The reference's losses are PRICE, ours are FEE — and that is a warning, not a comfort

2026-08-26. Checking section 15's drag against the only live instance of this
strategy, and repricing its flow on Kalshi's schedule.

### On Polymarket US, the fee is 5% of a crossed exit

772 real taker fills from the reference ledger, median 5 contracts at p=0.510:

| | median fee per taker fill |
|---|---|
| Polymarket US, actually paid | **$0.0600** |
| same fills on Kalshi's schedule | **$0.0699** |

Against their published median crossed exit of **−$1.21**, the fee is **5%** of
the loss — **6%** if repriced on Kalshi. Kalshi's 2.58x fee multiple (section 13)
therefore moves their damage by about **one percent**. Their loss is not fees.
It is price: the market moved against the position before they got out.

### On our simulated Kalshi exits, the fee is ~90% of the cost

`exit_cost.py` on `capture_long.db`, 900s deadline, crossed path:

| size | n | crossed $ | per contract |
|---|---|---|---|
| 5 | 78 | −$0.0810 | **−$0.0162** |
| 25 | 59 | −$0.4348 | −$0.0174 |
| 50 | 45 | −$0.9221 | −$0.0184 |
| 100 | 33 | −$1.8895 | **−$0.0189** |

**Per-contract cost is nearly constant across a 20x size range** (+17% from 5 to
100). A walk-the-ladder cost grows with size; a fee does not. The Kalshi taker
fee at this pool's median `p(1−p)` of 0.2158 is **$0.0151/contract** — which
alone explains **93%** of the size-5 cost. The book absorbs 100 contracts with
almost no walk (`thin=0` at every size).

So the two venues' exit costs are made of different things:

```
Polymarket US crossed exit   -$0.242/contract    5% fee,  95% price
Kalshi simulated exit        -$0.0174/contract  ~90% fee, ~10% price
```

### Their exit is 14x more expensive per contract, and that is the real finding

−$0.242 against −$0.0174. **This is not evidence that Kalshi is cheaper. It is
evidence that our model does not contain the term that costs them the money.**

Section 12 already named the mechanism as a known bias: **the cross is priced
against the book AT FILL TIME, not when the deadline expires.** A real cross
after 900s of waiting meets a book that has moved, and moved adversely — that
is what adverse selection means. Our simulation therefore measures the fee
almost exactly and the adverse move almost not at all, and the reference's data
says the adverse move is 95% of the damage.

**CORRECTED 2026-08-26.** An earlier version of this section built the bound on
**−$0.242/contract**, taken from the published *median crossed exit* (−$1.21 at
median qty 5). That is the median of the **worst subset** — crossed exits only —
used as if it were the average over all flow. It overstated the drag by 4x.

### The reference's realised economics, by quote-size era

Derived from 1,847 fills with `accounting.py`'s own closed-pair logic (long and
short legs pair and settle at exactly 1.00; fees tracked separately), on a copy
of the production ledger. Markets are assigned to the era of their first fill.

| era | days | fills | markets closed | price P&L | fees | net trading | **per contract** |
|---|---|---|---|---|---|---|---|
| size 5, 08-14..08-20 | 7 | 742 | 238 | −$49.16 | −$7.76 | −$56.92 (−$8.13/day) | **−$0.0417** |
| **size 10, 08-21..08-25** | 5 | 1,105 | 313 | −$181.68 | −$23.47 | **−$205.15 (−$41.03/day)** | **−$0.0586** |

**Doubling quote size made per-contract economics 40% worse**, not neutral —
−$0.0417 to −$0.0586. Their own reasoning was that reward and losses both scale
with size so the ratio holds; on the loss side it did not hold. Section 4e's
point 2 predicted this asymmetry for Kalshi and it turns out to be true on
Polymarket US as well.

**The corrected bound.** Their realised −$0.0586/contract against our modelled
−$0.0174/contract is a gap of **3.4x**, not 14x:

```
19.3 fills/day x 25 contracts x -$0.0586  =  -$28.3/day   against reward +$87/day
                                          =>  net +$59/day
at the reference's realised uptime (x0.25) =>  net +$15/day
```

**So the stress case is positive, not negative.** Even if Kalshi flow behaved
exactly like Polymarket US's at its current size, section 15's estimate survives
— it falls from ~$22/day to ~$15/day. The earlier "−$117/day, net −$30/day"
claim was an artifact of the wrong statistic and is withdrawn.

**Repricing their flow on Kalshi's fee schedule**, for completeness: their
size-10 fees of −$4.69/day become **−$11.81/day** (section 13), so the same
strategy on Kalshi's schedule loses −$48.15/day rather than −$41.03/day — **17%
worse**, entirely on the fee line.

### What this does to the estimate

Section 15's $22/day survives only if Kalshi's quiet books really do avoid the
adverse move. The reference planned for trading losses at 5% of reward and
measured over 100%. **Our drag is currently 10% of reward.** That is the same
shape of assumption at the same point in the project, and it is the assumption
that broke there.

**This is measurable without new data.** Repricing the cross at deadline rather
than at fill time is a change to `exit_cost.py` against books already captured.
Until that is run, treat the exit cost as a floor.

---

## 17. The reference is PROFITABLE at size 10 — the pessimistic prior is withdrawn

2026-08-26, operator-supplied venue figures for Polymarket US at `quote_size`
10, `max_markets` 20 ($200 worst-case exposure). These come from the venue, and
they supersede every reward figure derived in this file from the repo copy —
the production ledger available here carries only 13 `execution_reward_earnings`
rows, and `docs/REFERENCE_CRITIQUE.md` 4e read the trading side at 203 fills.

| date | trading | reward | net |
|---|---|---|---|
| 2026-08-20 | −$17.99 | $22.21 | +$4.22 |
| 2026-08-21 | −$30.52 | $32.79 | +$2.27 |
| 2026-08-22 | −$24.19 | $25.64 | +$1.45 |
| 2026-08-23 | −$42.88 | $85.09 | **+$42.21** |
| 2026-08-24 | −$43.42 | $174.74 | **+$131.32** |
| 2026-08-25 | −$27.95 | $172.90 | **+$144.95** |
| 2026-08-26* | −$57.10 | pending | — |

Six complete days: trading −$31.16/day, reward **+$85.56/day**, net **+$54.40/day**.
Last three days: net **+$106.16/day**.

### Reward scaled 8x while trading losses stayed flat

This is the finding, and it contradicts the reasoning both projects have been
using ("reward scores `discount^ticks x size` and losses scale with size too, so
the ratio is unchanged" — 4e point 2):

```
                    08-20..08-22 mean     08-23..08-26 mean     ratio
reward                    $26.88               $144.24          5.4x
trading                  -$24.23               -$42.84          1.8x
drag as % of reward   81%, 93%, 94%  ->  50%, 25%, 16%
```

**CORRECTED: the loss line is not flat.** An earlier version of this section
said trading stayed "flat, inside its own daily noise". It grew **1.8x** while
reward grew 5.4x. The ratio improved enormously and the conclusion stands, but
losses track the reward line rather than being independent of it, and 2026-08-26
posted **-$57.10**, the worst trading day recorded, against a unified daily loss
limit of $80.

Neither `quote_size` (10 since 08-20) nor `max_markets` (20) changed across this
window. **The scaling did not come from size or breadth.** The commits landing
over exactly these days are uptime and slot-utilisation work — `fix live
resting-hours telemetry`, `Persist daily score hours across restarts`, `Make
incremental market top-up transactional`, `Fix recovery visibility and slot
release stalls`. **Hypothesis, from commit titles rather than measurement: the
8x is recovered resting time.** The operator can confirm or refute this directly.

If that is right it is the most transferable result either project has produced,
because reward is a time integral over resting orders on **both** venues, and
resting time is an engineering variable, not a market property.

### What this does to our Kalshi numbers

1. **Section 15's uptime haircut (x0.25) was calibrated on their BROKEN uptime.**
   It came from 135-187 order-hours/day against ~960 possible. If the fix
   recovered that, the haircut is too harsh and $22/day is understated.
2. **The reward-per-fill advantage shrinks.** Their $172.90/day over ~150 maker
   fills is **$1.15/fill** against our modelled $4.51 — **3.9x**, not the 19x
   claimed earlier today off the stale $29.54 figure.
3. **Their drag is now 16-25% of reward.** Ours is modelled at 10% (own exit
   cost) or 33% (their per-contract rate applied). **We are in the same regime,
   not a better one.**
4. **Every argument in this file that leans on "the only live instance is
   loss-making" is withdrawn.** That includes 4e's instruction to take the
   pessimistic end when our own range cannot be resolved. The live instance is
   making money, and the prior should be neutral.

### The strategic question this opens

A working, profitable liquidity-reward market maker exists **today** on
Polymarket US, earning ~$106/day net over the last three days on 20 markets and
$200 of worst-case exposure. Kalshi remains unbuilt, has never placed an order,
and its reward scale is still inferred.

**"Is Kalshi better than scaling what already works?" is now a live decision, and
nothing in this file answers it.** Kalshi's case was breadth (~10x the
addressable universe) and a lower qualification bar. Its case was never a better
reward rate — section 14 measures the rate as *worse* per contract-hour. If the
reference's constraint was resting time rather than market count, breadth may
not be the binding lever at all.

---

## 18. Size is the wrong lever on Kalshi — measured, not argued

2026-08-26. `net_sizing.py --fill-model partial`, flatten 900s, on
`capture_long.db` (density-ranked pool). Contracts resting = markets x size x 2
sides.

| size | markets | contracts | reward/day | **$/contract** | %/day on collateral |
|---|---|---|---|---|---|
| 3 | 6 | 36 | $28.96 | **$0.804** | 185% |
| 5 | 7 | 70 | $50.77 | $0.725 | 164% |
| 10 | 11 | 220 | $88.37 | $0.402 | 91% |
| 15 | 11 | 330 | $55.00 | $0.167 | 43% |
| 20 | 14 | 560 | $78.19 | $0.140 | 36% |
| 25 | 12 | 600 | $87.01 | $0.145 | 38% |
| 40 | 7 | 560 | $58.65 | $0.105 | 36% |

**Reward per contract falls 8x from size 3 to size 40, monotonically.** That is
the reliable statistic here and it is the saturation of `q / (q + Σ)` showing up
in dollars: the density ranking selects small denominators, so our own size
enters its own denominator early.

**Do not read the reward column as a size-response curve.** It is not monotonic
(size 15 earns less than size 10) because **the funded market set changes with
size** — collateral guards fund different markets at each size, so each row is a
different portfolio. Only `$/contract` compares like with like.

### What this means

- **Quantity is not irrelevant.** Total reward does rise with size up to ~10
  ($28.96 -> $88.37). Below that the `$1.00` minimum payout is a real floor —
  section 9 measured one contract paying **$0.00 on 9 of 10 markets**.
- **Past ~10 contracts, additional size buys almost nothing** on this pool while
  consuming collateral linearly. Return on capital falls from 91%/day at size 10
  to 36-38% at size 20-25.
- **The lever is breadth, not depth.** Capital spent on depth in one market is
  capital not spent on a second market, and share saturates while market count
  does not.
- **This is the opposite of the reference's situation.** On Polymarket US their
  10 contracts sit against 7,500-15,000, so they never saturate and their
  measured 5->10 doubling returned a clean 1.89x per resting hour (section 17).
  Same formula, different position in the denominator (section 14).

**Limits.** Static book — our size entering its own denominator is modelled, a
competitor *reacting* to us is not, and reacting is exactly what a competitor
does when we take 80% of a side. Small sizes also fund fewer markets, so the
top rows are not simply "better"; they are a different and narrower portfolio.
The `%/day` figures are absurd on their face and inherit every caveat in
section 15, above all the unconfirmed `period_reward` scale.

---

## 19. Audit correction: profitability is promising, but the Kalshi replay is not decision-grade

2026-08-26. Reproduced the reference P&L against its latest production ledger
and the live Polymarket US earnings endpoint, then checked the Kalshi replay
against the current first-party rule descriptions.

### The six-day Polymarket result reproduces, under partial trading accounting

For 2026-08-20 through 2026-08-25, `liquidity-bot/scripts/daily_pnl.py`
reproduces every row in section 17. The arithmetic is exact: trading
**−$31.16/day**, paid reward **+$85.56/day**, reported net **+$54.40/day**;
the final three days are **+$106.16/day**.

The qualification matters: `daily_pnl.py` prices balanced-leg markets only. At
the verification run it excluded 38 unbalanced markets and stated that it
cannot see positions that settled rather than closing. Section 17's number is
therefore a **verified report result, not audited full-account daily P&L**.

Reward rose 7.78x from $22.21 to $172.90, but losses were not literally flat.
The first three complete days averaged −$24.23/day and the last three
−$38.08/day, a 57% increase. They grew far more slowly than reward. The listed
August 25 uptime fixes cannot by themselves explain reward that had already
jumped on August 23–24. `max_markets=20` is a capacity ceiling, not proof that
twenty markets were occupied and resting. The uptime explanation remains a
**HYPOTHESIS**.

### First-party Kalshi sources conflict with the implemented replay

The February 2026 CFTC filing used by `analyze_capture.py` assigns the highest
bid as Reference Price. Kalshi's current Help Center instead describes the
Reference Price as the first level where cumulative size reaches one fifth of
Target Size. The Help Center also says the payable reward is multiplied by the
fraction of non-excluded snapshots.

The current code uses the highest bid and computes `share * pool` without that
non-excluded-snapshot multiplier. Until a controlling source is identified, or
both interpretations are implemented and reported as bounds, sections 14–18
are **INFERRED under a disputed rule model**. "Formula-identical" is too strong;
the venues share a scoring family but not a verified identical implementation.

### The denominator example has one arithmetic correction

For competing score `Σ=4,703.8`, the exact reward-share multiple from size 5
to 100 is **19.6x**, not 21x. Under `q/(q+Σ)`, a 20x increase in `q` cannot
produce more than 20x reward. `Σ` is competing **discounted score**, not raw
contracts, unless every competing contract has multiplier 1.

### Section 18 reproduces the script but does not identify a size optimum

All seven rows reproduce from `net_sizing.py`. They are not a controlled size
sweep: the capital and crowding guards fund a different portfolio at each
size. Consequently neither total reward nor `$ / contract` is a like-for-like
size response. A fixed market set, selected on an earlier window and evaluated
on a later one, is required.

The `%/day on collateral` column is also not reward divided by collateral.
`net_sizing.py` computes `(reward + simulated markout) / collateral`; markout is
positive on this capture despite contradicting the adverse result on the wider
capture. At size 10, reward/collateral is 80.3%, not the displayed 91.1%; at
size 25 it is 29.0%, not 37.8%. Keep reward return and simulated net return in
separate columns.

**Decision consequence:** none of these corrections proves Kalshi is
unprofitable. The nominal headroom still justifies measurement. They do mean
the current tables cannot authorize capital or a full build. The active
experiment and operator boundary are now recorded in `EXPERIMENT.md` and
`DECISIONS.md`.

---

## 20. Current-rule and current-strategy correction

2026-08-26. This section supersedes the reward-rule assumptions behind
sections 4, 9, 11, 14, 15, and 18. Those sections remain historical evidence
of why the instruments changed; their reward dollars and one-tick conclusions
must not drive the current decision.

### VERIFIED — the July filing governs the August capture

Kalshi's July 15 certified filing, effective July 30, supersedes the February
best-bid rule. It sets Reference Price at the first level where cumulative size
reaches one fifth of Target Size, gives full weight to better prices, multiplies
payout by the non-excluded snapshot fraction, rounds down to cents, and retains
the per-program $1 minimum. The current Help Center describes the same rule.

The implementation defaults to `july-2026-one-fifth`; the February mode is
explicitly `SUPERSEDED` and exists only to reproduce old output. Independent
hand fixtures execute in `tests/test_reward_rules.py`.

### MEASURED — stepping inside no longer increases reward share here

Dataset `data/capture_long.db`, August 17–18 capture, size 10, 58,453 usable
snapshots, 56,246 countable (96.2%), 112,492 side comparisons:

| rule mode | inside/touch median | p10 | p90 |
|---|---:|---:|---:|
| July current | **1.000x** | 1.000x | 1.000x |
| February superseded | 1.943x | 1.557x | 1.986x |

Under the current reference, a price better than Reference Price already gets
full weight. Moving one more tick toward the market does not improve score on
these observations. It can still change queue position and fill risk; that is a
different measurement.

Reward-only `sizing.py`, current July rule, current Polymarket entry-price
policy, size 10, $300 cap: seven of 36 trustworthy candidates clear the payout
minimum, modeled reward is **$7.369/day** on $65.20 modeled collateral. The
legacy mode produced $93.414/day. The current number is still not a
fixed-universe result and contains no trading P&L, so it is not profitability.

### VERIFIED — the reference strategy was re-read from current code

The Polymarket repository was inspected read-only with no venue API request.
Local HEAD and GitHub `main` are identical at
`3134678e9937881a4b890c500fd905efb28abad6`; the working tree was clean and the
strategy files match reviewed deployed source `5825db8`.

The actual entry policy is size 10 across 20 sports/day-of slots: join both
touches when spread is at least 2¢, otherwise center an exact 2¢ quote window.
Entries are post-only, constrained to 10¢–90¢ and a stressed complete exit.
After a fill, cancel the risk-building side, work a passive reducer, and force
an IOC after 900 seconds or at T−300 seconds before the event. The reward/cost
gate is advisory/off. See `docs/POLYMARKET_REFERENCE.md` for source mapping and
remaining fidelity gaps.

### MEASURED — later-book loss replay is adverse, with material unknowns

`exit_cost.py`, same capture, size 10, audited Polymarket entry-price policy,
60-second maximum capture gap:

| deadline | fills | passive | timed cross | unknown | priced P&L | mean priced |
|---:|---:|---:|---:|---:|---:|---:|
| 300s | 84 | 5 | 65 | 14 | −$30.4411 | −$0.4349 |
| 900s | 84 | 11 | 56 | 17 | **−$27.8505** | **−$0.4157** |
| 1800s | 84 | 13 | 52 | 19 | −$26.7601 | −$0.4117 |
| 3600s | 84 | 17 | 33 | 34 | −$20.8166 | −$0.4163 |

Timed crosses use the first book at or after the deadline and include the
Kalshi taker fee at actual VWAP. The falling total at longer deadlines is not
evidence that waiting is safer: priced coverage falls from 83.3% to 59.5%.
Unknown fills are not assigned zero, and no complete net can be calculated
until they are bounded and this loss path shares the fixed reward clock.

---

## 21. The isolated read-only server shadow is operational

### VERIFIED — deployment did not share the Polymarket project or process

On 2026-08-27 UTC, tracked commit
`c13524201819c3f771b9b8193e168a9ae85e1372` was installed at
`/root/kalshi-bot` with its own virtual environment, database, logs, and
transient service. The recorder source scan found only the public
`api.elections.kalshi.com` base and default-method `urllib` requests; it found
no order/portfolio endpoint or write HTTP method. All 25 measurement tests
passed on the server.

The pre-canary and post-canary Polymarket supervisor/trader PIDs and start times
were identical. This verifies process separation for the deployment/canary; it
does not prove that future resource use can never interfere, which is why the
service is capped at 20% CPU and 256 MB RAM and remains monitored.

### MEASURED — two-minute canary, not strategy economics

Dataset `data/canary-20260827.db`, run
`cap-20260827T023150Z-a419d203`, 2026-08-27 02:31:50–02:34:07 UTC, five tracked
markets and 50 density candidates:

- 65 raw book snapshots and five market-metadata rows;
- zero non-200 book responses and zero recorded errors;
- SQLite integrity check `ok`;
- 16,371 first-seen program rows and one exchange-status row.

This canary verifies collection mechanics only. It contains no strategy fills
and cannot support a reward, trading-loss, or profitability claim.

### VERIFIED — 14-day collection started

The read-only service `kalshi-readonly-capture-14d` started at
2026-08-27 02:35:40 UTC, using run id
`cap-20260827T023541Z-dcee8aea`, 75 tracked markets, 60-second sweeps, at most
five public reads per second, and hourly density scans. Planned checkpoints are
2026-09-03 and completion on 2026-09-10. The initial service state was active
with one process and about 16 MB memory. This is an operational observation,
not evidence that the strategy is profitable.

### MEASURED — eight-hour operational checkpoint

Dataset `data/shadow-14d-20260827.db`, run
`cap-20260827T023541Z-dcee8aea`, observation window 2026-08-27
02:36:20–10:49:22 UTC:

- 41,501 raw book rows across 1,262 density-candidate tickers;
- 75 active tickers in the preceding five minutes and 5,241 captured trades;
- zero non-200 book responses and zero recorded errors;
- 60.0-second median active-market sample gap, 107.9-second p95, and
  267.1-second maximum over the preceding two hours;
- database plus WAL about 58 MB after 8.2 hours.

The service had zero restarts and its newest book was 30 seconds old. The
longer gaps coincide with hourly density scans that take about 200 seconds.
Those gaps are a known capture bias: downstream reward/fill analysis must mark
them missing rather than infer continuous qualification or no trades.

**VERIFIED capacity observation:** 461 MB host memory was available; Kalshi
used 105 MB with a 113 MB peak under its 256 MB cap; the one-core load averages
were 0.00/0.03/0.00; 19.4 GB disk remained; and the kernel recorded no OOM
event. Linear storage growth implies roughly 2.4 GB for 14 days. No server
upgrade is indicated at this checkpoint.

**UNKNOWN process event:** the Polymarket supervisor/trader observed at launch
were replaced by processes started at 04:02:57 UTC. The Kalshi unit did not
restart, there was no kernel OOM event, and later host load was low. Those facts
do not identify the restart's cause, so it must not be attributed to Kalshi
without additional evidence.

---

## 22. Current server data rejects broad pure spread scalping

### MEASURED — closed 9h51m server dataset

Dataset `data/server-shadow-20260827-closed.db`, run
`cap-20260827T023541Z-dcee8aea`, 2026-08-27 02:35:41–12:27:03 UTC, 50,038
books, 5,626 trades, size 10. The run ended early on a transient TLS EOF; it is
not a complete day and contains hourly density-scan gaps.

Non-overlapping quote windows produced:

| policy/window | windows | pairs | one-sided | neither | one-sided:pairs |
|---|---:|---:|---:|---:|---:|
| touch / 900s | 8,620 | 11 (0.1%) | 88 (1.0%) | 8,521 | 8.0:1 |
| inside / 900s | 8,620 | 21 (0.2%) | 140 (1.6%) | 8,459 | 6.7:1 |
| touch / 3600s | 6,574 | 12 (0.2%) | 48 (0.7%) | 6,514 | 4.0:1 |
| inside / 3600s | 6,574 | 26 (0.4%) | 70 (1.1%) | 6,478 | 2.7:1 |

Completed pairs earned positive gross spread, but they are too rare to define
the economics. At 900 seconds, a realized-exit replay priced 86 of 100 touch
fills for `-$50.9463` total and 236 of 277 inside fills for `-$108.7736`;
14 and 41 exits respectively remain unknown. The exit replay is not on the
same non-overlapping sampling clock, so these totals must not be subtracted
from pair edge as if they formed one portfolio. Directionally, however, both
instruments agree: broad pure spread scalping creates inventory much more often
than it captures both sides, and getting flat is adverse.

### INFERRED — reward may rescue selected markets, but this is not net yet

The current-rule same-clock proxy for the audited Polymarket entry policy,
size 10 and `$300` modeled capital, selected 30 markets and reported 93.1%
uptime, 201.3 partial fills/day, `$28.36/day` modeled reward,
`-$9.75/day` 300-second markout, and `+$18.61/day` proxy. Reward-only selection
of 20 markets reported `$25.385/day` after minimums on `$189.30` collateral.

These positive figures are **INFERRED**, not profitability: they extrapolate
partial program coverage, include sparse hourly candidate samples, use markout
instead of realized exit, omit maker/exit fees, and do not bound unknown exits.
The corrected current-policy exit replay found 106 fills, priced 92 for
`-$54.8268` total, and left 14 unknown. A fixed-universe replay that puts
reward, pair completion, realized exits, and unknown bounds on one clock is
still required.

### VERIFIED — retry-hardened replacement capture started

Commit `b97065485cbcf10b6c7c0a34d23c0d8c090e4f5e` passed the read-only endpoint
scan and all 27 tests on the server. Replacement run
`cap-20260828T003459Z-44ea69de` started at 2026-08-28 00:34:59 UTC as
`kalshi-readonly-capture-14d-r2`, with the same 20% CPU quota, 256 MB memory
limit, five-read/s limiter, and separate database/log. The Polymarket process
was absent and was not touched. This verifies deployment and start, not yet
survival of a real transport failure.

### VERIFIED — host reboot stopped R2; R3 restarted from a fresh database

The host shut down at 2026-08-28 01:22 UTC and booted again at 01:24 UTC.
Systemd recorded R2 stopping cleanly with an 87.6 MB memory peak and no kernel
OOM event. Because R2 was a transient unit, it no longer existed after boot;
this was a host-lifecycle interruption, not a recorder exception.

After all 27 tests and the read-only endpoint scan passed again at deployed
commit `b970654`, run `cap-20260828T021706Z-2e9d1d6b` started at 02:17:05 UTC
as `kalshi-readonly-capture-14d-r3`. It uses the same 20% CPU, 256 MB memory,
five-read/s, 75-market, 60-second-sweep boundaries and writes a fresh database
and log. At 02:19:17 UTC it was active as PID 3898 with zero restarts; the
database quick check was `ok`, 450 book rows, 17,069 program rows and one
exchange-status row were present, and zero errors were recorded. The live
Polymarket trader remained PID 2251 across the R3 start.

### VERIFIED — R3 survived a real transient network failure

At 2026-08-28 10:27:03 UTC, R3 logged an attempt-1/3 `URLError` caused by a
connection reset by peer. At the 12:58 UTC inspection it retained PID 3898 with
zero restarts and no traceback, its newest book was about 11 seconds old, and
the database had zero recorded errors and zero non-200 book rows. The bounded
retry fix has therefore survived a real transport interruption of the same
general class that ended the first capture. This verifies recorder resilience;
it does not turn the partial capture into profitability evidence.

---

## 23. Measurement relocated to the operator's laptop

### VERIFIED — identical tracked state and isolated Kalshi runtime

The former server was destroyed by the operator, so R3 is no longer running and
its unmirrored data cannot be treated as part of the new continuous window.
Under accepted decision D-009, exact commit
`0043c3aa1b1fbf51bc1a951bc391cf7b4c119953` was installed on 2026-08-29 UTC
at the standalone laptop WSL path `/home/polybot/kalshi-bot`. That commit matches
this PC and GitHub `main`; the laptop checkout was clean. The deployed collector
scan found no account, order, or write endpoint, all 27 tests passed, and both
collector modules compiled.

The laptop presented 16 logical CPUs, 15,545 MB WSL RAM with 14,782 MB
available, and 952 GB free inside WSL. Windows AC sleep and hibernation are
disabled by the active `Server Mode` plan. The collector remains capped at 20%
of one CPU and 256 MB memory; the laptop must remain plugged in because its
battery power policy can still suspend it.

### MEASURED — laptop canary and R1 start

The two-minute canary `cap-20260829T033425Z-33ba5758` ran from 03:34:25 to
03:36:37 UTC and closed cleanly with 70 books, 2,189 trades, 16,859 program
rows, five market-metadata rows, one exchange-status row, zero errors, zero
non-200 book rows, no traceback, and SQLite quick check `ok`.

Long run `cap-20260829T033905Z-a7cc8324` started at 03:39:05 UTC as systemd unit
`kalshi-readonly-capture-14d-laptop-r1`. At the 03:44 UTC check it remained PID
785 with zero restarts and held 1,094 books, 5,407 trades, 16,859 program rows,
75 market-metadata rows, zero errors and zero non-200 books; quick check was
`ok`. The initial density scan found 757 two-sided candidates among 5,379 and
took 210 seconds. This is operational verification, not profitability evidence.

A consistent SQLite online-backup checkpoint at 03:44 UTC contained 1,139 books
and 5,477 trades and passed quick check. It and the matching log were copied to
this PC as ignored files under `data/`. Runtime data is intentionally not stored
on GitHub; code and documentation are synchronized by Git commit instead.

---

## 25. Official API contract snapshot — 2026-09-19

**VERIFIED from published documentation, not live account behavior.**
`docs/KALSHI_API_REFERENCE.md` consolidates 240 pages discovered through the
official `https://docs.kalshi.com/llms.txt` and sitemap, three OpenAPI specs,
and two AsyncAPI specs. It includes 191 REST operations (116 Predictions,
48 margin, 27 clearing-member), 423 shared components, 23 WebSocket channels,
63 WebSocket operations, and technical material from all 20 FIX pages.
The CF Benchmarks passthrough is documented outside the OpenAPI operation count.
All 247 sources retrieved; no schema reference is unresolved. Manifest and
verification audit are next to the Markdown.

Current order writes use `/portfolio/events/orders` and YES-frame bid/ask
pricing. The documentation also specifies fractional fills, per-band price
grids, token-based rate limits, six-decimal fees with rounding rebates, and
shard-specific routing/collateral. Old project assumptions are not live API
contracts. Exact source links and implementation cautions are in the reference.

Eighteen operation/page differences are `x-mint` presentation metadata; one
component difference is a trailing newline. Both versions are preserved.
A separate narrative discrepancy remains: FIX connectivity says RFQ quote
accepts use the unscoped Write bucket, while the rate-limit guide says shard 1.
The changelog includes a future September 24 entry even though retrieved on
September 19; that entry is not evidence of already-deployed behavior.

No credentials were read and no account, order, or transfer endpoint was called.
The WSL ledger had D-009/D-010 and a D-008 clarification missing in the Windows
copy; those existing decisions were preserved when updating documentation.
The local Git repository remains unusable; no commit or remote parity claimed.

## 24. The 12.97-day laptop replay rejects the transferred strategy

**MEASURED 2026-09-14.** Dataset
`data/shadow-14d-laptop-r1-20260829.db` spans 2026-08-29 03:39 UTC through
2026-09-11 02:52 UTC: 1,567,512 books, 41,868 trades, 14 status-599 book
failures, and SQLite quick check `ok`.

The previous sizing report was invalid on this dataset because it assigned the
last program row for each ticker to every earlier book and then summed top
programs from different dates as though simultaneous. The corrected replay:

- matches each book to stable reward program IDs observed and active then;
- excludes 4,287 edited program IDs and 1,234 invalid program rows;
- uses the current July one-fifth rule and Polymarket-current quote policy;
- requires program duration >=1 day, >=80% observed span, and >=100 snapshots
  per observed day, excluding hourly candidate-scan samples;
- integrates a maximum 30-market/$300 portfolio on the actual capture clock;
- quotes only while a selected reward program qualifies on that book.

At size 10, the hindsight-ranked portfolio averages 13.6 markets and $130.45
collateral. Modeled reward is $100.55 over 12.97 days, or **+$7.75/day**. This
is optimistic because selection uses future full-period reward density.

Same-clock whole-fill/queue replay results, including the unverified 0.0175
maker fee-rate estimate:

| passive exit deadline | fills | unknown | central/day | max-loss bound/day |
|---:|---:|---:|---:|---:|
| 300s | 1,104 | 67 | -$30.41 | -$55.91 |
| 900s | 870 | 43 | -$21.12 | -$37.03 |
| 3600s | 603 | 13 | -$7.36 | -$11.65 |

At 3600 seconds with maker fees forced to zero and all unknown exits valued at
zero, combined P&L is still **-$4.98/day**. Charging unknown exits at maximum
terminal loss gives **-$9.24/day**. Since the favorable bound is negative, the
Stage 1 stop gate is met: do not build the Polymarket strategy transfer or
collect more of the same data. This does not establish that every possible
Kalshi reward strategy is unprofitable; it rejects this measured policy,
selection method, size, and tested exit family.

## 7. Open questions

1. **`period_reward` scale** — confirm 1e-4 against an actual payout. Everything in
   section 4 depends on it.
2. **Pro fee schedule** — exact maker/taker rates with the Pro discount.
3. **Does a fill on one side end both sides' accrual in practice?** The rules say the
   snapshot needs two-sided liquidity; they do not say your *own* orders must be on
   both. Re-read: your score sums normalized yes + normalized no, so a one-sided quote
   still scores — provided *someone* holds the other side to Target Size. This changes
   invariant 4's rewrite substantially. **Resolve before designing the fill policy.**
4. **Post-only order support** — not yet confirmed in the Kalshi API. Without it the
   reconciler's `PLACE_POST_ONLY` has no venue primitive.
5. **Rate limits** — separate read/write token buckets; `GET /account/limits` reports
   live refill rates. Tier-dependent, needs an authenticated read.
6. ~~Whether reward density is stable enough over a Time Period to rank on.~~
   **ANSWERED 2026-08-18 in section 11.** Stable enough to rank on — first-half
   vs second-half Spearman +0.818, 73% of markets within 2x — but re-measure
   continuously: a quarter of the top 12 rotates out within hours. Established
   over ~10 hours only, not over a full 7-14 day period.

---

## 8. Recommended order of work

1. Port `shadow_run.py` + `shadow_store.py` first. Read-only, zero risk, and it
   answers Q1, Q3, and Q6 with real Kalshi data.
2. Resolve Q4 (post-only) — it is structural for the reconciler.
3. Only then port the economics, and only then the execution path.

This is the same order that got liquidity-bot to a working state. Do not skip the
shadow phase: every number in section 4 is a single instantaneous snapshot.
