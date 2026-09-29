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
  it can reach $1.25 needing at most half its remaining earning time; the
  fastest to $1.25 are taken first.
- Contracts already past $1 are paid for every further cent, so they may use
  entry slots projects cannot use right now (lowest priority).
- Everything else is blocked (``project_list_full``), so effort is not spread.

Ordering and entry eligibility only: every loss check still applies. The list
is saved beside the ledger so restarts keep it, and launch keeps projects in
the watched scope.
"""
import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from .lip_meter import MINIMUM_PAYOUT
from .ranking import seconds
from .values import InvalidData, utc

TARGET_USD = Decimal('1.25')      # $1 plus a margin for estimate error
COMMIT_SHARE = Decimal('0.5')     # a project should need at most half the time left
# The entry cap holds 25 buy/sell pairs; 5 more let a project that is
# temporarily blocked (pull cooldown, sweep filter) keep its place without
# leaving an entry slot idle.
MAX_PROJECTS = 30
CLOSED_KEPT = 200                 # recently finished or dropped projects, for reports

PROJECT, NEW, CLEARED = 0, 1, 2   # priority tiers, best first
FULL = 'project_list_full'
CANNOT = 'cannot_reach_payout_minimum'


class FinishLine:
    def __init__(self, meter, path=None):
        self.meter, self.path = meter, path
        self.projects = {}      # program_id -> dict(ticker, until, added_at)
        self.closed = []        # dict(program_id, ticker, until, added_at, closed_at, reason, earned)
        self.planned = self.blocked = self.save_failures = 0

    def earned(self, program_id):
        row = self.meter.programs.get(program_id)
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
            if earned >= MINIMUM_PAYOUT or project['until'] <= now:
                self._close(pid, 'cleared' if earned >= MINIMUM_PAYOUT else 'ended_under_minimum', now)
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
            return CLEARED, -(rate or Decimal(0))
        needed = self._needed(earned, rate, until, now)
        if needed is None:
            self.blocked += 1
            return CANNOT
        if len(self.projects) >= MAX_PROJECTS:
            self.blocked += 1
            return FULL
        self.planned += 1
        return NEW, needed

    def claim(self, row, now):
        """At the moment an entry is chosen: projects and cleared contracts
        pass; a new contract becomes a project if the list still has room."""
        pid = row.program_id
        if pid in self.projects or self.earned(pid) >= MINIMUM_PAYOUT:
            return True
        if len(self.projects) >= MAX_PROJECTS:
            return False
        self.projects[pid] = dict(ticker=row.ticker, until=row.earning_until or row.program_end,
                                  added_at=utc(now))
        self.save()
        return True

    def drop(self, program_id, now):
        """Stop the waste: a project that can no longer reach $1 leaves the list."""
        if program_id in self.projects:
            self._close(program_id, CANNOT, now)
            self.save()

    def tickers(self):
        return tuple(sorted({p['ticker'] for p in self.projects.values()}))

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
            if (len(projects) > MAX_PROJECTS or any(not isinstance(k, str) or not isinstance(p['ticker'], str)
                                                    for k, p in projects.items())):
                raise ValueError('invalid project list')
            self.projects, self.closed = projects, closed[-CLOSED_KEPT:]
        except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation, InvalidData):
            self.projects, self.closed = {}, []
        return self

    def status(self, now):
        now = utc(now)
        rows = sorted(((pid, p) for pid, p in self.projects.items()),
                      key=lambda item: -self.earned(item[0]))
        return dict(target_usd=str(TARGET_USD), max_projects=MAX_PROJECTS,
            active=len(self.projects), planned=self.planned, blocked=self.blocked,
            save_failures=self.save_failures,
            cleared_total=sum(1 for c in self.closed if c['reason'] == 'cleared'),
            dropped_total=sum(1 for c in self.closed if c['reason'] != 'cleared'),
            projects=[dict(ticker=p['ticker'], earned_usd=str(round(self.earned(pid), 4)),
                           to_dollar=str(round(max(Decimal(0), MINIMUM_PAYOUT-self.earned(pid)), 4)),
                           hours_left=round(float(seconds(p['until']-now))/3600, 1))
                      for pid, p in rows],
            authorized=False)
