"""Weekly calibration report from the D-151 research dataset (read-only).

Usage:  python scripts/research_report.py [--days 7] [--db data/trader/research.db]
                                          [--out data/trader/reports]

Reads research.db only (never the ledger or the venue) and writes a Markdown
report to stdout and to ``--out``. Tables, not decisions: every threshold change
remains an operator decision.
"""
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
# Kalshi pays liquidity rewards around 2-4 AM ET the day after a program's end
# (operator-supplied community evidence, 2026-09-26); allow a two-day window.
PAYOUT_WINDOW = timedelta(days=2)


def load(db, since):
    uri = Path(db).resolve().as_uri()+'?mode=ro'
    data = {}
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        for table in ('entries', 'entry_ends', 'fills', 'fill_marks', 'withdrawals',
                      'withdrawal_marks', 'trades', 'health_hourly', 'reward_estimates',
                      'reward_credits'):
            data[table] = [(at, key, json.loads(payload)) for at, key, payload in conn.execute(
                f'SELECT at,key,payload FROM {table} WHERE at >= ? ORDER BY id',
                (since.isoformat(),))]
    return data


def dec(value):
    return None if value is None else Decimal(str(value))


def pct(n, d):
    return '–' if not d else f'{100*n/d:.0f}%'


def table(headers, rows):
    lines = ['| '+' | '.join(headers)+' |', '|'+'---|'*len(headers)]
    lines += ['| '+' | '.join(str(c) for c in row)+' |' for row in rows]
    return '\n'.join(lines)


def entries_section(data):
    ends = {key: row for _, key, row in data['entry_ends']}
    by_verdict = defaultdict(lambda: dict(pairs=0, orders=0, filled=0, withdrawn=0))
    by_volume = defaultdict(lambda: dict(orders=0, filled=0))
    by_ahead = defaultdict(lambda: dict(orders=0, filled=0))
    for _, _, entry in data['entries']:
        verdict = entry.get('screen') or 'unknown'
        stats = by_verdict[verdict]
        stats['pairs'] += 1
        volume = dec(entry.get('volume_24h'))
        vbucket = ('unknown' if volume is None else '0' if volume == 0
                   else '<100' if volume < 100 else '100-286' if volume*7 <= 2000 else '>286 (>2k/wk)')
        for order_id in entry.get('order_ids', ()):
            end = ends.get(order_id)
            if end is None:
                continue
            filled = dec(end.get('filled')) > 0
            stats['orders'] += 1
            stats['filled'] += filled
            stats['withdrawn'] += bool(end.get('withdrawn'))
            by_volume[vbucket]['orders'] += 1
            by_volume[vbucket]['filled'] += filled
            side = end.get('side')
            quote = next((q for q in entry.get('quotes', ()) if q.get('side') == side), None)
            ahead = dec(quote.get('visible_ahead')) if quote else None
            abucket = ('unknown' if ahead is None else '<100' if ahead < 100
                       else '100-300' if ahead < 300 else '300-1000' if ahead < 1000 else '1000+')
            by_ahead[abucket]['orders'] += 1
            by_ahead[abucket]['filled'] += filled
    out = ['## Entries and outcomes',
           table(['shadow verdict', 'pairs', 'ended orders', 'filled', 'fill rate', 'pulled'],
                 [(v, s['pairs'], s['orders'], s['filled'], pct(s['filled'], s['orders']),
                   pct(s['withdrawn'], s['orders'])) for v, s in sorted(by_verdict.items())]),
           '', '**Fill rate by 24-h volume** (the D-150 volume rule cuts above 286/day)',
           table(['24-h volume', 'orders', 'filled', 'fill rate'],
                 [(b, s['orders'], s['filled'], pct(s['filled'], s['orders']))
                  for b, s in sorted(by_volume.items())]),
           '', '**Fill rate by visible size ahead at placement**',
           table(['ahead', 'orders', 'filled', 'fill rate'],
                 [(b, s['orders'], s['filled'], pct(s['filled'], s['orders']))
                  for b, s in sorted(by_ahead.items())])]
    return '\n'.join(out)


def fills_section(data):
    marks = defaultdict(dict)
    for _, key, mark in data['fill_marks']:
        fill_key, _, delay = key.rpartition('@')
        marks[fill_key][delay] = mark
    rows, warned = [], 0
    for _, key, fill in data['fills']:
        price, qty = dec(fill['price']), dec(fill['quantity'])
        warned += bool(fill.get('withdrawal_in_progress'))
        moves = []
        for delay in ('60', '300', '1800'):
            mark = marks[key].get(delay)
            bid, ask = (dec(mark.get('best_bid')), dec(mark.get('best_ask'))) if mark else (None, None)
            # Liquidation value against us: a bought YES sells at the bid.
            value = bid if fill['side'] == 'bid' else ask
            moves.append('–' if value is None else
                         f"{(value-price if fill['side'] == 'bid' else price-value)*qty:+.2f}")
        rows.append((fill['ticker'], fill['role'], fill['side'], price, qty,
                     fill.get('estimated_ahead') or '–', *moves))
    return '\n'.join(['## Fills and mark-outs (USD, + = in our favour)',
        f'{len(rows)} fills; {warned} while a protective pull was already under way.',
        table(['market', 'role', 'side', 'price', 'qty', 'est. ahead', '1 min', '5 min', '30 min'],
              rows[-40:])])


