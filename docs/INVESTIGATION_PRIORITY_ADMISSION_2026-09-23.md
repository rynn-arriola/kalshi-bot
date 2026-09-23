# Priority admission investigation — 2026-09-23

Status: investigation complete; recommendation only. No bot code, configuration,
order, ledger or runtime operation changed. Kalshi source: `bef23eb`. Polymarket
reference: `c4e8af20136e0b66b4f57e619c7e6eba0b6a7c42`, inspected read-only.

## Verified mechanism

`InitialRankingCheckpoint.evaluated` records that each ticker was evaluated at
least once. It does not retain prices, candidate tiers or simultaneous freshness.
`RuntimeSelection.invalidate` removes both the dispatch proof and the selector
row. `RecoveryRuntime._revoke` invokes that invalidation across the scope on an
account revocation. Metadata expiration and other source gaps also invalidate
rows. The normal selector correctly sorts current $2 rows ahead of $1 rows, but
cannot prioritize a deleted historical $2 row for refresh.

Using the real `CombinedRankingTests` fixture and a temporary synthetic ledger:

1. Publish C at $2.4752475 remaining and A at $1.4851485. Proposal is C, A.
2. Invalidate C without changing either market's price or reward. Coverage stays
   complete; proposal becomes A alone.
3. Refresh C from the still-valid fixture inputs. Proposal returns to C, A.

All three outcomes were asserted; no mutation occurred. This proves a mechanism
that can admit fallback without freshly disproving known priority candidates.
It does not reconstruct every generation-76 admission or prove that all 38
priority markets from the older census were simultaneously eligible at entry.

Generation 76's 155-second first pass exceeded the 60-second metadata lifetime.
The four outer metadata workers are not four network readers: live `RestReads`
uses default concurrency two and reserves one slot from background requests;
metadata/incentives/reflection therefore share at most one background request.
`ExitInputService` additionally has a two-slot dependency semaphore. Raising the
outer worker count alone cannot remove those limits. Account revalidation and
five-second selection leases also constrain current candidate availability.

Two integration details must be included in any repair:

- `_ranked_entry_turn` returns before `selection.propose` until the checkpoint
  is ready, although `propose` owns early priority-capacity release. Direct
  proposal tests do not prove this path is reachable in normal runtime.
- `_initial_progress` returns whenever the gate has any reason; after early
  priority release it stops adding coverage, despite the checkpoint supporting
  progression to complete coverage. Test the actual runtime path, not only the
  checkpoint object.

## Evidence corrections

The complete public census ending 12:56:09 Eastern found 286 market-gate passes,
including 38 $2 candidates, among 1,024 sequentially sampled markets. It predates
generation 76 and assumes a hypothetical flat account; it is not its admission
slate. The later claim of a complete current 5-priority/10-fallback split was
not established by the recorded tool output. The best sampled owner projection
in that follow-up covered 11 markets: four priority and seven fallback, with
the other four unresolved in that sample. Full price weight does not establish
a $2 remaining projection. Preserve these distinctions in operator reports.

The earlier 10–30-second refresh estimate and 20–30-second suggested deadline
were unmeasured. A $2 projection alone does not establish higher fill risk.

## Recommended design

Keep the four book shards and existing broad reviewed scope. Separate a bounded
advisory discovery record from short-lived trading permission. Retain each
market/program's last observed tier, rate, horizon, blockers, timestamp and
source versions after temporary account/metadata loss. Expired records only
schedule refresh; they can never authorize a quote. Definitive program expiry,
changed scope/rules and newer observations retire or supersede old hints.

On startup or a vacancy, prioritize existing inventory/order maintenance first,
then revalidation of promising $2 candidates, then optional exploration. Start
with a refresh batch sized to twice the available pair slots (at most 30 for
the present cap). This is a dynamic work batch, not a fixed daily market pool.
If it cannot supply the required slots, advance through the remaining known
priority candidates while keeping broad discovery progressing within its budget.
Recompute competition, references, horizon, economics and account capacity before
each pair; retain current dispatch/writer checks and one mutation owner.

Admit valid $2 candidates before fallback. Allow $1 fallback only after the
current selection pass has resolved known higher-tier candidates as admitted or
ineligible and completed its required discovery coverage. Timeout, quota hold or
missing evidence means pending, not ineligible: defer fallback and expose the
reason. A bounded pass may end with empty slots and resume later; it must not
loop indefinitely or reset retry budgets. No live system can guarantee a global
optimum while competition changes, but this removes silent fallback caused by
forgetting promising candidates.

Retain qualifying incumbents under current policy. Changing this admission path
will not immediately replace the existing fallback orders. Use natural vacancies
or a separately authorized future restart for a new initial slate.

Preserve shared account-read priority and rate limits. Initially reuse current
network bounds and bulk metadata; measure candidate refresh time and quota load
before increasing actual REST concurrency. Do not simply lengthen freshness.
Record discovery coverage, current eligible counts, pending priority count,
actual admitted tier/projection and explicit fallback reason. Admission evidence
must survive subsequent proposal overwrites so the selected composition can be
audited without treating a later estimate as its original entry score.

## Alternatives and tradeoffs

- More book shards: no demonstrated solution to lost rankings or serialized
  metadata dependencies; retain the measured four-shard topology.
- More REST workers alone: may improve latency, but still loses priority history
  and increases quota contention. Consider only after targeted measurements.
- Longer freshness: could enlarge the current board but weakens evidence rules;
  not recommended as the repair.
- Fixed top-30/50 pool or timeout-to-fallback: can ignore unresolved $2 markets
  outside the batch or reproduce the same failure when refresh is delayed.
- Remember and revalidate priority candidates: reuses existing owners and Poly's
  practical pattern. Costs bounded state and possible empty slots while evidence
  is unavailable, with an explicit explanation for each deferred fallback.

## Reference and API checks

Polymarket `market_selector.py` retains an economically ranked head and rotating
tail in `_detailed_candidates`. `revalidate_viable` refreshes a bounded cached
set. `live_commissioning.py::_replacement_candidates_for_top_up` overfetches up
to twice the wanted slots and avoids full-scan amplification on throttling. Adapt
that separation, not its sports filters, numeric settings or teardown behavior.

Official Kalshi docs checked today support filtered event batches with nested
markets/milestones and lifecycle/fee update messages; incentive definitions
remain available through their documented REST endpoint. Existing bulk reads
already use this event capability; a second scanner is unnecessary:

- [Events](https://docs.kalshi.com/api-reference/events/get-events)
- [Lifecycle](https://docs.kalshi.com/websockets/market-and-event-lifecycle)
- [Incentives](https://docs.kalshi.com/api-reference/incentive-programs/get-incentives)

## Verification before implementation can be accepted

Current selection/checkpoint/bulk-input suites: 79 tests passed in 5.055 seconds.
The separate synthetic reproduction above passes without venue calls. No claim
is made that a proposed repair or its latency has been tested.

Required repair tests: early $2 expires before a late $1 arrives; private-account
revocation between pairs; priority capacity through the actual runtime loop;
coverage continuing after early release; insufficient first batch with priority
candidates in later batches; timeout/429 remaining pending; changed program or
economics; restart revalidation; scarce cash/slots; incumbent retention; bounded
memory/network work; safety priority. Measure selection-to-first-pair and
selection-to-full-cap latency separately from initial book delivery.
