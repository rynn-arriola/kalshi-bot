# Market ranking: Polymarket lessons, Kalshi adaptation

Date: 2026-09-21. VERIFIED CODE/OFFLINE unless explicitly marked proposed.
This completes the requested reference audit, not ranking/admission integration.
No strategy, configuration, runtime or live account was changed. Proposed
selection policy below awaits the operator's decision under D-022/D-003.

## Executable reference

Read-only source: `C:/Users/rynna/Bots/liquidity-bot`, final inspected HEAD
`ab26a2182ab93077cadbd7d8429954bb7a753f67`. The reference had unrelated edits
at first inspection and advanced during this audit; the ranking files below
have no final diff against that HEAD. These are local code observations, not
verification of deployed behavior. Its newly prepared risk settings are not
Kalshi policy.

| Source in `src/liquidity_bot/` | Verified behavior worth adapting |
|---|---|
| `market_selector.py`: `_candidate_key`, `_opportunity_key` | Cheap preliminary ranking, then detailed book-based projected reward ranking. Viability and sports phase precede projected reward; headline pool alone is not the final score. |
| `market_selector.py`: `_select`, `_detailed_candidates` | Filter metadata before expensive book work; bound detailed candidates; retain strong candidates and rotate a discovery tail. |
| `market_selector.py`: `revalidate_viable` | Refresh cached candidates, recheck time after awaited reads, propagate throttling instead of treating it as a bad market or starting a bigger scan. |
| `selection_books.py`: `SelectionBookSource` | Share a bounded full-book WebSocket scope; stale/missing stream data may use the budgeted REST fallback. |
| `live_commissioning.py`: `_owner_is_flat_and_clear`, `_replacement_candidates_for_top_up` | Release only owners without positions, working/absent orders or unresolved intents; revalidate a small replacement shortlist. Preserve inventory management. |

Do NOT copy:

- Sports/day-of preference, league reward priors, touch quoting, spread/price
  filters, refresh/idle durations or numeric risk settings. These are Poly policy.
- `fill_hazard.py`'s calibrated probabilities as Kalshi trading-loss estimates.
- The economic-gate override's positive floor as a meaningful net-profit score.
  In the inspected code, non-quotable economics can be clamped to `1e-9`;
  `_opportunity_key` therefore uses projected reward first within a phase.
- `projected_reward_total` sums reward-eligible projections, not specifically
  `viable_sides`. Our admission score must describe the exact admissible quote
  set, never reward from a side we will not actually quote.
- Full active-stream teardown/rebind during discovery. Poly itself defers
  disruptive discovery around inventory deadlines; Kalshi should keep existing
  book/position owners running while bounded background discovery proceeds.

## Existing Kalshi foundation: reuse, do not rebuild

[Quoting](../src/kalshi_bot/quoting.py) already computes reference quotes and
own-share arithmetic using Decimal, actual target/discount and tick bands.
[RankingBoard](../src/kalshi_bot/ranking.py) already provides separate gross
hourly, remaining-period and capital-efficiency views, freshness invalidation,
inventory blockers and deterministic ordering. It does not allocate markets.
Keep its conservative cap/unsupported-grid blockers and avoid summing
incompatible overlapping programs. Net profit remains unknown, not zero.

Current official sources rechecked on the audit date:

- [Scoring rules](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program):
  reference depth is one fifth of target, not a fixed tick distance from BBO.
  Full price weight is not the whole reward pool: competition changes our share.
  Both sides must reach target; excluded snapshots reduce payout. An unchanged-
  book hourly projection assumes continued qualification, not measured uptime.
- [Payment explanation](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them):
  final rewards below $1 per individual program are not paid. Event-level totals
  can combine markets. A displayed estimate is not a paid credit.
