"""Raw capture of Kalshi liquidity-incentive programs and their order books.

This script deliberately does NOT interpret anything. It stores the exact JSON
the venue returned, with a timestamp, and nothing else. No models, no scoring,
no eligibility, no derived columns.

That is the whole point. Every economic number we currently believe rests on
inferences that are not yet confirmed -- the `period_reward` scale, the maker
fee rate, whether our own size belongs in the denominator, how ticks are
counted at the boundary. Anything computed at capture time would bake one of
those in permanently. Raw books can be re-analysed as understanding improves;
a book we failed to record is gone.

Runs against the public API with no credentials. Kalshi's WebSocket
authenticates the connection even for public channels, so REST polling is what
can start collecting immediately.

Usage:

    python -B scripts/record_books.py --minutes 120 --markets 25 --interval 20
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


BASE = "https://api.elections.kalshi.com/trade-api/v2"

# Observed 2026-08-16: depth=200 returns HTTP 400, depth=100 is accepted.
MAX_BOOK_DEPTH = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS capture_runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    args_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS programs (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    raw_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS programs_run_time
    ON programs(run_id, fetched_at);
CREATE TABLE IF NOT EXISTS books (
    id            INTEGER PRIMARY KEY,
    run_id        TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    http_status   INTEGER,
    raw_json      TEXT
);
CREATE INDEX IF NOT EXISTS books_run_ticker_time
    ON books(run_id, market_ticker, fetched_at);
CREATE TABLE IF NOT EXISTS market_meta (
    id            INTEGER PRIMARY KEY,
    run_id        TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    raw_json      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS market_meta_run_ticker
    ON market_meta(run_id, market_ticker);
-- Failures are data too. A market that stops responding, or a rate limit we
-- tripped, changes how the surrounding books should be read.
CREATE TABLE IF NOT EXISTS errors (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    context     TEXT NOT NULL,
    detail      TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Limiter:
    """One shared request gate.

    Kalshi runs separate read/write token buckets whose refill rate is
    tier-dependent and readable from GET /account/limits -- which needs auth we
    do not have here. So this is deliberately conservative rather than tuned.
    """

    def __init__(self, requests_per_second: float):
        if not 0 < requests_per_second <= 20:
            raise ValueError("requests_per_second must be in (0, 20]")
        self._interval = 1.0 / requests_per_second
        self._next_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next_at:
            time.sleep(self._next_at - now)
            now = time.monotonic()
        self._next_at = now + self._interval


class Capture:
    def __init__(self, path: Path, limiter: Limiter):
        self.path = path
        self.limiter = limiter
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(SCHEMA)
        self.connection.commit()
        self.run_id = f"cap-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        self._pending = 0

    def start(self, args: dict) -> None:
        self.connection.execute(
            "INSERT INTO capture_runs(run_id, started_at, args_json) VALUES(?,?,?)",
            (self.run_id, utc_now(), json.dumps(args, sort_keys=True)))
        self.connection.commit()

    def finish(self) -> None:
        self.connection.execute(
            "UPDATE capture_runs SET ended_at=? WHERE run_id=?",
            (utc_now(), self.run_id))
        self.connection.commit()
        self.connection.close()

    def _flush(self, force: bool = False) -> None:
        # liquidity-bot's shadow store commits on every write -- one fsync per
        # book message. Batch instead, but keep the batch small: a crash must
        # not cost more than a few seconds of capture.
        self._pending += 1
        if force or self._pending >= 50:
            self.connection.commit()
            self._pending = 0

    def record_error(self, context: str, detail: str) -> None:
        self.connection.execute(
            "INSERT INTO errors(run_id, occurred_at, context, detail) VALUES(?,?,?,?)",
            (self.run_id, utc_now(), context, str(detail)[:2000]))
        self._flush(force=True)

    def record_programs(self, raw: list) -> None:
        stamp = utc_now()
        self.connection.executemany(
            "INSERT INTO programs(run_id, fetched_at, raw_json) VALUES(?,?,?)",
            [(self.run_id, stamp, json.dumps(row, sort_keys=True)) for row in raw])
        self._flush(force=True)

    def record_book(self, ticker: str, status: int, raw: object | None) -> None:
        self.connection.execute(
            "INSERT INTO books(run_id, market_ticker, fetched_at, http_status, raw_json)"
            " VALUES(?,?,?,?,?)",
            (self.run_id, ticker, utc_now(), status,
             None if raw is None else json.dumps(raw, sort_keys=True)))
        self._flush()

    def record_market(self, ticker: str, raw: object) -> None:
        self.connection.execute(
            "INSERT INTO market_meta(run_id, market_ticker, fetched_at, raw_json)"
            " VALUES(?,?,?,?)",
            (self.run_id, ticker, utc_now(), json.dumps(raw, sort_keys=True)))
        self._flush(force=True)

    def counts(self) -> dict:
        cursor = self.connection.execute(
            "SELECT (SELECT COUNT(*) FROM books WHERE run_id=?),"
            "       (SELECT COUNT(*) FROM programs WHERE run_id=?),"
            "       (SELECT COUNT(*) FROM market_meta WHERE run_id=?),"
            "       (SELECT COUNT(*) FROM errors WHERE run_id=?)",
            (self.run_id, self.run_id, self.run_id, self.run_id))
        books, programs, markets, errors = cursor.fetchone()
        return {"books": books, "program_rows": programs,
                "markets": markets, "errors": errors}


def get_json(limiter: Limiter, url: str, timeout: float = 30.0):
    """Return (status, parsed) and never raise for an HTTP error status."""

    limiter.wait()
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def fetch_active_programs(limiter: Limiter, capture: Capture) -> list:
    rows: list = []
    cursor = None
    for _ in range(80):
        url = (f"{BASE}/incentive_programs?status=active&type=liquidity&limit=200"
               + (f"&cursor={cursor}" if cursor else ""))
        status, payload = get_json(limiter, url)
        if status != 200 or payload is None:
            capture.record_error("fetch_programs", f"HTTP {status}")
            break
        rows.extend(payload.get("incentive_programs", []))
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return rows


def rank(rows: list, limit: int, max_per_series: int = 3) -> list[str]:
    """Rank by reward per unit of target size, capped per series.

    This is the ONE piece of interpretation in the script, and it only decides
    what to look at -- never what to store. `period_reward`'s unit is
    undocumented, but ranking is scale-invariant, so an unconfirmed scale
    cannot corrupt the ordering. Target size is the denominator we compete
    against, so reward/target is the natural density.

    The per-series cap exists because the first live run took the top 30 and
    got 29 markets from `KXTRUMPENDORSEMENTS` -- one event, many strikes,
    all sharing a reward schedule. That is a sample of one thing, and the
    question this capture has to answer is what the *universe* looks like.
    A series is the ticker's first hyphen-delimited segment, which is how
    Kalshi groups a schedule.

    Ties and unparseable rows sort last rather than raising: a malformed row
    should cost us one candidate, not the run.
    """

    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for row in rows:
        ticker = str(row.get("market_ticker") or "").strip()
        if not ticker or ticker in seen:
            continue
        try:
            target = float(row["target_size_fp"])
            reward = float(row["period_reward"])
        except (KeyError, TypeError, ValueError):
            continue
        if target <= 0:
            continue
        seen.add(ticker)
        scored.append((reward / target, ticker))
    scored.sort(key=lambda item: -item[0])

    picked: list[str] = []
    per_series: dict[str, int] = {}
    # Two passes: fill the diversified quota first, then top up from the
    # leftovers if the universe is too narrow to fill `limit` under the cap.
    # Running short on breadth is not a reason to poll fewer markets.
    for _, ticker in scored:
        series = ticker.split("-")[0]
        if per_series.get(series, 0) >= max_per_series:
            continue
        per_series[series] = per_series.get(series, 0) + 1
        picked.append(ticker)
        if len(picked) >= limit:
            return picked
    for _, ticker in scored:
        if ticker not in picked:
            picked.append(ticker)
            if len(picked) >= limit:
                break
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/capture.db")
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument("--markets", type=int, default=25,
                        help="how many top-ranked markets to poll")
    parser.add_argument("--interval", type=float, default=20.0,
                        help="seconds between book sweeps")
    parser.add_argument("--program-refresh-minutes", type=float, default=15.0)
    parser.add_argument("--rps", type=float, default=4.0,
                        help="shared request rate; conservative by default")
    args = parser.parse_args()

    if args.markets <= 0 or args.interval <= 0 or args.minutes <= 0:
        parser.error("markets, interval and minutes must be positive")

    limiter = Limiter(args.rps)
    capture = Capture(Path(args.database), limiter)
    capture.start(vars(args))
    print(f"run_id={capture.run_id}  database={args.database}")

    deadline = time.monotonic() + args.minutes * 60.0
    next_programs = 0.0
    tickers: list[str] = []
    known_meta: set[str] = set()

    try:
        while time.monotonic() < deadline:
            sweep_started = time.monotonic()

            if sweep_started >= next_programs:
                rows = fetch_active_programs(limiter, capture)
                if rows:
                    capture.record_programs(rows)
                    tickers = rank(rows, args.markets)
                    print(f"[{utc_now()}] programs={len(rows)} tracking={len(tickers)}")
                next_programs = sweep_started + args.program_refresh_minutes * 60.0

            for ticker in tickers:
                if ticker not in known_meta:
                    status, payload = get_json(limiter, f"{BASE}/markets/{ticker}")
                    if status == 200 and payload is not None:
                        capture.record_market(ticker, payload)
                        known_meta.add(ticker)
                    else:
                        capture.record_error("fetch_market", f"{ticker} HTTP {status}")
                status, payload = get_json(
                    limiter, f"{BASE}/markets/{ticker}/orderbook?depth={MAX_BOOK_DEPTH}")
                capture.record_book(ticker, status, payload)
                if status != 200:
                    capture.record_error("fetch_book", f"{ticker} HTTP {status}")
                if time.monotonic() >= deadline:
                    break

            elapsed = time.monotonic() - sweep_started
            if elapsed < args.interval:
                time.sleep(args.interval - elapsed)
            else:
                # The sweep itself outran the interval. That is not an error --
                # the rate limiter is doing its job -- but it means the real
                # sample spacing is the sweep length, and analysis must read
                # the timestamps rather than assume the configured interval.
                capture.record_error(
                    "sweep_overrun",
                    f"{elapsed:.1f}s for {len(tickers)} markets"
                    f" exceeds interval {args.interval}s")
    except KeyboardInterrupt:
        print("\ninterrupted; closing cleanly")
    finally:
        capture._flush(force=True)
        summary = capture.counts()
        capture.finish()
        print(json.dumps({"run_id": capture.run_id, **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
