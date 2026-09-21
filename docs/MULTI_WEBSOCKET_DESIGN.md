# Multi-WebSocket architecture recommendation
Date: 2026-09-19. **D-021 authorizes construction; live activation remains blocked.**
Accepted parameters live in D-016 through D-021 in [DECISIONS](../DECISIONS.md).
The operator chooses all project decisions (D-015). See the
[foundation build report](BUILD_FOUNDATION.md) for implemented vs remaining scope.

## Accepted starting parameters and remaining decisions
- Entry quote size: 10 contracts, replacing the earlier fewer-than-10 rule.
- Maximum 30 resting entry orders, excluding orders managing open positions.
  This is an order count, not 30 markets or 30 filled positions. Two entry
  orders in one flat market consume two slots.
- $25 settled trading-loss stop in each fixed America/New_York window:
  00:00-06:00, 06:00-12:00, 12:00-18:00, 18:00-00:00.
- Existing $500 capital ceiling and no paper testing remain. D-021 authorizes
  implementation, not live trading.
- D-018 adopts Polymarket's inventory policy and current size-10 reference
  exposure formula, corrected by D-020's source audit: $90 market at size 10,
  portfolio `10 * (market slots + 10)`. Market slots remain undecided;
  $420 is only the 32-slot example. The reference counts inventory, all working
  orders (including reducers), and deduplicated ambiguous-send reservations.
  The $500 capital limit also applies.
  Kalshi-specific exit/deadline mapping, additional correlated-event limits,
  entry expiry and restart/resume details remain for review.
- After a fill cancel building orders; no additional risk-building orders in
  that positioned market. Work an exact passive reducer with no break-even
  floor; retain a valid own-touch reducer. The reference evaluates IOC after
  15 minutes but may defer for depth or projected loss worse than $8, while
  retaining passive protection. Absolute event/maintenance/HARD exits override.
  Map the reference five-minute pre-kickoff exit to each Kalshi market's actual
  event-risk boundary before use; never invent a clock for non-sports markets.
  Exact remaining inventory controls reducing quantities; never round a partial
  position up to a 10-contract exit.
- Four $25 windows permit $100 nominal daily loss triggers; that is 20% of
  $500, not a recommended daily budget or guaranteed maximum. In-flight fills,
  price jumps, fees and evacuation can overshoot. A separate daily cap remains
  a decision, not implicitly $100.

## Recommended starting shape: one engine, four data connections
Recommend a modular Python async engine on native laptop Windows (D-019),
separate from Polymarket. Four sockets are a starting topology proposal, not a measured
optimum, a proven entitlement or an exchange requirement.

| Connection | Responsibility | Reason |
|---|---|---|
| Book A | First partition of managed order books | Contain book-recovery work |
| Book B | Remaining managed order books | Split bursts and fault scope |
| Account | All own orders, fills, positions and relevant order-group events | Keep account safety independent of book volume |
| Lifecycle | Relevant market/event lifecycle and only needed ticker/trade subscriptions | Keep discovery/status work away from execution events |

For up to 30 single-market entry orders, approximately 15 entry markets per
book socket is an initial illustration, not a hard market cap. Open inventory
and unresolved owners stay subscribed after entry capacity is freed. Total
managed scope must respect D-018 exposure limits and separately approved
market/resource capacity; the 30-entry ceiling alone is not that capacity.
Apply D-020's source-verified exposure formula rather than fixing $420.
Use stable ownership; do not constantly reshuffle books as activity changes.
Reserve extra connection headroom for a controlled replacement; do not open an
unlimited set of overlapping sockets.

