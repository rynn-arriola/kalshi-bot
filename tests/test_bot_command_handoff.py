"""D-059 atomic preparation/dispatch handoff regressions; no live transport."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest

from kalshi_bot.command_types import CommandDenied
from kalshi_bot.adapters import PriceBand
from kalshi_bot.books import Book, Ladder
from kalshi_bot.config import BotConfig
from kalshi_bot.exits import ExitTerms, plan_exit
from kalshi_bot.execution import InjectedExecutor
from kalshi_bot.ledger import Fill
from kalshi_bot.management import InventoryManager, ManagedPlan
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def request(client="client"):
    return dict(ticker="A", client_order_id=client, side="bid", count="10",
        price="0.4", time_in_force="good_till_canceled",
        self_trade_prevention_type="taker_at_cross", post_only=True,
        reduce_only=False, cancel_order_on_pause=True, subaccount=0,
        exchange_index=1)


class CommandHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"handoff.db"
        self.writer = await LedgerWriter(self.path).start()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def reserve(self, client="client", attempt=None, view=None):
        req = request(client)
        return await self.writer.reserve_entry(req, attempt_id=attempt or "attempt-"+client,
            view=view or await self.writer.portfolio(subaccount=0, now=NOW),
            config=BotConfig(managed_market_slots=30), now=NOW, free_cash=D(500),
            account_known=True, offline_fixture=True)

    async def funded_position(self, *, working=False, quantity="3"):
        entry = (await self.reserve()).receipt
        self.assertTrue((await self.writer.begin_send(entry)).dispatch_allowed)
        remaining = str(D(10)-D(quantity)) if working else "0"
        await self.writer.record_outcome("ack", entry, dict(order_id="entry-order",
            client_order_id="client", fill_count=quantity, remaining_count=remaining,
            ts_ms=1), NOW)
        order = OrderUpdate("entry-order", "client", "A", "bid", D(".4"),
            D(10), D(quantity), D(remaining), "resting" if working else "canceled",
            0, 1, 1)
        await self.writer.order(order, NOW)
        await self.writer.fill(Fill("fill", "entry-order", "A", "bid",
                                    D(quantity), D(".4"), D(0)), NOW)
        return order

    @staticmethod
    def reducer(client="reduce", *, exchange_index=1, price="0.6", ioc=False):
        return dict(ticker="A", client_order_id=client, side="ask", count="3",
            price=price, time_in_force="immediate_or_cancel" if ioc else "good_till_canceled",
            self_trade_prevention_type="taker_at_cross", post_only=not ioc,
            reduce_only=True, cancel_order_on_pause=True, subaccount=0,
            exchange_index=exchange_index)

    async def reduction_proof(self, request, *, now=None):
        decision_now = now or (NOW+timedelta(seconds=900)
                               if request['time_in_force'] == 'immediate_or_cancel'
                               else NOW)
        inventory = await self.writer.market_inventory('A', subaccount=0)
        book = Book('A', Ladder(8), Ladder(8), True)
        if request['time_in_force'] == 'immediate_or_cancel':
            book.bids.set(D(request['price']), D(20))
            book.asks.set(D('.9'), D(20))
        else:
            book.asks.set(D(request['price']), D(20))
        bands = (PriceBand(D(0), D(1), D('.01')),)
        terms = ExitTerms('A', bands, decision_now,
            decision_now+timedelta(hours=1), decision_now+timedelta(hours=2),
            event_risk_at=decision_now+timedelta(hours=1),
            taker_fee_per_contract_bound=D('.01'))
        exit_plan = plan_exit(ticker='A', position=inventory.position,
            basis=inventory.yes_basis, first_seen_at=inventory.first_seen_at,
            orders=inventory.orders, book=book, terms=terms,
            journal=inventory.exit_journal, now=decision_now, complete_scope=True)
        plan = ManagedPlan('A', decision_now, 1, 1, 1, book.revision,
            inventory, exit_plan.passive, (), exit=exit_plan, terms=terms)
        if getattr(self, '_manager_writer', None) is not self.writer:
            runtime = SimpleNamespace(writer=self.writer)
            runtime.clock = lambda: 100.0
            runtime.now = lambda: runtime.current_now
            self._manager = InventoryManager(runtime)
            self._manager_writer = self.writer
        runtime = self._manager.runtime
        runtime.current_now = decision_now
        runtime.account = SimpleNamespace(connected=True, generation=1, revision=1)
        runtime.engine = SimpleNamespace(stopped=False,
            market_shard={'A': 'fixture'}, book_received={'A': 100.0},
            public={'fixture': False},
            shards={'fixture': SimpleNamespace(generation=1, failed=False,
                                                books={'A': book})})
        self._manager.terms['A'] = terms
        self._manager._plans['A'] = plan
        evidence = await self.writer.reduction_evidence(request, now=decision_now)
        return evidence, decision_now

    async def test_accounting_hold_preserves_verified_reduction_path(self):
        await self.funded_position()
        await self.writer.accounting_source_failed()
        request = self.reducer()
        proof, decision_now = await self.reduction_proof(request)
        prepared = await self.writer.prepare_reduction('accounting-held-reducer',
            request, evidence=proof, now=decision_now)
        self.assertTrue(prepared.reserved, prepared.blockers)
        sent = await self.writer.begin_send(prepared.receipt)
        self.assertTrue(sent.dispatch_allowed, sent.blockers)
        self.assertIn('accounting_source_failed', (await self.writer.accounting_status()).holds)

    async def test_atomic_prepare_returns_post_commit_receipt(self):
        result = await self.reserve()
        self.assertTrue(result.reserved, result.blockers)
        self.assertEqual(result.receipt.writer_revision, self.writer.revision)
        rows = await self.writer.mutations()
        self.assertEqual((len(rows), rows[0]["phase"]), (1, "PREPARED"))
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_concurrent_same_view_only_one_entry_is_authorized(self):
        view = await self.writer.portfolio(subaccount=0, now=NOW)
        first, second = await asyncio.gather(
            self.reserve("one", view=view), self.reserve("two", view=view))
        self.assertEqual(sum(result.reserved for result in (first, second)), 1)
        denied = second if first.reserved else first
        self.assertIn("stale_writer_evidence", denied.blockers)
        self.assertFalse(self.writer.failed)

    async def test_cross_ledger_and_old_epoch_receipts_cannot_send(self):
        receipt = (await self.reserve()).receipt
        other_path = Path(self.temp.name)/"other.db"
        other = await LedgerWriter(other_path).start()
        try:
            denied = await other.begin_send(receipt)
            self.assertEqual(denied.blockers, ("prepared_receipt_owner_changed",))
            self.assertFalse(other.failed)
        finally:
            await other.close()
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        denied = await self.writer.begin_send(receipt)
        self.assertEqual(denied.blockers, ("prepared_receipt_owner_changed",))
        self.assertFalse(self.writer.failed)

    async def test_stale_receipt_does_not_copy_latest_revision(self):
        receipt = (await self.reserve()).receipt
        await self.writer.observe(NOW)
        denied = await self.writer.begin_send(receipt)
        self.assertEqual(denied.blockers, ("stale_writer_evidence",))
        self.assertEqual((await self.writer.mutations())[0]["phase"], "PREPARED")
        self.assertFalse(self.writer.failed)

    async def test_relabelled_stale_receipt_conflicts_with_durable_issuance(self):
        receipt = (await self.reserve()).receipt
        await self.writer.observe(NOW)
        relabelled = replace(receipt, writer_revision=self.writer.revision)
        with self.assertRaises(InvalidData):
            await self.writer.begin_send(relabelled)
        self.assertTrue(self.writer.failed)

    async def test_relabelled_receipt_after_restart_cannot_send(self):
        receipt = (await self.reserve()).receipt
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        relabelled = replace(receipt, writer_epoch=self.writer.epoch,
                             writer_revision=self.writer.revision)
        with self.assertRaises(InvalidData):
            await self.writer.begin_send(relabelled)
        self.assertTrue(self.writer.failed)

    async def test_abort_is_durable_and_releases_only_unused_credits(self):
        receipt = (await self.reserve()).receipt
        result = await self.writer.abort_prepared(receipt)
        self.assertEqual(result.blockers, ("prepared_aborted",))
        capacity = await self.writer.command_capacity()
        self.assertEqual((capacity.mutation_held, capacity.intent_held,
                          capacity.order_held), (0, 0, 0))
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual((await self.writer.mutations())[0]["phase"], "NOT_SENT")
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 0)

    async def test_flat_reopen_gets_a_new_episode_identity(self):
        first = (await self.reserve()).receipt
        await self.writer.abort_prepared(first)
        second = (await self.reserve("second")).receipt
        self.assertNotEqual(first.episode_id, second.episode_id)

    async def test_unknown_send_retains_episode_credits_across_restart(self):
        receipt = (await self.reserve()).receipt
        self.assertTrue((await self.writer.begin_send(receipt)).dispatch_allowed)
        await self.writer.record_outcome("unknown", receipt, {}, NOW)
        before = await self.writer.command_capacity()
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        after = await self.writer.command_capacity()
        self.assertEqual(after, before)
        # Unknown entry authority survives, but no reducer is authorized until
        # durable inventory and routing evidence exist.
        unknown_request = dict(
            ticker="A", client_order_id="reduce", side="ask", count="10",
            price="0.6", time_in_force="good_till_canceled",
            self_trade_prevention_type="taker_at_cross", post_only=True,
            reduce_only=True, cancel_order_on_pause=True, subaccount=0,
            exchange_index=1)
        evidence, _ = await self.reduction_proof(unknown_request)
        self.assertIsNone(evidence)

    async def test_tampered_terms_trigger_integrity_failure_and_zero_dispatch(self):
        receipt = (await self.reserve()).receipt
        changed = receipt.request | {"price": "0.5"}
        tampered = replace(receipt, request_json=json.dumps(
            changed, sort_keys=True, separators=(",", ":")))
        calls = []
        executor = InjectedExecutor(self.writer, invoke=lambda *_: calls.append(1),
            validate_proof=lambda *_: True, offline_fixture=True)
        with self.assertRaises(InvalidData):
            await executor.execute_prepared(tampered)
        self.assertEqual(calls, [])
        self.assertTrue(self.writer.failed)

    async def test_tampered_episode_binding_is_also_an_integrity_failure(self):
        receipt = (await self.reserve()).receipt
        tampered = replace(receipt, episode_id="wrong-episode")
        with self.assertRaises(InvalidData):
            await self.writer.begin_send(tampered)
        self.assertTrue(self.writer.failed)

    async def test_only_one_executor_owner_is_allowed(self):
        async def invoke(*_):
            return dict(order_id="order", client_order_id="client", fill_count="0",
                        remaining_count="10", ts_ms=1)
        InjectedExecutor(self.writer, invoke=invoke, validate_proof=lambda *_: True,
                         offline_fixture=True)
        with self.assertRaisesRegex(InvalidData, "one mutation executor"):
            InjectedExecutor(self.writer, invoke=invoke, validate_proof=lambda *_: True,
                             offline_fixture=True)

    async def test_writer_change_after_begin_send_prevents_gateway_call(self):
        receipt = (await self.reserve()).receipt
        calls, notices = [], []
        original = self.writer.begin_send

        async def begin_then_change(value):
            result = await original(value)
            await self.writer.observe(NOW)
            return result

        self.writer.begin_send = begin_then_change
        async def invoke(*_):
            calls.append(1)
        executor = InjectedExecutor(self.writer, invoke=invoke,
            validate_proof=lambda *_: True, offline_fixture=True,
            after_outcome=lambda: notices.append('changed'))
        with self.assertRaises(CommandDenied) as denied:
            await executor.execute_prepared(receipt)
        self.assertEqual(denied.exception.blockers, ("proof_changed_before_submission",))
        self.assertEqual(calls, [])
        self.assertEqual((await self.writer.mutations())[0]["phase"], "NOT_SENT")
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 0)
        capacity = await self.writer.command_capacity()
        self.assertEqual((capacity.mutation_held, capacity.intent_held,
                          capacity.order_held), (0, 0, 0))
        self.assertFalse(executor.failed)
        self.assertEqual(notices, ['changed'])

    async def test_only_active_executor_can_record_proven_unsent_after_sending(self):
        receipt = (await self.reserve()).receipt
        executor = InjectedExecutor(self.writer, invoke=lambda *_: None,
            validate_proof=lambda *_: True, offline_fixture=True)
        self.assertTrue((await self.writer.begin_send(receipt)).dispatch_allowed)
        with self.assertRaisesRegex(
                InvalidData, 'only the active mutation executor'):
            await self.writer.abort_sending_before_submission(receipt, object())
        self.assertEqual((await self.writer.mutations())[0]['phase'], 'SENDING')
        await self.writer.abort_sending_before_submission(receipt, executor)
        self.assertEqual((await self.writer.mutations())[0]['phase'], 'NOT_SENT')

    async def test_proof_mutation_cannot_change_dispatched_terms(self):
        receipt = (await self.reserve()).receipt
        calls = []
        def proof(_, request):
            request['count'] = '100'
            request['price'] = '0.9'
            return True
        async def invoke(_, request):
            calls.append(request)
            return dict(order_id="order", client_order_id="client",
                fill_count="0", remaining_count="10", ts_ms=1)
        executor = InjectedExecutor(self.writer, invoke=invoke,
            validate_proof=proof, offline_fixture=True)
        await executor.execute_prepared(receipt)
        self.assertEqual((calls[0]['count'], calls[0]['price']), ('10', '0.4'))

    async def test_post_sending_proof_exception_persists_unknown_and_holds_owner(self):
        receipt = (await self.reserve()).receipt
        checks = 0
        def proof(*_):
            nonlocal checks
            checks += 1
            if checks == 2:
                raise RuntimeError('proof fixture failure')
            return True
        executor = InjectedExecutor(self.writer, invoke=lambda *_: None,
            validate_proof=proof, offline_fixture=True)
        with self.assertRaises(RuntimeError):
            await executor.execute_prepared(receipt)
        self.assertEqual((await self.writer.mutations())[0]['phase'], 'UNKNOWN')
        self.assertTrue(executor.failed)

    async def test_sending_diagnostic_failure_persists_unknown_and_holds_owner(self):
        class BrokenDiagnostics:
            def ensure_healthy(self): pass
            def emit(self, event, **_):
                if event == 'mutation_sending':
                    raise RuntimeError('diagnostic fixture failure')
        receipt = (await self.reserve()).receipt
        executor = InjectedExecutor(self.writer, invoke=lambda *_: None,
            validate_proof=lambda *_: True, offline_fixture=True,
            diagnostics=BrokenDiagnostics())
        with self.assertRaises(RuntimeError):
            await executor.execute_prepared(receipt)
        self.assertEqual((await self.writer.mutations())[0]['phase'], 'UNKNOWN')
        self.assertTrue(executor.failed)

    async def test_cancellation_during_begin_is_drained_without_dispatch(self):
        receipt = (await self.reserve()).receipt
        entered, release, calls = asyncio.Event(), asyncio.Event(), []
        original = self.writer.begin_send

        async def delayed_begin(value):
            entered.set()
            await release.wait()
            return await original(value)

        self.writer.begin_send = delayed_begin
        async def invoke(*_):
            calls.append(1)
        executor = InjectedExecutor(self.writer, invoke=invoke,
            validate_proof=lambda *_: True, offline_fixture=True)
        task = asyncio.create_task(executor.execute_prepared(receipt))
        await entered.wait()
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(calls, [])
        self.assertEqual((await self.writer.mutations())[0]["phase"], "UNKNOWN")

    async def test_cancellation_during_ack_recording_finishes_ack_and_holds_owner(self):
        receipt = (await self.reserve()).receipt
        entered, release, calls = asyncio.Event(), asyncio.Event(), []
        original = self.writer.record_outcome

        async def delayed_outcome(operation, *args):
            if operation == "ack":
                entered.set()
                await release.wait()
            return await original(operation, *args)

        self.writer.record_outcome = delayed_outcome
        async def invoke(*_):
            calls.append(1)
            return dict(order_id="order", client_order_id="client", fill_count="0",
                        remaining_count="10", ts_ms=1)
        executor = InjectedExecutor(self.writer, invoke=invoke,
            validate_proof=lambda *_: True, offline_fixture=True)
        task = asyncio.create_task(executor.execute_prepared(receipt))
        await entered.wait()
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(calls, [1])
        self.assertEqual((await self.writer.mutations())[0]["phase"], "ACK")
        self.assertTrue(executor.failed)

    async def test_reducer_rejects_caller_selected_route_and_working_entry(self):
        await self.funded_position()
        wrong = self.reducer(exchange_index=99)
        evidence, decision_now = await self.reduction_proof(wrong)
        self.assertEqual(evidence.exchange_index, 1)
        denied = await self.writer.prepare_reduction(
            "wrong-route", wrong, evidence=evidence, now=decision_now)
        self.assertIn('reduction_route_changed', denied.blockers)
        self.assertFalse(self.writer.failed)

        await self.writer.close()
        self.path = Path(self.temp.name)/'working.db'
        self.writer = await LedgerWriter(self.path).start()
        await self.funded_position(working=True)
        working_evidence, _ = await self.reduction_proof(self.reducer(ioc=True))
        self.assertIsNone(working_evidence)
        self.assertFalse(self.writer.failed)

    async def test_reducer_requires_complete_pending_fill_scope_and_exact_plan(self):
        await self.funded_position()
        request = self.reducer()
        evidence, decision_now = await self.reduction_proof(request)
        changed = request | {'price': '0.59'}
        changed_result = await self.writer.prepare_reduction(
            'changed-plan', changed, evidence=evidence, now=decision_now)
        self.assertIn('reduction_evidence_scope_changed', changed_result.blockers)
        self._manager.runtime.account.revision = 2
        stale_management = await self.writer.prepare_reduction(
            'stale-management', request, evidence=evidence, now=decision_now)
        self.assertIn('reduction_management_decision_changed',
                      stale_management.blockers)
        await self.writer.stage_fill(Fill('pending', 'unknown-order', 'A', 'bid',
            D(1), D('.4'), D(0)), owner=0, scope=0, exchange_index=1, now=NOW)
        pending_request = self.reducer('pending-reducer')
        pending_evidence, _ = await self.reduction_proof(pending_request)
        self.assertIsNone(pending_evidence)
        self.assertFalse(self.writer.failed)

    async def test_reducer_aborts_if_management_changes_while_prepare_is_queued(self):
        await self.funded_position()
        request = self.reducer()
        evidence, decision_now = await self.reduction_proof(request)
        entered, release = Event(), Event()
        original = self.writer._execute

        def delayed(ledger, command, args):
            if command == 'prepare_reduction':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test did not release writer')
            return original(ledger, command, args)

        self.writer._execute = delayed
        task = asyncio.create_task(self.writer.prepare_reduction(
            'raced-management', request, evidence=evidence, now=decision_now))
        self.assertTrue(await asyncio.to_thread(entered.wait, 5))
        self._manager.runtime.account.revision = 2
        release.set()
        result = await task

        self.assertEqual(result.blockers,
                         ('reduction_management_decision_changed',))
        self.assertIsNone(result.receipt)
        mutation = next(row for row in await self.writer.mutations()
                        if row['id'] == 'raced-management')
        self.assertEqual(mutation['phase'], 'NOT_SENT')
        inventory = await self.writer.market_inventory('A', subaccount=0)
        self.assertFalse(inventory.exit_journal.unresolved_ioc)
        self.assertFalse(self.writer.failed)

    async def test_aborted_cancel_reauthorizes_same_funded_slot_after_restart(self):
        await self.funded_position(working=True)
        request = dict(order_id='entry-order', market_ticker='A', subaccount=0,
                       exchange_index=1)
        first = await self.writer.prepare_cancel('cancel-one', request,
            evidence=await self.writer.cancel_evidence('entry-order'), now=NOW)
        before = await self.writer.command_capacity()
        await self.writer.abort_prepared(first.receipt)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        second = await self.writer.prepare_cancel('cancel-two', request,
            evidence=await self.writer.cancel_evidence('entry-order'), now=NOW)
        self.assertTrue(second.reserved, second.blockers)
        self.assertEqual(second.receipt.attempt_id, first.receipt.attempt_id)
        self.assertNotEqual(second.receipt.authorization_id,
                            first.receipt.authorization_id)
        after = await self.writer.command_capacity()
        self.assertEqual((after.mutation_used, after.mutation_held),
                         (before.mutation_used, before.mutation_held))
        self.assertTrue((await self.writer.begin_send(second.receipt)).dispatch_allowed)

    async def test_unknown_cancel_cannot_be_reauthorized(self):
        await self.funded_position(working=True)
        request = dict(order_id='entry-order', market_ticker='A', subaccount=0,
                       exchange_index=1)
        first = await self.writer.prepare_cancel('cancel-one', request,
            evidence=await self.writer.cancel_evidence('entry-order'), now=NOW)
        self.assertTrue((await self.writer.begin_send(first.receipt)).dispatch_allowed)
        await self.writer.record_outcome('unknown', first.receipt, {}, NOW)
        denied = await self.writer.prepare_cancel('cancel-two', request,
            evidence=await self.writer.cancel_evidence('entry-order'), now=NOW)
        self.assertEqual(denied.blockers, ('cancel_already_attempted',))

    async def test_aborted_ioc_reauthorizes_without_consuming_attempt_or_slot(self):
        await self.funded_position()
        first_request = self.reducer(ioc=True)
        first_evidence, first_now = await self.reduction_proof(first_request)
        first = await self.writer.prepare_reduction('ioc-one', first_request,
            evidence=first_evidence, now=first_now)
        before = await self.writer.command_capacity()
        await self.writer.abort_prepared(first.receipt)
        journal = (await self.writer.market_inventory('A', subaccount=0)).exit_journal
        self.assertEqual(journal.attempts, 0)
        self.assertFalse(journal.unresolved_ioc)
        second_request = self.reducer(ioc=True, price='0.59')
        second_evidence, second_now = await self.reduction_proof(second_request)
        second = await self.writer.prepare_reduction('ioc-two', second_request,
            evidence=second_evidence, now=second_now)
        self.assertTrue(second.reserved, second.blockers)
        self.assertEqual(second.receipt.attempt_id, first.receipt.attempt_id)
        after = await self.writer.command_capacity()
        self.assertEqual(after, before)
        self.assertTrue((await self.writer.begin_send(second.receipt)).dispatch_allowed)
        sending = (await self.writer.market_inventory('A', subaccount=0)).exit_journal
        self.assertEqual(sending.attempts, 1)
        self.assertTrue(sending.unresolved_ioc)

    async def test_passive_reducer_is_single_active_and_replacement_uses_free_capacity(self):
        entry = (await self.reserve()).receipt
        self.assertTrue((await self.writer.begin_send(entry)).dispatch_allowed)
        await self.writer.record_outcome("ack", entry, dict(order_id="entry-order",
            client_order_id="client", fill_count="3", remaining_count="7", ts_ms=1), NOW)
        original = OrderUpdate("entry-order", "client", "A", "bid", D(".4"),
            D(10), D(3), D(7), "resting", 0, 1, 1)
        await self.writer.order(original, NOW)
        await self.writer.fill(Fill("fill", "entry-order", "A", "bid", D(3),
                                    D(".4"), D(0)), NOW)
        await self.writer.order(replace(original, remaining=D(0), status="canceled",
                                        version_us=2), NOW)

        def reducer(client):
            return dict(ticker="A", client_order_id=client, side="ask", count="3",
                price="0.6", time_in_force="good_till_canceled",
                self_trade_prevention_type="taker_at_cross", post_only=True,
                reduce_only=True, cancel_order_on_pause=True, subaccount=0,
                exchange_index=1)

        evidence, decision_now = await self.reduction_proof(reducer("reduce-one"))
        first = await self.writer.prepare_reduction("reduce-one", reducer("reduce-one"),
                                                    evidence=evidence, now=decision_now)
        self.assertTrue(first.reserved, first.blockers)
        self.assertTrue((await self.writer.begin_send(first.receipt)).dispatch_allowed)
        duplicate_request = reducer("reduce-two")
        duplicate = await self.writer.prepare_reduction("reduce-two", duplicate_request,
            evidence=evidence, now=decision_now)
        self.assertIn("reduction_command_already_active", duplicate.blockers)
        await self.writer.record_outcome("ack", first.receipt, dict(order_id="reduce-order",
            client_order_id="reduce-one", fill_count="0", remaining_count="3", ts_ms=2), NOW)
        reducing = OrderUpdate("reduce-order", "reduce-one", "A", "ask", D(".6"),
            D(3), D(0), D(3), "resting", 0, 1, 3)
        await self.writer.order(reducing, NOW)
        await self.writer.order(replace(reducing, remaining=D(0), status="canceled",
                                        version_us=4), NOW)
        replacement_request = reducer("reduce-three")
        replacement_evidence, replacement_now = await self.reduction_proof(
            replacement_request)
        replacement = await self.writer.prepare_reduction("reduce-three",
            replacement_request, evidence=replacement_evidence,
            now=replacement_now)
        self.assertTrue(replacement.reserved, replacement.blockers)


if __name__ == "__main__":
    unittest.main()
