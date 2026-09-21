# D-060 independent Astra review — changes required

**Disposition:** R1-R6 were corrected and verified offline on September 21,
2026; see [the correction evidence](BUILD_COMMAND_CAPACITY_REVIEW_FIXES.md).
This report remains the immutable record of the pre-fix findings.

September 21, 2026. Reviewed the uncommitted D-060 implementation against
`8c03aa0451b8937ad78b72b71f67ed833777675c` and the
[D-059 design](DESIGN_COMMAND_CAPACITY_HANDOFF.md). Source/diff inspection,
disposable offline probes and focused tests only. No bot source, configuration,
credentials, network, real ledger, runtime or account state changed. No commit
or push. The operator's “Astra do it” assigns review, not implementation.

## Outcome and priority

**Not cleared.** Six P2 findings below block acceptance of this offline component
before live integration. Address R1/R2 dispatch integrity, R3 reducer authority,
R4 recovery, R5 failure ownership, then R6 resource acceptance. The original
double-reservation path is corrected, but overall-review items 1/2 are not closed.
Passing existing tests do not cover the reproduced paths.

### R1 — Bind receipts to their original issuing epoch and revision

Source: `execution.insert_prepared`, `validate_prepared_identity`, `begin_send`.
The journal stores terms and creation time, but not the issuing epoch/revision.
Consumption compares caller-provided receipt fields only to the current writer.
A frozen dataclass prevents assignment, not construction of a relabelled copy.

VERIFIED OFFLINE: prepare an entry, advance the writer using `observe`, and send
the original receipt: denied `stale_writer_evidence`. Replace its revision with
the current revision: the same old PREPARED row dispatches and ACKs. Restart the
writer and replace both epoch and revision: the old row likewise dispatches;
the unchanged receipt correctly denies `prepared_receipt_owner_changed`.

Required correction: retain authoritative original issuance identity and compare
it at consumption, not just request terms. Never refresh stale authority by
copying current writer fields. Test relabelled receipts both within an epoch and
after restart, including zero invocation and preserved capacity. Keep the
designed fresh-preparation path distinct from consuming an old receipt.

### R2 — Do not let proof callbacks change the dispatched command

Source: `execution.InjectedExecutor.execute_prepared`.
Both proof calls receive the mutable `request` subsequently passed to `invoke`.
Validation happens before those callbacks, and durable identity checks use the
receipt's separate JSON, not the mutable outgoing object.

VERIFIED OFFLINE: a proof callback changes count from `10` to `100` and price
from `0.4` to `0.9`, then returns True. Injected invocation sees `100`/`0.9`,
while the durable request remains `10`/`0.4`. A zero-fill ACK is accepted. This
breaks the exact risk-reservation/dispatch contract without changing the receipt.

Required correction: preserve canonical immutable dispatch terms across every
callback; isolate proof input and compare/revalidate the exact submitted terms.
Test mutation on each proof call independently, including scope and nested
values if supported. Invocation must never receive terms different from the
authorized durable request; corruption must not silently pass as proof.

### R3 — Reducer evidence must prove current management and routing authority

Source: `writer`'s `reduction_evidence` handler and `execution.prepare_reduction`.
Evidence echoes the caller's exchange index. Preparation checks that echo,
episode identity, local position and absence of an active reducer, but not the
existing management gate or authoritative routing. It does not reject working
entries or incomplete fill evidence before preparing the reducer.

VERIFIED OFFLINE: an owned entry on exchange 1 has three accounted fills and
seven contracts still working. Request evidence for exchange 99; an exact
three-contract reduce-only ask using that index reserves with no blockers and
dispatches to the injected transport. This bypasses cancellation/completeness
ordering and does not prove the chosen shard.

Required correction: bind preparation to source-backed routing and the current
management/exit decision, with complete inventory/order/fill evidence checked
in the owner transaction. Preserve existing cancel-before-reduce, IOC/time and
exact-size policy. Test wrong routing, working entries, pending/unaccounted fills,
stale management evidence and a valid eligible reduction. A generic callback
returning True is not a substitute for the designed authoritative preparation.

### R4 — Proven-unsent aborts permanently wedge safety-command recovery

Source: `execution.prepare_cancel`, `abort_prepared`, `portfolio.market_inventory`.
Every prior cancel row prevents another cancellation, including NOT_SENT; abort
does not restore a viable cancellation path. The exit journal also treats an
ABORTED/NOT_SENT IOC as unresolved because its intent is not TERMINAL.

VERIFIED OFFLINE, two independent cases:

- Prepare a funded cancellation, advance the writer, observe stale-send denial,
  then abort. A fresh attempt with new evidence returns `cancel_already_attempted`
  even though no cancellation was invoked and the owned order is still working.
- Prepare an exact three-contract IOC and abort before send. Its durable phase
  is NOT_SENT, but inventory reports `attempts=1`, `unresolved_ioc=true`.
  The exit planner's unresolved-IOC branch waits for terminal/fill proof that
  cannot arrive for this unsent attempt.

