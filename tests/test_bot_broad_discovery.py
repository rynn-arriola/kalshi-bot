"""Broad observation is separate from account/write capacity. No venue calls."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from kalshi_bot.account import normalize_snapshot
from kalshi_bot.dispatch import ENTRY_PAIR, SAFETY_CANCEL
from kalshi_bot.runtime import RecoveryRuntime, readonly_reader_factory
from kalshi_bot.transport import topology
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_engine import NOW, program, snapshot
from test_bot_selection import terms


async def noop(*args):
    pass


class BroadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'fixture.db').start()
        self.tickers = tuple(f'M{i:04}' for i in range(1024))
        self.r = RecoveryRuntime(self.writer,None,None,tickers=self.tickers,subaccount=0,
            history_start=NOW-timedelta(hours=1),now=lambda:NOW,clock=lambda:100.,
            evaluate=noop,deadline_handler=noop,lifecycle_handler=noop,broad_discovery=True)
        self.s = self.r.attach_selection(offline_fixture=True)
        self.s.start()
        self.r.account.connect_generation()
        self.r.engine.begin_private_epoch()
        self.window = await self.writer.observe(NOW)
        snap = normalize_snapshot((),(),dict(balance_dollars='500',updated_ts=1),subaccount=0)
        await self.r.account.finish_reconciliation(self.r.account.begin_reconciliation(NOW),snap,NOW)

    async def asyncTearDown(self):
        self.r.dispatch_supervisor = None
        self.r.engine.stop()
        await self.writer.close()
        self.temp.cleanup()

    async def populate(self, count=1024):
        for i, ticker in enumerate(self.tickers[:count]):
            self.r.management.set_terms(replace(terms(),ticker=ticker))
            self.s.set_programs(ticker,(program(ticker=ticker,pool_centicents=5000000),),
                observed_at=NOW,valid_until=NOW+timedelta(minutes=5))
            if i % 32 == 0:
                await asyncio.sleep(0)
        for name, shard in self.r.engine.shards.items():
            generation = self.r.engine.begin_book_epoch(name)
            for seq, ticker in enumerate(sorted(set(shard.tickers)&set(self.tickers[:count])),1):
                self.r.engine.submit_book(name,snapshot(ticker,seq),generation=generation)
                if seq % 32 == 0:
                    await asyncio.sleep(0)
        while any(self.r.engine.public.values()) or self.r.engine.dirty.pending:
            await self.r.engine.step()

    async def test_full_scope_ranked_with_unchanged_order_and_money_limits(self):
        await self.populate()
        proposal = await self.s.propose(window=self.window,free_cash=D(500))
        self.assertEqual(len(self.s.selector.board.markets),1024)
        self.assertEqual(len(proposal.additions),15)
        self.assertEqual(self.writer.market_capacity,128)
        self.assertEqual(self.window.cap,30)
        self.assertFalse(await self.writer.mutations())
        with self.assertRaises(InvalidData): self.r.attach_admission(offline_fixture=True)

    async def test_inventory_cache_reuses_exact_revision_and_invalidates_on_write(self):
        await self.populate(1)
        original = self.writer.market_inventory
        with patch.object(self.writer,'market_inventory',AsyncMock(wraps=original)) as read:
            await self.r.management.refresh(self.tickers[0])
            self.assertEqual(read.await_count,0)
            await self.writer.observe(NOW)
            await self.r.management.refresh(self.tickers[0])
            self.assertEqual(read.await_count,1)
            await self.r.management.refresh(self.tickers[0])
            self.assertEqual(read.await_count,1)

    async def test_many_book_updates_queue_one_ranked_key_and_respect_safety_work(self):
        # This test isolates the post-checkpoint dispatcher scheduling boundary.
        for ticker in self.tickers: self.s.initial_ranking.observe(ticker)
        queued = []
        state = SimpleNamespace(active=None,queued=(),stopping=False,failed=False)
        self.r.dispatch_supervisor = SimpleNamespace(
            dispatcher=SimpleNamespace(status=lambda:state), request=lambda *args:queued.append(args))
        self.r.accounting_result = SimpleNamespace(released=True,window=self.window)
        self.s.refresh = lambda ticker: None
        self.s.current = lambda ticker: True
        self.r.management.refresh = AsyncMock()
        self.r._request_inventory_dispatch = lambda ticker:None
        self.s.propose = AsyncMock(return_value=SimpleNamespace(blockers=(),
            additions=(SimpleNamespace(ticker=self.tickers[-1]),)))
        for ticker in self.tickers: await self.r._evaluate(ticker,None,1)
        self.assertFalse(queued)
        with patch.object(RecoveryRuntime,'entry_allowed',property(lambda _:True)):
            await self.r._ranked_entry_turn()
            self.assertEqual(queued,[(self.tickers[-1],ENTRY_PAIR)])
            self.r._entry_dirty = True
            state.queued = ((SAFETY_CANCEL,self.tickers[0]),)
            await self.r._ranked_entry_turn()
            self.assertEqual(len(queued),1)
            self.assertTrue(self.r._entry_dirty)

    async def test_ranked_entry_does_not_survive_source_change_during_proposal(self):
        for ticker in self.tickers: self.s.initial_ranking.observe(ticker)
        calls = []
        self.r.dispatch_supervisor = SimpleNamespace(dispatcher=SimpleNamespace(status=lambda:
            SimpleNamespace(active=None,queued=(),stopping=False,failed=False)),request=lambda *a:calls.append(a))
        self.r.accounting_result = SimpleNamespace(released=True,window=self.window)
        async def propose(**kwargs):
            self.r.accounting_result = None
            return SimpleNamespace(blockers=(),additions=(SimpleNamespace(ticker=self.tickers[0]),))
        self.s.propose = propose
        self.r._entry_dirty = True
        with patch.object(RecoveryRuntime,'entry_allowed',property(lambda _:True)):
            await self.r._ranked_entry_turn()
        self.assertFalse(calls)

    def test_reader_bounds_grow_only_for_broad_public_shards(self):
        with patch('kalshi_bot.runtime.WebSocketReaders') as reader:
            factory=readonly_reader_factory(None)
            for spec in topology(self.tickers,market_capacity=1024):
                factory(spec)
                options=reader.call_args.kwargs
                expected=8192 if spec.name=='lifecycle' else 2048 if spec.name.startswith('book-') else 256
                self.assertEqual(options['capacity'],expected)
