# D-093: broad reviewed books with shared bulk metadata

Implemented September 23, 2026; not deployed or restarted. Authority is D-093.
This replaces the normal live composition's slow 128-book subscription rotation,
not its order, cash, loss, ownership or execution rules.

## Integration

- `live.compose` first validates durable owners, then observes all launch-reviewed
  tickers (maximum 1,024) across the existing two hash shards. Recovery-only keeps
  its narrow protected scope and existing admission owner. Normal broad mode
  cannot attach a competing rotating subscription owner.
- Account/writer capacity remains 128; 10-contract entries, 30 resting entries,
  $500 capital, $300 aggregate exposure, $90 market exposure and fixed six-hour
  settled-loss rules are unchanged. Reviewed candidates are not order slots.
- Large book readers use 2,048 events / 8 MiB per connection. Small book and
  account queues retain 256 / 2 MiB; lifecycle retains 8,192 / 16 MiB. Overflow,
  sequence gaps, reconnect generations and quiet-book snapshots retain their
  existing fail-closed behavior.
- `BulkEventInputs`, owned by `ExitInputService`, batches at most 50 events and
  2,048 query characters through the existing shared REST budget. Public
  `/events` supplies nested definitions and milestones. The original query UTC
  and monotonic timestamps remain on cache hits; TTL remains at most 60 seconds.
- Existing market/event/milestone parsers, rules reviews and lifecycle overlays
  remain authoritative. Duplicate/missing identities, unexhausted pagination,
  stale responses and stream conflicts block publication. Group versions and
  reset generations fence in-flight responses; shutdown joins owned loaders.
- Series definitions, complete event/series fee-change reads and member fee
  precision checks remain required. Bulk events are **not** fee schedules.
- Management reuses immutable durable inventory only at the exact writer epoch,
  revision and subaccount, bounded by the reviewed scope. Every write invalidates
  it; time/book/account/terms checks and exit planning still run each evaluation.
- Changed books still drive ranking. Broad mode coalesces entry work into at
  most one ranked key per 250ms turn, only with an empty, idle dispatcher and
  current account release. Checks repeat after the proposal await. Cancellation
  and inventory requests retain their existing immediate priority path. The
  dispatch source reproposes and validates again before reserving or sending.
- Status exposes `discovery_mode=broad_reviewed`. Existing selection exclusions
  describe current failures; a historical proposal is never execution authority.

Source contract: [local API reference](KALSHI_API_REFERENCE.md#openapi-yaml-get-events),
[official Get Events](https://docs.kalshi.com/api-reference/events/get-events),
and the [D-092 measured comparison](RESEARCH_DISCOVERY_OPTIONS_2026-09-23.md).
No REST book scanner or additional service/process was introduced.

## Public-only acceptance

Command: `python scripts/check_live_market_gates.py --read-only-live-check
--source-root C:\Users\rynna\Bots\kalshi --markets 1024 --broad`.

Final local artifact:
`data/market-gate-census/938464f211bd44b9a654c8f841134ef8/result.json`.
04:41:25–04:42:55 UTC, **90.073 seconds**, 570 public REST requests / 5,129,984
response bytes. Actual production per-reader queue bounds and existing live WS
snapshot refresh were used. All 1,013 current reviewed/rewarded markets were
examined with no metadata/book-source error: **150 pass**, including **28 $2+
priority** and **122 $1-only fallback** candidates. No private REST, ledger,
orders, account admission or production runtime was used.

The earlier census took 415.320 seconds / 2,563 requests: approximately **4.6x
faster and 78% fewer requests**. These are different observation times, not a
controlled profitability comparison. Reward prices/counts can change.

An initial D-093 diagnostic retained the old seed-first ordering and lacked
source-convergence retry: 140.950 seconds / 905 reads / three publication-expiry
failures. Retained artifact `3c31ed501fae4288b0325e8fc78e8922` is explicitly
PARTIALLY_COMPLETE. The final broad diagnostic follows the production metadata
scheduler's sorted bootstrap order and bounded retries; the real scheduler's
expiry-during-fee-read recovery is also tested. HTTP refusal still latches;
neither diagnostic retries refused network requests.

**Limits:** economic observations are sequential, not 150 simultaneously
admissible markets. Full fees/metadata are not available in 0.56 seconds; that
older number measured initial books alone. This is not guaranteed earnings,
full account/recovery acceptance, or proof all 1,024 metadata rows stay current
simultaneously during sustained live load. No freshness or economic filter was
relaxed to obtain these results.

## Offline verification

`scripts/benchmark_broad_discovery.py` uses actual engine, management, selector
and a disposable real writer: five 1,024-book burst/reconnect rounds; fixed
source-clock fixtures with real elapsed/CPU measurements. Initial ranked slate
0.631s; warm slates 0.310–0.375s; proposals 54–74ms; 1.984 CPU seconds over 2.012
wall seconds; sampled working set 53.3 MiB. All 5,120 evaluations finish, only
1,024 inventory reads, no book failures, 15 proposed pairs and no venue writes.
Loop/private-sentinel/due-sentinel p99: 61.51 / 61.17 / 61.12ms, under the 100ms
diagnostic target. These are scheduling sentinels, not real cancel/fill latency.

The first harness synchronously generated entire synthetic bursts, producing a
138ms loop p99 failure. Chunking fixture production every 32 records, like
yielding transport producers, resolved that harness bottleneck. No production
latency improvement is attributed to that fixture-only adjustment. Sustained
real account contention and maximum-depth books are not this workload.

Regressions cover 1,024-market ranking, unchanged caps, bounded entry handoff,
safety priority, account-source races, exact-revision inventory caching,
bulk coalescing/TTL/cancellation/generations, incomplete payloads and complete
fee-source enforcement. The existing composed live graph tests now exercise
broad/bulk startup to fake pair ACK, including unsupported-fee rejection.

Complete suite: 1,519 run / 1,518 pass / one expected Windows privilege skip in
239.829s. Final targeted rerun: 100 pass in 22.951s, covering the final query
validation and three additional bulk boundary tests. Exact diff review found no
blocking implementation issue. Documentation: 482 relative links resolve and
`git diff --check` passes. Current state is recorded in [STATUS](../STATUS.md).

## Operations boundary

No live inputs, secrets, writable production ledger or runtime state changed.
No bot restart/deployment occurred. Host continuity and evidence-based
reconciliation of the operator's manual cancellations remain separate
pre-restart work in [NEXT](../NEXT.md). An explicit authorized launch is still
required; this implementation is not a claim that the bot is currently trading.
