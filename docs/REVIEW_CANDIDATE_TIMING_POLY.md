# Candidate timing: executable Polymarket reference and Kalshi adaptation

2026-09-22. Research/design result; the qualification changes below are proposed,
not implemented or evidence that the bot is ready to launch. No live runtime,
credentials, account reads or orders were used. Polymarket was read only.

## Diagnosis and fresh evidence

Kalshi HEAD `13539bc`; Polymarket reference HEAD
`b9ac0981e1780d4f99f97200ba0956978a273776` in the adjacent `liquidity-bot` checkout.

The production preparation loop requires one future **primary** milestone,
then rejects every `can_close_early=true` market. The old saved launch inputs
contain 1,024 automatic early-close approvals withdrawn by `46ed45a`; current
validation correctly rejects that file. Refresh does not repair this by itself:
the current automatic path produces no candidates. The prior software-readiness
statement did not establish input readiness.

Public enumeration completed at 2026-09-22 19:58:01 UTC:

| First exclusion | Markets |
|---|---:|
| No future primary milestone | 1,943 |
| Multiple future primary milestones | 38 |
| Milestone within five minutes | 2 |
| Unreviewed early-close condition | 2,878 |
| Accepted | 0 |

Six inactive/capped incentive rows were separately excluded. Counts vary with
the catalog and are first-failure counts, not independent overlapping tests.
Matched milestone types included table tennis, company reports, economic and
other one-off events. A blanket sports solution cannot approve this whole set.

A separate, **incomplete first page** of 500 future Sports milestones showed
the Washington–Detroit baseball milestone
`26194a44-78b3-4ea6-a360-86e8086c50f9` with four primary event tickers and 40
related event tickers. Related-only scope includes first-five innings and
other markets. This proves the current binding method omits documented links;
it does not prove those markets currently have rewards or acceptable rules.

An actual table-tennis example, `KXTTELITEMATCH-26SEP221620RGAKPI-RGA`, has a
winner-based rule and early closure after a winner is declared. Its primary
milestone `1577a7c9-c8ea-517c-99aa-3aac318bfbb3` starts at 20:20 UTC. Public
live-data returned matching milestone/type and `status=not_started` /
`match_status=not_started`. Its provider `updated_at` was 17:38:09 UTC:
successful retrieval alone does not resolve provider freshness semantics.
The market's `occurrence_datetime` was 23:20 UTC and its close was seven days
later. Neither is a substitute for the verified match-start deadline.

## What Polymarket actually does

Source paths below are relative to the adjacent Polymarket checkout:

- `src/liquidity_bot/models.py:73`: executable structure requires
  `sports_market_type_v2` to identify supported moneyline markets.
- `src/liquidity_bot/adapters.py:175`: structured game time is required where
  requested; an explicitly formatted question clock may only tighten it.
- `src/liquidity_bot/event_guard.py`: exact parent membership, observed
  pregame/started/unknown state, shared batched reads and 30-second fetch
  freshness. Positive started state is retained in the ledger and cannot be
  undone by a later contradictory pregame response.
- `src/liquidity_bot/live_orders.py:286`: rechecks event eligibility immediately
  before creating new exposure after admission waits; reducers are separate.
- `src/liquidity_bot/commissioning.py:165` and `reconciler.py:741`: five-minute
  pre-event boundary. `entry_expiry.py` additionally limits entry lifetime to
  the earlier of configured short lifetime and pre-event cutoff.
- `src/liquidity_bot/market_selector.py:758`: metadata eligibility before book
  work; bounded ranked-head/rotating-tail discovery; final opportunity ranking
  uses reward projection. Day-of priority and historical priors are Poly-specific.

Kalshi already has bounded discovery, WebSocket competition-aware ranking,
program end times and a five-minute event deadline. Reuse these components.
Do not copy Poly's market-type strings, reward periods, historical yield priors,
provider status fields or numeric economic thresholds into Kalshi.

