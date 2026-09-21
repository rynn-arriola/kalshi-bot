# D-052 — Native Windows supervisor review fixes

Review status: [independent Astra re-review](REVIEW_D052_ASTRA.md) requires
four P2 follow-ups and one P3 identity validation fix. The evidence below records
implementation results, qualified by that review. D-053
[implements the follow-ups](BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md) and
awaits Astra re-review; S2 remains blocked.

Date: September 21, 2026. Native Windows; execution disabled. Implements R1-R7
from the [D-051 independent Astra review](REVIEW_D051_ASTRA.md) after operator
approval. This is Sol implementation evidence and requires Astra re-review.

## Fix mapping

- **R1 — trusted ordering and stop fencing.** Child identity/lifecycle filtering
  precedes payload clock handling. SQLite records both diagnostic event time and
  a wall-anchored monotonic control time. STOP and safety disarms advance the
  generation so an already-prepared ARM cannot clear the latch.
- **R2 — lifecycle ownership.** Spawn failure can release only an unconfirmed
  reservation. Duplicate/late start acknowledgements and out-of-phase status are
  stale; confirmed child identity remains owned until confirmed process exit.
- **R3 — useful progress.** A work deadline requires a fresh heartbeat, is
  anchored to last useful progress and has a 60-second maximum extension.
  Incident reset requires continuously fresh increasing progress observations.
- **R4 — retry holds.** Holds persist through status, exit and restart, block
  due/start/ARM decisions, and can be removed only with an explicit generation-
  bound `HOLDS_RESOLVED` event.
- **R5 — startup deadline.** Reservation time anchors one absolute 60-second
  startup bound. The 30-second running-progress rule does not preempt startup,
  and STARTING heartbeats cannot extend the absolute deadline.
- **R6 — truthful death recovery.** `process_exited`, cleanup success/failure and
  unresolved work are separate evidence. Unknown survival retains child
  ownership and blocks. Confirmed unexpected death may enter bounded recovery
  without claiming cleanup, while unresolved reasons remain visible and prevent
  a healthy label until clean recovery completes.
- **R7 — meaningful idle fixture.** Each timed wake now writes healthy status and
  tick decisions through a disposable transactional SQLite journal. Pure-policy
  timing remains separately labeled.

The supervisor/store schema is version 2 and deliberately refuses incompatible
existing S1 control databases. S1 was never deployed, so no live migration was
performed or authorized.

## Verification

- Focused supervisor suite: **46 tests passed in 0.202 seconds**; the same module
  passed **10/10** repeated runs.
- Exact complete suite: **850 tests passed in 75.922 seconds**.
- Offline 5,000-decision fixtures passed at 30 and 120 synthetic labels. P99 was
  0.1858 ms and 0.1731 ms; peak traced memory was 173,304 and 164,400 bytes.
- The 60.014-second idle fixture woke 60 times, performed and retained **124**
  policy/journal events, consumed 0.203125 CPU seconds (**0.3385% of one core**),
  and kept `live_ready=false`.
- Native disabled preflight returned expected exit 2 with `live_ready=false`,
  `creates_files=false`, `credentials_accessed=false` and
  `network_accessed=false`.
- Byte compilation and `git diff --check` passed. Documentation links and secret
  scanning are included in the final repository checks before publication.

No process launcher, IPC, runtime wiring, service/task, bot restart, account or
network access, credentials, orders, cancels or live authority were added. S2
requires independent Astra re-review, the separate D-048 review and a new
operator assignment.
