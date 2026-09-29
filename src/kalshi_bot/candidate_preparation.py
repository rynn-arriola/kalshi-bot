"""Public, bounded launch-scope preparation for reward-market discovery.

This owner creates rules/milestone bindings only. It does not subscribe, rank a
book, authorize an order, read an account, or claim that a reward will be paid.
The live metadata and selection owners still revalidate every admitted market.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from .incentive_discovery import QUERY as INCENTIVE_QUERY
from .market_inputs import (
    SCHEDULED_RELEASE_CONDITION,
    SCHEDULED_RELEASE_REVIEW,
    SCHEDULED_RELEASE_TYPES,
    TimingReview,
    parse_market,
    scheduled_release_timing,
    timestamp,
)
from .quoting import parse_program
from .ranking import seconds
from .rest import PageSet
from .values import InvalidData, identity, integer, utc
from .risk import MAX_RESTING_ENTRIES


@dataclass(frozen=True)
class PreparedCandidates:
    reviews: tuple[TimingReview, ...]
    initial_tickers: tuple[str, ...]
    exchange_indices: tuple[int, ...]
    incentive_rows: int
    market_rows: int
    milestone_rows: int
    excluded: tuple[tuple[str, int], ...]
    scanned: int = 0   # D-159: reviews chosen from the saved full-market scan
    pinned: int = 0    # D-161: project contracts kept in scope first


def _chunks(tickers, maximum=1800):
    """Keep encoded comma lists comfortably below RestReads' query bound."""
    rows, size = [], 0
    for ticker in tickers:
        needed = len(ticker)+(1 if rows else 0)
        if rows and size+needed > maximum:
            yield tuple(rows)
            rows, size = [], 0
            needed = len(ticker)
        rows.append(ticker)
        size += needed
    if rows:
        yield tuple(rows)


def _score(program):
    with localcontext() as ctx:
        ctx.prec = 40
        return Decimal(program.pool_centicents)/seconds(program.end-program.start)/program.target


