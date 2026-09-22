# D-078 — Automatic selection in the original launcher

## Scope and implementation

Reuse D-070/D-071 discovery and joined one-shard admission, not another scanner
or strategy. `live.compose` now attaches admission before runtime start.
`timing_reviews` supplies the bounded reviewed candidate universe; optional
`initial_tickers` seeds a subset. Default input files remain compatible.
Session permissions cover those exact reviewed candidates, not arbitrary catalog
rows. Durable exposure keys are always seeded; unresolved portfolio evidence
retains the entire reviewed universe for existing recovery, never authorizes entry.

`CandidateInputs` filters catalog rows on existing timing/member reviews and
known metadata/deadline/exchange failures. It keeps counts and at most 32 reason
samples per discovery pass, not per book tick. Existing head/tail exploration,
hourly reward/capital-efficiency ranking, whole size-10 pairs, max 30 resting
entries, capital/exposure/loss limits and stable owned markets are unchanged.
No automatic score-chasing cancellation or sports/category filter is introduced.

The metadata owner's separate registry preserves exact timing bindings through
retirement/re-admission, while active caches and retry budgets retain their
existing bounds. Explicit review revocation survives re-admission. Current
rules hashes, milestone type/primary-event binding, fee changes, tick grids and
entry deadlines are checked by the original metadata pipeline through shared
GET reads. New books still require WebSocket snapshots. Admission rechecks
candidate validity after reader join and defers during active dispatch/drain.
Entry dispatch also rejects explicit metadata-result blockers.

Full-graph testing exposed a scheduling defect: a rejected scope handoff was
counted as deferred but then labeled stable, suppressing the one-second retry.
The label now preserves deferral; no extra poller or shorter catalog interval is
introduced. An in-memory reversal reproduces the regression assertion failure.

No new API endpoint, mutation payload, quota budget, independent worker, persistent service,
private configuration or production process is introduced. The current official
[milestone definition](https://docs.kalshi.com/api-reference/milestone/get-milestone)
describes a milestone start and primary related events; it does **not** establish
a universal rules-to-risk mapping. Existing exact reviewed bindings therefore
remain required. Official pages inspected 2026-09-22; local schemas are in
[the API reference](KALSHI_API_REFERENCE.md).

## Acceptance and verification

Use credential-free temporary ledgers and injected wires only:

- Start subscribed to A; discover reviewed B and unreviewed U; automatically
  replace flat A, restore B's review, obtain fresh metadata/snapshot and submit
  one exact synthetic size-10 pair through the existing dispatch/account graph.
- Reject unsupported fees and explicit metadata blockers without writes.
- Preserve inventory/orders, review revocation, changed sources at reader join,
  active dispatch, drain, retry exhaustion and restart owners.
- Preserve bounded skip telemetry over a 10,000-row synthetic catalog.
- Rerun existing 30/120-market scope resource gates (CPU <5s, peak <16 MiB,
  commit/loop p99 <50ms) and the full test suite, then review the actual diff,
  check documentation links/ignores and publish the scoped verified unit.

Focused verification: 23 launcher/composition tests, 35 admission tests, 11
candidate-discovery tests and six input-filter tests pass. Ten repeated full-graph
discovery cases (five accepted pairs, five unsupported-fee cases) pass in 30.389s.
An initial pre-fix full run reported two discovery timeouts; those exposed the
deferral issue above. Final full suite on the corrected source:
`python -B -m unittest discover -s tests -q` — **1,401 run, 1,400 passed,
one expected Windows symlink-privilege skip**, 216.316s.

Existing scope resource check: 30/120 markets, ten cycles each, commit p99
0.453/1.289ms, loop p99 15.111/14.924ms, peak 23,173/28,948 bytes; all declared
gates pass. CPU was below the Windows process timer's resolution, not literally
zero. Reader teardown, writer, metadata and venue latency are excluded.
The new skip-filter fixture processes 10,000 rows ten times using 0.078125 CPU
seconds, 41,036 peak bytes and at most 9.139ms per pass, retaining only 32 samples.
These are synthetic resource measurements, not live throughput claims.

372 relative links in changed documentation resolve. Actual source/test diff
review and whitespace checks pass. Credentials, local inputs and data remain
ignored and untracked. Publication is scoped to this verified unit under D-065;
the final session response records the resulting commit and remote parity.

## Operational limitation

The unchanged ignored input file contains one review. Thus software integration
does not by itself create a broad trading universe. Additional exact timing
reviews and actual exchange shards must be prepared before multi-market launch;
unsupported/unreviewed markets are skipped visibly. No hot reload, automatic
review renewal, universal timing inference, live venue acceptance or guaranteed
reward/profit is claimed. Live launch remains a separate operator action.

See [run guide](RUN_LIQUIDITY_BOT.md) for input format and saved-status fields.
