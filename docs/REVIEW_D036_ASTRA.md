# Astra review: D-036 metadata scheduling and read limits

Date: September 20, 2026. Phase: review complete; handoff to 5.6 Sol for fixes.
Result: four reproduced P2 reliability findings remain open. Production Python
and test files were not edited during this review. These findings concern current
components; no live execution was activated.

Later Sol handoff note: R1-R4 have now been implemented with focused regressions
and passing 30/120 resource fixtures. The findings below preserve Astra's original
review evidence; current fix state is in `../STATUS.md`. The subsequent
[Astra re-review](REVIEW_D036_ASTRA_R2.md) cleared R1-R4 within the reviewed scope.

## Scope and evidence

Reviewed `metadata_scheduler.py`, `rest.py`, changes to `market_inputs.py`, runtime
ownership, engine book availability, inventory term consumption, diagnostics and
the corresponding tests against D-034/D-036 and permanent engineering rules.
`git status --short` confirms this directory has no usable Git metadata. Review
therefore covers present source and documented milestone scope; it cannot prove
the exact Git diff, attribution of every line, or absence of unrelated changes.

The exact current suite passes: **707 tests in 54.564 seconds**. Additional
in-memory probes, using injected clocks, gates and fixture transports, reproduce
the findings below. They are review diagnostics, not committed regressions.
Preflight remains `live_ready=false`, native exit 2, no credential/network access
or file creation. No real account call, socket, mutation, ledger import or
Polymarket modification occurred.

