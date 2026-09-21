# D-053 — Native Windows supervisor re-review follow-ups

Date: September 21, 2026. Native Windows; execution disabled. Implements R1-R5
from the [D-052 independent Astra re-review](REVIEW_D052_ASTRA.md) after operator
approval. This is Sol implementation evidence and requires Astra re-review.

## Fix mapping

- **R1 — repeated STOP fencing.** Every accepted STOP advances the control
  generation, including while already stopping. Child ownership retains its
  original generation so an exit can still be joined, while any ARM prepared
  before the latest STOP becomes stale.
- **R2 — deadline ordering and continuous health.** Startup and useful-progress
  expiry is evaluated from the prior state before a child status can refresh
  heartbeat/progress fields. A status after a 600-second observation gap stops
  the child and cannot refund incident attempts.
- **R3 — failed-spawn finalization.** Reservation release preserves an existing
  attention reason when the final state remains `ATTENTION_REQUIRED`, so the
  transition commits instead of failing validation and rolling back.
- **R4 — cross-instance clock continuity.** Schema 3 stores one transactional
  boot, wall, monotonic and normalized-control checkpoint. Every store instance
  compares against the shared checkpoint. Boot changes, monotonic regression or
  wall/monotonic divergence fail closed as `clock_untrusted`; trusted elapsed
  time alone may advance cooldowns. The undeployed S1 schema 2 remains refused
  rather than silently migrated.
- **R5 — mandatory child identity.** Spawn/status/result events are stale unless
  both current and event child IDs and generations are present and equal.
  Missing or partial identities cannot mutate childless states.

## Verification

- Focused supervisor suite: **59 tests passed in 0.374 seconds**; the same module
  passed **10/10** repeated runs (0.315–0.417 seconds each).
- Exact complete suite: **863 tests passed in 79.164 seconds**.
- Offline 5,000-decision fixtures passed at 30 and 120 synthetic labels. P99 was
  0.2025 ms and 0.1584 ms; peak traced memory was 171,312 and 164,400 bytes.
- The 60.013-second idle fixture woke 60 times, retained **124** policy/journal
  events, consumed 0.21875 CPU seconds (**0.3645% of one core**) and kept
  `live_ready=false`.
- Native disabled preflight returned expected exit 2 with `live_ready=false`,
  `creates_files=false`, `credentials_accessed=false` and
  `network_accessed=false`.
- Byte compilation, `git diff --check`, changed-document local-link audit and
  staged-content secret scan pass before publication.

No process launcher, IPC, runtime wiring, service/task, bot restart, account or
network access, credentials, orders, cancels or live authority were added. S2
requires independent Astra re-review, the separate D-048 review and a new
operator assignment.
