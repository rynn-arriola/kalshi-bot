# Final current-path review — 2026-09-22

Reviewed code: `481861295c1763e0f78a61b441f3e55951f763c8`.
Scope: the existing supervised production launcher and original live runtime,
not the retired REST canary, future watchdog or other pending improvements.
**Result: changes required before live acceptance.** This review supersedes
the earlier informal readiness assessment; it does not authorize a launch.

Read-only process inspection found no active Kalshi production child/runtime.
The review therefore covers the code intended to run, not observed live trading.
No production credentials, ledger, orders, venue requests or runtime controls
were used. Synthetic probes use temporary ledgers and fake network wires.

## R1 — P1: loss hold does not withdraw existing entry orders

`src/kalshi_bot/runtime.py:223-245`, `live.py:311-334`, `risk.py:138`.

The durable loss window correctly reaches `held=True, cap=0` at $25 and the
selector/writer reject new entries. However, neither the runtime dispatch chooser
nor live supervisor translates that hold into entry cancellation. The chooser
requests cancellations for operator/recovery pause or inventory-management
reasons only. Flat markets retain their nonreducing entry orders. Those orders
can still fill after the stop until some unrelated cancellation or expiry.

VERIFIED synthetic reproduction: one owned resting size-10 entry, flat inventory,
fresh account/book, and a supplied held `WindowState` with realized P&L -25.
`runtime._evaluate` queued no cancellation; `source.refresh(SAFETY_CANCEL)`
returned no candidate; the portfolio retained one entry. This supplies the risk
result to exercise its missing consumer, rather than claiming a real trading loss.
`account_release.release` can return a successful accounting release with that
held window; it does not implement cancellation either.

Read-only Poly source comparison at
`b9ac0981e1780d4f99f97200ba0956978a273776`:
`src/liquidity_bot/live_commissioning.py:_observe_risk_window` sets
`_entry_pause_cancel_requested` on a new held window. Kalshi lacks that bridge.

Required repair: connect the durable hold to owned-entry drain while preserving
normal exact inventory management, reconciliation, and the existing no-reset
rules. Test hold arrival with entries across markets and after recovery. Do not
introduce forced liquidation or silently change lesser-tier cancellation policy.

## R2 — P1: incentive revocation is lost at the final entry-send fence

`src/kalshi_bot/dispatch_sources.py:22-26, 259-274`.

Entry refresh checks the selected program and incentive observation, but `_Proof`
retains only the management plan, account timestamp and encoded request. After
the awaited durable reservation, `validate_proof` checks the management sources,
not the incentive observation or current selection authority. Incentive discovery
invalidates selection/reward evidence without synchronously invalidating that
management plan. The async send can win before the dirty-market reevaluation.

VERIFIED synthetic reproduction: revoke all programs after pair reservation.
Selection becomes noncurrent, but final send proof remains true and the fake
batch wire receives both orders. Repeated using `LiveEntryTests` with real
production activation, accounting, dispatcher and mutation transport, replacing
only its venue wire with the existing synthetic wire: result ACK, one wire call.
The test intercepts `reserve_entry_pair` to publish revocation after its await.

Required repair: pin and recheck incentive/program and entry-selection input
authority across preparation and SENDING without mistaking the writer's own
revision advance for external invalidation. Test revocation/replacement/expiry
at both await boundaries; an unsent pair must never reach the wire.

## R3 — P1: graceful entry cancellation depends on a recent book update

`src/kalshi_bot/dispatch_sources.py:94`, `management.py:50-61`.

The shared dispatch fence rejects every action, including cancellation by exact
owned order ID, when `book_revision < 0`. The manager treats a book whose last
market update is older than five seconds as unavailable. A quiet healthy market
or lost book feed can consequently prevent operator-stop/recovery cancellation
despite fresh, reconciled ownership evidence. This can leave entries exposed
and keep graceful drain waiting; a later book update may unblock it, but there
is no independent cancellation path.

VERIFIED synthetic reproduction: the same owned unfilled entry produces a valid
cancel candidate while paused with a fresh book. Aging only book ingress by six
seconds yields no candidate while account evidence remains current. No book
price is needed to cancel that exact order ID.

Required repair: separate ownership/account-based cancellation proof from
price-dependent create/reducer proof. Retain account, order identity, route,
quota and durable-command fences. Test quiet/disconnected books and stale or
conflicting ownership separately; do not loosen new-entry or IOC price checks.

## R4 — P2: program deduplication precedes the new reward qualification

`src/kalshi_bot/ranking.py:134-162`, `selection.py:144-176`.

The board first picks one program per market by hourly reward. Only afterward
does selection apply the $1 floor and $2 priority. With overlapping programs,
a high hourly rate with little earning time left can hide another qualifying
program in the same market, excluding it or misclassifying its tier.

VERIFIED synthetic example on the same eligible book: FAST projects $6.984/hour
but only $0.058 remaining; LONG projects $3.521/hour and $3.521 remaining. The
selector chooses FAST first, excludes the market below $1, and never tries LONG.
This is a supported-input defect, not a claim that overlapping programs were
observed in today's venue snapshot.

Required repair: qualify and tier per-program candidates before choosing one
program per market; preserve compatible exact quotes, rate/efficiency ordering
inside tiers, and no double-counting of overlapping programs. Cover qualifying
fallback and priority programs hidden by a shorter, faster program.

## Verification and limits

Reviewed startup/activation, account ownership/accounting, catalog and candidate
preparation, selection/admission, entry reservation/send, partial-fill management,
passive/IOC exits, quotas, logging, stop/drain, and supervisor recovery/cleanup.
The existing D-081 repairs remain present; no new finding is asserted in their
ownership/cleanup fixes. No claim of exhaustive proof or live profitability.

Local reproducer: `data/review-final-4818612/probes.py` (ignored, synthetic only).
Run with `.venv\Scripts\python.exe -B data/review-final-4818612/probes.py`.
Its five probes confirm the four defects (R2 has both fixture and production-mode
coverage). Source code, tests, configuration and runtime state are unchanged.
Fresh standard verification:
`.venv\Scripts\python.exe -B -m unittest discover -s tests` ran 1,434 tests
in 217.273 seconds: 1,433 passed and one expected Windows privilege skip.
All five reproduction probes completed and confirmed their assertions.
`git diff --check` and 278 local links in the five review documents passed.
No general documentation-audit command exists in this checkout; the existing
reward-research audit is a separate artifact-specific check. Passing existing
tests does not cover these newly identified missing regressions.

Repair R1-R3 before launch, then correct R4 in the same focused fix pass. Rerun
the new regressions, relevant integration suites and complete offline suite,
review the fixes and publish. First supervised live acceptance remains separate;
no optional pending feature is added to this review's scope.
