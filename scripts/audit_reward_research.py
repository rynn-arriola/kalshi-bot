"""Offline integrity and independent Decimal arithmetic check of research evidence."""
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal as D
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data/reward-research/20260919T225211Z"
read = lambda name: json.loads((EVIDENCE/name).read_text(encoding="utf-8"))
programs, rows, log, summary = (read(n) for n in
    ("programs.json", "book-analysis.json", "requests.json", "summary.json"))
assert len(programs) == len({p["id"] for p in programs}) == 5252
assert dict(Counter(p["incentive_type"] for p in programs)) == summary["types"]
assert len(log) == 102 and all(r["status"] == 200 for r in log)
assert len(rows) == 40 and sum(r["both_reach_target"] for r in rows) == 27

responses = {}
for entry in log:
    saved = read(entry["file"])
    assert saved["status"] == entry["status"] and saved["url"] == entry["url"]
    responses[urlsplit(entry["url"]).path] = saved["body"]

checked = 0
for row in rows:
    book = responses["/trade-api/v2/markets/" + row["ticker"] + "/orderbook"]["orderbook_fp"]
    for scenario in row.get("static_arithmetic", []):
        shares = []
        for side in ("yes", "no"):
            ladder = {D(p):D(q) for p,q in book[side+"_dollars"]}
            own_price = D(str(scenario["prices"][side]))
            own_q = D(scenario["size_each_side"])
            ladder[own_price] = ladder.get(own_price,D(0)) + own_q
            cumulative, target, reference, cutoff = D(0),D(str(row["target"])),None,None
            qualified = []
            for p,q in sorted(ladder.items(),reverse=True):
                cumulative += q
                qualified.append((p,q))
                if reference is None and cumulative >= target/5:
                    reference = p
                if cumulative >= target:
                    cutoff = p
                    break
            share = D(0)
            if cutoff is not None and own_price >= cutoff:
                tick = D(row["price_ranges"][0]["step"])
                discount = D(str(row["discount"]))
                def weight(p):
                    distance = max(D(0),(reference-p)/tick)
                    assert distance == int(distance)
                    return discount ** int(distance)
                share = own_q*weight(own_price)/sum(q*weight(p) for p,q in qualified)
            assert abs(float(share)-scenario["side_shares"][side]) < 1e-10
            shares.append(share)
        daily = sum(shares)/2*D(str(row["pool_per_24h"]))
        remaining = daily*D(str(row["hours_left"]))/24
        assert abs(float(daily)-scenario["gross_24h_static"]) < 1e-8
        assert abs(float(remaining)-scenario["remaining_gross_static"]) < 1e-8
        checked += 1

report_path = ROOT/"docs/LIQUIDITY_REWARD_RESEARCH.md"
report = report_path.read_text(encoding="utf-8")
local_links = []
for target in re.findall(r"\]\(([^)]+)\)",report):
    if "://" in target or target.startswith("#"):
        continue
    assert (report_path.parent/target.split("#")[0]).exists(),target
    local_links.append(target)

files = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
         for p in EVIDENCE.rglob("*") if p.is_file()}
for p in (report_path, ROOT/"scripts/inspect_reward_apis.py",Path(__file__).resolve()):
    files[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
result = {"observation_utc":summary["started_utc"],"logged_http_requests":len(log),
          "independent_decimal_scenarios_checked":checked,
          "local_markdown_links_checked":len(local_links),"file_sha256":files,
          "notes":["Offline audit, no API calls or orders.",
                   "Hash the saved JSON envelopes; original wire-body hashes cannot be reproduced from reserialized JSON.",
                   "Arithmetic verification is not a profitability or execution test."]}
(ROOT/"docs/LIQUIDITY_REWARD_AUDIT.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in result.items() if k!='file_sha256'},indent=2))
