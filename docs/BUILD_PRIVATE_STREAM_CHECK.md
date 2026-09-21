# Private-stream access check and starting-history direction

September 20, 2026. D-030. Native Windows, execution disabled.

## Accepted baseline direction

The operator accepted keeping the 18 previously returned fills separate from
this bot's trading record, while retaining history for reconciliation. This
does not reset an existing ledger or declare unknown orders foreign. Exact
bot-owned evidence must still follow D-024/025; conflicts block. No prior fills
were imported, removed or reclassified by code in this milestone.

The earlier flat primary account is an observation, not a permanent startup
baseline. Arming still needs a fresh scoped snapshot, a durable launch boundary,
ownership evidence and history/private-stream reconciliation. No launch boundary
or active accounting baseline has been installed. Other subaccounts were not
verified and are not silently included in that earlier flat-account claim.

## Implemented

- `src/kalshi_bot/diagnostics.py`: bounded subscription acknowledgment and
  delivery-count probe using the existing reader factory/transport. It verifies
  every requested channel, command ID and distinct subscription ID. An event
  must match its acknowledged channel's ID. Counts are not economic validation.
- `scripts/check_private_streams.py`: manual, explicit live-read-only opt-in;
  privately loads the supplied credential files. Sends only the subscription
  command through the existing signed GET WebSocket handshake. No mutation,
  REST polling, trading ledger or production-runner path.
- `tests/test_bot_diagnostics.py`: 19 offline tests, including real reader
  integration with an injected socket. No user keys or venue calls in tests.

Resource limits are explicit before use: two sequential connections at most,
10-second acknowledgment limit, 15-second observation after each acknowledgment,
256 delivered messages and 2 MiB normalized-message bytes per session; fail-fast,
no retry loop. Existing transport has 10-second open / 5-second close bounds,
bounded frames/queues and heartbeat handling. The 2 MiB diagnostic counter is
normalized JSON size, not measured network bytes. Cancellation joins/closes the
reader; reports retain aggregate counts, not raw account payloads or identifiers.

## Actual read-only production result

From `2026-09-20T21:56:59.516699Z` to `21:57:30.502835Z`:

| Session | Four acknowledgments | Acknowledgment latency | Total duration | Account events |
|---|---|---|---|---|
| First connection | Accepted | 263.521 ms | 15.312 s | 0 |
| Fresh connection after closing first | Accepted | 256.770 ms | 15.672 s | 0 |

Both sessions acknowledged `user_orders`, `fill`, `market_positions` and
`order_group_updates`. Each delivered four acknowledgment messages, totaling
278 normalized JSON bytes. These are two individual observations, not latency
percentiles, an SLA, or a production-load benchmark.

VERIFIED: authenticated subscription access and controlled close/re-subscription
using the actual account. No rejected subscriptions were observed.

UNKNOWN: actual order/fill/position event delivery and normalization, missed-fill
recovery across an outage, full history continuity, concurrent multi-socket venue
limits, private-stream/REST atomicity and reward eligibility. With no account
activity observed, these cannot be established by a quiet socket. The existing
runtime's recovery behavior is tested offline, not proved by this network probe.
The four-connection bot topology was not launched; only its private reader was
checked, sequentially twice. No order was created just to generate a test event.

## Verification

- Focused 19 tests: pass, 5.285 seconds.
- Full 498 tests: pass, 32.573 seconds. This includes the existing recovery,
  accounting, reservations and ownership tests. Offline fixtures, not paper trading.
- Two in-memory safeguard reversals detected: accepting incomplete channel
  acknowledgment and accepting the wrong event subscription ID. Patches were
  context-managed in a disposable interpreter; production files were unchanged.
- Local preflight still reports `live_ready=false`; no live switch enabled.
- No project Git metadata, so no commit/diff or remote parity claimed.

## Next decisions / unfinished implementation

The source recheck still finds Polymarket's portfolio exposure property at
`src/liquidity_bot/commissioning.py`: quote size times (configured market count
plus 10). That does not resolve Kalshi's limits-driven breadth rule. The proposed
replacement is a fixed $400 conservative aggregate exposure ceiling, retaining
the $500 capital ceiling, $90 per-market cap and 30 resting-entry maximum.
Count inventory, all working orders including reducers, and deduplicated
uncertain sends. This is a new explicit policy proposal, not an already accepted
Poly-derived number; it was pending at this milestone. **Superseded by D-031:**
operator chose "Just follow poly"; see [actual reference/calibration](BUILD_POLY_EXPOSURE.md).
No configuration changed during the earlier private-stream milestone.

Kalshi-specific event/IOC/expiry rules, launch supervision and production mutation
transport remain unfinished. Neither subscription access nor a successful
reconciliation report grants trading authority. Obtain separate launch approval
after the remaining policy and engineering gates are genuinely satisfied.

## Primary contracts

Read local `docs/api-specs/asyncapi.yaml` subscription/response schemas and
checked current official pages on September 20:
[connection](https://docs.kalshi.com/websockets/websocket-connection),
[orders](https://docs.kalshi.com/websockets/user-orders),
[fills](https://docs.kalshi.com/websockets/user-fills),
[positions](https://docs.kalshi.com/websockets/market-positions).
Private updates are not documented as a complete initial account/history snapshot.
