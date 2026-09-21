# Offline write-budget foundation — D-062 / priority 4

September 21, 2026. This is the smallest independent slice while priority 3's
opening boundary/accounting gates remain open. It neither installs a production
transport nor grants mutation authority.

## Contract

Use one caller-driven local write-budget owner for the account. Explicit
`offline_fixture=True` is mandatory. There are no tasks, sleeps, network calls,
credentials, CLI activation or runtime wiring. Inject complete limits/cost
evidence, opaque account scope, wall/monotonic clocks and explicit freshness.

Support only single create (`POST /portfolio/events/orders`) and single cancel
(`DELETE /portfolio/events/orders/{order_id}`), with explicit shard routing.
Normalize the API prefix once and retain method/path identity. Use the supplied
default/overrides, not a hardcoded cost. Shard 0 uses unscoped Write, positive
shards use their own Write buckets, shared across subaccounts. Reject automatic
routing, batches, perpetuals and unrelated operations in this slice.

Start local token estimates empty. Capacity is not available server tokens.
Bound configured shards and outstanding permits at 128 each. Issue a single-use
permit only after sufficient tokens; bind it to owner, exact operation/shard,
evidence revision and freshness. Validate the actual issued object before
consumption; copied/relabelled/stale/cross-owner permits are invalid. No refunds.

Refresh requires newer evidence with the same scope, resets estimates and
invalidates outstanding permits while preserving throttle pauses. A late 429
still clears the current affected bucket and revokes its permits. Expiry,
unknown grants or clock failure block even cancellations; a token permit does
not waive account/order proof. No automatic retry is introduced.

## Source evidence

Checked the exact local OpenAPI operations and shared schemas against current
[rate limits](https://docs.kalshi.com/getting_started/rate_limits) and
[endpoint-cost documentation](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs).
REST/FIX share applicable budgets; Read is separate. Single explicit shard
writes differ from auto-routed and batch charging. Current account limits and
external usage remain unobserved; synthetic fixtures establish local behavior
only. Existing `quota.parse_candidate` validates grants and write fields but
retains GET cost overrides only, so it cannot supply the write cost table alone.

## Tests and next integration

Deterministic fixtures must cover initial zero balance, exact costs/methods,
shard isolation, bounded scope, no reuse/tampering, TTL and grant expiry,
refresh/cooldown, late 429, rollback clocks and forbidden live/auto/batch modes.
Measure 30/120-shard fixed-work scheduling as local arithmetic, separately from
network/token waits; targets <250 ms CPU and <8 MiB incremental Python allocation.

A later bounded dispatcher queues market re-evaluations, never stale prepared
receipts: safety cancels, due IOC exits, passive reducers, then future entries.
Reserve tokens before durable SENDING, refresh the advisory plan, prepare once
through the existing writer, then use the sole executor. Partial fills require
terminal cancellation plus accounted-fill evidence before replacement.
UNKNOWN sends retain recovery holds; shutdown must join owned outcome work.
These dispatcher connections are not implemented by the budget primitive.
