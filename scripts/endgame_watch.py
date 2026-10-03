#!/usr/bin/env python3
"""D-175 watcher: tell the operator on ntfy when the Endgame Trader stops or
starts (operator 2026-10-03: "I have ntfy, i want you to update me if bot stop
or started"). Run every minute by the Windows task "KalshiEndgameWatch".

    python -B scripts/endgame_watch.py          one check (the task runs this)
    python -B scripts/endgame_watch.py --test   send a test message

Up = the trader's heartbeat (written every poll, ~10 s) is under STALE_SECONDS
old. A message is sent only when up/down changes. The ntfy address (a topic
URL such as https://ntfy.sh/<topic>; it acts as a password) is read from
data/endgame/ntfy_url.txt, which is never committed and never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data'/'endgame'
HEARTBEAT = OUT/'heartbeat'
STATE = OUT/'watch_state.json'
URL_FILE = OUT/'ntfy_url.txt'
STOP_FILE = OUT/'STOP'
STALE_SECONDS = 120


def heartbeat_age(now, path=HEARTBEAT):
    try:
        beat = datetime.fromisoformat(path.read_text(encoding='utf-8').strip().replace('Z', '+00:00'))
    except (OSError, ValueError):
        return None
    return (now-beat).total_seconds()


def decide(previous, age, stop_file):
    """(new state, message or None). First run records the state silently."""
    state = 'up' if age is not None and age < STALE_SECONDS else 'down'
    if previous is None or previous == state:
        return state, None
    if state == 'up':
        return state, ('started', 'Kalshi Endgame Trader STARTED (paper mode). Watching live games again.')
    why = 'STOP file present' if stop_file else (
        'no heartbeat' if age is None else f'last poll {int(age//60)} min ago')
    return state, ('stopped', f'Kalshi Endgame Trader STOPPED ({why}). It will not trade until restarted.')


def send(url, title, message, priority='default', tags=''):
    request = urllib.request.Request(url, data=message.encode('utf-8'), method='POST',
                                     headers={'Title': title, 'Priority': priority, 'Tags': tags})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--test', action='store_true')
    a = p.parse_args(argv)
    try:
        url = URL_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        print('no ntfy address: put the topic URL in data/endgame/ntfy_url.txt', file=sys.stderr)
        return 2
    if not url.startswith('https://'):
        print('ntfy address must start with https://', file=sys.stderr)
        return 2
    if a.test:
        send(url, 'Kalshi bot', 'Test: Kalshi Endgame Trader alerts are set up.', tags='white_check_mark')
        return 0
    now = datetime.now(timezone.utc)
    try:
        previous = json.loads(STATE.read_text(encoding='utf-8')).get('state')
    except (OSError, ValueError):
        previous = None
    state, message = decide(previous, heartbeat_age(now), STOP_FILE.exists())
    if message is not None:
        kind, text = message
        send(url, f'Kalshi bot {kind}', text, priority='high' if kind == 'stopped' else 'default',
             tags='rotating_light' if kind == 'stopped' else 'green_circle')
    # Saved only after a successful send, so a failed send is retried next minute.
    STATE.write_text(json.dumps(dict(state=state, at=now.isoformat(timespec='seconds'))), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
