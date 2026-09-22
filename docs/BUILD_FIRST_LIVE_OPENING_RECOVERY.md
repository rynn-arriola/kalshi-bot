# D-084 — First-live opening attribution and recovery

September 22, 2026. This correction was triggered by the first explicitly
authorized supervised live initialization.

## Observed failure

The production supervisor created one account ledger and connected the account,
book, lifecycle and quota owners. The current account snapshot was flat: zero
resting entries, zero positions and zero exposure. Opening approval then failed
closed. The ledger retained an earlier applied $500 personal deposit and a
completed $0.4417 intra-exchange transfer; both predated the chosen boundary,
but the venue documents carried no completion timestamp. The only durable holds
were `opening_proof_unresolved` and `cash_activity_unattributed`.

No create/cancel mutation was dispatched. The supervisor used its bounded
restart budget and entered `attention_required`; no live child remained.

## Correction

Opening approval now has one narrow personal-account attribution path. It:

- requires the exact immutable checkpoint and a fresh current inspection;
- requires unchanged account scope, source cardinality and economic cash;
- accepts only applied deposits and completed intra-exchange transfers created
  before the opening boundary;
- records each accepted accounting-event digest in the opening approval;
- rejects pending/failed/returned funding, withdrawals, subaccount transfers,
  post-boundary activity, settlements, changed cash and all other economic
  holds.

Kalshi may advance the balance observation timestamp without changing cash, so
resume permits that clock to move forward while requiring every economic cash
field to match.

The supervised initialize profile also distinguishes first creation from
interrupted approval. If the ledger already has the unapproved checkpoint, a
new explicitly armed child obtains a fresh inspection and may approve that same
checkpoint. It cannot replay initialization, change the boundary, delete state
or silently treat a normal restart as opening authority.

The first re-arm after that correction was refused before child creation by the
Windows control-file guard. SQLite's prior clean close had recreated WAL/SHM
sidecars with the protected directory's exact user/System full-control grants,
but Windows marked those grants inherited instead of explicitly protected. The
guard now permits either exact representation for SQLite sidecars only. The
control root and database still require their explicit protected DACLs, and any
extra sidecar principal/permission remains invalid. No ACL is repaired or
broadened by this compatibility rule. The current native/focused supervisor
set passed 61 tests with one expected privilege skip. The complete suite after
this correction ran 1,445 tests in 218.331 seconds: 1,444 passed and one
expected skip.

Generation 3 subsequently resumed the exact checkpoint and installed the
baseline, recording both attributed cash-event digests. It remained flat with
zero orders/exposure and disarmed. That run exposed a final ordering race:
approval queues a second recovery pass for the new writer revision, while the
terminal-flat fence was allowed to stop between passes. The retained account
inspection was then cancelled and correctly persisted
`accounting_source_failed`. Terminal flatness now requires the recovery lock to
be idle and no recovery request queued. Hold removal remains solely inside the
fresh operational-release transaction; no runtime path deletes a hold directly.
The focused live/account/supervisor set passed 75 tests, and the complete suite
then ran 1,446 tests in 219.163 seconds: 1,445 passed and one expected Windows
privilege skip.

Generation 4 exposed two follow-on mismatches in the operational release. The
venue returned the same available cash on its sequential balance reads while
advancing `updated_ts` by one second, and each complete cash-history scan again
returned the two events already attributed by the opening baseline. Release now
accepts a forward-only balance timestamp only when available cash is unchanged.
It also treats prior cash activity as attributed only when the current API set,
the retained journal set and the baseline's approved `(kind, digest)` set are
all exact and non-empty. New, missing, changed, post-boundary or subaccount cash
activity continues to install a durable hold. This exact match can clear the
legacy stale hold only inside the ordinary operational-release transaction.
Focused opening/accounting/release verification passes 81 tests.

## Verification

Focused accounting/account-release/supervisor tests: 68 passed. The supported
recovery-runtime and complete live-runtime discovery runs: 70 passed. The full
offline suite ran 1,444 tests in 220.622 seconds: 1,443 passed and one expected
Windows privilege skip. The account-release 30/120-market benchmark passed on
its verification rerun; all four latency/memory cases passed and the two
large/small-history median ratios were 1.8520 and 0.9250. An immediately prior
run measured one ratio at 2.0006 against the strict 2.0 cutoff while all direct
budgets passed, so that isolated 0.03% overage is retained as measurement noise,
not hidden. `git diff --check` passes. Corrected relaunch evidence is added after
the supervised acceptance run.
