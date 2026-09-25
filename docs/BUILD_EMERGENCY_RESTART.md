# D-116: command 1 — cancel, flatten, restart

Explicit operator invocation authorizes canceling this bot's orders and closing
its inventory at available executable prices, with trading P&L and fees. Ordinary
stop/restart keeps the existing passive/timed exit policy. Never operate another
account or adopt unknown orders/positions implicitly.

## Implementation boundary

One generation-bound local request asks the existing child to pause entries and
apply an immediate flatten deadline. Existing terminal cancellation, fresh book,
inventory/account, reduce-only IOC, writer and quota checks remain authoritative.
Late fills after cancellation are reconciled and only remaining inventory exits.
No separate closer, synthetic fill, loss-limit reset or broad process kill.

The command waits for correlated verified-flat cleanup and process exit, then
uses the existing supported launcher. Saved RUNNING or a zero exit code is not
readiness. A finite timeout reports the exact last stage/blockers; stale requests
cannot flatten a later generation. Partial fills use actual execution IDs and
fees. Insufficient liquidity or exhausted IOC policy is an explicit blocker.

## Acceptance

- Normal stop unchanged; emergency deadline bypasses the passive age wait only.
- Both current and subsequently refreshed metadata retain the explicit deadline.
- Wrong-generation/expired/malformed requests cannot authorize flattening.
- Repeated command does not create competing writers or duplicate close orders.
- No normal restart before current terminal flat proof and old-owner exit.
- Timeout/failure is not COMPLETE; status identifies cancellation, flattening,
  reconciliation, launch and ready stages separately.
- Synthetic tests cover request/response correlation, partial-fill and stale-
  source boundaries. Live testing must use an explicitly authorized operation.

Deployment and verification results belong in STATUS, not this design.
