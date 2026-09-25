import asyncio
import base64
from decimal import Decimal as D
import json
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from kalshi_bot.books import BookConnection, ProofLost
from kalshi_bot.scheduler import DirtyScheduler
from kalshi_bot.transport import Signer, Subscription, WebSocketReaders, topology
from kalshi_bot.values import InvalidData


def snapshot(seq=1,ticker="A",sid=1):
    return {"type":"orderbook_snapshot","seq":seq,"sid":sid,"msg":{
        "market_ticker":ticker,"yes_dollars_fp":[["0.4","10.00"]],
        "no_dollars_fp":[["0.6","20.00"]]}}


def delta(seq=2,ticker="A",side="yes",quantity="-1.00",p="0.4"):
    return {"type":"orderbook_delta","seq":seq,"sid":1,"msg":{
        "market_ticker":ticker,"side":side,"price_dollars":p,"delta_fp":quantity}}


class BookTests(unittest.TestCase):
    def setUp(self):
        self.feed=BookConnection(("A","B"),max_levels=2)
        self.epoch=self.feed.reconnect()

    def apply(self,event):
        return self.feed.apply(event,generation=self.epoch)

    def test_incremental_delta_updates_exact_quantity(self):
        self.apply(snapshot())
        self.apply(delta())
        self.assertEqual(self.feed.books["A"].bids.levels[D("0.4")],9)

    def test_no_side_is_explicit_unified_yes_price(self):
        self.apply(snapshot())
        self.apply(delta(side="no",p="0.6",quantity="3"))
        self.assertEqual(self.feed.books["A"].asks.levels[D("0.6")],23)

    def test_sequence_is_shared_across_markets(self):
        self.apply(snapshot())
        self.apply(snapshot(2,"B"))
        self.apply(delta(3,"A"))
        self.assertTrue(self.feed.books["A"].valid)
        self.assertTrue(self.feed.books["B"].valid)

    def test_sequence_gap_invalidates_entire_connection(self):
        self.apply(snapshot())
        self.apply(snapshot(2,"B"))
        with self.assertRaises(ProofLost): self.apply(delta(4))
        self.assertTrue(self.feed.failed)
        self.assertTrue(all(not book.valid for book in self.feed.books.values()))

    def test_repeated_sequence_is_not_applied_twice(self):
        self.apply(snapshot())
        self.apply(delta())
        with self.assertRaises(ProofLost): self.apply(delta())

    def test_uninitialized_market_cannot_accept_delta(self):
        self.apply(snapshot())
        with self.assertRaises(ProofLost): self.apply(delta(ticker="B"))

    def test_old_generation_cannot_overwrite_new_book(self):
        self.apply(snapshot())
        old=self.epoch
        self.epoch=self.feed.reconnect()
        self.apply(snapshot())
        self.assertIsNone(self.feed.apply(delta(),generation=old))
        self.assertEqual(self.feed.books["A"].bids.levels[D("0.4")],10)

    def test_negative_quantity_invalidates_proof(self):
        self.apply(snapshot())
        with self.assertRaises(ProofLost): self.apply(delta(quantity="-11"))
        self.assertFalse(self.feed.books["A"].valid)

    def test_zero_removes_price_level(self):
        self.apply(snapshot())
        self.apply(delta(quantity="-10"))
        self.assertEqual(self.feed.books["A"].bids.prices,[])

    def test_level_capacity_is_enforced(self):
        self.apply(snapshot())
        self.apply(delta(p="0.3",quantity="1"))
        with self.assertRaises(ProofLost): self.apply(delta(3,p="0.2",quantity="1"))

    def test_crossed_snapshot_refuses_quote_proof(self):
        event=snapshot()
        event["msg"]["no_dollars_fp"]=[["0.3","1"]]
        with self.assertRaises(ProofLost): self.apply(event)

    def test_missing_sequence_is_not_accepted(self):
        event=snapshot()
        del event["seq"]
        with self.assertRaises(ProofLost): self.apply(event)

    def test_gap_cannot_be_cleared_by_late_snapshot_same_generation(self):
        self.apply(snapshot())
        with self.assertRaises(ProofLost): self.apply(delta(3))
        with self.assertRaises(ProofLost): self.apply(snapshot(4))
        self.epoch=self.feed.reconnect()
        self.apply(snapshot())
        self.assertTrue(self.feed.books["A"].valid)

    def test_duplicate_snapshot_price_rejected(self):
        event=snapshot()
        event["msg"]["yes_dollars_fp"]*=2
        with self.assertRaises(ProofLost): self.apply(event)

    def test_second_subscription_cannot_overwrite_owned_market(self):
        self.apply(snapshot())
        with self.assertRaises(ProofLost): self.apply(snapshot(sid=2))


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler=DirtyScheduler(2)
        for ticker in ("A","B"): self.scheduler.register(ticker)

    def test_repeated_updates_coalesce_without_unbounded_backlog(self):
        for _ in range(10000): self.scheduler.mark("A")
        self.assertEqual(self.scheduler.take(0),["A"])
        self.assertEqual(self.scheduler.take(0),[])

    def test_due_risk_timer_runs_without_market_messages(self):
        self.scheduler.schedule("B",10)
        self.assertEqual(self.scheduler.take(9),[])
        self.assertEqual(self.scheduler.take(10),["B"])

    def test_repeated_reschedules_keep_heap_bounded(self):
        for index in range(10000): self.scheduler.schedule("A",index)
        self.assertLessEqual(len(self.scheduler._heap),4)
        self.assertEqual(self.scheduler.take(9998),[])
        self.assertEqual(self.scheduler.take(9999),["A"])

    def test_unknown_scope_fails(self):
        with self.assertRaises(InvalidData): self.scheduler.mark("C")
        with self.assertRaises(InvalidData): self.scheduler.register("C")

    def test_priority_promotes_existing_work_without_starving_discovery(self):
        s = DirtyScheduler(1024)
        tickers = [f'M{i:04d}' for i in range(1024)]
        for ticker in tickers:
            s.register(ticker)
            s.mark(ticker)
        for _ in range(100):
            for ticker in tickers[-30:]: s.mark(ticker, priority=True)
        self.assertEqual(len(s._queue)+len(s._priority),1024)
        first = s.take(0,limit=4)
        self.assertEqual(first,tickers[-30:-27]+tickers[:1])
        for ticker in first[:3]: s.mark(ticker,priority=True)
        self.assertEqual(s.take(0,limit=4)[-1],tickers[1])
        s.unregister(tickers[-1])
        remaining = s.take(0,limit=1024)
        self.assertNotIn(tickers[-1],remaining)
        self.assertEqual(len(remaining),len(set(remaining)))
        self.assertFalse(s.pending)


class WireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=cls.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
        cls.signer=Signer("test-key",pem)  # Ephemeral test key, never user credentials.

    def test_signed_path_excludes_query_string(self):
        headers=self.signer.headers("GET","/trade-api/v2/portfolio/orders?limit=1",123)
        self.key.public_key().verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
            b"123GET/trade-api/v2/portfolio/orders",
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())

    def test_signer_cannot_authorize_write(self):
        with self.assertRaises(InvalidData): self.signer.headers("POST","/trade-api/v2/portfolio/events/orders")

    def test_signer_repr_redacts_key_id(self):
        self.assertNotIn("test-key",repr(self.signer))

    def test_topology_covers_every_market_once(self):
        tickers=tuple(f"M-{i}" for i in range(30))
        specs=topology(tickers)
        self.assertEqual(len(specs),4)
        books=[spec for spec in specs if spec.name.startswith("book")]
        self.assertEqual(sorted(t for spec in books for t in spec.tickers),sorted(tickers))
        self.assertTrue(all(spec.command()["params"]["use_yes_price"] for spec in books))
        self.assertNotIn("market_tickers",next(s for s in specs if s.name=="account").command()["params"])

    def test_partition_does_not_move_existing_markets_when_scope_grows(self):
        first={t:s.name for s in topology(("A","B")) for t in s.tickers}
        second={t:s.name for s in topology(("A","B","C")) for t in s.tickers}
        self.assertTrue(all(second[t]==name for t,name in first.items()))

    def test_four_book_shards_cover_every_market_once(self):
        tickers=tuple(f"M-{i}" for i in range(1024))
        specs=topology(tickers,market_capacity=1024,book_connections=4)
        books=[spec for spec in specs if spec.name.startswith('book-')]
        self.assertEqual(len(books),4)
        self.assertEqual(sorted(t for spec in books for t in spec.tickers),sorted(tickers))
        self.assertLess(max(len(spec.tickers) for spec in books),300)


class FakeSigner:
    def headers(self,*args): return {"fake":"fixture-only"}


class FakeSocket:
    def __init__(self,messages):
        self.messages=messages
        self.sent=[]
        self.closed=False
    async def __aenter__(self): return self
    async def __aexit__(self,*args): self.closed=True
    async def send(self,message): self.sent.append(json.loads(message))
    def __aiter__(self): return self
    async def __anext__(self):
        if self.messages:
            return self.messages.pop(0)
        await asyncio.Event().wait()
        raise StopAsyncIteration


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_byte_budget_limits_large_messages_before_count_limit(self):
        socket=FakeSocket([json.dumps({"type":"fill","padding":"a"*100})])
        reader=WebSocketReaders(FakeSigner(),(Subscription("account",("fill",)),),
                                capacity=100,byte_capacity=10,connector=lambda *a,**k:socket)
        async def consume(name,event): pass
        with self.assertRaises(ExceptionGroup): await asyncio.wait_for(reader.run(consume),1)
        self.assertTrue(reader.invalid)
        self.assertEqual(reader.queue.qsize(),0)

    async def test_bounded_queue_overflow_invalidates_and_closes(self):
        socket=FakeSocket([json.dumps({"type":"fill"})]*3)
        reader=WebSocketReaders(FakeSigner(),(Subscription("account",("fill",)),),
                                capacity=1,connector=lambda *a,**k:socket)
        async def consume(name,event): await asyncio.Event().wait()
        with self.assertRaises(ExceptionGroup):
            await asyncio.wait_for(reader.run(consume),1)
        self.assertTrue(reader.invalid)
        self.assertTrue(socket.closed)

    async def test_cancellation_closes_all_socket_contexts(self):
        sockets=[]
        def connector(*args,**kwargs):
            socket=FakeSocket([])
            sockets.append(socket)
            return socket
        specs=topology(tuple(f"M-{i}" for i in range(30)))
        reader=WebSocketReaders(FakeSigner(),specs,connector=connector)
        async def consume(name,event): pass
        task=asyncio.create_task(reader.run(consume))
        for _ in range(20):
            await asyncio.sleep(0)
            if len(sockets)==4: break
        self.assertEqual(len(sockets),4)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(all(socket.closed for socket in sockets))
        self.assertTrue(reader.invalid)

    async def test_wire_error_is_not_silently_ignored(self):
        socket=FakeSocket([json.dumps({"type":"error","msg":{"code":1}})])
        reader=WebSocketReaders(FakeSigner(),(Subscription("account",("fill",)),),
                                connector=lambda *a,**k:socket)
        async def consume(name,event): pass
        with self.assertRaises(ExceptionGroup): await asyncio.wait_for(reader.run(consume),1)
        self.assertTrue(reader.invalid)
