"""Calibration report: evidence for improving the bot (D-151 dataset, read-only).

Usage:  python scripts/calibration_report.py [--days 7] [--db data/trader/research.db]
                                             [--out data/trader/reports]

Its goal is to improve the bot: it shows how entries, fills, protective pulls
and rewards actually turned out, so gates and thresholds can be tuned on
evidence. Reads research.db only (never the ledger or the venue) and writes a
Markdown report to stdout and to ``--out``. Tables, not decisions: every
threshold change remains an operator decision.
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
# Kalshi pays nothing for a program whose reward ends under $1 (all or nothing).
MINIMUM_PAYOUT = Decimal(1)
# D-154/D-155 loss filters (cooldown, downside cap, family memory, sweep filter)
# were all live from this build start; fills before and after are compared.
FILTERS_LIVE = datetime(2026, 9, 27, 11, 42, tzinfo=timezone.utc)


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


def load_ledger(path):
    """Authoritative money from the bot's ledger (read-only): realized P&L per
    fill, cash credits and deposits, and open positions. None if unreadable."""
    try:
        uri = Path(path).resolve().as_uri()+'?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            realized = [(datetime.fromisoformat(at), Decimal(pnl), Decimal(fee)) for pnl, fee, at in
                        conn.execute('SELECT pnl, fee, received_at FROM realized_events')]
            cash = [(datetime.fromisoformat(at), kind, Decimal(amount)) for kind, amount, at in
                    conn.execute('SELECT kind, amount, at FROM cash_adjustments')]
            open_lots = conn.execute('SELECT COUNT(*) FROM lots').fetchone()[0]
    except (sqlite3.Error, OSError, ValueError, ArithmeticError):
        return None
    return dict(realized=realized, cash=cash, open_lots=open_lots)


def resting_estimates(data, now):
    """Resting-based reward estimate per program: every entry leg's resting time
    (placement to its recorded end, or now if still open) times half the pair's
    estimated reward per hour at placement. Our share can shrink after placing
    and quotes can drift out of range, so this leans high; the strict tracker
    only counts verified time and leans low. Payouts show which is closer."""
    ends = {key: datetime.fromisoformat(at) for at, key, _ in data['entry_ends']}
    per = {}
    for at, _, entry in data['entries']:
        placed = datetime.fromisoformat(at)
        rate = dec(entry.get('hourly_reward_usd')) or Decimal(0)
        row = per.setdefault(entry.get('program_id'), dict(hours=Decimal(0), estimate=Decimal(0),
            end=entry.get('program_end')))
        for order_id in entry.get('order_ids', ()):
            stop = min(ends.get(order_id, now), now)
            hours = Decimal(str(max(0.0, (stop-placed).total_seconds())))/3600
            row['hours'] += hours
            row['estimate'] += rate*hours/2
    return per


def _end(value):
    return None if not value else datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def finish_line(data, tracker, now):
    """Per live program we have rested on: earned so far, our resting share of
    its time since we first entered, and whether it can still reach Kalshi's
    $1 minimum before it ends at that share. Verdicts use the resting-based
    estimate, which leans high: "cannot reach" is reliable, "on track" is
    optimistic."""
    strict = {p['program_id']: p['estimate'] for p in tracker or ()}
    resting = resting_estimates(data, now)
    first, rate = {}, {}
    for at, _, entry in data['entries']:
        pid = entry.get('program_id')
        first.setdefault(pid, datetime.fromisoformat(at))
        rate[pid] = dec(entry.get('hourly_reward_usd')) or Decimal(0)  # latest pair rate
        resting[pid]['ticker'] = entry.get('ticker')
    rows = []
    for pid, r in resting.items():
        end = _end(r['end'])
        if end is None or end <= now:
            continue
        elapsed = Decimal(str((now-first[pid]).total_seconds()))/3600
        left = Decimal(str((end-now).total_seconds()))/3600
        share = min(Decimal(1), r['hours']/2/elapsed) if elapsed > 0 else Decimal(0)
        need = MINIMUM_PAYOUT-r['estimate']
        if need <= 0:
            needed, verdict = Decimal(0), 'cleared $1'
        elif not rate[pid]:
            needed, verdict = None, 'cannot reach'
        else:
            needed = need/(rate[pid]*left)
            verdict = ('cannot reach' if needed > 1 else 'on track' if needed <= share
                       else 'needs more resting')
        rows.append(dict(program_id=pid, ticker=r.get('ticker'), left=left, share=share,
                         needed=needed, verdict=verdict, rate=rate[pid], earned=r['estimate'],
                         strict=strict.get(pid)))
    return rows


FINISH_ORDER = ('cleared $1', 'on track', 'needs more resting', 'cannot reach')


def finish_line_section(data, tracker, now):
    rows = finish_line(data, tracker, now)
    out = ['## $1 finish line (live programs we have rested on)',
           'Kalshi pays nothing for a program that ends under $1. "Share" is the part of '
           'the time since we first entered that we were resting; "needed" is the share '
           'of the time left that would still reach $1. Verdicts use the resting-based '
           'estimate (leans high): "cannot reach" is reliable, "on track" is optimistic.']
    if not rows:
        return '\n'.join(out+['No live programs with entries in this window.'])
    summary = []
    for verdict in FINISH_ORDER:
        group = [r for r in rows if r['verdict'] == verdict]
        summary.append((verdict, len(group), f"{sum((r['earned'] for r in group), Decimal(0)):.2f}"))
    out.append(table(['verdict', 'programs', 'earned so far $ (resting-based)'], summary))
    at_risk = sum((r['earned'] for r in rows if r['verdict'] in FINISH_ORDER[2:]), Decimal(0))
    out.append(f'Estimated earnings on programs not yet on track for $1 (pay nothing unless '
               f'that changes): ${at_risk:.2f}. Median resting share: '
               f"{median(r['share'] for r in rows):.0%}.")
    rows.sort(key=lambda r: (FINISH_ORDER.index(r['verdict']), -r['earned']))
    out.append(table(['market', 'ends in (h)', 'earned $ strict', 'earned $ resting-based',
                      'rate $/h', 'share', 'needed', 'verdict'],
        [(r['ticker'], f"{r['left']:.1f}", '–' if r['strict'] is None else f"{r['strict']:.2f}",
          f"{r['earned']:.2f}", f"{r['rate']:.2f}", f"{r['share']:.0%}",
          '–' if r['needed'] is None else f"{min(r['needed'], Decimal(9.99)):.0%}", r['verdict'])
         for r in rows[:40]]))
    return '\n'.join(out)


def loss_filter_section(ledger, now):
    """Fill losses before and after the D-154/D-155 loss filters (ledger money)."""
    out = ['## Fill losses before and after the loss filters',
           f'Filters (cooldown, downside cap, family memory, sweep filter) live from '
           f'{FILTERS_LIVE:%Y-%m-%d %H:%M} UTC. Small samples: read as direction, not proof.']
    if ledger is None or not ledger['realized']:
        return '\n'.join(out+['No ledger fills.'])
    first = min(at for at, _, _ in ledger['realized'])
    rows = []
    for label, start, stop in (('before', first, FILTERS_LIVE), ('after', FILTERS_LIVE, now)):
        fills = [(p, f) for at, p, f in ledger['realized'] if start <= at < stop]
        days = Decimal(str(max(0., (stop-start).total_seconds())))/86400
        money = sum((p for p, _ in fills), Decimal(0))
        rows.append((label, f'{days:.1f}', len(fills), f'{money:+.2f}',
                     f'{money/len(fills):+.2f}' if fills else '–',
                     f'{len(fills)/days:.1f}' if days else '–',
                     f'{money/days:+.2f}' if days else '–'))
    out.append(table(['period', 'days', 'fill events', 'trading $ (after fees)', '$ per fill',
                      'fills per day', '$ per day'], rows))
    return '\n'.join(out)


def business_section(ledger, tracker, data, *, days, now):
    """The money: measured from the ledger, estimates labelled separately."""
    out = ['## Business summary',
           'Money rows are measured from the bot ledger; estimate rows are not money.']
    if ledger is None:
        return '\n'.join(out+['Ledger unavailable: no measured money in this report.'])
    since = now-timedelta(days=days)
    first = min((at for at, _, _ in ledger['realized']), default=None)
    def money(start):
        realized = sum((p for at, p, _ in ledger['realized'] if at >= start), Decimal(0))
        fees = sum((f for at, _, f in ledger['realized'] if at >= start), Decimal(0))
        rewards = sum((a for at, k, a in ledger['cash'] if at >= start and k == 'unattributed_credit'),
                      Decimal(0))
        fills = sum(1 for at, _, _ in ledger['realized'] if at >= start)
        return realized, fees, rewards, fills
    rows = []
    for label, start in ((f'last {days} days', since),
                         ('since the first fill' + ('' if first is None else f' ({first:%Y-%m-%d})'),
                          first or since)):
        realized, fees, rewards, fills = money(start)
        rows.append((label, fills, f'{realized:+.2f}', f'{fees:.2f}', f'{rewards:.2f}',
                     f'{realized+rewards:+.2f}'))
    out.append(table(['period', 'fill events', 'realized trading $ (after fees)', 'fees paid $',
                      'rewards paid $', 'net $'], rows))
    deposits = sum((a for _, k, a in ledger['cash'] if k == 'deposit'), Decimal(0))
    out.append(f"Deposits (not income): ${deposits:.2f}. Open positions now: {ledger['open_lots']} "
               '(unrealized P&L not included).')
    strict = None if tracker is None else sum((p['estimate'] for p in tracker if p['end'] > now), Decimal(0))
    resting = resting_estimates(data, now)
    covered = min((datetime.fromisoformat(at) for at, _, _ in data['entries']), default=None)
    unpaid = sum((r['estimate'] for r in resting.values()
                  if r['end'] and datetime.fromisoformat(r['end']) > now), Decimal(0))
    out.append('Coverage: ledger money since ' + ('–' if first is None else f'{first:%Y-%m-%d %H:%M} UTC')
               + '; research sections since ' + ('–' if covered is None else f'{covered:%Y-%m-%d %H:%M} UTC')
               + f' (report window: last {days} days).')
    out += ['', '**Estimates, not money:**',
            '- Rewards not yet paid, strict tracker (verified time only; a floor): '
            + ('–' if strict is None else f'${strict:.2f}')+'.',
            '- Rewards not yet paid, resting-based (resting time × estimated rate; leans high): '
            f'${unpaid:.2f}' + ('' if covered is None else f' (from research since {covered:%Y-%m-%d %H:%M} UTC only)')+'.',
            '- See "Reward truth" for which estimate Kalshi\'s payouts are closer to.']
    return '\n'.join(out)


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
            filled = (dec(end.get('filled')) or Decimal(0)) > 0
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
        if delay.startswith('60') and mark.get('level_gone') is not None:
            gone[base] = bool(mark['level_gone'])  # None = no book then: unchecked.
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


TRADE_LOOKBACK = timedelta(seconds=30)


def _when(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def _consumes(trade, side, price):
    """A trade eats the queue at our level: takers selling YES hit bids at or
    above our bid; takers buying YES lift asks at or below our ask."""
    _, taker, traded, _ = trade
    if traded is None or price is None:
        return False
    return ((side == 'bid' and taker == 'no' and traded >= price)
            or (side == 'ask' and taker == 'yes' and traded <= price))


def trade_evidence_section(data):
    """D-152 counterfactual: would a trade-evidence rule have pulled?

    For each protective pull, look for real trades on our side of the book in
    the 30 s before it. Pulls without any were driven by cancellations ahead;
    a trade-evidence trigger would have skipped them. The risk column counts
    skipped pulls whose price level was then really gone 60 s later.
    """
    trades = defaultdict(list)
    for _, _, t in data['trades']:
        when = _when(t.get('created_time'))
        if when is not None:
            trades[t['ticker']].append((when, t.get('taker_side'), dec(t.get('yes_price')),
                                        dec(t.get('count')) or 0))
    gone = {}
    for _, key, mark in data['withdrawal_marks']:
        base, _, delay = key.rpartition('@')
        if delay.startswith('60') and mark.get('level_gone') is not None:
            gone[base] = bool(mark['level_gone'])
    stats = defaultdict(lambda: [0, 0, 0, 0])  # pulls, trade-backed, skipped, skipped but gone
    for at, key, row in data['withdrawals']:
        when = _when(at)
        orders = [(o.get('side'), dec(o.get('price'))) for o in row.get('orders') or ()]
        backed = when is not None and any(
            when-TRADE_LOOKBACK <= trade[0] <= when and _consumes(trade, side, price)
            for trade in trades.get(row.get('ticker'), ()) for side, price in orders)
        for trigger in row.get('triggers') or ['none']:
            s = stats[trigger]
            s[0] += 1
            s[1] += backed
            s[2] += not backed
            s[3] += (not backed) and gone.get(key, False)
    fills = []
    for _, _, fill in data['fills']:
        executed = fill.get('executed_us')
        when = (datetime.fromtimestamp(executed/1e6, timezone.utc) if isinstance(executed, (int, float))
                else None)
        side, price = fill.get('side'), dec(fill.get('price'))
        before = when is not None and any(
            when-TRADE_LOOKBACK <= trade[0] < when-timedelta(seconds=1) and _consumes(trade, side, price)
            for trade in trades.get(fill.get('ticker'), ()))
        fills.append(before)
    return '\n'.join(['## Pull trigger vs real trades (D-152 counterfactual)',
        'A pull is trade-backed when Kalshi recorded a trade on our side of the book, at our '
        'price or better, in the 30 s before it. A trade-evidence trigger would skip the '
        'others; "skipped but gone" counts those where our level really was gone 60 s later.',
        table(['trigger', 'pulls', 'trade-backed', 'would skip', 'skipped but gone'],
              [(t, *s) for t, s in sorted(stats.items())]),
        '', f'{len(fills)} fills; {sum(fills)} had trades on our side in the 30 s before '
            f'(the rest were single sweeps no trigger could see coming).'])


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


WEEK_WEIGHTS = (0.50, 0.25, 0.25)  # as Polymarket's ranker: newest week 50%, then 25%, 25%
try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo('America/New_York')
except Exception:  # No tz database: Kalshi's season here is on EDT.
    EASTERN = timezone(timedelta(hours=-4))
SETTLE_BY = timedelta(hours=36)  # after the ET day ends: its credit had time to arrive


def load_tracker(path):
    """The reward tracker's checkpoint: every program's full-period estimate (read-only)."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    programs = []
    for record in raw.get('records', ()):
        program = record.get('program') or {}
        try:
            programs.append(dict(program_id=program['program_id'], ticker=program.get('ticker'),
                end=datetime.fromisoformat(str(program['end']).replace('Z', '+00:00')),
                estimate=Decimal(str(record['estimate'])),
                hours=Decimal(str(record['qualifying_seconds']))/3600))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    return programs


