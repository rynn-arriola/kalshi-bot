# Owned write outcomes — priority 4

Offline injected component, 2026-09-21; no HTTP client, retry loop or live
activation. One scalar notice retains operation scope/outcome/status only.
Typed HTTP failures never accept response bodies. ACK or uncertainty revokes
the pinned plan/account proof and signals the existing coalesced recovery owner.
The executor re-signals after retained persistence, including failures, so an
early recovery wake-up cannot consume the only notification before the journal
advances. Recovery is requested, not declared successful or safe to resume.

A numeric 429 pauses only the original request's exchange shard in the same
write budget, including late replies after quota refresh. Local pause is an
explicit 0 < seconds <= 60 fixture parameter (default 1); not a venue header or
live trading policy. Other errors do not infer throttling. Transport/validation
failures remain UNKNOWN (or held SENDING if persistence fails), with executor/
dispatcher latched and durable capacity retained. A notification failure after
durable ACK keeps that ACK but latches the owner. ACK does not prove terminal fills or
cancel completion. No automatic resubmission or hold release is implemented.

Official contracts checked 2026-09-21:
[rate limits](https://docs.kalshi.com/getting_started/rate_limits),
[create v2](https://docs.kalshi.com/api-reference/orders/create-order-v2),
[cancel v2](https://docs.kalshi.com/api-reference/orders/cancel-order-v2), and
their local operation/response schemas in `KALSHI_API_REFERENCE.md`. Current
rate-limit guidance supplies no Retry-After header; the implementation does
not invent one. Reads remain independent. The outcome path performs no GETs;
missing authoritative order/fill evidence remains the existing recovery owner's
responsibility. No raw exceptions or response bodies are stored in notices/logs.

## Acceptance declared before measurement

Actual dispatcher/writer/account owners with disposable SQLite and synthetic
transport: ACK, cancel, 429 shard isolation, late refresh, HTTP faults, malformed
ACK, timeout/cancellation, persistence/notification faults and early recovery
wake-up. UNKNOWN and capacity must survive closing/reopening the fixture ledger.
No second transport call; old account proof must be invalidated.

Resource fixture: one sequential outcome owner, 30/120 configured shards,
300/1,200 injected 429 calls. Acceptance: CPU <1s, allocation <8 MiB, outcome
p99 <20ms, loop lag p99 <50ms, one retained notice, no extra reads/tasks. These
are component costs, excluding writer/recovery/network; not live capacity or
profitability claims. Full suite and disabled preflight required.

## Verification

Native Windows verification:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bot_mutation_outcomes.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bot_write_quota_source.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B scripts/benchmark_mutation_outcomes.py
.\.venv\Scripts\python.exe -B -m kalshi_bot preflight
```

24 outcome tests and 30 shared-quota tests passed. Two deliberate in-memory
bypasses make the regressions fail: removing the post-persistence notification,
and restoring the old shield wait. Python 3.14's cancelled shield can send a
later exception to its default loop logger even when the owner subsequently
retrieves it. Dispatcher run/close and executor persistence now retain tasks
with `asyncio.wait` and explicitly consume their result. No task is detached or
force-killed. Raw transport exception text stays outside structured diagnostics.

| Shards / outcomes | Outcome p50/p95/p99 ms | Loop p50/p95/p99 ms | CPU / wall seconds | Peak bytes |
|---|---|---|---|---|
| 30 / 300 | .044 / .126 / .182 | .159 / 2.337 / 2.337 | .0156 / .0207 | 25,831 |
| 120 / 1,200 | .042 / .096 / .183 | .136 / .354 / 1.710 | .0625 / .0697 | 53,600 |

All declared outcome-component budgets passed, with exactly one retained notice.
Percentiles use nearest rank over the stated calls; short loop samples are not
production tail estimates. Account-wide invalidation/recovery and durable writer
costs are excluded, not claimed as measured by this microbenchmark.
Disabled preflight returned native exit 2 and `live_ready=false`, with no files,
credentials or network access. Final full suite: **1,156 run, 1,155 passed,
one expected Windows symlink-privilege skip**, in 120.048s.

Actual diff review covered exact durable scope, same-budget late 429s, source
clocks, cancel/ACK ambiguity, notification/commit ordering, retained cancellation,
writer failure and constant-size notice retention. No blocking issue found in
this offline component. Eight changed Markdown files passed local-link checks
(274 links); staged whitespace and secret-pattern checks passed. Publication
follows D-065 after final checks.

Follow-up: [supervised injected lifecycle](BUILD_DISPATCH_LIFECYCLE.md) now owns
runtime dispatch tasks, outcome draining and no-replay fixture restart checks.
Production transport, verified account quota/fee inputs and live restart/resumption
policy remain separate.
Pauses/notices are process-local; durable UNKNOWN/authority holds survive restart.
