# Unattended recovery and quote rebuilding

D-110 addresses the four defects reproduced in Finding 169. It preserves one
runtime, one account coordinator, one writer and the existing ranked dispatcher.
It does not replay stale orders or relax account, risk, loss, ownership,
reference-price, reward or market-selection gates.

## Runtime recovery

- Account, book and lifecycle readers use bounded connection rounds. Three rapid
  failures produce a 30-second inter-round wait, increasing to at most five
  minutes. A subscription ACK does not reset history; the connection must remain
  subscribed for 60 seconds. Disconnect immediately revokes affected proof.
- REST transport failures and final HTTP 429/5xx responses get the same bounded
  recovery-pass cooldown. Invalid data, ambiguous scope, writer/engine failure,
  economic restrictions and uncertain mutations remain terminal holds.
- Runtime status exposes retry rounds. The child reports reconnect/recovery waits
  as `recovering` and persistent integrity states as `degraded`, never healthy.

## Crash recovery and fresh rebuild

An unexpected child death still launches recovery-only. That child may reconcile,
cancel owned entries and reduce inventory, but cannot create entries. Only its
verified-flat CLEAN result preserves the original still-armed parent and queues
one fresh normal child. The normal child refreshes the candidate universe,
re-ranks current markets and uses the ordinary dispatcher to refill. Manual STOP,
retry holds, incomplete cleanup, loss/economic restrictions and integrity or
unknown outcomes never enter this path. The existing restart budget remains.

## Accounting retention

The hot journal and current 64 exact compressed archives remain unchanged. When
that exact archive generation fills, only already-superseded `inspection`, `cash`
and `operational_release` archives roll into one cumulative hash commitment.
The commitment binds the prior root, exact archive IDs, counts, byte totals and
time bounds. Current hot observations and all fills, fees, settlements, cash
activity, conflicts, holds and other economic rows remain exact. A cold open
validates the commitment and current archives. This intentionally trades old
snapshot reconstruction for bounded non-economic retention; it never erases an
accounting hold or grants authority.

## Verification

Offline regressions cover persistent reconnect rounds, healthy-time reset rules,
transient REST restoration, non-transient exhaustion, truthful health projection,
unexpected death through recovery-only to a fresh normal child, manual-stop
non-resumption, archive rollover and cold validation. Windows supervisor and
complete-suite evidence is recorded in `STATUS.md`. The pre-restart release gate
passed 1,662 tests with one expected Windows privilege skip; the final 49-test
reader module and 274-test fast plus native-supervisor gate also pass.

## Live acceptance

The supported generation-106 stop canceled 30 owned orders and reached verified
flat cleanup before disarming. Generation 108 then loaded the published D-110
build, ranked 1,024/1,024 markets, and rebuilt 30 orders across 15 $2+ priority
markets. The stable sample has all readers subscribed, current account proof,
zero positions, retry rounds or blockers, healthy logging/dispatch and SQLite
`quick_check=ok`. This verifies startup and rebuild, not an artificial crash.