- [Incentive API](https://docs.kalshi.com/api-reference/incentive-programs/get-incentives)
  and the local [operation/schema reference](KALSHI_API_REFERENCE.md): definitions
  include exact market, dates, pool, target, discount and optional account cap;
  this response does not provide personal accrued earnings. Preserve centi-cent
  conversion and complete bounded pagination. Use the existing shared REST
  budget for these missing stream fields, not another poller.

## Recommended selection policy — PROPOSED, not activated

1. **Eligibility before score.** Require fresh book/program/market proof, reviewed
   event/exit timing, executable tick/quantity rules, both target depths,
   account/risk authority and sufficient exit evidence. Unknown authority blocks
   new entries; missing data is not a low numeric score. Exit stress and fees
   should be visible separately; do not invent a fill probability or net return.
2. **Rank estimated gross dollars/hour from our feasible quotes.** Use size 10
   at Kalshi's reference prices, competition including our own orders exactly
   once, and actual program duration. Prefer higher capital efficiency on equal
   hourly reward, then stable ticker/program identity. Display remaining earning
   time and gross remaining reward separately, capped by the permitted entry
   horizon as well as program end. This is a greedy priority rule, not proof of
   globally optimal portfolio allocation or future profitability.
3. **Admission is a separate transaction.** Refresh/revalidate the chosen row at
   consumption and through existing dispatch fences. Check actual order cost,
   working/uncertain commitments, $500 capital, $300 portfolio exposure, $90
   market exposure and ratcheted caps. Thirty resting entries allow at most
   fifteen two-sided markets before other constraints; that is not a target.
   If the accepted percentage reducer changes entry size, recompute reward and
   cost for that actual size before admission; never retain a size-10 score.
   An unaffordable row does not reserve fictional capacity. Leave unsupported
   one-sided allocation as a separate policy rather than quietly dropping a leg.
4. **Stable occupancy initially.** Fill available capacity, retain healthy
   incumbents and replace an ineligible/ended owner only once positively flat
   and clear. Do not liquidate inventory or churn quotes just to improve rank.
   Better-score displacement thresholds and economic-idle timers need a later
   explicit policy; safety revocation never waits for a ranking timer.
5. **Expose payout uncertainty.** Show the per-program $1 feasibility warning,
   remaining projection, qualification assumptions and unknown accrued amount.
   Do not apply a new minimum-profit hard gate or combine unrelated programs
   to imply payment. Retain the existing block for unsupported account caps.

Alternative: capital-efficiency-first admission can favor tiny earnings while
using scarce order slots. Remaining-reward-first can favor long programs over
better hourly opportunities. Recommend hourly-first for this initial fixed-size,
two-sided strategy; show both alternatives as report views.

## CPU/transport implementation direction

Reuse existing long-lived public-book shards and metadata/account owners.
Coalesce *ranking recomputation* per dirty ticker, never discard ordered book
deltas or private events. Cache per-market/program results; sort only a bounded
board when admission/reporting needs it. Use a bounded discovery watch set with
a strong head and rotating tail, separate from inventory subscriptions.

Program refresh and detailed candidate discovery are background shared-budget
work; safety, fills and exits preempt them. A 429/deferred budget stops discovery
without triggering full-catalog fallback. Recheck generation/revision/freshness
after awaits. A board row or cached shortlist never grants trading authority.

Next implementation, after the policy decision: connect the existing ranking
board to bounded discovery/revalidation and an advisory admission proposal;
route accepted proposals through existing writer/capacity/dispatch owners.
Before coding, specify concrete queue/subscription bounds and latency budgets
against the existing 30/120-market fixtures. This audit is not a completed
performance design or an optimization benchmark.

Required integration regressions: smaller pool beats crowded larger pool;
different duration; own-liquidity reflection; infeasible side not counted;
expiry/metadata change during await; slot/cash/ratchet contention; UNKNOWN
orders; inventory never orphaned; missing/capped/overlapping programs;
per-program payout warning; 429 without scan amplification; stable ties;
bounded dirty-market bursts while exit deadlines remain serviced.

## Verification and limits

- Poly `test_market_selector.py` + `test_selection_books.py`: **56 passed**,
  2.437 seconds. Kalshi `test_bot_engine.py`: **68 passed**, 2.545 seconds.
- Native Windows virtualenv Python, `-B`, process-local `src` import path.
  Tests use synthetic books/fake gateways; test-process socket connections were
  denied except loopback needed by Windows asyncio. No venue requests.
- Initial test harness attempts failed: Poly lacked its `src` import path;
  blanket socket denial also blocked Windows asyncio's internal loopback pair.
  Corrected harness reruns above pass; no repository-code fix was needed.
- Full suites, live rewards, deployment behavior and new performance gates were
  not exercised. These tests verify the reference primitives, not the proposed
  integration or profitability. Poly files were not edited by this task.
- Documentation verification: 232 local Markdown links across the six changed
  documents resolved; whitespace/diff review found no unrelated code changes.
