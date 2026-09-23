# Public market-gate census — 2026-09-23

MEASURED using `scripts/check_live_market_gates.py` against runtime source
`8adea24`. Explicit invocation: `.venv/Scripts/python.exe -B
scripts/check_live_market_gates.py --read-only-live-check --source-root
C:\Users\rynna\Bots\kalshi --markets 1024`.

Local ignored artifact:
`data/market-gate-census/def120c98c874200b8301dd4581ad5f6/result.json`.
Observation: 04:00:13.735989–04:07:09.055571 UTC, 415.320 seconds.

| Sequentially observed scope | Examined | Passed $1 minimum | Of those, $2 priority |
|---|---:|---:|---:|
| Saved initial seed, still current | 127 | 15 | 4 |
| Outside saved seed | 886 | 141 | 28 |
| Total | 1,013 | 156 | 32 |

The other 124 passing markets were $1–under-$2 fallback candidates. Thresholds
refer to projected remaining-program gross rewards, not hourly income, paid
rewards or guaranteed earnings. Catalog enumeration found 4,545 supported active
reward markets; only 1,013 of the 1,024 saved reviews were current and rewarded.
This is not an economic census of all 4,545 markets.

Exclusions (overlap, not additive): retained value below minimum 394; projected
reward below minimum 429; insufficient two-sided depth 28; entry horizon ended
25; ranking evidence expired 25. No book-missing/stale or metadata/source error
was recorded. Public REST: 2,563 calls, 22,047,197 response bytes.

## Method and limits

The diagnostic uses fresh public reward/metadata REST, actual public WebSocket
books/lifecycle and the real metadata service and selector. Two metadata workers
evaluate batches of at most 128 books; each batch constructs a new metadata
service. Books are collected concurrently; economic evaluations are not an
instantaneous whole-universe snapshot. Public REST is allowlisted, rate/budget
bounded and stops after refusal. WebSocket authentication uses existing local
credentials without logging them. No private REST, ledger, trader, order command
or production configuration write is performed.

An explicitly hypothetical empty $500 account isolates market gates. Actual
account admission, simultaneous capacity, production rotating-admission timing,
fills, payment and profitability are NOT assessed. This does not establish the
exact historical 28-order blocker or prove 30 orders can be placed now.

## Why discovery remains slow

VERIFIED CODE: live discovery has 128 active book slots and admits at most 16
replacements per scope change. D-091 fixes skipped candidates, not these limits.
Its 30-second post-change dwell gives 56 dwell intervals (about 28 minutes) for
896 additional candidates after an initial 128 in the favorable frozen fixture;
actual source/ownership delays can add time. These are our software settings,
not an established Kalshi maximum.

The independent census took 6m55s and does not exercise that rotation timer.
Its two-worker cold metadata path and sequential batches constrain throughput;
per-endpoint latency/cache contribution was not profiled. Do not present the
census duration as live refresh latency. The first batch's observation span was
117.498s; batches two through five spanned 47.195, 34.993, 34.276 and 40.395s.

Recommendation, not approved implementation: decouple bounded discovery book
collection from order-management subscriptions, share reviewed metadata caches,
and rank fresh candidates before handing the best to execution. Preserve 30
resting orders and current reward/risk gates. Validate time-to-first-qualified
slate, whole reviewed-universe coverage, freshness and account-path latency under
load before claiming improvement. Do not simply raise subscriptions blindly.

## Verification

Five new synthetic census tests plus existing reward-source/selection tests:
58 passed. Tests use mocked responses; the separately explicit live census above
completed with `OBSERVED`, 1,013 distinct rows and exit zero. No runtime logic was
changed for this instrument. D-091's prior full-suite result belongs to that
runtime commit, not a new full-suite run here. Bot remains stopped; manual-order
cancellation/account reconciliation and host continuity remain separate work.
