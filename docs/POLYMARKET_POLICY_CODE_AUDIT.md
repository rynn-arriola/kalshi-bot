# Polymarket capacity, accounting, selection, exits and restart audit

September 20, 2026. Read-only executable source at
`C:/Users/rynna/Bots/liquidity-bot`, clean HEAD
`54ac71a241d1ad6f02e3445655bb7115247bac02`.
This establishes checkout behavior, not an already-running process's settings.
No external API, credentials, real trading data or WSL execution was used.

## Capacity: use the user's limits, not an invented market target

The operator clarified that Kalshi market capacity should follow its limits.
At the full 30-entry allowance, 15 two-sided markets or 30 one-sided markets
would exhaust the entry count, before capital, exposure and eligibility gates.
Mixed sides consume the same order budget. Inventory management remains outside
that count, but continues to consume conservative dollar exposure and resources.
Track and manage inventory even when it no longer occupies an entry slot.

Polymarket itself has a separately configured slot ceiling (`slot_capacity.py`),
not an automatic inversion of capital into markets. `commissioning.py:303`
computes two entry orders per configured market; the risk-window policy further
limits entries to 30. Lines 360/366 independently compute market exposure as
9*size and portfolio exposure as size*(max_markets+10).

Do not set Kalshi to 30/32 slots or assume $400/$420 from this clarification.
Do not let an exposure limit grow automatically because current occupancy grows.
The dynamic admission design must resolve the old slot-dependent exposure formula
without weakening approved limits or using circular capacity calculations.
The $500 capital ceiling is not automatically a newly approved replacement for
the separate portfolio exposure rule. Discovery/technical capacity is separate.

## Partial closures and the actual loss-meter call path

`live_commissioning.py:4737` calls `ExecutionLedger.realized_pnl` with
`received_since=window_start` and `received_through=snapshot.observed_at`.
`execution_ledger.py:2058` replays non-reversed durable executions through
`pnl.py:MatchedInventory.apply` with older fills retained for opening basis.

Actual behavior:

- Every opposite-side matched quantity realizes gross P&L immediately, including
  a partial close. The remaining open quantity produces no gross marked loss.
- Basis is weighted average cost, not FIFO. Same-direction fills recompute that
  basis; a flip leaves the unmatched remainder at the incoming fill's cost.
- Actual observed fees are charged immediately on every fill, including fills
  that leave inventory open. They are not deferred/prorated until matching closes.
- The stop meter attributes by durable receipt time, sorted by receipt, event
  time and execution ID. A delayed loss is charged when learned; it is not moved
  back to a completed execution-time risk window. Historical reporting can use
  execution time instead; those clocks must not be conflated.
- `risk_windows.py:155` persists the minimum cap reached within the window and
  sticky trips. A restart or later profit does not widen that window's cap.

Example ignoring fees: opening 10 at .50 then closing 4 at .40 realizes -.40
immediately, with six still open. The paper value of those six is excluded.
An opening fee of .10 is nevertheless charged in full at its receipt under Poly.

**Historical difference at audit time (superseded by D-024 implementation):**
the Kalshi candidate was FIFO, with opening and
closing fees allocated to matched quantities, and receipt-time close attribution.
The earlier proposed execution-time late-fill approach was not a verified Poly
copy. Neither the new audit nor "check Poly" authorizes changing accounting.
The operator subsequently approved the source-verified accounting in D-024,
including immediate fees on unmatched inventory. See [implementation](BUILD_ACCOUNTING.md).

## Selection and rotation: filter first, rank, retain useful owners

`market_selector.py:324` evaluates each side: event/tick availability, minimum
price and spread, reward eligibility, stressed exit depth and entry-quality
checks. `_opportunity_key` at line 472 orders viable rows first, then day-of
program phase, projected reward, expected-net tiebreak, historical reward-yield
prior and other tiebreaks. `top_viable` excludes barred/nonviable rows before
applying the count limit. This is not a raw headline-pool ranking.

