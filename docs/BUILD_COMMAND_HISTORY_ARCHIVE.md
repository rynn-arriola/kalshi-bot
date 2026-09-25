# Exact proven-unsent command archive

D-125 completes the bounded maintenance phase deferred by D-060 without changing
its capacity policy. When hot mutation use reaches the 4,096 ordinary-entry
boundary, the serial ledger writer may archive at most 512 creates only when all
of the following are durable: phase `NOT_SENT`, aborted matching intent and sole
authorization, no order evidence, no held owned credit, no second mutation for
the client identity, and a retired episode.

The transaction stores canonical JSON containing the complete mutation, intent,
authorization and owned-credit rows in a zlib-compressed, SHA-256-addressed
archive. Only after insertion does it delete those exact hot rows; trigger-owned
capacity counters fall in the same commit. Startup validates archive count,
compressed and decompressed bounds, schema, digest, metadata, unique identities,
hot-table disjointness and retired episode state. Invalid evidence fails closed.

ACK, rejected, unknown, active-episode, order/fill, P&L, position, risk and
accounting evidence cannot enter this archive. The unchanged limits remain 4,096
ordinary-entry mutations, 8,192 total mutations and 4,096 intents/orders. At 128
archives, new archival stops and normal capacity refusal resumes.

Focused regressions cover boundary recovery, active-episode refusal, tamper
refusal and existing cancellation headroom. A disposable backup of the stopped
production ledger verifies the real eligible shape, transaction time, SQLite
integrity, cold reopen and unchanged financial/risk/accounting hashes. Final
release verification passes 1,787 tests with one expected Windows privilege
skip. Deployment evidence belongs in `STATUS.md`.
