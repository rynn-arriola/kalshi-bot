"""Credential-free real-owner lifecycle regressions for D-098."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import unittest
from test_bot_reward_tracker import QueueReads

from kalshi_bot.config import BotConfig
from kalshi_bot.dispatch import QUOTE_CANCEL, ENTRY_PAIR, SAFETY_CANCEL, DUE_IOC, PASSIVE_REDUCER
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.quote_maintenance import MaintenanceCycle, QuoteMaintenance
from kalshi_bot.selection import MarketSelector
import test_bot_dispatch_sources as dispatch_fixtures
from test_bot_inventory_risk import request
from test_bot_engine import program, NOW, book
from test_bot_selection import terms, view, window


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = dispatch_fixtures.DispatchSourceTests()
        await self.f.asyncSetUp()
        self.r = self.f.runtime
        self.s = self.r.attach_selection(offline_fixture=True)
        self.rewards = self.r.attach_rewards(scope='fixture', offline_fixture=True)
        self.m = self.r.attach_maintenance()
        self.p = program(pool_centicents=5000000)
        self.s.set_programs('A', (self.p,), observed_at=NOW,
                            valid_until=NOW+timedelta(minutes=30))
        self.m.bind(self.p)
        bid = await self.f.ready(filled='0', remaining='10')
        req = request('ask-open', side='ask') | {'price': '.6'}
        prepared = await self.f.writer.reserve_entry(req, attempt_id='ask-attempt',
            view=await self.r.risk_view(), config=BotConfig(), now=self.f.now,
            free_cash=D(500), account_known=True, offline_fixture=True)
        self.assertTrue(prepared.reserved, prepared.blockers)
        await self.f.writer.begin_send(prepared.receipt)
        await self.f.writer.record_outcome('ack', prepared.receipt,
            dict(order_id='ask-order', fill_count='0', remaining_count='10', ts_ms=1), self.f.now)
        ask = OrderUpdate('ask-order', 'ask-open', 'A', 'ask', D('.6'), D(10), D(0), D(10),
                          'resting', 0, 0, 1)
        await self.f.writer.order(ask, self.f.now)
        self.orders = [bid, ask]
        market = SimpleNamespace(value=SimpleNamespace(exchange=0))
        self.r.market_inputs = SimpleNamespace(values={('market','A'):market},
            results={'A':SimpleNamespace(terms=self.r.management.terms['A'])},
            _fresh=lambda value: value is market)
        await self.sample(0)

    async def asyncTearDown(self):
        await self.f.asyncTearDown()

    async def sample(self, seconds=2, *, drift=False, reflection=True, quantity='0', shallow=False):
        self.f.now += timedelta(seconds=seconds)
        self.f.mono += seconds
        await self.f.books()
        _, b = self.r.management._book('A')
        b.bids.set(D('.5'), D(10))
        if drift:
            b.bids.set(D('.54'), D(1000))
        if shallow:
            b.asks.set(D('.6'), D(10))
        state = await self.f.writer.observe(self.f.now)
        self.r.accounting_result = SimpleNamespace(released=True, window=state)
        for receipt in await self.f.writer.orders():
            self.r.account._store_order(receipt)
        await self.f.report(quantity, tuple(o for o in self.orders if not o.terminal))
        await self.r.management.refresh('A')
        self.s.refresh('A')
        if reflection:
            self.rewards.confirm_reflection_fixture('A', offline_fixture=True)
        else:
            self.rewards.invalidate('A')
        self.rewards.refresh('A')
        self.m.refresh('A')

    async def drift(self):
        for _ in range(17):
            await self.sample(drift=True)
        self.assertIsNotNone(self.m.cycle, self.m.status())

    async def test_full_weight_better_reference_pair_retained_after_estimated_dollar(self):
        self.rewards.tracker.records['P'].estimate = D(2)
        for _ in range(18):
            await self.sample()
        self.assertIsNone(self.m.cycle)
        self.assertEqual(self.m.samples['A']['quote_statuses'],
                         ('full_price_weight', 'full_price_weight'))
        self.assertEqual(await self.f.source.refresh('A', QUOTE_CANCEL), None)

    async def test_unknown_and_short_drift_do_not_cancel(self):
        for _ in range(10):
            await self.sample(drift=True)
        self.assertIsNone(self.m.cycle)
        await self.sample(10, drift=True, reflection=False)
        self.assertIsNone(self.m.cycle)
        for _ in range(3):
            await self.sample(drift=True)
        self.assertIsNone(self.m.cycle)
        await self.sample()
        self.assertNotIn('A', self.m._dwell)

    async def test_live_cadence_gaps_accumulate_only_verified_coverage(self):
        # Each six-second cadence has five seconds of explicit source validity.
        # The one-second unknown portion is not counted, but does not erase the
        # prior verified evidence as the old five-second reset did.
        for _ in range(6):
            await self.sample(6, drift=True)
        self.assertIsNone(self.m.cycle)
        self.assertEqual(self.m._dwell['A'].verified_seconds, 25)
        await self.sample(6, drift=True)
        self.assertIsNotNone(self.m.cycle)
        self.assertEqual(self.m.cycle.reason, 'restore_reference_pair')

    async def test_long_evidence_gap_resets_verified_coverage(self):
        for _ in range(5):
            await self.sample(6, drift=True)
        self.assertEqual(self.m._dwell['A'].verified_seconds, 20)
        await self.sample(16, drift=True)
        self.assertIsNone(self.m.cycle)
        self.assertEqual(self.m._dwell['A'].verified_seconds, 0)

    async def test_stale_cycle_cannot_authorize_cancel_send(self):
        await self.drift()
        plan = self.r.management.current('A')
        self.m.cycle = replace(self.m.cycle,
            evidence_valid_until=self.f.now+timedelta(seconds=1))
        candidate = await self.f.source.refresh('A', QUOTE_CANCEL)
        self.assertIsNotNone(candidate)
        self.f.now += timedelta(seconds=2)
        self.f.mono += 2
        self.assertFalse(self.f.source.validate_proof('cancel', candidate.request))
        self.assertIsNone(self.m.cancel_target(plan))

    async def test_terminal_original_leg_keeps_remaining_cycle_identity(self):
        await self.drift()
        plan = self.r.management.current('A')
        one = replace(plan, inventory=replace(plan.inventory,
            orders=plan.inventory.orders[:1]))
        self.assertTrue(self.m._cycle_current(one, self.m.cycle))
        changed = replace(one.inventory.orders[0], order=replace(
            one.inventory.orders[0].order, remaining=D(9)))
        changed_plan = replace(plan, inventory=replace(plan.inventory,
            orders=(changed,)))
        self.assertFalse(self.m._cycle_current(changed_plan, self.m.cycle))

    async def test_expired_cycle_rearms_only_from_fresh_drift(self):
        await self.drift()
        old = self.m.cycle
        await self.sample(6, drift=True)
        self.assertIsNotNone(self.m.cycle)
        self.assertIsNot(self.m.cycle, old)
        self.assertGreater(self.m.cycle.evidence_valid_until, self.f.now)

    async def test_drift_restricts_same_market_program_not_unrelated_entries(self):
        await self.drift()
        self.assertTrue(self.m.cycle.reenter)
        self.assertTrue(self.m.entry_allowed('A', 'P'))
        self.assertTrue(self.m.entry_allowed('B', 'P'))
        self.assertFalse(self.m.entry_allowed('A', 'OTHER'))
        candidate = await self.f.source.refresh('A', QUOTE_CANCEL)
        self.assertIn(candidate.request['order_id'], self.m.cycle.order_ids)
        self.assertIsNone(await self.f.source.refresh('A', ENTRY_PAIR))

    async def test_cancel_ack_never_authorizes_replacement_or_second_cancel(self):
        await self.drift()
        self.assertEqual((await self.f.run_priority(QUOTE_CANCEL)).state, 'ACK')
        await self.sample(drift=True)
        self.assertIsNone(await self.f.source.refresh('A', ENTRY_PAIR))
        self.assertIsNone(await self.f.source.refresh('A', QUOTE_CANCEL))

    async def test_confirmed_terminal_pair_gets_fresh_reference_reentry(self):
        await self.drift()
        # Positive terminal/no-fill evidence, never inference from absence.
        for old in self.orders:
            await self.f.writer.order(replace(old, remaining=D(0), status='canceled', version_us=2), self.f.now)
        self.orders = []
        await self.sample(drift=True)
        candidate = await self.f.source.refresh('A', ENTRY_PAIR)
        self.assertIsNotNone(candidate, self.f.source.last_entry_block)
        self.assertEqual({(v['side'], D(v['price'])) for v in candidate.requests},
                         {('bid', D('.54')), ('ask', D('.6'))})
        self.assertTrue(all(D(v['count']) == 10 and v['post_only'] for v in candidate.requests))

    async def test_terminal_first_leg_after_lease_expiry_completes_reprice(self):
        await self.drift()
        first = await self.f.run_priority(QUOTE_CANCEL)
        self.assertEqual(first.state, 'ACK')
        canceled = self.f.calls[-1][1]['order_id']
        old = next(o for o in self.orders if o.order_id == canceled)
        await self.f.writer.order(replace(old, remaining=D(0), status='canceled', version_us=2), self.f.now)
        self.orders.remove(old)
        await self.sample(6, drift=True)
        self.assertIsNotNone(self.m.cycle)
        second = await self.f.run_priority(QUOTE_CANCEL)
        self.assertEqual(second.state, 'ACK')
        old = self.orders.pop()
        self.assertEqual(self.f.calls[-1][1]['order_id'],old.order_id)
        await self.f.writer.order(replace(old, remaining=D(0), status='canceled', version_us=2), self.f.now)
        await self.sample(6, drift=True)
        candidate = await self.f.source.refresh('A', ENTRY_PAIR)
        self.assertIsNotNone(candidate, self.f.source.last_entry_block)

    async def test_real_queue_proof_reprices_across_recovery_plan_gaps(self):
        # No test-only reflection injection: reproduce recovery publishing its
        # queue join before dirty-market management catches up.
        for _ in range(9):
            await self.sample(6, drift=True, reflection=False)
            self.r.management.invalidate('A')
            self.r.reads = QueueReads([dict(order_id=o.order_id,
                market_ticker='A',queue_position_fp='0') for o in self.orders])
            self.assertEqual(await self.rewards.reflect_once(),1)
            await self.r._evaluate('A',None,0)
        self.assertIsNotNone(self.m.cycle,self.m.status())
        self.assertEqual(self.m.cycle.reason,'restore_reference_pair')
        self.assertIsNotNone(await self.f.source.refresh('A',QUOTE_CANCEL))

    async def test_partial_fill_hands_back_to_inventory_and_no_new_pair(self):
        from kalshi_bot.ledger import Fill
        await self.drift()
        bid = self.orders[0]
        filled = replace(bid, filled=D(4), remaining=D(6), version_us=2)
        await self.f.writer.order(filled, self.f.now)
        await self.f.writer.fill(Fill('race-fill', bid.order_id, 'A', 'bid', D(4), D('.5'), D(0)), self.f.now)
        self.orders[0] = filled
        await self.sample(drift=True, quantity='4')
        self.assertIsNone(self.m.cycle)
        self.assertIsNone(await self.f.source.refresh('A', QUOTE_CANCEL))
        self.assertIsNone(await self.f.source.refresh('A', ENTRY_PAIR))
        candidate = await self.f.source.refresh('A', SAFETY_CANCEL)
        self.assertEqual(candidate.request['order_id'], bid.order_id)

    async def test_cycle_invalidated_between_cancel_prepare_and_send(self):
        await self.drift()
        candidate = await self.f.source.refresh('A', QUOTE_CANCEL)
        prepared = await self.f.writer.prepare_cancel(attempt_id=candidate.attempt_id,
            request=candidate.request, evidence=candidate.evidence, now=self.f.now)
        self.assertTrue(self.f.source.validate_proof('cancel', candidate.request))
        # Preserve every other source object and expire only the maintenance
        # lease. The synchronous send fence must check this exact lease rather
        # than relying on broader plan freshness to fail coincidentally.
        object.__setattr__(self.m.cycle, 'evidence_valid_until',
                           self.f.now-timedelta(microseconds=1))
        self.assertFalse(self.f.source.validate_proof('cancel', candidate.request))
        await self.f.writer.abort_prepared(prepared.receipt)

    async def test_ended_program_withdraws_without_reward_chasing(self):
        ended = replace(self.p, end=self.f.now)
        self.m.bind(ended)
        self.m.refresh('A')
        self.assertFalse(self.m.cycle.reenter)
        self.assertEqual(self.m.cycle.reason, 'earning_window_ended')

    async def test_changed_program_terms_cannot_spend_old_estimate(self):
        await self.drift()
        self.rewards.tracker.records['P'].estimate = D(2)
        self.s.set_programs('A', (replace(self.p, pool_centicents=10000),),
            observed_at=self.f.now, valid_until=self.f.now+timedelta(minutes=5))
        self.assertFalse(self.m.entry_allowed('A', 'P'))

    async def test_progress_exposes_estimates_not_paid_cash(self):
        rows = self.rewards.status()['program_progress']
        self.assertEqual(rows[0]['program_id'], 'P')
        self.assertIsNone(rows[0]['paid_usd'])
        self.assertFalse(rows[0]['payout_confirmed'])
        self.assertIn('seconds_to_minimum', rows[0])
        self.assertIn('unknown_seconds', rows[0])

    async def test_lower_cap_actively_cancels_only_overflow(self):
        self.r.accounting_result.window = replace(self.r.accounting_result.window, cap=1)
        ids = self.r.entry_overflow_ids()
        self.assertEqual(len(ids), 1)
        candidate = await self.f.source.refresh('A', SAFETY_CANCEL)
        self.assertIn(candidate.request['order_id'], ids)
        self.assertIsNone(self.m.cycle)

    async def test_cap_change_during_cycle_releases_flat_capacity_without_reentry(self):
        await self.drift()
        for old in self.orders:
            await self.f.writer.order(replace(old, remaining=D(0), status='canceled', version_us=2), self.f.now)
        self.orders = []
        await self.sample(drift=True)
        self.r.accounting_result.window = replace(self.r.accounting_result.window, cap=1)
        self.m.refresh('A')
        self.assertIsNone(self.m.cycle)
        self.assertIsNone(await self.f.source.refresh('A', ENTRY_PAIR))

    async def test_missing_order_join_never_guesses_overflow_ownership(self):
        self.r.accounting_result.window = replace(self.r.accounting_result.window, cap=1)
        self.r.account.order_states.clear()
        self.assertIsNone(self.r.current_entry_orders())
        self.assertFalse(self.r.entry_overflow_ids())

    async def test_overflow_policy_keeps_whole_pair_before_higher_ranked_orphan(self):
        # Pure allocation fixture; no dispatch/ledger claim for these added rows.
        report = self.r.account.report
        original = report.snapshot.orders
        a = next(o for o in original if o.book_side == 'bid')
        b = tuple(replace(o, order_id='B-'+o.order_id, ticker='B') for o in original)
        for row in b:
            receipt = self.r.account.order_states[row.order_id[2:]]
            self.r.account._store_order(replace(receipt, order=replace(receipt.order,
                order_id=row.order_id, ticker='B')))
        self.r.account.report = replace(report, snapshot=replace(report.snapshot, orders=(a,)+b))
        self.r.accounting_result.window = replace(self.r.accounting_result.window, cap=2)
        self.assertEqual(self.r.entry_overflow_ids(), frozenset((a.order_id,)))

    async def test_inventory_reducer_is_not_an_overflow_entry(self):
        # Flags are immutable owned intent evidence, never inferred from side.
        receipt = self.r.account.order_states['ask-order']
        self.r.account._store_order(replace(receipt, reducing=True))
        self.r.accounting_result.window = replace(self.r.accounting_result.window, cap=1)
        self.assertEqual(len(self.r.current_entry_orders()), 1)
        self.assertFalse(self.r.entry_overflow_ids())

    async def test_unknown_reward_terms_never_mean_persistently_unprofitable(self):
        self.r.management.set_terms(replace(self.r.management.terms['A'],
            taker_fee_per_contract_bound=None))
        for _ in range(50):
            await self.sample(drift=True)
        self.assertIsNone(self.m.cycle)
        self.assertEqual(self.m.samples['A']['state'], 'UNKNOWN')

    async def test_qualifying_observation_resets_lost_depth_dwell(self):
        for _ in range(47):
            await self.sample()
            _, b = self.r.management._book('A')
            b.asks.set(D('.6'), D(10))
            # Keep the same current source; the failed cutoff is definite.
            self.m.refresh('A')
        # The alternating qualifying observations deliberately reset the timer.
        self.assertIsNone(self.m.cycle)

    async def test_persistent_known_lost_depth_withdraws_after_dwell(self):
        for _ in range(47):
            await self.sample(shallow=True)
        self.assertIsNotNone(self.m.cycle)
        self.assertFalse(self.m.cycle.reenter)
        self.assertEqual(self.m.cycle.reason, 'persistently_unscoring')

    async def test_incomplete_qualifying_pair_restores_after_reprice_dwell(self):
        removed = self.orders.pop()
        await self.f.writer.order(replace(removed, remaining=D(0), status='canceled',
                                          version_us=2), self.f.now)
        for _ in range(17):
            await self.sample()
        self.assertIsNotNone(self.m.cycle, self.m.status())
        self.assertTrue(self.m.cycle.reenter)
        self.assertEqual(self.m.cycle.reason, 'restore_reference_pair')

    async def test_incomplete_pair_below_minimum_withdraws_orphan_after_dwell(self):
        low = replace(self.p, pool_centicents=1000000)
        self.s.set_programs('A', (low,), observed_at=self.f.now,
                            valid_until=self.f.now+timedelta(minutes=30))
        self.m.bind(low)
        orphan = self.orders[0]
        removed = self.orders.pop()
        await self.f.writer.order(replace(removed, remaining=D(0), status='canceled',
                                          version_us=2), self.f.now)
        for _ in range(47):
            await self.sample()
        self.assertIsNotNone(self.m.cycle, self.m.status())
        self.assertFalse(self.m.cycle.reenter)
        self.assertEqual(self.m.cycle.reason, 'incomplete_pair_below_minimum')
        candidate = await self.f.source.refresh('A', QUOTE_CANCEL)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.request['order_id'], orphan.order_id)

    async def test_dispatch_prioritizes_existing_exits_over_quote_maintenance(self):
        await self.drift()
        d = self.f.dispatcher
        d.submit('A', QUOTE_CANCEL)
        d.submit('B', PASSIVE_REDUCER)
        self.assertEqual(d.status().queued[0], (PASSIVE_REDUCER, 'B'))
        d.submit('A', SAFETY_CANCEL)
        self.assertEqual(d.status().queued[0], (SAFETY_CANCEL, 'A'))


class ContinuationTests(unittest.TestCase):
    def test_stalled_market_allows_twenty_to_thirty_without_reserved_slots(self):
        # Unknown/changed A proof must not be consulted for other markets.
        def unavailable(_):
            raise AssertionError('unrelated entry read stalled market proof')
        owner = QuoteMaintenance(SimpleNamespace(selection=SimpleNamespace(
            _observation=unavailable)))
        owner.cycle = MaintenanceCycle('A', program(), (), 'restore_reference_pair', True)
        selector = MarketSelector()
        for ticker in ('B', 'C', 'D', 'E', 'F', 'G'):
            selector.update(replace(book(), ticker=ticker),
                (program(ticker=ticker, pool_centicents=5000000),),
                terms=terms(ticker), now=NOW, valid_until=NOW+timedelta(seconds=4))
        args = dict(view=view(entry_count=20, exposure=(('EXISTING', D(180)),)),
            window=window(), free_cash=D(320), account_known=True,
            now=NOW, current=lambda t: True, entry_allowed=owner.entry_allowed)
        result = selector.propose(**args)
        self.assertEqual(len(result.additions), 5)
        self.assertEqual(20+2*len(result.additions), 30)
        self.assertTrue(all(row.ticker != 'A' for row in result.additions))
        self.assertIn('entry_cap', dict(result.exclusions)['G'])
        # Ratcheted limits still apply; a single free slot is not a pair.
        for cap, pairs in ((21, 0), (24, 2), (30, 5)):
            with self.subTest(cap=cap):
                self.assertEqual(len(selector.propose(
                    **(args | {'window': window(cap=cap)})).additions), pairs)
        for overrides in ({'window': window(held=True)}, {'account_known': False},
                          {'free_cash': D(0)}, {'current': lambda t: False}):
            with self.subTest(gate=overrides):
                self.assertFalse(selector.propose(**(args | overrides)).additions)

    def test_withdrawal_and_unknown_same_market_proof_remain_local(self):
        owner = QuoteMaintenance(SimpleNamespace(selection=SimpleNamespace(
            _observation=lambda _: None)))
        for reenter in (True, False):
            owner.cycle = MaintenanceCycle('A', program(), (), 'withdraw', reenter)
            self.assertTrue(owner.entry_allowed('B', 'P'))
            self.assertFalse(owner.entry_allowed('A', 'P'))
            self.assertFalse(owner.entry_allowed('A', 'OTHER'))

    def test_earned_credit_is_only_for_same_program_and_never_bypasses_risk(self):
        s = MarketSelector()
        p = program(pool_centicents=100000)
        s.update(book(), (p,), terms=terms(), now=NOW, valid_until=NOW+timedelta(seconds=4))
        args = dict(view=view(), window=window(), free_cash=D(500), account_known=True,
                    now=NOW, current=lambda t: True)
        self.assertFalse(s.propose(**args).additions)
        self.assertFalse(s.propose(**args, continuations={'A':('OTHER',D(2))}).additions)
        self.assertTrue(s.propose(**args, continuations={'A':('P',D(2))}).additions)
        self.assertFalse(s.propose(**(args | {'window':window(held=True)}),
                                  continuations={'A':('P',D(2))}).additions)

    def test_own_opposite_order_never_counts_as_exit_depth(self):
        from kalshi_bot.quoting import Quote
        s = MarketSelector()
        p = program(target=D(200))
        b = book(bids=(('.5','10'),('.1','200')), asks=(('.6','10'),('.9','200')))
        qs = (Quote('bid',D('.5'),D(10)), Quote('ask',D('.6'),D(10)))
        s.update(b, (p,), terms=terms(), now=NOW, valid_until=NOW+timedelta(seconds=4),
                 reflected=qs, proposed=qs)
        self.assertIn('entry_retained_value_below_minimum', s.board.markets['A'][0].blockers)
