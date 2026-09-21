# Recovery evidence and owned-order management

2026-09-20. D-021 implementation, native Windows only. **No live activation.**
This extends the [account-I/O milestone](BUILD_ACCOUNT_IO.md); it does not claim
complete recovery, a live executor or permission to trade.

## What is now connected

- `orders.py` normalizes canonical order direction, quantity, status, scope and
  update time. Exact client identity and immutable terms bind a venue order to
  an existing durable SENDING/UNKNOWN/ACKNOWLEDGED intent. Prefixes do not prove
  ownership; RESERVED/rejected intents cannot silently claim a venue order.
- Owned order observations persist through the single SQLite writer, including
  terminal observations. Old updates cannot restore a canceled/executed order.
  Missing/comparable-version ambiguity and conflicting same-version states stop
  progress rather than picking whichever state looks more convenient.
- Terminal order status does not resolve its intent until the ledger has the
  exact reported cumulative filled quantity. Fill-before-order and
  order-before-fill paths converge; fills and any resulting terminal-intent
  transition commit together with the loss-ratchet update.
- The account coordinator consumes private order/position/fill events. Order
  state is durable; position notifications are informational and never replace
  ledger lots, fees or the closed-trade loss meter. Their documented stream does
  not supply a cross-channel atomic ordering guarantee.
- Startup reconciliation ingests resting orders in batches of at most 32 and
  reloads persisted order evidence. It never deletes an owned order just because
  a REST list omits it. A direct order GET can supply terminal evidence; a 404,
  timeout, missing row or reconnect cannot prove cancellation.
- The account fill path now requires a durable owned-order binding. Missing
  optional fill subaccount can be resolved through that binding. An explicit
  conflicting account, mismatched market/direction or unbound fill blocks the
  path. A fill arriving before its order binding needs order/history recovery;
  it is not silently counted as this bot's trade or silently treated as absent.

No mutation transport or injected executor was added. Existing pure V2 payload
builders still do not send orders. Resting-order ownership and execution proof
are inputs for the future executor, not proof one already exists.

## History recovery: evidence, not an unapproved accounting replay

`recovery.py` reads the trade-history cutoff, fetches required current/archive
pages, normalizes exact executions and checks the cutoff again. A one-second
query overlap handles second-based boundary filters; records are deduplicated
by order/execution identity, checked for conflicts and clipped to the requested
half-open execution-time interval. A moving cutoff invalidates the collection.

Current fill requests explicitly filter subaccount. Historical fills have no
documented subaccount query: explicit row scope is required, other accounts are
excluded and missing/null historical scope fails closed. No primary-account
assumption is introduced. Canonical identifier aliases and execution timestamp
aliases must agree. Execution ordering at identical timestamps is not invented.

Recovered fills are stored in a separate `recovery_fills` evidence table. They
are compared with already-recorded economic payloads and missing executions are
reported. They **do not** create lots, change loss windows, import zero-cost
starting inventory or erase a previous stop. Corrections are reported as errors,
not applied automatically. Empty/current-position agreement is not history proof.

The writer stages at most 256 records per command and yields between chunks so
fill/order/risk commands can interleave. Each chunk is atomic, not the whole
10,000-record enumeration. If canceled or interrupted, earlier evidence chunks
may remain safely staged, but no completed audit is returned. These rows are
never trading accounting. Final account publication still checks source epoch,
revision and age; intervening private activity invalidates the candidate audit.

Final replay behavior is pending the operator's partial-close, fee and late-fill
window decision. Settlements, corrected/busted executions, archived terminal
order recovery, imported starting inventory and reverse completeness checking
still need implementation. Current ledger records lack full venue execution-time
coverage, so the audit explicitly retains that blocker. No report enables entries.

## Passive inventory planner

The new pure planner uses exact signed YES-frame inventory:

- Cancel known owned risk-building orders before proposing a replacement.
- Keep one exact-quantity reducing order at the supplied passive touch and
  cancel duplicates/wrong reducers before replacement.
- Propose only the exact remaining reducer quantity, including 0.01-contract
  residues; the percentage rule still controls entry count, not liquidation size.
- Preserve existing reducing work when no reducing-side touch is available;
  do not invent a price or automatically choose IOC.
- Incomplete scope, foreign orders or unaccounted fills block a new reducer.

This is a **plan only**, not a venue cancellation, price-selection policy or
automatic exit process. The supplied touch must come from validated book/tick
state; market/event deadlines, IOC depth/loss rules and quote repricing are not
connected here. The reducer plan never creates a fresh entry.

