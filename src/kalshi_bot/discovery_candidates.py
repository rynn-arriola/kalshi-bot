"""Poly-inspired bounded head/tail discovery; not an order/subscription command."""
from dataclasses import dataclass
from decimal import Decimal, localcontext

from .incentive_discovery import IncentiveCatalog
from .ranking import seconds
from .values import InvalidData, identity, integer, utc


@dataclass(frozen=True)
class DiscoveryCandidates:
    tickers: tuple[str, ...]
    protected: tuple[str, ...]
    deferred: int
    source: IncentiveCatalog | None
    authorized: bool = False


class CandidateDiscovery:
    def __init__(self):
        self.cursor = 0

    def choose(self, catalog, *, now, budget, protected=(), incumbents=(), eligible=None):
        """Budget is engineering capacity, NOT desired market/order occupancy.

        Pool/time/target is only a cheap exploration hint. Actual selection still
        requires fresh book competition, fees, event deadlines and account gates.
        """
        now = utc(now)
        integer(budget,1,1024)
        for values in (protected,incumbents):
            if type(values) is not tuple or len(values) > 1024 or len(set(values)) != len(values):
                raise InvalidData('bounded unique discovery owner list required')
            for ticker in values: identity(ticker)
        if len(protected) > budget:
            raise InvalidData('protected owners exceed capacity; never evict for discovery')
        retained = tuple(sorted(protected))
        if catalog is not None and not isinstance(catalog,IncentiveCatalog):
            raise InvalidData('typed incentive catalog required')
        if catalog is None or not catalog.observed_at <= now < catalog.valid_until:
            return DiscoveryCandidates(retained,retained,0,None)
        if len(catalog.observations) > 10000:
            raise InvalidData('bounded incentive catalog required')
        if eligible is not None and (type(eligible) is not frozenset or len(eligible) > 10000):
            raise InvalidData('bounded eligible candidate set required')
        ranked = []
        with localcontext() as ctx:
            ctx.prec = 40
            for ticker, observation in catalog.observations.items():
                if eligible is not None and ticker not in eligible:
                    continue
                scores = [Decimal(p.pool_centicents)/seconds(p.end-p.start)/p.target
                    for p in observation.programs if not p.paid_out and p.start <= now < p.end
                    and p.max_reward_centicents is None and p.pool_centicents > 0]
                if scores: ranked.append((-max(scores),ticker))
        ranked.sort()
        eligible = {ticker for _,ticker in ranked}
        selected = list(retained)
        chosen = set(selected)
        # Stable eligible incumbents first; unprotected additions may be skipped,
        # but this plan never releases their orders or subscription ownership.
        for ticker in incumbents:
            if ticker in eligible and ticker not in chosen and len(selected) < budget:
                selected.append(ticker)
                chosen.add(ticker)
        remaining = [ticker for _,ticker in ranked if ticker not in chosen]
        slots = budget-len(selected)
        head = min(slots,max(1,min(5,budget//5))) if slots else 0
        selected.extend(remaining[:head])
        tail, slots = remaining[head:],slots-head
        if tail and slots:
            start = self.cursor % len(tail)
            count = min(slots,len(tail))
            selected.extend(tail[(start+i) % len(tail)] for i in range(count))
            self.cursor = (start+count) % len(tail)
        return DiscoveryCandidates(tuple(selected),retained,len(eligible-set(selected)),catalog)
