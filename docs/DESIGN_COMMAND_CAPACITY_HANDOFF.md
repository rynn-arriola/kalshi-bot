# D-059 — Safety-command capacity and atomic execution handoff

September 21, 2026. **Design approved and implemented offline under
[D-060](BUILD_COMMAND_CAPACITY_HANDOFF.md);
[independent Astra review](REVIEW_D060_ASTRA.md) requires corrections.**
Addresses items 1/2 of the [overall review](REVIEW_OVERALL_2026-09-21.md), against
source commit `8c03aa0`. Numbers and interfaces below are proposed engineering
contracts, not implemented behavior, venue guarantees or changed trading limits.

## 1. Scope and evidence

- `execution.journal_mutation` rejects all preparation at 4,096 mutation rows,
  including cancellation of an owned working order. `writer._run` faults its
  owner on the resulting exception. Merely exempting cancels would be unbounded.
- `portfolio.reserve_entry` inserts an intent; execution preparation inserts it
  again. The previous review reproduced writer failure and zero dispatches.
- Adjacent limits matter: intents, order evidence, account audit and basis
  readers use 4,096-row bounds. Reserving only a mutation row would leave a
  reducer unable to reserve an intent or persist its eventual order evidence.
- A successful reservation changes the writer revision. The dispatch receipt
  must carry the **post-commit** revision, not reuse the pre-reservation view.
- Current IOC exit policy permits three attempts; ACK and cancel responses
  do not constitute terminal order/fill proof. These contracts are unchanged.

Keep one Windows ledger writer, one injected mutation executor, existing exact
risk/accounting rules and all live-disable gates. No live transport, new API
semantics, archive deletion, production database conversion, account baseline,
supervisor work, market-selection change or paper trading. This is local
durability/admission design; no fresh venue guarantee is assumed or needed.

## 2. Capacity: bounded headroom backed by durable reservations

### Proposed limits and invariant

Keep retained intents and order evidence bounded at 4,096 each. Introduce a
separate bounded command-journal policy: **4,096 ordinary-entry high-water mark,
8,192 total mutation rows**, including safety commands. The extra capacity is
not permission to increase capital, contracts, resting orders or market count.
Do not globally replace every occurrence of 4096 with 8192.

For each resource, maintain transactional used (`U`) and held-for-future (`H`)
counters backed by explicit credit rows:

| Resource | Required invariant |
|---|---|
| Mutation rows | `U_mutation + H_mutation <= 8192` |
| Intent rows | `U_intent + H_intent <= 4096` |
| Order-evidence rows | `U_order + H_order <= 4096` |

Entry preparation requires `U_mutation < 4096` **and** all three invariants
after its full charge. At the entry high-water mark, or insufficient headroom,
return `capacity_entries_held`; never poison the writer for this expected denial.
The high-water condition survives restart through retained counts. Other
temporary capacity denials can clear only when real held credits are released;
they do not clear a trading-loss hold or grant account authority.

Every newly prepared create consumes one intent and one mutation row, and holds
one future order-evidence row plus one future cancellation-mutation row. This
includes reducers. A cancellation spends its target order's held mutation
credit; it does not compete with new entries for ordinary admission space.
Existing request ownership/account/exchange checks remain mandatory.

Before the first potentially filling entry for a market episode, also hold a
**drain bundle**: one passive reduction and three IOC reductions, with one cancel
and one order-evidence slot per create. Its worst-case reservation is eight
mutation, four intent and four order-evidence slots. This is storage provision
for existing management mechanics, not authority to trade, a mandatory exit or
a guarantee of flatness. Even IOC cancellations may never be needed; holding
their slots conservatively simplifies the invariant.

The bundle is shared by all admitted orders in that account/market episode,
not allocated independently to each quote. Its key is a durable episode ID,
not just `first_seen_at`, so reopenings cannot reuse an old allowance. Keep it
while any admitted order can still fill, inventory remains, or evidence is
ambiguous. Bind create reservations to the episode before any send.

### Spending, replenishment and release

- Spending a credit converts held capacity to a used row in the **same** writer
  transaction. Never check space, await, then insert later.
- The first bound order consumes its held evidence slot; subsequent updates
  use that same row. A second venue order for one client ID is an integrity fault.
- Passive replacements may acquire a new passive allocation only from genuinely
  unreserved capacity; they cannot consume another order's cancel credit or the
  three protected IOC allocations. Refusal is a capacity blocker, not a reason
  to alter exit prices, force an IOC, exceed its attempt limit or blind-retry.
- Three IOC storage allocations do not reset the existing attempt/time budgets.
  Unknown creates/cancels retain their credits and reservations. A second cancel
  for the same order is not authorized by unused headroom.