Polymarket reference was re-read in executable source:
`C:/Users/rynna/Bots/liquidity-bot/src/liquidity_bot/reconciler.py`,
`_passive_inventory_plan` around lines 644–720. It cancels building orders,
preserves an exact reducer at touch, handles duplicates and preserves reducing
work when the side has no touch. HEAD remains
`54ac71a241d1ad6f02e3445655bb7115247bac02`, clean and unchanged.
Kalshi additionally requires verified ownership and explicit reducing intent;
no Polymarket runtime, credentials or API assumptions were copied.

## API/source checks and corrections

Checked local operation/schema definitions and official pages on September 20:
[order GET](https://docs.kalshi.com/api-reference/orders/get-order),
[private orders](https://docs.kalshi.com/websockets/user-orders),
[fill GET](https://docs.kalshi.com/api-reference/portfolio/get-fills),
[historical split](https://docs.kalshi.com/getting_started/historical_data).
The complete local [API reference](KALSHI_API_REFERENCE.md) remains canonical
for the captured contracts. No authenticated venue/account call was made.

The new single-order route is fixed to `/portfolio/orders/{order_id}` with path
validation and GET only. Its route participates in the existing endpoint-cost
budget; no historical cost or caller tier is hardcoded.

Fixed the pager's missing-cursor assumption: orders/current fills/historical
fills require `cursor`; a missing field now fails rather than declaring success.
Positions/incentives retain their documented optional-cursor behavior. See
[BUGFIXES](../BUGFIXES.md), also documenting the tightened fill-ownership gate.

## Bounds and verification

**212 tests passed**: 159 previous tests plus 53 recovery/order regressions.
Previous account fixtures now explicitly bind their synthetic owned orders;
they no longer rely on unowned executions entering the accounting path.
All tests are offline correctness/fault tests, not paper trading.

Coverage includes order ownership/term collisions, duplicate/stale/conflicting
updates, UNKNOWN create reconciliation, terminal-before/after-fill races,
restart persistence, REST absence/404, missing account scope, exact reducer
quantities, unavailable touch, archive overlap and moving boundaries, partial
pagination, history/ledger conflicts, chunk interleaving and atomic batch failure.

Two deliberate reversals caused their focused tests to fail, then were restored:

1. Ignoring cumulative-fill agreement prematurely resolved a terminal intent.
2. Removing the required-cursor check accepted a malformed incomplete page.

Bounds: 4,096 persisted order records (including terminal tombstones),
4,096 in-memory order projections, configured position capacity, 32 order
updates per writer batch, 256 history records per writer command and 10,000
staged history records. Existing records are not silently evicted to hide
unresolved state. Explicit retention/archival work is still needed before
unattended operation. Added tables/index are additive; no existing capture or
operator database was opened or migrated. Per-order fill lookup uses a SQLite
JSON-expression index rather than scanning every account fill.

### Offline resource measurement

`.\.venv\Scripts\python.exe -B scripts/benchmark_recovery.py`

Fresh temporary WAL/FULL SQLite; tracemalloc; 2ms heartbeat; synthetic owned
order → partial fill → terminal order. One durable event acknowledgement at a
time, no backlog by construction. Intent setup excluded from timed region.

| Fixture markets / events | Wall / CPU seconds | Event ack p50 / p95 / p99 ms | Loop lag p50 / p95 / p99 ms |
|---|---|---|---|
| 30 / 90 | 0.1816 / 0.1875 | 1.661 / 3.033 / 4.003 | 0.733 / 2.002 / 4.736 |
| 120 / 360 | 0.7096 / 0.6562 | 1.734 / 3.628 / 4.318 | 0.588 / 2.131 / 2.955 |

Rates 495.6 / 507.3 events/sec; heartbeat samples 62 / 256; incremental traced
peaks 363,966 / 225,583 bytes. Initialization influences the first case. These
short fixtures exclude venue latency, replay, quote selection, execution,
simultaneous book load and live risk admission; they are not live capacity SLAs.

Separate missing-history staging: 1,000 rows in 0.1301 wall / 0.1250 CPU seconds;
4,000 rows in 0.4924 / 0.4688 seconds. Incremental traced peaks 111,765 / 376,175
bytes, excluding preconstructed input records. Both leave trading inventory
unchanged. A deterministic test proves a queued risk command runs between
history chunks; this is not a comprehensive priority/saturation benchmark.

## Handoff boundaries

Next: approved historical replay contract and recovery orchestration; remaining
cross-channel completeness checks; injected execution lifecycle, exact quoting
and inventory deadline integration; independent stream recovery and prioritized
deadlines; metadata cache and Windows operational control. Market slots remain
undecided. No live start, account writes, paper run, auto-start service, WSL action,
old-data deletion or Polymarket edits occurred. Kalshi is not a usable Git checkout;
no commit/push/parity claim is made.
