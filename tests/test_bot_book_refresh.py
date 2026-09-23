"""No keys/network: real transport and engine with synthetic WebSocket replies."""
import asyncio
from decimal import Decimal
from datetime import timedelta
import json
import time
import unittest
from unittest.mock import patch

from kalshi_bot.book_refresh import BookRefresh
from kalshi_bot.books import BookConnection, ProofLost
from kalshi_bot.engine import EventEngine
from kalshi_bot.transport import Subscription, WebSocketReaders
from kalshi_bot.values import InvalidData
from test_bot_feeds import FakeSigner, snapshot, delta


def ack():
    return dict(type='subscribed', id=1, msg=dict(channel='orderbook_delta', sid=1))


class RefreshTests(unittest.TestCase):
    def ready(self, tickers=('A',)):
        r = BookRefresh(tickers)
        r.observe(ack(), 0.)
        return r

    def test_no_command_before_ack_or_quiet_deadline(self):
        r = BookRefresh(('A',))
        self.assertIsNone(r.next_command(100))
        r.observe(ack(), 100)
        self.assertIsNone(r.next_command(102.99))
        self.assertEqual(r.next_command(103), dict(id=2, cmd='update_subscription',
            params=dict(sids=[1], market_tickers=['A'], action='get_snapshot')))

    def test_active_market_is_not_polled_and_ping_is_not_freshness(self):
        r = self.ready(('A','B'))
        r.observe(snapshot(ticker='A'), 2)
        r.observe(dict(type='pong'), 2.9)
        self.assertEqual(r.next_command(3)['params']['market_tickers'], ['B'])
        self.assertEqual(r.last, {'A':2})

    def test_one_inflight_batch_and_partial_replies_do_not_extend_deadline(self):
        r = self.ready(('A','B'))
        r.next_command(3)
        self.assertIsNone(r.next_command(4))
        r.observe(snapshot(ticker='A') | {'id':2}, 7)
        self.assertEqual(r.pending, {'B'})
        with self.assertRaises(InvalidData): r.next_command(8)

    def test_delta_does_not_acknowledge_snapshot_request(self):
        r = self.ready()
        r.next_command(3)
        r.observe(delta(), 4)
        self.assertEqual(r.pending, {'A'})
        with self.assertRaises(InvalidData): r.next_command(8)

    def test_optional_id_and_wrong_ids(self):
        for reply_id in (None,2,3,True):
            r = self.ready()
            r.next_command(3)
            event = snapshot() if reply_id is None else snapshot() | {'id':reply_id}
            if reply_id is None or type(reply_id) is int and reply_id == 2:
                r.observe(event, 4)
                self.assertFalse(r.pending)
            else:
                with self.assertRaises(InvalidData): r.observe(event, 4)

    def test_duplicate_and_late_response_fail_closed(self):
        r = self.ready()
        r.next_command(3)
        r.observe(snapshot() | {'id':2}, 4)
        with self.assertRaises(InvalidData): r.observe(snapshot() | {'id':2}, 4.1)
        r = self.ready()
        r.next_command(3)
        with self.assertRaises(InvalidData): r.observe(snapshot() | {'id':2}, 8)

    def test_wrong_sid_scope_ack_and_old_generation_rejected(self):
        for event in (snapshot(sid=2), snapshot(ticker='B'), ack(), snapshot() | {'id':2}):
            r = self.ready()
            with self.assertRaises(InvalidData): r.observe(event, 1)
        with self.assertRaises(InvalidData): BookRefresh(('A',)).observe(snapshot(), 1)

    def test_maximum_scope_batched_without_starvation(self):
        r = self.ready(tuple(f'M{i:04}' for i in range(1024)))
        seen = set()
        for i in range(11):
            now = 3 + i*.01
            command = r.next_command(now)
            tickers = command['params']['market_tickers']
            self.assertLessEqual(len(tickers), 100)
            for ticker in tickers:
                r.observe(snapshot(ticker=ticker) | {'id':command['id']}, now)
            seen.update(tickers)
        self.assertEqual(seen, r.scope)
        self.assertIsNone(r.next_command(3.2))

    def test_contiguous_refresh_keeps_delta_sequence_and_exact_depth(self):
        feed = BookConnection(('A',))
        gen = feed.reconnect()
        for event in (snapshot(1), delta(2), snapshot(3) | {'id':2}, delta(4)):
            feed.apply(event, generation=gen)
        self.assertEqual(feed.books['A'].bids.levels[Decimal('.4')], 9)
        self.assertEqual(feed.books['A'].revision, 4)
        with self.assertRaises(ProofLost): feed.apply(snapshot(6), generation=gen)
        new_gen = feed.reconnect()
        self.assertIsNone(feed.apply(snapshot(7), generation=gen))
        feed.apply(snapshot(1), generation=new_gen)


class Socket:
    def __init__(self, *, respond=True, block_send=False):
        self.events = asyncio.Queue()
        for event in (ack(), snapshot()): self.events.put_nowait(json.dumps(event))
        self.respond, self.block_send = respond, block_send
        self.sent, self.closed = [], False
        self.requested = asyncio.Event()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.closed = True
    def __aiter__(self): return self
    async def __anext__(self): return await self.events.get()
    async def send(self, raw):
        command = json.loads(raw)
        self.sent.append(command)
        if command['cmd'] != 'update_subscription': return
        self.requested.set()
        if self.block_send: await asyncio.Event().wait()
        if self.respond:
            self.events.put_nowait(json.dumps(snapshot(2) | {'id':command['id']}))
            self.events.put_nowait(json.dumps(delta(3)))


