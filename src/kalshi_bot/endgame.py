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
# EXACT: tennis exact-score markets (KXATPEXACTMATCH 'wins 2-1') end in MATCH
# too; 43 paper trades bought them as winners until 10-05.
NOT_WINNER_WORDS = ('SPREAD', 'TOTAL', 'BTTS', 'EXTRAS', 'DELAY', '1H', '2H', 'HALF', 'EXACT')
MATCH_TIEBREAK_POINTS = 9
MATCH_TIEBREAK_LEAD = 3
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
    # Paper-only 'test' floor below the rule (operator 10-03 "Ok apply it",
    # from the 14-day replay: late tennis/table tennis at 92c, esports at 95c).
    test_price: Decimal | None = None
    experimental: bool = False             # never real orders, paper only
    events: str = 'winner'                 # 'winner' (GAME/MATCH) or 'advance' (soccer cup ties)
    max_expiry_hours: float | None = None  # market must be due to settle within this (advance: not a first leg)
    # D-176 (Polymarket rule research 2026-10-04, ported to Kalshi):
    big_lead: int | None = None            # soccer: this lead from big_lead_minute; football: within big_lead_clock
    big_lead_minute: int | None = None
    big_lead_clock: float | None = None
    leader_ball: bool = False              # football: the leader must have the ball (unknown = skip)
    games: tuple[str, ...] = ()            # esports titles to trade (milestone details 'game'), empty = all
    skip_games: tuple[str, ...] = ()
    require_format: bool = False           # esports: best-of known from the total-maps market
    max_spread: Decimal | None = None      # per-sport overrides of the policy spread / price cap
    max_price: Decimal | None = None
    hold_seconds: int = 0                  # the entry must qualify on every poll this long
    side: str = 'yes'                      # 'yes' (favourite wins) or 'no_trailer' (NO on the trailing team)
    # D-177 esports per title (Polymarket 2026-10-04, Kalshi 60-day replay per title):
    formats: tuple[int, ...] = ()          # allowed best-of (3, 5); empty = any
    bo3_states: tuple[str, ...] = ()       # allowed map scores "high-low" ('1-1' = deciding map)
    bo5_states: tuple[str, ...] = ()
    force_best_of: int | None = None       # titles with no total-maps market (Overwatch: first to 3)
    # D-179 tennis (Polymarket 2026-10-05, Sackmann 19k matches): the leader won
    # set 1, never a deciding set or match tiebreak.
    leader_won_first_set: bool = False
    no_deciding_set: bool = False
    # D-180 99c tier (operator 10-06 "How do we make sure our 99c only wins" ->
    # "Ok do it"): paying PREMIUM_PRICE needs these stricter settings (a bigger
    # lead / less time); {'never': True} = never pay 99c; empty = no tier.
    premium: dict = field(default_factory=dict)

    def __post_init__(self):
        if (self.kind not in KINDS or not self.types or self.events not in EVENT_KINDS
                or self.side not in ('yes', 'no_trailer') or not 0 <= self.hold_seconds <= 600):
            raise ValueError(f'unknown endgame rule kind {self.kind!r}/{self.events!r}/{self.side!r}')


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


PREMIUM_PRICE = Decimal('0.99')
PREMIUM_KEYS = {'never', 'min_lead', 'max_clock_minutes', 'min_minute', 'min_inning', 'leader_ball',
                'big_lead', 'big_lead_minute', 'big_lead_clock', 'min_current'}


def _premium(sport, raw):
    if not isinstance(raw, dict) or set(raw) - PREMIUM_KEYS:
        raise ValueError(f'premium for {sport} must be a dict of {sorted(PREMIUM_KEYS)}')
    return dict(raw)


def premium_rule(rule):
    """The stricter rule a 99c buy must also pass; None = never pay 99c."""
    if rule.premium.get('never'):
        return None
    from dataclasses import replace
    return replace(rule, premium={}, **{k: v for k, v in rule.premium.items() if k != 'never'})