def payout_days(programs, credits, resting=None):
    """Programs grouped by the ET day they end; Kalshi pays that day the next ET morning."""
    days = {}
    for p in programs:
        day = p['end'].astimezone(EASTERN).date()
        g = days.setdefault(day, dict(programs=0, hours=Decimal(0), estimate=Decimal(0),
                                      paid=Decimal(0), credited=False, resting=Decimal(0),
                                      resting_hours=Decimal(0)))
        g['programs'] += 1
        g['hours'] += p['hours']
        g['estimate'] += p['estimate']
        r = (resting or {}).get(p['program_id'])
        if r is not None:
            g['resting'] += r['estimate']
            g['resting_hours'] += r['hours']
    unmatched = Decimal(0)
    for at, amount in credits:
        day = at.astimezone(EASTERN).date()-timedelta(days=1)
        if day in days:
            days[day]['paid'] += amount
            days[day]['credited'] = True
        else:
            unmatched += amount
    return days, unmatched


def day_settled(day, g, now):
    closes = datetime.combine(day+timedelta(days=1), datetime.min.time(), EASTERN)
    return g['credited'] or now >= closes+SETTLE_BY-timedelta(hours=24)


def weighted_factor(days, now):
    """Paid ÷ estimated over settled payout days, three weeks weighted 50/25/25."""
    estimate = paid = Decimal(0)
    for day, g in days.items():
        if not day_settled(day, g, now):
            continue
        ended = datetime.combine(day, datetime.max.time(), EASTERN)
        for k, weight in enumerate(WEEK_WEIGHTS):
            if now-timedelta(days=7*(k+1)) <= ended < now-timedelta(days=7*k):
                estimate += Decimal(str(weight))*g['estimate']
                paid += Decimal(str(weight))*g['paid']
    return None if not estimate else paid/estimate


