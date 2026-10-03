"""D-175 Endgame Trader rules: buy the near-certain favourite when a match is
almost over and hold it to settlement (a port of the operator's Polymarket
late-favourite trader, liquidity-bot/src/liquidity_bot/late_favorite_trader.py).

Operator 2026-10-03: "build something i did on polymarket like the endgame
trader", "doing all sport", "use polymarket as reference like how they enter
trade", 99c cap kept ("Then its ok"), dry run first for data at 90-99c.

Pure logic only, no I/O; the process is scripts/endgame_trader.py. Game state
comes from Kalshi live data (/live_data/batch) per milestone type.

Entry (as Polymarket): the game is almost over (per sport), clock sports are
not tied, the book is two-sided with spread <= max_spread, the middle price is
>= the floor (the market's view, not the ask: a thin 89/99 book is a 94c
middle), the ask is <= max_price, a win clears the taker fee, and the cheapest
qualifying favourite is chosen. Kalshi buys YES on the favourite's own market
only (team markets; never Tie, never NO).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

CENT = Decimal('0.01')
ONE = Decimal(1)
LIVE_STATUSES = frozenset({'inprogress', 'live', 'started'})
WINNER_SERIES_ENDINGS = ('GAME', 'MATCH', 'DOUBLES')
NOT_WINNER_WORDS = ('SPREAD', 'TOTAL', 'BTTS', 'EXTRAS', 'DELAY', '1H', '2H', 'HALF')
KINDS = frozenset({'minute', 'clock', 'tennis', 'table_tennis', 'maps', 'baseball', 'volleyball', 'advance'})
EVENT_KINDS = frozenset({'winner', 'advance'})


@dataclass(frozen=True)
class SportRule:
    kind: str
    types: tuple[str, ...]                 # Kalshi milestone types this rule reads
    min_minute: int | None = None          # minute: soccer 90'+
    min_inning: int | None = None          # baseball: this inning or later
    max_clock_minutes: float | None = None  # clock: last N minutes of the last period
    min_lead: int = 1                      # lead needed (clock sports: 1 = not tied)
    min_current: int = 0                   # sets: games/points the leader has in the current unit
    units_to_win: int | None = None        # tennis/esports best-of (None: read from live data)
    min_price: Decimal | None = None       # per-sport floor on the middle price
    experimental: bool = False             # never real orders, paper only
    events: str = 'winner'                 # 'winner' (GAME/MATCH) or 'advance' (soccer cup ties)
    max_expiry_hours: float | None = None  # market must be due to settle within this (advance: not a first leg)

    def __post_init__(self):
        if self.kind not in KINDS or not self.types or self.events not in EVENT_KINDS:
            raise ValueError(f'unknown endgame rule kind {self.kind!r}/{self.events!r}')


@dataclass(frozen=True)
class Policy:
    enabled: bool = False
    live_orders: bool = False
    risk_per_trade_usd: Decimal = Decimal(10)
    max_open_positions: int = 50           # live only; the dry run has no cap (operator: "as much position we can")
    daily_loss_stop_usd: Decimal = Decimal(50)
    min_price: Decimal = Decimal('0.95')   # the trading rule
    data_min_price: Decimal = Decimal('0.90')  # dry-run data band below the rule (operator: "Then 90-99c")
    max_price: Decimal = Decimal('0.99')
    poll_seconds: float = 10.0
    max_spread: Decimal = Decimal('0.10')
    rules: dict = field(default_factory=dict)

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.live_orders) is not bool:
            raise ValueError('enabled/live_orders must be boolean')
        for name, value, low, high in (
                ('risk_per_trade_usd', self.risk_per_trade_usd, 1, 100),
                ('daily_loss_stop_usd', self.daily_loss_stop_usd, 1, 1000),
                ('min_price', self.min_price, Decimal('0.5'), Decimal('0.99')),
                ('data_min_price', self.data_min_price, Decimal('0.5'), Decimal('0.99')),
                ('max_price', self.max_price, Decimal('0.5'), Decimal('0.99')),
                ('max_spread', self.max_spread, Decimal('0.01'), Decimal('0.10'))):
            if not isinstance(value, Decimal) or not value.is_finite() or not low <= value <= high:
                raise ValueError(f'endgame {name} must be in [{low}, {high}]')
        if not 5 <= self.poll_seconds <= 120:
            raise ValueError('endgame poll_seconds must be in [5, 120]')
        if type(self.max_open_positions) is not int or not 1 <= self.max_open_positions <= 200:
            raise ValueError('max_open_positions must be an integer in [1, 200]')
        if not self.data_min_price <= self.min_price <= self.max_price:
            raise ValueError('need data_min_price <= min_price <= max_price')

    def rules_for(self, milestone_type):
        """Every (sport, rule) reading this milestone type: soccer has the
        90-minute winner rule and the cup 'advances' rule."""
        return [(name, rule) for name, rule in self.rules.items() if milestone_type in rule.types]


def _dec(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f'{name} must be a string or integer')
    return Decimal(str(value))


def load_policy(path: Path) -> Policy:
    raw = json.loads(path.read_text(encoding='utf-8'))
    rules = {}
    allowed = {'kind', 'types', 'min_minute', 'max_clock_minutes', 'min_lead', 'min_current',
               'units_to_win', 'min_price', 'experimental', 'events', 'max_expiry_hours', 'min_inning'}
    for sport, r in (raw.pop('rules', None) or {}).items():
        if set(r) - allowed:
            raise ValueError(f'unknown rule fields for {sport}: {sorted(set(r) - allowed)}')
        rules[sport] = SportRule(
            kind=r['kind'], types=tuple(r['types']), min_minute=r.get('min_minute'),
            max_clock_minutes=r.get('max_clock_minutes'), min_lead=r.get('min_lead', 1),
            min_inning=r.get('min_inning'),
            min_current=r.get('min_current', 0), units_to_win=r.get('units_to_win'),
            min_price=_dec(r['min_price'], 'min_price') if 'min_price' in r else None,
            experimental=bool(r.get('experimental', False)), events=r.get('events', 'winner'),
            max_expiry_hours=r.get('max_expiry_hours'))
    money = {'risk_per_trade_usd', 'daily_loss_stop_usd', 'min_price', 'data_min_price',
             'max_price', 'max_spread'}
    if set(raw) - set(Policy.__dataclass_fields__):
        raise ValueError(f'unknown endgame fields: {sorted(set(raw) - set(Policy.__dataclass_fields__))}')
    values = {k: (_dec(v, k) if k in money else v) for k, v in raw.items()}
    return Policy(rules=rules, **values)


# ---- game state -------------------------------------------------------------

def match_minute(text):
    """Soccer minute from "85'" or "90+6'" (-> 90)."""
    m = re.match(r"\s*(\d{1,3})(?:\+\d+)?'", str(text or ''))
    return int(m.group(1)) if m else None


def clock_minutes(text):
    """Countdown "05:37" / "0:42" -> minutes left."""
    m = re.fullmatch(r'\s*(\d{1,2}):(\d{2})(?:\.\d+)?\s*', str(text or ''))
    return int(m.group(1)) + int(m.group(2))/60 if m else None


def _int(value):
    return value if type(value) is int else None


def _points(details, home, away):
    a, b = _int(details.get(home)), _int(details.get(away))
    return (a, b) if a is not None and b is not None else None


def _lead_ok(score, min_lead):
    return score is not None and abs(score[0]-score[1]) >= max(1, min_lead)


def _last_period(details, milestone_type):
    """(in the last period or overtime, minutes left) for clock sports."""
    if milestone_type == 'football_game':
        period, left = _int(details.get('quarter')), clock_minutes(details.get('clock'))
        return period is not None and period >= 4, left
    period = _int(details.get('period'))
    left = clock_minutes(details.get('period_remaining_time'))
    if period is None:
        return False, left
    if milestone_type == 'basketball_game':
        last = 2 if details.get('period_type') == 'half' else 4
    elif milestone_type == 'hockey_tournament':
        last = 3
    else:                                   # rugby: two halves
        last = 2
    return period >= last, left


def _sets_from_rounds(rounds):
    """Tennis competitorN_round_scores -> (sets won, current set games or None)."""
    if not isinstance(rounds, list):
        return None
    won, current = 0, None
    for r in rounds:
        if not isinstance(r, dict) or _int(r.get('score')) is None:
            return None
        if r.get('outcome') == 'winner':
            won += 1
        elif r.get('outcome') == 'ongoing':
            current = r['score']
    return won, current


def _unit_scores(details, a_key, b_key):
    rows = details.get('period_scores')
    if not isinstance(rows, list) or not rows:
        return None
    out = []
    for r in sorted((r for r in rows if isinstance(r, dict)), key=lambda r: _int(r.get('number')) or 0):
        a, b = _int(r.get(a_key)), _int(r.get(b_key))
        if a is None or b is None:
            return None
        out.append((a, b))
    return out or None


def _units_almost_over(units, units_to_win, min_current, min_lead):
    """The last unit is in play: a player with units_to_win-1 completed units
    has >= min_current and a lead of >= min_lead in it (Polymarket sets rule)."""
    done, (a, b) = units[:-1], units[-1]
    won = (sum(x > y for x, y in done), sum(y > x for x, y in done))
    if max(won) >= units_to_win:
        return False                         # already decided, or best-of misread
    return any(won[i] == units_to_win-1 and (a, b)[i] >= min_current
               and (a, b)[i]-(a, b)[1-i] >= max(1, min_lead) for i in (0, 1))


def almost_over(rule, milestone_type, details):
    """True when this game is in its last moments by the sport's rule."""
    if rule is None or not isinstance(details, dict):
        return False
    if details.get('status') not in LIVE_STATUSES or details.get('widget_status') != 'live':
        return False                         # halftime, delayed, finished, not started
    kind = rule.kind
    if kind == 'minute':                     # soccer: 90'+ and not tied (same-game score)
        minute = match_minute(details.get('time'))
        score = _points(details, 'home_same_game_score', 'away_same_game_score')
        return minute is not None and minute >= rule.min_minute and _lead_ok(score, rule.min_lead)
    if kind == 'advance':
        # Soccer cup tie (operator: "Advances"): extra time and penalties count,
        # and two-leg ties go on the aggregate. Almost over = from min_minute
        # (80') to the end of normal time, or 120'+ of extra time, with a lead
        # of min_lead (2, Polymarket 10-03 after four stoppage-time equalisers)
        # on the aggregate (same-game score if no aggregate). Never during
        # penalties; 91'-119' is extra time with up to half an hour left.
        if details.get('show_penalties') is True or 'penalt' in str(details.get('match_status') or '').lower():
            return False
        minute = match_minute(details.get('time'))
        score = (_points(details, 'home_aggregate_score', 'away_aggregate_score')
                 or _points(details, 'home_same_game_score', 'away_same_game_score'))
        return (minute is not None and (rule.min_minute <= minute <= 90 or minute >= 120)
                and _lead_ok(score, rule.min_lead))
    if kind == 'clock':                      # basketball, football, hockey, rugby
        last, left = _last_period(details, milestone_type)
        score = _points(details, 'home_points', 'away_points')
        return (last and left is not None and left <= rule.max_clock_minutes
                and _lead_ok(score, rule.min_lead))
    if kind == 'baseball':
        # Polymarket rule (operator 10-03, "yes add basesball"): 9th inning or
        # later with a lead of min_lead runs (2), any half, any outs.
        inning = _int(details.get('inning'))
        score = _points(details, 'home_points', 'away_points')
        return (inning is not None and inning >= (rule.min_inning or 9)
                and _lead_ok(score, rule.min_lead))
    if kind == 'tennis':                     # best of 3: the leader needs only the current set
        one = _sets_from_rounds(details.get('competitor1_round_scores'))
        two = _sets_from_rounds(details.get('competitor2_round_scores'))
        if one is None or two is None or one[1] is None or two[1] is None:
            return False
        units_to_win = rule.units_to_win or 2
        if max(one[0], two[0]) >= units_to_win:
            return False
        return any(w == units_to_win-1 and cur >= rule.min_current and cur-other >= max(1, rule.min_lead)
                   for (w, cur), other in ((one, two[1]), (two, one[1])))
    if kind == 'table_tennis':
        best = _int(details.get('best_of_sets'))
        units = _unit_scores(details, 'competitor1_score', 'competitor2_score')
        return (best is not None and best % 2 == 1 and units is not None
                and _units_almost_over(units, best//2+1, rule.min_current, rule.min_lead))
    if kind == 'volleyball':
        best = _int(details.get('best_of'))
        units = _unit_scores(details, 'home_score', 'away_score')
        return (best is not None and best % 2 == 1 and units is not None
                and _units_almost_over(units, best//2+1, rule.min_current, rule.min_lead))
    if kind == 'maps':                       # esports: a team is one map from winning
        score = _points(details, 'home_score', 'away_score')
        units_to_win = rule.units_to_win or 2
        return score is not None and max(score) == units_to_win-1
    return False


def game_text(milestone_type, details):
    """Short game state for the trade record."""
    keep = ('time', 'half', 'quarter', 'clock', 'period', 'period_type', 'period_remaining_time',
            'inning', 'inning_half', 'outs', 'home_points', 'away_points', 'home_score', 'away_score',
            'home_same_game_score', 'away_same_game_score', 'best_of_sets', 'best_of', 'completed_rounds')
    state = {k: details.get(k) for k in keep if details.get(k) is not None}
    for k in ('competitor1_round_scores', 'competitor2_round_scores'):
        if isinstance(details.get(k), list):
            state[k[:11]] = [r.get('score') for r in details[k] if isinstance(r, dict)]
    if isinstance(details.get('period_scores'), list):
        state['units'] = [[r.get(a) for a in ('competitor1_score', 'competitor2_score', 'home_score', 'away_score')
                           if r.get(a) is not None] for r in details['period_scores'] if isinstance(r, dict)]
    return json.dumps(dict(type=milestone_type, **state), separators=(',', ':'))[:600]


# ---- markets ----------------------------------------------------------------

def rule_events(rule, event_tickers):
    """The events a rule trades: winner events, or soccer 'advances' events."""
    if rule.events == 'advance':
        return [t for t in event_tickers or () if str(t).split('-')[0].upper().endswith('ADVANCE')]
    return winner_events(event_tickers)


def winner_events(event_tickers):
    """The milestone's winner (moneyline) events: series ending GAME/MATCH/DOUBLES,
    never spreads, totals, both-teams-to-score, first half, extras or delays."""
    out = []
    for ticker in event_tickers or ():
        series = str(ticker).split('-')[0].upper()
        if series.endswith(WINNER_SERIES_ENDINGS) and not any(w in series for w in NOT_WINNER_WORDS):
            out.append(ticker)
    return out


def taker_fee(count, price, multiplier=ONE):
    """Kalshi quadratic taker fee for one order, rounded up to the cent."""
    raw = Decimal('0.07')*multiplier*count*price*(ONE-price)
    return (raw/CENT).to_integral_value(rounding=ROUND_CEILING)*CENT


@dataclass(frozen=True)
class Candidate:
    event_ticker: str
    ticker: str
    team: str
    bid: Decimal
    ask: Decimal
    mid: Decimal
    band: str                               # 'rule' (>= min_price) or 'data' (dry-run data band)


def _quote(value):
    try:
        x = Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return None
    return x if x.is_finite() and Decimal(0) < x < ONE else None


def _when(text):
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None


def pick_entry(event_ticker, markets, policy, rule, *, data_band, now=None):
    """The one favourite to buy in this winner event now, or None.

    ``data_band`` (dry run only) lowers the middle-price floor to
    data_min_price; such entries are tagged 'data', never traded live."""
    floor = max(policy.min_price, rule.min_price or Decimal(0))
    lowest = min(floor, policy.data_min_price) if data_band else floor
    best = None
    for m in markets or ():
        if not isinstance(m, dict) or m.get('status') != 'active':
            continue
        ticker, team = str(m.get('ticker') or ''), str(m.get('yes_sub_title') or '')
        if not ticker or ticker.upper().endswith('-TIE') or team.strip().lower() in ('tie', 'draw'):
            continue                         # soccer: winners only, never the draw
        if rule.max_expiry_hours is not None:
            # A first leg's 'advances' market settles after the second leg.
            due = _when(m.get('expected_expiration_time'))
            if due is None or now is None or (due-now).total_seconds() > rule.max_expiry_hours*3600:
                continue
        bid, ask = _quote(m.get('yes_bid_dollars')), _quote(m.get('yes_ask_dollars'))
        if bid is None or ask is None or ask < bid or ask-bid > policy.max_spread:
            continue                         # one-sided or wide book: the price is not reliable
        mid = (bid+ask)/2
        if mid < lowest or ask > policy.max_price:
            continue
        # A win must still clear the taker fee (one contract, unrounded per contract).
        if (ONE-ask)-Decimal('0.07')*ask*(ONE-ask) <= 0:
            continue
        cand = Candidate(event_ticker, ticker, team, bid, ask, mid, 'rule' if mid >= floor else 'data')
        if best is None or ask < best.ask:   # the cheapest favourite pays most
            best = cand
    return best


def contracts_for(risk_usd, worst_price):
    """Whole contracts so that worst_price x qty <= risk (Polymarket sizes on the cap)."""
    return int((Decimal(risk_usd)/Decimal(worst_price)).to_integral_value(rounding=ROUND_FLOOR))


def fill_from_book(no_levels, qty, limit):
    """Walk the YES asks (1 - NO bids) up to ``limit``: (filled, average price).

    The full size must be there (Polymarket depth check), else (0, None)."""
    asks = []
    for level in no_levels or ():
        try:
            price, size = ONE-Decimal(str(level[0])), Decimal(str(level[1]))
        except (ArithmeticError, ValueError, TypeError, IndexError):
            return 0, None
        if price.is_finite() and size.is_finite() and size > 0 and price <= limit:
            asks.append((price, size))
    asks.sort()
    need, cost = Decimal(qty), Decimal(0)
    for price, size in asks:
        take = min(need, size)
        cost += take*price
        need -= take
        if need <= 0:
            break
    if need > 0 or qty <= 0:
        return 0, None
    return qty, cost/Decimal(qty)


def realized_result(won, qty, avg_price, fee):
    qty, avg_price = Decimal(qty), Decimal(avg_price)
    return (qty*(ONE-avg_price) if won else -qty*avg_price)-Decimal(fee)


def daily_stop_hit(realized_today, policy):
    return math.isfinite(float(realized_today)) and realized_today <= -policy.daily_loss_stop_usd


def price_bucket(price):
    """Whole-cent bucket label for the report: 0.953 -> '95c'."""
    return f'{int((Decimal(price)*100).to_integral_value(rounding=ROUND_FLOOR))}c'