- Terminal order evidence **and matching accounted fills** release unused
  cancellation capacity. Cancellation ACK, 404, absence, elapsed time, restart
  and flat net position do not. Release an unused order-evidence credit only for
  a positively known unsent create, never an ambiguous send.
- Retire an episode only after no unresolved/working intents, no pending fills
  and coherent flat inventory in that episode's complete fixture scope. Retain
  its audit identity; do not relabel old commands as a new episode. Production
  completeness remains blocked by overall review item 3.
- Used history is never reclaimed in this phase. Unused held credits may be
  released transactionally; terminal mutation/intent/order rows are retained.
  Eventually the system refuses new entries and needs an explicitly designed
  archival/maintenance phase. It must not silently start a new ledger or reset
  risk to regain space.

This guarantees storage headroom for already funded commands in a valid ledger,
not cancellation during disk-full, corrupt storage, queue overflow, lost account
proof or venue outage. Those existing failure gates remain. A legacy/full ledger
with unfunded open orders is **not** made safe by inventing credits; it requires
separate controlled migration/recovery. The original 4,096-row cliff regression
must use valid funded ownership in the new format and demonstrate a cancel can
still prepare at that ordinary high-water mark.

### Persistence and bounded reads

Add `command_capacity.py` for typed policy, credit accounting and invariants;
all SQL executes on the existing ledger writer. Use resource counters plus
indexed per-intent/per-episode credit records. Bound credit records by retained
intents/episodes; no task, thread or polling loop per credit. Reconcile counters
against bounded rows on startup; mismatch blocks rather than repairs silently.
Never scan all history on a public-book tick.

Use a new ledger schema version **3**, retaining unchanged fill/P&L economics.
New disposable ledgers initialize counters and persistent ledger identity.
Reject existing schema-2 databases before WAL/DDL writes, without automatic
migration. Existing user ledgers are not opened, converted or deleted by this
assignment. Adjust old-schema tests; upgrade fixture creation, not real data.
Raw fixture seeding must initialize credits consistently or be explicitly
non-executable; direct legacy `reserve_intent` is not command authority.

Update only mutation-history readers to the 8,192 total bound, including
`writer.mutations` and the exit-journal projection in `portfolio.market_inventory`.
Keep order/intents/account bounds at 4,096, backed by reserved slots. Preserve
indexed query paths; add exact attempt/client/order/episode indexes as needed.
Do not truncate history and call the remainder complete. Unrelated fill,
history-receipt, epoch, venue-cost and book-level limits remain unchanged.

## 3. One preparation contract, then consume once

```text
Fresh fixture evidence + request
    -> sole writer transaction: risk checks + credits + intent + PREPARED attempt
    -> immutable post-commit receipt
    -> revalidate -> writer compare-and-set SENDING -> revalidate -> injected call
    -> ACK or UNKNOWN; private/REST evidence separately proves fills/terminal state
```

### Interfaces

Put immutable shared records in `command_types.py` to avoid the current
portfolio/execution import cycle. Freeze and size-limit request encoding before
queue admission; preserve exact economic terms and explicit routing.

| Interface | Contract |
|---|---|
| `LedgerWriter.reserve_entry(..., attempt_id=...) -> PreparationResult` | Existing risk reservation becomes the atomic command-preparation entry point. In one outer transaction recompute risk, validate the view, allocate all capacity, insert exactly one intent and its PREPARED attempt. |
| `LedgerWriter.prepare_cancel(attempt_id, request, evidence) -> PreparationResult` | Check exact owned working order and existing cancel attempts, then spend that order's protected credit. No new intent. |
| `LedgerWriter.prepare_reduction(attempt_id, request, evidence) -> PreparationResult` | Fixture-only; exact current reducing direction/quantity and current management evidence; consume a suitable episode allocation and reserve its intent/evidence/cancel capacity. |
| `LedgerWriter.begin_send(receipt, evidence) -> SendResult` | Validate identity, immutable request, writer epoch/revision and PREPARED state; atomically set attempt and create intent to SENDING, returning post-commit dispatch evidence. |
| `LedgerWriter.abort_prepared(receipt) -> AbortResult` | Only proven PREPARED, never SENDING: persist NOT_SENT, mark create intent ABORTED, release unused credits consistently. Does not erase used history. |
| `InjectedExecutor.execute_prepared(receipt)` | One bounded single mutation owner, injected offline gateway only; never calls reserve_intent or creates another reservation. |

`PreparationResult` contains a receipt or typed blockers, plus current capacity
status. `PreparedMutation` contains ledger ID, writer epoch, post-commit revision,
attempt ID, kind, client/target identity, exact frozen request, episode/credit
binding and preparation time. It is a reference to durable evidence, not a
bearer permission: re-read and compare authoritative rows before dispatch.

