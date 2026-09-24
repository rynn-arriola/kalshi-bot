# Exact reconciliation of an already-closed settlement

## Incident

Generation 111 observed a post-boundary settlement for
`KXTRUEV-26SEP23-T1258.69` after the bot had already bought and sold the same
10 YES-equivalent contracts and returned to flat inventory. Durable fill
accounting had already booked the complete `-$1.8138` net result. The generic
settlement capture correctly retained the venue row, but the operational release
treated every settlement as requiring manual reconciliation. New entry and
refill therefore remained blocked with 28 existing resting orders.

## Implemented rule

Settlement capture and conflict detection remain unchanged. Operational release
may clear only `settlement_reconciliation_required` when every current
post-boundary settlement is proved to describe fills already closed before
settlement:

- the market is binary, has zero settlement revenue, and its optional YES value
  agrees with the result;
- the current account snapshot has no position or resting order for the ticker;
- the ledger has no lot, position clock, nonzero venue-cost fallback, pending
  fill, or uncertain mutation for the ticker;
- every retained fill has exact bot-owned order evidence or one explicitly
  approved operator-close scope, a terminal order, primary-account/shard terms,
  and an execution time between the approved boundary and settlement;
- retained YES/NO quantities, costs and fees exactly equal the settlement row;
- every fill's realized event and matched-close evidence agree, all bought
  quantities are closed, and order fill totals agree with terminal order proof;
- the complete current settlement set exactly equals the normalized settlement
  rows retained in the accounting journal; omission or identity change blocks.

The release records settlement and fill digests in its durable proof. It does
not add settlement cash, revenue, fees or P&L; the fills remain the only economic
booking. Missing, open, scalar, conflicting, corrected, externally unproved or
otherwise mismatched evidence keeps the hold. `settlement_economics_conflict`
is never attributed or cleared by this path.

## Verification

- The focused account-release module passes 37 tests, including exact release,
  repeated identical reconciliation, mismatched settlement economics, unmatched
  settlement retention, changed settlement identity, restart validation, and no
  double booking.
- `scripts/Test-Bot.ps1 -Fast` passes 262 tests.
- The complete release suite passes 1,670 tests with one expected Windows
  symlink-privilege skip.
- A SQLite online backup of the running production ledger was inspected without
  venue access or source-database mutation. Its single settlement produced the
  exact closed proof with two retained fills.

This is an offline source repair. It does not hot-load the running child and did
not place, cancel, change, stop or restart any live order or process.
