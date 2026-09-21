# Bounded offline cancel/reducer dispatcher — D-062 / priority 4

September 21, 2026. `src/kalshi_bot/dispatch.py` connects a synthetic,
injected candidate producer to the existing durable writer and sole injected
executor. `offline_fixture=True` is mandatory. It has no credential, network,
transport, runtime hook, or live-order branch.

One writer claims one dispatcher. At most 128 market keys are coalesced by
priority: safety cancel, due IOC, passive reducer. Only one task writes; after
caller cancellation, that task retains outcome ownership until it finishes.
The queue never holds a prepared mutation or an old advisory plan. A fresh
candidate binds exact ticker, order or reducer terms, subaccount, explicit
exchange shard and typed evidence. After reserving from the local write budget,
the dispatcher refreshes it again; route changes requeue the key without a
durable mutation. The writer verifies the latest cancellation or managed exit,
creates a durable PREPARED receipt and passes it to the one executor. Quota
expiry before handoff aborts unsent work. The permit remains outstanding through
the awaited durable SENDING handoff and is consumed synchronously at the
injected send edge. Expiry during that handoff causes no transport call and a
conservative UNKNOWN/reconciliation hold. UNKNOWN sends and post-SENDING proof
failures latch the dispatcher failed without blind retries. Cancel ACK remains
nonterminal until account order/fill reconciliation establishes terminal proof.

`run_one()` is caller-driven: WAITING returns a delay hint but does not sleep,
retry or spin. `stop()` prevents new work; `close()` retains and joins the one
active operation. It cannot assert venue cancellation or flatten inventory.

Initial verification: 12 dispatcher tests and 33 budget tests passed. The full suite ran
1,013 tests: 1,012 passed, one expected Windows symlink-privilege skip in
134.462s. Disabled preflight exits 2, reports `live_ready=false` and no file,
credential or network activity. The synthetic write-budget 30/120-shard CPU/allocation
fixture passes; see [budget evidence](BUILD_WRITE_BUDGET.md). Unit tests cover
priority, coalescing, bounds, real writer/executor handoff, waiting, route
changes, quota expiry, pre/post-SENDING denial, cancellation ownership and an
injected uncertain transport result. No account, credentials or live network.

After the send-edge correction, **48 focused tests** pass; the complete suite
ran **1,018 tests, 1,017 passed and one expected Windows symlink-privilege
skip** in 134.890s. Disabled preflight still exits 2 without file, credential
or network access. The new fault test checks that an outstanding permit remains
held through the awaited SENDING transition, and expiry there produces zero
injected calls and durable UNKNOWN rather than an unsafe send or blind retry.
An asynchronous callback is rejected before SENDING.

Follow-up: [source-bound candidates](BUILD_DISPATCH_SOURCES.md) now connect
current runtime/management evidence, block missing/stale proof, recheck sources
at the final edge and fence dispatcher stop through preparation/submission.
Denied handoffs release their unused quota permit. Remaining: verified production
inputs, retained quota/429 lifecycle across restart and supervised runtime
composition/fault verification. These checks exist only on the injected path.
Connect the real write transport and runtime/supervisor lifecycle
only after account baseline and separate live-authorization gates. The fixture
cannot be enabled by changing a flag; new reviewed production authority is
required. No existing venue order has been modified.
