# Overall code triage — September 21, 2026

Reviewed source at `8c03aa0451b8937ad78b72b71f67ed833777675c` after committing
the preceding D-057 work at the operator's request. This is cross-component
triage, not exhaustive certification or independent clearance of every D-057
failure path. No source/configuration edits, account calls, push or restart.

## Conclusion and recommended action order

The repository has substantial tested components, but no production trading
composition. The CLI exposes only `policy` and `preflight`; configuration rejects
live activation. Missing integrations below are not evidence of a running bot
losing money. Priorities describe what must be addressed before live use, not
new authority to implement, enable trading or bypass existing review gates.

### 1. Preserve safety cancellations when durable evidence reaches capacity

**Confirmed capacity hazard; high priority before any mutation integration.**
[execution.py](../src/kalshi_bot/execution.py), `journal_mutation`, rejects every
new preparation at 4,096 mutation rows, before distinguishing create from
cancel. Thus old evidence can prevent cancellation of a currently owned resting
order, not merely stop new entries. Through `LedgerWriter`, a command exception
also faults the writer. Other intent/order/history/epoch limits deliberately
fail closed; there is no completed durable archival/rollover workflow.

Offline reproduction: construct an in-memory ledger, reserve/send/bind one
valid resting order, insert 4,096 historical mutation rows, then prepare a
cancel for that order. Result: `mutation evidence capacity reached`; no cancel
is prepared. This tests the capacity branch, not a real venue cancellation.

Action: design bounded retention and safety-operation headroom/backpressure.
Stop admitting entries early enough to preserve cancellation/reduction work;
preserve unresolved intents, fill deduplication and loss-window evidence. Do not
solve this by deleting financial history or making queues unbounded. Add a
full-capacity owned-order cancellation/reduction regression.

### 2. Define one risk-reservation-to-execution transaction contract

**Confirmed component incompatibility, not an already connected live defect.**
[portfolio.py](../src/kalshi_bot/portfolio.py), `reserve_entry`, commits an intent.
[execution.py](../src/kalshi_bot/execution.py), `journal_mutation(prepare_create)`,
unconditionally reserves it again. [ledger.py](../src/kalshi_bot/ledger.py),
`reserve_intent`, correctly rejects the duplicate identity. These offline APIs
cannot simply be chained into production order execution.

Offline reproduction using an in-memory `LedgerWriter`: obtain a portfolio
view; successfully reserve a valid ten-contract entry with fixture authority;
pass that exact request to `InjectedExecutor.attempt` with a true fixture proof
callback. Preparation is refused, `writer.failed` becomes true, and the injected
gateway is called zero times. Existing combined engine tests start directly at
the executor; they do not establish this reservation handoff.

Action: specify one owner transaction and a writer-issued reservation identity
that execution consumes exactly once, with exact immutable terms and current
account/book/risk revisions. Preserve intent-before-send and unknown-send holds;
never weaken duplicate rejection or bypass the risk gate. This requires design,
not a routine removal of the second check.

### 3. Finish opening-account, continuity and cash accounting contracts

**Unbuilt readiness dependency.** [runtime.py](../src/kalshi_bot/runtime.py)
deliberately returns `entry_allowed=False`; its reservation inspection supplies
`account_known=False` and `offline_fixture=False`.
[continuity.py](../src/kalshi_bot/continuity.py) always includes
`venue_history_stream_handoff_unproven`. Current agreement checks do not establish
complete opening basis or a coherent cash/history/private-stream boundary.
The ledger accounts actual fills, fees and matched closes; settlements,
corrections and opening-state installation need separate contracts.

Action: separately assign the conditional handoff and opening-account phases of
[the continuity design](DESIGN_ACCOUNT_CONTINUITY.md). Verify venue guarantees,
or present the explicitly controlled account-boundary alternative to the
operator. Define old-order/fill treatment and cash/hold/settlement behavior before
granting production admission. Never infer proof from repeated matching reads,
an empty stream or historical test success. Phases 2/3 remain unapproved.

### 4. Connect inventory exits and separately budgeted write execution

