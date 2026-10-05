#!/usr/bin/env python3
"""D-175 Endgame Trader for Kalshi: buy the near-certain favourite when a game
is almost over and hold it to settlement. Rules: src/kalshi_bot/endgame.py;
settings: config/endgame_policy.json (re-read every poll).

    python -B scripts/endgame_trader.py run [--minutes N]
    python -B scripts/endgame_trader.py status

DRY RUN ONLY (paper trades; nothing is ever sent to Kalshi). This build has no
order code: live_orders true is refused and it stays on paper. Operator
2026-10-03: "lets start testing this", "open as much position we can handle to
get all data", "Then 90-99c", "We can decide anyways what is measure for live".

- Paper trades have no open-position cap; one 'rule' trade (middle >= 95c,
  esports 97c) and one 'data' trade (middle 90c up to the rule) per event.
- A paper fill needs the whole size (30 contracts at $30 on the 99c cap) on
  the book at <= 99c; it fills at the walked average price.
- The daily stop ($90, settled 'rule' trades per New York day) is reported as
  "would stop" and does not end the data run.
- Kill switch: create data/endgame/STOP. One instance only (file lock).
- Public market data only; no credentials are read.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from kalshi_bot.endgame import (  # noqa: E402
    almost_over, book_market, contracts_for, daily_stop_hit, fill_from_book, game_text, load_policy,
    maps_to_win, pick_entry, price_bucket, realized_result, rule_events, taker_fee, tennis_progress)

BASE = 'https://external-api.kalshi.com/trade-api/v2'
POLICY = ROOT/'config'/'endgame_policy.json'
OUT = ROOT/'data'/'endgame'
DB = OUT/'endgame.db'
STOP_FILE = OUT/'STOP'
LOCK_FILE = OUT/'endgame.lock'
HEARTBEAT = OUT/'heartbeat'      # UTC time of the last finished poll (read by endgame_watch.py)
LAST_OK = OUT/'last_ok'
STARTED = OUT/'started_at'       # UTC start time of this process (a change = a restart, for the watcher)          # UTC time of the last poll that read Kalshi without an error
ET = ZoneInfo('America/New_York')
LOOKBACK_HOURS = 24                # Polymarket 10-03: long games and extra innings
MILESTONE_REFRESH = 300
THIN_RECHECK_SECONDS = 60
SETTLE_RETRY_MINUTES = 5
SETTLES_PER_CYCLE = 10
BATCH = 100
FINISHED = frozenset({'closed', 'finished', 'complete', 'ended', 'cancelled', 'canceled', 'postponed'})

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY, mode TEXT NOT NULL, band TEXT NOT NULL, sport TEXT NOT NULL,
  experimental INTEGER NOT NULL, milestone_id TEXT NOT NULL, event_ticker TEXT NOT NULL,
  ticker TEXT NOT NULL, team TEXT, bid TEXT, ask TEXT, mid TEXT, price TEXT NOT NULL,
  qty INTEGER NOT NULL, fee TEXT NOT NULL, created_at TEXT NOT NULL, game_state TEXT,
  outcome TEXT, settled_at TEXT, result TEXT, next_settle_at TEXT,
  UNIQUE(mode, event_ticker, band));
CREATE TABLE IF NOT EXISTS games(
  milestone_id TEXT PRIMARY KEY, type TEXT, title TEXT, start_date TEXT, event_tickers TEXT);
CREATE TABLE IF NOT EXISTS snapshots(
  milestone_id TEXT NOT NULL, at TEXT NOT NULL, state TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_snapshots_game ON snapshots(milestone_id, at);
"""
# Recorder (operator 10-03 "Ok apply it"): score/clock history of every live
# game, so lead rules (basketball 7+, soccer 2 goals) can be tested against
# Kalshi's minute price history later. Prices are not recorded here.
SNAPSHOT_SECONDS = 60
# D-177 stale feed (Polymarket 2026-10-04: events stuck "live" for hours): no buy
# when a game's live data has not changed for STALE_MINUTES (esports excluded:
# its state only changes between maps).
STALE_MINUTES = 15
SNAPSHOT_KEEP_DAYS = 21
CLOCK_KEYS = ('time', 'clock', 'period_remaining_time')


def now_utc():
    return datetime.now(timezone.utc)


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def log(msg):
    print(f'[endgame] {now_utc().isoformat(timespec="seconds")} {msg}', flush=True)


