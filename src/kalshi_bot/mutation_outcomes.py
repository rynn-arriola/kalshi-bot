"""Bounded injected-write outcome routing. No HTTP client or retry loop."""
import asyncio
from dataclasses import dataclass
import inspect
import math

from .execution import acknowledgement, validate_request
from .values import InvalidData, integer
from .write_budget import WriteBudget


class MutationHTTPFailure(InvalidData):
    """Transport reports only a numeric non-success status, never a raw body.

    An observed HTTP failure is not durable rejection/no-fill evidence. The
    executor still records UNKNOWN and holds its authority for reconciliation.
    """
    def __init__(self, status):
        self._status = integer(status, 300, 599)
        super().__init__('mutation_http_failure')

    @property
    def status(self):
        return self._status


@dataclass(frozen=True)
class MutationNotice:
    kind: str
    ticker: str
    subject_id: str
    subaccount: int
    exchange_index: int
    outcome: str
    http_status: int | None = None


class MutationOutcomeOwner:
    """One retained scalar notice, no exception/payload/traceback history.

    Invoked only by the sole executor, after its durable SENDING transition.
    Notifications revoke account proof and request coalesced reconciliation;
    neither acknowledgement nor notification releases command authority.
    """
    def __init__(self, budget, *, invoke, clock_pair, notify,
                 pause_seconds=1., offline_fixture=False):
        if (offline_fixture is not True or not isinstance(budget, WriteBudget)
                or not callable(invoke) or not callable(clock_pair)
                or not callable(notify) or inspect.iscoroutinefunction(notify)):
            raise InvalidData('offline single-budget and synchronous notification required')
        if (type(pause_seconds) not in (int, float) or not math.isfinite(pause_seconds)
                or not 0 < pause_seconds <= 60):
            raise InvalidData('bounded explicit local pause required')
        self.budget, self.invoke, self.clock_pair = budget, invoke, clock_pair
        self.notify, self.pause_seconds = notify, pause_seconds
        self.last = None
        self.busy = False

    def _notify(self, notice):
        self.last = notice
        result = self.notify(notice)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise InvalidData('mutation notification must not await')

    async def __call__(self, kind, request):
        if self.busy:
            raise InvalidData('mutation outcome owner busy')
        validate_request(kind, request)
        # Detach scalar scope before yielding to the injected transport. A
        # mutated request/exception cannot redirect the throttle to another shard.
        ticker = request['market_ticker' if kind == 'cancel' else 'ticker']
        subject = request['order_id' if kind == 'cancel' else 'client_order_id']
        scope = (kind, ticker, subject, request['subaccount'], request['exchange_index'])
        durable_request = dict(request)
        self.busy = True
        try:
            try:
                reply = await self.invoke(kind, request)
                ack = acknowledgement(kind, durable_request, reply)
            except BaseException as exc:
                status = exc.status if type(exc) is MutationHTTPFailure else None
                if status is not None:
                    integer(status, 300, 599)
                outcome = ('rate_limited' if status == 429 else 'http_failure' if status is not None
                           else 'interrupted' if isinstance(exc, asyncio.CancelledError)
                           else 'uncertain')
                notice = MutationNotice(*scope, outcome, status)
                try:
                    if status == 429:
                        self.budget.pause_429(shard=scope[4], seconds=self.pause_seconds,
                                              now=self.clock_pair())
                finally:
                    # Even a quota/clock failure must request recovery. The
                    # executor owns durable UNKNOWN despite callback failure.
                    self._notify(notice)
                raise
            self._notify(MutationNotice(*scope, 'ack'))
            return ack
        finally:
            self.busy = False
