# D-098: entry/exit audit and incumbent maintenance

Prepared September 23, 2026 in an isolated checkout based on `221dacc`.
Production is not deployed/restarted by this work. STATUS owns current state.

## Actual-code comparison

Read-only Polymarket reference: `C:/Users/rynna/Bots/liquidity-bot`,
`acba287f59688bebdb7e8eea934e7af13fed7984`. This is source evidence, not live
deployment/configuration proof. Its 76 pure reconciler tests pass. The first
invocation lacked the `src` import path; the corrected invocation passed without
changing that repository.

| Stage | Polymarket executable reference | Kalshi and this bundle |
|---|---|---|
| Discovery/ranking | `live_commissioning._evaluate_rewards_inner`, `_replacement_candidates_for_top_up` | Retain two broad book shards, missing-field metadata, active programs, $2 priority/$1 fallback, reference pair and 70% retained-value checks. No imported sports-only filter or Poly day-of clock. |
| Entry | `reconciler._flat_plan`, live admission/execution | Existing two size-10 post-only orders, atomic local reservation, non-atomic V2 venue batch. Fresh cash/exposure/fee/timing/quota/source gates remain. |
| Existing quotes | `_flat_plan`, desired-price matching and reward dwell | Add same-program quote maintenance, not higher-rank displacement. Full-weight qualifying quotes at/better than reference stay. |
| Partial fills | `_inventory_plan`, `_passive_inventory_plan` | Preserve actual fill/fee accounting, exact remaining inventory and no building pair. Fix passive cancellation order: building side first, not lexical order ID. |
| Cancel | hard-exit cancel tracking and live reconciliation | One exact target at a time; ACK, absence or timeout never proves terminal/no-fill. Ambiguous outcomes remain durable, without blind retry. |
| Passive exit | `_passive_inventory_plan`, `exit_quote_price` | Exact reduce-only quantity, keep exact touch reducer; otherwise conditional non-crossing one-tick improvement. No losing-position cost-basis floor. |
| Timed deferral | `_inventory_plan` returns to passive management when early crossing is expensive/thin | **Fixed:** `passive_deferred` previously could not dispatch or obtain writer reducer authorization. Keep $8 ordinary loss bound/50% stressed depth, but continue passive creation/replacement and building cancellation. |
| Deadline/IOC | bounded cancel-confirm-IOC path | Keep 900-second ordinary age, verified event-risk minus five minutes/close/explicit flatten deadlines, exact IOC without expiry, three attempts/30-second envelope. No new tiny-residue exception. |
| Loss-scaled cap | `_loss_cap_overflow_order_ids`, `_loss_cap_cancel_action` | **Fixed:** Kalshi's persisted cap blocked additions but did not drain excess resting entries before hard hold. Now cancel owned flat overflow, complete pairs first, stable admission order. Position management/reducers stay separate. |
| Refill/restart | `_owner_is_flat_and_clear`, `_reward_authorization_lost_and_flat`, recovery | Same-market continuation waits for terminal/fill proof and fresh gates. Preserve recovery-only crash replacement and source fingerprint; do not resume a stale maintenance plan. |

Kalshi paths traced: `selection_runtime`, `selection`, `ranking`, `quoting`,
`management`, `orders`, `exits`, `dispatch_sources`, `dispatch`, `execution`,
`writer`, `portfolio`, `risk`, `account`, `runtime`, `live`, `supervision`.
Unchanged full-suite coverage includes accounting, durable loss windows,
shutdown and recovery. No live fill/exit is manufactured for acceptance.

## Implementation contract

`quote_maintenance.QuoteMaintenance` stores bounded subscription-scoped program
bindings and **one** withdrawal/re-entry cycle. It is not another writer,
scanner, process or venue client. Only normal composition attaches it.

- Bind the exact selected program. Join actual orders with the existing
  operational account/queue/book reflection evidence. Unknown reflection,
  missing fees or changed terms is not zero reward.
