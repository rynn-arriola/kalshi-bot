# D-079 — Automatic rewarded-market preparation

## Outcome

The launcher is no longer restricted to one manually listed ticker. A bounded,
public-only preparation owner enumerates current active liquidity programs,
fetches only their exact market definitions, and joins each event to exactly
one future official primary milestone. It rejects missing/ambiguous milestone
bindings, unsupported market/program forms, inactive markets and account-capped
programs. Complete current rules produce the same digest revalidated later by
the existing metadata owner.

Candidate authority, WebSocket subscriptions and resting orders remain separate:

- at most 1,024 exact candidate bindings;
- at most 128 initial/active market books;
- the unchanged maximum of 30 resting entry orders.

Pool/time/target is only a cheap discovery ordering. Preparation keeps a
30-market rewarded head and a stratified, event-diverse tail so the known weak
proxy does not become a profitability filter. The existing WebSocket selection
owner remains final: it computes actual current competition, gross hourly reward
and capital efficiency from fresh books before account/risk/dispatch gates.
Admission retains owners and rotates only flat, clear subscription scope.

The operator accepted automatic primary-milestone preparation to remove the
one-market bottleneck. Milestone uniqueness is established before applying the
T-5 entry buffer, so an imminent binding cannot be discarded in favor of a
later one. Automatic preparation excludes `can_close_early` markets because a
rules digest proves identity, not the meaning of natural-language early-close
conditions. Separately reviewed launch inputs retain the existing explicit
early-close path. Current rules, lifecycle, active state and milestone binding
are rechecked at runtime; any conflict blocks entry. This is not a claim that a
reward will be paid or that a market is profitable.

## Operation and safety

`python -B -m kalshi_bot.live refresh-candidates` refreshes the ignored local
input while no ledger exists or saved shutdown is verified flat. The first
explicit `run --live --initialize` performs the same public preparation before
loading credentials, creating a live session or constructing order transport.
An existing non-flat/uncertain ledger blocks explicit refresh. The original
one-market input is backed up once under ignored `backups/`.

The broad scope is bounded independently from the 128-book engineering capacity.
On restart, durable positions, active-order exposure and pending-fill owners
take subscription priority; optional discovery seeds fill only the remaining
capacity. Uncertain account state still blocks entry, but no longer expands one
known owner into the whole 1,024-market candidate universe. Restart fails closed
if actual protected owners cannot fit. This change does not invent recovery
authority, hot-reload candidates, start a service, or loosen capital, size,
position, loss, fee or shutdown limits.

## Evidence

The final credential-free real refresh on 2026-09-22 returned 4,759 active incentive
rows and 4,753 matching market rows, inspected 3,228 future milestones, prepared
1,024 bounded candidates and 128 initial WebSocket markets, and reported 1,874
missing plus 38 ambiguous future-primary bindings. The resulting ignored input
parses successfully. No account key, bot process or mutation endpoint was used.

Synthetic tests cover exact binding, event-diverse selection, unsupported,
early-close, imminent and ambiguous exclusions, duplicate identities, public
endpoint scope, candidate authority above subscription capacity, launch-event
logging, rotated-owner restart and legacy automatic-input rejection. Final
suite: `python -B -m unittest discover -s tests -q` — **1,412 run, 1,411 passed
and one expected Windows privilege skip** in 215.358 seconds.

Existing resource gates remain green. Reward tracking at 30/120 markets used
0.3594/1.4531 CPU seconds with update p99 2.230/2.205 ms and loop p99
5.581/5.650 ms. Ten-cycle admission at 30/120 markets used 23,173/28,900 peak
bytes with scope-commit p99 0.494/1.569 ms and loop p99 15.250/15.113 ms.
The 10,000-program to 128-candidate discovery pass took 20.872 ms. These are
synthetic CPU/memory checks, not venue-latency or profitability evidence.
