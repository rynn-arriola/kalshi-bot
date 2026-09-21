# Supervised quota freshness and grant expiry

Date: September 20, 2026. Phase: Astra design ONLY, under D-037/D-038.
Status: proposed implementation contract; no executable changes or new live policy.
Historical design handoff: Phase 1 only. The operator subsequently said
"Implement both" (D-039), explicitly authorizing both phases in one assignment.
Both phases are now implemented; independent Astra review is NOT CLEARED. Its
[R1 finding](REVIEW_D039_ASTRA.md) identifies a conflict between refresh timing
and candidate acceptance at finite-grant expiry. The original contract below is
preserved for history. D-040's [proposed correction](DESIGN_QUOTA_REVIEW_FIXES.md)
is ready for the operator's Sol implementation handoff; it is not implemented.
See also
[build evidence](BUILD_QUOTA_FRESHNESS.md). D-039 supersedes the
separate Phase 2 approval/stop instructions below, not D-037 or live boundaries.

## 1. Outcome and boundaries

Add an expiring, account-scoped lease for the shared Predictions Read budget.
Refresh before expiry; do not keep spending an old entitlement indefinitely.
Keep healthy WebSocket processing independent of quota recovery. REST remains
necessary here because the inspected stream contracts do not supply account
limits, endpoint costs or grant changes. No per-market quota tasks or buckets.

This is not a trading lease. Preserve all account, cash, history, book, logging,
ownership and risk gates. No write transport, tier upgrade, automatic selection,
new live market capacity, launch command, account call or credential loading.
No Polymarket quota assumptions are inherited; the existing component boundaries
and source-verified inventory/risk rules remain unchanged.

Recommendation: strict ordinary-read blocking at expiry, with a restricted quota
probe path. Continuing ordinary reads on an assumed Basic tier would invent an
entitlement; blocking every request would prevent automatic recovery. Restricted
probes accept possible 429s and are NOT proof of a venue-guaranteed minimum quota.

## 2. Evidence checked

VERIFIED from current source, not just project documents:

- `rest.py`: `refresh_budget()` coalesces a limits/costs pair and installs its read
  configuration. It currently does not retain or validate grant expiry, document
  lifetime, account-generation provenance or a freshness lease. `configured_at`
  is installation time, not the beginning of the HTTP observation interval.
- `TokenBudget.reconfigure()` starts empty, preserves the 429 pause and counters,
  and wakes waiters. Keep those properties and the reviewed R1-R4 fixes.
- `RestReads._fetch()` has three attempts, a 30-second logical operation deadline,
  bounded shared admission and worker slots. Caller cancellation does not stop
  already-running blocking I/O. Its ordinary priority classes alone do not
  guarantee a quota refresh admission slot under saturated account reads.
- `RecoveryRuntime` owns engine/readers/recovery/metadata tasks, but not a quota
  supervisor. Entry authority is always false. REST and writer teardown remain
  the caller's responsibility; add no competing owner.
- D-033 diagnostics require registered event codes and bounded safe fields.

Official sources rechecked September 20, 2026:

