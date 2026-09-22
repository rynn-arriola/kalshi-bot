# Bounded incentive discovery — D-069 continuation

Offline implementation scope: one runtime-owned catalog refresh using the
existing shared `RestReads` and account-wide budget. No new HTTP transport,
account request, subscription mutation, order, configuration or live activation.
The catalog supports future subscription admission but does not choose a new
market set or evict any inventory owner.

## Contract and resource gates (before implementation)

- REST `/incentive_programs`, `status=active`, `type=liquidity`; no documented
  incentive WebSocket exists. Complete bounded cursor enumeration is required;
  cursor exhaustion is not an atomic venue snapshot. Reuse the recorded
  [operation and schemas](KALSHI_API_REFERENCE.md).
- At most 10,000 rows, 100 pages, 8 MiB response bytes per enumeration, 100 rows
  per request, one refresh worker, 30-second attempt deadline, three attempts.
  Parse in 128-row chunks with event-loop yields. Never fetch books by REST.
- Default refresh/validity 300 seconds, configurable 60–3,600 seconds. Freshness
  starts before enumeration, not after parsing. New refresh, failure, expiry,
  stop or invalid source revokes the old catalog. No stale-while-error ranking.
- Unsupported program terms exclude the whole identified market; broken scope,
  duplicate program IDs or enumeration bounds reject the complete publication.
  At most 16 programs per market. Empty complete publication revokes old rows.
- Account/private recovery work takes precedence; quota holds do not consume
  market-data retries. Exhausted attempts require explicit retry and preserve
  cooldown. Coalesced invalidations cannot publish an older in-flight result.
- Runtime selection consumes identity-bound immutable observations; construction
  opens nothing. Shutdown joins this service before shared read teardown. Shared
  read requests remain owned by `RestReads` even if a catalog waiter is cancelled.
- Synthetic 30/120 subscribed-market fixtures against 5,000 and 10,000 catalog
  rows: CPU <5 seconds, traced peak <32 MiB, event-loop delay p99 <50 ms.
  Include publication/invalidation, not only parsing. These are component gates,
  not whole-runtime latency or live reward evidence.

## Verification

26 focused tests pass with synthetic wire responses and disposable ledgers.
The actual shared read service, runtime, event engine and selection attachment
are exercised. Tests cover complete/empty/multi-page publication, cycles,
duplicates, provenance/limits, unsupported terms, paid/ended/future programs,
expiry, clock faults, quota loss, retry exhaustion/cooldown, coalescing, retained
wire ownership, runtime failure/stop and publication/portfolio-await races.
The 42 existing selection tests also pass. Removing the final generation fence
in memory makes the late-publication regression fail; no source was weakened.

Measured native Windows component results with actual injected pagination:

| Subscribed / catalog rows | GETs | CPU / wall seconds | Peak bytes | Loop p50/p95/p99 ms | Publish / invalidate ms |
|---|---:|---|---:|---|---|
| 30 / 5,000 | 50 | .2812 / .3048 | 7,178,112 | 1.157 / 10.428 / 20.456 | .265 / 10.767 |
| 120 / 10,000 | 100 | .5938 / .5956 | 13,566,285 | 1.113 / 10.326 / 14.148 | .460 / 23.364 |

Both declared gates pass. Prebuilt synthetic response bytes are outside traced
allocation; decoding, enumeration, normalization, publication and invalidation
are inside it. This is not a live network/whole-runtime benchmark or evidence
that an actual account quota can finish the catalog within 30 seconds.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bot_incentive_discovery.py -q
.\.venv\Scripts\python.exe -B scripts/benchmark_incentive_discovery.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

Final full suite: **1,247 run, 1,246 passed, one expected Windows symlink-privilege
skip**, in 175.399 seconds. Exact diff review, 328 local Markdown links,
whitespace and scoped staged secret-pattern checks pass. No known blocking
finding remains in this discovery component. Disabled preflight returns
nonzero and reports `live_ready=false`, no created files, credentials or network.
D-065 requires commit/push/parity for this verified unit; publication is source
synchronization only, not deployment.

## Interfaces and remaining integration

`RecoveryRuntime.attach_incentives(offline_fixture=True)` requires an attached
selector, unused runtime, and the same shared `RestReads` monotonic clock. It
replaces manual program-fixture ownership without touching inventory or writer
state. `request(retry=True)` is the explicit retry of an exhausted catalog;
ordinary requests retain failures and cooldown. Status contains bounded counts
and static failure state, never raw payloads or exception text.

The catalog is an immutable active-liquidity enumeration, not a recommended
market set, account proof or book snapshot. Unsupported markets are excluded
rather than truncating their programs or inventing reward fields. Refresh uses
a distinct observation scope, preventing a retained older wire call from being
re-aged after caller timeout. No credentials/venue calls were used to verify it.

The runtime joins the catalog waiter; the caller still owns shared `RestReads`
closure, which drains any retained wire work. There is no new HTTP client,
per-market worker, ledger mutation or automatically launched native process.

Subscription rotation, working-order reflection, entry-pair dispatch and
runtime/live readiness remain unfinished integration. New subscriptions must
retain inventory/unknown owners and rebind stream/metadata generations. No
additional strategy decision, sports filter or payout hard gate was introduced.