def get(path, params=None, timeout=15):
    """Public GET; repeated keys are passed as a list of pairs."""
    url = BASE+path+('?'+urllib.parse.urlencode(params, doseq=True) if params else '')
    request = urllib.request.Request(url, headers={'Accept': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 2:
                raise
            time.sleep(2*(attempt+1))
    raise RuntimeError('unreachable')


def open_db(path=DB):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript(SCHEMA)
    # D-176: NO-side paper trades (soccer NO on the trailer).
    if 'side' not in {r[1] for r in db.execute('PRAGMA table_info(trades)')}:
        db.execute("ALTER TABLE trades ADD COLUMN side TEXT NOT NULL DEFAULT 'yes'")
    return db


def lock_single_instance():
    """Hold an exclusive lock on LOCK_FILE for the process lifetime."""
    OUT.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_FILE, 'a+')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('another endgame trader is already running')
    return handle


def realized_today(db, mode):
    start = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    rows = db.execute("SELECT result FROM trades WHERE mode=? AND band='rule' AND settled_at>=?",
                      (mode, iso(start))).fetchall()
    return sum((Decimal(r['result']) for r in rows), Decimal(0))


class Trader:
    def __init__(self, db, fetch=get):
        self.db, self.get = db, fetch
        self.policy = load_policy(POLICY)
        self.mode = 'dry'
        self.milestones = {}               # id -> milestone (sports we have rules for)
        self.finished = set()
        self.milestones_at = None
        self.uncovered = {}                # started milestone types with no rule (status log)
        self.thin_until = {}
        self.fee_multipliers = {}
        self.formats = {}                  # milestone id -> esports maps to win (None = unknown)
        self.qualified = {}                # (sport, event) -> first time the entry qualified (hold_seconds)
        self.state_seen = {}               # milestone id -> (full live state, first time seen unchanged)
        self.progress = {}                 # tennis milestone id -> last (sets played, current games)
        self.reversed = set()              # tennis milestones whose score went backwards: never traded
        self.counts = dict(polls=0, almost_over=0, candidates=0, thin=0, trades=0, settled=0, errors=0,
                           snapshots=0)
        self.snapped = {}                  # milestone id -> (time, score key) of its last snapshot
        self.pruned_at = None

    # -- discovery --
    def refresh_milestones(self, now):
        types = {t for rule in self.policy.rules.values() for t in rule.types}
        found, cursor, uncovered = {}, None, {}
        for _ in range(40):
            params = {'minimum_start_date': iso(now-timedelta(hours=LOOKBACK_HOURS)), 'limit': 500}
            if cursor:
                params['cursor'] = cursor
            page = self.get('/milestones', params)
            for m in page.get('milestones') or []:
                if not isinstance(m, dict) or str(m.get('start_date') or '9') > iso(now+timedelta(minutes=2)):
                    continue
                if m.get('type') in types and m.get('id'):
                    found[m['id']] = m
                elif m.get('category') in ('Sports', 'Esports'):
                    # Shown in the status line so a sport Kalshi names differently
                    # (NHL is 'hockey_match') cannot be missed silently.
                    uncovered[m.get('type')] = uncovered.get(m.get('type'), 0)+1
            cursor = page.get('cursor')
            if not cursor:
                break
        self.milestones = {k: v for k, v in found.items() if k not in self.finished}
        self.milestones_at, self.uncovered = now, uncovered

    def live_details(self):
        ids, out = list(self.milestones), {}
        for i in range(0, len(ids), BATCH):
            page = self.get('/live_data/batch', [('milestone_ids', x) for x in ids[i:i+BATCH]])
            for row in page.get('live_datas') or []:
                if isinstance(row, dict) and isinstance(row.get('details'), dict):
                    out[row.get('milestone_id')] = row['details']
        return out

    def fee_multiplier(self, ticker):
        series = ticker.split('-')[0]
        if series not in self.fee_multipliers:
            try:
                value = Decimal(str(self.get(f'/series/{series}')['series'].get('fee_multiplier', 1)))
                self.fee_multipliers[series] = value if value.is_finite() and 0 <= value <= 2 else Decimal(1)
            except Exception:
                return Decimal(1)
        return self.fee_multipliers[series]

    # -- trading --
    def recorded_bands(self, event_ticker):
        return {r[0] for r in self.db.execute('SELECT band FROM trades WHERE mode=? AND event_ticker=?',
                                               (self.mode, event_ticker))}

    def maps_format(self, milestone):
        """Esports maps to win from the milestone's total-maps market (cached)."""
        mid = milestone['id']
        if mid not in self.formats:
            units = None
            for ticker in milestone.get('related_event_tickers') or milestone.get('primary_event_tickers') or ():
                if 'TOTALMAPS' in str(ticker).upper():
                    event = self.get(f'/events/{ticker}', {'with_nested_markets': 'true'})
                    units = maps_to_win((event.get('event') or {}).get('markets') or event.get('markets'))
                    break
            self.formats[mid] = units
        return self.formats[mid]

    def stale(self, milestone, details, now):
        """True when this game's live data has not changed for STALE_MINUTES."""
        text = json.dumps(details, sort_keys=True, default=str)
        seen = self.state_seen.get(milestone['id'])
        if seen is None or seen[0] != text:
            self.state_seen[milestone['id']] = (text, now)
            return False
        return (now-seen[1]).total_seconds() >= STALE_MINUTES*60

    def score_reversed(self, milestone, details):
        """D-179 (Polymarket tennis research 2): a tennis match whose score ever
        goes backwards (a feed glitch, 2.3% of events) is never traded."""
        if not str(milestone.get('type', '')).startswith('tennis'):
            return False
        mid, now_progress = milestone['id'], tennis_progress(details)
        if now_progress is not None:
            last = self.progress.get(mid)
            if last is not None and now_progress < last and mid not in self.reversed:
                self.reversed.add(mid)
                log(f'score went backwards milestone={mid} {last} -> {now_progress}: not traded')
            self.progress[mid] = now_progress
        return mid in self.reversed

    def consider(self, milestone, details, now):
        meta = milestone.get('details') if isinstance(milestone.get('details'), dict) else {}
        if self.score_reversed(milestone, details):
            return
        stale = self.stale(milestone, details, now)
        for sport, rule in self.policy.rules_for(milestone.get('type')):
            if stale and rule.kind != 'maps':
                if details.get('widget_status') == 'live':   # count live games only
                    self.counts['stale_feed'] = self.counts.get('stale_feed', 0)+1
                continue
            units = self.maps_format(milestone) if rule.require_format else None
            if almost_over(rule, milestone['type'], details, meta=meta, units_to_win=units):
                self.counts['almost_over'] += 1
                self.consider_rule(sport, rule, milestone, details, now)
            else:
                for key in [k for k in self.qualified if k[0] == sport and k[2] == milestone['id']]:
                    self.qualified.pop(key, None)

    def consider_rule(self, sport, rule, milestone, details, now):
        meta = milestone.get('details') if isinstance(milestone.get('details'), dict) else {}
        for event_ticker in rule_events(rule, milestone.get('primary_event_tickers')):
            if 'rule' in self.recorded_bands(event_ticker):
                continue                     # traded at the rule: nothing more to learn here
            if self.thin_until.get(event_ticker, now) > now:
                continue
            event = self.get(f'/events/{event_ticker}', {'with_nested_markets': 'true'})
            markets = (event.get('event') or {}).get('markets') or event.get('markets') or []
            cand = pick_entry(event_ticker, markets, self.policy, rule, data_band=self.mode == 'dry', now=now)
            key = (sport, event_ticker, milestone['id'])
            if cand is None:
                self.qualified.pop(key, None)
                continue
            if cand.band in self.recorded_bands(event_ticker):
                continue
            if rule.hold_seconds:
                # Polymarket strict esports rule: the entry must qualify on every
                # poll for hold_seconds (a ~30 s 95/99c spike bought FORZE at 99c).
                first = self.qualified.setdefault(key, now)
                if (now-first).total_seconds() < rule.hold_seconds:
                    continue
            self.counts['candidates'] += 1
            qty = contracts_for(self.policy.risk_per_trade_usd, self.policy.max_price)
            book = self.get(f'/markets/{cand.ticker}/orderbook').get('orderbook_fp') or {}
            # D-176: re-check the trigger on the live book we fill from (the event
            # listing lagged: two 'rule' trades filled at 87c and 94c).
            source = next((m for m in markets if isinstance(m, dict) and m.get('ticker') == cand.ticker), {})
            live = pick_entry(event_ticker, [book_market(cand.ticker, cand.team, book,
                                                         expected_expiration_time=source.get('expected_expiration_time'))]
                              + ([m for m in markets if isinstance(m, dict) and m.get('ticker') != cand.ticker]
                                 if rule.side == 'no_trailer' else []),
                              self.policy, rule, data_band=self.mode == 'dry', now=now)
            if live is None or live.ticker != cand.ticker or live.band in self.recorded_bands(event_ticker):
                self.counts['stale'] = self.counts.get('stale', 0)+1
                log(f'skip stale quote {cand.ticker} band={cand.band} listing mid={cand.mid} book={live and live.mid}')
                continue
            cand = live
            # YES fills walk the YES asks (1 - NO bids); NO fills walk the NO asks (1 - YES bids).
            levels = book.get('no_dollars') if cand.side == 'yes' else book.get('yes_dollars')
            filled, avg = fill_from_book(levels, qty, self.policy.max_price)
            if not filled:
                self.counts['thin'] += 1
                self.thin_until[event_ticker] = now+timedelta(seconds=THIN_RECHECK_SECONDS)
                log(f'skip thin book {cand.ticker} band={cand.band} mid={cand.mid} need={qty}')
                continue
            fee = taker_fee(filled, avg, self.fee_multiplier(cand.ticker))
            with self.db:
                self.db.execute(
                    'INSERT OR IGNORE INTO trades(mode,band,sport,experimental,milestone_id,event_ticker,ticker,'
                    'team,bid,ask,mid,price,qty,fee,created_at,game_state,side) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (self.mode, cand.band, sport, int(rule.experimental), milestone['id'], event_ticker,
                     cand.ticker, cand.team, str(cand.bid), str(cand.ask), str(cand.mid),
                     str(round(avg, 4)), filled, str(fee), iso(now), game_text(milestone['type'], details, meta),
                     cand.side))
            self.qualified.pop(key, None)
            self.counts['trades'] += 1
            log(f'PAPER BUY {cand.side.upper()} {cand.ticker} ({cand.team}) sport={sport} band={cand.band} mid={cand.mid} '
                f'ask={cand.ask} fill={round(avg, 4)} qty={filled} fee={fee} game={game_text(milestone["type"], details, meta)}')

    def settle(self, now):
        rows = self.db.execute(
            'SELECT * FROM trades WHERE mode=? AND settled_at IS NULL AND (next_settle_at IS NULL OR next_settle_at<=?) '
            'ORDER BY id LIMIT ?', (self.mode, iso(now), SETTLES_PER_CYCLE)).fetchall()
        for r in rows:
            try:
                market = self.get(f'/markets/{r["ticker"]}').get('market') or {}
            except Exception:
                market = {}
            outcome = market.get('result')
            if outcome not in ('yes', 'no'):
                with self.db:
                    self.db.execute('UPDATE trades SET next_settle_at=? WHERE id=?',
                                    (iso(now+timedelta(minutes=SETTLE_RETRY_MINUTES)), r['id']))
                continue
            result = realized_result(outcome == (r['side'] or 'yes'), r['qty'], Decimal(r['price']), Decimal(r['fee']))
            with self.db:
                self.db.execute('UPDATE trades SET outcome=?, settled_at=?, result=? WHERE id=?',
                                (outcome, iso(now), str(result), r['id']))
            self.counts['settled'] += 1
            log(f'SETTLED {r["ticker"]} band={r["band"]} sport={r["sport"]} price={r["price"]} '
                f'outcome={outcome} result={result:+.2f}')

    def record(self, details, now):
        """One snapshot per live game per SNAPSHOT_SECONDS, plus one whenever
        its score changes; old snapshots are pruned once an hour."""
        rows, games = [], []
        for mid, d in details.items():
            milestone = self.milestones.get(mid)
            if milestone is None or d.get('widget_status') != 'live':
                continue
            state = json.loads(game_text(milestone['type'], d, milestone.get('details')))
            key = json.dumps({k: v for k, v in state.items() if k not in CLOCK_KEYS}, sort_keys=True)
            last = self.snapped.get(mid)
            if last is not None and last[1] == key and (now-last[0]).total_seconds() < SNAPSHOT_SECONDS:
                continue
            if last is None:
                games.append((mid, milestone['type'], milestone.get('title'), milestone.get('start_date'),
                              json.dumps(milestone.get('primary_event_tickers') or [])))
            rows.append((mid, iso(now), json.dumps(state, separators=(',', ':'))))
            self.snapped[mid] = (now, key)
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO games VALUES(?,?,?,?,?)', games)
            self.db.executemany('INSERT INTO snapshots VALUES(?,?,?)', rows)
            if self.pruned_at is None or (now-self.pruned_at).total_seconds() >= 3600:
                self.db.execute('DELETE FROM snapshots WHERE at<?', (iso(now-timedelta(days=SNAPSHOT_KEEP_DAYS)),))
                self.pruned_at = now
        self.counts['snapshots'] += len(rows)

    def cycle(self, now):
        fresh = load_policy(POLICY)
        if fresh != self.policy:
            log('policy reloaded')
        self.policy = fresh
        if fresh.live_orders:
            log('live_orders is true but this build has no order code; staying on paper')
        if not fresh.enabled or STOP_FILE.exists():
            return 'disabled' if not fresh.enabled else 'stop_file'
        if self.milestones_at is None or (now-self.milestones_at).total_seconds() >= MILESTONE_REFRESH:
            self.refresh_milestones(now)
        details = self.live_details()
        self.counts['polls'] += 1
        for mid, d in details.items():
            if d.get('status') in FINISHED:
                self.finished.add(mid)
                self.milestones.pop(mid, None)
        try:
            self.record(details, now)
        except (sqlite3.Error, ValueError, TypeError) as exc:
            log(f'recorder error {type(exc).__name__}: {str(exc)[:160]}')
        self.settle(now)
        for mid, d in details.items():
            milestone = self.milestones.get(mid)
            if milestone is not None:
                try:
                    self.consider(milestone, d, now)
                except Exception as exc:
                    self.counts['errors'] += 1
                    log(f'error milestone={mid} {type(exc).__name__}: {str(exc)[:160]}')
        return None

    def run(self, minutes=None):
        stop_at = now_utc()+timedelta(minutes=minutes) if minutes else None
        next_status = now_utc()
        try:
            STARTED.write_text(iso(now_utc()), encoding='utf-8')
        except OSError:
            pass
        log(f'start mode={self.mode} band={self.policy.data_min_price}/{self.policy.min_price}-{self.policy.max_price} '
            f'risk=${self.policy.risk_per_trade_usd} rules={sorted(self.policy.rules)}')
        while stop_at is None or now_utc() < stop_at:
            started = time.monotonic()
            idle = None
            try:
                idle = self.cycle(now_utc())
                try:
                    LAST_OK.write_text(iso(now_utc()), encoding='utf-8')
                except OSError:
                    pass
            except Exception as exc:
                self.counts['errors'] += 1
                log(f'error {type(exc).__name__}: {str(exc)[:200]}')
            try:
                HEARTBEAT.write_text(iso(now_utc()), encoding='utf-8')
            except OSError:
                pass
            if now_utc() >= next_status:
                next_status = now_utc()+timedelta(minutes=15)
                today = realized_today(self.db, self.mode)
                stop = ' WOULD_STOP' if daily_stop_hit(today, self.policy) else ''
                open_rows = self.db.execute('SELECT COUNT(*) FROM trades WHERE mode=? AND settled_at IS NULL',
                                            (self.mode,)).fetchone()[0]
                log(f'status idle={idle} watching={len(self.milestones)} open={open_rows} '
                    f'rule_today=${today:+.2f}{stop} counts={self.counts} not_covered={self.uncovered}')
            time.sleep(max(1.0, self.policy.poll_seconds-(time.monotonic()-started)))
        return 0