def withdrawals_section(data):
    gone = {}
    for _, key, mark in data['withdrawal_marks']:
        base, _, delay = key.rpartition('@')
        if delay.startswith('60'):
            gone[base] = bool(mark.get('level_gone'))
    stats = defaultdict(lambda: [0, 0, 0])
    for _, key, row in data['withdrawals']:
        for trigger in row.get('triggers') or ['none']:
            stats[trigger][0] += 1
            if key in gone:
                stats[trigger][1] += 1
                stats[trigger][2] += gone[key]
    return '\n'.join(['## Protective pulls: was the market really coming?',
        'A pull counts as justified when our price level was gone 60 s later.',
        table(['trigger', 'pulls', 'checked', 'justified', 'precision'],
              [(t, s[0], s[1], s[2], pct(s[2], s[1])) for t, s in sorted(stats.items())])])


def sweeps_section(data):
    per_market = defaultdict(lambda: defaultdict(Decimal))
    for _, _, trade in data['trades']:
        key = (trade.get('created_time'), trade.get('taker_side'))
        per_market[trade['ticker']][key] += dec(trade.get('count')) or 0
    rows = []
    for ticker, sweeps in per_market.items():
        sizes = sorted(sweeps.values())
        rows.append((ticker, len(sizes), f'{median(sizes):.0f}', f'{sizes[-1]:.0f}',
                     sum(1 for s in sizes if s >= 150)))
    rows.sort(key=lambda r: -Decimal(r[3]))
    return '\n'.join(['## Sweep sizes in markets we quoted (one taker order = one sweep)',
        table(['market', 'sweeps', 'median', 'largest', '≥150'], rows[:30])])


def rewards_section(data):
    latest, ends = {}, {}
    for _, _, row in data['reward_estimates']:
        latest[row['program_id']] = row
    for _, _, entry in data['entries']:
        if entry.get('program_end'):
            ends[entry['program_id']] = datetime.fromisoformat(entry['program_end'])
    credits = [(datetime.fromisoformat(at), dec(row['amount']))
               for at, _, row in data['reward_credits'] if row.get('kind') == 'unattributed_credit']
    rows = []
    for program_id, end in sorted(ends.items(), key=lambda item: item[1]):
        estimate = dec((latest.get(program_id) or {}).get('sampled_gross_usd'))
        paid = sum((amount for at, amount in credits if end <= at <= end+PAYOUT_WINDOW), Decimal(0))
        rows.append((program_id[:8], end.date(), '–' if estimate is None else f'{estimate:.2f}',
                     'yes' if estimate is not None and estimate >= 1 else 'no',
                     f'{paid:.2f}' if paid else '–'))
    return '\n'.join(['## Reward truth: estimate vs. credits',
        'Payouts arrive ~2–4 AM ET the day after a program ends; credits in that window '
        'are listed beside every program ending then (shared credits appear more than once).',
        f"{len(credits)} reward-like credits totalling ${sum((a for _, a in credits), Decimal(0)):.2f}.",
        table(['program', 'ends', 'our estimate $', 'clears $1', 'credits in window $'], rows)])


def health_section(data):
    rows = []
    for _, key, row in data['health_hourly'][-48:]:
        counters = row.get('counters') or {}
        pulls = sum(v for k, v in counters.items() if k.startswith('pulls.'))
        recoveries = sum(v for k, v in counters.items() if k.startswith('recovery.'))
        fraction = row.get('entry_allowed_fraction')
        rows.append((key[:13], row['samples'], '–' if fraction is None else f'{fraction:.0%}',
                     row.get('average_resting_entries') and f"{row['average_resting_entries']:.0f}" or '–',
                     recoveries, pulls, counters.get('fills_recorded', 0)))
    return '\n'.join(['## Hourly health (latest 48 hours)',
        table(['hour (UTC)', 'samples', 'entries allowed', 'avg resting', 'full re-checks',
               'pulls', 'fills'], rows)])


def report(data, *, days, now):
    return '\n\n'.join([f'# Research calibration report — {now:%Y-%m-%d} (last {days} days)',
        entries_section(data), fills_section(data), withdrawals_section(data),
        sweeps_section(data), rewards_section(data), health_section(data)])+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--db', default=str(ROOT/'data'/'trader'/'research.db'))
    parser.add_argument('--out', default=str(ROOT/'data'/'trader'/'reports'))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    text = report(load(args.db, now-timedelta(days=args.days)), days=args.days, now=now)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out/f'research-{now:%Y%m%d}.md').write_text(text, encoding='utf-8')
    # The Windows console code page cannot print the report's typography.
    sys.stdout.reconfigure(encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
