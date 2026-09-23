# Lifecycle reconnect recovery — D-087

## Observed failure and diagnosis

At 21:24:27 Eastern on September 22, the unchanged production child remained
running with 14 resting entries and no positions, but `lifecycle` was permanently
`retry_exhausted` after three connection attempts. The detailed reader-failure
records had already rotated out of the bounded JSONL logs, so the exact original
transport cause is **UNKNOWN** and is not relabeled as a venue outage.

A separate read-only subscription using the same documented
`market_lifecycle_v2` command and existing credentials acknowledged successfully
and stayed connected for the observation window. That verifies the current
channel/entitlement contract; it does not reconstruct the earlier failures.

The code defect is independently verified: `_connection` allowed three attempts,
then returned normally and left any reader—including this advisory source—in
`retry_exhausted` for the remaining process lifetime. The runtime deliberately
kept running, so neither the supervisor nor another owner could restore the
lifecycle source. Restarting would reset the symptom without repairing recovery.

## Repair

Only the lifecycle reader receives continuing retry rounds:

- Three attempts per round retain the existing 1/2-second attempt backoff.
- Exhausted rounds enter `retry_wait` for 30, 60, 120, 240, then at most 300
  seconds. One socket/task exists at a time; there is no detached worker.
- Every attempt increments a monotonic lifecycle generation. A later round can
  never reuse an old generation or accept an old delivery.
- Every disconnect invokes the existing `ExitInputService.disconnect`: terms,
  overlays, pending reads and source authority are revoked before retry.
- `reader_retry_wait` is a bounded structured event. Status exposes round and
  attempt totals without payloads or exception text.
- Runtime stop/cancellation joins the sleeping/reconnecting task. Writer or
  engine failure still ends retry. Account and book readers retain their prior
  finite exhaustion rules because they own financial/sequence authority.
- Lifecycle reconnection does not reset metadata scheduler exhaustion, catalog
  exhaustion, candidate reviews, risk, accounting or order state. Only fresh,
  sequence-valid lifecycle events can supplement current metadata again.

## Verification and limits

A synthetic integration fails exactly three lifecycle readers, crosses a
30-second retry wait, then subscribes on attempt four. It asserts generations
1–4, delay sequence 1/2/30, one retry round and joined shutdown. The existing
lifecycle routing/disconnect, connection-exhaustion, private continuity,
diagnostics, source-refresh and read-only probe tests remain green: **161 tests**.
The final complete suite also passes: **1,478 run, 1,477 passed, one expected
Windows privilege skip**.

The current live process was not modified or restarted. Its lifecycle remains
exhausted until D-087 is deployed through a controlled stop/update/restart. This
repair does not address the independently exhausted reward catalog; D-086 does.
Postdeployment acceptance requires both readers subscribed, a complete fresh
catalog and no weakening of source/economic filters.
