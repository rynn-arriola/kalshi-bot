# Original liquidity runtime: minimal foreground operation

D-077 uses the existing runtime, not the retired REST-only canary. Native Windows
only, canonical checkout `C:/Users/rynna/Bots/kalshi`. No service, scheduled task,
automatic restart, model switch or worker is installed.

## Current state

Software integration exists; **no live trading launch is verified**. A complete
synthetic graph starts quota, readers, recovery, opening accounting, metadata,
selection, rewards and dispatch and receives one two-order ACK over a fake wire.
Partial fills and safety timers reach the existing exact reducers/IOC handlers.
Every live constructor uses an explicit session, not a fixture bypass.

Verification on 2026-09-22 includes the complete offline suite, focused launch
regressions and ten consecutive full-graph synthetic startup-to-ACK runs. These
checks do not submit venue orders:

- Full suite: 1,384 run in 208.482 seconds, 1,383 passed and one expected native
  symlink-privilege skip. No failures.
- Final launcher suite: all 18 tests passed, including the subsequent final
  status-save error regression. This targeted rerun covers that last change.
- Ten repeated complete compositions passed. All four PowerShell launch/status/
  diagnostic scripts parse; local CLI help runs; `git diff --check` and 364
  relative links in changed documentation pass. Private inputs/data remain ignored.

The read-only run `949542ffbfda4b0099e5085138f20282` finished at
14:39:44 UTC with `startup_verified=true`, `trading_ready=false` and
`process_stopped=true`. It connected the book shard, four private account
channels and lifecycle feed; obtained current account evidence, quota, metadata
and the reward catalog; then joined its readers. The catalog contained 4,717
rows covering 4,711 current markets, not 4,711 launch-eligible selections.
Its status and bounded logs remain ignored under `data/runtime-startup/`.

Current blockers are reviewed launch inputs and the first real opening baseline.
`config/live-inputs.local.json` is deliberately not fabricated from market expiry
or a balance format. No production `data/trader/account.db` has been initialized.

## Prepare the reviewed scope

The ignored input file contains exactly `timing_reviews`, `fee_profile` and
`exchange_indices`. Each timing row uses the existing `TimingReview` fields:
`ticker`, `event`, `milestone_id`, `milestone_type`, `rules_hash`,
`review_reference`, `valid_until`, `early_close_reviewed`. The fee profile uses
`balance_quantum`, `review_reference`, `valid_until`. Exchange indices include
0 for the unscoped batch bucket and every reviewed market's actual shard.

The rules digest is computed by `market_inputs.rules_digest` from the complete
current market document. Verify the event's primary milestone, rules, early-close
behavior and member precision; never substitute expiry for event-risk time or
silently default FCM membership. REST revalidates all those bindings at runtime.
Rank only within this reviewed initial scope; no sports-only filter or fixed
60-market universe is introduced. Broader automatic admission is deferred, not
silently allowed to subscribe unreviewed markets.

`python -B -m kalshi_bot.live check-inputs` validates the file locally; it does
not verify venue data or authorize orders. No new numeric profitability cutoff
is introduced. Existing conservative fee bounds and all approved risk settings
remain unchanged. Entry orders expire at the earlier of the selected program's
end and the existing event/market exit deadline; exact reducing IOC has no expiry.

## Commands

Commands below are for the human operator. The coding assistant must not invoke
the trading or order-canceling commands.

```powershell
# First live run only: explicit approval to establish a fresh flat opening.
.\scripts\Start-LiquidityBot.ps1 -Live -Initialize

# A later explicit run preserves the same baseline, ledger, fills and risk.
.\scripts\Start-LiquidityBot.ps1 -Live

# Local saved status; does not contact Kalshi or restart anything.
.\scripts\Get-LiquidityBotStatus.ps1

# Request drain, not a force-kill or a claim that the account is flat.
.\scripts\Stop-LiquidityBot.ps1
```

One account-scoped Windows lease prevents competing copies of this launcher.
`-Initialize` refuses an existing ledger. A failed initial approval cannot be
worked around by deleting that ledger; inspect the failure before recovery.
Never use a new data path to reset loss limits or ownership. Do not run the old
canary, another bot or manual account trades concurrently.

The stop request blocks new entries, cancels proven-owned entry orders through
the same writer/quota path, and continues the approved inventory exits until
flat/terminal evidence is current. It may remain `DRAINING` when an exit cannot
be made or proof is unavailable. It does not introduce unconditional liquidation.
An exception, network ambiguity, Ctrl+C, sleep or process death may leave orders
or inventory: `NEEDS_ATTENTION` is not canceled/flat. Do not force-close the window
as the normal stop method. Keep the laptop awake and online; no power settings
have been changed. Automatic supervisor recovery remains outside this release.
If source proof changes after durable SENDING, the existing conservative UNKNOWN
hold remains; this release does not introduce an automatic retry of that command.

## Data and debugging

Ignored local `data/trader/` holds `account.db` (single financial writer),
`account.rewards.json` (estimated reward checkpoint), atomic `status.json` and
rotating `logs/events.jsonl`. `RUNNING` means process activity, not that any
order exists; inspect resting entries, positions, account/dispatch blockers and
timestamps. Saved status is explicitly historical, not proof the PID is alive.
Actual fills/fees and receipt-window risk remain in the ledger. Estimated rewards
are not credited cash; no profitability claim precedes real payout reconciliation.

The separate bounded startup diagnostic is safe for the assistant to invoke:

```powershell
.\scripts\Test-RuntimeStartup.ps1 -Ticker '<current-market-ticker>' -Seconds 45
```

It uses the original read owners with a GET-only signer, cannot attach dispatch,
does not approve opening accounting, and writes a new diagnostic ledger under
ignored `data/runtime-startup/<run-id>/`. It joins readers and closes all owners
before returning. This is a startup check, not another paper/profitability trial.

## API verification

The current official V2 [create](https://docs.kalshi.com/api-reference/orders/create-order-v2.md),
[batch](https://docs.kalshi.com/api-reference/orders/batch-create-orders-v2.md)
and [cancel](https://docs.kalshi.com/api-reference/orders/cancel-order-v2.md)
contracts were retrieved on 2026-09-22. Payloads retain single-book bid/ask,
fixed-point count/prices, per-row batch outcomes and explicit shard routing.
Neither HTTP 201 nor a cancel ACK replaces subsequent fill/order reconciliation.
