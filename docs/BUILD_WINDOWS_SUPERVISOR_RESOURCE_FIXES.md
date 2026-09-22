# D-074 — native supervisor resource and readiness evidence

Implemented September 22, 2026 on native Windows. This clears the remaining
S2A resource target and records one fresh, read-only account quota observation.
It does **not** implement S2B, construct a live runtime, start the bot or grant
order authority.

## Resource fixes

The corrected benchmark attributed the idle parent cost to two paths:

- each serialized control operation reopened and retraversed SQLite WAL/SHM
  sidecars before repeating the same DACL check; and
- the one-second host timer durably committed an SQLite/FULL event even when
  policy changed only the observation timestamp.

`ProtectedControlFiles` now retains validated WAL/SHM handles for the lifetime
of the store. The handles allow SQLite read/write sharing but deny deletion and
replacement. Every control operation still validates the exact approved-user/
System DACL on the retained kernel objects; an unexpected journal sidecar is
still discovered and validated. This removes repeated path traversal and handle
open/close without reducing the security check.

The host routes timer events through `SupervisorStore.tick`. It samples and
validates the durable wall/monotonic clock pair and evaluates the complete
policy. It coalesces only a result with no action, no stale decision and no
material state difference other than `updated_utc`. Clock faults, restart/start
actions, healthy-budget resets, startup/progress/shutdown deadlines and every
non-timer event still commit before action. Direct `apply(TICK)` retains the
original fully journaled behavior for deterministic policy/store callers.

## Native acceptance

The full `scripts/benchmark_supervisor_native.py` workload passed all declared
targets with one inert S2A child and 100 lifecycle cycles:

| Measurement | Result |
|---|---:|
| Parent idle CPU, 60.004 s | **0.781%** (<1% target) |
| Child CPU | 1.172% (reported separately) |
| Event-loop delay p99 | 16.048 ms (<50 ms) |
| Policy latency p99 | 7.759 ms |
| Added working set | 39,587,840 bytes (<40 MiB) |
| Maximum message backlog | 1 |
| Warmed 100-cycle handles / native threads / Python threads | -2 / -2 / 0 |
| Retained supervisor threads | none |

The whole interpreter still retains 13 handles after first-use executor/native
initialization. This is bounded cold-runtime retention, not growth across the
warmed 100-cycle workload; the acceptance target is the warmed lifecycle delta.
No target was relaxed. The benchmark remains an inert process fixture, not a
30/120-market runtime or live-recovery test.

Focused S1/S2 verification runs 114 tests with one expected Windows symlink-
privilege skip. New regressions prove idle ticks do not advance revision/history,
action-bearing ticks and clock faults do, and retained sidecars cannot be renamed.
The quota compatibility follow-up passes 67 write/quota tests and 11 entry-
dispatch tests. Final complete suite: **1,352 run, 1,351 passed and one expected
privilege skip in 188.770 seconds**.

## Fresh quota evidence

At `2026-09-22T05:13:56Z`, the previously authorized read-only signer began a
bounded verification using only `/account/limits` and
`/account/endpoint_costs`. Five authenticated GETs were made in total: two
limits/cost pairs plus one costs-only inspection needed to diagnose and verify
the current path-template syntax. Every response returned HTTP 200; the final
pair passed both `parse_candidate` and `WriteQuotaSnapshot`:

Official contracts checked the same day: [rate limits](https://docs.kalshi.com/getting_started/rate_limits),
[account limits](https://docs.kalshi.com/api-reference/account/get-account-api-limits)
and [endpoint costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs).

| Input | Observed value |
|---|---:|
| Usage tier | basic |
| Read refill / capacity | 200 / 600 |
| Write refill / capacity | 100 / 100 |
| Default endpoint cost | 10 |
| Non-default cost rows | 17 |
| Event-contract grants | none |

The current document uses `:order_id` templates and includes an unrelated
`*endpoint` wildcard. The write-cost parser now validates both current forms,
canonicalizes `:order_id` to `{order_id}` and detects duplicates across forms.
The supported single-order DELETE override is 2; event-order create and batch
create plus the quota-control GETs use the observed default cost 10. This
resolves the current account quota/probe numbers for readiness; they must
still be refreshed by the existing guarded owner because account limits can
change. No response body, key ID, signature or private key was saved or logged.

## Remaining readiness boundaries

- The API does not expose a general direct/non-direct member field. Balance
  precision remains UNKNOWN until operator/account/support evidence establishes
  the fee profile; it must not be inferred from balances.
- Current [fee-rounding guidance](https://docs.kalshi.com/getting_started/fee_rounding)
  describes a per-order accumulator. The existing deliberately conservative
  bound charges a balance quantum per possible fragment and is therefore too
  pessimistic for economic selection, though still safe. Lowering it can admit
  more risk and requires an explicit reviewed/operator-approved fee-bound change.
- Timing review is market-specific and rules/milestone-bound. Reviews can be
  created only for the markets actually selected near launch and must expire on
  rule, milestone or early-close changes.
- Flat account/continuity/cash evidence must be captured at the approved launch
  boundary; an earlier snapshot cannot prove a later launch state.
- S2B production-runtime ownership/restriction transfer is not implemented.
  S2A resource clearance does not authorize a service, restart or live process.

No order endpoint, private stream, market request, bot process, deployment,
configuration change or Polymarket modification occurred.