Replace the permissive `attempt(kind, id, request)` create path in all existing
fixture tests/callers with explicit preparation and receipt consumption. Do not
leave a hidden "direct create" branch bypassing risk or capacity. Generic writer
mutation commands must not expose a second preparation/SENDING bypass; move
preparation/send transitions behind the typed writer APIs. Preserve bounded
ACK/UNKNOWN recording. Low-level evidence-seeding helpers remain fixture-only
and cannot issue executable receipts.

`runtime.inspect_entry` remains execution-disabled and must still deny; it can
use the unified method with false fixture/account authority. No runtime order
dispatcher is installed here. Existing public data remains WebSocket-first.

### Risk/revision and consumption rules

- Keep the current single writer revision model. Return the revision **after**
  the preparation transaction; its own insert must not immediately stale its
  receipt. Do not exempt other queued account/risk writes or ignore revisions.
  In `_run`, compare the supplied revision before incrementing it, as the current
  `reserve_entry` special case does; increment once after the successful owner
  operation and publish that new revision on the receipt. Apply the same ordering
  to `begin_send`; a generic pre-dispatch increment must not invalidate its own
  comparison. A denied operation that observes/tightens risk still advances the
  revision when it commits evidence, without issuing a send receipt.
- Revalidate external account/book/generation/freshness evidence before each
  awaited writer transition and immediately after it. The fixture supplies this
  synchronous proof callback; it is not production account proof. Writer checks
  its epoch/revision and durable terms independently.
- If another write changes evidence before send, return a stale denial. Do not
  fix staleness by copying the latest revision onto an old receipt. The current
  phase may safely abort an unsent PREPARED command and require a fresh plan;
  production reauthorization/recovery is not invented here.
- A compare-and-set from PREPARED to SENDING grants at most one dispatch for that
  attempt. Exact duplicate preparation reports existing state without rearming;
  same identity with conflicting terms remains an integrity fault. Two consumers
  cannot both win. This is local at-most-once dispatch, **not** a venue-wide
  exactly-once guarantee.
- Require one executor owner per writer lifetime; reject a competing owner.
  Keep bounded busy rejection rather than add an unbounded mutation queue.
  No await/queued work between final proof validation and entering the injected
  invocation; no production network dispatch is implemented by this contract.
- After SENDING, any proof loss, timeout, malformed ACK, caller cancellation or
  crash leaves SENDING/UNKNOWN for reconciliation. Never turn uncertainty into
  NOT_SENT or automatically resend. ACK does not release risk or safety credits.
- Old-epoch receipts cannot execute after writer restart. Durable reservations,
  credits, attempt states and held risk survive; restart never reissues authority.

### Expected denial versus failure

Capacity, stale proof, busy ownership, duplicate exact attempt and already-used
receipt are typed, non-success outcomes with zero dispatch. They do not set
`writer.failed` or globally poison the executor. Risk/clock observation may still
tighten persistent holds while denying a new entry; never roll back a ratchet to
make a denial transaction appear read-only.

SQL/commit failure, conflicting immutable evidence, broken credit invariant,
unsafe clock or internal exception keep the existing fatal writer behavior.
Do not catch broad InvalidData and treat corruption as ordinary denial.
An uncertain send keeps the executor recovery hold; reserved storage does not
override that hold. Diagnostics use bounded reason codes and safe identifiers,
not raw order documents or exception text.

Caller cancellation cannot discard an accepted writer operation. Retain and
drain the preparation/send transition owned task to learn its committed result;
do not dispatch after its caller has cancelled. If preparation alone committed,
request a verified unsent abort or leave the reservation held for inspection.
Repeated cancellation must not release dispatch ownership while invocation or
ACK/UNKNOWN recording remains unfinished. The outer owner still closes/joins
the writer; no new process supervisor is introduced.

## 4. Implementation sequence and file ownership

One bounded Sol assignment for both items, on approval; internal steps are not
extra model-switch phases. Stop after verification for Astra review.

1. **Capacity foundation:** add `command_types.py`/`command_capacity.py`, schema-3
   counters/credits, atomic charges/releases, typed denials, bounded history
   reader changes and cancellation-at-high-water tests. No executor authority
   until all create paths fund their future evidence/cancel slots.
2. **Atomic handoff:** extend `portfolio.reserve_entry`, expose typed writer
   preparation/send/abort methods, wire injected receipt consumption and exact
   cancel/reduction preparation, update old fixture callers. Keep risk logic in
   portfolio/risk, durability on the writer and network injection in execution.
3. **Integrated verification:** add `test_bot_command_capacity.py` and
   `test_bot_command_handoff.py`; update engine/inventory/exits/accounting tests
   and bounded logging codes. Add a focused command-lifecycle resource harness
   using the existing inventory benchmark conventions. No unrelated refactoring.