- [Account limits](https://docs.kalshi.com/api-reference/account/get-account-api-limits)
  returns Predictions read/write settings and grants across lanes. Local exact
  schemas: `GetAccountApiLimitsResponse`, `BucketLimit`, `ApiUsageLevelGrant`,
  `ExchangeInstance` in `api-specs/openapi.yaml`.
- [Rate-limit guide](https://docs.kalshi.com/getting_started/rate_limits): grants
  apply to their lane; absent expiry denotes permanence. Read scope is not per
  shard. Tier labels must not replace the returned numeric settings.
- [Endpoint costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs)
  supplies the default and exceptions; an omitted route uses the default.
- [WebSocket overview](https://docs.kalshi.com/websockets) and the local
  `api-specs/asyncapi.yaml` channel inventory provide no quota-update feed.

UNKNOWN: the source schemas allow a null `expires_ts`, while the guide explicitly
defines only absent expiry as permanent. Do not silently equate null with absent.
No server snapshot version, validity TTL or guaranteed notification of early grant
revocation is specified. A local TTL bounds observation age, not venue certainty.
No fresh private account observation was made for this design.

## 3. File structure and ownership

| File | Proposed responsibility |
|---|---|
| `src/kalshi_bot/quota.py` | Pure bounded document parsing; immutable snapshots/policy; synchronous lease owner and clock checks; typed unavailable error |
| `src/kalshi_bot/rest.py` | Fetch candidates through existing transport, guard every actual attempt, atomically install validated lease/config, reserve quota recovery admission |
| `src/kalshi_bot/quota_supervisor.py` | Phase 2: single coalescing deadline/retry owner, no parsing or second bucket |
| `src/kalshi_bot/runtime.py` | Phase 2: optional explicit supervisor ownership, status/blockers and recovery wakeup integration |
| `src/kalshi_bot/observability.py` | Register safe quota transition/failure events |
| `tests/test_bot_quota.py` | Parser, lease, dispatch, provenance and clock tests |
| `tests/test_bot_quota_supervisor.py` | Phase 2 scheduling/runtime/fault tests |
| `scripts/benchmark_quota_freshness.py` | Offline injected workload/resource checks |

All mutable quota state belongs to the same asyncio loop as RestReads/TokenBudget.
Wire workers return observations only. Never mutate the lease from a worker thread.
No persistence of usable tokens or leases; restart requires new observations.

Data flow: injected policy/scope -> bounded quota GET pair -> typed candidate ->
lease/config commit -> guarded shared GET attempts. Phase 2 adds one deadline
supervisor around that path, not a replacement transport.

## 4. Typed contracts

Names below are proposed interfaces; implementation may use project naming style
without weakening ownership, validation or gating.

- `QuotaPolicy`: explicit maximum age, refresh lead, expiry margin, clock-skew
  tolerance, retry count/cooldown, pair timeout and bounded probe configuration.
  Reject non-finite/negative values and incoherent lead/age/timeout combinations.
- `QuotaScope`: opaque process-local identity binding this service to an account,
  Predictions environment and credential generation. Never log key IDs or hashes
  of private keys. A new signer/account requires a new service; no hot assignment.
- `QuotaCandidate`: immutable numeric read/write configuration, normalized GET
  costs, bounded grant records, observation start/end UTC and monotonic times,
  scope, owner epoch and refresh sequence. No raw responses or credentials retained.
- `QuotaLease`: revision, observation interval, hard UTC/monotonic deadlines,
  earliest relevant grant expiry and safe state/reason. Write data is information
  only; `write_enabled` stays false.
- `QuotaUnavailable(InvalidData)`: stable reason enum, no response/message data.
  Distinguish stale quota from a market failure so callers need not spend market
  or account recovery retry budgets on a known quota hold.
- `QuotaGuard.check(route, control_capability=None)`: synchronous dispatch-time
  check; performs expiry/clock validation and returns the current revision/mode.
  Ordinary mode requires a usable lease. A caller-provided `reason='budget'` or
  arbitrary coalescing scope must never confer the internal control capability.
- `RestReads.refresh_budget()`: retain public explicit refresh compatibility;
  in supervised mode delegate to its sole owner operation. Concurrent callers
  join the same candidate pair. Keep existing summary keys and add quota status.
- `QuotaSupervisor.run()/stop()/close()/request_refresh(retry=False)/status()`:
  Phase 2 lifecycle; constructor performs no I/O. Requests coalesce into one bit.

Keep low-level explicit-budget fixtures supported, but label their quota status
`unmanaged` and never present them as supervised/live-ready. Attaching the guard
is explicit before use; refuse attachment to an already-used RestReads service.
Once attached, direct manual reconfiguration/refresh must not bypass the owner.

## 5. Validation and lease math

Parse complete required limits fields including `usage_tier` and `grants`; do not
derive numbers by ranking tier names. Keep existing integer bounds (including
rejecting booleans), 2,048 cost-row bound and normalized route duplicate checks.
Validate write fields but never create a write bucket. Preserve method distinction;
only GET overrides configure this transport. Bounds are client acceptance limits,
not venue schema guarantees. Proposed grant bound: 128; labels <=128 characters.

Validate every grant's lane, level, source and expiry type. `event_contract`
grants affect this lease; valid `margined` grants do not. Unknown lanes fail closed
pending a contract update. Absent event-contract expiry adds no grant deadline;
explicit null is `grant_expiry_unknown` and blocks installation. Finite expiry
must be a supported positive integer Unix time. Empty grants are valid.

Use the earliest finite expiry among all relevant grants, even a lower-tier one.
This may refresh conservatively but avoids reconstructing the effective tier or
guessing post-expiry capacity. A response still listing an already-expired grant
cannot extend the lease; await corrected evidence with bounded backoff.

Fetch costs then limits sequentially, with a unique `(scope, owner_epoch, sequence)`
coalescing scope. This uses one reserved admission entry and obtains grant evidence
last. Both documents must belong to the same completed local refresh. They are
not claimed to be an atomic server snapshot. Do not reuse a half-successful pair.

Anchor age at the first dispatch attempt of the pair, not completion. At validated
installation, calculate the earlier of observation-start + maximum age and each
grant expiry minus the safety margin. Compute matching monotonic deadlines from
the observation's UTC/monotonic pair. A lease is usable only while BOTH clocks
are strictly before their deadlines. Equality means expired. Installation after
the deadline fails; a late result cannot extend its own validity.

Proposed engineering defaults for approval with implementation: maximum age 300s,
refresh lead 90s, grant safety margin 5s, pair timeout 65s, clock divergence
tolerance 2s. These are local safety settings, not Kalshi requirements. New
candidates must have >90s remaining usable life to install; otherwise enter the
quota hold and retry on cooldown, avoiding near-expiry refresh loops.

Clock regressions or UTC/monotonic drift above tolerance invalidate immediately.
Large advances with consistent clocks still expire normally. On Windows resume,
check both clocks before any new dispatch, regardless of timer delivery. Clock
faults require explicit owner reinitialization with a trustworthy clock; ordinary
reconnects cannot silently re-anchor. No timer can undo an already-sent request.

## 6. Dispatch and recovery without a bypass bucket

Guard checks occur at admission, on every token-wait wake, after acquiring a
transport slot, immediately before enqueueing wire work, and on response return.
Bound pending waits by the lease deadline as well as the operation deadline;
do not depend on the Phase 2 supervisor to enforce Phase 1 expiry. While work is
pending, a shared bounded clock-health wake (at most once/second) also detects UTC
drift; no per-waiter polling task. Idle Phase 1 needs no background clock task:
the next admission synchronously checks both clocks before doing work.
Carry a dispatch lease revision through awaits. Recheck/reacquire if it changes;
do not send under a newly changed cost table using an old debit. Conservative
lost debits are acceptable; no refund that could mint tokens. Cost computation
and debit must use the same revision, with no await between validation and debit.

When ordinary authority expires, wake token and slot waiters so unsent ordinary
work exits with `QuotaUnavailable`. New retries/pages cannot use the expired
lease. A completed ordinary response dispatched under revoked evidence is not
returned as fresh proof. In-flight requests retain their bounded ownership;
late 429s still extend the shared pause even when their payload is rejected.
The final event-loop check authorizes handoff to the blocking worker; revocation
after that point cannot recall the request. Document that in-flight uncertainty.

Control capability permits ONLY GET `/account/endpoint_costs` and `/account/limits`
for the current owner pair, with no query parameters. It is private to RestReads,
not a public boolean to attach to arbitrary reads. Unsupervised direct calls to
these names do not gain reserved admission or stale-mode privileges.

At cold start or expiry, ordinary requests are blocked. Switch the EXISTING bucket
to an explicitly supplied conservative probe configuration, zero its token estimate
once per transition, and preserve spent counters and the longest 429 pause. No
second replenishing allowance. Repeated status checks/retries must not reset refill
time, tokens or the pause. During fresh-mode refresh, control GETs use current
validated endpoint costs. Probe configuration charges both quota routes explicitly.

No production probe rate is silently selected. It must be injected from a dated,
reviewed configuration; a safe small local rate is still not venue entitlement.
For OFFLINE fixtures only, use 10 tokens/s, capacity 10 and cost 10 per quota GET,
starting empty. If a retained verified quota is lower, clamp probe rate/capacity
down and charges up; never silently truncate a cost to fit. An impossible cost
blocks with attention. Stale cost changes can still cause 429s; they are not
magically discoverable before the first probe. No auto-upgrade endpoint.

In supervised mode require at least three in-flight entries and two wire slots.
Reserve one in-flight entry for the sequential quota pair; ordinary work may use
at most total minus one, background at most total minus two. Thus at default 32,
30 background + one ordinary-critical + one control entry fit. Deduplicated callers
do not consume another slot. Refuse unsupported small configurations explicitly.

Give pending control work priority for the next available transport slot and
token turn, followed by critical then background, FIFO within class. Preserve
the background wire reservation. Do not hold a global lock while waiting; do not
preempt a dispatched wire call or release its slot on consumer cancellation.
Queued ordinary slot waiters must not repeatedly get ahead of a pending control
pair. Bound priority tickets by the existing in-flight/waiter limits. No extra
worker or physical connection pool just for quotas. Priority is not a hard latency
guarantee; the pair can time out under blocked I/O and must then fail closed.

Atomic install: validate both documents and candidate scope/epoch/sequence/deadlines
first; then synchronously replace bucket configuration and lease in one loop turn.
No observer may see new numeric limits with an old lease, or vice versa. A stopped,
superseded or wrong-scope candidate never installs. Invalid refresh data does not
alter the last good settings or extend its deadline. A fresh successful refresh
resets tokens to zero and preserves shared throttling, as D-036 already requires.

## 7. Phase 2 scheduling, runtime and failure handling

One supervisor loop, one owned refresh task, one coalesced request flag, and one
timer/change waiter pair. Compute the next wake from refresh-due, hard expiry,
retry-not-before and a <=1s clock-health check. Do not create a timer per grant or
market. Grant scanning occurs only while parsing a candidate; status is O(1).

States: `uninitialized`, `fresh`, `refreshing`, `stale`, `exhausted`, `clock_fault`,
`stopped`. State labels do not replace per-dispatch deadline checks. While refreshing,
the old lease is usable only until its original deadline. A successful new lease
restores read availability, not entries or risk holds.

Three consecutive failed pair attempts, with 5s then 15s backoff and bounded
nonnegative jitter <=20%; preserve a 60s cooldown after exhaustion. Each endpoint
retains its existing maximum of three wire attempts: at most 18 wire attempts per
failed three-pair cycle. All share token costs and 429 pauses. Pair timeout includes
slot/token waits; cancellation cannot orphan an underlying shared wire operation.
Do not start another pair while timed-out owned work is still draining.

An early refresh failure leaves a still-valid old lease usable until expiry.
Malformed/partial responses never extend it. Authentication 401/403 enters attention
without repetitive automatic retries. Unexpected faults propagate to runtime
supervision. After exhaustion, only an explicit control-plane retry can reopen a
cycle; it preserves cooldown/429 deadlines. Socket ACKs, market events and book
ticks do not reset quota failures. Stop is irreversible for that owner epoch.

Wire one optional supervisor to the same RestReads instance used by recovery and
metadata. Reject mismatched services/scopes. Healthy readers start/continue while
quota bootstrap runs; stream fills still reach the durable writer. REST-dependent
recovery and metadata wait on a coalesced quota-availability event, not a busy loop,
and do not consume their own attempt budgets for `QuotaUnavailable`. Preserve
their earlier exhausted states and unresolved evidence.

On a fresh-to-unusable transition, invalidate dependent account reports/plans once,
not once per blocked request; expose the separate quota blocker. On recovery to
fresh, request one ordinary reconciliation only if that worker is not independently
exhausted. Never reset its attempts, metadata exhaustion, risk ratchets or entry
authority. Execution remains disconnected. A future write supervisor must design
cancel/exit availability separately; this read gate is not authority to stop exits.

Runtime stop first revokes quota authority, then stops/cancels the coordinator and
joins its tasks. Late results are discarded by owner epoch. RestReads still owns
and drains actual wire work when its caller closes it; runtime must not also close
an externally owned shared service. Writer and diagnostic shutdown order stays
unchanged. No claim that a local stop cancels venue orders or proves flatness.

Diagnostics: register `quota_refresh_started`, `quota_fresh`, `quota_stale`,
`quota_retry`, `quota_exhausted`, `quota_clock_fault`, `quota_stopped`. Log transitions
and bounded attempts, not every rejected read. Status exposes ages, remaining
lifetime, next refresh, revision, attempts, mode and enumerated blocker; no raw
grants, credentials, account payloads or exception messages. Logging failure follows
the existing runtime safety rule.

## 8. Implementation phases and acceptance

### Phase 1 — next Sol assignment only

Implement `quota.py`, supervised RestReads/TokenBudget enforcement and explicit
manual refresh integration, diagnostic codes, tests and the offline benchmark.
No automatic supervisor/runtime wiring yet. Leave legacy fixture mode explicitly
unmanaged. Complete ownership/admission/dispatch protection before adding timers.

Required regressions:

1. Empty/mixed-lane/permanent/finite/expired/null/malformed/oversized grants;
   lower-level earliest expiry; unknown tier label not converted into capacity.
2. Observation-start TTL, equality boundary, delayed pair, near-expiry rejection,
   forward/backward clocks, Windows-resume-style drift and restart without lease.
3. Malformed second document leaves the last good lease/config unchanged;
   no partial publish, no mutation/write allowance, no credential loading.
4. Expiry during token/slot waits and between retries/pages; revision changes
   between debit and dispatch; late successes cannot confer fresh proof; late
   final 429 still pauses the same bucket.
5. Saturated background AND critical admission permits the one control pair;
   bounded slots/tickets; small supervised caps rejected; normal priority retained.
6. Coalesced refresh callers, canceled consumer, stop while a wire is blocked,
   wrong scope/epoch, timed-out pair draining, stale delayed candidate rejected.
7. Ordinary callers cannot forge recovery privileges through endpoint names,
   `reason`, params or coalescing scope; no repeated reset/refill on stale checks.
8. Current D-036 tests remain passing; add explicit unmanaged/supervised assertions
   rather than silently weakening old contracts to make tests pass.

Run the complete suite and unchanged D-036 30/120 fixtures. Demonstrate at least
two guard-reversal failures offline (e.g. expiry check removed, late candidate
installation allowed), restoring original guards afterward. Report exact results
and limits, then STOP for Astra review. Do not begin Phase 2 automatically.

### Phase 2 — separate approval after Phase 1 review

Implement `quota_supervisor.py`, optional runtime ownership and quota holds in
metadata/recovery. Tests must cover scheduled refresh, event storms, simultaneous
expiry/refresh completion, failure while old lease remains fresh, exhaustion,
explicit retry cooldown, sleep/resume, logging failure and shutdown. Demonstrate
healthy WebSocket fill persistence during quota outage and unchanged risk holds.
Run complete/integrated/resource checks, then STOP for Astra review.

### Later production gate — not part of either implementation phase

Choose/reverify the actual launch probe configuration and clock assumptions,
finish production write limits, account/history/cash/stream proof and market input
approvals, and obtain live authority. No account use is necessary for Phases 1/2.

## 9. Predeclared resource checks

Fixtures are software engineering, not paper trading or earnings evidence.

- Phase 1: 30 and 120 concurrent mixed read/control callers with deterministic
  clocks and injected wire; 10,000 synchronous guard/status checks. At most 32
  in-flight operations, existing configured wire concurrency, <=128 token waiters,
  one refresh pair and <=128 grants/2,048 costs. No retained task per rejected call.
  Successful coalesced refresh makes exactly two wire GETs without injected faults.
- Phase 2: repeat with 30/120 managed markets and 1,000 coalesced notifications;
  quota GET/task counts must not scale with market count. No extra quota reads from
  book ticks. New expiry/refresh decisions follow injected deadlines exactly.
- Each fixture: CPU <1s/3s, incremental traced Python peak <8MiB, event-loop lag
  p99 <50ms, zero unowned tasks after injected transport drain. Report wall time,
  CPU, memory, p50/p95/p99 lag, gate-check latency and token spending. Token/HTTP
  waiting is reported separately, not hidden in a fast-path latency claim.
- A 10s healthy idle scheduler check adds <=12 clock-health wakes and zero refresh
  GETs when no deadline is due. No sleep-spinning or full-market scan per wake.
  Retain original D-036 benchmark budgets; do not relax them to accommodate this.

## 10. Handoff and verification limits

Only Markdown changes were made in the design session. No implementation, tests,
benchmarks, credentials, account calls or bot process were run for this plan.
Earlier 716-suite / 87-re-review results remain historical evidence, not validation
of this proposed feature. Git metadata is unavailable, so no diff/commit coverage
is claimed. Preserve operator files and the cleared D-036 implementation.

The TTL/probe/null-expiry behavior above is a recommendation for approval with
Phase 1, not a newly accepted trading setting. A general "implement" after the
operator's model switch should target Phase 1 only, with no Phase 2 or live launch.
ALWAYS STOP HERE for the operator to switch to 5.6 Sol.
