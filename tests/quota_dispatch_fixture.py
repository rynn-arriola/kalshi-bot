"""Real shared quota owner with blocked synthetic wire; no account access."""
import asyncio
import json
from threading import Event

from kalshi_bot.rest import WireResponse
from kalshi_bot.write_quota_source import WriteQuotaSource
from test_bot_quota import setup, LIMITS, COSTS, eventually


class ObservedQuotaFixture:
    def __init__(self):
        self.hold = False
        self.entered, self.release = Event(), Event()
        self.task = None
        def wire(url, *_):
            if self.hold and url.endswith('endpoint_costs'):
                self.entered.set()
                if not self.release.wait(5):
                    raise TimeoutError('fixture quota refresh not released')
            return WireResponse(200, json.dumps(
                COSTS if url.endswith('endpoint_costs') else LIMITS).encode())
        self.clock, self.reads, self.guard = setup(wire=wire)
        self.source = WriteQuotaSource(self.reads, shards=(0, 1), offline_fixture=True)

    async def attach(self, dispatcher):
        await self.reads.refresh_budget()
        self.clock.t += 1
        dispatcher.budget = self.source.budget
        dispatcher.clock_pair = self.source.clock_pair
        return dispatcher.budget

    async def begin_refresh(self):
        self.hold = True
        self.task = asyncio.create_task(self.reads.refresh_budget())
        await eventually(self.entered.is_set)

    async def finish_refresh(self):
        self.release.set()
        await self.task
        self.clock.t += 1

    async def close(self):
        self.release.set()
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)
        await self.reads.close()
