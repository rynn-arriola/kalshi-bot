"""Sustained synthetic refill: real owners, disposable ledger, no real venue."""
import asyncio
from datetime import timedelta
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from kalshi_bot.dispatch import ENTRY_PAIR
from kalshi_bot.live import LaunchInputs, compose
from kalshi_bot.live_session import LiveSession
from kalshi_bot.observability import NO_LOG
from kalshi_bot.quota import QuotaGuard, QuotaPolicy, ProbeConfig
from kalshi_bot.quota_supervisor import QuotaSupervisor
from kalshi_bot.rest import RestReads, TokenBudget, WireResponse
from kalshi_bot.writer import LedgerWriter
import test_bot_live_runtime as entry_fixture
import test_bot_market_inputs as metadata
from test_bot_engine import snapshot
from test_bot_incentive_discovery import row as reward_row
from test_bot_opening_account import balance
from test_bot_quota import LIMITS, COSTS, Signer


class EntryInterleavingTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, mode, edge='risk'):
        runtime_type, session_type = entry_fixture.RecoveryRuntime, entry_fixture.LiveSession
        def runtime(*args, **kw):
            return runtime_type(*args, **(kw | {'tickers':('A','B')}))
        def session(*args, **kw):
            return session_type(*args, **(kw | {'tickers':('A','B')}))
        f = entry_fixture.LiveEntryTests()
        with patch.object(entry_fixture, 'RecoveryRuntime', runtime), patch.object(entry_fixture, 'LiveSession', session):
            await f.asyncSetUp()
        try:
            r, calls = f.runtime, 0
            name = r.engine.market_shard['A']
            shard = r.engine.shards[name]
            def noise():
                if mode == 'private':
                    r.engine.submit_private({'type':'synthetic_pending'}, generation=r.engine.private_generation)
                elif mode == 'deadline':
                    r.engine.schedule('B', r.clock())
                elif mode == 'stale':
                    r.engine.book_received['A'] -= 6
                else:
                    count = 65 if mode == 'burst' else 1
                    for n in range(count):
                        event = snapshot('A' if mode == 'changed' else 'B', n+2)
                        if mode == 'gap': event['seq'] += 1
                        if mode == 'malformed': event['msg']['yes_dollars_fp'] = 'invalid'
                        r.engine.submit_book(name, event, generation=shard.generation)
            method = {'risk':'risk_view','proposal':'risk_view','inventory':'market_inventory',
                      'prepare':'reserve_entry_pair','sending':'begin_batch_send'}[edge]
            owner = r if method == 'risk_view' else f.f.writer
            original = getattr(owner, method)
            async def overlap(*args, **kwargs):
                nonlocal calls
                result = await original(*args, **kwargs)
                calls += 1
                if calls == (2 if edge == 'risk' else 1): noise()
                return result
            setattr(owner, method, overlap)
            f.dispatcher.submit('A', ENTRY_PAIR)
            result = await f.dispatcher.run_one()
            self.assertEqual(result.state, 'ACK' if mode == 'unrelated' else 'BLOCKED', result.blockers)
            self.assertEqual(len(f.calls), 1 if mode == 'unrelated' else 0)
            self.assertFalse(f.dispatcher.status().failed)
            if mode == 'unrelated':
                self.assertEqual(shard.books['A'].revision, 1)
                self.assertEqual(shard.books['B'].revision, 2)
                self.assertEqual(r.engine.send_edge_events, 1)
            if mode == 'burst':
                self.assertEqual(len(r.engine.public[name]), 1)
            if mode in {'gap','malformed'}:
                self.assertTrue(shard.failed)
                self.assertEqual(r.engine.book_failures[name], 1)
        finally:
            await f.asyncTearDown()

    async def test_unrelated_frame_during_risk_read_does_not_starve_entry(self):
        await self.scenario('unrelated')

    async def test_unrelated_frame_after_prepare_does_not_starve_entry(self):
        await self.scenario('unrelated', 'prepare')

    async def test_unrelated_frames_during_inventory_proposal_and_sending(self):
        for edge in ('inventory','proposal','sending'):
            with self.subTest(edge=edge): await self.scenario('unrelated',edge)

    async def test_changed_market_gap_malformed_private_deadline_and_stale_still_block(self):
        # Risk I/O now precedes price capture. A change at that point is safely
        # repriced (covered by LiveEntryTests), not a stale prepared command.
        for mode in ('gap','malformed','private','deadline','stale'):
            with self.subTest(mode=mode): await self.scenario(mode)
        for mode in ('changed','burst'):
            for edge in ('prepare','sending'):
                with self.subTest(mode=mode, edge=edge): await self.scenario(mode, edge)


class RefillLoadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Measure the production loop, not unittest's per-callback traceback
        # instrumentation. Focused interleaving/failure tests retain debug=True.
        asyncio.get_running_loop().set_debug(False)

    async def test_1024_books_fill_thirty_orders_then_refill_with_real_recovery(self):
        # The event and mutation wire never leave this process. No fixture
        # authorization bypass: compose installs the actual live owners.
        started = time.monotonic()
        base = metadata.NOW
        now = lambda:base+timedelta(seconds=time.monotonic()-started)
        tickers = tuple(f'M{i:04d}' for i in range(1024))
        markets = {t:metadata.market(t) for t in tickers}
        md = metadata.Reads()
        orders, batches, canceled = {}, [], []
        threatened, cancel_recoveries, cancel_times = set(), [], []
        calls = {}
        docs = {
            '/account/limits':LIMITS, '/account/endpoint_costs':COSTS,
            '/portfolio/balance':balance(),
            '/portfolio/positions':{'market_positions':[], 'cursor':''},
            '/portfolio/fills':{'fills':[], 'cursor':''},
            '/portfolio/settlements':{'settlements':[], 'cursor':''},
            '/portfolio/subaccounts/transfers':{'transfers':[]},
            '/portfolio/intra_exchange_instance_transfers':{'transfers':[]},
            '/portfolio/deposits':{'deposits':[]}, '/portfolio/withdrawals':{'withdrawals':[]},
            '/historical/cutoff':{'trades_created_ts':(base-timedelta(days=1)).isoformat()},
            '/events/E':{'event':md.event}, '/series/S':{'series':md.series},
            '/events/fee_changes':{'event_fee_changes':[], 'cursor':''},
            '/series/fee_changes':{'series_fee_change_arr':[]}, '/milestones/M':{'milestone':md.milestone},
            '/events':{'events':[{**md.event, 'markets':list(markets.values())}],
                       'milestones':[md.milestone], 'cursor':''},
        }
        rewards = [reward_row(t, 'reward-'+t, period_reward=5000000 if i<32 else 20000)
                   for i,t in enumerate(tickers)]
        def wire(url, *_):
            parsed = urlparse(url)
            path = parsed.path.removeprefix('/trade-api/v2')
            query = parse_qs(parsed.query)
            calls[path] = calls.get(path, 0)+1
            if path == '/portfolio/orders':
                rows = list(orders.values())
                if query.get('status') == ['resting']: rows = [r for r in rows if r['status']=='resting']
                doc = {'orders':rows, 'cursor':''}
            elif path == '/portfolio/orders/queue_positions':
                doc = {'queue_positions':[dict(order_id=r['order_id'], market_ticker=r['ticker'],
                    queue_position_fp='0' if r['ticker'] in threatened else '1000')
                    for r in orders.values() if r['status']=='resting']}
            elif path.startswith('/portfolio/orders/'):
                doc = {'order':orders[path.rsplit('/',1)[1]]}
            elif path.startswith('/markets/'):
                doc = {'market':markets[path.rsplit('/',1)[1]]}
            elif path == '/incentive_programs':
                offset = int(query.get('cursor',['0'])[0])
                limit = int(query.get('limit',['100'])[0])
                doc = {'incentive_programs':rewards[offset:offset+limit],
                       'next_cursor':str(offset+limit) if offset+limit<len(rewards) else ''}
            else: doc = docs[path]
            return WireResponse(200, json.dumps(doc, default=str).encode())
        class Reader:
            def __init__(self, spec): self.spec = spec
            async def run(self, consume):
                for sid, channel in enumerate(self.spec.channels, 1):
                    await consume(self.spec.name, dict(type='subscribed',id=1,msg=dict(channel=channel,sid=sid)))
                seq = 0
                if self.spec.name.startswith('book-'):
                    for ticker in self.spec.tickers:
                        seq += 1
                        event = snapshot(ticker, seq)
                        event['msg']['yes_dollars_fp'] = [['.5','1000']]
                        await consume(self.spec.name, event)
                noise = [t for t in self.spec.tickers if t >= 'M0032']
                eligible = [t for t in self.spec.tickers if t < 'M0032']
                index = 0
                while True:
                    await asyncio.sleep(.025)
                    pools = [noise]*4+([eligible] if index%4 == 0 else [])
                    for n, pool in enumerate(pools):
                        if not pool: continue
                        seq += 1
                        await consume(self.spec.name, dict(type='orderbook_delta',sid=1,seq=seq,
                            msg=dict(market_ticker=pool[(index*4+n if pool is noise else index//4)%len(pool)],side='yes',
                                price_dollars='.1',delta_fp='1')))
                    index += 1
        class MutationWire:
            async def __call__(self, kind, req):
                if kind != 'cancel': raise AssertionError('unexpected inventory create')
                session.check('cancel', req)
                row = orders[req['order_id']]
                row.update(status='canceled', remaining_count_fp='0', last_updated_ts_ms=2)
                canceled.append(row['order_id'])
                cancel_recoveries.append(runtime.recovery_attempts)
                cancel_times.append(time.monotonic())
                return dict(order_id=row['order_id'],reduced_by='10',ts_ms=2)
            async def batch(self, requests):
                session.check('batch_create', requests)
                batches.append(requests)
                reply = []
                for req in requests:
                    key = req['client_order_id']
                    orders[key] = dict(order_id=key,client_order_id=key,ticker=req['ticker'],
                        book_side=req['side'],yes_price_dollars=req['price'],initial_count_fp=req['count'],
                        fill_count_fp='0',remaining_count_fp=req['count'],status='resting',
                        exchange_index=req['exchange_index'],subaccount_number=0,last_updated_ts_ms=1)
                    reply.append(dict(order_id=key,client_order_id=key,fill_count='0',remaining_count='10',ts_ms=1))
                return {'orders':reply}
        with TemporaryDirectory() as directory:
            session = LiveSession(run_id='refill-load',tickers=tickers)
            writer = await LedgerWriter(Path(directory)/'account.db',live_session=session).start()
            reads = RestReads(TokenBudget(rate=10000,capacity=10000,default_cost=10,clock=time.monotonic),
                              Signer(),wire=wire)
            guard = QuotaGuard(QuotaPolicy(ProbeConfig(10000,10000,10,10)),clock=time.monotonic,now=now)
            reads.attach_quota(guard)
            quota = QuotaSupervisor(reads)
            runtime = task = None
            try:
                inputs = LaunchInputs(tuple(metadata.review(m) for m in markets.values()),
                    metadata.FeeProfile(D('.0001'),'synthetic',base+timedelta(hours=2)),(0,1),tickers[:1])
                runtime = await compose(writer,reads,Reader,MutationWire(),inputs=inputs,
                    boundary=base-timedelta(seconds=1),now=now,clock=time.monotonic,diagnostics=NO_LOG,
                    quota=quota,initialize=True,book_connections=4)
                task = asyncio.create_task(runtime.run())
                last_progress = started
                async with asyncio.timeout(150):
                    while sum(r['status']=='resting' for r in orders.values()) < 30:
                        if task.done(): task.result()
                        if time.monotonic()-last_progress >= 10:
                            last_progress = time.monotonic()
                            print('REFILL_PROGRESS',json.dumps(dict(seconds=round(last_progress-started,2),
                                batches=len(batches),coverage=len(runtime.selection.initial_ranking.evaluated),
                                priority=len(runtime.selection._priority_hints),
                                dispatch=runtime.dispatch_supervisor.status()),default=str))
                        await asyncio.sleep(.05)
                first_full = time.monotonic()-started
                self.assertEqual(len(batches),15)
                self.assertTrue(all(r['ticker']<'M0032' for batch in batches for r in batch))
                self.assertEqual(len(runtime.engine.shards),4)
                self.assertEqual(len(runtime.engine.market_shard),1024)
                # Mimic two independently terminal venue cancels, then use the
                # actual full recovery path. No direct ledger editing.
                pair = list(orders.values())[:2]
                for row in pair: row.update(status='canceled',remaining_count_fp='0',last_updated_ts_ms=2)
                runtime.request_recovery('source_change')
                async with asyncio.timeout(30):
                    while len(batches) == 15 or sum(r['status']=='resting' for r in orders.values()) != 30:
                        if task.done(): task.result()
                        await asyncio.sleep(.05)
                refill_seconds = time.monotonic()-started-first_full
                # Wire ACK precedes durable recovery; a fixed 3.5s sleep can
                # end before the next renewal even starts. Await its evidence.
                async with asyncio.timeout(10):
                    while runtime.routine_refresh_completed+runtime.steady_refresh_completed == 0:
                        if task.done(): task.result()
                        await asyncio.sleep(.05)
                self.assertEqual(sum(r['status']=='resting' for r in orders.values()),30)
                self.assertEqual(len(batches),16)
                self.assertFalse(canceled)
                self.assertFalse(runtime.engine.failed)
                self.assertFalse(runtime.dispatch_supervisor.failed)
                self.assertGreater(runtime.routine_refresh_completed+runtime.steady_refresh_completed,0)
                self.assertTrue(all(len(batch)==2 and all(D(r['count'])==D(10) for r in batch)
                                    for batch in batches))
                # Drive the real reflection -> risk decision -> two exact
                # cancellations -> reconciliation -> ranked refill graph.
                victim=next(row['ticker'] for row in orders.values() if row['status']=='resting')
                victim_ids={r['order_id'] for r in orders.values()
                            if r['ticker']==victim and r['status']=='resting'}
                threatened.add(victim)
                risk_started=time.monotonic()
                runtime.rewards.request_reflection()
                async with asyncio.timeout(45):
                    while (len(canceled)<2 or len(batches)<17
                           or sum(r['status']=='resting' for r in orders.values()) != 30):
                        if task.done(): task.result()
                        await asyncio.sleep(.05)
                self.assertEqual(set(canceled),victim_ids)
                self.assertEqual(cancel_recoveries[0],cancel_recoveries[1])
                self.assertLess(cancel_times[1]-cancel_times[0],2)
                self.assertNotIn(victim,{r['ticker'] for r in batches[-1]})
                self.assertFalse(runtime.maintenance.entry_allowed(victim,'reward-'+victim))
                self.assertFalse(runtime.dispatch_supervisor.failed)
                print('REFILL_LOAD', json.dumps(dict(first_full_seconds=round(first_full,3),
                    refill_seconds=round(refill_seconds,3),
                    risk_refill_seconds=round(time.monotonic()-risk_started,3),
                    cancel_pair_gap_seconds=round(cancel_times[1]-cancel_times[0],3),
                    final_seconds=round(time.monotonic()-started,3),batches=len(batches),
                    engine=runtime.engine.status(),dispatch=runtime.dispatch_supervisor.status(),
                    routine_refreshes=runtime.routine_refresh_completed,
                    steady_refreshes=runtime.steady_refresh_completed,
                    loop_debug=asyncio.get_running_loop().get_debug()),default=str))
            except BaseException:
                if runtime is not None:
                    print('REFILL_FAILURE',json.dumps(dict(orders=len(orders),batches=len(batches),
                        status=runtime.status()),default=str))
                raise
            finally:
                if runtime is not None: runtime.stop()
                try:
                    if task is not None: await task
                finally:
                    await quota.close()
                    await reads.close()
                    await writer.close()
