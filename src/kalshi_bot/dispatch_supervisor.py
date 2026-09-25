"""Event-driven lifetime owner for the explicitly configured dispatcher."""
import asyncio
import math

from .dispatch import MutationDispatcher
from .dispatch_sources import InventoryDispatchSource
from .mutation_outcomes import MutationOutcomeOwner
from .values import InvalidData


class DispatchSupervisor:
    def __init__(self, source, dispatcher, *, offline_fixture=False):
        if (not isinstance(source, InventoryDispatchSource)
                or not (offline_fixture is True or source.runtime.live_components_enabled)
                or not isinstance(dispatcher, MutationDispatcher)
                or dispatcher.writer is not source.runtime.writer
                or dispatcher.refresh != source.refresh
                or dispatcher.after_result != source._dispatch_result
                or dispatcher.executor.validate_proof != source.validate_proof
                or dispatcher.executor.after_outcome != source._mutation_observed
                or not isinstance(dispatcher.executor.invoke, MutationOutcomeOwner)
                or dispatcher.executor.invoke.notify != source._mutation_observed
                or dispatcher.executor.invoke.budget is not dispatcher.budget
                or dispatcher.executor.invoke.clock_pair != dispatcher.clock_pair
                or dispatcher.status().active is not None
                or dispatcher.status().failed or dispatcher.status().stopping
                or source._stopped or source.runtime.used
                or source.runtime.dispatch_supervisor is not None):
            raise InvalidData('unused matching offline dispatch owners required')
        self.source, self.dispatcher = source, dispatcher
        self.wake = asyncio.Event()
        self.task = None
        self.used = self.running = self.stopping = self.failed = False
        self.turns = 0
        self.last_state = None
        self.last_outcome = None

    def request(self, ticker, priority):
        if self.stopping or self.failed or self.source.runtime.stop_requested.is_set():
            return False
        if ticker not in self.source.runtime.engine.market_shard:
            raise InvalidData('dispatch market outside runtime scope')
        try:
            changed = self.dispatcher.submit(ticker, priority)
        except BaseException:
            self.failed = True
            self.stop()
            raise
        if changed:
            self.wake.set()
        return changed

    def changed(self):
        if not self.stopping:
            self.wake.set()

    def stop(self):
        self.stopping = True
        self.source.stop()
        self.dispatcher.stop()
        self.wake.set()

    async def _wait(self, delay=None):
        if delay is None:
            await self.wake.wait()
        else:
            if type(delay) not in (float, int) or not math.isfinite(delay) or delay < 0:
                raise InvalidData('invalid dispatch wait delay')
            try:
                async with asyncio.timeout(max(.01, delay)):
                    await self.wake.wait()
            except TimeoutError:
                pass

    async def run(self):
        if self.used:
            raise InvalidData('dispatch supervisor cannot be reused')
        self.used = self.running = True
        self.task = asyncio.current_task()
        try:
            while not self.stopping:
                self.wake.clear()
                self.last_state = 'RUNNING'
                result = await self.dispatcher.run_one()
                self.turns += 1
                self.last_state = result.state
                if result.state != 'IDLE':
                    self.last_outcome = dict(state=result.state, ticker=result.ticker,
                        priority=result.priority, blockers=list(result.blockers),
                        observed_at=self.source.runtime.now().isoformat(), historical_only=True)
                if result.state in {'FAILED', 'INTERRUPTED'} or 'dispatcher_busy' in result.blockers:
                    if not self.stopping:
                        raise InvalidData('dispatch owner failed or unexpectedly stopped')
                if self.stopping:
                    break
                if result.state in {'IDLE', 'WAITING'}:
                    await self._wait(result.retry_after if result.state == 'WAITING' else None)
                else:
                    await asyncio.sleep(0)  # Yield between bounded queue turns.
            if self.failed:
                raise InvalidData('dispatch supervisor failed')
        except BaseException as exc:
            if not isinstance(exc, asyncio.CancelledError) or not self.stopping:
                self.failed = True
            raise
        finally:
            self.stop()
            try:
                await self.dispatcher.close()
            finally:
                self.running = False

    async def close(self):
        self.stop()
        if self.task is None:
            await self.dispatcher.close()
            return
        if self.task is asyncio.current_task():
            raise InvalidData('dispatch owner cannot join itself')
        cancelled = False
        while not self.task.done():
            try:
                await asyncio.wait((self.task,))
            except asyncio.CancelledError:
                cancelled = True
        try:
            self.task.result()
        except asyncio.CancelledError:
            pass  # Its runtime owner still observes that cancellation.
        if cancelled:
            raise asyncio.CancelledError

    def status(self):
        state = self.dispatcher.status()
        return dict(running=self.running, stopping=self.stopping, failed=self.failed,
            turns=self.turns, last_state=self.last_state, queued=len(state.queued),
            active=state.active is not None, high_water=state.high_water, live_ready=False,
            last_outcome=self.last_outcome, last_entry_block=self.source.last_entry_block,
            risk_drain_pending=self.source.risk_drain_pending,
            risk_cancel_deferrals=self.source.risk_cancel_deferrals,
            entry_block_counts=dict(self.source.entry_block_counts))
