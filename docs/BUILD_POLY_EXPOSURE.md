# Polymarket-derived exposure calibration

D-031, September 20, 2026. Native Windows; no live activation.

## Executable reference

Read-only Poly checkout: `C:/Users/rynna/Bots/liquidity-bot`, clean HEAD
`51cf59548b8e339be790e0662b6594ff0af77ddc`. This differs from the older audit
commit; current code was rechecked rather than relying on Markdown.

- `src/liquidity_bot/slot_capacity.py:11`: default capacity 20.
- `commissioning.py:137`: config uses that default.
- `commissioning.py:360`: market exposure is `9 * quote_size`.
- `commissioning.py:366`: portfolio exposure is `quote_size * (max_markets + 10)`.
- `commissioning.py:554`: diagnostics use a validated runtime override if
  present, otherwise the default. No local override file existed at inspection.
- `scripts/start_commissioning.sh:12` and `supervise_commissioning.sh:11`:
  third argument defaults to 20. Inspected as text only; no shell execution.
- `live_commissioning.py:781`: passes derived dollars into the reconciler.
- `reconciler.py:857`: rejects entries beyond the exposure budgets.

The actual reference diagnostic config, evaluated with Kalshi's approved size
10, returned 20 slots, $300 portfolio and $90 market exposure. This is local
checkout/default evidence, not a running-process, remote-host or historical
32-slot setting. Poly's fallback quote size is not copied.

## Implementation

The operator said "Just follow poly" instead of accepting a new fixed $400
ceiling. `config/bot.json` and `BotConfig()` now use the verified reference
capacity 20: `10 * (20 + 10) = $300`. The policy CLI exposes the reference input.
Existing pure admission and atomic writer reservations enforce the formula.

D-023 still makes actual Kalshi entry breadth limits-driven. The legacy field
`managed_market_slots` calibrates exposure; it is not current occupancy or a new
20-market admission ceiling. The budget never grows as inventory accumulates.
The technical 128-market tracking bound is separate. No future Poly config changes
are automatically synchronized; reconfiguring risk requires operator review.

Inventory, working orders including reducers, and deduplicated uncertain sends
share the exposure allowance. Reducers are exempt from entry count only. The
$500 capital, available cash, $90 market exposure, 30 entry orders and six-hour
loss ratchet remain independent gates. Exposure is not a guaranteed loss cap.
Explicit unresolved configuration (`managed_market_slots=None`) still blocks.

## Verification and limitations

- 510 Kalshi tests pass, 38.252 seconds, including 12 new regressions.
- New tests cover exact $300 boundary, $0.0001 overrun, occupancy independence,
  more than 20 markets below limits, separate count/cash/market gates, explicit
  unresolved config, CLI reporting, and atomic inventory-plus-reducer exposure.
- 104 actual Poly commissioning/reconciler tests pass, 0.307 seconds, using its
  existing Windows environment. An initial run in Kalshi's minimal environment
  had 30 import errors for missing `httpx`; no dependency installed. Re-running
  with Poly's environment passed. Its Git worktree stayed clean.
- Two in-memory fault reversals detected: replacing the derived cap with $400,
  and removing portfolio-overage rejection. Context-managed patches restored;
  no production-file mutation for those checks.
- The property remains O(1); existing bounded scans unchanged. No new load or
  performance claim. Offline tests are not paper trading.
- Policy remains live-disabled; preflight returns `live_ready=false`, exit 2.

No credentials, venue requests, orders, ledger imports, Poly modifications or
trading processes. Kalshi lacks Git metadata; no commit or parity claimed.
Production account/cash/history proof, Kalshi exits, selection/execution
integration and supervised launch remain unfinished and outside this change.
