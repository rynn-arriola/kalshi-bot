# Reward API re-audit — September 22, 2026 Eastern

Follow-up: D-086 [implements the two source repairs](BUILD_REWARD_SOURCE_REFRESH.md)
in isolation. This document retains the original audit-time observations below.

Research only. No live configuration, order, ledger, key, process or retry hold
was changed. This supplements [the full September 19 research](LIQUIDITY_REWARD_RESEARCH.md)
and [API reference](KALSHI_API_REFERENCE.md), not a replacement strategy.

## Coverage and conclusion

Freshly retrieved the official [documentation index](https://docs.kalshi.com/llms.txt),
all three REST specifications (116 Predictions, 48 Perps, 27 clearing-member
operations) and both WebSocket specifications (15 and 8 channels, including
connection/control channels). Searched operation descriptions/IDs/paths for reward,
incentive, rebate and credit interfaces; inspected the relevant schemas, related
endpoint pages, changelog, reward help pages and July filing. This is a public
API-surface audit, not a claim to have reviewed every unrelated website article
or undocumented internal service. The regulatory-notices page did not expose a
complete readable notice list; later unindexed amendments cannot be ruled out.

Only `GET /incentive_programs` is a dedicated public reward-definition operation.
An FCM daily-cap description mentioning credits is not a reward endpoint.
No published personal accrual/score, qualification-check, claim, paid-reward
ledger or reward WebSocket was found. The absent endpoint finding is limited to
these published sources; it does not describe Kalshi's internal systems.

**The useful omissions are implementation capabilities already documented:**
larger incentive pages and on-demand WebSocket book snapshots. The reward
operation and its relevant schemas are unchanged from our September 19 capture.
Both WebSocket specifications are also byte-identical to that capture.

## Dedicated endpoint contract

`GET https://external-api.kalshi.com/trade-api/v2/incentive_programs` is public.
Its five parameters are `status`, `type`, `incentive_description`, `limit`,
and `cursor`. Status distinguishes all/active/upcoming/closed/paid-out programs;
type distinguishes liquidity, volume and the two margin-volume variants. The
description filter is an exact string match. There is no current documented
ticker, account, program-ID, date-range or changed-since filter. `limit` permits
1–10,000, default 100. Continue using `next_cursor` until exhausted.

Rows identify the program/market, type, description, dates, total pool and payout
state, with nullable liquidity target, basis-point discount and account cap.
Pool/cap amounts are centi-cents (divide by 10,000 for dollars); target size is
fixed-point quantity. `paid_out` concerns the program, not this account's credit.
Definitions alone supply neither current reference prices nor personal earnings.
[Current operation and embedded schema](https://docs.kalshi.com/api-reference/incentive-programs/get-incentives).

The old changelog mentions ticker filtering and `series_ticker`; neither is in
the current operation/schema contract. Do not invent support or depend on
undocumented parameters; a server may silently ignore them.
[Changelog](https://docs.kalshi.com/changelog).

## Missed page-size opportunity: measured

Our runtime and candidate preparation both explicitly request `limit=100`.
The D-069 build contract selected that size despite the earlier research already
documenting 10,000. `IncentiveDiscovery._refresh` and `RestReads.collect` each
enforce a 30-second enumeration deadline. Roughly 5,000 rows means about 50
sequential requests, before metadata/account contention and quota changes.
This is a credible timeout contributor, not a measured decomposition of the
failed production request's network/queue latency.

A bounded **unauthenticated research read**, through existing `RestReads` with
`limit=1000`, completed at **2026-09-23 00:37:59 UTC** (20:37:59 Eastern):

| Observation | Result |
|---|---:|
| Active liquidity rows / unique IDs / unique markets | 4,981 / 4,981 / 4,981 |
| Pages, complete cursor enumeration | 5, yes |
| Elapsed time | 1.986 seconds |
| Total response bytes | 1,894,742 |
| Largest reconstructed 1,000-row JSON page, approximately | 381,455 bytes |
| Existing per-response cap / total enumeration cap | 2 MiB / 8 MiB |

No response was installed into production and no private endpoint was called.
This is one public sample, without the live account workload or quota lease;
it does not prove live performance or economic eligibility. Reconstructed page
size is not an exact per-request wire measurement. The catalog changes over time.

**Recommendation, not implemented:** test 1,000-row pages first, keeping exact
cursor/duplicate/provenance checks, total row/byte limits, account priority and
freshness fences. The documented 10,000 maximum is not automatically the best
choice: a future large response may exceed the client's 2 MiB per-page bound.
Do not increase deadlines, loosen reward filters or reset exhaustion merely to
mask unnecessary requests. Larger pages reduce round trips; no fixed API-token
savings are claimed. [Rate rules](https://docs.kalshi.com/getting_started/rate_limits)
and [endpoint costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs)
remain authoritative for actual account budgeting.

## Other documented interfaces and implementation gaps

| Interface | What it supplies / boundary | Our current use or opportunity |
|---|---|---|
| WS `orderbook_delta`, `update_subscription` action `get_snapshot` | Fresh snapshots for requested ticker list without altering subscriptions; reply can include command ID | Current reader sends initial subscribe only. Add bounded request/response correlation and sequence-safe snapshot handling before using this to refresh quiet books |
| WS Ping/Pong | Connection health; server ping every 10 seconds | Existing client uses 10-second keepalive. This does not prove an individual market book is current or relax its five-second rule |
| WS orderbook delta `client_order_id`, `subaccount` | Optional annotation when our order caused a change | Potential telemetry improvement; not full snapshot ownership or proof of earned rewards. Do not remove recovery/queue checks on this basis |
| `GET /markets/{ticker}/orderbook`, `/markets/orderbooks` | Depth; batch supports 1–100 tickers | REST fallback if justified; prefer the documented WS snapshot capability, not another full-universe polling loop |
| `GET /portfolio/orders/queue_positions`, `/portfolio/orders/{order_id}/queue_position` | Execution queue position, not liquidity score | Existing reward reflection uses the account-wide route; no per-order reward endpoint is missing |
| WS own orders/fills/positions; portfolio order/fill/position/history reads | Actual remaining size, execution and inventory evidence | Necessary for risk and sampled reward estimates, but not venue reward accounting |
| Markets/events/series, fee changes, milestones; lifecycle WS | Rules, grids, fees and event timing | Existing metadata path; no generic expiry-as-event-start shortcut |
| Portfolio settlements/balance | Contract settlement and account cash | Neither identifies a personal liquidity-reward credit by itself |

Sources: [book updates](https://docs.kalshi.com/websockets/orderbook-updates),
[keepalive](https://docs.kalshi.com/websockets/connection-keep-alive),
[full WS schema](https://docs.kalshi.com/asyncapi.yaml),
[batch books](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks),
[queue positions](https://docs.kalshi.com/api-reference/orders/get-queue-positions-for-orders),
[settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements).
The April 20, 2026 changelog specifically documents `get_snapshot`; this is not
a newly invented command. A quiet book and an unhealthy connection must remain
distinct without treating a heartbeat as a market snapshot.

## Reward rules and payout evidence rechecked

The current help and July clean filing still use target-depth reference pricing,
size/distance-weighted shares and two-sided-depth qualification. Full price weight
is not the whole reward pool. The qualifying cutoff includes the full crossing
price level; periods may overlap and excluded snapshots reduce payouts.
[Current help](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program),
[July filing, clean appendix](https://www.cftc.gov/filings/orgrules/rules07152610358.pdf).
No scoring change was found requiring alteration of our approved entry filters.
Account eligibility and unresolved rule/API discrepancies remain as recorded in
the earlier research; this re-audit is not account-eligibility certification.

The $1 minimum is **per individual program**, not pooled across programs or the
whole account. Signed-in market popovers may show estimated earnings; the Rewards
history and Activity credits show paid amounts. Event-level discovery totals can
combine several market pools. Neither `paid_out` nor a balance delta substitutes
for our personal credit record.
[Official UI and payment guide](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them).

Volume rewards, designated-provider agreements, margin programs and the separately
filed sports-component program are not additional passive LIP income by default.
The current [volume](https://help.kalshi.com/en/articles/13823850-what-is-the-kalshi-volume-incentive-program)
and [designated-provider](https://help.kalshi.com/en/articles/15410219-liquidity-provider-program)
guides preserve that distinction. Do not add those strategies to this repair.

## Provenance and remaining verification

Fresh schema SHA-256 values:

| Official file under `https://docs.kalshi.com/` | SHA-256 |
|---|---|
| `openapi.yaml` | `4c03a1c6fdf8f575b568335febec6be9eb9169c7103862c709c265c50e46b4cd` |
| `perps_openapi.yaml` | `517707d63d5f1581f6b7c49c554bf39275052fac273385bc69e7b2680e0ee0a7` |
| `perps_scm_openapi.yaml` | `2e0e00e2323879efbc04ab639fbc87c0a763d2dfb76fc8c86c155020983305e0` |
| `asyncapi.yaml` | `88c08bda9118af5cca503de49da152e1e5f2e6e67493e887e9cf622dbfba8045` |
| `perps_asyncapi.yaml` | `daa116f8c971346d02d60c5c39a09cbb4ecc296f3ad7457b7c922769d69a1c45` |

Some REST material changed since September 19 (including historical order/fill
operations); the full saved reference remains explicitly dated, not silently
recertified. Reward operation/response components were compared structurally and
are unchanged. No production WebSocket command was sent during this research.
Live shared-budget performance, snapshot sequencing and exact per-market exclusion
counts still require implementation tests and separately approved live acceptance.
