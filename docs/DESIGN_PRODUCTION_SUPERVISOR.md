# Production supervisor recovery contract

This document defines the production connection between the existing Windows
native supervisor and the live liquidity runtime. The financial ledger remains
the source of truth; the supervisor control database is only a process-control
journal.

## Launch and ownership

- The operator explicitly arms one foreground supervisor with `--live`.
- `--initialize` is accepted only for the first opening. Once `account.db`
  exists, every child opens the existing approved ledger.
- The parent never reads credentials. A fixed child module owns credentials,
  the live-process lease, runtime resources, and cleanup.
- The parent and child authenticate each other with the existing Windows user
  ACL, named leases, inherited process handles, fixed fingerprints, and bounded
  IPC protocol. No PID-only adoption is allowed.

## Recovery rule

1. A normal child can create entries only while the existing runtime gates
   permit them.
2. An operator stop pauses entries and asks the same child to cancel owned
   entries and manage inventory until the account is verified flat.
3. An unexpected child exit records unresolved recovery work. A bounded parent
   restart launches the next child in **recovery-only** mode.
4. Recovery-only sets `entries_paused` before runtime composition. It may
   reconcile, cancel owned entries, and reduce existing inventory, but cannot
   create a new entry.
5. A recovery child that proves flat after an unexpected child death returns
   `clean`; the still-armed supervisor spends the existing restart budget to
   launch one fresh normal child. That child re-runs every startup, account,
   risk, reward, selection and reference-price gate before creating entries.
   A manual operator stop still disarms after verified-flat cleanup and never
   enters this automatic rebuild path.
6. Startup refusal, integrity uncertainty, retry exhaustion, local control
   failure, power-state change, or exhausted restart budget enters attention
   state and cannot auto-arm.

The default restart budget is three attempts in ten minutes with bounded
backoff. An ambiguous mutation is never cleared by retry: every restart uses
the same account ledger and the runtime's existing reconciliation rules.

## Failure boundaries

- A child result or exit code alone does not prove flatness. Only the live
  runtime's verified-flat result can produce a clean stop.
- A parent loss does not authorize a cold parent to adopt or resume a child.
  A future host watchdog may start a recovery process, but adding persistent
  Windows startup behavior requires separate operator approval.
- No supervisor command starts a detached process. The foreground parent stays
  responsible for its exact child and exits only after owned cleanup.
