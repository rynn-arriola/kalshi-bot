"""Real owners + synthetic account/book/transport; never venue I/O."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.account import normalize_snapshot
from kalshi_bot.command_types import CommandDenied
from kalshi_bot.config import BotConfig
from kalshi_bot.dispatch import SAFETY_CANCEL, DUE_IOC, PASSIVE_REDUCER
from kalshi_bot.dispatch_sources import InventoryDispatchSource
from kalshi_bot.exits import ExitTerms
from kalshi_bot.ledger import Fill
from kalshi_bot.market_inputs import ExitInputService, FeeProfile
from kalshi_bot.metadata_scheduler import MetadataScheduler
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.values import InvalidData
from kalshi_bot.write_budget import WriteBudget
from kalshi_bot.writer import LedgerWriter
from test_bot_engine import NOW, BANDS, snapshot
from test_bot_inventory_risk import request
from test_bot_write_budget import snapshot as quota_snapshot, now as quota_now
from test_bot_market_inputs import Reads, review


class DispatchSourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'fixture.db').start()
        self.now, self.mono = NOW, 100.0
        async def ignore(*args):
            pass
        self.runtime = RecoveryRuntime(self.writer, None, None, tickers=('A', 'B'),
            subaccount=0, history_start=NOW-timedelta(hours=1), now=lambda: self.now,
            clock=lambda: self.mono, evaluate=ignore, deadline_handler=ignore,
            lifecycle_handler=ignore)
        self.runtime.account.connect_generation()
        self.runtime.engine.begin_private_epoch()
        await self.books()
        self.terms()
        self.source = InventoryDispatchSource(self.runtime, offline_fixture=True)
        self.calls = []
        self.budget = WriteBudget(quota_snapshot(rate=100, capacity=100),
            shards=(0, 1), now=quota_now(), offline_fixture=True)
        self.dispatcher = self.source.dispatcher(self.budget, invoke=self.invoke,
                                               clock_pair=lambda: quota_now(1))

    async def asyncTearDown(self):
        self.source.stop()
        try:
            await self.dispatcher.close()
        finally:
            await self.writer.close()
            self.temp.cleanup()

    async def books(self):
        for name, shard in self.runtime.engine.shards.items():
            generation = self.runtime.engine.begin_book_epoch(name)
            for seq, ticker in enumerate(sorted(shard.tickers), 1):
                event = snapshot(ticker, seq)
                self.runtime.engine.submit_book(name, event, generation=generation)
        while self.runtime.engine.backlog:
            await self.runtime.engine.step()

    def terms(self, **kwargs):
        terms = ExitTerms('A', BANDS, self.now, self.now+timedelta(hours=1),
            self.now+timedelta(hours=2), event_risk_at=self.now+timedelta(hours=1),
            taker_fee_per_contract_bound=D('.02'))
        self.runtime.management.set_terms(replace(terms, **kwargs))

    async def opening(self, *, filled='10', remaining='0', side='bid', route=0,
                      client='open', order_id='opening-order'):
        req = request(client, side=side) | dict(exchange_index=route)
        prepared = await self.writer.reserve_entry(req, attempt_id=client+'-attempt',
            view=await self.writer.portfolio(subaccount=0, now=self.now),
            config=BotConfig(), now=self.now, free_cash=D(500),
            account_known=True, offline_fixture=True)
        self.assertTrue(prepared.reserved, prepared.blockers)
        self.assertTrue((await self.writer.begin_send(prepared.receipt)).dispatch_allowed)
        await self.writer.record_outcome('ack', prepared.receipt,
            dict(order_id=order_id, fill_count=filled,
                 remaining_count=remaining, ts_ms=1), self.now)
        order = OrderUpdate(order_id, client, 'A', side, D('.5'), D(10),
            D(filled), D(remaining), 'resting' if D(remaining) else 'executed' if filled == '10' else 'canceled',
            0, route, 1)
        await self.writer.order(order, self.now)
        self.runtime.account._store_order((await self.writer.orders())[0])
        if D(filled):
            await self.writer.fill(Fill('opening-fill', order.order_id, 'A', side,
                D(filled), D('.5'), D(0)), self.now)
        return order

    async def report(self, quantity='10', orders=(), route=0):
        positions = () if D(quantity) == 0 else (dict(ticker='A', exchange_index=route,
            position_fp=quantity, market_exposure_dollars=str(abs(D(quantity))*D('.5'))),)
        rows = tuple(dict(order_id=o.order_id, client_order_id=o.client_id,
            ticker=o.ticker, status='resting', exchange_index=o.exchange_index,
            book_side=o.side, yes_price_dollars=str(o.yes_price),
            remaining_count_fp=str(o.remaining)) for o in orders)
        evidence = normalize_snapshot(rows, positions,
            dict(balance_dollars='500', updated_ts=1), subaccount=0)
        account = self.runtime.account
        await account.finish_reconciliation(account.begin_reconciliation(self.now),
                                             evidence, self.now)

    async def ready(self, **kwargs):
        order = await self.opening(**kwargs)
        qty = str(order.filled*(1 if order.side == 'bid' else -1))
        await self.report(qty, (order,) if order.remaining else (), order.exchange_index)
        return order

    async def invoke(self, kind, request):
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'SENDING')
        self.calls.append((kind, request))
        if kind == 'cancel':
            return dict(order_id=request['order_id'], reduced_by='6', ts_ms=1)
        return dict(order_id='reducer-order', fill_count='0', ts_ms=1,
            remaining_count='0' if request['time_in_force'] == 'immediate_or_cancel' else request['count'])

    async def run_priority(self, priority=PASSIVE_REDUCER):
        self.assertTrue(self.dispatcher.submit('A', priority))
        return await self.dispatcher.run_one()

    async def due(self):
        self.now += timedelta(seconds=900)
        self.mono += 900
        await self.books()
        await self.report()

    async def test_no_live_or_fake_runtime_construction(self):
        for flag in (False, 1, None):
            with self.assertRaises(InvalidData):
                InventoryDispatchSource(self.runtime, offline_fixture=flag)
        with self.assertRaises(InvalidData):
            InventoryDispatchSource(object(), offline_fixture=True)

    async def test_only_durable_safety_ack_advances_recovery_progress(self):
        from kalshi_bot.dispatch import DispatchResult, ENTRY_PAIR
        self.runtime.recovery_state = 'blocked_retry_exhausted'
        self.runtime.recovery_requested.clear()
        for state in ('UNKNOWN', 'REJECTED', 'BLOCKED', 'WAITING', 'FAILED'):
            self.source._dispatch_result(DispatchResult(state, 'A', SAFETY_CANCEL))
        self.source._dispatch_result(DispatchResult('ACK', 'A', ENTRY_PAIR))
        self.assertEqual(self.runtime.recovery_action_progress, 0)
        self.assertFalse(self.runtime.recovery_requested.is_set())
        self.source._dispatch_result(DispatchResult('ACK', 'A', SAFETY_CANCEL))
        self.assertEqual(self.runtime.recovery_action_progress, 1)
        self.assertTrue(self.runtime.recovery_requested.is_set())
        self.assertIsNone(self.runtime.account.current_report(self.now))

    async def test_late_paused_drain_ack_keeps_shared_idle_recovery_wake(self):
        from kalshi_bot.dispatch import DispatchResult
        self.runtime.recovery_state = 'blocked_retry_exhausted'
        self.runtime.recovery_requested.clear()
        self.runtime._post_drain_recovery_pending = True
        self.source._dispatch_result(DispatchResult('ACK', 'A', SAFETY_CANCEL))
        self.assertEqual(self.runtime.recovery_action_progress, 1)
        self.assertFalse(self.runtime.recovery_requested.is_set())
        self.assertTrue(self.runtime._post_drain_recovery_pending)

    async def test_empty_discovered_market_does_not_flood_inventory_logs(self):
        events = []
        self.runtime.diagnostics = type('Log', (), {
            'emit': lambda _self, event, **fields: events.append((event, fields)) or True,
            'ensure_healthy': lambda _self: None})()
        await self.report('0')
        await self.runtime.management.refresh('B')
        await self.runtime.management.refresh('B')
        self.assertFalse([event for event, _ in events
                          if event == 'inventory_plan_changed'])

        # A formerly material market emits one final state and is then removed
        # from the deduplication map instead of repeating on every refresh.
        self.runtime.management._logged_states['B'] = ('passive', ())
        await self.runtime.management.refresh('B')
        count = len([event for event, _ in events
                     if event == 'inventory_plan_changed'])
        await self.runtime.management.refresh('B')
        self.assertEqual(len([event for event, _ in events
                              if event == 'inventory_plan_changed']), count)
        self.assertNotIn('B', self.runtime.management._logged_states)

    async def test_passive_yes_exact_quantity_price_route_durable_handoff(self):
        await self.ready(filled='4', route=1)
        result = await self.run_priority()
        self.assertEqual(result.state, 'ACK')
        self.assertEqual(self.runtime.recovery_action_progress, 1)
        kind, req = self.calls[0]
        self.assertEqual((kind, req['side'], D(req['price']), D(req['count']),
                          req['exchange_index']), ('create', 'ask', D('.59'), 4, 1))
        self.assertFalse(req['reduce_only']); self.assertTrue(req['post_only'])
        self.assertFalse(result.live_ready)
        self.assertIsNone(await self.source.refresh('A', PASSIVE_REDUCER))

    async def test_passive_no_maps_to_bid_not_double_complement(self):
        await self.ready(side='ask')
        self.assertEqual((await self.run_priority()).state, 'ACK')
        req = self.calls[0][1]
        self.assertEqual((req['side'], D(req['price']), D(req['count'])), ('bid', D('.41'), 10))

    async def test_due_ioc_exact_inventory_no_expiration(self):
        await self.ready()
        await self.due()
        self.assertEqual((await self.run_priority(DUE_IOC)).state, 'ACK')
        req = self.calls[0][1]
        self.assertEqual((req['side'], D(req['price']), D(req['count']), req['time_in_force']),
                         ('ask', D('.4'), 10, 'immediate_or_cancel'))
        self.assertFalse(req['post_only'])
        self.assertTrue(req['reduce_only'])
        self.assertNotIn('expiration_time', req)

    async def metadata_during_exit(self, *, due=False, changed=False):
        await self.ready()
        if due:
            await self.due()
        reads = Reads(('A',))
        service = ExitInputService(reads, ('A',), now=lambda:self.now,
            clock=lambda:self.mono, ttl=30, timing_reviews=(review(reads.markets['A']),),
            fee_profile=FeeProfile(D('.0001'), 'fixture', NOW+timedelta(hours=1)))
        service.bind(self.runtime.management.set_terms, self.runtime.management.revoke_terms)
        scheduler = MetadataScheduler(service, defer=lambda:True)
        service.begin(1)
        service.subscribed(1, 7)
        await service.refresh('A')
        original = self.writer.prepare_reduction
        async def overlap(*args, **kwargs):
            prepared = await original(*args, **kwargs)
            scheduler.request('A')
            scheduler.step()
            await service.refresh('A')  # Cached identical publication at prepare edge.
            if changed:
                service.ingest(dict(type='market_lifecycle_v2', sid=7, seq=1,
                    msg=dict(market_ticker='A', event_type='deactivated')), generation=1)
            return prepared
        self.writer.prepare_reduction = overlap
        try:
            result = await self.run_priority(DUE_IOC if due else PASSIVE_REDUCER)
            self.assertEqual(result.state, 'BLOCKED' if changed else 'ACK', result.blockers)
            self.assertEqual(len(self.calls), 0 if changed else 1)
            self.assertFalse(self.dispatcher.status().failed)
            self.assertEqual((await self.writer.mutations())[-1]['phase'],
                             'NOT_SENT' if changed else 'ACK')
            self.assertEqual(scheduler.started, 0)
        finally:
            await scheduler.close()

    async def test_identical_metadata_during_passive_prepare_keeps_exit_proof(self):
        await self.metadata_during_exit()

    async def test_identical_metadata_during_timed_prepare_keeps_exit_proof(self):
        await self.metadata_during_exit(due=True)

    async def test_real_metadata_change_during_exit_prepare_still_blocks(self):
        await self.metadata_during_exit(changed=True)

    async def test_deferred_early_exit_still_places_exact_passive_reducer(self):
        await self.ready(filled='4')
        self.now += timedelta(seconds=900)
        self.mono += 900
        await self.books()
        await self.report('4')
        # Stress has too little depth, but a real passive touch is available.
        _, book = self.runtime.management._book('A')
        book.bids.set(D('.4'), D(1))
        self.assertEqual((await self.runtime.management.refresh('A')).exit.mode,
                         'passive_deferred')
        self.assertEqual((await self.run_priority()).state, 'ACK')
        req = self.calls[0][1]
        self.assertEqual((req['side'], D(req['count']), req['time_in_force']),
                         ('ask', D(4), 'good_till_canceled'))
        self.assertTrue(req['post_only']); self.assertFalse(req['reduce_only'])

    async def test_deferred_early_exit_still_cancels_building_partial_fill(self):
        order = await self.ready(filled='4', remaining='6')
        self.now += timedelta(seconds=900)
        self.mono += 900
        await self.books()
        await self.report('4', (order,))
        _, book = self.runtime.management._book('A')
        book.bids.set(D('.4'), D(1))
        self.assertEqual((await self.runtime.management.refresh('A')).exit.mode,
                         'passive_deferred')
        self.assertEqual((await self.run_priority(SAFETY_CANCEL)).state, 'ACK')
        self.assertEqual(self.calls[0][1]['order_id'], order.order_id)
        # ACK is not terminal/no-fill evidence, including on the deferred path.
        await self.report('4', (order,))
        self.assertIsNone(await self.source.refresh('A', PASSIVE_REDUCER))

    async def test_owned_building_cancel_ack_never_unblocks_reducer(self):
        await self.ready(filled='4', remaining='6')
        self.assertEqual((await self.run_priority(SAFETY_CANCEL)).state, 'ACK')
        self.assertEqual(self.calls[0][0], 'cancel')
        await self.report('4', ((await self.writer.orders())[0].order,))
        for priority in (SAFETY_CANCEL, PASSIVE_REDUCER, DUE_IOC):
            self.assertIsNone(await self.source.refresh('A', priority))
        self.assertEqual(len(self.calls), 1)

    async def test_paused_drain_cancels_all_exact_entries_without_recovery_between(self):
        first = await self.opening(filled='0', remaining='10', side='bid',
                                   client='first', order_id='first-order')
        second = await self.opening(filled='0', remaining='10', side='ask',
                                    client='second', order_id='second-order')
        await self.report('0', (first, second))
        self.runtime.live_session = type('Paused', (), {'entries_paused': True})()
        self.assertEqual((await self.run_priority(SAFETY_CANCEL)).state, 'ACK')
        # The first cancel ACK is not terminal proof and makes the account
        # report stale. The second exact safety cancel must still proceed.
        self.assertIsNone(self.runtime.account.current_report(self.now))
        self.assertEqual((await self.run_priority(SAFETY_CANCEL)).state, 'ACK')
        self.assertEqual({row[1]['order_id'] for row in self.calls},
                         {'first-order', 'second-order'})
        self.assertEqual(self.runtime.recovery_action_progress, 2)
        self.assertTrue(all(row['phase'] == 'ACK' for row in await self.writer.mutations()))
        self.assertIsNone(await self.source.refresh('A', SAFETY_CANCEL))

    async def test_paused_drain_falls_through_to_cancel_due_passive_reducer(self):
        await self.ready()
        self.assertEqual((await self.run_priority(PASSIVE_REDUCER)).state, 'ACK')
        request = self.calls[-1][1]
        reducer = OrderUpdate('reducer-order', request['client_order_id'], 'A',
            request['side'], D(request['price']), D(request['count']), D(0),
            D(request['count']), 'resting', 0, request['exchange_index'], 2)
        receipt = await self.writer.order(reducer, self.now)
        self.assertTrue(receipt.reducing)
        self.runtime.account._store_order(receipt)
        self.now += timedelta(seconds=900)
        self.mono += 900
        await self.books()
        await self.report('10', (reducer,))
        self.runtime.live_session = type('Paused', (), {'entries_paused': True})()
        plan = await self.runtime.management.refresh('A')
        self.assertEqual(plan.exit.mode, 'cancel_before_ioc')

        self.assertEqual((await self.run_priority(SAFETY_CANCEL)).state, 'ACK')
        self.assertEqual(self.calls[-1], ('cancel', {
            'order_id': reducer.order_id, 'market_ticker': 'A',
            'subaccount': 0, 'exchange_index': 0}))

    async def test_final_paused_cancel_wakes_exhausted_recovery_once_when_idle(self):
        from types import SimpleNamespace
        await self.test_paused_drain_cancels_all_exact_entries_without_recovery_between()
        self.assertTrue(self.runtime._post_drain_recovery_pending)
        self.runtime.dispatch_supervisor = SimpleNamespace(dispatcher=self.dispatcher)
        self.runtime.recovery_state = 'blocked_retry_exhausted'
        self.runtime.recovery_requested.clear()
        self.dispatcher.submit('A', SAFETY_CANCEL)
        self.assertFalse(self.runtime._request_post_drain_recovery())
        await self.dispatcher.run_one()  # No further eligible cancel.
        self.assertTrue(self.runtime._request_post_drain_recovery())
        self.assertTrue(self.runtime.recovery_requested.is_set())
        self.runtime.recovery_requested.clear()
        self.assertFalse(self.runtime._request_post_drain_recovery())
        self.assertFalse(self.runtime.recovery_requested.is_set())

    async def test_post_drain_wake_waits_for_inflight_recovery(self):
        from types import SimpleNamespace
        await self.test_paused_drain_cancels_all_exact_entries_without_recovery_between()
        self.runtime.dispatch_supervisor = SimpleNamespace(dispatcher=self.dispatcher)
        self.runtime.recovery_state = 'recovering'
        self.assertFalse(self.runtime._request_post_drain_recovery())
        self.assertTrue(self.runtime._post_drain_recovery_pending)
        self.runtime.recovery_state = 'blocked_retry_exhausted'
        self.assertTrue(self.runtime._request_post_drain_recovery())

    async def test_missing_account_terms_and_wrong_priority_block(self):
        await self.opening()
        self.assertIsNone(await self.source.refresh('A', PASSIVE_REDUCER))
        await self.report()
        self.runtime.management.revoke_terms('A')
        self.assertIsNone(await self.source.refresh('A', PASSIVE_REDUCER))
        self.terms()
        self.assertIsNone(await self.source.refresh('A', DUE_IOC))
        self.assertIsNone(await self.source.refresh('A', SAFETY_CANCEL))
        self.assertIsNone(await self.source.refresh('OUTSIDE', PASSIVE_REDUCER))
        self.assertIsNone(await self.source.refresh('A', 'entry'))
        self.assertFalse(self.calls)

    async def test_due_missing_fee_cannot_fall_back_to_old_passive_subplan(self):
        await self.ready(filled='4', remaining='6')
        self.now += timedelta(seconds=900)
        await self.books()
        await self.report('4', ((await self.writer.orders())[0].order,))
        self.terms(taker_fee_per_contract_bound=None)
        for priority in (SAFETY_CANCEL, PASSIVE_REDUCER, DUE_IOC):
            self.assertIsNone(await self.source.refresh('A', priority))

    async def test_due_working_order_cancels_before_ioc(self):
        order = await self.ready(filled='4', remaining='6')
        self.now += timedelta(seconds=900)
        await self.books()
        await self.report('4', (order,))
        self.assertIsNone(await self.source.refresh('A', DUE_IOC))
        self.assertEqual((await self.run_priority(SAFETY_CANCEL)).state, 'ACK')
        self.assertEqual(self.calls[0][0], 'cancel')

    async def test_stale_cancel_ownership_evidence_is_discarded(self):
        await self.ready(filled='4', remaining='6')
        original = self.writer.cancel_evidence
        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.runtime._revoke()
            return result
        self.writer.cancel_evidence = changed
        self.assertIsNone(await self.source.refresh('A', SAFETY_CANCEL))
        self.assertIsNone(self.source._proof)

    async def test_private_ingress_during_evidence_await_revokes_candidate(self):
        await self.ready()
        original = self.writer.reduction_evidence
        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.runtime._revoke()
            return result
        self.writer.reduction_evidence = changed
        self.assertIsNone(await self.source.refresh('A', PASSIVE_REDUCER))
        self.assertIsNone(self.source._proof)

    async def prepared(self):
        candidate = await self.source.refresh('A', PASSIVE_REDUCER)
        self.assertIsNotNone(candidate)
        result = await self.writer.prepare_reduction(candidate.attempt_id, candidate.request,
            evidence=candidate.evidence, now=self.now)
        self.assertTrue(result.reserved, result.blockers)
        self.assertTrue(self.source.validate_proof('create', candidate.request))
        return candidate, result.receipt

    async def test_mutable_request_and_another_plan_cannot_reuse_proof(self):
        await self.ready()
        candidate, receipt = await self.prepared()
        self.assertFalse(self.source.validate_proof('create', candidate.request | {'count': '1'}))
        self.assertFalse(self.source.validate_proof('cancel', candidate.request))
        self.runtime.management.invalidate('A')
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        await self.writer.abort_prepared(receipt)

    async def test_queued_book_change_revokes_at_sending(self):
        await self.ready()
        original = self.writer.begin_send
        async def changed(receipt):
            result = await original(receipt)
            name = self.runtime.engine.market_shard['A']
            shard = self.runtime.engine.shards[name]
            self.runtime.engine.submit_book(name,
                dict(type='orderbook_delta',sid=1,seq=2,
                     msg=dict(market_ticker='A',side='yes',price_dollars='.1',delta_fp='1')),
                generation=shard.generation)
            return result
        self.writer.begin_send = changed
        result = await self.run_priority()
        self.assertEqual((result.state, result.blockers),
                         ('BLOCKED', ('proof_changed_before_submission',)))
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')
        self.assertFalse(self.calls)

    async def test_account_change_in_sync_quota_hook_is_rechecked(self):
        await self.ready()
        original = self.budget.consume
        def changed(*args, **kwargs):
            original(*args, **kwargs)
            self.runtime._revoke()
        self.budget.consume = changed
        result = await self.run_priority()
        self.assertEqual((result.state, result.blockers),
                         ('BLOCKED', ('proof_changed_before_submission',)))
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')
        self.assertFalse(self.calls)

    async def test_passive_deadline_crossing_revokes_still_fresh_plan(self):
        await self.ready()
        self.terms(flatten_at=self.now+timedelta(seconds=1))
        candidate, receipt = await self.prepared()
        self.now += timedelta(seconds=1)
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        await self.writer.abort_prepared(receipt)

    async def test_already_forced_ioc_revoked_at_trading_close(self):
        await self.ready()
        self.terms(flatten_at=self.now-timedelta(seconds=1),
                   close_at=self.now+timedelta(seconds=1))
        candidate = await self.source.refresh('A', DUE_IOC)
        self.assertIsNotNone(candidate)
        result = await self.writer.prepare_reduction(candidate.attempt_id, candidate.request,
            evidence=candidate.evidence, now=self.now)
        self.assertTrue(result.reserved, result.blockers)
        self.assertTrue(self.source.validate_proof('create', candidate.request))
        self.now += timedelta(seconds=1)
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        with self.assertRaises(CommandDenied):
            await self.dispatcher.executor.execute_prepared(result.receipt)
        self.assertFalse(self.calls)
        await self.writer.abort_prepared(result.receipt)

    async def test_old_report_cannot_renew_age_via_new_plan(self):
        await self.ready()
        self.now += timedelta(seconds=4)
        candidate, receipt = await self.prepared()
        self.now += timedelta(seconds=2)
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        await self.writer.abort_prepared(receipt)

    async def test_book_ingress_age_and_terms_replacement_revoke(self):
        await self.ready()
        candidate, receipt = await self.prepared()
        self.mono += 6
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        self.mono -= 6
        self.terms()
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        await self.writer.abort_prepared(receipt)

    async def test_runtime_shutdown_and_source_stop_revoke(self):
        await self.ready()
        candidate, receipt = await self.prepared()
        self.runtime.stop_requested.set()
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        self.source.stop()
        self.runtime.stop_requested.clear()
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        self.assertIsNone(await self.source.refresh('A', PASSIVE_REDUCER))
        await self.writer.abort_prepared(receipt)

    async def test_epoch_change_cannot_restore_pinned_proof(self):
        await self.ready()
        candidate, receipt = await self.prepared()
        await self.writer.abort_prepared(receipt)
        self.runtime.account.disconnect()
        self.runtime.account.connect_generation()
        self.assertFalse(self.source.validate_proof('create', candidate.request))
        self.assertIsNone(await self.source.refresh('A', PASSIVE_REDUCER))

    async def test_unrelated_writer_revision_is_not_own_send_revision(self):
        await self.ready()
        candidate, receipt = await self.prepared()
        await self.writer.observe(self.now)
        # Source fence alone never substitutes for the exact prepared receipt.
        with self.assertRaises(CommandDenied):
            await self.dispatcher.executor.execute_prepared(receipt)
        self.assertFalse(self.calls)
        await self.writer.abort_prepared(receipt)

    async def test_dispatcher_stop_after_first_refresh_has_no_prepared_command(self):
        await self.ready()
        original = self.dispatcher.refresh
        async def stopped(*args):
            result = await original(*args)
            self.dispatcher.stop()
            return result
        self.dispatcher.refresh = stopped
        self.assertEqual((await self.run_priority()).state, 'INTERRUPTED')
        self.assertEqual(len(await self.writer.mutations()), 1)
        self.assertFalse(self.calls)

    async def test_dispatcher_stop_after_second_refresh_releases_permit(self):
        await self.ready()
        original = self.dispatcher.refresh
        refreshes = 0
        async def stopped(*args):
            nonlocal refreshes
            result = await original(*args)
            refreshes += 1
            if refreshes == 2:
                self.dispatcher.stop()
            return result
        self.dispatcher.refresh = stopped
        self.assertEqual((await self.run_priority()).state, 'INTERRUPTED')
        self.assertEqual(len(await self.writer.mutations()), 1)
        self.assertEqual(self.budget.status(now=quota_now(1)).outstanding, 0)
        self.assertFalse(self.calls)

    async def test_dispatcher_stop_inside_quota_hook_never_invokes(self):
        await self.ready()
        original = self.budget.consume
        def stopped(*args, **kwargs):
            original(*args, **kwargs)
            self.dispatcher.stop()
        self.budget.consume = stopped
        with self.assertRaises(CommandDenied):
            await self.run_priority()
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertFalse(self.calls)

    async def test_caller_cancellation_retains_injected_outcome_owner(self):
        await self.ready()
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(kind, req):
            entered.set()
            await release.wait()
            return await self.invoke(kind, req)
        self.dispatcher.executor.invoke = held
        task = asyncio.create_task(self.run_priority())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'ACK')
        self.assertEqual(len(self.calls), 1)

    async def test_dispatcher_stop_during_prepare_aborts_unsent(self):
        await self.ready()
        original = self.writer.prepare_reduction
        async def stopped(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.dispatcher.stop()
            return result
        self.writer.prepare_reduction = stopped
        self.assertEqual((await self.run_priority()).state, 'INTERRUPTED')
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')
        self.assertFalse(self.calls)

    async def test_dispatcher_stop_during_sending_records_unknown_no_invoke(self):
        await self.ready()
        original = self.writer.begin_send
        async def stopped(receipt):
            result = await original(receipt)
            self.dispatcher.stop()
            return result
        self.writer.begin_send = stopped
        with self.assertRaises(CommandDenied):
            await self.run_priority()
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertFalse(self.calls)

    async def test_concurrent_refresh_revokes_both_without_second_read(self):
        await self.ready()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.writer.reduction_evidence
        async def held(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        self.writer.reduction_evidence = held
        task = asyncio.create_task(self.source.refresh('A', PASSIVE_REDUCER))
        await asyncio.wait_for(entered.wait(), 2)
        self.assertIsNone(await self.source.refresh('A', PASSIVE_REDUCER))
        release.set()
        self.assertIsNone(await task)
        self.assertIsNone(self.source._proof)

    async def test_unknown_invoke_never_retries_or_claims_ack(self):
        await self.ready()
        async def uncertain(*args):
            raise TimeoutError('synthetic')
        self.dispatcher.executor.invoke = uncertain
        with self.assertRaises(TimeoutError):
            await self.run_priority()
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertEqual((await self.dispatcher.run_one()).state, 'FAILED')
