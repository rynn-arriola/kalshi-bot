#!/usr/bin/env python3
"""D-175 watcher: keep the Endgame Trader running and tell the operator on
ntfy when it stops, restarts or starts. Operator 2026-10-03: "I have ntfy, i
want you to update me if bot stop or started", "Pc wont ever restart so what i
want this should recover when bot stopped". Run every minute by the Windows
task "KalshiEndgameWatch".

    python -B scripts/endgame_watch.py          one check (the task runs this)
    python -B scripts/endgame_watch.py --test   send a test message

Up = the trader's heartbeat (written every poll, ~10 s) is under STALE_SECONDS
old. When down: any stuck trader process is ended (exact command line) and a
new one started, at most MAX_RESTARTS per hour and not within RESTART_GAP of
the last try; past the limit it alerts once and waits. Never restarts while
data/endgame/STOP exists (the operator's off switch). Messages go out only on
changes. The ntfy topic URL (it acts as a password) is read from
data/endgame/ntfy_url.txt, never committed and never printed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data'/'endgame'
HEARTBEAT = OUT/'heartbeat'
STATE = OUT/'watch_state.json'
URL_FILE = OUT/'ntfy_url.txt'
STOP_FILE = OUT/'STOP'
LOG = OUT/'endgame.log'
STALE_SECONDS = 120
RESTART_GAP = timedelta(minutes=3)
MAX_RESTARTS = 5                 # per rolling hour
TRADER_MARK = 'scripts\\endgame_trader.py run'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def heartbeat_age(now, path=HEARTBEAT):
    try:
        beat = datetime.fromisoformat(path.read_text(encoding='utf-8').strip().replace('Z', '+00:00'))
    except (OSError, ValueError):
        return None
    return (now-beat).total_seconds()


def plan(previous, age, stop_file, now):
    """(new state, messages [(kind, text)], restart?) from the saved state.

    The first run ever records the state silently and acts from the next."""
    previous = previous or {}
    up = age is not None and age < STALE_SECONDS
    restarts = [t for t in previous.get('restarts', [])
                if now-datetime.fromisoformat(t) < timedelta(hours=1)]
    state = dict(state='up' if up else 'down', at=now.isoformat(timespec='seconds'),
                 restarts=restarts, gave_up=bool(previous.get('gave_up')) and not up)
    was = previous.get('state')
    messages = []
    if up:
        if was == 'down':
            again = (f' (after {len(restarts)} automatic restart{"s" * (len(restarts) != 1)})'
                     if restarts else '')
            messages.append(('started', f'Kalshi Endgame Trader STARTED{again}. Paper mode, watching live games.'))
        return state, messages, False
    if was is None:
        return state, messages, False
    if stop_file:
        if was == 'up':
            messages.append(('stopped', 'Kalshi Endgame Trader STOPPED. STOP file present, so no automatic restart.'))
        return state, messages, False
    why = 'no heartbeat' if age is None else f'last poll {int(age//60)} min ago'
    if was == 'up':
        messages.append(('stopped', f'Kalshi Endgame Trader STOPPED ({why}). Restarting automatically.'))
    if len(restarts) >= MAX_RESTARTS:
        if not state['gave_up']:
            state['gave_up'] = True
            messages.append(('stuck', f'Kalshi Endgame Trader still DOWN after {MAX_RESTARTS} restarts in an hour '
                                      f'({why}). Auto-restart paused until the hour passes; needs a look.'))
        return state, messages, False
    last = datetime.fromisoformat(restarts[-1]) if restarts else None
    if last is not None and now-last < RESTART_GAP:
        return state, messages, False
    state['restarts'] = restarts+[now.isoformat(timespec='seconds')]
    return state, messages, True


def trader_pids():
    """PIDs of running trader processes, matched on the exact script and command."""
    query = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like "
             f"'*{TRADER_MARK}*' }} | ForEach-Object {{ $_.ProcessId }}")
    out = subprocess.run(['powershell', '-NoProfile', '-Command', query], capture_output=True, text=True,
                         timeout=60, creationflags=NO_WINDOW).stdout
    return [int(x) for x in out.split() if x.isdigit()]


def restart_trader():
    for pid in trader_pids():                  # a hung trader still holds the single-instance lock
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True, timeout=30,
                       creationflags=NO_WINDOW)
    python = ROOT/'.venv'/'Scripts'/'python.exe'
    flags = (getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
             | NO_WINDOW)
    with open(LOG, 'a', encoding='utf-8') as log:
        subprocess.Popen([str(python), '-B', '-u', str(ROOT/'scripts'/'endgame_trader.py'), 'run'], cwd=ROOT,
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)


def send(url, title, message, priority='default', tags=''):
    request = urllib.request.Request(url, data=message.encode('utf-8'), method='POST',
                                     headers={'Title': title, 'Priority': priority, 'Tags': tags})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status


STYLE = {'started': ('default', 'green_circle'), 'stopped': ('high', 'rotating_light'),
         'stuck': ('urgent', 'sos')}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--test', action='store_true')
    a = p.parse_args(argv)
    try:
        url = URL_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        url = ''
    if a.test:
        if not url.startswith('https://'):
            print('no ntfy address in data/endgame/ntfy_url.txt', file=sys.stderr)
            return 2
        send(url, 'Kalshi bot', 'Test: Kalshi Endgame Trader alerts are set up.', tags='white_check_mark')
        return 0
    now = datetime.now(timezone.utc)
    try:
        previous = json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = None
    state, messages, restart = plan(previous, heartbeat_age(now), STOP_FILE.exists(), now)
    STATE.write_text(json.dumps(state), encoding='utf-8')
    if restart:
        restart_trader()                       # recovery never waits on the alert
    for kind, text in messages:
        if url.startswith('https://'):
            priority, tags = STYLE[kind]
            try:
                send(url, f'Kalshi bot {kind}', text, priority=priority, tags=tags)
            except OSError:
                pass                           # alerts are best effort; recovery already ran
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
