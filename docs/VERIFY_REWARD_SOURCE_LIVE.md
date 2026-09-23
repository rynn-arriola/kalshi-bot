# Predeployment live market-data verification — 2026-09-22

Operator request: “Cant we test that before we run.” Executed a bounded,
read-only source check of D-086 without deploying/restarting the trader.

## Measurement

Started **21:19:21 Eastern** (2026-09-23 01:19:21 UTC), followed by a 30.197-second
WebSocket observation. Public-only incentive reads were paced at one request per
second, with existing response/enumeration bounds and no retry after refusal.

| Check | Result |
|---|---:|
| Complete catalog | 5,006 programs / 6 pages |
| Active supported reward markets | 5,000 |
| Catalog duration / bytes | 5.376 s / 1,904,358 |
| Saved-seed markets with current rewards sampled | 128 |
| Book connections / initial snapshots | 2 / 128 |
| Valid correlated refresh snapshots | 1,135 |
| Incremental book deltas | 65 |
| After-warmup comparisons | 48 half-second samples |
| Baseline average fresh books | 4.81 |
| Refreshed average fresh books | 128.00 |
| Final baseline / refreshed fresh books | 2 / 128 |

**MEASURED, same-feed comparison:** both counters observe the same validated
stream. The baseline clock advances only on initial snapshots and ordinary
deltas; the refreshed clock also advances on requested snapshots. Both use the
unchanged five-second gate. This isolates freshness contribution without a
second old-version socket/client. It is not two independent production runs.
All delivered book frames pass the current sequence/depth validator; mismatches
fail the probe. Both connections were canceled and joined at completion.

This establishes venue compatibility and substantially better fresh-book
coverage for this sample/window. It does **not** establish 128 entry-eligible
markets, 30 order placement, net profit or guaranteed reward. Timing, fees,
70% retained value, $1/$2 projections, account state and available slots were
not evaluated. The public request pacing is not the live shared account budget.
No full-universe economic eligibility count is inferred from 5,000 definitions.

## Safety and reproduction

`scripts/probe_reward_sources.py` requires an explicit read-only flag. It loads
the existing signing files only for public-book WebSocket authentication. Its
REST adapter rejects private/unrelated paths and authentication headers. No
private streams, mutation client, trader runtime, ledger or candidate update is
constructed. A dedicated local lease prevents duplicate probes; state/traffic,
duration and market scope are bounded. Raw keys/account payloads are never saved.

```powershell
.\.venv\Scripts\python.exe -B scripts/probe_reward_sources.py --read-only-live-check --source-root C:/Users/rynna/Bots/kalshi --seconds 30 --markets 128
```

Local evidence: `data/source-probe/8cd5699c4f8f4201b943c291e078d0f9/result.json`
in the isolated fix checkout, ignored by Git. Four synthetic probe tests and
15 existing book-refresh tests pass. Review confirms no production package or
configuration edits in this verification unit. Full repository suite was not
rerun for the diagnostic-only addition; the unchanged runtime's prior full-suite
result remains recorded in the [build report](BUILD_REWARD_SOURCE_REFRESH.md).

Saved production status at 21:20:31 Eastern still identified PID 46576, 14
resting entries and no positions. Catalog exhaustion remained held and the
lifecycle stream independently reported `retry_exhausted`. No hold was cleared,
process restarted or venue order changed by the probe. That lifecycle failure
needs separate diagnosis; the source test does not establish full bot readiness.
