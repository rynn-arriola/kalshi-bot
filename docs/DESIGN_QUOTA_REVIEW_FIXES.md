# Quota review fixes — Astra design clarification

Date: September 20, 2026. D-040 authorized this design task only.
Historical status: proposed Sol handoff. D-041 subsequently implemented the fixes;
independent [Astra re-review](REVIEW_D041_ASTRA.md) clears the original findings
with two low-priority follow-ups. See
[build evidence](BUILD_QUOTA_REVIEW_FIXES.md). This addendum replaces
the conflicting grant-boundary failure handling in sections 5/7 of
[D-038](DESIGN_QUOTA_FRESHNESS.md) when approved for implementation; other
contracts remain unchanged. [Review findings](REVIEW_D039_ASTRA.md) remain open.

## 1. Evidence and choice

The present code schedules refresh at deadline minus 90 seconds but rejects a
candidate with at most 90 seconds left. An unchanged finite grant cannot pass
at that time. Three failures then prevent the later post-expiry refresh.

Public documentation rechecked for this design: numeric read/write settings and
lane-scoped grants are returned by [account limits](https://docs.kalshi.com/api-reference/account/get-account-api-limits).
The [cost endpoint](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs)
returns the default and exceptions. The [rate guide](https://docs.kalshi.com/getting_started/rate_limits)
describes grants and bucket mechanics, not a client freshness lease or guaranteed
publication delay at expiry. Local exact schemas were read in
`KALSHI_API_REFERENCE.md`: GetAccountApiLimitsResponse, ApiUsageLevelGrant,
ExchangeInstance, BucketLimit, GetAccountEndpointCostsResponse and EndpointTokenCost.
The old design's standalone `api-specs/openapi.yaml` path is unavailable here;
the embedded reference supplies those schemas. Null-expiry ambiguity remains
unchanged. No private account data was requested.

Recommend one bounded deferred recheck at the known grant boundary, without
installing near-expiry evidence or changing the old hard cutoff. This preserves
the >90-second install rule and avoids guessing the next entitlement.

Alternatives not selected: refreshing earlier still returns the same expiry;
accepting arbitrarily short leases needs different anti-spin and publication
rules; ignoring finite grants or assuming a Basic tier weakens evidence gates.
Tradeoff: ordinary REST intentionally pauses at the hard cutoff until a new
fully validated pair installs. The five-second margin plus request latency is
not promised availability; stale server responses or faults can extend the hold.
WebSocket fill persistence and all trading/risk gates remain independent.

## 2. R1 — Distinguish a boundary observation from a refresh failure

Keep current parsing, lane selection, scope/epoch/sequence checks, dual-clock
checks, pair timeout, observation-start age and hard deadline math. Classify only
after ALL those checks. Proposed internal type in `quota.py`:

`QuotaRolloverPending(QuotaUnavailable)` carries a stable reason and immutable
scope/epoch/sequence, finite expiry UTC and corresponding monotonic boundary.
It is a scheduling observation, NOT a lease or successful refresh. No raw grants,
responses, labels or credentials are needed in the exception or diagnostics.

`QuotaGuard.install(candidate)` has three outcomes:

1. Install exactly as before when remaining usable life is greater than the
   refresh lead. Only actual installation resets the supervisor failure count,
   increments its successful completion count and confers read availability.
2. Raise `QuotaRolloverPending` only if the candidate's observation-age deadline
   alone still has more than the refresh lead on both clocks, pair age is within
   its timeout, and a finite relevant grant is the reason remaining usable life
   is at most the lead. The grant's actual expiry must still be strictly future
   on both clocks. This includes the safety-margin interval before actual expiry,
   even though the candidate cannot be used for ordinary requests then.
3. All other rejection remains failure: expired grant (including equality), null
   or malformed grants, invalid second document, stale observation, wrong scope,
   clock fault, auth/transport failure. Never infer a pending rollover from a
   generic exception string or from the previously installed lease alone.

On outcome 2 do not publish the new candidate, increment a fresh revision, refill
tokens, replace observation time or extend the previous deadline. An existing
lease may remain usable ONLY if still fresh and the new candidate has the same
read rate, capacity, default cost, normalized GET overrides and earliest relevant
expiry as that lease. Compare typed values, not tier names. Otherwise revoke the
old read authority immediately using the existing single stale/probe transition;
do not keep an old entitlement after contradictory read evidence. Write settings
remain informational and do not authorize a write bucket. Cold/stale services
remain unavailable. No repeated stale transition may reset tokens or throttling.

The new type also propagates to explicit callers, so none receive an apparent
success for a non-installed candidate. Existing successful summary keys stay
unchanged. Manual guarded mode has no automatic scheduler: callers receive the
typed hold and must not be given a hidden background loop.

## 3. R1 — Bounded supervisor scheduling

Extend the existing single supervisor with one optional immutable rollover record
and one `rollover_used` bit. No new loop, worker, bucket, per-grant cache or task
per market. Catch the typed outcome before generic InvalidData handling.

- The first valid pending observation since a successful install may use the
  one deferral allowance. Set the bit, consume the current request flag and store
  the boundary. Do NOT increment or reset real failures or successful completions.
- The next pair starts no earlier than the grant's actual expiry on BOTH clocks,
  existing retry-not-before, and five seconds after the deferred pair finished.
  The last floor reuses the shortest existing backoff interval to avoid tiny
  boundary gaps; it is a local scheduling rule, not a venue entitlement. Use the
  trusted observation clock mapping, never silently reanchor it. Shared tokens,
  429 pause, slot availability and prior physical-worker drain can delay dispatch.
- Pending rollover overrides the ordinary `deadline - lead` refresh trigger and
  coalesced requests. Still poll/enforce the original hard expiry and clock health.
  Explicit refresh during this wait returns a typed pending hold promptly; it
  does not wait indefinitely or send an early pair. Request storms cannot move
  the boundary, mint deferrals or reset failures/cooldown. Terminal states win.
- When due, consume the record once and start one ordinary owned refresh pair.
  An install clears the bit and failure count. A failure follows unchanged 5/15
  second backoff, three-failure exhaustion and 60-second cooldown. A second
  near-boundary result before installation is a counted failure, not another
  free deferral, even if it names a later expiry. This bounds chains of tiny grants.
- 401/403 still exhaust immediately. Clock fault/stop never starts a boundary
  pair. Expiry never resets an exhausted cycle. Explicit retry retains cooldown
  and the used bit; only a successful install or a genuinely new service epoch
  replenishes the deferral allowance. No restart lease/token persistence.

Bound: at most one non-installing deferred pair in addition to the existing three
failed pairs per automatic recovery cycle: at most four pairs / 24 wire attempts
with the existing three-attempt endpoint ceiling. This explicitly replaces the
old 18-attempt bound only when the deferral is used. Every wire attempt is still
charged to the same bucket. There is no unlimited post-expiry polling.

Expected injected timeline (seconds; idealized transport, not live prediction):

| Time | Action | Ordinary REST |
| --- | --- | --- |
| 0 | Install grant expiring at 300; hard cutoff 295 | Available |
| 205 | Unchanged valid grant produces one pending rollover; zero failures | Old lease only |
| 210, 225 | No retry GETs, no failure-budget spending | Old lease only |
| 295 | Hard cutoff enforced, existing bucket enters probe mode | Blocked |
| 300 or later | One new pair after boundary and all dispatch constraints | Blocked until install |
| Pair completion | Install valid renewal/no-grant/downgrade, or bounded failure | Based on evidence |

A healthy no-grant/long-renewed response at the initial scheduled refresh still
installs normally. The design does not fetch new evidence during the pending wait
just to detect a possible early renewal. Earliest relevant grant still governs
when multiple grants exist; do not reconstruct tier precedence.

## 4. R2 — Cancellation-safe physical ownership

Keep RestReads as the sole physical-work owner. Introduce at most one strongly
retained close/drain task per service; every close caller observes it through a
non-propagating wait. Repeated or concurrently cancelled close calls must refer
to the same drain. Revoke authority/close admission synchronously before awaiting.

Audit joins in `_refresh_quota`, `RestReads.close`, `QuotaSupervisor.close/run`
and their runtime callers. A cancelled observer may receive CancelledError, but
must not cancel the owned pair, worker fetch task or owner drain. Shielding a
temporary gather without retaining its owner is insufficient. Keep task handles
and consume/report unexpected task failures using safe diagnostics; never replace
exceptions with a false successful-close result. No shutdown timeout may erase
physical ownership. Externally owned RestReads is still closed by its caller.

Slots, inflight/control tracking and pair identity remain occupied until the
actual worker returns. Process late 429 before discarding its stale/stopped
payload. No late lease install; no overlap with a replacement pair. Once the
worker drains, normal cleanup releases each resource exactly once. This is local
request ownership, not a promise to cancel a thread/socket or any venue order.

## 5. R3 and test reliability

`QuotaSupervisor.refresh()` must recheck service closure, supervisor liveness,
stop, sticky clock fault and exhaustion before every wait and after wakeup.
Check pending rollover separately as a prompt typed hold. Terminal changes must
notify existing waiters. Capture the current notification event with the state
check on the owning loop without an intervening await, preventing a lost wake.
Never clear cooldown, reanchor clocks, restore quota or charge a market retry.
Once joined to an active pair, preserve its owned drain semantics from R2;
consumer cancellation must not propagate into it.

Investigate the full-suite timeout without assuming its root cause is proven.
Replace reliance on a worker entering within 30 ms with explicit test-owned
barriers and controlled timeout delivery AFTER wire entry. A test-local timeout
wrapper may capture/reschedule the real asyncio timeout handle; do not change
production timeout semantics to make tests pass. Also test timeout BEFORE worker
dispatch as a distinct valid case. Use bounded cleanup and release gated workers
in finally blocks. Repeating tests alone is not a fix.

## 6. File interfaces and implementation assignment

Use existing files: `quota.py` owns validation/classification and revocation;
`quota_supervisor.py` owns the single boundary record, retry accounting and waits;
`rest.py` owns physical drain and typed result propagation. Register one safe
transition event for rollover deferral in `observability.py`; do not log it on
every timer tick. Status exposes pending/used, next-boundary delay and existing
availability/failure fields in O(1), never reports pending as a fresh success.
Only change runtime/metadata callers if required to preserve typed-hold handling.
No new transport, public order API, credential loader or persistence schema.

One proposed Sol fixes assignment, in this order:

1. R1 typed classification, bounded scheduling, diagnostics and regressions.
2. R2 retained cancellation-safe drain and repeated-close regressions.
3. R3 terminal waiter handling and deterministic timeout-test repair.
4. Integration/resource checks, exact full suite, documentation, then STOP for
   independent Astra review. Do not begin a new milestone or enable live trading.

Required additional regressions:

- Exact 205/295/300 timeline, expiry equality, near-expiry bootstrap, changed read
  settings/costs causing early revocation, and unchanged lease not extended.
- Renewed grant, valid lower quota/no grants, multiple relevant grants, other
  lane grants, null/malformed/expired grant, stale pair and second-document error.
- Failure -> deferral -> failure preserves count; second deferral counts failure;
  auth/exhaustion cannot be reopened by expiry; explicit retry keeps cooldown/bit.
- 1,000 notifications/manual requests during deferral make no early GET; 429,
  saturation and slow drain delay but never multiply the boundary pair. Deadline
  passing during a pair or laptop-resume clock changes never restores old proof.
- Pair timeout -> cancelled close -> repeated close with gated worker: tracking
  remains until release; late 429 applied; no overlap/late installation/leaks.
  Cover both direct REST and supervisor/runtime stop paths, including repeated
  cancellation while close is already draining and worker exceptions.
- Clock fault, service close and supervisor stop while an explicit refresh awaits
  cooldown all finish with typed errors and no new GET. Preserve unrelated holds.
- Demonstrate the grant-boundary and cancelled-close regressions fail when each
  fix is temporarily reversed in memory; restore guards before final verification.

Keep D-038's predeclared 30/120 resource and 10-second idle budgets unchanged.
Add a rollover stage to the injected fixture: one deferred pair plus one boundary
pair (four fault-free GETs beyond bootstrap), independent of market count; zero
GETs between these pairs, at most one owned pair and one boundary record, zero
leftover tasks after actual drain. Preserve shared priority and D-036 fixtures.
Report CPU/memory/lag/tokens as before and label any fixture without feed ACKs.
Run focused suites repeatedly and the exact complete suite after the final code
edit; report every failure and its disposition rather than only passing reruns.

## 7. Gate and verification limits

Design only: no implementation, tests, benchmarks or preflight run this turn.
Current source was inspected and public docs rechecked. Previous review's one
full-suite error and three findings are still unresolved. Git metadata remains
unavailable; no verified diff/commit coverage. No credentials, account calls,
live sockets/orders/cancels, ledger changes, Polymarket edits or risk changes.

STOP HERE. Operator switches to 5.6 Sol and approves this correction for the
fixes assignment. Recommendations here are not production probe settings or
permission to run the bot. Independent Astra re-review is required afterward.