Kalshi documents multi-market book subscriptions with snapshots/deltas and
stream snapshot requests. Private orders, fills and positions can be received
account-wide without market filters. This favors one account feed over copying
Polymarket's market-specific private shards.
Sources: [books](https://docs.kalshi.com/websockets/orderbook-updates),
[orders](https://docs.kalshi.com/websockets/user-orders),
[fills](https://docs.kalshi.com/websockets/user-fills),
[positions](https://docs.kalshi.com/websockets/market-positions).

The inspected official pages do not establish a numeric concurrent-connection
allowance for this account. Validate permitted simultaneous subscriptions and
any account limits before locking in four sockets. Do not silently substitute
a single connection if the requested multi-connection design is unavailable.
More sockets do not increase API quotas or protect against laptop/network loss.

## Ownership and data flow
Readers -> validated bounded event queues -> one state coordinator ->
changed-market/deadline scheduler -> strategy -> account-wide risk gate ->
durable intent acknowledgement -> one order execution authority.

- One state owner, one durable ledger writer, one execution authority. Parallel
  readers may not mutate ownership, place orders or independently adjust risk.
- SQLite WAL is the proposed local ledger. A bounded single-writer worker
  acknowledges durable intent before a send; storage stall blocks new risk.
  Reports use read-only committed state, never competing venue polling.
- Separate raw ordered book deltas from coalesced strategy wakeups. Apply every
  required delta; deduplicate fills across reconnects and REST backfill.
- Track connection generation, subscription identity and documented sequences.
  Do not invent a global sequence across sockets or across private channels.
- Keep monetary values exact. Normalize YES/NO, side, fees and rounding through
  a Kalshi-specific adapter, not a copied Polymarket payload.
- Separate transport liveness, subscription readiness and authoritative account
  completeness. Ping/Pong alone never proves that no fills were missed.
  Quiet markets/accounts are not automatically broken merely for having no
  business events. [Keep-alive](https://docs.kalshi.com/websockets/connection-keep-alive)
- Each book partition can recover independently. Shared account uncertainty
  blocks all new risk. Recovery and catalog work yield to fills, cancellations,
  position management and deadlines; resumption requires positive fresh proof.
- REST serves missing incentive/metadata/balance/startup/history evidence and
  documented order commands, not duplicate healthy-stream polling.
  Share cache, in-flight reads and cost-aware admission. Reserve mutation
  headroom for safety work; respect actual bucket scope and 429 backoff.
  [Rate limits](https://docs.kalshi.com/getting_started/rate_limits)
- Suggested modules: transport, normalized state, incentives, selection,
  quoting, risk, execution, reconciliation, ledger, runtime and observability.
  Avoid a giant coordinator containing every strategy/report/recovery detail.
  No microservices or process-per-market without measured need.

## Lessons from Polymarket: evidence, not blame or copied venue assumptions

D-020: use [the code audit](POLYMARKET_INVENTORY_CODE_AUDIT.md) for verified
inventory behavior. The incident documents below are historical leads, not
sufficient evidence that any particular implementation remains in force.

## Windows runtime design boundary

D-019 supersedes the original WSL recommendation. Use native Python/async I/O
and a dedicated Windows virtual environment. Propose PowerShell lifecycle tools,
a Windows-compatible single-instance lock and an explicit graceful control
channel; do not rely solely on POSIX signals. A future watchdog/service must
follow approved recovery rules and cannot silently restart normal trading.
Propose runtime SQLite/WAL/logs under a private non-cloud-synced Windows data
directory; its exact location remains a design choice, not a data-move action.
OneDrive project documents can remain where they are. Verify sleep/resume,
network changes, lock release and shutdown on Windows before live authorization.

## Historical reference sources
Read-only reference: C:/Users/rynna/Bots/liquidity-bot at
54ac71a241d1ad6f02e3445655bb7115247bac02. These are documented historical
incidents/code properties, not freshly observed live status.

| Reference incident | Kalshi design response |
|---|---|
| One public-stream error was treated as separate market failures, repeating recovery and retiring owners | Recover once at the owning connection; contain affected markets; do not cascade identical work |
| Private connection liveness did not guarantee complete account state | Separate liveness/readiness/completeness with scoped reconciliation |
| Account read backpressure and recovery delayed urgent service | Shared endpoint-aware admission; bounded recovery steps; prioritize exits |
| A reducer repeatedly improved against its own order | Account for own resting quantity; preserve a valid exact reducer; avoid self-chasing |
| Delayed matched cash was misclassified as trading loss | Durable closed-fill realized P&L plus actual fees; exclude cash timing and rewards |
| WSL died while resting orders remained at the venue | Proposed exchange-side entry expiry and restricted recovery watchdog; neither substitutes for inventory exit protection |
| Repeated all-market work and historical ledger scans consumed CPU | Incremental state, dirty-market/deadline scheduling and bounded indexed reads |

Reference files under that checkout:
- docs/history/SHARED_STREAM_RECOVERY_AND_REST_LOAD_2026-09-13.md
- docs/ACCOUNT_SOURCE_ARCHITECTURE.md
- docs/history/ACCOUNT_READ_AND_REDUCER_LOAD_2026-09-13.md
- docs/history/SIX_HOUR_RISK_WINDOWS_2026-09-15.md
- docs/history/HOST_OUTAGE_PROTECTION_2026-09-15.md
- src/liquidity_bot/live_commissioning.py (dirty-market scheduler)
- src/liquidity_bot/execution_ledger.py (durable ledger)
- BUGFIXES.md (incident index)

## Six-hour risk design for operator review
D-017 explicitly requires realized results from trades the bot opened and
closed, including attributable actual trading fees. Exclude pending/paid
rewards, transfers, cash settlement timing and unrealized open inventory.
This means closed trades, not waiting for event resolution. Recommend a
restart-persistent meter. Before implementation present partial-close,
fee-allocation, delayed/corrected-fill, matching-basis and window-attribution
rules for approval; do not silently decide how partially open inventory counts.
Retain separate unrealized exposure monitoring, not an unauthorized stop.
Use America/New_York calendar boundaries with
UTC timestamps, including DST days, not a rolling six hours or restart timer.

Proposed breach behavior: latch new entries off, cancel risk-building orders,
confirm their outcomes, reduce remaining inventory under approved exit rules,
and resume only under an approved next-window/fresh-state policy. Do not reset
the stop on restart. D-021 now accepts Polymarket's 30/25/20/15/10/0 entry
ratchet; the persistent foundation implements and tests it.

## Required verification before live authorization
No paper trading is proposed. Offline contract, invariant, fault-injection and
load checks must cover lost/duplicate/out-of-order events, partial fills during
cancel/expiry, ambiguous sends, stale snapshots, queue overflow, 429s, slow disk,
laptop sleep, restart and clock/DST boundaries. Do not induce faults on live orders.

Before implementation agree resource/latency budgets; measure CPU, memory,
event-loop delay, queue depth, gap recovery, write admission and fill-to-risk-action
latency under normal load, simultaneous fills and reconnect bursts. Include
managed inventory beyond the 30 resting-entry ceiling. Multiple sockets alone
are not proof of scalable or low-latency operation.

Future live commissioning needs explicit approval, eligibility/account proof,
inventory/exit limits and the finished implementation review. Keys were not
used for this design review; no orders, stream sessions or runtime changes occurred.