- Reuse scoring and 70% checks for actual/proposed quotes. Remove proven own
  quotes exactly once; exclude our opposite order from executable exit depth.
- Require 30 seconds of explicitly verified drift before repricing and a
  30-second post-cycle cooldown. D-100 preserves accumulated verified coverage
  through gaps up to 15 seconds without counting unknown time; changed exact
  ownership/program/account generation, a longer gap or a recovered qualifying
  sample resets the dwell. Definite unscoring/depth/value failure without a
  valid repair requires 90 seconds before withdrawal. Unsupported evidence
  never becomes economic failure; known earning deadlines do not wait.
- Cancel through the sole writer, reconcile terminal records/all fills, then
  re-evaluate a fresh same-program pair. Never submit the original cached price.
  A fill hands control back to inventory exits.
- D-117 makes the one cycle's admission restriction market-local. Other markets
  use ordinary ranked admission and shared capacity even while this ticker's
  evidence is missing; no free slots are reserved for its eventual replacement.
  Failed current gates, program end or insufficient remaining cap release only
  a proven-flat owner. Same-ticker replacement still waits for terminal/fill and
  fresh same-program evidence. Exits/account work and the single writer retain
  priority; no overlapping replacement or guessed cancellation is introduced.
- New entries retain $1 projected remaining and $2 priority. A continuation may
  use its own nonconflicting sampled accrued estimate plus remaining projection,
  not estimates from another/changed program. It need not earn another future
  dollar at each reprice. Neither estimated $1 nor a richer spare triggers rotation.
- Priority: safety/overflow cancel, due IOC, passive reducer, maintenance cancel,
  new pair. Durable funding, rate limits, source fences and risk amounts remain.

The existing tracker now exposes bounded per-program sampled gross accrual,
current estimated rate, time to $1, safe remaining time and unknown gaps in
runtime status. Checkpoints preserve estimates, not rate/entry authority.
Maintenance status includes historical sample times, actual prices, reference/
cutoff, blockers and active cycle. Estimates are not paid cash or guaranteed net
profit. Bindings are ephemeral: crash recovery drains durable orders; a later
normal startup follows initial selection rather than blindly resuming a cycle.

## Official contracts and verification

Checked local API operations/schemas and current official
[V2 create](https://docs.kalshi.com/api-reference/orders/create-order-v2),
[V2 cancellation](https://docs.kalshi.com/api-reference/orders/cancel-order-v2)
and [incentive help](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them)
on September 23. Reuse existing endpoints; no invented amend, WebSocket mutation
or earnings API. Minimum payout is per individual program; estimates can change.
Queue/private/public reflection is operational evidence, not an atomic guarantee.

New tests cover retention above estimated $1, drift/unknown/changed terms,
same-program capacity, cancel proof, partial-fill takeover, prepare/send races,
deadline withdrawal, definite versus unknown failures, pair-first cap drainage,
own-depth exclusion and exit priority. Three in-memory reversals each fail the
new deferred-writer, building-first and cap-drain regression without file edits.
Final suite and publication evidence live in STATUS.

Synthetic fixed-source arithmetic: 1,000 representative policy evaluations,
0.28125 CPU seconds, p50/p95/p99 0.231/0.516/0.791ms (target p99<5ms, CPU<5s).
This reuses one fixture; it is not 30 simultaneous real markets. Separately,
100 pathological 4,096-level-per-side evaluations used 10.15625 CPU seconds,
p50/p99 115.5/125.1ms. Deep-book cost remains material, not submillisecond.
The engine yields after each market; reflection also yields between owners and
rechecks subsequent sources. No global scan-speed or live-latency claim.

No production account calls, order actions, database edits/copies, process
controls or restart. Real repricing cadence, cancellation latency and payout/
profitability remain observations after a separately authorized restart. Keep
the active package unchanged until its supervisor is safely stopped/disarmed.