def load_policy(path: Path) -> Policy:
    raw = json.loads(path.read_text(encoding='utf-8'))
    rules = {}
    allowed = {'kind', 'types', 'min_minute', 'max_clock_minutes', 'min_lead', 'min_current',
               'units_to_win', 'min_price', 'experimental', 'events', 'max_expiry_hours', 'min_inning',
               'test_price', 'big_lead', 'big_lead_minute', 'big_lead_clock', 'leader_ball', 'games',
               'skip_games', 'require_format', 'max_spread', 'max_price', 'hold_seconds', 'side',
               'formats', 'bo3_states', 'bo5_states', 'force_best_of', 'leader_won_first_set',
               'no_deciding_set', 'premium'}
    for sport, r in (raw.pop('rules', None) or {}).items():
        if set(r) - allowed:
            raise ValueError(f'unknown rule fields for {sport}: {sorted(set(r) - allowed)}')
        rules[sport] = SportRule(
            kind=r['kind'], types=tuple(r['types']), min_minute=r.get('min_minute'),
            max_clock_minutes=r.get('max_clock_minutes'), min_lead=r.get('min_lead', 1),
            min_inning=r.get('min_inning'),
            min_current=r.get('min_current', 0), units_to_win=r.get('units_to_win'),
            min_price=_dec(r['min_price'], 'min_price') if 'min_price' in r else None,
            test_price=_dec(r['test_price'], 'test_price') if 'test_price' in r else None,
            experimental=bool(r.get('experimental', False)), events=r.get('events', 'winner'),
            max_expiry_hours=r.get('max_expiry_hours'), big_lead=r.get('big_lead'),
            big_lead_minute=r.get('big_lead_minute'), big_lead_clock=r.get('big_lead_clock'),
            leader_ball=bool(r.get('leader_ball', False)), games=tuple(r.get('games', ())),
            skip_games=tuple(r.get('skip_games', ())), require_format=bool(r.get('require_format', False)),
            max_spread=_dec(r['max_spread'], 'max_spread') if 'max_spread' in r else None,
            max_price=_dec(r['max_price'], 'max_price') if 'max_price' in r else None,
            hold_seconds=r.get('hold_seconds', 0), side=r.get('side', 'yes'),
            formats=tuple(r.get('formats', ())), bo3_states=tuple(r.get('bo3_states', ())),
            bo5_states=tuple(r.get('bo5_states', ())), force_best_of=r.get('force_best_of'),
            leader_won_first_set=bool(r.get('leader_won_first_set', False)),
            no_deciding_set=bool(r.get('no_deciding_set', False)),
            premium=_premium(sport, r.get('premium') or {}))
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
    elif milestone_type.startswith('hockey'):
        # D-176: NHL is 'hockey_match'; it used to fall into the rugby branch,
        # so the 2nd period counted as the last (found by the Polymarket research).
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


def _won_first_set(rounds):
    return (isinstance(rounds, list) and bool(rounds) and isinstance(rounds[0], dict)
            and rounds[0].get('outcome') == 'winner')


def tennis_progress(details):
    """(sets played, games in the current set) for the score-reversal guard;
    None when unreadable. A real match never goes backwards on this."""
    one = _sets_from_rounds(details.get('competitor1_round_scores'))
    two = _sets_from_rounds(details.get('competitor2_round_scores'))
    if one is None or two is None:
        return None
    done = sum(1 for r in details.get('competitor1_round_scores') or () if r.get('outcome') in ('winner', 'loser'))
    return done, (one[1] or 0)+(two[1] or 0)


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


def _soccer_window(rule, minute, score, *, normal_time_end=None):
    """Polymarket soccer rule (research 2026-10-04): min_lead from min_minute,
    or big_lead from big_lead_minute (2 goals from 88', 3+ from 80')."""
    if minute is None or score is None:
        return False
    lead = abs(score[0]-score[1])
    end = normal_time_end if normal_time_end is not None else 10**6
    windows = [(rule.min_minute, rule.min_lead)]
    if rule.big_lead is not None and rule.big_lead_minute is not None:
        windows.append((rule.big_lead_minute, rule.big_lead))
    return any(start <= minute <= end and lead >= max(1, need) for start, need in windows)


