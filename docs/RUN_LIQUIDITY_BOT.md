# Supervised liquidity runtime: Windows operation

D-081 places the D-077 runtime behind the native Windows process supervisor.
Native Windows only, canonical checkout `C:/Users/rynna/Bots/kalshi`. The
supervisor now uses D-094's [independent on-demand host](BUILD_HOST_CONTINUITY.md).
No service, scheduled task or startup entry is installed. `-Foreground` retains
terminal-bound diagnostic operation; keep that terminal open when using it.

## Current state

The next authorized normal launch uses D-093's
[broad reviewed discovery](BUILD_BROAD_DISCOVERY.md), not the historical 128-book
rotation described below. Recovery-only remains narrow. The same launch commands,
reviewed inputs and trading limits apply; no automatic deployment/restart occurs.

Current operational evidence is owned by [STATUS](../STATUS.md), not the dated
prelaunch checks below. On 2026-09-22 the operator-authorized live run placed
orders; D-085 recovery later reached STOPPED_FLAT, and an authorized normal
restart completed a live admission rotation. Recheck current local status and
process identity before any operation. This does not grant standing launch
authority or establish profitability, fill/exit acceptance or reboot recovery.

## Historical prelaunch verification

The seven [end-to-end supervisor findings](REVIEW_D081_END_TO_END.md) are repaired
and verified offline. The commands below remain an operation reference, not live
acceptance evidence or independent authority to trade. First supervised live
acceptance is still unverified and requires explicit operator launch authority.

Software integration exists; **no supervised live trading launch is verified**. A complete
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

The ignored launch-input file now contains the bounded D-082 public preparation:
1,024 exact candidate bindings and 128 initial WebSocket markets. The refresh
selected only current active reward programs and the reviewed scheduled-release
timing family; 1,505 other early-close rules remain blocked. Runtime incentive
refresh and fresh WebSocket-book ranking still determine which candidates are
currently reward-eligible and worth admitting. The remaining live step is the
first real opening baseline, captured only by an explicit operator `-Initialize`
start. No production `data/trader/account.db` has been initialized.

A 45-second read-only startup check used the first current seed,
`KXDIESELD-26SEP23-T6.580`, and returned `startup_verified=true` with book,
account and lifecycle readers joined plus a current reward catalog. It remained
`trading_ready=false` because the diagnostic deliberately does not approve an
opening baseline or load launch timing/fee inputs. It stopped cleanly and did
not create a production ledger or order. This is connectivity evidence, not a
reward or profitability estimate.

## Prepare the reviewed scope

The first `-Initialize` launch automatically refreshes candidates from public
incentive, market and milestone endpoints before loading credentials or creating
trading authority. An operator may run the same safe preparation separately:

```powershell
.\.venv\Scripts\python.exe -B -m kalshi_bot.live refresh-candidates
```

It refuses to replace scope over an existing ledger unless saved shutdown is
`STOPPED_FLAT`. The previous local file is backed up once under ignored
`backups/`. Public preparation is not an account read or order command.

The ignored input file requires `timing_reviews`, `fee_profile` and
`exchange_indices`; optional `initial_tickers` selects a nonempty reviewed
subscription seed subset. Omit it to seed every supplied review, as before.
Each timing row uses the existing `TimingReview` fields:
`ticker`, `event`, `milestone_id`, `milestone_type`, `rules_hash`,
`review_reference`, `valid_until`, `early_close_reviewed`. The fee profile uses
`balance_quantum`, `review_reference`, `valid_until`. Exchange indices include
0 for the unscoped batch bucket and every reviewed market's actual shard.

The rules digest is computed by `market_inputs.rules_digest` from the complete
current market document. Verify the event's primary milestone, rules, early-close
behavior and member precision; never substitute expiry for event-risk time or
silently default FCM membership. REST revalidates all those bindings at runtime.
Under D-079 the timing rows define the reviewed candidate universe (at most 1,024),
not a desired market count. The actual launcher attaches automatic admission:
active reward discovery filters this universe, replaces only flat/clear book
scope, resolves metadata on the existing shared reads and ranks fresh books.
New entries must satisfy D-083's exact full-weight reference pair, 70% per-side
retained-value and $1 projected-remaining-reward gates. $2+ candidates are
offered slots before the $1–<$2 fallback. No sports-only filter, fixed 60-market
pool or reward-chasing cancellation is introduced. Reviews survive subscription retirement; explicitly revoked reviews
are not restored. On restart, durable exposure owners are added to the seed set; unresolved
ownership retains the full reviewed universe for recovery, not entry permission.