## Recommended Kalshi change

Replace blanket early-close exclusion with a bounded registry of reviewed
market-rule families. The rule review is reusable; current exact market rules,
event membership and time still have to match on each admission. Unknown or
changed rules remain excluded with a specific reason. Merely finding words
such as 'winner' or 'released', a ticker prefix, or a rules hash is insufficient.

1. **Resolve timing by market family.** Begin with explicitly reviewed scheduled
   event contracts. Match event/participants, full rule pattern and settlement
   exceptions to the official milestone. Accept related-event links only when
   the reviewed family binds that contract to that occurrence. Missing and
   ambiguous timing remain unresolved; no fallback from expiry or title guesses.
2. **Check real event state where supported.** For sports, validate the actual
   Kalshi live-data schema per supported type and the freshness contract. A
   known start tightens the deadline permanently. Missing, contradictory,
   stale or unsupported state blocks new entries, while inventory management
   retains its existing authority. Do not label an open market 'pregame'.
3. **Keep existing exits and ranking.** The effective earning window ends at
   the earliest of program end, market close and verified event cutoff.
   Rank eligible candidates using current Kalshi score share, hourly reward,
   capital use and existing exit-depth checks. Estimated rewards stay estimates.
4. **Reuse current ownership.** Put binding/review logic in candidate preparation
   and metadata validation; share event evidence by milestone through the
   existing read budget. WebSocket lifecycle changes invalidate state; bounded
   REST obtains fields not supplied by that feed. Recheck evidence at the
   existing dispatch source boundary. No separate scanner or per-market loop.
5. **Make exclusions visible.** Empty preparation must return bounded counts
   and examples for early-close review, missing/ambiguous timing, event state and
   unsupported rules. The current generic 'no ... future primary milestone'
   error is misleading when early-close review is the decisive failure.

This is not a proposal to make Kalshi sports-only. Scheduled economic releases
can have a separate reviewed adapter; rolling thresholds, announcements that
can happen at any time and unsupported tournament structures cannot borrow a
match-start rule. The first supported family set and event-state freshness
contract must be explicit before changing automatic qualification. Keep all
approved capital, order, inventory and loss limits.

## Implementation and acceptance

Affected components: `candidate_preparation.py`, `market_inputs.py`, shared
REST/metadata scheduling, entry source checks and, if observed-start state is
introduced, its durable owner. Preserve schema/restart compatibility explicitly;
do not improvise a second account writer. Diagnostics belong in the existing
bounded schema and launcher output.

Tests must cover reviewed versus unknown early closure, rule/participant
mismatch, related-event ambiguity, schedule conflicts, earlier actual starts,
stale/contradictory live data, restart persistence, evidence expiry during
dispatch waits, T-5/program-end cutoffs and zero-candidate diagnostics. Verify
bounded shared fetches and preserve existing ranking/regression results.

Final acceptance must rerun **the real public preparation path with the new
code** and report qualified counts and remaining exclusions. Synthetic tests or
an old successful refresh cannot substitute for this. A nonempty candidate
list still is not fresh account readiness, profitable books or live acceptance.

## Official contracts checked

- [Market definitions](https://docs.kalshi.com/api-reference/market/get-market):
  rules, early-close flag/condition and distinct market timestamps.
- [Targets and milestones](https://docs.kalshi.com/getting_started/targets_and_milestones):
  primary versus related event membership and type-specific details.
- [Milestone](https://docs.kalshi.com/api-reference/milestone/get-milestone):
  identity, type, start and event bindings.
- [Live data](https://docs.kalshi.com/api-reference/live-data/get-live-data):
  milestone-keyed response; `details` is flexible, not a universal typed pregame
  freshness guarantee.
- [WebSocket lifecycle](https://docs.kalshi.com/websockets/market-and-event-lifecycle):
  market lifecycle and event-creation notifications, not a documented generic
  real-world game-start feed. Use existing WebSockets for their supported data.
