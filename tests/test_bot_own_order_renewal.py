"""D-134 own-order renewal, history floor and chained recovery; no network."""
from decimal import Decimal as D
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kalshi_bot.dispatch_sources import InventoryDispatchSource
from kalshi_bot.mutation_outcomes import MutationNotice
from kalshi_bot.orders import OrderUpdate
from tests import test_bot_account_release as baseline
from tests import test_bot_routine_refresh as routine


def resting_row(order_id, client):
    return dict(order_id=order_id, client_order_id=client, ticker='A', book_side='bid',
        yes_price_dollars='.01', initial_count_fp='10', fill_count_fp='0',
        remaining_count_fp='10', status='resting', subaccount=0, exchange_index=1,
        last_update_time='1970-01-01T00:00:00.000001Z')


class OwnOrderRenewalTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch
    refresh = baseline.AccountReleaseTests.refresh
    reserve = baseline.AccountReleaseTests.reserve
    runtime = routine.RoutineRefreshTests.runtime
    advance = routine.RoutineRefreshTests.advance

    async def place_own_order(self, runtime, client='own-1', order_id='order-own-1'):
        """The bot's own entry is acknowledged and appears resting at the venue."""
        req = dict(baseline.request(client), price='0.01')
        reserved = await self.reserve(client, req=req)
        self.assertTrue(reserved.reserved, reserved.blockers)
        self.assertTrue((await self.writer.begin_send(reserved.receipt)).dispatch_allowed)
        await self.writer.record_outcome('ack', reserved.receipt, dict(order_id=order_id,
            client_order_id=client, fill_count='0', remaining_count='10', ts_ms=1), self.now)
        await self.writer.order(OrderUpdate(order_id, client, 'A', 'bid', D('.01'),
            D(10), D(0), D(10), 'resting', 0, 1, 1), self.now)
        runtime.reads.orders += (resting_row(order_id, client),)
        runtime._revoke(economic=False)  # What the acknowledgement notice does.

    async def renew_own(self, runtime):
        self.advance(1)
        anchor = runtime._current_own_order_anchor()
        self.assertIsNotNone(anchor)
        return anchor, await runtime._refresh_routine_account(anchor=anchor)

    # ---- item 1: renewal after the bot's own acknowledged orders ----

    async def test_own_ack_renews_without_full_recovery_or_history_replay(self):
        runtime = await self.runtime()
        await self.place_own_order(runtime)
        self.assertTrue(runtime.own_order_acknowledged())
        runtime.reads.calls.clear()
        anchor, renewed = await self.renew_own(runtime)
        self.assertTrue(renewed)
        self.assertFalse(runtime.recovery_requested.is_set())
        self.assertTrue(runtime.accounting_result.released)
        self.assertTrue(self.writer._accounting_lease.fence.current())
        # Only the elapsed tail was enumerated: no replay from the boundary.
        self.assertNotIn('historical_fills', runtime.reads.calls)
        proof = runtime._current_routine_proof()
        self.assertEqual(proof.receipt_ids[:-1], anchor.receipt_ids)
        self.assertEqual(len(runtime.account.report.snapshot.orders), 1)
        self.assertEqual(runtime.own_order_renewal['completed'], 1)

    async def test_changed_position_after_own_ack_escalates_immediately(self):
        runtime = await self.runtime()
        await self.place_own_order(runtime)
        original = runtime.reads.collect
        async def filled(name, **kwargs):
            if name == 'positions':
                return baseline.PageSet((dict(ticker='A', exchange_index=1, position_fp='3',
                    market_exposure_dollars='.03'),), 1, 20)
            return await original(name, **kwargs)
        runtime.reads.collect = filled
        anchor, renewed = await self.renew_own(runtime)
        self.assertFalse(renewed)
        self.assertTrue(runtime.recovery_requested.is_set())
        self.assertEqual(runtime.own_order_renewal['retries'], 0)
        self.assertEqual(runtime.own_order_renewal['escalations'], 1)

    async def test_consistent_but_changed_position_is_never_explained(self):
        # An acknowledgement can itself carry a fill (e.g. an IOC exit): the
        # ledger then agrees with the venue, yet the position still changed.
        runtime = await self.runtime()
        proof = runtime._chain_anchor()
        positions, orders, balance, subaccount = proof.snapshot_signature
        audit = SimpleNamespace(consistent=True)
        changed = SimpleNamespace(snapshot=SimpleNamespace(
            positions=('A', 3), orders=orders, available_balance=balance,
            subaccount=subaccount), positions_match=True, audit=audit)
        same = SimpleNamespace(snapshot=SimpleNamespace(positions=positions, orders=orders,
            available_balance=balance, subaccount=subaccount), positions_match=True, audit=audit)
        self.assertTrue(runtime._snapshot_explained(same, proof, own_orders=True))
        self.assertFalse(runtime._snapshot_explained(changed, proof, own_orders=True))

    async def test_unchanged_orders_cannot_explain_changed_cash(self):
        runtime = await self.runtime()
        runtime._revoke(economic=False)
        runtime.reads.cash = dict(runtime.reads.cash, balance=49000, balance_dollars='490')
        anchor, renewed = await self.renew_own(runtime)
        self.assertFalse(renewed)
        self.assertTrue(runtime.recovery_requested.is_set())

    async def test_racing_order_update_retries_bounded_then_escalates(self):
        runtime = await self.runtime()
        await self.place_own_order(runtime)
        original = runtime.account.reconcile
        async def raced(*args, **kwargs):
            runtime._revoke(economic=False)  # The venue's own order update lands.
            return await original(*args, **kwargs)
        with patch.object(runtime.account, 'reconcile', raced):
            for attempt in range(runtime.OWN_ORDER_RETRIES):
                self.assertFalse((await self.renew_own(runtime))[1])
                self.assertFalse(runtime.recovery_requested.is_set())
            self.assertFalse((await self.renew_own(runtime))[1])
        self.assertTrue(runtime.recovery_requested.is_set())
        self.assertEqual(runtime.own_order_renewal['retries'], runtime.OWN_ORDER_RETRIES)

    # ---- D-136: an acknowledged order the venue has not listed yet ----

    def capture(self, runtime):
        events = []
        original = runtime.diagnostics.emit
        def emit(name, **context):
            events.append((name, context))
            return original(name, **context)
        runtime.diagnostics.emit = emit
        return events

    async def test_not_yet_listed_own_order_retries_then_renews(self):
        runtime = await self.runtime()
        await self.place_own_order(runtime)
        listed, runtime.reads.orders = runtime.reads.orders, ()  # REST lags the ACK.
        events = self.capture(runtime)
        self.assertFalse((await self.renew_own(runtime))[1])
        self.assertFalse(runtime.recovery_requested.is_set())
        self.assertEqual(runtime.own_order_renewal['retries'], 1)
        failed = [c for n, c in events if n == 'account_refresh_failed']
        self.assertEqual(failed[-1]['outcome'], 'order_not_visible')
        runtime.reads.orders = listed  # The venue now lists it.
        self.assertTrue((await self.renew_own(runtime))[1])
        self.assertFalse(runtime.recovery_requested.is_set())

    async def test_order_that_never_appears_escalates_after_bounded_retries(self):
        runtime = await self.runtime()
        await self.place_own_order(runtime)
        runtime.reads.orders = ()
        for _ in range(runtime.OWN_ORDER_RETRIES):
            self.assertFalse((await self.renew_own(runtime))[1])
            self.assertFalse(runtime.recovery_requested.is_set())
        self.assertFalse((await self.renew_own(runtime))[1])
        self.assertTrue(runtime.recovery_requested.is_set())

    async def test_other_audit_disagreement_escalates_immediately(self):
        runtime = await self.runtime()
        await self.place_own_order(runtime)
        runtime.reads.orders += (resting_row('foreign-order', 'someone-else'),)
        events = self.capture(runtime)
        self.assertFalse((await self.renew_own(runtime))[1])
        self.assertTrue(runtime.recovery_requested.is_set())
        self.assertEqual(runtime.own_order_renewal['retries'], 0)
        failed = [c for n, c in events if n == 'account_refresh_failed']
        self.assertEqual(failed[-1]['outcome'], 'audit_blocked')

    async def test_economic_event_ends_chain_reuse(self):
        runtime = await self.runtime()
        self.assertIsNotNone(runtime._chain_anchor())
        runtime._revoke()  # e.g. a fill, position update or reconnect
        self.assertIsNone(runtime._chain_anchor())
        self.assertIsNone(runtime._current_own_order_anchor())
        self.assertFalse(runtime.own_order_acknowledged())

    async def test_release_itself_rejects_receipts_older_than_the_floor(self):
        runtime = await self.runtime()
        proof = runtime._chain_anchor()
        runtime._revoke()  # Economic: the floor moves past every chain receipt.
        runtime._last_proof = (proof, runtime.account.history_floor)  # Bypass the gate.
        self.advance(1)
        self.assertFalse(await runtime._refresh_routine_account(anchor=proof))
        self.assertIn('accounting_history_receipt_invalid', runtime.accounting_result.blockers)
        self.assertIsNone(runtime._last_proof)
        self.assertTrue(runtime.recovery_requested.is_set())

    # ---- item 4: full recovery continues the chain instead of the boundary ----

    async def test_non_economic_full_recovery_enumerates_after_chain_only(self):
        runtime = await self.runtime()
        chain = runtime._chain_anchor()
        await self.place_own_order(runtime)
        requests = []
        original = runtime.reads.collect
        async def record(name, **kwargs):
            if name in {'fills', 'historical_fills'}:
                requests.append((name, kwargs.get('min_ts')))
            return await original(name, **kwargs)
        runtime.reads.collect = record
        runtime.request_recovery('snapshot_freshness')
        runtime.recovery_requested.clear()
        self.advance(1)
        self.assertTrue(await runtime.recover_once())
        self.assertEqual(runtime.chained_recoveries, 1)
        self.assertTrue(all(min_ts >= chain.end_us//1_000_000-1 for _, min_ts in requests))
        self.assertEqual(runtime._routine_account_proof.receipt_ids[:len(chain.receipt_ids)],
                         chain.receipt_ids)

    async def test_failed_chained_pass_restarts_from_boundary(self):
        runtime = await self.runtime()
        runtime.request_recovery('snapshot_freshness')
        runtime.recovery_requested.clear()
        self.advance(1)
        with patch.object(runtime.account, 'recover_history', return_value=None):
            self.assertFalse(await runtime.recover_once())
        self.assertIsNone(runtime._chain_anchor())
        self.assertTrue(await runtime.recover_once())
        self.assertEqual(runtime.chained_recoveries, 0)

    async def test_economic_recovery_reproves_from_boundary(self):
        runtime = await self.runtime()
        runtime._revoke()
        runtime.request_recovery('private_fill_pending')
        runtime.recovery_requested.clear()
        self.advance(1)
        self.assertTrue(await runtime.recover_once())
        self.assertEqual(runtime.chained_recoveries, 0)


class HistoryFloorTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch
    refresh = baseline.AccountReleaseTests.refresh
    reserve = baseline.AccountReleaseTests.reserve
    runtime = routine.RoutineRefreshTests.runtime

    async def order_event(self, order_id, client):
        return dict(type='user_order', msg=dict(resting_row(order_id, client),
            subaccount_number=0))

    async def test_owned_settled_order_update_keeps_floor(self):
        await self.runtime()  # A current proven account can reserve an entry.
        account = self.account
        req = dict(baseline.request('own'), price='0.01')
        reserved = await self.reserve('own', req=req)
        self.assertTrue(reserved.reserved, reserved.blockers)
        await self.writer.begin_send(reserved.receipt)
        await self.writer.record_outcome('ack', reserved.receipt, dict(order_id='o-own',
            client_order_id='own', fill_count='0', remaining_count='10', ts_ms=1), self.now)
        floor, revision = account.history_floor, account.revision
        await account.on_event(await self.order_event('o-own', 'own'),
                               generation=account.generation, received_at=self.now)
        self.assertEqual(account.revision, revision+1)
        self.assertEqual(account.history_floor, floor)

    async def test_foreign_order_update_moves_floor(self):
        account = self.account
        await account.on_event(await self.order_event('o-foreign', 'someone'),
                               generation=account.generation, received_at=self.now)
        self.assertEqual(account.history_floor, account.revision)

    async def test_position_event_and_reconnect_move_floor(self):
        account = self.account
        event = dict(type='market_position', msg=dict(market_ticker='A', position_fp='0',
            position_cost_dollars='0', subaccount=0))
        await account.on_event(event, generation=account.generation, received_at=self.now)
        self.assertEqual(account.history_floor, account.revision)
        account._invalidate(economic=False)
        self.assertLess(account.history_floor, account.revision)
        account.connect_generation()
        self.assertEqual(account.history_floor, account.revision)


class AcknowledgementClassificationTests(unittest.TestCase):
    def source(self, anchor=True):
        calls = []
        runtime = SimpleNamespace(
            entry_pause_active=False, maintenance=None, dispatch_supervisor=None,
            _revoke=lambda economic=True: calls.append(('revoke', economic)),
            own_order_acknowledged=lambda: anchor,
            request_recovery=lambda reason='source_change': calls.append(('recover', reason)),
            diagnostics=SimpleNamespace(emit=lambda *a, **k: None, ensure_healthy=lambda: None))
        source = SimpleNamespace(runtime=runtime, _proof=None, _generation=0,
            _transport_invoked=False, _risk_cancel_notice=None, _paused_cancel_notice=None,
            _executor=None, _rebase_requested=False, _own_ack=None)
        observed = lambda notice=None: InventoryDispatchSource._mutation_observed(source, notice)
        return observed, calls

    def notice(self, outcome='ack', status=None):
        return MutationNotice('create', 'A', 'c', 0, 1, outcome, status)

    def test_acknowledged_command_renews_instead_of_recovering(self):
        observed, calls = self.source()
        observed(self.notice())
        observed()
        self.assertEqual(calls, [('revoke', False), ('revoke', False)])

    def test_batch_with_one_failed_leg_recovers(self):
        for order in (('ack', 'uncertain'), ('uncertain', 'ack')):
            with self.subTest(order=order):
                observed, calls = self.source()
                for outcome in order:
                    observed(self.notice(outcome))
                observed()
                self.assertEqual(calls[-2:], [('revoke', True), ('recover', 'mutation_persisted')])

    def test_rejection_or_missing_anchor_recovers(self):
        for notice, anchor in ((self.notice('rejected', 400), True), (self.notice(), False)):
            with self.subTest(outcome=notice.outcome, anchor=anchor):
                observed, calls = self.source(anchor)
                observed(notice)
                self.assertEqual(calls[-1][0], 'recover')


if __name__ == '__main__':
    unittest.main()
