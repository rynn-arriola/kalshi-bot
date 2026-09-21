# Opening-account and cash evidence — D-062

September 21, 2026. Part of overall priority 3; execution-disabled development.
The [design](DESIGN_OPENING_ACCOUNT_CASH.md) owns the scope. This evidence
component does not close the complete opening-account/accounting milestone.

## Implemented

`opening_account.py` normalizes precise cash, optional settlement payout fields,
subaccount transfers, intra-exchange transfers and member funding into bounded
immutable records. Page evidence carries endpoint, initial query, page/row/byte
counts and explicit cursor exhaustion. Wrong scope, filtering, inconsistent
duplicates, future timestamps and incompatible cash representations are rejected.
Subcent cash is retained exactly with legacy-rounding uncertainty exposed.

`AccountCoordinator.inspect_opening_account` explicitly reads the six sources
through the existing shared read service, joins failures, and normalizes off the
event loop. One retained inspection prevents overlapping work after consumer
cancellation. Account/report/writer revisions are checked before and after the
thread operation. Snapshot and inspection times remain distinct. There is no
periodic polling, public-tick work, ledger mutation or authority installation.

The GET allowlist includes the five new histories. Historical-fill recovery
sends the now-documented subaccount filter. Current official changes and links
are in [API reference notes](API_REFERENCE_NOTES.md); the captured September 19
reference is preserved.

## Review and correctness verification

The independent reviewer found pre-boundary pending/unknown-time funding and
intra-exchange transfers were incorrectly omitted. The fix retains pending or
undated funding and all intra-exchange observations, since their completion time
cannot be inferred from creation time. Explicit attribution/timing blockers
remain. Regression covers both funding directions, all four funding statuses,
absent/null finalization and both transfer statuses.

- Expanded impacted suite before final lifecycle changes: 232 passed in 30.510s.
- Opening-evidence module before batching: 15 tests passed in 1.098s;
  the final module has 17 tests, included in the combined run below.
- Final combined source-tree suite: **999 run, 998 passed, one expected Windows
  symlink-privilege skip**, 133.088s, including the write-budget foundation.
- After D-064's primary/flat-policy update: **1,015 run, 1,014 passed, one
  expected Windows symlink-privilege skip**, 134.201s. Two new policy tests
  check nonprimary scope, nonzero positions, zero-quantity rows and resting
  orders. All outputs remain non-authorizing.
- Disabled preflight: native exit 2; `live_ready=false`; files, credential and
  network access all false.
- Meaningful tests cover source/query binding, explicit cursors, decimals,
  optional fields, old cash activity, exact scope, revision changes during
  reads/thread normalization, cancellation ownership and non-authorizing output.

## Resource evidence — batching correction passes the bounded fixture

`scripts/benchmark_opening_account.py` generates synthetic rows across all five
histories. It runs three untraced normalization samples off-thread, then measures
allocations separately. No account, live database or secrets are used.

Before batching, the instrumented diagnostic (GC timings collected separately):

| Total rows | Maximum wall | Maximum CPU | Peak Python allocation | Loop p99 |
|---:|---:|---:|---:|---:|
| 128 | 5.458 ms | below timer resolution | 44,571 B | 3.129 ms |
| 4,096 | 27.934 ms | 31.250 ms | 1,130,434 B | 48.955 ms |
| 50,000 | 337.672 ms | 343.750 ms | 14,167,498 B | **61.163 ms** |

Wall/memory targets pass. The 50,000-row event-loop target of <50 ms does not;
earlier runs show 61–74 ms, and one 4,096-row run also exceeded it. Generation-2
GC pauses of 24.712/38.291 ms were observed. These are measured performance
limitations, not a complete causal proof or resource clearance. No global GC or
safety threshold was weakened. Investigation found result replacement took only
3.6–4.4 ms, so it was not the main cause. GC contributes without explaining every
stall; the benchmark is normalization/replacement evidence, not REST ingestion
or full runtime acceptance.

The primary session completed sequential 512-row normalization jobs, preserving
global duplicate/conflict checks, raw source metadata and retained inspection
ownership. Synchronous and asynchronous output equality and a conflicting
duplicate across the chunk boundary are tested. The final bounded fixture:

| Total rows | Maximum wall | Maximum CPU | Peak Python allocation | Loop p99 / max | Heartbeat samples |
|---:|---:|---:|---:|---:|---:|
| 128 | 4.071 ms | 15.625 ms | 48,975 B | 6.801 / 6.801 ms | 4 |
| 4,096 | 32.385 ms | 31.250 ms | 1,135,521 B | 9.670 / 9.670 ms | 23 |
| 50,000 | 379.857 ms | 390.625 ms | 14,179,219 B | 9.349 / 41.341 ms | 225 |

After D-064's bounded flat check, the fixture was rerun: 50,000 rows, three
untraced normalization samples, maximum wall 386.279 ms and CPU 390.625 ms;
peak traced allocation 14,177,227 B; loop p99 11.334 ms, maximum 40.203 ms
over 238 heartbeat samples. All declared bounds still pass.

All predeclared fixture bounds pass. Sparse small-workload samples do not
establish production tail guarantees. The earlier miss remains above for audit;
the change does not justify clearing any account, transport or live launch gate.

## D-064 primary-account policy and remaining contracts

No durable opening basis, cash-flow journal, hold reconciliation or settlement/
correction P&L application is implemented. The API documents no shared
history/private-stream barrier. Repeated matching reads cannot establish one.
The operator selected primary subaccount 0 for exclusive bot use and a verified
flat opening. Offline evidence now blocks a nonprimary scope or any nonzero
position/resting order, while a zero-quantity position row is not treated as
open inventory. This is policy plumbing, not a current account inspection.
Fresh flatness/exclusivity evidence and the launch-time boundary remain open.
Member funding and intra-exchange attribution remain unknown. Missing terminal
cursors deliberately make inspection unavailable even where the venue schema
allows omission.

Priority 4 may proceed with an isolated injected write-budget component; actual
dispatch/admission and launch remain blocked. No live bot action, venue API
request, ledger migration, configuration change, commit or push occurred.