Required correction: define a bounded, auditable fresh-plan/reauthorization path
for proven-unsent safety work, including restart. Distinguish retained journal
storage, capacity reservations and permission to send. Do not delete history,
refund used rows as free space, blindly retry uncertain sends, or reset genuine
IOC limits to work around this. Tests must prove fresh cancel/reducer recovery,
bounded repeated aborts and continued blocking of SENDING/UNKNOWN attempts.
Escalate any change to the approved one-cancel funding contract rather than
silently expanding it.

### R5 — Retain a fail-closed owner for every failure after SENDING

Source: `execution.InjectedExecutor.execute_prepared`, after `begin_send`.
The second proof and sending diagnostics run outside the exception boundary.
Other failure paths set `failed` only after fallible diagnostics/persistence.
An exception can therefore leave durable SENDING while releasing the lock and
leaving the executor available rather than held for recovery.

VERIFIED OFFLINE: first proof returns True; second proof raises RuntimeError.
No invocation occurs, but the resulting state is `phase=SENDING`,
`executor.failed=False`, `writer.failed=False`, `lock.locked()=False`.
Source inspection shows equivalent uncovered diagnostic/outcome failure paths;
those individual fault combinations were not all injected in this review.

Required correction: establish the recovery hold before fallible post-consumption
work; retain finalization through repeated cancellation. Cover proof exceptions,
diagnostic emission/health failure, unknown/ACK persistence failure, timeout and
repeated cancellation. After ambiguous or failed finalization, subsequent
commands must not dispatch without the existing explicit recovery discipline.

### R6 — Replace invalid capacity fixtures and clear the actual CPU regression

Source: `scripts/benchmark_command_lifecycle.seed`,
`command_capacity.validate_capacity`, `episode_for_client`.
The benchmark's 4,000 historical rows are create ACKs lacking corresponding
intents, orders, episodes or credits. They are not a lifecycle-reachable retained
history and hide scans over the credit tables. The 120-market case still executes
only 30 entry/cancel lifecycles; the other markets are synthetic inventory, not
120-market management/drain work. Backlog is sampled after awaited operations.

MEASURED OFFLINE: replaced only the process-local seed function, leaving the
benchmark workload/instrumentation unchanged. The replacement contains 2,000
terminal entry/cancel pairs (4,000 mutations), 2,000 terminal intents, 2,000
canceled unfilled orders, 2,000 retired episodes and 36,000 credits: 16 released
unused drain credits plus two spent own-order/cancel credits per episode. Held
counters are zero and `validate_capacity` passes. Setup is outside measurement.

| Scope | Small CPU/lifecycle | Retained-history CPU/lifecycle | Ratio | Near prepare p99 | Near cancel p99 |
|---:|---:|---:|---:|---:|---:|
| 30 | 0.014583 s | 0.204167 s | 14.000x | 153.494 ms | 133.849 ms |
| 120 | 0.021875 s | 0.228125 s | 10.429x | 134.696 ms | 106.261 ms |

Both ratios fail the approved <2x CPU target; harness exit is 1. Latency,
loop-lag and memory thresholds still pass in this limited workload. This is
one offline run, concurrent with the focused tests, not a production benchmark.
CPU is process time; the script labels its /30 lifecycle metric CPU/command.
The magnitude is a regression signal, not a claim of stable production timing.

VERIFIED SOURCE/query plans: full credit integrity/group scans run repeatedly
during each preparation, and the owner-only `episode_for_client` lookup scans
`command_credits`. The current composite indexes do not serve that lookup.

Required correction: use complete lifecycle-consistent fixtures for both real
boundaries and resource acceptance; optimize transaction-local accounting and
owner lookups while retaining corruption checks and startup reconciliation.
Measure actual entry/terminal/management/drain work at 30/120-market scope, with
meaningful backlog sampling, then rerun matched small/near-capacity cases.
Do not clear CPU on the old fixture or weaken safety to pass. Record actual
safeguard reversals separately from tests that merely supply invalid inputs.

## Verification and handoff

- Fresh review run: **244 tests pass in 16.486 seconds** across command capacity,
  handoff, engine, inventory risk, exits, logging and accounting.
- The reproductions above use disposable ledgers and injected transport only;
  probe code ran from standard input and is not a committed regression suite.
  Sol must add durable tests for the corrected behavior.
- Fresh credential-free disabled preflight: expected exit 2,
  `live_ready=false`, `creates_files=false`, `credentials_accessed=false`,
  `network_accessed=false`.
- The complete 936-test result remains prior Sol evidence; not rerun by this
  review. Existing full-suite success does not clear these findings.
- Only review/handoff Markdown changed. Git whitespace, Markdown fence and
  whitespace checks pass; 237 local links across the ten touched Markdown files
  resolve. No dedicated repository Markdown audit exists. No sensitive
  credential markers were found in the new report.

**STOP under D-049. Recommended next agent: 5.6 Sol** for R1-R6 corrections and
focused/full verification, then Astra re-review of these meaningful execution
changes. Preserve schema-2 refusal, retained history, existing risk/exit rules,
live-disable gates and all unrelated readiness blockers. No S2B advancement,
production transport, migration, deployment or restart is authorized.