Rechecked the official [rate-limit guide](https://docs.kalshi.com/getting_started/rate_limits),
[account limits](https://docs.kalshi.com/api-reference/account/get-account-api-limits)
and [endpoint costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs),
plus local exact operation/response schemas. Read and Write budgets are separate;
actual account refill/capacity and method/route costs remain the relevant inputs.
No additional venue policy is inferred by these local concurrency findings.

## R1 — P2: replacing a timing review permanently exhausts dependency slots

Locations: `src/kalshi_bot/market_inputs.py:260` (`set_review`) and `:351` (`_key`).

`_key` limits the lifetime `epochs` dictionary to six entries per market, but
`set_review` never retires the previous milestone dependency. A fully reviewed
single market already uses all six slots: market, event, series, event fee
changes, series fee changes and milestone. A legitimate replacement review
pointing to milestone M2 requires a seventh historical key and always fails.
Disconnect clears values but retains/increments epochs, so reconnect does not
repair it. The scheduler eventually exhausts that market's retries and retains
no usable terms even when the replacement review and response are valid.

Reproduced with a service constructed for exactly one ticker A, ttl 30, fixture
review M and fee profile; normal refresh succeeds. Call `set_review` with
`dataclasses.replace(old_review, milestone_id='M2')`, set the fixture response ID
to M2, and refresh. Output before and after `begin(2)`/subscription:

```text
review replacement generation 1 : metadata dependency capacity exceeded
review replacement generation 2 : metadata dependency capacity exceeded
```

Fix within the current service: bound retained dependency state by current
references and bounded outstanding work, safely retire unreferenced dependencies,
and retain stale-response protection. Do not merely increase the lifetime cap
or reset an epoch while an old task can still publish into that key.

Acceptance: successive valid milestone replacements refresh successfully with
bounded state; shared dependencies remain available to other markets; pending
old responses cannot restore a retired binding; reconnect still revokes evidence.
Exercise more replacements than the original capacity, not only one M->M2 case.

## R2 — P2: background work can consume all read admission capacity

Location: `src/kalshi_bot/rest.py:403` (`RestReads.read` admission check).

The reserved transport slot and token priority act after admission to `inflight`.
Background callers can occupy every admission entry while waiting for their
background semaphore. A critical account/quota request is then rejected before
it can use the idle reserved transport slot. This defeats recovery priority at
the queue boundary and can make quota refresh fail during background saturation.

Reproduced with default `inflight_limit=32`, concurrency 2, sufficient tokens and
a gated injected wire: enqueue 32 distinct metadata market reads. Only one can
occupy the background wire lane; a `costs` read with reason `budget` fails:

```text
default capacity: 32 unused wire slots: 1
quota read: read in-flight budget exceeded
```

The same failure occurs with supported `inflight_limit=2`. The normal two-worker
metadata fixture alone does not generate the 32-call burst; this probe exercises
the shared REST component's supported concurrent consumers and saturation policy.

Fix admission as well as transport/token priority. Reserve bounded admission
for critical work or use a bounded priority queue that prevents background
waiters occupying all usable capacity. Keep hard total bounds, coalescing and
honest behavior at very small configurations. Do not cancel dispatched account
or background requests to pretend their worker slots are free.

Acceptance: saturated background admission still permits critical account/quota
progress when reserved capacity exists; total requests/workers remain bounded;
overload/cancellation cleans up state; concurrent quota refresh retains coalescing
and cannot partially reconfigure the bucket.

## R3 — P2: a new connection inherits failure from an old metadata request

Locations: `src/kalshi_bot/market_inputs.py:333` (disconnect), `:364` (pending task
lookup), and `src/kalshi_bot/metadata_scheduler.py:98` (failure accounting).

Disconnect cancels scheduler consumers but leaves service-owned `_load` tasks
pending. A generation-2 `_get` looks up pending work solely by `(name, key)` and
awaits the generation-1 task. That task necessarily rejects its response as stale.
The scheduler records this rejection against generation 2 because it knows only
the generation of its new consumer, consuming a current retry without attempting
a fresh current-generation load. A slow old request also delays current recovery.
An already nearly exhausted budget can become exhausted from this transition.

Reproduced using the existing scheduler fixture and default retry/time limits:
gate the first two market reads; connect generation 1; begin/ack generation 2
while the old reads remain pending; advance the paired clocks 0.1 seconds; run
scheduler turns, then release the gate:

```text
old-generation pending reads: 2
new generation consumers: 2 total wire fixture calls: 2
healthy generation 2 first refresh:
  failures={'A': 1, 'B': 1}, published=[], completed=0
after extra retry: failures={}, published=['A', 'B']
```

Preserve generation/revision identity in pending-work ownership. Use bounded
drain/replacement or an explicit superseded-work outcome so an obsolete response
does not become a new-generation dependency failure. Preserve existing genuine
failure counts and cooldown; a reconnect must still never reset exhaustion.
Coordinate with R1's retirement rules. Also preserve wire provenance: merely
starting a new wrapper around an old coalesced REST request must not label its
response as newly observed current-generation evidence.

Acceptance: pending reconnect, same-generation invalidation and a nearly
exhausted retry budget; stale results never publish, old work never erases new
pending state, current genuine failures still count, and task/transport bounds
hold through repeated disconnects. Keep shutdown ownership explicit.

## R4 — P2: quota updates cannot interrupt the head token wait

Locations: `src/kalshi_bot/rest.py:185` (`await self.sleep(delay)`) and `:190`
(`reconfigure`).

Followers wait on the change event, but the head request sleeps only on a timer.
Reconfiguration wakes the event without interrupting that head's old delay.
After an increased refill rate or reduced endpoint cost, an eligible request can
therefore remain parked on its old timer while holding a transport slot; same
priority followers remain behind it. Updated configuration is not promptly used.

Reproduced with an injected gated sleep: rate 1, capacity 20, cost 10, initial
tokens 0 and deadline 30. The head starts a ten-second sleep. Reconfigure to rate
1000/capacity 100, then advance the clock to 0.1 seconds. Enough tokens can accrue,
but after scheduling turns the task still awaits the original ten-second sleep.
It proceeds only when that old sleep is explicitly released.

Make the head wait interruptible by configuration/queue/throttle changes as well
as its due time. Recompute eligibility after wake, retaining deadline checks,
FIFO within priority, shared throttle, exact token charging and bounded cleanup.
Avoid a busy loop or leaked timer/event tasks, including with injected clocks.

Acceptance: rate/cost increase and decrease while the head sleeps, priority
arrival, throttle extension, cancellation and deadline expiry. A configuration
change must neither keep an obsolete wait nor permit premature spending.

## Sol handoff and completion criteria

Implement R1-R4 with the existing architecture and public service boundaries.
Add focused regressions for each demonstrated behavior; add integrated coverage
where the dependency retirement and reconnect changes interact. Run the complete
suite after the final source edit. Rerun affected scheduler/rate resource fixtures
because these fixes change waiting and retained task/state behavior. Preserve
the predeclared bounds rather than adjusting them to make failures disappear.

Update STATUS/NEXT/BUILT and fix evidence, then hand the changes back to Astra
for review. No fix was applied during this review; stop here for the operator's
switch to 5.6 Sol, as required by D-037.

Automatic quota freshness/grant expiry and write execution remain separate future
work already acknowledged in RATE_LIMITS.md; their absence is not counted as a
new defect in this scoped review. Current gate/revocation checks prevented stale
metadata from authorizing live actions in the inspected paths. Passing fixtures
and this review do not supply the outstanding live account/market proofs.