Preparation requires exactly one future primary milestone and complete supported
rules. For automatic early-close review, only D-082's exact scheduled-release
condition/types and a nonconflicting occurrence timestamp are supported. Missing
or ambiguous bindings and all other early-close families are excluded; expiry
never substitutes for event start. It retains a rewarded head plus stratified tail, while fresh
WebSocket competition supplies final ranking. There is no hot reload during a
run. See [preparation](BUILD_AUTOMATIC_CANDIDATES.md) and
[integration](BUILD_LIVE_SELECTION.md).

Saved runtime status includes `admission` and
`selection.candidate_inputs`: timestamped skip counts and at most 32 ticker/reason
samples (missing/expired timing, fees, unsupported shard, deadline or exhausted
metadata). These are last-pass diagnostics, not fresh eligibility or payout proof.

`python -B -m kalshi_bot.live check-inputs` validates the file locally; it does
not verify venue data or authorize orders. No new numeric profitability cutoff
is introduced. Existing conservative fee bounds and all approved risk settings
remain unchanged. Entry orders expire at the earlier of the selected program's
end and the existing event/market exit deadline; exact reducing IOC has no expiry.

## Commands

Commands below require explicit operator authorization. A coding assistant may
carry out the exact approved operation; documentation or a successful software
test is not independent permission to trade, cancel, stop or restart.

```powershell
# First live run only: explicit approval to establish a fresh flat opening.
.\scripts\Start-LiquidityBot.ps1 -Live -Initialize

# A later explicit run preserves the same baseline, ledger, fills and risk.
.\scripts\Start-LiquidityBot.ps1 -Live

# Local process presence plus historical status; no Kalshi calls or restart.
.\scripts\Get-LiquidityBotStatus.ps1

# Request drain, not a force-kill or a claim that the account is flat.
.\scripts\Stop-LiquidityBot.ps1

# D-116, explicit "command 1": cancel, immediate reducing exits, verified flat,
# then normal restart. Accepts resulting execution P&L and fees.
.\scripts\Restart-LiquidityBot.ps1 -Flatten -Live
```

Command 1 uses the existing live owner, not a second order writer. Its request
is bound to the exact child/generation and cannot liquidate a later run. It
requires a current emergency-capable child; old/stopped/unknown owners report a
blocker without an ad hoc close. The normal stop/start commands remain available
for separately supervised recovery. Default flatten/readiness bounds are 180/300
seconds, configurable up to 900 each. Timeout leaves the actual state visible;
it never force-kills, assumes flat, or launches a duplicate automatically.
`data/trader/supervisor/command1-status.json` holds the last operation and stage;
read it and ordinary status before retrying an interrupted command. COMPLETE
requires old-owner terminal flat proof, exit, and a fresh ready normal child.
Thin or unavailable books can block liquidation; immediate does not guarantee a
fill or bounded loss. No foreign ownership or another subaccount is included.

The account-scoped Windows leases prevent competing supervisor/runtime owners.
`HOST_STARTED` is only a startup acknowledgment; inspect current status and
readiness afterward. A timed-out acknowledgment is unknown, not permission to
launch another copy. See [host semantics](BUILD_HOST_CONTINUITY.md).
`-Initialize` creates a ledger only when none exists. Under D-084, its explicit
supervised profile may resume an existing unapproved checkpoint only after a
fresh matching inspection; it never recreates the ledger or opening boundary.
A failed initial approval cannot be worked around by deleting that ledger;
inspect the failure before recovery.
Never use a new data path to reset loss limits or ownership. Do not run the old
canary, another bot or manual account trades concurrently.

The stop request is now durable in the separate supervisor control journal. It
blocks new entries, cancels proven-owned entry orders through
the same writer/quota path, and continues the approved inventory exits until
flat/terminal evidence is current. It may remain `DRAINING` when an exit cannot
be made or proof is unavailable. It does not introduce unconditional liquidation.
An exception, network ambiguity, Ctrl+C, sleep or process death may leave orders
or inventory: `NEEDS_ATTENTION` is not canceled/flat. Do not force-close the window
as the normal stop method. Keep the laptop awake and online; no power settings
have been changed.