def _select(rows, limit):
    """Keep a rewarded head and a stratified tail across event-diverse rows."""
    ordered, seen_events, seen_tickers = [], set(), set()
    for row in rows:
        if row[2].event not in seen_events:
            ordered.append(row)
            seen_events.add(row[2].event)
            seen_tickers.add(row[1])
    for row in rows:
        if row[1] not in seen_tickers:
            ordered.append(row)
            seen_tickers.add(row[1])
    if len(ordered) <= limit:
        return ordered
    head = min(MAX_RESTING_ENTRIES, limit)
    selected = ordered[:head]
    tail, slots = ordered[head:], limit-head
    # Even rank quantiles prevent the known cheap reward/target hint from
    # silently becoming a profitability filter before books are observed.
    selected.extend(tail[((index+1)*len(tail)-1)//slots] for index in range(slots))
    return selected


def _automatic_review(market, binding):
    """Review one bounded timing family; unknown early-close rules stay blocked."""
    milestone_id, kind, risk_at = binding
    if not market.early:
        return TimingReview(market.ticker, market.event, milestone_id, kind,
            market.rules_hash, 'automatic-primary-milestone-v1', market.closes,
            early_close_reviewed=False), None
    if (market.early_condition != SCHEDULED_RELEASE_CONDITION
            or kind not in SCHEDULED_RELEASE_TYPES):
        return None, 'early_close_unreviewed'
    if market.occurrence_at is None:
        return None, 'scheduled_release_occurrence_missing'
    # A milestone earlier than the occurrence produces a conservative exit. A
    # later milestone would authorize entry after the event may have happened.
    if not scheduled_release_timing(market, kind, risk_at):
        return None, 'scheduled_release_timing_conflict'
    return TimingReview(market.ticker, market.event, milestone_id, kind,
        market.rules_hash, SCHEDULED_RELEASE_REVIEW, market.closes,
        early_close_reviewed=True), None


SCAN_RESERVE_DIVISOR = 8  # D-159: 1/8 of the scope stays on the old order


def _select_scanned(rows, limit, scan_scores):
    """D-159: markets the saved full scan measured as scoring, best reward left
    first, fill all but one eighth of the scope; the rest keeps the old
    event-diverse, stratified order so new or unscanned programs stay seen."""
    scanned = sorted((row for row in rows if scan_scores.get(row[1], 0) > 0),
                     key=lambda row: (-scan_scores[row[1]], row[1]))
    head = scanned[:limit-limit//SCAN_RESERVE_DIVISOR]
    chosen = {row[1] for row in head}
    rest = [row for row in rows if row[1] not in chosen]
    return head+_select(rest, min(limit-len(head), len(rest))), len(head)


async def prepare_candidates(reads, *, now, max_reviews=1024, seed_capacity=128,
                             scan_scores=None, pinned=()):
    """Resolve current programs to exact market rules and primary milestones.

    Cheap pool/time/target density is only a discovery ordering. The returned
    scope must still receive fresh WebSocket books and pass the existing exact
    reward/capital ranking before an entry can be proposed. D-159: fresh saved
    full-scan scores (reward left per market), when given, choose most of the
    scope instead of the hint; eligibility checks are unchanged.
    """
    now = utc(now)
    integer(max_reviews, 1, 1024)
    integer(seed_capacity, 1, 128)
    incentives = await reads.collect('incentives', reason='incentives',
        max_pages=100, max_rows=10000, byte_limit=16777216,
        coalesce_scope=object(), **dict(INCENTIVE_QUERY))
    if (not isinstance(incentives, PageSet) or not incentives.exhausted
            or incentives.source != 'incentives' or incentives.query != INCENTIVE_QUERY):
        raise InvalidData('incomplete incentive candidate enumeration')

    scores, excluded, seen_programs = {}, {}, set()
    for row in incentives.rows:
        try:
            program = parse_program(row)
        except InvalidData:
            ticker = row.get('market_ticker') if isinstance(row, dict) else None
            if isinstance(ticker, str):
                excluded['unsupported_program'] = excluded.get('unsupported_program', 0)+1
            continue
        if program.program_id in seen_programs:
            raise InvalidData('duplicate incentive identity across pages')
        seen_programs.add(program.program_id)
        if (program.paid_out or program.max_reward_centicents is not None
                or not program.start <= now < program.end or not program.pool_centicents):
            excluded['inactive_or_capped_program'] = excluded.get('inactive_or_capped_program', 0)+1
            continue
        score = _score(program)
        scores[program.ticker] = max(score, scores.get(program.ticker, Decimal(0)))
    if not scores:
        raise InvalidData('no current supported liquidity programs')

    # Fetch only rewarded tickers, not Kalshi's entire open-market universe.
    # Market chunks and the independent milestone census overlap, while each
    # market batch remains bounded to four requests.  This is public startup
    # work; it never changes the single account/read or mutation owners.
    ranked_tickers = tuple(t for t, _ in sorted(scores.items(), key=lambda row:(-row[1], row[0])))
    chunks = tuple(_chunks(ranked_tickers))
    async def market_pages():
        results = []
        for offset in range(0, len(chunks), 4):
            results.extend(await asyncio.gather(*(reads.read('markets',
                reason='candidate', tickers=','.join(chunk), limit=1000,
                mve_filter='exclude') for chunk in chunks[offset:offset+4])))
        return tuple(results)
    market_task = asyncio.create_task(market_pages())
    milestone_task = asyncio.create_task(reads.collect('milestones', reason='candidate',
        minimum_start_date=now.isoformat(), limit=500, max_pages=100,
        max_rows=10000, byte_limit=16777216, coalesce_scope=object()))
    try:
        market_results, milestones = await asyncio.gather(market_task, milestone_task)
    except BaseException:
        for task in (market_task, milestone_task):
            task.cancel()
        await asyncio.gather(market_task, milestone_task, return_exceptions=True)
        raise

    markets = {}
    for chunk, result in zip(chunks, market_results, strict=True):
        rows = result.payload.get('markets')
        if not isinstance(rows, list) or len(rows) > len(chunk):
            raise InvalidData('invalid rewarded-market response scope')
        requested = set(chunk)
        for row in rows:
            if not isinstance(row, dict):
                raise InvalidData('invalid rewarded-market row')
            ticker = identity(row.get('ticker'))
            if ticker not in requested or ticker in markets:
                raise InvalidData('rewarded-market identity conflict')
            markets[ticker] = row

    if (not isinstance(milestones, PageSet) or not milestones.exhausted
            or milestones.source != 'milestones'):
        raise InvalidData('incomplete future milestone enumeration')
    primary = {}
    seen_milestones = set()
    for row in milestones.rows:
        try:
            milestone_id = identity(row['id'])
            kind = identity(row['type'])
            start = timestamp(row['start_date'])
            events = row['primary_event_tickers']
            if (milestone_id in seen_milestones or type(events) is not list
                    or len(events) > 1024):
                raise InvalidData('milestone identity/scope conflict')
            seen_milestones.add(milestone_id)
            if start <= now:
                continue
            if len(set(events)) != len(events):
                raise InvalidData('duplicate primary event in milestone')
            for event in events:
                primary.setdefault(identity(event), []).append((milestone_id, kind, start))
        except (KeyError, TypeError):
            raise InvalidData('invalid future milestone row') from None

    eligible = []
    for ticker in ranked_tickers:
        row = markets.get(ticker)
        if row is None:
            excluded['market_missing'] = excluded.get('market_missing', 0)+1
            continue
        try:
            market = parse_market({'market':row}, ticker)
        except InvalidData:
            excluded['unsupported_market'] = excluded.get('unsupported_market', 0)+1
            continue
        # Resolve uniqueness across the complete future result before applying
        # the entry buffer. Otherwise an imminent binding can be discarded and
        # a later binding incorrectly promoted to the event's risk deadline.
        bindings = primary.get(market.event, ())
        if len(bindings) != 1:
            key = 'milestone_missing' if not bindings else 'milestone_ambiguous'
            excluded[key] = excluded.get(key, 0)+1
            continue
        if not market.active or not market.opens <= now < market.closes:
            excluded['market_inactive'] = excluded.get('market_inactive', 0)+1
            continue
        milestone_id, kind, risk_at = bindings[0]
        if risk_at <= now+timedelta(minutes=5):
            excluded['milestone_imminent'] = excluded.get('milestone_imminent', 0)+1
            continue
        review, reason = _automatic_review(market, bindings[0])
        if reason is not None:
            excluded[reason] = excluded.get(reason, 0)+1
            continue
        eligible.append((-scores[ticker], ticker, market, review))
    eligible.sort(key=lambda row:(row[0], row[1]))
    # D-161: project contracts (committed to finish past $1) stay watched and
    # seeded first across restarts; the rest of the scope is chosen as before.
    pinned = frozenset(pinned)
    head = [row for row in eligible if row[1] in pinned][:max_reviews]
    rest = [row for row in eligible if row[1] not in pinned]
    limit = min(max_reviews, len(eligible))-len(head)
    if limit <= 0:
        selected, scanned = [], 0
    elif scan_scores:
        selected, scanned = _select_scanned(rest, limit, scan_scores)
    else:
        selected, scanned = _select(rest, limit), 0
    selected = head+list(selected)
    if not selected:
        raise InvalidData('no current reward market has one future primary milestone')
    reviews = tuple(row[3] for row in selected)
    seeds = tuple(row[1] for row in selected[:min(seed_capacity, len(selected))])
    exchanges = tuple(sorted({0, *(row[2].exchange for row in selected)}))
    return PreparedCandidates(reviews, seeds, exchanges, len(incentives.rows),
                              len(markets), len(milestones.rows),
                              tuple(sorted(excluded.items())), scanned, len(head))
