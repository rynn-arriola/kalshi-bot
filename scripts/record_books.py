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
-- Trades carry `taker_book_side`, which names the side that was RESTING when
-- the trade happened -- the maker side. That is the only observable signal of
-- whether a resting order would have been filled, so without it no fill rate
-- and no markout can be reconstructed afterwards.
--
-- `trade_id` is the venue's own identifier and is the dedupe key: sweeps
-- overlap deliberately (we re-ask from a little before the last seen trade),
-- because asking only for strictly-newer trades loses anything that landed
-- between the query and the response.
CREATE TABLE IF NOT EXISTS trades (
    trade_id      TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    created_time  TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    raw_json      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trades_ticker_time
    ON trades(market_ticker, created_time);
-- The reward rules only count a snapshot "if the market is open for trading".
-- Without this, a closed-market gap reads as a period of zero liquidity and
-- corrupts the two-sided rate.
CREATE TABLE IF NOT EXISTS exchange_status (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    raw_json    TEXT NOT NULL
);
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


def still_open(end_date: str | None) -> bool:
    """Is this program's end_date in the future?

    Parsed rather than string-compared. `end_date` arrives as '...Z' while
    `utc_now()` renders '+00:00', so a lexicographic test only works by
    accident of where the two formats first differ -- and would invert
    silently if either format ever changed. An unparseable or missing date
    returns False so the ticker is re-ranked normally rather than pinned
    forever by a bad value.
    """

    if not end_date:
        return False
    try:
        return datetime.fromisoformat(
            str(end_date).replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False


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
        # Last stored JSON per program, so only changes are written.
        self._program_state: dict[str, str] = {}

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
        """Store program rows, but only when one has actually changed.

        Three poll passes now run per cycle (active, settled, unfiltered) and
        they overlap heavily -- a smoke test produced 35,033 rows for 16,027
        distinct programs in a single cycle. At a 15-minute cadence that is
        ~3.4M near-identical rows a day, which buries the transitions we are
        actually here for: `paid_out` flipping, and a program leaving the
        active set.

        Storing on change keeps every transition and drops the repetition. The
        first sighting of a program is always stored, so nothing is lost.
        """

        stamp = utc_now()
        pending = []
        for row in raw:
            body = json.dumps(row, sort_keys=True)
            key = str(row.get("id") or row.get("market_ticker") or body)
            if self._program_state.get(key) == body:
                continue
            self._program_state[key] = body
            pending.append((self.run_id, stamp, body))
        if pending:
            self.connection.executemany(
                "INSERT INTO programs(run_id, fetched_at, raw_json) VALUES(?,?,?)",
                pending)
            self._flush(force=True)

    def record_book(self, ticker: str, status: int, raw: object | None) -> None:
        self.connection.execute(
            "INSERT INTO books(run_id, market_ticker, fetched_at, http_status, raw_json)"
            " VALUES(?,?,?,?,?)",
            (self.run_id, ticker, utc_now(), status,
             None if raw is None else json.dumps(raw, sort_keys=True)))
        self._flush()

    def record_trades(self, ticker: str, rows: list) -> int:
        """Store trades, ignoring ones already seen. Returns rows newly stored."""

        if not rows:
            return 0
        stamp = utc_now()
        before = self.connection.total_changes
        self.connection.executemany(
            "INSERT OR IGNORE INTO trades(trade_id, run_id, market_ticker,"
            " created_time, fetched_at, raw_json) VALUES(?,?,?,?,?,?)",
            [(str(row.get("trade_id")), self.run_id, ticker,
              str(row.get("created_time") or ""), stamp,
              json.dumps(row, sort_keys=True)) for row in rows
             if row.get("trade_id")])
        self._flush(force=True)
        return self.connection.total_changes - before

    def record_exchange_status(self, raw: object) -> None:
        self.connection.execute(
            "INSERT INTO exchange_status(run_id, fetched_at, raw_json) VALUES(?,?,?)",
            (self.run_id, utc_now(), json.dumps(raw, sort_keys=True)))
        self._flush(force=True)

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


def fetch_programs(limiter: Limiter, capture: Capture,
                   status_filter: str | None) -> list:
    """Page every liquidity program under one status filter.

    `status_filter=None` omits the parameter entirely, which returns a
    different set from `status=active` -- checked against the live API
    2026-08-18: active/closed give one population, settled/ended/no-filter
    another with later end dates. Polling only `active` therefore never
    observes a program AFTER it ends, and `paid_out` is the field that would
    corroborate the `period_reward` scale (FINDINGS 3). A program that leaves
    the active list takes its terminal state with it, permanently.
    """

    rows: list = []
    cursor = None
    base = f"{BASE}/incentive_programs?type=liquidity&limit=200" + (
        f"&status={status_filter}" if status_filter else "")
    for _ in range(80):
        url = base + (f"&cursor={cursor}" if cursor else "")
        status, payload = get_json(limiter, url)
        if status != 200 or payload is None:
            capture.record_error(
                "fetch_programs", f"status={status_filter} HTTP {status}")
            break
        rows.extend(payload.get("incentive_programs", []))
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return rows


def fetch_active_programs(limiter: Limiter, capture: Capture) -> list:
    """Active programs -- the set that drives ranking.

    Everything fetched under other filters is recorded too, but ranking uses
    the active set so we never quote a program that has already ended.
    """

    return fetch_programs(limiter, capture, "active")


def backfill_trades(limiter: Limiter, capture: "Capture", ticker: str,
                    since: int, max_pages: int = 25) -> int:
    """Page a ticker's trade history back to `since`. Returns rows stored."""

    stored = 0
    cursor = None
    for _ in range(max_pages):
        url = (f"{BASE}/markets/trades?ticker={ticker}&min_ts={since}&limit=1000"
               + (f"&cursor={cursor}" if cursor else ""))
        status, payload = get_json(limiter, url)
        if status != 200 or payload is None:
            capture.record_error("backfill_trades", f"{ticker} HTTP {status}")
            break
        rows = payload.get("trades", [])
        stored += capture.record_trades(ticker, rows)
        cursor = payload.get("next_cursor") or payload.get("cursor")
        # An empty page still returns a cursor on this endpoint, so stop on the
        # page contents rather than trusting the cursor to go falsy.
        if not cursor or not rows:
            break
    return stored


def scan_density(limiter: Limiter, capture: "Capture", rows: list,
                 max_candidates: int) -> dict[str, float]:
    """Measure each candidate's real reward density: pool / competing score.

    Ranking by `period_reward / target_size` is ANTI-CORRELATED with revenue
    (Spearman -0.150, FINDINGS 11). Its premise -- that target size is the
    denominator we compete against -- is false: target is 1000 in 99.2% of
    programs while the score we actually compete against spans 629x. That
    metric was ported from liquidity-bot, where target really does range
    5,000-15,000, and it lost all its discriminating power on the way.

    The real denominator needs one orderbook call per candidate. At 200 reads/s
    the whole live universe costs under three minutes, so this is affordable at
    an hourly cadence -- and the denominator is stable enough to rank on
    (first-half/second-half Spearman +0.818, FINDINGS 11).

    Two things fall out for free:

      * the two-sided gate. A market whose either side misses Target Size pays
        NOTHING regardless of our share (section 2), and the old ranking never
        checked it at all.
      * the books themselves are stored, giving universe-wide snapshots rather
        than only the slate we chose to track.

    Returns {ticker: density}. Markets failing the two-sided gate are absent.
    """

    density: dict[str, float] = {}
    seen: set[str] = set()
    for row in rows[:max_candidates]:
        ticker = str(row.get("market_ticker") or "").strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        try:
            target = float(row["target_size_fp"])
            discount = float(row["discount_factor_bps"]) / 10000.0
            pool = float(row["period_reward"])
        except (KeyError, TypeError, ValueError):
            continue
        if target <= 0:
            continue
        status, payload = get_json(
            limiter, f"{BASE}/markets/{ticker}/orderbook?depth={MAX_BOOK_DEPTH}")
        capture.record_book(ticker, status, payload)
        if status != 200 or payload is None:
            continue
        book = (payload or {}).get("orderbook_fp") or {}
        scores = []
        for name in ("yes", "no"):
            ladder = [(float(px), float(sz))
                      for px, sz in (book.get(f"{name}_dollars") or [])]
            score, reached = qualifying_score(ladder, target, discount)
            if not reached:
                scores = []
                break
            scores.append(score)
        if not scores:
            continue        # one-sided: pays nothing, do not track it
        competing = sum(scores) / 2.0
        if competing <= 0:
            continue
        density[ticker] = pool / competing
    return density


def qualifying_score(ladder: list[tuple[float, float]], target: float,
                     discount: float) -> tuple[float, bool]:
    """Total discount-weighted score of the qualifying bids on one side.

    Mirrors `analyze_capture.qualifying` deliberately -- this script must not
    import the analysis layer, because the capture has to keep running when the
    analysis changes. Kept small enough to read side by side.
    """

    if not ladder:
        return 0.0, False
    ordered = sorted(ladder, key=lambda level: -level[0])
    reference = ordered[0][0]
    cumulative = 0.0
    score = 0.0
    for price, size in ordered:
        cumulative += size
        score += (discount ** round((reference - price) * 100)) * size
        if cumulative >= target:
            return score, True
    return score, False


def rank(rows: list, limit: int, max_per_series: int = 3,
         density: dict[str, float] | None = None) -> list[str]:
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
        if density is not None:
            # Measured density, and absence means the market failed the
            # two-sided gate during the scan -- it pays nothing, so it is not
            # a candidate at all.
            if ticker not in density:
                continue
            scored.append((density[ticker], ticker))
        else:
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
    parser.add_argument("--rps", type=float, default=20.0,
                        help="shared request rate. /account/limits reports the"
                             " basic tier refilling reads at 200/s, so this is"
                             " deliberately far under the ceiling.")
    parser.add_argument("--rank-by", choices=("density", "target"),
                        default="density",
                        help="'density' measures the real competing score with"
                             " one orderbook call per candidate and also"
                             " applies the two-sided gate. 'target' is the old"
                             " reward/target_size, kept only for reproducing"
                             " earlier captures -- it is anti-correlated with"
                             " revenue (FINDINGS 11).")
    parser.add_argument("--density-refresh-minutes", type=float, default=60.0,
                        help="how often to re-scan denominators; the"
                             " denominator is stable enough to rank on"
                             " (Spearman +0.818) so this need not be frequent")
    parser.add_argument("--density-candidates", type=int, default=3000,
                        help="cap on candidates scanned, to bound scan time")
    parser.add_argument("--trade-backfill-hours", type=float, default=48.0,
                        help="how far back to page trades on first sight of a market")
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
    program_end: dict[str, str] = {}
    density_map: dict[str, float] = {}
    next_density = 0.0
    backfilled: set[str] = set()
    trade_total = 0

    try:
        while time.monotonic() < deadline:
            sweep_started = time.monotonic()
            overhead = 0.0

            if sweep_started >= next_programs:
                overhead_started = time.monotonic()
                status, payload = get_json(limiter, f"{BASE}/exchange/status")
                if status == 200 and payload is not None:
                    capture.record_exchange_status(payload)
                rows = fetch_active_programs(limiter, capture)
                # Record the terminal-state population too. It is not used for
                # ranking -- we never quote an ended program -- but it is the
                # only way to observe `paid_out` after a program closes, and
                # that observation cannot be made retrospectively.
                for extra in ("settled", None):
                    other = fetch_programs(limiter, capture, extra)
                    if other:
                        capture.record_programs(other)
                        for row in other:
                            ticker = str(row.get("market_ticker") or "").strip()
                            if ticker:
                                program_end[ticker] = str(
                                    row.get("end_date") or "")
                if rows:
                    capture.record_programs(rows)
                    for row in rows:
                        ticker = str(row.get("market_ticker") or "").strip()
                        if ticker:
                            program_end[ticker] = str(row.get("end_date") or "")
                    if args.rank_by == "density" and (
                            sweep_started >= next_density or not density_map):
                        before = time.monotonic()
                        density_map = scan_density(
                            limiter, capture, rows, args.density_candidates)
                        print(f"[{utc_now()}] density scan:"
                              f" {len(density_map)} two-sided of {len(rows)}"
                              f" in {time.monotonic() - before:.0f}s")
                        next_density = (sweep_started
                                        + args.density_refresh_minutes * 60.0)
                    fresh = rank(rows, args.markets,
                                 density=density_map or None)
                    # STICKY SELECTION. Re-ranking from scratch every refresh
                    # lets a market we have watched for twenty hours fall out
                    # of the top N and take its end-window with it. Coverage --
                    # observed span over program period -- is the guard that
                    # decides whether a market's share is trustworthy at all
                    # (FINDINGS 9), so churn actively destroys the thing this
                    # capture exists to produce. Once picked, a ticker is held
                    # until its program's end_date passes.
                    now_iso = utc_now()
                    held = [t for t in tickers if still_open(program_end.get(t))]
                    tickers = held + [t for t in fresh if t not in held]
                    if len(tickers) > args.markets:
                        tickers = tickers[:args.markets]
                    print(f"[{now_iso}] programs={len(rows)}"
                          f" tracking={len(tickers)} held={len(held)}"
                          f" trades={trade_total}")
                # Market metadata is refreshed here rather than only on first
                # sight: a market that settles mid-capture changes status and
                # gains a result, and fetching once would record neither.
                known_meta.clear()
                next_programs = sweep_started + args.program_refresh_minutes * 60.0
                # Program refresh and the density scan are periodic overhead,
                # not part of the book sweep. Counting them against --interval
                # produced a spurious sweep_overrun on every refresh cycle.
                overhead = time.monotonic() - overhead_started

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

                # Trades, in two modes.
                #
                # First sight of a ticker: page back `--trade-backfill-hours`.
                # The markets that rank highest on reward/target are thin by
                # construction -- that is *why* they rank -- so a short window
                # returns nothing at all. The first run asked for 45 seconds
                # and recorded zero trades across 40 markets, which reads as
                # "no trades exist" rather than "the window was too narrow".
                # Backfill also means markout is computable immediately
                # instead of after hours of waiting.
                #
                # Afterwards: a deliberately overlapping window. Trades dedupe
                # on the venue's own trade_id, so overlap costs bandwidth and
                # nothing else, while a gap loses fill signals permanently.
                if ticker not in backfilled:
                    since = int(time.time()) - int(args.trade_backfill_hours * 3600)
                    trade_total += backfill_trades(limiter, capture, ticker, since)
                    backfilled.add(ticker)
                else:
                    since = int(time.time()) - max(300, int(args.interval * 6))
                    status, payload = get_json(
                        limiter,
                        f"{BASE}/markets/trades?ticker={ticker}"
                        f"&min_ts={since}&limit=200")
                    if status == 200 and payload is not None:
                        trade_total += capture.record_trades(
                            ticker, payload.get("trades", []))
                    else:
                        capture.record_error("fetch_trades", f"{ticker} HTTP {status}")

                if time.monotonic() >= deadline:
                    break

            elapsed = time.monotonic() - sweep_started - overhead
            if elapsed < args.interval:
                time.sleep(max(0.0, args.interval - elapsed))
            else:
                # The sweep itself outran the interval. That is not an error --
                # the rate limiter is doing its job -- but it means the real
                # sample spacing is the sweep length, and analysis must read
                # the timestamps rather than assume the configured interval.
                capture.record_error(
                    "sweep_overrun",
                    f"{elapsed:.1f}s for {len(tickers)} markets"
                    f" exceeds interval {args.interval}s"
                    f" (excluding {overhead:.1f}s of program/density overhead)")
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
