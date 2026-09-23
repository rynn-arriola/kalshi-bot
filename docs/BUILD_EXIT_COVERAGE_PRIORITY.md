# D-103: exit recovery, broad-book capacity and priority admission

## Implemented behavior

Kalshi V2 permits `reduce_only` only with IOC/FOK. Passive inventory exits now
send venue-valid post-only GTC requests with `reduce_only=false`; their reducer
identity remains bound to the durable `managed_exit` authorization, exact
position, account generation, writer revision and current management proof. The
single-create live transport accepts such a request only while armed with that
exact prepared authorization. Due IOC exits remain `reduce_only=true`.

An exhausted recovery with durable inventory now receives one bounded retry when
the existing 15-minute safety age or market deadline becomes due. It first
reacquires account proof and cannot dispatch from the stale plan that caused the
wake. The retry is once per inventory episode, so it cannot create an unbounded
recovery loop.

Normal broad discovery uses four deterministic public-book shards. The initial
ranking checkpoint no longer treats an incomplete timeout as entry permission.
It opens when either every reviewed market has a reasoned evaluation or current
$2+ candidates fill every presently available two-order slot (at most 15). An
early priority release remains priority-only until full coverage is reached;
later $1 fallback cannot inherit that partial proof. Once full coverage is
reached, $1 remains fallback. Existing qualifying owners are retained and later
$2 candidates fill natural vacancies; this change does not add reward-chasing
incumbent cancellation.

## Capacity evidence

The order-disabled probe ran two 15-second repetitions at 1,024 markets for both
two and four book shards. Every stage received 1,024/1,024 initial snapshots and
had 100% minimum/average five-second freshness. Four shards met all targets in
both repetitions (full snapshot 0.58/0.59 seconds, callback-ingress p99 68.5/42.5
ms). Two shards passed once and missed only the 100ms ingress-tail target once;
four is therefore the prepared production setting. The ignored artifact is
`data/book-capacity/90ce9cf0e59d4eba86f3e9bf5683ff04/result.json`. Each saved
stage includes one explicit result reason per market; console output omits the
large per-market list.

## Boundaries and verification

The bot remained stopped and flat. The capacity probe used public incentive REST
and public book WebSockets only; it made no private/account/order request. No
ledger, risk, capital, quantity, loss, reward threshold or exit deadline changed.
Official contract: <https://docs.kalshi.com/api-reference/orders/create-order-v2>.

Focused regressions cover passive/IOC payloads, durable reducer classification,
single-create authority, exhausted-recovery rearming, two/four-shard topology,
per-market probe outcomes, timeout fail-closed behavior and priority-capacity
release. Final review caught the event engine's old two-shard constructor bound;
it now accepts one to four validated shards and has an exact regression. The
focused set passes 402 tests; the post-fix complete suite passes 1,628 tests with
one expected skip. Publication evidence belongs in `STATUS.md`.
