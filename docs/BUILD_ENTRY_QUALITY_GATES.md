# D-083: entry-quality and projected-reward gates

## Accepted entry contract

The existing WebSocket-driven selector remains the only ranking path. For each
fresh candidate book, a new two-sided size-10 pair is admissible only when:

- both orders are exactly at the current program reference prices and receive
  full price weight;
- each side retains at least 70% of its entry value if immediately crossed
  through all currently visible depth, including the reviewed taker-fee bound;
- projected gross reward through the earlier program end or approved entry
  deadline is at least $1.

Candidates at $2 or more projected remaining reward are considered before the
$1–<$2 fallback. Existing gross hourly reward, capital efficiency and stable
identity ordering are preserved inside each tier. Below-$1 candidates never
consume an entry slot. The 30-resting-entry limit still permits at most 15 new
two-order markets when no slots are already occupied.

The projection uses the current reward program, current WebSocket book and
unchanged-book competition arithmetic. It is neither an accrued-reward value nor
a guarantee of the venue's $1 payout minimum. Competition, eligibility, book
prices, fills and available earning time can change after entry.

## Implementation and failure behavior

`MarketSelector.update` reuses the existing exact `cross` calculation for each
side. Missing visible exit depth blocks the row. A complete result computes
`(entry value + projected exit P&L) / entry value`; either side below 0.70 adds
`entry_retained_value_below_minimum`. The diagnostic ratios remain bounded with
the selector's per-program state and are cleared on invalidation.

`MarketSelector.propose` rechecks the exact hypothetical reference pair, both
full-weight statuses and the dynamically decayed remaining reward. It emits
`initial_quote_not_at_full_weight_reference` or
`projected_reward_below_minimum` when those gates fail. A stable tiering pass
puts viable $2+ rows before viable fallback rows. The existing runtime refreshes
from the latest joined book before proposal, and dispatch retains its source,
book, metadata, account and writer-revision checks after awaits.

This changes new-entry selection only. It does not cancel or reprice incumbents,
alter inventory reducers, infer paid reward, modify loss/capital/position limits,
or authorize live trading.

## Evidence and verification

A credential-free public snapshot before implementation joined 4,919 active
incentive rows to the 1,024 reviewed candidates. Of 992 books with valid
two-sided scoring pairs, 596 passed the 70% per-side gate, 218 also projected at
least $1, and 50 projected at least $2. The 50 priority plus 168 fallback-only
candidates exceeded the current 15-market maximum. This was a sequential public
snapshot, not simultaneous market state or profitability evidence.

Synthetic tests cover the 70% per-side calculation, the hard $1 rejection, the
$2-first tier overriding a higher hourly-rate fallback, exact full-weight
reference enforcement, dynamic deadline decay, cache invalidation and the
actual discovery/admission/live-dispatch graph. No credential, production
ledger, venue mutation or live bot was used.

Final offline suite: 1,434 tests in 215.907 seconds, with 1,433 passed and one
expected Windows symlink-privilege skip. The 30/120-market selection benchmark
passed: update p99 2.329/2.648ms, loop p99 13.717/33.581ms, CPU
0.5312/2.0156 seconds and traced peak 445,639/517,246 bytes. The matching
admission benchmark also passed. These are same-laptop synthetic measurements,
not live latency evidence.
