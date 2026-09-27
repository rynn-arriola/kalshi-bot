"""Read-only scan: which rewarded Kalshi markets would earn us the most right now.

Public data only (no account access, no orders): every active liquidity
program, each market's price bands and order book, scored with the bot's own
reward model (``RankingBoard``) at our configured size. It marks the markets
we already quote and the bot's own entry filters (downside cap, market-family
cooldown, recent big sweep), so "available" means the bot could take it.

    python -B scripts/market_scan.py [--top 30]

This is the scoring core a later ranker (D-156) builds on; it changes nothing.
"""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from kalshi_bot.books import Book, Ladder  # noqa: E402
from kalshi_bot.config import BotConfig, activate  # noqa: E402
from kalshi_bot.market_inputs import tick_bands  # noqa: E402
from kalshi_bot.quoting import parse_program  # noqa: E402
from kalshi_bot.ranking import RankingBoard  # noqa: E402
from kalshi_bot.values import InvalidData  # noqa: E402

API = 'https://api.elections.kalshi.com/trade-api/v2'
FAMILY_DAYS = 7          # D-155 family memory
SWEEP_MINUTES = 60       # D-155 sweep filter


_last = [0.0]
RATE = 0.2  # seconds between public requests (~5/s): stay well under Kalshi's limit


