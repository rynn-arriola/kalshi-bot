# D-101: actual-order repricing and final-drain recovery

September 23, 2026. Prepared in the isolated `fix/order-maintenance` checkout.
The operator requested fixes for the running bot's reference positioning and
related retained-log defects, then explicitly ordered stop/cancellation. No
subsequent live start is authorized. STATUS owns current process/deployment state.

## Evidence and scope

Generation 66 held 29 orders after its single maintenance cancellation at
15:30:17 UTC. The independent public census at 16:23:56–16:25:39 examined 1,024
reviewed markets: 181 passed $1 and 20 passed $2. Four of 15 incumbent markets
were $2-priority; only three appeared in the sampled top 15. This does not itself
justify rotating qualifying incumbents: D-098 explicitly retains them.

Public sampled references versus actual ledger quotes (YES-book cents):

| Market | Side | Resting | Sample reference |
|---|---|---:|---:|
| KXTOKENUSE-26SEP28-T132 | bid | 67 | 83 |
| KXTOKENUSE-26SEP28-T138 | bid | 34 | 40 |
| KXSPRITEPOS-26OCT03-T91 | ask | 92 | 91 |
| KXSPRITEPOS-26OCT03-T92 | ask | 97 | 86 |

The other 25 orders were at/better than the sampled reference. All 15 markets
passed using hypothetical reference pairs, not necessarily their actual quotes.
The public census is sequential, includes unidentified own aggregate liquidity,
and uses hypothetical flat capital. It cannot establish exact owner-adjusted
score, a simultaneously executable top portfolio or paid rewards. Its ignored
artifact is `data/market-gate-census/5271e4ca0c9841ce9d0b6fb1518f778a/result.json`.

## Reproduced defects and repair

1. Queue reflection could complete while management plans were dirty and publish
   no proof for those owners. Queue evidence now binds to the already validated
   complete account snapshot. Consumption still requires exact fresh owned-order
   signatures, current account generation/revision/report, book and reward terms.
2. A transient market-plan gap, including a progress/status read, deleted the
   otherwise current queue identity. Only the sampled rate is now invalidated
   during that gap. The original lease never extends; account changes, explicit
   epoch invalidation and expiry still revoke evidence. Unknown time is not earned.
3. Account publication races during an awaited queue read are superseded reads,
   not malformed venue replies. They remain fail-closed and have their own status
   counter. True reflection failures now emit stack-only diagnostics on failure
   counts 1, 2, 4, 8, etc.; no response bodies or exception text are logged.
4. Rapid paused cancellation could exhaust an overlapping recovery pass and
   never request another after the final outcome. Each new durable cancel outcome
   sets one coalesced pending flag. Once dispatch and active recovery are idle,
   the existing refresh owner requests one bounded reconciliation. No new outcome
   means no additional attempt; ACK is never treated as terminal/no-fill proof.

The existing maintenance cycle passes a sequential first-cancel / delayed
terminal receipt / second-cancel / delayed terminal receipt / fresh-reference
pair regression. No cancel-proof shortcut or price-chasing policy was added.
$2-first/$1-fallback, 70% retained value, size 10, cap 30 and incumbent retention
remain unchanged. There are no new venue endpoints, workers or schedulers;
post-drain reconciliation reuses the existing bounded account-read owner.

## Retained-log and ledger audit

All retained production child and parent JSONL rotations were parsed. At stop,
child records covered **16:32:57–16:36:10 UTC**, 2,039 records: 2,035 INFO,
three recovery-incomplete warnings and one recovery-exhausted error during the
drain. Rotation prevents reconstructing the entire 73-minute run from these
files; absence of retained errors is not proof of no historical error.

The parent log held 136 records from September 22 through this launch. Its two
errors concern an old September 22 native-control security failure, not the
current run. Last runtime logging showed zero drops and no sink/engine/book
failure. Durable generation-66 evidence contained 30 acknowledged creates,
20 proven-unsent creates, 30 acknowledged cancels (one maintenance plus 29 stop),
zero new fills, zero pending fills and 931 hot history receipts. No current-run
unknown or rejected mutation was found. Proven-unsent source races are not venue
orders and do not justify weakening send-edge checks.

The stop's 29 cancel preparations span 16:34:03.847–16:34:12.249 UTC. Complete
GET-only venue enumeration verified no resting orders or nonzero positions at
16:35:52.161 UTC, before exact-process termination. The financial ledger and
supervisor journal were not manually rewritten or reset.

## Verification and review

Focused reward tests: 55 passed; maintenance: 28 passed; dispatch sources: 34
passed. Three in-memory baseline reversals independently caused the intended
assertion failure (queue publication, proof retention, final-drain wake), with
no fixture error. Production queue-proof tests do not use the fixture reflection
bypass; quantity changes, account revocation and original lease expiry remain
negative controls. Complete offline suite: **1,620 run, 1,619 passed and one
expected Windows privilege skip**, 276.362 seconds, no failures. Changed-document
relative links: 421 checked, none missing; `git diff --check` passed.

The exact source/test diff was reviewed in the primary session for stale proof
reuse, changed ownership, lease renewal, account/recovery races, shutdown retry
loops and logging disclosure. No known blocking implementation issue remains.
The pending post-drain flag is consumed only after dispatch and current repair
are idle, and cannot create repeated attempts without a new durable outcome.
The reviewed change does not claim our protected incumbents always form the
globally highest-paying portfolio.

Live acceptance remains pending a separately authorized deployment/restart.
Neither these offline tests nor the public census proves reward payout or profit.

Reviewed implementation `44986ee` was pushed to `origin/master` and exact remote
parity verified. Canonical `dbbc4dd` remains clean and stopped; publication did
not deploy code, alter the production ledger or restart trading.
