# D-062 — Opening-account and cash evidence contract

Date: September 21, 2026. Native Windows, execution disabled. D-062 is the
continued priority-order build assignment recorded in `DECISIONS.md`. This design
continues D-044 after D-060 cleared the command handoff. It does not select an
account boundary, authorize live reads, install opening lots, reset risk, or
grant entry authority.

Update: D-064 subsequently selected exclusive primary subaccount 0 and a
verified flat start. The exact boundary and fresh account proof remain open;
the earlier undecided-account language below is historical design context.

## Verified venue boundary

Current official documentation was rechecked on September 21, 2026. User fill
and order WebSocket messages are immediate updates, but the published contract
still provides no replay cursor, shared REST/WebSocket watermark, snapshot
barrier, or late-publication bound. Market-position updates remain unscoped by
subaccount in the published message. Therefore Phase 2 cannot positively prove
the handoff and `venue_handoff_proven` must remain false.

The current REST contract does provide scoped, paginated recent and historical
fills; historical fills now document a `subaccount` query. Positions, balance,
settlements and historical positions are subaccount-scoped. Balance reports
available balance, portfolio value and its own last-update timestamp, but it is
not atomic with positions, orders, fills, settlements or transfers. Settlements,
subaccount transfers, intra-exchange transfers, deposits and withdrawals are
separate paginated histories.

Sources:
[user fills](https://docs.kalshi.com/websockets/user-fills),
[user orders](https://docs.kalshi.com/websockets/user-orders),
[market positions](https://docs.kalshi.com/websockets/market-positions),
[fills](https://docs.kalshi.com/api-reference/portfolio/get-fills),
[historical fills](https://docs.kalshi.com/api-reference/historical/get-historical-fills),
[positions](https://docs.kalshi.com/api-reference/portfolio/get-positions),
[balance](https://docs.kalshi.com/api-reference/portfolio/get-balance),
[settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements), and
[historical routing](https://docs.kalshi.com/getting_started/historical_data).

## Implementation contract

1. Add only GET allowlist entries for the documented evidence sources. Require
   explicit reasons, bounded pagination, strict schemas, exact decimals,
   subaccount filtering and duplicate/conflict rejection. Update historical fill
   recovery to send the now-documented subaccount filter.
2. Add immutable normalized observations for balance, settlements, transfers,
   deposits and withdrawals. Keep the source records and pagination metadata;
   counts or a balance delta alone are not evidence.
3. Build one explicit, bounded opening-account inspection from an already-current
   reconciliation report and continuity assessment. Capture writer epoch/
   revision before and after all reads. Any account event, writer mutation,
   stale report, scope mismatch, incomplete page, source conflict or capacity
   overflow invalidates the result.
   Bind every page set to its endpoint and initial query; reject narrowing
   filters, resumed cursors or missing terminal cursors. Join all bounded reads
   before reporting a source failure. Retain both snapshot and inspection times.
4. The result is evidence for operator review only. It always retains blockers
   for the unproven venue handoff, non-atomic cash snapshot, unapproved boundary,
   unapproved account exclusivity and uninstalled opening basis. Existing
   positions, foreign/resting orders, pending fills or unresolved basis add exact
   blockers. It cannot set `approved`, `ready_for_entry`, `entry_allowed` or
   `live_ready` true.
5. Do not write these observations into the trading ledger yet. A durable
   baseline would be an authority-changing schema contract and needs the
   operator's exact account/subaccount, exclusivity, boundary timestamp and
   pre-boundary inventory decision.

## Acceptance

Use injected responses only. Test strict source normalization, scoped historical
fills, cursor exhaustion, duplicate/conflicting rows, revision races, bounded
histories and a complete-looking flat fixture that still cannot grant authority.
Run impacted tests, the full suite, disabled preflight and secret/diff checks.
No credential, account, network, configuration, deployment or process action is
authorized.

Resource scope: at most six concurrent logical reads using the existing shared
REST budget; each history is limited to 50 pages, 10,000 raw rows, 8 MiB and
30 seconds. No periodic loop or per-market consumer is added. The existing
five-second account report freshness remains unchanged; a slow inspection is
discarded. One retained inspection owns all reads and sequential 512-row
normalization jobs off-loop, with global duplicate checks and final assembly;
caller cancellation cannot start overlapping work. Recheck state after
normalization. For synthetic 128/4,096 total rows across five sources, measure
wall/CPU time and peak Python allocations; target <250 ms and <40 MiB. Also
exercise 50,000 total rows (10,000/source) at <3 seconds and <40 MiB, with
event-loop p99 <50 ms. Measure normal latency separately from allocation-tracing
overhead. This is a control-plane inspection, not a public-event operation or
live throughput claim.
