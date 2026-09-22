# Current production-path repairs — 2026-09-22

This implements the four findings in the
[final current-path review](REVIEW_CURRENT_LIVE_PATH_2026-09-22.md). It changes
only the existing supervised live path and its tests. It does not add optional
features, alter configured capital/order size/loss thresholds, authorize a
launch or contact the account.

## Implemented behavior

- A durable $25 loss-window hold is now an effective entry pause. It prevents
  new entry authority, stops admission changes, reports `DRAINING`, queues exact
  cancellation of every proven-owned risk-building order and then preserves the
  existing reducer/IOC rules for naturally remaining inventory. Lower loss-tier
  cap behavior is unchanged.
- Each entry pair pins its exact selection proof, program object, observation
  and validity boundary before reservation. Revocation, replacement, expiry,
  candidate-input change or admission transition fails the synchronous fences
  before and after SENDING. The writer's own preparation revisions remain the
  only tolerated revision advances; an unsent rejected pair is never retried.
- Exact owned-order cancellations use current account, inventory, writer,
  route, command-capacity and quota proof without requiring a current price or
  market-terms object. Creates, reducers and IOC decisions still require the
  existing fresh market/book/terms proof.
- Selection now freshness-adjusts and qualifies every bounded per-market reward
  program before choosing exactly one. $2+ programs retain priority over the
  $1–<$2 fallback, then existing hourly-rate, efficiency and identity ordering
  applies. Overlapping programs are never summed or allocated twice.

## Verification

Permanent regressions exercise the nonfixture production activation/transport
path for reward revocation both before SENDING and immediately after SENDING,
plus proof expiry. Runtime integration tests cover hard-loss cancellation and
paused cancellation with both stale book ingress and revoked terms. Selection
tests cover a below-$1 fast program hiding an eligible program and a higher-rate
fallback hiding a $2 priority program.

Focused selection/live/dispatch-source tests: 106 passed. Related accounting,
admission, production-supervisor and incentive-discovery tests: 104 passed.
All 30/120-market selection, admission, dispatch-source and entry-dispatch
benchmarks passed. The representative selection loop p99 was 13.507/30.342 ms;
dispatch-source candidate p99 was 3.619/5.754 ms. These are synthetic engineering
checks, not live execution or profitability evidence.

Final complete suite: 1,441 tests in 218.486 seconds, with 1,440 passed and one
expected Windows symlink-privilege skip. The corrected 1,024-candidate input
parsed successfully. A 45-second GET-only startup initialized account, book and
lifecycle streams, fresh quota, healthy logging and 4,936 current incentive rows;
`startup_verified=true`, `process_stopped=true`, and no dispatch was attached.
Its launch-only opening/timing/fee blockers and `trading_ready=false` are expected
for that deliberately read-only diagnostic. First supervised live acceptance
remains a separate operator action under the existing run guide.