def rewards_section(data, tracker, now):
    credits = [(datetime.fromisoformat(at), dec(row['amount']))
               for at, _, row in data['reward_credits'] if row.get('kind') == 'unattributed_credit']
    head = ['## Reward truth: our estimate vs. what Kalshi paid',
            'Kalshi pays each ET morning, as one unlabelled credit, for programs that ended the '
            'previous ET day; each credit is matched to that day.',
            f"{len(credits)} reward-like credits totalling ${sum((a for _, a in credits), Decimal(0)):.2f}."]
    if tracker is None:
        return '\n'.join(head+['Reward tracker checkpoint unavailable; no per-day comparison.'])
    days, unmatched = payout_days(tracker, credits, resting_estimates(data, now))
    today = now.astimezone(EASTERN).date()
    rows, settled_est, settled_paid = [], Decimal(0), Decimal(0)
    for day in sorted(days):
        g = days[day]
        if not (g['estimate'] or g['paid'] or g['resting']) or day < today-timedelta(days=21):
            continue
        settled = day_settled(day, g, now)
        if settled:
            settled_est += g['estimate']
            settled_paid += g['paid']
        rows.append((day, g['programs'], f"{g['hours']:.1f}", f"{g['estimate']:.2f}",
                     f"{g['resting_hours']:.1f}", f"{g['resting']:.2f}",
                     f"{g['paid']:.2f}" if settled else 'pending',
                     f"{g['paid']/g['estimate']:.1f}×" if settled and g['estimate'] else '–',
                     f"{g['paid']/g['resting']:.1f}×" if settled and g['resting'] else '–'))
    factor = weighted_factor(days, now)
    return '\n'.join(head+[table(['programs end (ET day)', 'programs', 'verified hours (strict)',
                                   'strict estimate $', 'leg-hours rested (research)',
                                   'resting-based $', 'paid $', 'paid ÷ strict',
                                   'paid ÷ resting-based'], rows),
        'Resting-based figures cover only time since research began (2026-09-26 19:15 UTC); '
        'days before that are understated.', '',
        f"Settled days: paid ${settled_paid:.2f} vs estimated ${settled_est:.2f}"
        + (f" ({settled_paid/settled_est:.1f}×)." if settled_est else '.'),
        'Three-week weighted factor (50/25/25), the reward calibration a ranker would use: '
        + ('–' if factor is None else f'{factor:.2f}×')+'.',
        f'Credits matched to no program day: ${unmatched:.2f}.'])


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


