# D-076 minimal live profitability canary

Implemented on native Windows in `C:/Users/rynna/Bots/kalshi`. This is a narrow
experiment path, not activation of the autonomous multi-market runtime.

## Scope

`scripts/live_canary.py prepare` performs authenticated GETs only. It requires a
flat primary account, enumerates active liquidity programs, checks current market
rules and fixed-point books, and chooses one market that can estimate at least
the program's $1 minimum during at most six hours. The prepared plan expires in
45 seconds and records exact ticker, rules digest, program, exchange route,
prices, two client IDs, quantity, expiry and maximum exposure.

`run` requires the exact prepared run ID. It rechecks the flat account, active
program, rules and quote prices before consuming a single-use capability bound
to the complete request digest. It can submit only one V2 batch containing one
post-only 10-contract bid and one post-only 10-contract ask. Orders request
cancel-on-pause and server-side expiry. The monitor polls only the owned ticker,
cancels acknowledged orders on the first observed fill or planned end, and
writes atomic ignored run status under `data/live-canary/`.

This canary does not market-take, reprice, rotate, submit a second entry batch,
or activate the production supervisor. A fill may leave at most ten contracts
to settle; the status reports that inventory rather than calling it complete.
Estimated reward is not paid reward or profit. Final economics require fills,
fees, settlement/trading P&L and later reward-credit reconciliation.

## Verified before live authorization

- Fresh read-only account evidence: $500.4268 cash, zero positions and zero
  resting orders.
- Fresh preview selected a same-day gas-price market with YES $0.71 / NO $0.25,
  $9.60 maximum combined entry cost, $7.10 maximum one-sided loss and $1.49
  estimated six-hour reward. The preview expired and no order was submitted.
- `python -B -m unittest discover -s tests -v`: 1,367 tests passed with one
  expected Windows symlink-privilege skip in 199.687 seconds.
- The live-canary tests cover REST NO-to-YES conversion, price/risk guards,
  plan integrity/expiry, exact request construction and one-use activation.

## Remaining authorization

No order or cancellation has occurred. A fresh plan and an explicit operator
instruction to submit this bounded canary are required. The account must still
be flat at the send edge. Any stale quote, changed rules, active order, position,
unknown response or failed reconciliation blocks rather than retries.