def report(db, mode='dry', since=None):
    rows = db.execute('SELECT * FROM trades WHERE mode=? AND created_at>=? ORDER BY id',
                      (mode, since or '')).fetchall()
    lines = [f'{mode}{" since "+since if since else ""}: trades={len(rows)} open={sum(r["settled_at"] is None for r in rows)}'
             f' rule_today=${realized_today(db, mode):+.2f}']

    def table(title, key):
        groups = {}
        for r in rows:
            groups.setdefault(key(r), []).append(r)
        lines.append(f'  {title}:')
        for name in sorted(groups):
            g = groups[name]
            done = [r for r in g if r['result'] is not None]
            won = sum(Decimal(r['result']) > 0 for r in done)
            pnl = sum((Decimal(r['result']) for r in done), Decimal(0))
            rate = f'{100*won/len(done):.1f}%' if done else '-'
            lines.append(f'    {name:28} trades={len(g):4} settled={len(done):4} won={won:4} '
                         f'win={rate:>6} result=${pnl:+.2f}')
    table('by band', lambda r: r['band'])
    table('by band/sport', lambda r: f'{r["band"]}/{r["sport"]}{"*" if r["experimental"] else ""}')
    table('by band/price', lambda r: f'{r["band"]}/{price_bucket(r["price"])}')
    lines.append('  last 10:')
    for r in rows[-10:]:
        result = '' if r['result'] is None else f'{Decimal(r["result"]):+.2f}'
        lines.append(f'    {r["created_at"][5:16]} {r["band"]:4} {r["sport"]:12} {r["ticker"][:42]:42} '
                     f'@{r["price"]} x{r["qty"]} {result}')
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('command', choices=('run', 'status'))
    p.add_argument('--minutes', type=float, default=None)
    p.add_argument('--since', default=None, help='status: only trades created at/after this UTC time')
    a = p.parse_args(argv)
    if a.command == 'status':
        print(report(open_db(), since=a.since))
        return 0
    handle = lock_single_instance()
    try:
        return Trader(open_db()).run(a.minutes)
    finally:
        handle.close()


if __name__ == '__main__':
    raise SystemExit(main())