class TransportRefreshTests(unittest.IsolatedAsyncioTestCase):
    def reader(self, socket):
        return WebSocketReaders(FakeSigner(),
            (Subscription('book-0', ('orderbook_delta',), ('A',), True),),
            connector=lambda *a, **k: socket)

    async def test_real_transport_requests_and_delivers_refresh_in_order(self):
        socket = Socket()
        reader = self.reader(socket)
        feed = BookConnection(('A',))
        gen = feed.reconnect()
        done = asyncio.Event()
        received = []
        async def consume(name, event):
            if event['type'] == 'subscribed': return
            received.append(event['_received_mono'])
            feed.apply(event, generation=gen)
            if event['seq'] == 3: done.set()
        with patch.object(BookRefresh, 'QUIET_SECONDS', .01):
            task = asyncio.create_task(reader.run(consume))
            try:
                await asyncio.wait_for(done.wait(), 2)
                self.assertEqual(len(socket.sent), 2)
                self.assertEqual(feed.books['A'].revision, 3)
                self.assertEqual(received, sorted(received))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(socket.closed)
        self.assertTrue(reader.invalid)
        self.assertFalse(any(t.get_name().startswith('kalshi-snapshot-')
                             for t in asyncio.all_tasks() if not t.done()))

    async def test_response_timeout_invalidates_and_joins_reader(self):
        socket = Socket(respond=False)
        reader = self.reader(socket)
        async def consume(*args): pass
        with patch.object(BookRefresh, 'QUIET_SECONDS', .01), \
                patch.object(BookRefresh, 'RESPONSE_SECONDS', .01):
            with self.assertRaises(ExceptionGroup):
                await asyncio.wait_for(reader.run(consume), 2)
        self.assertTrue(reader.invalid)
        self.assertTrue(socket.closed)

    async def test_cancel_while_send_is_blocked_joins_control_task(self):
        socket = Socket(block_send=True)
        reader = self.reader(socket)
        async def consume(*args): pass
        with patch.object(BookRefresh, 'QUIET_SECONDS', .01):
            task = asyncio.create_task(reader.run(consume))
            try:
                await asyncio.wait_for(socket.requested.wait(), 2)
            finally:
                task.cancel()
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
        self.assertTrue(socket.closed)

    async def test_transport_timestamp_survives_slow_consumer(self):
        socket = Socket(respond=False)
        reader = self.reader(socket)
        stamps = []
        async def consume(name, event):
            if event['type'] == 'subscribed': await asyncio.sleep(.03)
            else:
                stamps.append((event['_received_mono'], time.monotonic()))
                raise InvalidData('fixture finished')
        with self.assertRaises(ExceptionGroup): await reader.run(consume)
        self.assertGreaterEqual(stamps[0][1]-stamps[0][0], .02)


class IngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_runtime_restores_quiet_selection_without_new_generation(self):
        import test_bot_selection as fixtures
        f = fixtures.RuntimeSelectionTests()
        await f.asyncSetUp()
        try:
            name, shard = next(iter(f.r.engine.shards.items()))
            gen = shard.generation
            spec = Subscription(name, ('orderbook_delta',), ('A',), True)
            refresh = BookRefresh(('A',))
            refresh.observe(ack(), 100)
            refresh.observe(snapshot(), 100)
            f.now += timedelta(seconds=6)
            f.mono += 6
            f.w = await f.writer.observe(f.now)
            account = fixtures.normalize_snapshot((), (),
                dict(balance_dollars='500', updated_ts=1), subaccount=0)
            await f.r.account.finish_reconciliation(
                f.r.account.begin_reconciliation(f.now), account, f.now)
            f.r.management.set_terms(fixtures.terms(observed_at=f.now,
                valid_until=f.now+timedelta(seconds=60)))
            f.publish()
            # A queued old frame must not restore source authority at dequeue time.
            def response(seq, stamp):
                return dict(type='orderbook_snapshot', sid=1, seq=seq,
                    _received_mono=stamp, msg=dict(market_ticker='A',
                    yes_dollars_fp=[['.5','1000']], no_dollars_fp=[['.6','1000']]))
            await f.r._consume(spec, response(2,100), gen, {'orderbook_delta'})
            await f.r.engine.step()
            self.assertFalse((await f.s.propose(window=f.w, free_cash=500)).additions)
            command = refresh.next_command(106)
            fresh = response(3,106) | {'id':command['id']}
            refresh.observe(fresh, 106)
            await f.r._consume(spec, fresh, gen, {'orderbook_delta'})
            await f.r.engine.step()
            self.assertEqual(len((await f.s.propose(window=f.w, free_cash=500)).additions), 1)
            self.assertEqual(shard.generation, gen)
            self.assertFalse(await f.writer.mutations())
        finally:
            await f.asyncTearDown()

    async def test_engine_does_not_reage_delayed_snapshot(self):
        async def noop(*args): pass
        feed = BookConnection(('A',))
        engine = EventEngine({'book-0':feed}, private_handler=noop, evaluate=noop,
            deadline_handler=noop, clock=lambda:10.)
        gen = engine.begin_book_epoch('book-0')
        engine.submit_book('book-0', snapshot(), generation=gen, received_at=3.)
        await engine.step()
        self.assertEqual(engine.book_received['A'], 3.)
        for bad in (11., float('nan'), True, -1):
            gen = engine.begin_book_epoch('book-0')
            with self.assertRaises(ProofLost):
                engine.submit_book('book-0', snapshot(), generation=gen, received_at=bad)
