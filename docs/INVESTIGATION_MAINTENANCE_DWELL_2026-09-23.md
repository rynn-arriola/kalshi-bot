# Non-scoring incumbent retained: evidence-gap investigation

Read-only investigation, 2026-09-23. Production source `ad96429`, supervisor
generation 63. No source/configuration change, deployment, restart or assistant
order action. Synthetic checks used disposable test fixtures in the isolated
`kalshi-order-maintenance` checkout.

## Observed issue

`KXORBOFHARVEST-27NOV30-T180` retained a 52-cent YES-equivalent bid. At
13:32:33 UTC production maintenance identified a 53-cent bid reference and
cutoff, classified that order `outside_reward_cutoff`, showed no target
blockers, and reported `action=retain`, with no maintenance cycle.

A 90-second read-only observation of the atomically published runtime status
at 13:36:13–13:37:42 UTC produced 90 samples: 81 UNKNOWN, two with the market
missing from the saved plan set, and seven OBSERVED. There were only two
distinct OBSERVED timestamps, 13:37:34.151039 and 13:37:39.387510 UTC, separated
by **5.236471 seconds**. Both identified the bid outside the then-current
71-cent reference/cutoff, with no target blockers and action retain. No cycle
started. Account snapshots were current in 61 samples; account-wide reflection
completed ten times and failed ten times during this interval. The bot retained
30 orders and no reported positions throughout.

These are one-second samples of published status, not an instrumented trace of
every maintenance call. Internal dwell state and exact reflection rejection
reasons are not published; a reset at a particular live call is therefore an
inference, not directly observed. Missing plan samples do not prove lost orders.

## Mechanism and reproduction

`quote_maintenance.py:refresh` requires 30 seconds of repeated fresh drift
observations to start repricing (90 seconds for an unrepairable unscoring pair).
It resets the start timestamp whenever the gap between valid drift observations
exceeds five seconds. Ordinary fully qualifying observations also reset it.

`reward_runtime.py` schedules reflection four seconds after each reflection
attempt finishes. Proof binds to the exact account report object and revision.
`runtime.py:_live_refresh` requests account reconciliation once the report is
about three seconds old; replacing that report invalidates prior reflection.
Fresh books, metadata and management plans must also coincide. Thus normal
refresh timing and failed joins can repeatedly prevent the dwell from finishing.

Using the real `MaintenanceTests` fixture and unchanged implementation:

| Fresh, always-drifting sample spacing | Simulated elapsed | Repricing starts |
|---|---:|---|
| 2 seconds | 34 seconds | Yes |
| 4 seconds | 40 seconds | Yes |
| 6 seconds | 180 seconds | No |
| 8 seconds | 184 seconds | No |

All failing-to-act scenarios still produced OBSERVED, outside-cutoff status
with a valid repair target. This verifies the timing starvation mechanism;
the live status pattern strongly supports it as the present explanation.
Existing maintenance suite: **21 tests passed**, 11.294 seconds. Existing tests
verify regular observations and deliberate reset behavior, not progress under
ordinary repeated gaps. No fix is claimed.

## Recommended next change (not implemented)

Coordinate reflection with a newly reconciled account report and prioritize
maintenance for owned markets. Keep a bounded record of verified drift across
short evidence gaps without counting unknown time as verified drift; reset on
qualifying recovery, changed orders/program/generation, fills or a long gap.
Require fresh complete evidence again at decision and dispatch. Add regressions
for live-like reflection/account timing, bounded gaps, fills and genuine recovery.
Do not simply lengthen source freshness or act on an old book. The proposed dwell
semantics would revise the current D-098 contract and need an accepted decision.

Local ignored evidence: `data/maintenance-dwell-live-observation.json` and
`data/maintenance-dwell-reproduction.json` in the isolated checkout.
