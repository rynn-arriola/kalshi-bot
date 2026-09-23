# D-096: initial combined-ranking checkpoint

## Behavior

Both existing public book shards and the shared metadata scheduler continue
concurrently. Normal broad discovery starts an in-memory checkpoint immediately
before its runtime tasks. Only new entry proposals wait; account reconciliation,
fills, cancellations, inventory exits, book processing and metadata keep running.

The checkpoint opens after every reviewed ticker has reached a source-backed
ranking evaluation (including economic/unsupported-input rejection), or after
120 monotonic seconds. A complete current catalog may also rule out an unrewarded
ticker. Missing catalog/book/metadata/account evidence does not count as evaluated.
The timeout is an explicit bounded constructor option (1–300 seconds), not a
changed capital, risk, reward or freshness setting. The 120-second default gives
the measured 90–96-second cold census headroom, not a promised live scan duration.

Before release, book epochs/failure changes, metadata generations and catalog
publication changes discard accumulated coverage without extending the deadline.
After release this is a one-time historical checkpoint, not a periodic all-market
barrier. A new runtime starts fresh; recovery-only composition has no checkpoint.

The existing selector then ranks **currently valid** rows from both feeds:
$2+ projected remaining reward first, then $1–<$2 fallback; unchanged reward-rate
and capital-efficiency ordering within tiers. Existing per-market, account, writer,
price, quota and source proofs still repeat at dispatch. Direct dispatch cannot
bypass the checkpoint. No stale score is retained as order authority and there
is no change to the venue API or mutation payloads.

`selection.initial_ranking` exposes waiting/coverage_complete/timeout_partial,
elapsed time, evaluated/missing totals, eight missing samples, per-shard coverage
and reset count. Release coverage freezes and is explicitly historical, not a
simultaneous freshness claim. `selection.last_proposal` adds bounded candidate
reward samples and a priority-addition count; proposals are not placed orders.

## Boundaries

Timeout allows only independently eligible **known current** candidates. It
does not invent results for unavailable markets or guarantee globally optimal
allocation. Metadata may expire while other markets load; those expired rows
remain excluded. An eventual better candidate does not displace an incumbent.
No automatic repricing, reward-chasing cancellation, new connection, REST poll,
extra worker, larger retry budget or widened risk limit was introduced.

Coverage has at most 1,024 keys, O(1) observation and a constant-size epoch check
per evaluation. Full coverage counts/samples are rendered only for status. The
existing 250ms entry scheduler polls the barrier; it does not block the engine
waiting for a feed. Existing REST quota/concurrency and snapshot refresh remain.

## Verification and deployment

Published/deployed as `bf03b56`; final normal-run acceptance is in STATUS. Live
waiting released at 120.132s with 864/1,024 evaluated, then reached 30 resting
orders. This verifies the bounded partial-release path, not full simultaneous
coverage. Subsequent markets continued entering the current ranking.

Synthetic regressions exercise delayed opposite-shard priority, metadata delay,
economic rejection, missing versus complete reward catalog, stale evidence at
timeout, reconnect/metadata epochs, direct dispatch refusal, safety cancellation,
bounded scope and invalid clocks. The existing composed fake-wire startup and
1,024-book tests exercise the actual production composition without venue access.

The broad benchmark now explicitly reevaluates initially interrupted dirty rows
and bounds/reports proposal retries when its synthetic private sentinel arrives
during the writer await. Source rejection remains correct behavior; these are
fixture scheduling changes, not relaxed runtime checks. Timings and final suite
results are recorded in [STATUS](../STATUS.md).

The initial full-suite attempt used the canonical checkout's virtual environment
with a temporary import override. Native child processes deliberately strip that
override, so their source-identity checks refused the isolated checkout. This was
not a valid native acceptance run. A private ignored virtual environment now
loads this checkout's source and reuses installed dependency libraries; the
native 12-test suite passes there. No identity check was weakened and no live
environment was edited. Reversing the checkpoint in memory makes the delayed
priority regression fail, confirming it detects the original early-entry behavior.

Built in `fix/initial-ranking-checkpoint` away from the running package so its
supervisor recovery fingerprint remains intact. D-096 separately authorizes
controlled stop, verified flatness, deployment and restart after review. The same
ledger and all limits must be preserved; no force-kill or second live bot.
