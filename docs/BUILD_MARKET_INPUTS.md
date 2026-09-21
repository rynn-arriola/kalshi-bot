# D-034 — Market inputs for advisory inventory exits

Implemented and checked September 20, 2026, native Windows at
`C:/Users/rynna/Bots/kalshi`. Public documentation only; no credentials, account
reads, live stream, orders, cancellations, paper process or trading ledger changes.
No Polymarket changes. Kalshi has no Git metadata, so no commit/diff/parity claim.

## Verified source contracts

| Input | Source and treatment |
|---|---|
| Trading state, open/close, rules, early-close flag, exchange | [Get Market](https://docs.kalshi.com/api-reference/market/get-market). Bootstrap/full missing definitions via REST. Close is a trading boundary, not event start. |
| Tick grid | Market `price_ranges`, then [lifecycle updates](https://docs.kalshi.com/websockets/market-and-event-lifecycle). Parse actual bands; never infer ticks from labels or book gaps. |
| Event-to-series and fee override | [Get Event](https://docs.kalshi.com/api-reference/events/get-event), then lifecycle `event_fee_update`. Override takes precedence; paired nulls restore series fees. |
| Series fee model/multiplier | [Get Series](https://docs.kalshi.com/api-reference/market/get-series). Required fallback; no series-fee stream was established in the inspected contract. |
| Announced fee changes | [Event fee changes](https://docs.kalshi.com/api-reference/events/get-event-fee-changes) and [series fee changes](https://docs.kalshi.com/api-reference/exchange/get-series-fee-changes). Bound pagination; expire inputs before the next announced change. |
| Reviewed event start | [Get Milestone](https://docs.kalshi.com/api-reference/milestone/get-milestone) and [milestone guide](https://docs.kalshi.com/getting_started/targets_and_milestones). Exact reviewed ID/type and primary-event membership required. Broadly related events are not sufficient. |
| Rounding | [Fee rounding](https://docs.kalshi.com/getting_started/fee_rounding) and [fixed-point quantities](https://docs.kalshi.com/getting_started/fixed_point_migration). Exact Decimal calculations; no inferred member class. |

The dated local OpenAPI/AsyncAPI copies and `KALSHI_API_REFERENCE.md` were checked
alongside the current official pages. REST endpoints added are GET-only public
metadata adapters: event, series, milestone, event fee changes, series fee changes.
Existing market GET is reused. A 401/unsupported response remains a failure,
not permission to silently use a credential or bypass account setup.

The public lifecycle guide also documents `metadata_updated` and event-fee
updates beyond the narrower market-event enum in the cached schema. Metadata
updates invalidate the full market definition; they do not preserve a reviewed
rule interpretation without rechecking the fetched rules. Unknown message types
revoke the connection's input evidence. Unknown market-event subtypes revoke
that market's definition and require full refresh, without guessing semantics.

## What is built

`market_inputs.py` parses immutable market, event, fee and milestone evidence.
Supports standard binary unit-dollar contracts; multivariate/scalar/non-unit
notionals, malformed ranges and unsupported precision fail closed. Tick ranges
must be bounded, contiguous and cover the unit interval. Only supported quadratic
taker fee models receive an estimate; flat/unknown models remain explicit blockers.

`ExitInputService` shares dependencies and in-flight reads across managed markets.
It publishes `ExitTerms` into `InventoryManager` through the optional
`RecoveryRuntime.market_inputs` integration. Lifecycle begin/ACK/ingress/disconnect
and runtime stop revoke or update the correct generation. The control-plane
`refresh_exit_inputs(ticker)` performs refresh; it is deliberately not called
inside a public-book tick handler. No new autonomous polling/launch process exists.
The future supervisor must schedule bounded initial, missing-input and expiry
refreshes using the shared read-token budget, and close the service after runtime
stop. This remains production wiring work, not a claim of an armed/live feed.

Supported stream updates replace cached tick/close/state/fee fields without
additional REST calls while the remaining baseline is fresh. Full definitions,
milestones and schedules still require REST because those full facts are missing
from the stream. Stream updates never extend unrelated metadata TTLs. A full
REST refresh may include overlapping fields, but conflicts with the last stream
value block publication instead of overriding it.

Generation, dependency revision, UTC and monotonic freshness are checked after
awaits and immediately before publication. Changes revoke published terms first.
Stream observations arriving before the first REST baseline, while a read is
pending, or after baseline expiry remain as bounded field overlays. They cannot
be lost on a subsequent stale REST response. Reconnect clears the old generation;
subscription acknowledgment is not complete account/history or stream replay proof.
Strict local sequence continuity rejects gaps/reordering; this is a conservative
consumer check, not an invented venue-wide REST/WebSocket atomicity guarantee.

## Timing and fee limits that must remain visible

`TimingReview` is an explicit, expiring rules-to-milestone binding. It names the
market/event, milestone ID/type, a review reference and exact rule/strike digest.
Early-close markets require explicit early-close review. The caller must have
actually established that the milestone start is the relevant risk time for that
contract. The class is not an automatic reviewer or trading approval. Changes to
rules, strikes or early-close conditions invalidate the interpretation. It does
not infer start from expected/latest expiry, occurrence time, title or strike date.
No real-market reviews or market selections were installed this milestone.

The existing planner subtracts the approved five minutes from this reviewed
start and respects trading close. It does not promise flattening if a market
closes early or liquidity disappears. Unreviewed timing has a null risk time and
an explicit blocker; it cannot authorize timed taker exits.

`FeeProfile` requires a reviewed balance quantum and expiration. The guide
distinguishes direct `$0.0001` from non-direct `$0.01` alignment, model fees rounded
up to a microdollar, and per-order rebates. Membership cannot be inferred from a
sample cash balance. No real account profile was established here; FCM/additional
broker charges are outside this exchange-fee estimator and must be resolved
before live use. The review reference must identify real evidence, not a fixture.

The current [official fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)
gives the quadratic taker coefficient `0.07 * multiplier * quantity * p * (1-p)`.
For supported models, our conservative per-contract exchange-fee bound is:

```text
0.0175 * multiplier + 100 * (0.000001 + verified_balance_quantum)
```

This is an engineering upper-bound derivation, not a venue-provided quote:
`p*(1-p)<=0.25`, minimum fill quantity is 0.01, and each fill can add model and
balance-alignment rounding. It deliberately ignores rebates and fee waivers.
With a verified direct profile and multiplier 1, the bound is $0.0276/contract,
or $0.276 for ten contracts. Non-direct bounds are much looser; do not choose
direct precision just to obtain a more attractive estimate. These are not actual
fees, trading-loss promises or reward estimates. D-024 still records actual fees.
The PDF's older whole-cent table examples are not used as the fractional-fill
rounding algorithm; current detailed rounding guidance supplies that behavior.

Effective fee changes must agree with current metadata. Future scheduled changes
shorten terms validity; this service does not apply a forecast fee early or
extend old inputs through a change. Missing/expired member profiles, unsupported
models, timing mismatches and malformed/missing schedules remain explicit gaps.
Passive exact reducers can still be planned with valid market facts under the
existing exit rules; missing timing/fees do not become entry or IOC authority.

## Resource contract and tests

Fixed managed universe <=1,024; dependency-key budget <=6 per managed market;
2 read slots, 16 shared pending reads, 8 simultaneous market refreshes; no
per-market threads or automatic poll loops. Event changes use a reverse dependency
index, not a full market scan per incoming universe notification. Fee schedules
are bounded to 128 rows, event changes to four pages/256 KiB. Caller supplies
metadata TTL, capped at 60 seconds and shortened by known changes/review expiry.
Caps fail closed; they are technical bounds, not larger live risk budgets.

41 focused tests cover source semantics, fee arithmetic and fragmentation,
override clearing, scheduled changes, tick grids, rules/milestone review,
early-close controls, stale/superseded REST, pre-bootstrap/expired-baseline stream
updates, generation/sequence loss, caching, pagination, scope, review/profile
expiry, runtime publication and revocation. Two in-memory safeguard reversals
were detected: skipping published-term invalidation and omitting rounding costs.
No source files were altered by those fault injections.

Predeclared diagnostic: 30/120 markets sharing one event, cold bootstrap plus
ten warm refreshes per market and a tick update per market. Required read counts
exactly markets+5; wall <3/10 seconds, refresh p99 <50ms, loop-lag p99 <50ms and
traced peak <16MiB. Both passed:

| Markets | Reads | Wall / CPU seconds | Refresh p99 ms | Loop-lag p99 ms | Peak bytes |
|---|---:|---|---:|---:|---:|
| 30 | 35 | 0.0905 / 0.0781 | 0.639 | 0.829 | 121,400 |
| 120 | 125 | 0.3418 / 0.3438 | 0.648 | 0.696 | 401,027 |

Injected in-memory reads, not measured venue RTT/rate limits or live readiness.
Final full suite: 639 tests passed in 44.198s. Local preflight reports
`live_ready: false`, no credential/network access and no file creation.
Account history/cash/continuity proof,
production scheduling/selection, fee-profile and market-rule reviews, mutation
transport and supervised Windows launch remain unfinished. All execution stays
disabled, with existing capital, exposure and stop rules unchanged.