No changes to bot risk configuration, Polymarket, actual ledger files, account
continuity Phases 2/3, S2A implementation or S2B. The existing supervisor review
and CPU/handle gates remain open; this assignment does not clear them.

## 5. Required acceptance and evidence

### Correctness and fault tests

- At 4,096 retained mutation rows, a valid funded owned-order cancel
  prepares successfully; new entry is denied and writer stays healthy. Existing
  protection still funds reductions and order evidence. Use legitimate mixed
  create/cancel history, not 4,096 creates plus impossible extra intent credits.
  At `U+H` equal to the hard bound, a funded command still converts H to U. At
  `U` equal to the bound and H zero, no new unfunded rows; updates to existing
  records still work. No over-allocation or manufactured credit is permitted.
- Tiny injected capacity policies exercise every exact boundary cheaply; one
  real 4,096/8,192-row fixture checks the production-sized reader limits. In
  particular `mutations`, market inventory/exit journal and account audit must
  neither truncate nor fail at their **respective** supported limits.
- Concurrent entries cannot spend the same headroom or risk view twice. Every
  accepted create is cancellable within reserved storage. No unrelated cancel,
  spoofed reduce-only entry or passive reprice can steal IOC/cancel credits.
- Cancel/fill and terminal/fill-order races release credits once, only after
  complete proof. Partial fills and unknown sends retain the episode bundle;
  reopening gets a new episode. IOC budgets and inventory age survive restart.
- A risk-approved entry produces one intent, one PREPARED attempt and one fake
  gateway call; duplicate consumers yield no second call. Tampered terms,
  cross-ledger/epoch/scope receipts and stale evidence cannot send.
- Validate post-commit revisions, competing writes at every await, concurrent
  preparation and final proof loss. Ordinary denial leaves writer usable for a
  subsequent valid safety command; financial ratchets never loosen.
- Deterministic barriers cover cancellation before/during preparation, during
  SENDING, during invocation and ACK recording; repeat cancellation; reopen at
  each committed boundary. No blind retries, freed ambiguous credit or orphaned
  accepted work. Inject SQL rollback/commit/diagnostic failure and corruption.
- Pre-existing schema-2 files are refused unchanged; no WAL/DDL side effects.
  Never use real user ledgers in migration/compatibility tests.
- Two offline safeguard reversals must detect: omission of cancellation credit
  reservation, and bypass of receipt-consumption/identity checks. The original
  duplicate-reservation chain must fail against old code and succeed through
  the new contract, without weakening duplicate identity protection.

### Resource and completion gates

Use disposable native Windows WAL/FULL ledgers at 30 and 120 markets; include
near-entry-capacity history and a bounded safety-drain workload. Generate valid
active ownership under the unchanged 30-entry ceiling; extra markets exercise
inventory management, not 120 authorized entry orders. Resource fixtures may
seed synthetic accounting evidence but cannot confer live authority.

Measure preparation/consume/cancel and capacity-check p50/p95/p99, process CPU,
wall time, peak memory, writer backlog and event-loop lag. Compare matched
small-history and near-capacity workloads. Proposed acceptance: command path
p99 <250ms, loop-lag p99 <50ms, incremental traced memory <40MiB, unchanged
bounded writer queue/thread count, no polling/extra idle wakeups. Report CPU
seconds per completed command; near-capacity workload must stay within 2x the
matched small-history CPU cost, or stop with attribution instead of raising
limits. These are offline engineering targets, not measured results/live SLAs.

Run focused tests, the exact full suite, disabled credential-free preflight,
relative-link/whitespace/sensitive-marker checks and inspect the complete diff.
Record actual results and skips; prior 267/915-test counts are not clearance of
new work. No long unrelated supervisor benchmark is required for this phase.

## 6. Approval and handoff

Design verification performed: seven new design/handoff relative links resolve;
Markdown fences, whitespace and sensitive-marker checks pass. Arithmetic checks
at 30/120 markets confirm that consuming a held cancel credit preserves the
proposed capacity sums. These are document/model checks, not implementation
tests. No bot suite, benchmark, account call, commit or push was run in this
planning task; all task changes are Markdown, preserving the earlier review work.

Recommended approach is reserved bounded headroom plus atomic preparation.
Rejected shortcuts: unlimited cancel history, blind deletion of terminal rows,
silently increasing all 4096 limits, accepting any duplicate intent, or making
all writer errors nonfatal. A complete archive/rollover subsystem is deferred:
it is larger than these two fixes and risks losing deduplication/accounting proof.

D-059 originally authorized producing this plan. The operator subsequently
approved its disposable offline implementation under D-060. That approval did
not authorize converting existing databases, authenticated transport or launch.
Implementation was submitted for review; the
[independent review](REVIEW_D060_ASTRA.md) requires R1-R6 corrections.
**STOP for Sol fixes and verification, then Astra re-review.**
