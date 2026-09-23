# Reward-source repairs — D-086

Scope: the two actionable omissions in the [API audit](REWARD_API_REAUDIT_2026-09-22.md).
No ranking formula, market capacity, order limit, economic filter, accounting
baseline or retry-exhaustion policy changes. No personal reward API was found;
the existing estimates must still be distinguished from paid credits.

## Catalog

Runtime discovery owns one shared immutable query, reused by candidate
preparation: active liquidity programs, 1,000 rows per page. The existing
2 MiB response, 8 MiB enumeration, 10,000-row, 100-page, 30-second and three-attempt
bounds remain. Complete cursor enumeration, duplicate/provenance checks,
account-read priority, fresh observation scope and invalidation remain mandatory.
This reduces request count, not a promise of live latency or fixed token savings.

## Quiet books

`BookRefresh` is local to each book socket/generation. Only a valid subscription
ACK installs its SID. One control task checks the bounded subscribed set twice
per second; markets without a book frame for three seconds become candidates.
Frequently updated markets do not receive redundant snapshot requests.

- Use documented `update_subscription/get_snapshot`, never a REST book poll.
- One in-flight request per socket, at most 100 tickers, oldest first. Maximum
  supported state is 1,024 tickers; production capacity remains 128 across two
  book connections. No worker per market or unbounded outbound queue.
- A two-second send deadline and five-second whole-batch response deadline;
  partial responses/deltas do not extend it. Requests coalesce while pending.
- Validate SID/ticker and the command ID when present. The published optional
  ID can be absent; it never replaces stream scope/sequence validation.
- Replies use the existing book engine in wire order. Gaps, replays, old reader
  generations, malformed depth and crossed books still invalidate authority.
  Snapshot refresh never repairs a failed generation in place.
- Timeout, rejected command or send failure uses the existing reader failure,
  invalidation and bounded reconnect path. Shutdown joins the control task;
  no lingering sender or independent retry loop remains.
- A request/ACK/Ping does not update book age. Transport assigns receive time
  before decoding/queuing; runtime carries it into the event engine. Queued old
  snapshots cannot acquire fresh timestamps when finally consumed.

The existing five-second book gate is unchanged. This can refresh quiet books,
but does not guarantee every book remains fresh under network/backlog failure.
Actual venue snapshot sequencing and workload behavior still need controlled
live acceptance. No live command was sent to test this repair.

## Verification and release

Synthetic tests cover correlation, absent IDs, wrong SID/ticker, duplicate/late
responses, partial batches, timeout, active-market suppression, bounded fairness
at 1,024 markets, contiguous/gapped sequence, generation replacement, reader
cancellation and delayed ingress. The actual runtime/selector fixture recovers
one eligible pair after a fresh snapshot without reconnecting or writing orders.

Catalog regressions enumerate 5,000 rows in five bounded responses and reject
an oversized response. Existing incomplete/cyclic pagination, source expiry,
quota loss, stop and exhausted-retry tests remain active. The five breadth
characterizations still pass: stale data is still blocked and unchanged limits
allow 30 orders when 40 synthetic qualifying markets have sufficient fresh proof.

The updated catalog benchmark passes its existing CPU <5 s, peak <32 MiB and
event-loop p99 <50 ms gates:

| Subscribed / rows | Requests | CPU / wall s | Peak bytes | Loop p99 ms |
|---|---:|---|---:|---:|
| 30 / 5,000 | 5 | .2656 / .2642 | 7,115,063 | 22.847 |
| 120 / 10,000 | 10 | .5000 / .5620 | 13,490,454 | 27.686 |

These use synthetic wires and disposable ledgers, not production traffic or
profitability evidence. Final full suite: 1,471 run / 1,470 passed / one expected
Windows privilege skip in 227.536 seconds. Publication state is owned by STATUS.

`scripts/benchmark_book_refresh.py` measures only controller bookkeeping over
120 scheduler turns / 60 virtual seconds, not network or book-depth throughput.
Both declared gates (CPU <1 s, peak <2 MiB, max turn <20 ms) pass:

| Markets | Requests / replies | CPU s | Peak bytes | Max turn ms |
|---|---|---:|---:|---:|
| 128 | 39 / 2,532 | .0156 | 59,352 | .095 |
| 1,024 | 115 / 11,500 | .0781 | 232,224 | .477 |

One first full-suite run timed out in the existing admission ownership fixture.
Twenty-five isolated runs passed on each source version. Injecting one normal
deferred cycle on unchanged source reproduced the frozen synthetic-clock failure.
The fixture now advances to its scheduled one-second retry, with an explicit
regression; no runtime admission cadence or policy was modified.

In-memory reversals of the request scheduler, ingress-time propagation and
1,000-row query each cause their targeted regression to fail. No source file
or production process was weakened to perform those checks.

Work is isolated at `C:/Users/rynna/Bots/kalshi-reward-source-fix`, branch
`fix/reward-source-refresh`. Updating the active package changes the supervisor's
recovery fingerprint. Do not overwrite its checkout during the old live run.
Deployment requires an approved controlled stop/update/restart using the same
ledger, no initialization/reset, and inspection of fresh runtime evidence.
Do not reset exhausted catalog retries merely to repeat the unchanged failure.
