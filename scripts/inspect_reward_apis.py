"""One-shot public GET research. No keys, orders, collector, or paper trading.

Writes dated raw evidence and a summary under ignored data/reward-research/.
Books are a purposive sample, NOT a population estimate or profit forecast.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://external-api.kalshi.com/trade-api/v2"
NOW = datetime.now(timezone.utc)
OUT = ROOT / "data" / "reward-research" / NOW.strftime("%Y%m%dT%H%M%SZ")
OUT.mkdir(parents=True, exist_ok=False)
LOG = []


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def get(path, params=None, name=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
    started = datetime.now(timezone.utc).isoformat()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "KalshiRewardReadOnlyResearch/1.0"}, method="GET")
        with urllib.request.urlopen(request, timeout=25) as response:
            raw, status = response.read(), response.status
        body = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"error": raw.decode(errors="replace")[:1000]}
    except Exception as exc:
        raw, status, body = b"", None, {"error": str(exc)}
    filename = name or f"response-{len(LOG):03d}.json"
    save(filename, {"url": url, "fetched_utc": started, "status": status, "body": body})
    LOG.append({"url": url, "utc": started, "status": status, "file": filename,
                "body_sha256": hashlib.sha256(raw).hexdigest()})
    time.sleep(0.12)
    return body if status == 200 else {}


def date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def duration(p):
    return (date(p["end_date"]) - date(p["start_date"])).total_seconds()


def rate(p):
    return p["period_reward"] / 10000 * 86400 / duration(p)


def stats(values):
    values = sorted(values)
    if not values:
        return {}
    return {"min": values[0], "median": statistics.median(values),
            "p90": values[int((len(values)-1)*.9)], "max": values[-1]}


# Full active enumeration; other statuses intentionally sampled, not historical archive.
programs, cursor, seen = [], "", set()
for page in range(100):
    params = {"status": "active", "type": "all", "limit": 10000}
    if cursor:
        params["cursor"] = cursor
    body = get("/incentive_programs", params, f"active-{page}.json")
    if "incentive_programs" not in body:
        raise RuntimeError("active inventory failed; do not report complete")
    programs.extend(body["incentive_programs"])
    cursor = body.get("next_cursor", "")
    if not cursor:
        break
    if cursor in seen:
        raise RuntimeError("repeated pagination cursor")
    seen.add(cursor)
else:
    raise RuntimeError("active inventory exceeded bounded page count")

probes = []
for status in ("all", "active", "upcoming", "closed", "paid_out"):
    body = get("/incentive_programs", {"status": status, "type": "all", "limit": 2})
    probes.append({"filter": {"status": status}, "returned": len(body.get("incentive_programs", [])),
                   "has_cursor": bool(body.get("next_cursor")), "http": LOG[-1]["status"]})
for kind in ("all", "liquidity", "volume", "margin_maker_volume", "margin_taker_volume"):
    body = get("/incentive_programs", {"status": "active", "type": kind, "limit": 2})
    probes.append({"filter": {"type": kind}, "returned": len(body.get("incentive_programs", [])),
                   "types": sorted({p["incentive_type"] for p in body.get("incentive_programs", [])}),
                   "http": LOG[-1]["status"]})
first = get("/incentive_programs", {"status": "active", "type": "liquidity", "limit": 2})
second = get("/incentive_programs", {"status": "active", "type": "liquidity", "limit": 2,
                                     "cursor": first.get("next_cursor", "")}) if first.get("next_cursor") else {}
liquidity = [p for p in programs if p["incentive_type"] == "liquidity"]
description = liquidity[0]["incentive_description"]
exact = get("/incentive_programs", {"status": "active", "incentive_description": description, "limit": 2})

# Deterministic diverse high-pool/target sample: one market per series per stratum.
selected, tickers = [], set()
for pool in (sorted(liquidity, key=lambda p: rate(p)/float(p["target_size_fp"]), reverse=True),
             sorted(liquidity, key=lambda p: rate(p), reverse=True)):
    series_seen = set()
    n = 0
    for p in pool:
        ticker = p["market_ticker"]
        series = ticker.split("-")[0]  # sampling grouping only, verified by event later
        if ticker in tickers or series in series_seen:
            continue
        selected.append(p)
        tickers.add(ticker)
        series_seen.add(series)
        n += 1
        if n == 20:
            break

books, rows = {}, []
for p in selected:
    ticker = p["market_ticker"]
    market = get("/markets/" + urllib.parse.quote(ticker))["market"]
    book = get("/markets/" + urllib.parse.quote(ticker) + "/orderbook", {"depth": 0})
    books[ticker] = book
    fp = book.get("orderbook_fp", {})
    levels = {side: sorted([(float(a), float(b)) for a,b in fp.get(side+"_dollars", [])], reverse=True)
              for side in ("yes", "no")}
    target = float(p["target_size_fp"])
    sides = {}
    for side, ladder in levels.items():
        total, ref, cutoff, qualifying = 0., None, None, []
        for price, count in ladder:
            total += count
            qualifying.append([price,count])
            if ref is None and total >= target/5:
                ref = price
            if total >= target:
                cutoff = price
                break
        sides[side] = {"reference": ref, "cutoff": cutoff,
                       "best": ladder[0][0] if ladder else None,
                       "total_book_size": sum(q for _,q in ladder),
                       "qualifying_size": total if cutoff is not None else 0,
                       "levels": qualifying if cutoff is not None else []}
    row = {"program_id":p["id"], "ticker":ticker, "title":market["title"],
           "market_status":market["status"], "event_ticker":market["event_ticker"],
           "close_time":market["close_time"], "occurrence_datetime":market.get("occurrence_datetime"),
           "price_ranges":market["price_ranges"], "exchange_index":market.get("exchange_index"),
           "volume_24h":market.get("volume_24h_fp"), "target":target,
           "discount":p["discount_factor_bps"]/10000, "pool":p["period_reward"]/10000,
           "pool_per_24h":rate(p), "hours_left":max(0,(date(p["end_date"])-NOW).total_seconds()/3600),
           "sides":sides, "both_reach_target":all(sides[s]["cutoff"] is not None for s in sides)}
    # No assumed variable-band tick calculation. Current single-band books only.
    ranges = market["price_ranges"]
    if len(ranges) == 1 and row["both_reach_target"] and market["status"] == "active":
        tick = float(ranges[0]["step"])
        from reward_rules import qualify_side
        comparisons = []
        for size in (1,3,5,9):
            for behind in (0,1,2):
                prices = {s:round(sides[s]["reference"]-behind*tick,8) for s in sides}
                if min(prices.values()) <= 0 or sum(prices.values()) >= 1:
                    continue
                share, credited = 0., {}
                for s, price in prices.items():
                    # Recompute reference, cutoff and denominator including proposed size.
                    augmented = levels[s] + [(price,float(size))]
                    q = qualify_side(augmented,target,row["discount"],tick_size=tick)
                    own_score = size * row["discount"] ** max(0,round((q.reference_price-price)/tick)) if q.reached_target and price >= q.cutoff_price else 0
                    credited[s] = own_score/q.total_score if q.total_score else 0
                    share += credited[s]/2
                daily = share*rate(p)
                remaining = daily*row["hours_left"]/24
                comparisons.append({"size_each_side":size, "ticks_behind_original_reference":behind,
                                    "prices":prices, "side_shares":credited,
                                    "gross_24h_static":daily,"remaining_gross_static":remaining,
                                    "standalone_remaining_clears_1":remaining>=1,
                                    "collateral_unnetted":size*sum(prices.values())})
        row["static_arithmetic"] = comparisons
    rows.append(row)

# Supporting GETs; no authenticated account calls or guessed private routes.
sample = rows[0]
get("/markets/orderbooks", {"tickers": [sample["ticker"], rows[1]["ticker"]]})
get("/markets/trades", {"ticker":sample["ticker"],"limit":2})
get("/events/"+sample["event_ticker"])
get("/series/"+sample["ticker"].split("-")[0])
get("/series/fee_changes", {"series_ticker":sample["ticker"].split("-")[0]})
get("/events/fee_changes", {"event_ticker":sample["event_ticker"]})
get("/exchange/status")
get("/historical/cutoff")

inventory = []
for filename in ("openapi.yaml","perps_openapi.yaml","perps_scm_openapi.yaml"):
    spec = yaml.safe_load((ROOT/"docs"/"api-specs"/filename).read_text(encoding="utf-8"))
    ops = []
    reward = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method not in {"get","post","delete","put","patch"}:
                continue
            ops.append(f"{method.upper()} {path}")
            terms = path + " " + op.get("summary", "") + " " + op.get("description", "")
            if any(word in terms.lower() for word in ("incentiv","reward","earning","rebate")):
                reward.append({"method":method,"path":path,"operationId":op.get("operationId"),
                               "summary":op.get("summary")})
    inventory.append({"spec":filename,"operations":len(ops),"keyword_matches":reward})

summary = {
    "started_utc":NOW.isoformat(), "finished_utc":datetime.now(timezone.utc).isoformat(),
    "active_program_count":len(programs),"unique_ids":len({p['id'] for p in programs}),
    "types":dict(Counter(p['incentive_type'] for p in programs)),
    "liquidity_unique_markets":len({p['market_ticker'] for p in liquidity}),
    "description_counts":dict(Counter(p['incentive_description'] for p in liquidity)),
    "discount_bps_counts":dict(Counter(p.get('discount_factor_bps') for p in liquidity)),
    "target_counts":dict(Counter(p.get('target_size_fp') for p in liquidity)),
    "liquidity_pool_dollars":stats([p['period_reward']/10000 for p in liquidity]),
    "liquidity_duration_hours":stats([duration(p)/3600 for p in liquidity]),
    "liquidity_pool_per_24h":stats([rate(p) for p in liquidity]),
    "liquidity_nonnull_account_caps":sum(p.get('max_reward_per_account') is not None for p in liquidity),
    "fractional_second_programs":sum(date(p['start_date']).microsecond!=0 or date(p['end_date']).microsecond!=0 for p in liquidity),
    "active_outside_dates_at_start":sum(not date(p['start_date'])<=NOW<date(p['end_date']) for p in programs),
    "volume_programs":[p for p in programs if p['incentive_type']!='liquidity'],
    "probes":probes,"pagination_second_page_count":len(second.get('incentive_programs',[])),
    "pagination_disjoint":not ({p['id'] for p in first.get('incentive_programs',[])} & {p['id'] for p in second.get('incentive_programs',[])}),
    "description_filter_exact":all(p['incentive_description']==description for p in exact.get('incentive_programs',[])),
    "spec_inventory":inventory,"sampled_markets":len(rows),
    "sample_both_depth":sum(r['both_reach_target'] for r in rows),
    "http_status_counts":dict(Counter(str(r['status']) for r in LOG)),
    "http_failures":[r for r in LOG if r['status']!=200],
}
save("programs.json",programs)
save("book-analysis.json",rows)
save("summary.json",summary)
save("requests.json",LOG)
print(json.dumps({"output":str(OUT), **summary},indent=2))