def load_meter(path):
    """D-161 LIP meter totals per program (read-only); None if unreadable."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))['programs']
        return [dict(program_id=pid, ticker=row['ticker'],
                     end=datetime.fromisoformat(row['end']), first_at=datetime.fromisoformat(row['first_at']),
                     earned=Decimal(row['earned']), seconds=Decimal(row['seconds']))
                for pid, row in raw.items()]
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        return None


def meter_section(meter, data, now):
    """D-161: the meter per contract, and per payout day what Kalshi should pay
    after its $1-per-contract floor versus what it paid (WATCHLIST B9)."""
    out = ['## LIP meter per contract (D-161; validating, WATCHLIST B9)',
           "Kalshi pays a program only if it earns $1 or more on that contract. "
           "'Meter payable' applies that floor to the meter's earnings; 'paid ÷ meter' "
           "is the accuracy check (target: within a few percent)."]
    if meter is None:
        return '\n'.join(out+['Meter file unavailable (the meter starts with the D-161 build).'])
    credits = [(datetime.fromisoformat(at), dec(row['amount']))
               for at, _, row in data['reward_credits'] if row.get('kind') == 'unattributed_credit']
    paid = {}
    for at, amount in credits:
        day = at.astimezone(EASTERN).date()-timedelta(days=1)
        paid[day] = paid.get(day, Decimal(0))+amount
    days = {}
    for p in meter:
        g = days.setdefault(p['end'].astimezone(EASTERN).date(),
                            dict(programs=0, earned=Decimal(0), payable=Decimal(0), cleared=0, partial=0))
        g['programs'] += 1
        g['earned'] += p['earned']
        if p['earned'] >= MINIMUM_PAYOUT:
            g['payable'] += p['earned']
            g['cleared'] += 1
    rows = []
    for day in sorted(days):
        g = days[day]
        settled = day_settled(day, dict(credited=day in paid), now)
        got = paid.get(day, Decimal(0))
        rows.append((day, g['programs'], g['cleared'], f"{g['earned']:.2f}", f"{g['payable']:.2f}",
                     f'{got:.2f}' if settled else 'pending',
                     (f"{got/g['payable']:.2f}×" if g['payable'] else ('–' if not got else 'paid, meter 0'))
                     if settled else '–'))
    out.append(table(['programs end (ET day)', 'contracts metered', 'cleared $1', 'meter earned $',
                      'meter payable $ (after $1 floor)', 'paid $', 'paid ÷ meter'], rows))
    start = min((p['first_at'] for p in meter), default=None)
    out.append('Meter coverage starts ' + ('–' if start is None else f'{start:%Y-%m-%d %H:%M} UTC')
               + '; days whose programs began earlier are understated.')
    live = sorted((p for p in meter if p['end'] > now), key=lambda p: -p['earned'])
    out.append(table(['contract', 'ends in (h)', 'meter earned $', 'to $1', 'hours metered'],
        [(p['ticker'], f"{(p['end']-now).total_seconds()/3600:.1f}", f"{p['earned']:.2f}",
          'cleared' if p['earned'] >= MINIMUM_PAYOUT else f"{MINIMUM_PAYOUT-p['earned']:.2f}",
          f"{p['seconds']/3600:.1f}") for p in live[:30]]))
    return '\n'.join(out)


def load_projects(path):
    """D-161 project list (read-only); None if unreadable."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
        when = lambda value: datetime.fromisoformat(value)
        return dict(active={pid: dict(ticker=p['ticker'], until=when(p['until']), added_at=when(p['added_at']))
                            for pid, p in raw['projects'].items()},
                    closed=[dict(program_id=c['program_id'], ticker=c['ticker'], reason=c['reason'],
                                 closed_at=when(c['closed_at']), earned=Decimal(c['earned']))
                            for c in raw['closed']])
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        return None


