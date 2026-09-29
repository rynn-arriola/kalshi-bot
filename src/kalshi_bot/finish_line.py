"""D-161 step 3 (phase 3): drive contracts past Kalshi's $1-per-contract floor.

Kalshi pays a program only if it earns $1 or more on that contract. The
selector used to rank contracts by reward rate per dollar and rotate across
hundreds of them, so almost none reached $1 (2026-09-28: 150 programs, ~$0.80
in total, paid $0). This policy, fed by the LIP meter's earnings per program,
ranks new entries so contracts we have started finish first, then new
contracts that can reach $1 fastest, then contracts already past $1; and it
blocks new entries in contracts that cannot reach $1 before they stop
earning even if we rest half of the remaining time. Ordering and entry
eligibility only: every existing loss check still applies, and resting
orders are never canceled by this policy.
"""
from decimal import Decimal, localcontext

from .lip_meter import MINIMUM_PAYOUT
from .ranking import seconds
from .values import utc

TARGET_USD = Decimal('1.25')      # $1 plus a margin for estimate error
COMMIT_SHARE = Decimal('0.5')     # a target should need at most half the time left

STARTED, NEW, CLEARED = 0, 1, 2   # priority tiers, best first


class FinishLine:
    def __init__(self, meter):
        self.meter = meter
        self.planned = self.blocked = 0

    def earned(self, program_id):
        row = self.meter.programs.get(program_id)
        return row['earned'] if row is not None else Decimal(0)

    def plan(self, row, now):
        """(tier, key) for one ranked entry row, or None when the contract
        cannot reach the target in time (its entry is then blocked).
        Within a tier, a smaller key ranks first."""
        earned = self.earned(row.program_id)
        rate = row.gross_hourly_usd
        if earned >= MINIMUM_PAYOUT:
            self.planned += 1
            return CLEARED, -(rate or Decimal(0))     # past $1: normal rate order
        until = row.earning_until or row.program_end
        with localcontext() as ctx:
            ctx.prec = 40
            hours_left = seconds(until-utc(now))/3600
            if rate is None or rate <= 0:
                self.blocked += 1
                return None
            needed = (TARGET_USD-earned)/rate          # hours of resting still needed
            if needed > hours_left*COMMIT_SHARE:
                self.blocked += 1
                return None
        self.planned += 1
        return (STARTED if earned > 0 else NEW), needed

    def status(self, now):
        return dict(target_usd=str(TARGET_USD), commit_share=str(COMMIT_SHARE),
                    planned=self.planned, blocked=self.blocked, authorized=False)