**Unbuilt readiness dependency.** [management.py](../src/kalshi_bot/management.py)
and [exits.py](../src/kalshi_bot/exits.py) produce advisory plans, not commands.
[market_inputs.py](../src/kalshi_bot/market_inputs.py) explicitly detects missing
timing reviews and fee profiles. The signer and [REST service](../src/kalshi_bot/rest.py)
are GET-only; read quota does not cover mutations. No production mutation
transport, write scheduler or integrated cancel/reducer dispatcher exists.

Action: supply verified per-market event timing, ticks and fee bounds; integrate
one mutation owner with cancel/exit priority and separately verified write costs.
Test partial-fill/cancel races, ambiguous sends, deadlines, quota loss and
shutdown as one offline lifecycle. Make stop-loss entry restrictions and
next-window release consume verified state, not caller booleans. Live testing
still needs separate authorization; this does not introduce paper trading.

### 5. Connect reward ranking to bounded market admission and replacement

**Unbuilt strategy integration.** [ranking.py](../src/kalshi_bot/ranking.py) has
gross unchanged-book reward views; `trade_ready` is false and net profit is not
estimated. The runtime accepts caller-selected tickers and evaluation callbacks.
There is no production composition connecting incentive discovery, the ranking
board, allocation under the existing limits and the order lifecycle. An
`incentives` REST operation alone is not that composition.

Action: design bounded discovery/refresh and rank-to-admission wiring, including
inventory exclusions, evidence expiry, market replacement, own-order/public-book
agreement and unsupported/capped programs. Preserve the approved $500 capital,
ten-contract entry and 30-resting-entry ceilings and fixed exposure budgets.
Keep gross rewards separate from trading losses, fees and actual reward credits;
do not turn snapshot scores into a promised daily income figure.

### 6. Complete supervised runtime and end-to-end acceptance

**Unbuilt integration plus unresolved measurements.**
[process_supervisor.py](../src/kalshi_bot/process_supervisor.py) runs only the
fixed inert child; [ScopeSpec](../src/kalshi_bot/supervisor_control.py) accepts
only test account scopes. S2B runtime ownership/restriction transfer remains
unimplemented. Restart must preserve cooldowns, exhausted retries and unknown
account/command state, not just keep a process alive.

Action: retain the independent D-057 review and focused resource gate before any
separately approved S2B implementation. Prior recorded parent CPU is 2.135%
against <1%; cold-baseline +13 handles are unattributed, not a proven leak.
These are [historical measurements](BUILD_WINDOWS_SUPERVISOR_S2A_FIXES.md), not
rerun here. Do not spend this triage phase on another broad supervisor rewrite or
claim resource clearance. Eventually verify the connected 30/120-market workload,
shutdown/recovery and approved laptop sleep behavior, then obtain explicit live
launch authority. No start CLI should bypass the preceding gates.

## Verification and limits

- Fresh focused run: **267 tests passed in 27.773 seconds** using
  `python -B -m unittest -q test_bot_accounting test_bot_inventory_risk test_bot_exits test_bot_engine test_bot_verification test_bot_continuity test_bot_rate_limits`
  with process-local `PYTHONPATH=src;tests`.
- Both additional in-memory probes above reproduced their stated outcomes.
- Fresh credential-free preflight: expected exit 2, `live_ready=false`,
  `creates_files=false`, `credentials_accessed=false`, `network_accessed=false`.
- Commit staging passed whitespace and private-key/GitHub-token marker checks;
  ignored key, environment and data paths were verified. Working tree was clean
  immediately after commit. Review/handoff Markdown is subsequent local work.
- No complete-suite, native supervisor fault matrix, 100-cycle benchmark,
  performance rerun or fresh venue/API research in this review. The prior
  915-test result is implementation evidence, not a new review result.

Recommendation: a bounded Astra design for items 1/2 is the next code-change
preparation; resolve item 3 before production authority is wired. Then stop for
Sol implementation on approval. This order is a recommendation, not a new
operator decision or clearance of the existing S2B gates.
