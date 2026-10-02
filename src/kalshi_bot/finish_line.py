"""D-161 step 3 (phase 3): drive contracts past Kalshi's $1-per-contract floor.

Kalshi pays a program only if it earns $1 or more on that contract. Ranking
every contract that had ever earned a cent as "started" still spread 3 hours
over 131 contracts (median 0.27 resting hours each; $1 needs 22-36). So new
entries now go only to a bounded, saved **project list**: contracts we have
committed to finish past $1.

- A project keeps its place until the meter shows $1 earned (cleared) or it
  can no longer reach the target in time (dropped); it is never displaced by
  a better-looking contract.
- A new contract becomes a project only while the list has room and only if
  it can reach the target needing at most half its remaining earning time.
- Order (operator 2026-09-30): projects first; then contracts already past $1
  whose reward is juicy (payment is guaranteed and every further cent is
  paid); then everything else in the normal reward ranking.
- Everything else is blocked (``project_list_full``), so effort is not spread.
  Only projects with working orders count toward the list limit; blocked
  projects keep their place without holding entry slots idle.

Ordering and entry eligibility only: every loss check still applies. The list
is saved beside the ledger so restarts keep it, and launch keeps projects in
the watched scope.
"""
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext

from .lip_meter import MINIMUM_PAYOUT
from .ranking import seconds
from .values import InvalidData, utc

# Operator 2026-09-30: aim for $1.50 per market so estimate error cannot leave
# a contract under Kalshi's $1 floor; earnings above $1 are paid in full.
TARGET_USD = Decimal('1.50')
COMMIT_SHARE = Decimal('0.5')     # a project should need at most half the time left
# The entry cap holds 25 buy/sell pairs; 5 more give a little room. Only
# projects with working orders count toward it (operator 2026-10-01): blocked
# projects (pull cooldown, entry filters) keep their place and first priority
# but no longer hold entry slots idle (12 of 30 did, leaving 18 of 25 pairs
# used). MAX_LIST bounds the whole list so effort is not spread: at 50
# contracts cash covers about 25 working pairs, plus 10 places for blocked
# projects (operator 2026-10-01: 50 spread resting time too thin).
MAX_PROJECTS = 30
# D-169 (2026-10-01): 35 was too small: only ~40% of projects can rest at a
# time, so 35 filled with idle projects and turned new markets away (10-15
# working). 50 kept ~21 working; back to 50 until the idle cause is fixed.
MAX_LIST = 50
CLOSED_KEPT = 200                 # recently finished or dropped projects, for reports
# D-168 (2026-10-01): metered progress is never orphaned. At launch a market
# with at least this much earned but under the target rejoins the list (a
# shrink of MAX_LIST had discarded the saved list and dropped a $0.40 market).
ADOPT_EARNED = Decimal('0.25')
TRIMMED = 'list_limit_trimmed'
SANITY_LIST = 1000                # more saved projects than this is corruption

# Priority tiers, best first (operator 2026-09-30): projects still working
# toward the target; then markets already past $1 whose reward is juicy; then
# new projects and other markets past $1 together, kept in the board's normal
# reward ranking (the selection sort is stable and their key is equal).
PROJECT, JUICY, RANKED = 0, 1, 2
JUICY_RATE_USD = Decimal('0.05')  # $/hour for our pair: about our top 10%
FULL = 'project_list_full'
CANNOT = 'cannot_reach_payout_minimum'
AVOID = 'sweep_prone_market_type'

# Finding 224 (2026-09-30): market types behind ~8 of 9 bad fills. Their
# prices jump on scheduled data (app-store ranks ~03:00 UTC, card-spend and
# fuel/rate/port data), when one order sweeps the whole book with no warning.
# Matched on the series (ticker before the first '-').
AVOID_TYPES = (('app_rank', re.compile(r'APP$')), ('card_spend', re.compile(r'CC$')),
               ('port_teu', re.compile(r'PORT.*TEU|TEU$')), ('diesel', re.compile(r'DIESEL')),
               ('mortgage', re.compile(r'MORT')),
               # D-171 (2026-10-02): Carbon Arc sector ad spend, like card spend;
               # one seller swept 865 contracts at 77c, leaving an 8c bid.
               ('ad_spend', re.compile(r'ADS$')))


def avoided_type(ticker):
    series = ticker.split('-')[0]
    return next((name for name, pattern in AVOID_TYPES if pattern.search(series)), None)


