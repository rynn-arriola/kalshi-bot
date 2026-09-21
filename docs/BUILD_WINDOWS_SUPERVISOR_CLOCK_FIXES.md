# D-054 — Native Windows supervisor clock review fixes

Date: September 21, 2026. Native Windows; execution disabled. Implements R1/R2
from the [D-053 independent Astra review](REVIEW_D053_ASTRA.md) after operator
approval. This is Sol implementation evidence and requires Astra re-review.

## Fix mapping

- **R1 — stale events cannot consume local clock distrust.** The policy derives
  child identity/lifecycle staleness without mutating state, then applies an
  untrusted local control-clock sample first. It persists attention, fences the
  armed generation, requests graceful stop when a child is owned, and retains
  the ignored payload's `stale=true` journal label. Stable later samples cannot
  remove the hold or restore spawn/status authority. Trusted calls still filter
  stale child timestamps before event-time regression checks.
- **R2 — tolerant persisted default continuity.** The default path stores an
  estimated boot epoch but treats it as evidence with the same two-second
  wall/monotonic tolerance, not an exact freshly quantized identity. Trusted
  samples retain the prior persisted identity across store handles and reopen.
  Wall/monotonic divergence or monotonic regression installs a new checkpoint
  only with a durable clock-untrusted hold. An injected platform boot provider
  still requires exact boot identity as well as valid deltas.

## Regression coverage

The new tests cover pure-policy local distrust with a stale payload; stale and
missing child identity through two store handles and reopen; duplicate child
start while active; retained child ownership, graceful stop and later confirmed
exit; blocked following tick/start/status; default near-boundary 2 ms sampling
skew; alternating store instances; and forward, backward and monotonic default
clock discontinuities. Four selected new tests fail when the `b051067` policy
and store are loaded in memory, proving they detect the reviewed parent defects.

## Verification

- Focused supervisor suite: **64 tests passed in 0.439 seconds**; the same module
  passed **10/10** repeated runs (0.415–0.496 seconds each).
- Exact complete suite: **868 tests passed in 76.297 seconds**.
- Offline 5,000-decision fixtures passed at 30 and 120 synthetic labels. P99 was
  0.1841 ms and 0.1676 ms; peak traced memory was 173,328 and 164,400 bytes.
- The 60.006-second idle fixture woke 60 times, retained **124** policy/journal
  events, consumed 0.265625 CPU seconds (**0.4427% of one core**) and kept
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