def projects_section(projects, meter, now, *, days=7):
    """D-161: the project list, and the waste the $1 floor makes worthless."""
    out = ['## Projects: contracts we are finishing past $1 (D-161)']
    earned = {p['program_id']: p for p in meter or ()}
    if projects is None:
        out.append('Project list unavailable (starts with the D-161 project build).')
    else:
        since = now-timedelta(days=days)
        recent = [c for c in projects['closed'] if c['closed_at'] >= since]
        out.append(f"Active {len(projects['active'])}; last {days} days: "
                   f"{sum(c['reason'] == 'cleared' for c in recent)} cleared $1, "
                   f"{sum(c['reason'] != 'cleared' for c in recent)} dropped under $1.")
        rows = sorted(projects['active'].items(), key=lambda item: -(
            earned[item[0]]['earned'] if item[0] in earned else Decimal(0)))
        out.append(table(['project', 'earned $', 'to $1', 'hours left', 'hours rested'],
            [(p['ticker'], f"{earned[pid]['earned']:.2f}" if pid in earned else '0.00',
              f"{max(Decimal(0), MINIMUM_PAYOUT-(earned[pid]['earned'] if pid in earned else Decimal(0))):.2f}",
              f"{(p['until']-now).total_seconds()/3600:.1f}",
              f"{earned[pid]['seconds']/3600:.1f}" if pid in earned else '0.0') for pid, p in rows]))
    out.append('')
    out.append('## Waste: contracts that ended under $1 (paid nothing)')
    if meter is None:
        return '\n'.join(out+['Meter file unavailable.'])
    since = now-timedelta(days=days)
    wasted = [p for p in meter if since <= p['end'] <= now and Decimal(0) < p['earned'] < MINIMUM_PAYOUT]
    cleared = [p for p in meter if since <= p['end'] <= now and p['earned'] >= MINIMUM_PAYOUT]
    hours = sum((p['seconds'] for p in wasted), Decimal(0))/3600
    out.append(f"Last {days} days: {len(wasted)} contracts ended under $1 after {hours:.1f} resting hours "
               f"(${sum((p['earned'] for p in wasted), Decimal(0)):.2f} earned, paid $0); "
               f"{len(cleared)} ended past $1. Should trend to zero.")
    out.append(table(['contract', 'ended', 'earned $', 'hours rested'],
        [(p['ticker'], f"{p['end']:%m-%d %H:%M}", f"{p['earned']:.2f}", f"{p['seconds']/3600:.1f}")
         for p in sorted(wasted, key=lambda p: -p['seconds'])[:20]]))
    return '\n'.join(out)


