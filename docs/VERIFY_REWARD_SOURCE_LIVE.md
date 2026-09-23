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

## Reference-price follow-up — 21:45 Eastern

The follow-up audit first checked the current official liquidity rule and
order-direction guide. The rule defines each side's Reference Price as the first
level where cumulative size reaches one fifth of Target Size. This runtime's
book subscription explicitly sends `use_yes_price=true`, so Kalshi reports its
NO-side book levels on the common YES-price scale. Those values are already YES
asks and must not be complemented again.

A second 30.140-second read-only run independently walked the raw unified wire
ladders and compared them with the production reference helper:

| Check | Result |
|---|---:|
| Complete catalog | 4,998 programs / 5 pages |
| Active supported reward markets | 4,992 |
| Sampled current rewarded books | 128 |
| Unified NO-ladder checks | 128 / 128 matched |
| Program/reference comparisons | 128 / 128 matched |
| Sides reaching one-fifth depth | 246 |
| Initial / correlated refresh snapshots | 128 / 1,139 |
| Final baseline / refreshed fresh books | 2 / 128 |
| Private REST / order mutations | 0 / 0 |

The integrated regression starts from a real WebSocket-shaped snapshot and
proves the generated initial quote levels equal the independently expected bid
and ask references. Local Gemini and Polymarket implementations were also
inspected: both use a common YES/LONG economic frame and complement the opposite
outcome at their venue boundary. That comparison is supporting consistency only;
Kalshi's official `use_yes_price` contract and observed wire data are the
authority.

Local ignored evidence:
`data/source-probe/113659f8407341c6a1ceb40ecf4bbfbe/result.json`.
The run did not assess fees, account state, retained-value eligibility, projected
payout, available slots, fills or profitability. Reference correctness alone
does not guarantee a quote will pass every gate or earn at least one dollar.
