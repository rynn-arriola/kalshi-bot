# D-070 — Poly-style discovery and Kalshi reward tracker

## Reference and design (before implementation)

Read-only Poly source at `10f4daec464265502ad33d109303a2368a562f58`:
`market_selector.py` keeps a ranked head plus rotating bounded discovery tail,
revalidates cached replacements and separates minimum-payout measurement from
entry authority. `live_commissioning.py` releases only flat/clear owners and
defers scans near inventory deadlines. Its `rewards.py` is a projection, not
proof of personal accrual. No Poly file, live process, ledger or account changed.

Adopt bounded exploratory discovery, retain owners, revalidate before admission;
do not introduce a fixed 60-market business setting or copy sports-only filters,
six-hour reward duration, fill-loss estimates or numerical rotation thresholds.
Kalshi catalog and ranking remain the existing owners. Discovery recommendations
are advisory until the separate stream-subscription/admission handoff is built.

Per-program telemetry is separate from financial accounting. Integrate actual
order quote scores at observed sample boundaries; never sum hypothetical entry
rankings as earned rewards. Use exact Decimal and actual pool/duration. Both
sample endpoints must be valid, within five seconds and share an ownership/source
generation. Use the lesser endpoint rate as a cautious sampled approximation,
not a mathematically guaranteed lower bound. Unknown intervals earn no credited
estimate and are explicitly reported. Changed terms under the same program ID
preserve old amounts but block further estimates pending review.

Each report distinguishes sampled gross estimate, qualifying/observed/unknown
time, current estimated hourly rate, time to $1, remaining permitted earning
time and official paid amount (unknown). No reward offsets trading losses or
buys an exit delay. Payout buffer and automatic better-score replacement remain
unconfigured policy, not inferred constants.

Runtime observations must bind actual owned orders to current management,
account, public book and program versions. Private ACK and matching aggregate
depth alone do not prove own-order reflection. Without a verified reflection
producer, show unknown, not a made-up positive rate. Explicit fixture proof
exercises the positive integration offline; it is not production clearance.

Checkpoint immutable telemetry through explicit asynchronous bounded file I/O,
not the financial ledger. Reload accumulated totals but never restore a live
sample; downtime is unknown. Corrupt/oversized/conflicting checkpoints fail
closed. No credential, account or venue request is needed.

Official references inspected 2026-09-21:
[Kalshi liquidity incentive scoring](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program),
[program-level minimum and pending/paid distinction](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them),
[aggregate order-book streams](https://docs.kalshi.com/websockets/orderbook-updates).
Do not infer personal paid rewards or general private/public synchronization from
aggregate deltas or an optional client-order identifier.

## Resource and acceptance gates

- At most 4,096 retained programs; reject saturation rather than evict accrued
  history. At most 16 programs/market and 30 actual quote rows per scoring sample.
- No per-market task/REST read/database scan. Dirty-market runtime observations
  reuse management inputs and validate a shared book once per program batch.
  Checkpoints are explicit snapshots, at most
  one retained I/O operation; never disk writes per book event.
- Discovery catalog bound 10,000 programs, dynamic candidate budget bounded by
  existing managed capacity, no fixed 60; owners are never evicted by a score.
- Synthetic 30/120-market, 10 updates each: CPU <5s, peak <16 MiB, update/loop
  p99 <50ms. Test checkpoint round-trip, gaps/restarts/expiry, duplicate/regressed
  clocks, term changes, actual vs hypothetical orders, reflection/source races,
  program identity isolation, saturation and non-authorizing status.

## Verification

Implemented: `CandidateDiscovery.choose`, `RuntimeSelection.discovery_candidates`,
`RewardTracker.observe_many/progress`, `RecoveryRuntime.attach_rewards` (explicit
offline fixture only), and `RewardCheckpoint.save/load`. Runtime fault status is
sticky on rejected telemetry; retained totals survive and inventory management
continues. Unknown source evidence is not a zero-scoring observation.

Focused verification: 39 tracker/checkpoint/runtime tests and 10 discovery tests.
Coverage includes actual versus hypothetical quotes, shared independent program
scoring, identical-but-new source identity, invalidation gaps, partial quantity,
unsupported account caps, clipping/expiry, clocks, saturation, checkpoint atomic
replace failure, byte/JSON limits, load races, stale writes and joined cancellation.
Reversing runtime reward invalidation in memory makes the catalog-gap regression
fail with false positive accrual; no source file was changed by that negative test.

`scripts/benchmark_reward_tracker.py` final synthetic Windows results:

| Workload | CPU seconds | Peak bytes | Update p50/p95/p99 ms | Loop delay p50/p95/p99 ms |
|---|---:|---:|---|---|
| 30 markets, 300 updates | 0.3281 | 154,725 | 0.932 / 1.572 / 2.104 | 2.578 / 4.484 / 5.877 |
| 120 markets, 1,200 updates | 1.4062 | 524,576 | 0.941 / 1.704 / 1.961 | 2.423 / 4.517 / 5.158 |

Representative inputs: 20 levels/side, one active program/market, two actual
10-contract quotes and explicit synthetic reflection. Includes checkpoint
serialization/restore, not disk/network/venue latency. All declared gates pass.
10,000 catalog programs to 128 candidate capacity: 16.207 ms. Separate boundary
probe, 4,096 levels/side and 16 overlapping programs: 42.427 ms; not a claim that
all maximum-input production workloads satisfy the representative latency gate.

Final full suite: `python -B -m unittest discover -s tests -q` — 1,296 run,
1,295 passed, one expected Windows symlink-privilege skip, 174.810 seconds.
An earlier concurrent-edit run loaded mismatched module revisions and is not
acceptance evidence; the final run above used frozen implementation files.
Actual diff review, `git diff --cached --check`, staged secret-pattern scan and
333 scoped local documentation links pass. D-065 publication uses only this
component's source, tests, benchmark and operating documentation; no data/secrets.
Disabled preflight returns `live_ready=false`, opens no credential, creates no
file and accesses no network. No venue/account call, bot operation or risk change.

## Remaining integration, not hidden completion claims

- D-071 subsequently connects candidate results to the
  [flat/clear subscription handoff](BUILD_MARKET_ADMISSION.md). The tracker itself
  remains advisory; no reward-chasing cancellation or new repricing threshold.
- Production order reflection is unverified. Only explicit fixture injection
  allows positive runtime estimates. Account ACK or aggregate matching quantity
  is insufficient; never label fixture estimates as actual earnings.
- Checkpoint paths, load-before-observation, periodic coalescing and final flush
  must be explicitly owned by the future supervised runtime. This component
  opens nothing on construction and does not install an autosave loop. Keep JSON
  telemetry in ignored local data, never the financial ledger or credentials.
- Source-bound entry dispatch, production transport and existing readiness/
  authorization gates remain. This is not a finished live trader or a guarantee
  of qualifying time, reward payment or net profit.