def almost_over(rule, milestone_type, details, meta=None, units_to_win=None):
    """True when this game is in its last moments by the sport's rule.

    ``meta``: the milestone's own details (team ids, esports game title).
    ``units_to_win``: esports maps needed, from the total-maps market."""
    if rule is None or not isinstance(details, dict):
        return False
    if details.get('status') not in LIVE_STATUSES or details.get('widget_status') != 'live':
        return False                         # halftime, delayed, finished, not started
    meta = meta if isinstance(meta, dict) else {}
    kind = rule.kind
    if kind == 'minute':                     # soccer 3-option market: same-game score
        minute = match_minute(details.get('time'))
        score = _points(details, 'home_same_game_score', 'away_same_game_score')
        return _soccer_window(rule, minute, score)
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
        if minute is not None and minute >= 120:
            return _lead_ok(score, rule.min_lead)
        return _soccer_window(rule, minute, score, normal_time_end=90)
    if kind == 'clock':                      # basketball, football, hockey, rugby
        last, left = _last_period(details, milestone_type)
        score = _points(details, 'home_points', 'away_points')
        if not last or left is None or score is None:
            return False
        lead = abs(score[0]-score[1])
        # Football (Polymarket research, 402 games): 17+ in the last 2:00 ...
        if (rule.big_lead is not None and rule.big_lead_clock is not None
                and left <= rule.big_lead_clock and lead >= rule.big_lead):
            return True
        if left > rule.max_clock_minutes or not _lead_ok(score, rule.min_lead):
            return False
        if rule.leader_ball:
            # ... or 9+ in the last 3:00 only while the leader has the ball
            # (Kalshi situation.possession_team_id vs the milestone's team ids).
            ball = (details.get('situation') or {}).get('possession_team_id')
            leader = meta.get('home_team_id') if score[0] > score[1] else meta.get('away_team_id')
            return bool(ball) and ball == leader
        return True
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
        if rule.no_deciding_set and one[0] == two[0] == units_to_win-1:
            return False                     # deciding set / match tiebreak: never (Polymarket 10-05)
        need, lead = rule.min_current, max(1, rule.min_lead)
        if (details.get('last_set_scoring_type') == 'MatchTiebreak'
                and one[0] == two[0] == units_to_win-1):
            # Deciding match tiebreak (first to 10 points): the score is points,
            # not games. Polymarket research: 9+ points and a 3-point lead.
            need, lead = MATCH_TIEBREAK_POINTS, MATCH_TIEBREAK_LEAD
        firsts = (_won_first_set(details.get('competitor1_round_scores')),
                  _won_first_set(details.get('competitor2_round_scores')))
        return any(w == units_to_win-1 and cur >= need and cur-other >= lead
                   and (not rule.leader_won_first_set or first)
                   for (w, cur), other, first in ((one, two[1], firsts[0]), (two, one[1], firsts[1])))
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
        game = str(meta.get('game') or '').upper()
        if (rule.games and game not in {g.upper() for g in rule.games}) or game in {g.upper() for g in rule.skip_games}:
            return False
        if rule.force_best_of:
            units_to_win = rule.force_best_of//2+1
        if rule.require_format and units_to_win is None:
            return False                     # best-of unknown (best of 1, no format market): skip
        need = units_to_win or rule.units_to_win or 2
        best_of = 2*need-1
        if rule.formats and best_of not in rule.formats:
            return False
        score = _points(details, 'home_score', 'away_score')
        if score is None or max(score) != need-1:
            return False
        allowed = rule.bo5_states if best_of == 5 else rule.bo3_states
        return not allowed or f'{max(score)}-{min(score)}' in allowed
    return False


def game_text(milestone_type, details, meta=None):
    """Short game state for the trade record and the score recorder."""
    keep = ('time', 'half', 'quarter', 'clock', 'period', 'period_type', 'period_remaining_time',
            'inning', 'inning_half', 'outs', 'home_points', 'away_points', 'home_score', 'away_score',
            'home_same_game_score', 'away_same_game_score', 'home_aggregate_score', 'away_aggregate_score',
            'best_of_sets', 'best_of', 'completed_rounds', 'last_set_scoring_type')
    state = {k: details.get(k) for k in keep if details.get(k) is not None}
    meta = meta if isinstance(meta, dict) else {}
    ball = (details.get('situation') or {}).get('possession_team_id') if isinstance(details.get('situation'), dict) else None
    if ball:
        state['ball'] = ('home' if ball == meta.get('home_team_id') else
                         'away' if ball == meta.get('away_team_id') else '?')
    for side in ('home', 'away'):                # esports: rounds in the maps played (CS2 in-map score)
        periods = details.get(f'{side}_periods')
        if isinstance(periods, dict) and periods:
            state[f'{side}_rounds'] = [periods[k] for k in sorted(periods)]
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