The durable $25 settled-loss hold uses the same drain behavior: it revokes new
entry/admission authority, reports `DRAINING`, cancels exact proven-owned entry
orders even when price/market terms are stale, and leaves open inventory to the
existing approved reducer/IOC policy. It does not force liquidation, loosen
ownership proof or reset automatically on process restart. Lower loss-tier caps
continue to restrict new admission without a newly introduced rotation policy.

An unexpected child exit receives at most the supervisor's bounded retry budget.
Its first replacement child is recovery-only: entries are paused before
composition, the same financial ledger is opened, and only reconciliation,
owned-order cancellation and existing-inventory reduction are permitted. If that
child proves flat with no hold, the still-armed supervisor launches one fresh
normal child, which re-ranks and passes every ordinary entry gate before quoting.
A manual stop still disarms after verified-flat cleanup and never auto-restarts.
Startup refusal, unknown/integrity state, local-control failure or exhausted
retry budget requires attention. Parent loss is not reboot recovery; the optional
host watchdog remains uninstalled and separately authorized. See the
[production recovery contract](DESIGN_PRODUCTION_SUPERVISOR.md).
If source proof changes after durable SENDING, the existing conservative UNKNOWN
hold remains; this release does not introduce an automatic retry of that command.

## Data and debugging

Ignored local `data/trader/` holds `account.db` (single financial writer),
`account.rewards.json` (estimated reward checkpoint), atomic `status.json` and
rotating `logs/events.jsonl` (routine telemetry in `telemetry.jsonl`, D-149). `data/trader/supervisor/` holds the separate
protected control journal and bounded parent/child diagnostics. `RUNNING` means process activity, not that any
order exists; inspect resting entries, positions, account/dispatch blockers and
timestamps. Saved status is explicitly historical, not proof the PID is alive.
Actual fills/fees and receipt-window risk remain in the ledger. Estimated rewards
are not credited cash; no profitability claim precedes real payout reconciliation.
Repository status commands use Windows delete-sharing reads; atomic publication
has bounded transient-contention retry and still fails closed on permanent I/O
errors. See [D-097](BUILD_STATUS_PUBLICATION.md).

The separate bounded startup diagnostic is safe for the assistant to invoke:

```powershell
.\scripts\Test-RuntimeStartup.ps1 -Ticker '<current-market-ticker>' -Seconds 45
```

It uses the original read owners with a GET-only signer, cannot attach dispatch,
does not approve opening accounting, and writes a new diagnostic ledger under
ignored `data/runtime-startup/<run-id>/`. It joins readers and closes all owners
before returning. This is a startup check, not another paper/profitability trial.

The final exact-ticker diagnostic run was
`2a6947d80694482590709bafd3805a86`: `startup_verified=true`, current account and
book evidence were present, all three reader owners subscribed, the catalog held
4,677 rows / 4,671 current markets, and the process stopped cleanly. Its expected
`timing_review_missing`/`fee_profile_missing` labels reflect that the generic
diagnostic intentionally does not load launch inputs. A separate real metadata
adapter check did load the ignored inputs and returned no blockers.

## API verification

The current official V2 [create](https://docs.kalshi.com/api-reference/orders/create-order-v2.md),
[batch](https://docs.kalshi.com/api-reference/orders/batch-create-orders-v2.md)
and [cancel](https://docs.kalshi.com/api-reference/orders/cancel-order-v2.md)
contracts were retrieved on 2026-09-22. Payloads retain single-book bid/ask,
fixed-point count/prices, per-row batch outcomes and explicit shard routing.
Neither HTTP 201 nor a cancel ACK replaces subsequent fill/order reconciliation.


## Automatic restart after reboot or power loss (D-144)

Install once (it changes a Windows setting, so run it yourself):

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Install-LiquidityBotAutostart.ps1

Two minutes after you sign in, `scripts\Start-LiquidityBotOnBoot.ps1` waits for the
network and runs `python -m kalshi_bot.supervised_live boot --live`, which starts
the bot only if it was running before (never after a manual stop or an
attention state). Results are appended to `data\trader\autostart.log`.
Remove with `-Remove`. For unattended recovery after a power cut the PC must
sign in by itself and must not sleep on AC power.
