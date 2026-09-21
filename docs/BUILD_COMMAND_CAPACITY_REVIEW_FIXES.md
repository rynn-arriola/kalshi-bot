# D-060 review corrections

September 21, 2026. Implements R1-R6 from the
[independent D-060 review](REVIEW_D060_ASTRA.md) in the same offline,
execution-disabled scope. No authenticated transport, account access, schema-2
migration, deployment, restart, configuration change or live order action
occurred.

## Corrections

- Every preparation now creates a durable authorization containing its original
  writer epoch, revision, subject, episode and canonical request. Consumption
  validates that record, so relabelling a stale receipt cannot refresh authority.
- Proof callbacks receive separately decoded request values. Dispatch is rebuilt
  from the durable canonical request and revalidated immediately before the
  injected transport call.
- Reduction evidence requires a current typed management/exit plan and durably
  binds its exact mode, price, quantity, account/book generations, terms window,
  exit journal and writer revision. Preparation also recomputes the active
  episode, signed inventory, unique source-backed route, terminal order state,
  accounted fills and absence of pending fills. After queued preparation commits,
  current account/book/management authority is checked again; stale PREPARED
  work is durably aborted before the caller receives a usable receipt.
- A proven-unsent cancel or reducer can be reauthorized across restart without
  adding a command slot or expanding the one-cancel/three-IOC funding contract.
  Authorization history is retained and capped at eight per mutation. SENDING,
  UNKNOWN and ACK commands remain non-retryable.
- The executor enters its recovery hold immediately after durable SENDING and
  clears it only after durable ACK plus healthy diagnostics. Proof, diagnostics,
  transport, timeout and persistence failures remain fail-closed.
- Trigger-maintained used counters and explicit held counters make hot capacity
  checks constant-time. Full credit, authorization and counter reconciliation
  remains mandatory at writer startup. Legacy fixture/recovery intent and order
  insertion paths enforce the configured limits transactionally as well.

## Verification

- Focused impacted suite: **258 passed** in 23.237 seconds.
- Complete native Windows suite: **950 run, 949 passed, one existing native
  symlink-privilege skip**, in 129.923 seconds.
- Disabled credential-free preflight: expected exit 2, `live_ready=false`, and
  `creates_files`, `credentials_accessed`, `network_accessed` all false.
- Regression coverage includes receipt relabelling within an epoch and after
  restart, proof mutation, authoritative reducer route/state, pending fills,
  restart recovery of proven-unsent cancels/reducers, bounded reauthorization,
  and post-SENDING proof/diagnostic failures.

The corrected benchmark uses complete retained create/cancel histories and real
active inventory episodes for all additional management markets. Setup remains
outside measurement; each run executes 30 complete entry/cancel lifecycles and,
at 120-market scope, 90 authoritative reducer preparations and proven-unsent
aborts.

| Scope | Retained rows | CPU/lifecycle | Near/small CPU | Prepare p99 | Cancel p99 | Reducer p99 | Loop p99 | Peak memory | Backlog |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | 0 | 0.014583 s | — | 5.040 ms | 2.897 ms | — | 5.613 ms | 426,452 B | 1 |
| 30 | 4,000 | 0.020833 s | 1.429x | 13.971 ms | 3.493 ms | — | 8.209 ms | 79,841 B | 1 |
| 120 | 180 | 0.013542 s | — | 18.888 ms | 4.600 ms | 17.006 ms | 7.915 ms | 378,552 B | 1 |
| 120 | 4,000 | 0.010807 s | 0.798x | 18.479 ms | 2.813 ms | 12.983 ms | 7.865 ms | 337,070 B | 1 |

Before timing, the harness validates every seeded request, canonical ACK,
authorization proof, lifecycle link and per-epoch monotonic revision. All four
cases pass. The worst retained-history CPU ratio is **1.429x**, below
the approved `<2x` threshold. These are bounded offline engineering fixtures,
not production latency, profitability or live-readiness evidence.

## Remaining boundaries

Schema-2 and the earlier development schema-3 format remain refused rather than
silently migrated. Retained command history is not reclaimed; archive/rollover
policy remains separate. Account continuity, production dispatch and exits,
ranking/allocation, S2A resource review and S2B remain open.
