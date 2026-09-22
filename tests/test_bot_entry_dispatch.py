"""Two-leg entry dispatch and bounded V2 transport; synthetic I/O only."""
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_bot.config import BotConfig
from kalshi_bot.account import normalize_snapshot
from kalshi_bot.dispatch import (ENTRY_PAIR, EntryPairCandidate,
                                 MutationDispatcher)
from kalshi_bot.execution import InjectedExecutor
from kalshi_bot.mutation_outcomes import MutationOutcomeOwner
from kalshi_bot.mutation_outcomes import MutationHTTPFailure
from kalshi_bot.mutation_transport import MutationActivation, OrderMutationTransport
from kalshi_bot.dispatch_sources import InventoryDispatchSource
from kalshi_bot.rest import WireResponse
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.transport import MutationSigner
from kalshi_bot.values import InvalidData
from kalshi_bot.write_budget import BATCH_ORDERS, WriteBudget
from kalshi_bot.writer import LedgerWriter
from test_bot_command_handoff import request
from test_bot_write_budget import now as quota_now, snapshot
from test_bot_selection import program, terms


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def pair():
    bid = request('bid-client')
    ask = request('ask-client') | {'side': 'ask', 'price': '.6'}
    return bid, ask


class BatchWire:
    def __init__(self, reply=None):
        self.reply = reply
        self.calls = []

    async def __call__(self, kind, request):
        raise AssertionError('single transport not expected')

    async def batch(self, requests):
        self.calls.append(tuple(dict(row) for row in requests))
        if isinstance(self.reply, BaseException):
            raise self.reply
        if self.reply is not None:
            return self.reply
        return {'orders': [dict(order_id='order-'+row['side'],
            client_order_id=row['client_order_id'], fill_count='0',
            remaining_count='10', ts_ms=1) for row in requests]}


class EntryPairTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'pair.db'
        self.writer = await LedgerWriter(self.path).start()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def reserve(self, *, cash=D(500), batch='pair-a'):
        return await self.writer.reserve_entry_pair(pair(), batch_id=batch,
            view=await self.writer.portfolio(subaccount=0, now=NOW),
            config=BotConfig(), now=NOW, free_cash=cash,
            account_known=True, offline_fixture=True,
            fee_per_contract_bound=D(0))

    async def test_pair_reservation_is_all_or_none(self):
        blocked = await self.reserve(cash=D(3))
        self.assertFalse(blocked.reserved)
        self.assertIn('capital', blocked.blockers)
        self.assertEqual(await self.writer.mutations(), ())
        self.assertEqual((await self.writer.portfolio(
            subaccount=0, now=NOW)).entry_count, 0)

        prepared = await self.reserve()
        self.assertTrue(prepared.reserved, prepared.blockers)
        self.assertEqual(len(prepared.batch.receipts), 2)
        self.assertEqual({row.request['side'] for row in prepared.batch.receipts},
                         {'bid', 'ask'})
        self.assertEqual(len(await self.writer.mutations()), 2)

    async def dispatcher(self, wire):
        budget = WriteBudget(snapshot(rate=100, capacity=100), shards=(0, 1),
            now=quota_now(), offline_fixture=True)
        outcomes = MutationOutcomeOwner(budget, invoke=wire,
            clock_pair=lambda: quota_now(1), notify=lambda *_: None,
            offline_fixture=True)
        executor = InjectedExecutor(self.writer, invoke=outcomes,
            validate_proof=lambda *_: True, offline_fixture=True,
            now=lambda: NOW)
        async def refresh(ticker, priority):
            return EntryPairCandidate('A', ENTRY_PAIR, 'batch-dispatch', pair(),
                await self.writer.portfolio(subaccount=0, now=NOW), D(500), D(0), 1)
        dispatcher = MutationDispatcher(self.writer, executor, budget,
            refresh=refresh, clock_pair=lambda: quota_now(1), now=lambda: NOW,
            offline_fixture=True)
        return dispatcher, budget

    async def test_dispatch_uses_one_batch_and_twenty_unscoped_tokens(self):
        wire = BatchWire()
        dispatcher, budget = await self.dispatcher(wire)
        dispatcher.submit('A', ENTRY_PAIR)
        result = await dispatcher.run_one()
        self.assertEqual(result.state, 'ACK')
        self.assertEqual(set(result.order_ids), {'order-bid', 'order-ask'})
        self.assertEqual(len(wire.calls), 1)
        status = budget.status(now=quota_now(1))
        self.assertEqual(status.buckets[0][1], 80)
        self.assertEqual(status.buckets[1][1], 100)
        self.assertEqual({row['phase'] for row in await self.writer.mutations()},
                         {'ACK'})

    async def test_partial_batch_fails_closed_and_never_retries(self):
        reply = {'orders': [dict(order_id='order-ask',
            client_order_id='ask-client', fill_count='0',
            remaining_count='10', ts_ms=1),
            dict(client_order_id='bid-client', error={'code': 'bad_price'})]}
        wire = BatchWire(reply)
        dispatcher, _ = await self.dispatcher(wire)
        dispatcher.submit('A', ENTRY_PAIR)
        result = await dispatcher.run_one()
        self.assertEqual((result.state, result.blockers), ('FAILED',
            ('entry_pair_partial_reconciliation_required',)))
        self.assertTrue(dispatcher.status().failed)
        self.assertEqual({row['phase'] for row in await self.writer.mutations()},
                         {'ACK', 'REJECTED'})
        self.assertFalse(dispatcher.submit('A', ENTRY_PAIR))
        self.assertEqual(len(wire.calls), 1)

        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual({row['phase'] for row in await self.writer.mutations()},
                         {'ACK', 'REJECTED'})
        capacity = await self.writer.command_capacity()
        self.assertGreater(capacity.mutation_held+capacity.intent_held,
                           0)  # ACK create remains held until account evidence.

    async def test_unidentified_batch_error_marks_both_unknown(self):
        wire = BatchWire({'orders': [dict(error={'code': 'bad_price'}),
            dict(order_id='order-ask', client_order_id='ask-client',
                 fill_count='0', remaining_count='10', ts_ms=1)]})
        dispatcher, _ = await self.dispatcher(wire)
        dispatcher.submit('A', ENTRY_PAIR)
        with self.assertRaises(InvalidData):
            await dispatcher.run_one()
        self.assertEqual({row['phase'] for row in await self.writer.mutations()},
                         {'UNKNOWN'})
        self.assertTrue(dispatcher.status().failed)

    async def test_contradictory_batch_error_marks_both_unknown(self):
        wire = BatchWire({'orders': [dict(order_id='maybe-order',
            client_order_id='bid-client', error={'code': 'bad_price'}),
            dict(order_id='order-ask', client_order_id='ask-client',
                 fill_count='0', remaining_count='10', ts_ms=1)]})
        dispatcher, _ = await self.dispatcher(wire)
        dispatcher.submit('A', ENTRY_PAIR)
        with self.assertRaises(InvalidData):
            await dispatcher.run_one()
        self.assertEqual({row['phase'] for row in await self.writer.mutations()},
                         {'UNKNOWN'})

    async def test_batch_429_pauses_only_unscoped_bucket_and_is_not_retried(self):
        wire = BatchWire(MutationHTTPFailure(429))
        dispatcher, budget = await self.dispatcher(wire)
        dispatcher.submit('A', ENTRY_PAIR)
        with self.assertRaises(MutationHTTPFailure):
            await dispatcher.run_one()
        buckets = {row[0]: row for row in budget.status(now=quota_now(1)).buckets}
        self.assertGreater(buckets[0][3], 0)
        self.assertEqual(buckets[1][3], 0)
        self.assertEqual(len(wire.calls), 1)
        self.assertEqual({row['phase'] for row in await self.writer.mutations()},
                         {'UNKNOWN'})


class MutationTransportTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.signer = MutationSigner('fixture-key', pem)

    def transport(self, response):
        calls = []
        def wire(url, method, headers, body, max_bytes, timeout):
            calls.append((url, method, headers, body, max_bytes, timeout))
            return response
        return OrderMutationTransport(self.signer, wire=wire,
                                      offline_fixture=True), calls

    async def test_batch_payload_and_signed_path_are_exact(self):
        response = WireResponse(201, json.dumps({'orders': [dict(
            order_id='one', client_order_id='bid-client', fill_count='0',
            remaining_count='10', ts_ms=1), dict(order_id='two',
            client_order_id='ask-client', fill_count='0',
            remaining_count='10', ts_ms=1)]}).encode())
        transport, calls = self.transport(response)
        result = await transport.batch(pair())
        self.assertEqual(len(result['orders']), 2)
        url, method, headers, body, maximum, timeout = calls[0]
        self.assertTrue(url.endswith('/portfolio/events/orders/batched'))
        self.assertEqual(method, 'POST')
        self.assertEqual(json.loads(body), {'orders': list(pair())})
        self.assertIn('KALSHI-ACCESS-SIGNATURE', headers)
        self.assertEqual((maximum, timeout), (1048576, 10))

    async def test_live_constructor_and_unrelated_signing_are_closed(self):
        with self.assertRaisesRegex(InvalidData, 'activation'):
            MutationActivation()
        with self.assertRaisesRegex(InvalidData, 'activation'):
            OrderMutationTransport(self.signer, wire=lambda *_: None)
        with self.assertRaises(InvalidData):
            self.signer.headers('POST', '/trade-api/v2/portfolio/balance')
        for method, path in (
                ('DELETE', '/trade-api/v2/portfolio/events/orders/batched'),
                ('POST', '/trade-api/v2/portfolio/events/orders/one/amend'),
                ('DELETE', '/trade-api/v2/portfolio/events/orders/one/decrease')):
            with self.subTest(method=method, path=path), self.assertRaises(InvalidData):
                self.signer.headers(method, path)

    async def test_single_create_and_cancel_cover_exit_transport(self):
        create_response = WireResponse(201, json.dumps(dict(order_id='created',
            client_order_id='bid-client', fill_count='0', remaining_count='10',
            ts_ms=1)).encode())
        transport, calls = self.transport(create_response)
        created = await transport('create', pair()[0])
        self.assertEqual(created['order_id'], 'created')
        self.assertEqual(calls[0][1], 'POST')

        cancel_response = WireResponse(200, json.dumps(dict(order_id='order/a',
            client_order_id='bid-client', reduced_by='10', ts_ms=2)).encode())
        transport, calls = self.transport(cancel_response)
        request_row = dict(order_id='order/a', market_ticker='A', subaccount=0,
                           exchange_index=1)
        cancelled = await transport('cancel', request_row)
        self.assertEqual(cancelled['reduced_by'], '10')
        self.assertIn('/order%2Fa?', calls[0][0])
        self.assertEqual(calls[0][1], 'DELETE')
        self.assertEqual(calls[0][3], b'')


class EntrySourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'source.db').start()
        self.mono = 100.
        async def noop(*_args):
            pass
        self.runtime = RecoveryRuntime(self.writer, None, None, tickers=('A',),
            subaccount=0, history_start=NOW.replace(hour=11), now=lambda: NOW,
            clock=lambda: self.mono, evaluate=noop, deadline_handler=noop,
            lifecycle_handler=noop)
        self.selection = self.runtime.attach_selection(offline_fixture=True)
        self.runtime.account.connect_generation()
        self.runtime.engine.begin_private_epoch()
        window = await self.writer.observe(NOW)
        evidence = normalize_snapshot((), (),
            dict(balance_dollars='500', updated_ts=1), subaccount=0)
        await self.runtime.account.finish_reconciliation(
            self.runtime.account.begin_reconciliation(NOW), evidence, NOW)
        current_terms = replace(terms(), observed_at=NOW,
            valid_until=NOW+timedelta(minutes=30),
            close_at=NOW+timedelta(hours=4),
            event_risk_at=NOW+timedelta(hours=2))
        self.runtime.management.set_terms(current_terms)
        current_program = replace(program(pool_centicents=5000000), start=NOW-timedelta(hours=1),
            end=NOW+timedelta(hours=1))
        self.selection.set_programs('A', (current_program,), observed_at=NOW,
            valid_until=NOW+timedelta(minutes=5))
        name, shard = next(iter(self.runtime.engine.shards.items()))
        generation = self.runtime.engine.begin_book_epoch(name)
        self.runtime.engine.submit_book(name, dict(type='orderbook_snapshot',
            sid=1, seq=1, msg=dict(market_ticker='A',
            yes_dollars_fp=[['.5', '1000']],
            no_dollars_fp=[['.6', '1000']])), generation=generation)
        await self.runtime.engine.step()
        market = SimpleNamespace(value=SimpleNamespace(exchange=1))
        self.runtime.market_inputs = SimpleNamespace(
            values={('market', 'A'): market},
            results={'A': SimpleNamespace(terms=current_terms)},
            _fresh=lambda row: row is market)
        self.runtime.accounting_result = SimpleNamespace(
            released=True, window=window)
        self.source = InventoryDispatchSource(self.runtime, offline_fixture=True)

    async def asyncTearDown(self):
        self.source.stop()
        self.runtime.engine.stop()
        await self.writer.close()
        self.temp.cleanup()

    async def test_ranked_market_becomes_exact_source_bound_pair(self):
        candidate = await self.source.refresh('A', ENTRY_PAIR)
        self.assertIsInstance(candidate, EntryPairCandidate)
        self.assertEqual({row['side'] for row in candidate.requests},
                         {'bid', 'ask'})
        self.assertFalse(self.source.validate_proof(
            'batch_create', candidate.requests))
        self.assertEqual(candidate.shard, 1)
        self.assertEqual(candidate.view.revision, self.writer.revision)
        prepared = await self.writer.reserve_entry_pair(candidate.requests,
            batch_id=candidate.batch_id, view=candidate.view,
            config=BotConfig(), now=NOW, free_cash=candidate.free_cash,
            account_known=True, offline_fixture=True,
            fee_per_contract_bound=candidate.fee_per_contract_bound)
        self.assertTrue(prepared.reserved, prepared.blockers)
        self.assertTrue(self.source.validate_proof(
            'batch_create', candidate.requests))
        await self.writer.abort_batch(prepared.batch)

    async def test_runtime_evaluation_queues_lower_priority_entry_pair(self):
        budget = WriteBudget(snapshot(rate=100, capacity=100), shards=(0, 1),
            now=quota_now(), offline_fixture=True)
        dispatcher = self.source.dispatcher(budget, invoke=BatchWire(),
            clock_pair=lambda: quota_now(1))
        service = self.runtime.attach_dispatch(self.source, dispatcher,
                                               offline_fixture=True)
        try:
            await self.runtime._evaluate('A', None, 0)
            self.assertEqual(dispatcher.status().queued, ((ENTRY_PAIR, 'A'),))
        finally:
            await service.close()
