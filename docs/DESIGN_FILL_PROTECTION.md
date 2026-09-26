# Fill protection — final design (proposed D-145)

Status: PROPOSED, 2026-09-26. Replaces nothing until the operator accepts it.
Evidence: Finding 206 (withdrawal outcomes vs public trades) and the generation
run `cce01ccf` (05:09–05:31 UTC, 46 entries × 30 contracts, 9,198 risk samples).

## 1. Problem

Entries earn liquidity rewards by resting at the reference price. The loss we
protect against is an **adverse fill**: the book is swept through our price and
the market keeps moving against the position (KXWMTCC 01:32: 0.90 ask swept,
then 0.97). Protection must (a) act before the sweep reaches us when it can be
seen coming, (b) cap the damage when it cannot, and (c) keep working when the
bot is slow, blind or offline.

## 2. What the data says

| Measurement (run `cce01ccf`) | Value | Meaning |
|---|---|---|
| Contracts ahead of our order (median / p10 / p1) | 313 / 200 / 125 | We sit well back; the danger is one large sweep, not a trickle |
| Samples with depletion rate = 0 | 98% | The time-to-fill trigger is dormant almost always |
| Rate 0 and ≤ 30 contracts ahead | 0.1% | Quiet-queue blind spot: real but rare |
| Time without a current risk reading | 27% (some markets 84–96%) | The 5 s freshness gate leaves orders unprotected |
| Cause of blind time | missing/expired queue reading ≫ book gaps | Fixable without more API reads |
| Cancel acknowledgement (median / p90 / max) | 0.48 / 0.96 / 1.51 s | Reaction path is fast enough |
| Threat trigger: estimated time-to-fill vs reaction window (medians) | 1.2 s vs 9.4 s | Fires early when it fires |
| Withdrawal outcomes (Finding 206) | 12 of 13 markets had no trades; 1 real sweep caught because makers pulled first | Book shrinkage is the useful early signal; trades alone come too late |

## 3. Final approach — four layers

### Layer 1 — Kalshi-side fill cap (order group) · NEW
Every **entry** order is created in the shard's current order group
(`order_group_id`). The group's `contracts_limit` is one entry's size (30).
When 30 contracts fill across the group within Kalshi's rolling 15 s window,
**Kalshi cancels every other entry in that group itself and blocks new ones**
until reset — no reaction latency, and it works while we are offline.

- One group per exchange shard used by entries; created at startup and
  persisted (id + state) in the ledger; exits/reducers are never in a group.
- `order_group_updates` (already subscribed) drives state: `triggered` →
  entries on that shard are blocked; the fills are processed by the normal
  recovery; affected markets get the D-135 lockout.
- Reset: automatically, only after a full recovery proves the account, every
  resulting position has its exit plan, and 60 s have passed. Every trigger
  and reset is journaled and visible in status.
- If the group cannot be created or its state is unknown, **no new entries**
  are placed on that shard (fail closed); creation retries on the D-141
  schedule (30 s, 1, 2, 5 min). Existing entries still expire (D-144 lease).

Why: the only layer that caps the damage of a sweep we cannot predict, a
correlated news move across many markets, or a bot/network outage.

### Layer 2 — Continuous queue tracking · UPGRADE (removes the 27% blind time)
Keep each order's last Kalshi queue reading as an **anchor** instead of
discarding it after 5 s. Between readings:

    ahead_now = max(0, anchor − Σ every book decrease at our price or better since the anchor)

counted **per delta message** as it arrives (a per-shard cumulative-decrease
counter), not from depth snapshots, so a cancel ahead followed by a join
behind is never netted away. Increases never raise the estimate; decreases
we caused ourselves (deltas carrying our `client_order_id`) are excluded.
The estimate is therefore always ≤ the true queue ahead (conservative).

- A fresh queue reading replaces the anchor (it is the truth).
- The anchor is valid while the book stream is continuous (same shard
  generation, no gap) and the order is unchanged; a book gap or reconnect
  requires a fresh reading, and until then the order is treated as unprotected
  → Layer 3's stale rule applies.
- The reaction window no longer grows with anchor age (the estimate already
  assumes the worst); it keeps the reading's own fetch latency.

### Layer 3 — Triggers · KEEP + TWO ADDITIONS
Withdraw the pair when **any** holds:
1. *Time-to-fill* (existing): `ahead ÷ depletion rate ≤ reaction window`,
   depletion measured from book shrinkage including cancels (it caught the
   one real sweep).
2. *Short queue* (new): `ahead < entry size` (30), regardless of rate.
3. *Blind* (new): no valid anchor for more than 10 s (book gap, missing
   reading) — treat as a threat rather than as safe.

### Layer 4 — Fast anchoring and exposure bounds · SMALL ADDITIONS
- Request a queue reading immediately after each entry acknowledgement, so a
  new order is anchored within ~1–2 s instead of waiting for the 4 s cycle.
- Keep: D-135 adaptive re-entry lockout, D-144 20-minute entry lease,
  Kalshi `cancel_order_on_pause`.

## 4. Options considered and rejected

| Option | Why not |
|---|---|
| Depletion from the public trade feed only | Would have missed the one real sweep: liquidity was pulled 6.6 s before any trade (Finding 206) |
| Poll queue positions faster (e.g. every 1 s) | Costs read budget and still leaves gaps; Layer 2 needs no extra reads |
| Account-wide cancel-all as the emergency tool | Also cancels exits and manual orders and blocks new orders for a minute |
| Quote one tick behind the reference | Lower reward weight on every order; a strategy change, not protection |
| Order-group limit of 1 contract | Any partial fill would pull all entries; 30 keeps it to "one order's worth" |
| Rely on the ETA model alone (status quo) | Blind 27% of the time; cannot cap a single sweep or offline damage |

## 5. Expected effect

- Unprotected time: ~27% → only book-stream gaps (brief; covered by the blind rule).
- Worst case from one sweep: one entry's fill (30 contracts), then Kalshi
  cancels the rest of the shard's entries — including while offline.
- Extra withdrawals: short-queue rule ≈ 0.1% of the time; blind rule only
  during book gaps; group triggers only on real fills (none in the last runs).
- Reward time lost after a trigger: roughly 1–2 minutes of the shard's
  entries per real fill.

## 6. Decisions for the operator

1. Group limit = 30 contracts (one entry), entries only, one group per shard.
2. Automatic reset after recovery + exits + 60 s (versus manual reset).
3. Fail closed (no entries) when a group cannot be created.
4. Short-queue floor = entry size (30); blind rule after 10 s.

## 7. Verification plan

Offline: per-delta accounting unit tests (cancel-ahead-then-join-behind,
own-order deltas, gaps), trigger tests for each rule, group lifecycle tests
(create, trigger, blocked entries, reset gating, fail-closed), mutation checks
for each guard, the real `LiveSession` path. Live: coverage (target ≥ 97% of
order-time protected), withdrawal counts vs baseline, group create/trigger
events, zero unexplained cancels of exits.