def get(path, tries=6):
    for attempt in range(tries):
        wait = _last[0]+RATE-time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            with urllib.request.urlopen(API+path, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == tries-1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries-1:
                raise
        time.sleep(0.5*2**attempt)


def pool_per_hour(programs, now):
    """Upper bound on our $/hour: the whole live pool rate (as if we were alone)."""
    total = Decimal(0)
    for p in programs:
        if p.start <= now < p.end:
            hours = Decimal(str((p.end-p.start).total_seconds()))/3600
            rate = Decimal(p.pool_centicents)/10000/hours
            if p.max_reward_centicents is not None:
                rate = min(rate, Decimal(p.max_reward_centicents)/10000/hours)
            total += rate
    return total


def active_programs():
    programs, cursor = {}, ''
    for _ in range(100):
        page = get('/incentive_programs?status=active&limit=1000'+(f'&cursor={cursor}' if cursor else ''))
        for row in page.get('incentive_programs', ()):
            try:
                program = parse_program(row)
            except InvalidData:
                continue  # Volume incentives and malformed rows.
            programs.setdefault(program.ticker, []).append(program)
        cursor = page.get('next_cursor') or ''
        if not cursor:
            break
    return programs


def markets_for(tickers):
    out = {}
    for i in range(0, len(tickers), 100):
        page = get('/markets?limit=1000&tickers='+','.join(tickers[i:i+100]))
        out.update({m['ticker']: m for m in page.get('markets', ())})
    return out


def book_for(ticker):
    levels = get(f'/markets/{ticker}/orderbook')['orderbook_fp']
    from kalshi_bot.full_scan import parse_book
    return parse_book(ticker, levels)  # NO bids at p become YES asks at 1 - p


def own_state(trader):
    """Markets we quote now, families that filled us, and recent sweeps (read-only)."""
    now = datetime.now(timezone.utc)
    quoted, families, swept = set(), set(), set()
    try:
        with sqlite3.connect((trader/'research.db').resolve().as_uri()+'?mode=ro', uri=True) as c:
            ended = {k for (k,) in c.execute('SELECT key FROM entry_ends')}
            for (payload,) in c.execute("SELECT payload FROM entries WHERE at >= ?",
                                        ((now-timedelta(hours=6)).isoformat(),)):
                entry = json.loads(payload)
                if any(o not in ended for o in entry.get('order_ids', ())):
                    quoted.add(entry['ticker'])
    except sqlite3.Error:
        pass
    try:
        with sqlite3.connect((trader/'account.db').resolve().as_uri()+'?mode=ro', uri=True) as c:
            since = int((now-timedelta(days=FAMILY_DAYS)).timestamp()*1_000_000)
            for (payload,) in c.execute('SELECT payload FROM fills WHERE executed_us >= ?', (since,)):
                families.add(json.loads(payload)[0].split('-', 1)[0])
    except sqlite3.Error:
        pass
    try:
        state = json.loads((trader/'sweeps.json').read_text(encoding='utf-8'))
        horizon = now.timestamp()-SWEEP_MINUTES*60
        swept = {t for t, at in state['sweeps'].items() if at > horizon}
    except (OSError, ValueError, KeyError):
        pass
    return quoted, families, swept


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--top', type=int, default=30)
    parser.add_argument('--trader', default=str(ROOT/'data'/'trader'))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    config = activate(BotConfig.load(ROOT/'config'/'bot.json'))
    now = datetime.now(timezone.utc)
    programs = {t: p for t, p in active_programs().items()
                if any(x.start <= now < x.end and not x.paid_out for x in p)}
    order = sorted(programs, key=lambda t: -pool_per_hour(programs[t], now))
    markets = markets_for(order)
    board, failures, read, scored = RankingBoard(1024), 0, 0, []
    for ticker in order:
        bound = pool_per_hour(programs[ticker], now)
        best = sorted((r.gross_hourly_usd for r in scored), reverse=True)
        if len(best) >= args.top and best[args.top-1] >= bound:
            break  # No unread market can beat the current top list.
        market = markets.get(ticker)
        if market is None or market.get('status') != 'active':
            continue
        try:
            book = book_for(ticker)
            read += 1
            if read % 250 == 0:
                print(f'progress: {read} books read, {len(scored)} scoring', file=sys.stderr, flush=True)
            if len(board.markets) >= 1024:
                board = RankingBoard(1024)
            live = tuple(p for p in programs[ticker] if p.start <= now < p.end)[:16]
            board.update(book, live, tick_bands(market['price_ranges']), now=now,
                         valid_until=now+timedelta(minutes=30), market_open=True)
            scored += [r for r in board.markets.get(ticker, ()) if r.gross_hourly_usd]
        except Exception:
            failures += 1
    quoted, families, swept = own_state(Path(args.trader))
    best_per_market = {}
    for r in scored:
        if r.ticker not in best_per_market or r.gross_hourly_usd > best_per_market[r.ticker].gross_hourly_usd:
            best_per_market[r.ticker] = r
    rows = sorted(best_per_market.values(), key=lambda r: -r.gross_hourly_usd)
    cap = config.maximum_entry_downside
    print(f'# Market scan — {now:%Y-%m-%d %H:%M} UTC ({config.entry_contracts} contracts per side)')
    print(f'{len(programs)} markets with an active liquidity program; {len(rows)} scoring for our size; '
          f'{failures} could not be read. Estimated $ per hour uses the bot\'s own model '
          '(strict estimate; payouts so far ran higher).\n')
    print('| # | market | est. $/hour | est. $ left to program end | program ends (UTC) | our bid / ask | '
          'worst loss per contract | status |')
    print('|---|---|---|---|---|---|---|---|')
    for i, row in enumerate(rows[:args.top], 1):
        quotes = {q.side: q.yes_price for q in row.quotes}
        downside = max([quotes['bid']] if 'bid' in quotes else []
                       + [1-quotes['ask']] if 'ask' in quotes else [Decimal(0)])
        reasons = []
        if row.ticker in quoted:
            status = 'ours now'
        else:
            if downside > cap:
                reasons.append('downside cap')
            if row.ticker.split('-', 1)[0] in families:
                reasons.append('family filled us <7d')
            if row.ticker in swept:
                reasons.append('swept <60 min')
            reasons += [b for b in row.blockers]
            status = 'blocked: '+', '.join(reasons) if reasons else 'available'
        print(f"| {i} | {row.ticker} | {row.gross_hourly_usd:.3f} | "
              f"{(row.gross_remaining_usd or 0):.2f} | {row.program_end:%m-%d %H:%M} | "
              f"{quotes.get('bid', '–')} / {quotes.get('ask', '–')} | {downside:.2f} | {status} |")


if __name__ == '__main__':
    main()