The projected reward uses a common short horizon. The reward-cost veto defaults
off in this checkout (`commissioning.py:230`); expected net is then advisory and
can be floored. Consequently it must not be presented as a proven net-profit
ranking. Sport-specific paid-reward priors and phase preferences are not Kalshi
evidence. Do not copy them, the .02 spread/.10 price thresholds or disabled veto
as newly approved Kalshi strategy.

`live_commissioning.py:8579` tops up free slots without canceling healthy owners.
It requires clean ownership/flatness for released markets and an actual viable
replacement for optional economic-idle rotation. Config uses a 900-second scan
and 600-second continuous economic-idle dwell. Inventory deadlines take priority.
Transfer the separation of eligibility/rank/admission/rotation, not unapproved
timers or automatic cancellation of every market that drops in rank.

## Exits: exact remaining quantity, then confirmed deadline escalation

`commissioning.py` supplies 900-second ordinary inventory evaluation, size*.8
early-cross loss allowance ($8 at size 10), and five-minute pre-kickoff boundary.
`reconciler.py:493` cancels building risk, works exact reducers, and requires
terminal cancellation evidence before IOC. Ordinary crossing can defer for
insufficient depth or excessive projected loss while passive protection remains.
Event/maintenance/HARD deadlines override ordinary deferral, not liquidity or
ownership constraints. Bounded failures escalate rather than claim flatness.

Nuance omitted from earlier short summaries: `exit_quote_price` at line 244 can
improve a newly needed reducer one tick if that price does not cross the opposite
touch or lose against entry basis. That is a price comparison, not fee-inclusive
profit proof. Losing reducers still join the touch with no break-even floor.
At line 691 onward, an existing exact reducer already at the touch is retained,
avoiding repricing against itself. Kalshi's current helper takes a supplied touch;
it does not yet implement all of these source-specific price/deadline branches.

Tiny .01-.09 residuals have a 300-second, venue-aligned exception in Poly.
It and sports kickoff rules are not automatically valid for Kalshi markets.
No new Kalshi event deadline or IOC policy was chosen in this audit.

## Restart versus loss-stop release

`live_commissioning.py:11360` onward distinguishes refusal/integrity/no-flatness
from recoverable failures. `scripts/supervise_commissioning.sh:127` reads exit
codes: 0 ends cleanly; 2/3/4 enter attention without relaunch; 5 permits retry.
Other unexpected exit codes also enter bounded retry, not permission to trade.
Backoff is 10 seconds doubling to 60; three consecutive runtimes shorter than
120 seconds trigger attention. This is not three crashes in a rolling two minutes.
The shell was inspected as text only; no Bash/WSL/service was run.

A restarted process repeats startup ownership/account proof and may enter a
scoped recovery-only path. Process restart does not erase unresolved orders,
inventory, durable entry-cap ratchets or loss holds. Never translate this into
"restart means safe to quote" or blindly retry an ambiguous creation.

`live_commissioning.py:5377` permits later-window loss-hold release only after
fresh reconciled account/equity evidence, healthy gates, no stream rebind pending,
no positions, working/absent orders or unresolved intents. `risk_windows.py:201`
releases only expired windows. Keep manual clean stop and integrity failures
distinct from recoverable transport trouble in a future native Windows design.

## Verification and limits

216 source tests passed on native Windows: `test_pnl`, `test_risk_windows`,
`test_market_selector`, `test_reconciler`, `test_execution_ledger`.
The first test command lacked the source path and failed imports; rerunning with
`src` and `tests` inserted into the interpreter path passed without installations
or repository edits. No shell supervisor tests were executed. Source/test evidence
is not a live deployment check. Kalshi implementation/config was not changed.

Outstanding: approve accounting differences, map dynamic capacity to an explicit
non-circular exposure rule, and approve Kalshi-specific selection/exit/restart
details. The operator requested reference inspection, not blanket adoption of
every Poly setting. No live activation authority was granted.