def report(data, *, days, now, tracker=None, ledger=None, meter=None, projects=None):
    return '\n\n'.join([f'# Calibration report — {now:%Y-%m-%d} (last {days} days)',
        'Goal: improve the bot. Evidence for tuning entry gates, fill protection '
        'and reward estimates; every change remains an operator decision.',
        business_section(ledger, tracker, data, days=days, now=now),
        loss_filter_section(ledger, now), meter_section(meter, data, now),
        projects_section(projects, meter, now),
        finish_line_section(data, tracker, now),
        entries_section(data), fills_section(data), withdrawals_section(data),
        trade_evidence_section(data), sweeps_section(data), rewards_section(data, tracker, now), health_section(data)])+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--db', default=str(ROOT/'data'/'trader'/'research.db'))
    parser.add_argument('--out', default=str(ROOT/'data'/'trader'/'reports'))
    parser.add_argument('--rewards', default=str(ROOT/'data'/'trader'/'account.rewards.json'))
    parser.add_argument('--ledger', default=str(ROOT/'data'/'trader'/'account.db'))
    parser.add_argument('--meter', default=str(ROOT/'data'/'trader'/'lip_meter.json'))
    parser.add_argument('--projects', default=str(ROOT/'data'/'trader'/'projects.json'))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    text = report(load(args.db, now-timedelta(days=args.days)), days=args.days, now=now,
                  tracker=load_tracker(args.rewards), ledger=load_ledger(args.ledger),
                  meter=load_meter(args.meter), projects=load_projects(args.projects))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out/f'calibration-{now:%Y%m%d}.md').write_text(text, encoding='utf-8')
    # The Windows console code page cannot print the report's typography.
    sys.stdout.reconfigure(encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
