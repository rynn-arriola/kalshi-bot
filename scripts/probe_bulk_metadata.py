"""Bounded public bulk-metadata comparison; never installs trading evidence."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from uuid import uuid4

from kalshi_bot.market_inputs import parse_market, parse_event, timestamp
from kalshi_bot.observability import safe_error
from kalshi_bot.rest import get_wire, decode
from kalshi_bot.startup import save_result
from kalshi_bot.values import InvalidData
from kalshi_bot.windows import WindowsLease


def indexed(rows, key, expected):
    values = {}
    for row in rows:
        identity = row[key]
        if identity in values or identity not in expected:
            raise InvalidData('bulk response identity conflict')
        values[identity] = row
    if set(values) != set(expected):
        raise InvalidData('bulk response incomplete')
    return values


class PublicMetadata:
    def __init__(self):
        self.calls = []
        self.started = self.next_at = time.monotonic()
        self.failed = False

    def read(self, path, **query):
        if not re.fullmatch(r'(markets|events)(/[A-Za-z0-9_.-]+)?', path):
            raise InvalidData('metadata-only path required')
        if path.endswith(('/orderbooks','/trades','/fee_changes','/candlesticks','/multivariate')):
            raise InvalidData('unrelated endpoint forbidden')
        if self.failed or len(self.calls) >= 40 or time.monotonic()-self.started > 90:
            raise InvalidData('public metadata probe bound reached')
        time.sleep(max(0,self.next_at-time.monotonic()))
        self.next_at = time.monotonic()+.5
        before = time.monotonic()
        self.failed = True  # any exception/refusal prevents a subsequent read
        response = get_wire('https://external-api.kalshi.com/trade-api/v2/'+path+
                            ('?'+urlencode(query) if query else ''), {'Accept':'application/json'},8*1024*1024)
        self.calls.append(dict(route=path.split('/')[0], detail='/' in path,
            status=response.status,bytes=len(response.body),seconds=time.monotonic()-before))
        if response.status != 200 or sum(c['bytes'] for c in self.calls)>64*1024*1024:
            raise InvalidData('metadata response refused or total bound exceeded')
        doc = decode(response.body)
        if doc.get('cursor'):
            raise InvalidData('bounded metadata query not exhausted')
        self.failed = False
        return doc


def probe(source, output):
    result = dict(state='RUNNING', started_at=datetime.now(timezone.utc).isoformat(),
        private_rest_requests=0,orders_modified=0,trading_started=False,
        fee_schedules_and_live_authority_verified=False)
    client = PublicMetadata()
    try:
        path = source/'config'/'live-inputs.local.json'
        if path.stat().st_size>1048576:
            raise InvalidData('saved input size exceeded')
        document = json.loads(path.read_text(encoding='utf-8-sig'))
        reviews = {r['ticker']:r for r in document['timing_reviews']}
        if not 1<=len(reviews)<=1024:
            raise InvalidData('invalid reviewed scope')
        # Compare list-market metadata on a bounded 100-market sample first.
        sample = tuple(reviews)[:100]
        listed = {}
        before = time.monotonic()
        for offset in range(0,len(sample),50):
            scope = sample[offset:offset+50]
            doc = client.read('markets',tickers=','.join(scope),limit=1000)
            listed.update(indexed(doc['markets'],'ticker',scope))
        result['market_list'] = dict(requested=len(sample),returned=len(listed),
            parsed=sum(parse_market({'market':row},t).ticker==t for t,row in listed.items()),
            elapsed_seconds=time.monotonic()-before)
        events = tuple(sorted({r['event'] for r in reviews.values()}))
        nested, returned_events, milestones = {}, {}, {}
        before = time.monotonic()
        call_start = len(client.calls)
        for offset in range(0,len(events),50):
            scope = events[offset:offset+50]
            doc = client.read('events',tickers=','.join(scope),limit=200,
                with_nested_markets='true',with_milestones='true')
            batch = indexed(doc['events'],'event_ticker',scope)
            returned_events.update(batch)
            for event,row in batch.items():
                parse_event({'event':row},event)
                for market in row['markets']:
                    if market['ticker'] in reviews:
                        if market['ticker'] in nested:
                            raise InvalidData('duplicate nested market')
                        nested[market['ticker']] = market
            for row in doc.get('milestones',[]):
                if row['id'] in milestones and milestones[row['id']] != row:
                    raise InvalidData('milestone changed between pages')
                milestones[row['id']] = row
        counts = Counter()
        for t,review in reviews.items():
            if t not in nested:
                counts['missing_market'] += 1
                continue
            market = parse_market({'market':nested[t]},t)
            counts['parsed_markets'] += 1
            counts['active_markets'] += market.active
            counts['rules_match_saved_review'] += market.rules_hash == review['rules_hash']
            milestone = milestones.get(review['milestone_id'])
            matched = (milestone is not None and milestone['type']==review['milestone_type']
                and review['event'] in milestone['primary_event_tickers'])
            if matched:
                timestamp(milestone['start_date'])
            counts['milestone_binding_present'] += bool(matched)
        result['nested_events'] = dict(requested_events=len(events),returned_events=len(returned_events),
            requests=len(client.calls)-call_start,requested_markets=len(reviews),**counts,
            elapsed_seconds=time.monotonic()-before)
        # Sequential equality compares parser-used fields, not moving best prices.
        comparisons = Counter()
        for t in sample[:5]:
            individual = parse_market(client.read('markets/'+t),t)
            comparisons['market_details_checked'] += 1
            comparisons['market_list_matches'] += individual==parse_market({'market':listed[t]},t)
            comparisons['nested_market_matches'] += t in nested and individual==parse_market({'market':nested[t]},t)
        for t in events[:3]:
            individual = parse_event(client.read('events/'+t),t)
            comparisons['event_details_checked'] += 1
            comparisons['event_list_matches'] += individual==parse_event({'event':returned_events[t]},t)
        result.update(comparisons=dict(comparisons),state='OBSERVED')
    except Exception as exc:
        result.update(state='FAILED',errors=safe_error(exc))
    result.update(calls=client.calls,elapsed_seconds=time.monotonic()-client.started,
                  finished_at=datetime.now(timezone.utc).isoformat())
    save_result(output,result)
    print(json.dumps(dict(result_file=str(output),**result),indent=2))
    return 0 if result['state']=='OBSERVED' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only-live-check',required=True,action='store_true')
    parser.add_argument('--source-root',required=True,type=Path)
    args = parser.parse_args()
    if not args.source_root.is_absolute():
        raise InvalidData('absolute source root required')
    output = Path(__file__).resolve().parents[1]/'data'/'bulk-metadata'/uuid4().hex/'result.json'
    output.parent.mkdir(parents=True,exist_ok=False)
    with WindowsLease('kalshi-reward-source-readonly-probe'):
        return probe(args.source_root,output)


if __name__=='__main__':
    raise SystemExit(main())