class FinishLine:
    def __init__(self, meter, path=None):
        self.meter, self.path = meter, path
        self.projects = {}      # program_id -> dict(ticker, until, added_at)
        self.working = frozenset()   # tickers with our working orders (observe_working)
        self.closed = []        # dict(program_id, ticker, until, added_at, closed_at, reason, earned)
        self.planned = self.blocked = self.save_failures = 0

    def earned(self, program_id):
        row = self.meter.programs.get(program_id) if self.meter is not None else None
        return row['earned'] if row is not None else Decimal(0)

    def _needed(self, earned, rate, until, now):
        """Resting hours still needed to reach the target, or None when the
        contract cannot reach it needing at most half its remaining time."""
        with localcontext() as ctx:
            ctx.prec = 40
            if rate is None or rate <= 0:
                return None
            needed = (TARGET_USD-earned)/rate
            if needed > seconds(until-utc(now))/3600*COMMIT_SHARE:
                return None
            return needed

    def hopeless(self, program_id, rate, until, now):
        """True when a contract cannot reach $1 even resting all of its
        remaining earning time at ``rate`` (or its measured rate, if higher):
        our orders there are then pure fill risk (stop the waste)."""
        earned = self.earned(program_id)
        if earned >= MINIMUM_PAYOUT:
            return False
        row = self.meter.programs.get(program_id)
        with localcontext() as ctx:
            ctx.prec = 40
            measured = (row['earned']/row['seconds']*3600
                        if row is not None and row['seconds'] >= 600 else Decimal(0))
            best = max(rate or Decimal(0), measured)
            return earned+best*seconds(until-utc(now))/3600 < MINIMUM_PAYOUT

    def review(self, now):
        """Close projects that cleared $1 or whose earning time ended."""
        now, changed = utc(now), False
        for pid, project in list(self.projects.items()):
            earned = self.earned(pid)
            if avoided_type(project['ticker']):
                self._close(pid, AVOID, now)
                changed = True
            elif earned >= TARGET_USD:
                self._close(pid, 'cleared', now)
                changed = True
            elif project['until'] <= now:
                self._close(pid, 'ended_paid' if earned >= MINIMUM_PAYOUT else 'ended_under_minimum', now)
                changed = True
        if changed:
            self.save()

    def _close(self, pid, reason, now):
        project = self.projects.pop(pid)
        self.closed.append(dict(program_id=pid, ticker=project['ticker'], until=project['until'],
            added_at=project['added_at'], closed_at=utc(now), reason=reason, earned=self.earned(pid)))
        del self.closed[:-CLOSED_KEPT]

    def plan(self, row, now):
        """(tier, key) for one ranked entry row (smaller ranks first), or a
        blocker code when the row must not be entered."""
        pid, earned, rate = row.program_id, self.earned(row.program_id), row.gross_hourly_usd
        until = row.earning_until or row.program_end
        if avoided_type(row.ticker):
            if pid in self.projects:
                self._close(pid, AVOID, now)
                self.save()
            self.blocked += 1
            return AVOID
        if pid in self.projects:
            # A committed project continues while $1 is reachable at all.
            if self.hopeless(pid, rate, until, now):
                self.drop(pid, now)
                self.blocked += 1
                return CANNOT
            self.planned += 1
            with localcontext() as ctx:
                ctx.prec = 40
                return PROJECT, (max(Decimal(0), TARGET_USD-earned)/rate if rate and rate > 0
                                 else Decimal(10**9))
        if earned >= MINIMUM_PAYOUT:
            self.planned += 1
            if rate is not None and rate >= JUICY_RATE_USD:
                return JUICY, -rate
            return RANKED, 0
        needed = self._needed(earned, rate, until, now)
        if needed is None:
            self.blocked += 1
            return CANNOT
        if not self.room():
            self.blocked += 1
            return FULL
        self.planned += 1
        return RANKED, 0

    def claim(self, row, now):
        """At the moment an entry is chosen: projects and cleared contracts
        pass; a new contract becomes a project if the list still has room."""
        pid = row.program_id
        if avoided_type(row.ticker):
            return False
        if pid in self.projects or self.earned(pid) >= MINIMUM_PAYOUT:
            return True
        if not self.room():
            return False
        self.projects[pid] = dict(ticker=row.ticker, until=row.earning_until or row.program_end,
                                  added_at=utc(now))
        self.working = self.working | {row.ticker}   # its orders are about to be placed
        self.save()
        return True

    def observe_working(self, tickers):
        """The markets where we have working orders now (from the portfolio view)."""
        self.working = frozenset(tickers)

    def working_projects(self):
        return sum(1 for p in self.projects.values() if p['ticker'] in self.working)

    def room(self):
        """A new project may join while fewer than MAX_PROJECTS projects have
        working orders and the whole list is under MAX_LIST."""
        return len(self.projects) < MAX_LIST and self.working_projects() < MAX_PROJECTS

    def drop(self, program_id, now):
        """Stop the waste: a project that can no longer reach $1 leaves the list."""
        if program_id in self.projects:
            self._close(program_id, CANNOT, now)
            self.save()

    def tickers(self):
        return tuple(sorted({p['ticker'] for p in self.projects.values()}))

    def has_ticker(self, ticker):
        """Cheap membership for schedulers (at most MAX_LIST projects)."""
        return any(p['ticker'] == ticker for p in self.projects.values())

    def save(self):
        if self.path is None:
            return
        try:
            temp = self.path.with_suffix('.tmp')
            stamp = lambda d: {k: (v.isoformat() if isinstance(v, datetime) else str(v)
                                   if isinstance(v, Decimal) else v) for k, v in d.items()}
            temp.write_text(json.dumps(dict(
                projects={pid: stamp(p) for pid, p in self.projects.items()},
                closed=[stamp(c) for c in self.closed])), encoding='utf-8')
            os.replace(temp, self.path)
        except OSError:
            self.save_failures += 1

    def load(self):
        """Restore the list; a missing or corrupt file starts empty."""
        try:
            if self.path is None:
                return self
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            when = lambda value: utc(datetime.fromisoformat(value))
            projects = {pid: dict(ticker=p['ticker'], until=when(p['until']), added_at=when(p['added_at']))
                        for pid, p in raw['projects'].items()}
            closed = [dict(program_id=c['program_id'], ticker=c['ticker'], until=when(c['until']),
                           added_at=when(c['added_at']), closed_at=when(c['closed_at']),
                           reason=c['reason'], earned=Decimal(c['earned'])) for c in raw['closed']]
            if (len(projects) > SANITY_LIST or any(not isinstance(k, str) or not isinstance(p['ticker'], str)
                                                    for k, p in projects.items())):
                raise ValueError('invalid project list')
            self.projects, self.closed = projects, closed[-CLOSED_KEPT:]
        except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation, InvalidData):
            self.projects, self.closed = {}, []
            return self
        if len(self.projects) > MAX_LIST:
            # A lowered limit keeps the best-earning projects; never discard all.
            now = datetime.now(timezone.utc)
            keep = set(sorted(self.projects, key=lambda pid: -self.earned(pid))[:MAX_LIST])
            for pid in [pid for pid in self.projects if pid not in keep]:
                self._close(pid, TRIMMED, now)
            self.save()
        return self

    def adopt_progress(self, now):
        """Launch: markets with metered progress toward the target rejoin the
        list while it has room, best first. Not avoided types, not markets
        dropped as hopeless or avoided, not past the target or ended."""
        now = utc(now)
        if self.meter is None:
            return 0
        refused = {c['program_id'] for c in self.closed if c['reason'] in (CANNOT, AVOID)}
        candidates = sorted(((row['earned'], pid, row) for pid, row in self.meter.programs.items()
                             if ADOPT_EARNED <= row['earned'] < TARGET_USD and row['end'] > now
                             and pid not in self.projects and pid not in refused
                             and not avoided_type(row['ticker'])), key=lambda item: -item[0])
        added = 0
        for _, pid, row in candidates:
            if len(self.projects) >= MAX_LIST:
                break
            self.projects[pid] = dict(ticker=row['ticker'], until=row['end'], added_at=now)
            added += 1
        if added:
            self.save()
        return added

    def unclaim(self, program_id):
        """Undo a claim made in this selection whose entry was then deferred,
        so a project that never rested does not hold a place on the list."""
        if self.projects.pop(program_id, None) is not None:
            self.save()

    def status(self, now):
        now = utc(now)
        rows = sorted(((pid, p) for pid, p in self.projects.items()),
                      key=lambda item: -self.earned(item[0]))
        return dict(target_usd=str(TARGET_USD), max_projects=MAX_PROJECTS, max_list=MAX_LIST,
            active=len(self.projects), working=self.working_projects(),
            planned=self.planned, blocked=self.blocked,
            save_failures=self.save_failures,
            cleared_total=sum(1 for c in self.closed if c['reason'] in ('cleared', 'ended_paid')),
            dropped_total=sum(1 for c in self.closed if c['reason'] not in ('cleared', 'ended_paid')),
            projects=[dict(ticker=p['ticker'], earned_usd=str(round(self.earned(pid), 4)),
                           to_dollar=str(round(max(Decimal(0), MINIMUM_PAYOUT-self.earned(pid)), 4)),
                           to_target=str(round(max(Decimal(0), TARGET_USD-self.earned(pid)), 4)),
                           hours_left=round(float(seconds(p['until']-now))/3600, 1))
                      for pid, p in rows],
            authorized=False)
