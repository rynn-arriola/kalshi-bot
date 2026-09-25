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
ordinary-entry mutations, 8,192 total mutations and 4,096 intents/orders. Originally, at 128
archives new archival stopped; D-129 below replaces that stop with rollover.

Focused regressions cover boundary recovery, active-episode refusal, tamper
refusal and existing cancellation headroom. A disposable backup of the stopped
production ledger verifies the real eligible shape, transaction time, SQLite
integrity, cold reopen and unchanged financial/risk/accounting hashes. Final
release verification passes 1,787 tests with one expected Windows privilege
skip. Deployment evidence belongs in `STATUS.md`.

## D-129 terminal-episode archive and rollover

Finding 196 showed ACK/rejected/unknown rows accumulating toward the same
4,096 ordinary-entry boundary, with order/intent evidence close behind. D-129
adds a second exact archive record type inside the same reservation
transaction. It never changes the limits, retries or strategy.

**Eligibility (all required):** episode `RETIRED` and created at least ten
minutes ago; ticker flat in the ledger; every episode credit `SPENT` or
`RELEASED`; every owning client's intent `TERMINAL`, `REJECTED` or `ABORTED`;
every order terminal with zero fills, bound to a `TERMINAL` intent, and absent
from `fills`, `recovery_fills`, `pending_fills` and operator fill scopes; creates
`ACK`/`REJECTED`/`NOT_SENT`, cancels `ACK`/`REJECTED`/`UNKNOWN`/`NOT_SENT`; every
related create/cancel covered by that episode's authorizations; no
authorization `PREPARED`/`SENDING`; the newest row older than the quiet window.
Anything else stays hot. Episodes with any fill are never archived.

**Record:** version 2, up to 128 episodes, each with its exact episode,
mutation, authorization, intent, order-evidence, credit and fee rows. The
episode row remains hot with state `ARCHIVED`; the other rows are deleted after
the archive insert in the same commit, and trigger-owned counters fall.

**Triggering:** checked on entry reservation once any resource reaches 75% of
its bound (entry mutations, or used+held intents/orders), at most once a
minute, with minimum batches (128 proven-unsent rows, 32 episodes). At 90%, or
at the entry boundary, every reservation reclaims with no minimum. Supporting
indexes cover episode state and authorizations by episode.

**Rollover:** at 256 exact archives the oldest 128 fold into
`command_archive_rollup`, a SHA-256 chain over their immutable metadata (IDs,
counts, first/last timestamps, prior root). Newer archives stay exact. Startup
validates every exact archive (digest, schema, per-episode invariants, unique
identities, hot-table disjointness, `ARCHIVED` episode state) and the rollup
digest/metadata; any conflict fails closed.

**Verification:** eight D-129 regressions (continuation at the boundary, quiet
window, fill-bearing episode stays hot, below-pressure no-op, tamper and
hot-restore refusal, rollover and tampered rollup). On a disposable copy of the
running production ledger, ten passes archived 1,280 episodes plus 72
proven-unsent creates in 169–250 ms each, lowering hot mutation/intent/order
use from 3,957/2,111/1,955 to 3,029/1,611/1,527, where pressure drops below the
threshold. SQLite `integrity_check` passed, a hash over every
financial/risk/accounting/history table was unchanged and a cold writer start
validated the archives. These are offline measurements; the copy never
touched the production file.