def maps_to_win(total_maps_markets):
    """Esports maps needed to win, from the total-maps lines: 'Over 2.5' only
    = best of 3 (2); a 3.5 or 4.5 line = best of 5 (3); none = unknown."""
    strikes = []
    for m in total_maps_markets or ():
        try:
            strikes.append(float(m.get('floor_strike')))
        except (TypeError, ValueError, AttributeError):
            continue
    if not strikes:
        return None
    return 3 if max(strikes) > 3 else 2


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
    band: str                               # 'rule' (>= floor), 'test' (>= test_price) or 'data' (dry run)
    side: str = 'yes'                       # 'yes' or 'no' (prices above are then the NO prices)


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
    data_min_price; such entries are tagged 'test' (at or above the rule's
    test_price) or 'data', never traded live."""
    floor = max(policy.min_price, rule.min_price or Decimal(0))
    test = rule.test_price                   # a test floor at or above the rule never applies
    lowest = min(floor, policy.data_min_price) if data_band else floor
    spread_cap = rule.max_spread if rule.max_spread is not None else policy.max_spread
    price_cap = min(policy.max_price, rule.max_price) if rule.max_price is not None else policy.max_price
    if rule.side == 'no_trailer':
        return _pick_no_trailer(event_ticker, markets, rule, floor, test, lowest, spread_cap, price_cap)
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
        if bid is None or ask is None or ask < bid or ask-bid > spread_cap:
            continue                         # one-sided or wide book: the price is not reliable
        mid = (bid+ask)/2
        if mid < lowest or ask > price_cap:
            continue
        # A win must still clear the taker fee (one contract, unrounded per contract).
        if (ONE-ask)-Decimal('0.07')*ask*(ONE-ask) <= 0:
            continue
        band = 'rule' if mid >= floor else 'test' if test is not None and mid >= test else 'data'
        cand = Candidate(event_ticker, ticker, team, bid, ask, mid, band)
        if best is None or ask < best.ask:   # the cheapest favourite pays most
            best = cand
    return best


def _pick_no_trailer(event_ticker, markets, rule, floor, test, lowest, spread_cap, price_cap):
    """Kalshi lets us buy NO: on a 3-option soccer game with a 1-goal lead late,
    NO on the trailing team wins on a draw too (Polymarket research: Kalshi
    goal timelines, 1 loss in 286 from 88'). The trailer = the cheapest team."""
    teams = []
    for m in markets or ():
        if not isinstance(m, dict) or m.get('status') != 'active':
            continue
        ticker, team = str(m.get('ticker') or ''), str(m.get('yes_sub_title') or '')
        if not ticker or ticker.upper().endswith('-TIE') or team.strip().lower() in ('tie', 'draw'):
            continue
        bid, ask = _quote(m.get('yes_bid_dollars')), _quote(m.get('yes_ask_dollars'))
        if bid is None or ask is None or ask < bid:
            continue
        teams.append((bid+ask, ticker, team, bid, ask))
    if len(teams) < 2:
        return None
    _, ticker, team, bid, ask = min(teams)
    no_bid, no_ask = ONE-ask, ONE-bid
    mid = (no_bid+no_ask)/2
    if no_ask-no_bid > spread_cap or mid < lowest or no_ask > price_cap:
        return None
    if (ONE-no_ask)-Decimal('0.07')*no_ask*(ONE-no_ask) <= 0:
        return None
    band = 'rule' if mid >= floor else 'test' if test is not None and mid >= test else 'data'
    return Candidate(event_ticker, ticker, team, no_bid, no_ask, mid, band, 'no')


def book_market(ticker, team, book, *, expected_expiration_time=None):
    """A market dict from the live order book (best YES bid; YES ask = 1 - best
    NO bid), so the trigger is re-checked on the book we would fill from."""
    def best(levels):
        prices = []
        for level in levels or ():
            try:
                price, size = Decimal(str(level[0])), Decimal(str(level[1]))
            except (ArithmeticError, ValueError, TypeError, IndexError):
                continue
            if price.is_finite() and size.is_finite() and size > 0:
                prices.append(price)
        return max(prices) if prices else None
    yes_bid, no_bid = best(book.get('yes_dollars')), best(book.get('no_dollars'))
    return dict(ticker=ticker, yes_sub_title=team, status='active',
                yes_bid_dollars=str(yes_bid) if yes_bid is not None else None,
                yes_ask_dollars=str(ONE-no_bid) if no_bid is not None else None,
                expected_expiration_time=expected_expiration_time)


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
