"""D-032 offline price/depth/deadline, lifecycle and runtime regressions."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.adapters import PriceBand
from kalshi_bot.books import Book, Ladder
from kalshi_bot.exits import ExitTerms, ExitJournal, adjacent_tick, plan_exit, ioc_payload
from kalshi_bot.execution import validate_request
from kalshi_bot.orders import OrderReceipt, OrderUpdate
from kalshi_bot.ledger import Ledger, Fill
from kalshi_bot.portfolio import market_inventory
from kalshi_bot.values import InvalidData
from test_bot_engine import NOW
import test_bot_inventory_risk as management_fixtures

BANDS=(PriceBand(D(0),D(1),D('.01')),)

def book(bids=(('.4','40'),), asks=(('.6','40'),)):
    b=Book('A',Ladder(4096),Ladder(4096),True)
    for rows, ladder in ((bids,b.bids),(asks,b.asks)):
        for p,q in rows: ladder.set(D(p),D(q))
    return b

def terms(**kwargs):
    return replace(ExitTerms('A',BANDS,NOW,NOW+timedelta(hours=1),NOW+timedelta(hours=2),
        event_risk_at=NOW+timedelta(hours=1),taker_fee_per_contract_bound=D('.02')),**kwargs)

def receipt(key='r',side='ask',p='.6',qty='10',reducing=True,waiting=False,owned=True,terminal=False):
    o=OrderUpdate(key,key,'A',side,D(p),D(qty),D(0),D(0) if terminal else D(qty),
                  'canceled' if terminal else 'resting',0,0,1)
    return OrderReceipt(o,owned,True,waiting,'TERMINAL' if terminal else 'ACKNOWLEDGED',reducing)

class ExitTests(unittest.TestCase):
    def plan(self,**kw):
        defaults=dict(ticker='A',position=D(10),basis=D('.5'),first_seen_at=NOW,
            orders=(),book=book(),terms=terms(),journal=ExitJournal(),now=NOW,complete_scope=True)
        return plan_exit(**(defaults|kw))

    def due(self,**kw): return self.plan(**({'first_seen_at':NOW-timedelta(seconds=900)}|kw))

    def test_profitable_long_steps_one_tick(self):
        p=self.plan(); self.assertEqual((p.mode,p.limit_price,p.passive.reduce_quantity),('passive',D('.59'),10))

    def test_profitable_no_position_steps_bid(self):
        p=self.plan(position=D(-10)); self.assertEqual(p.limit_price,D('.41'))

    def test_losing_long_has_no_basis_floor(self):
        p=self.plan(basis=D('.8')); self.assertEqual(p.limit_price,D('.6'))

    def test_losing_no_position_has_no_basis_floor(self):
        self.assertEqual(self.plan(position=D(-10),basis=D('.2')).limit_price,D('.4'))

    def test_never_crosses_opposite_touch(self):
        self.assertEqual(self.plan(book=book(asks=(('.41','40'),)),basis=D('.2')).limit_price,D('.41'))

    def test_one_sided_passive_does_not_improve(self):
        self.assertEqual(self.plan(book=book(bids=())).limit_price,D('.6'))

    def test_exact_touch_reducer_is_kept_not_repriced_against_self(self):
        p=self.plan(orders=(receipt(),)); self.assertEqual(p.passive.keep_id,'r')
        self.assertIsNone(p.passive.reduce_side)

    def test_exact_improved_reducer_is_kept(self):
        self.assertEqual(self.plan(orders=(receipt(p='.59'),)).passive.keep_id,'r')

    def test_partial_fill_quantity_requires_confirmed_replacement(self):
        p=self.plan(position=D(4),orders=(receipt(),))
        self.assertEqual(p.passive.cancel_ids,('r',)); self.assertIsNone(p.passive.reduce_side)

    def test_tick_band_boundary_steps_to_valid_neighbor(self):
        bands=(PriceBand(D(0),D('.5'),D('.01')),PriceBand(D('.5'),D(1),D('.005')))
        self.assertEqual(adjacent_tick(D('.5'),'ask',bands),D('.49'))
        self.assertEqual(adjacent_tick(D('.5'),'bid',bands),D('.505'))

    def test_no_early_ioc_before_900(self):
        self.assertEqual(self.plan(first_seen_at=NOW-timedelta(seconds=899)).mode,'passive')

    def test_ordinary_exact_quantity_capped_ioc(self):
        p=self.due(); self.assertEqual((p.mode,p.limit_price,p.quantity),('ioc',D('.4'),10))
        self.assertEqual(p.projected_pnl,D('-1.2')); self.assertFalse(p.authorized)

    def test_ordinary_depth_haircut_defers_preserving_reducer(self):
        p=self.due(book=book(bids=(('.4','10'),)),orders=(receipt(),))
        self.assertEqual(p.mode,'passive_deferred'); self.assertEqual(p.passive.keep_id,'r')

    def test_ordinary_loss_limit_defers_at_worse_than_eight(self):
        p=self.due(basis=D('.99'),book=book(bids=(('.1','40'),),asks=(('.11','40'),)))
        self.assertEqual(p.mode,'passive_deferred')

    def test_fee_bound_participates_in_loss_limit(self):
        p=self.due(basis=D('.9'),book=book(bids=(('.11','40'),)),terms=terms(taker_fee_per_contract_bound=D('.02')))
        self.assertEqual(p.mode,'passive_deferred')

    def test_forced_exit_uses_full_depth_and_overrides_ordinary_loss_cap(self):
        p=self.plan(basis=D('.99'),book=book(bids=(('.1','10'),)),terms=terms(flatten_at=NOW))
        self.assertEqual(p.mode,'ioc'); self.assertLess(p.projected_pnl,-8)

    def test_forced_insufficient_depth_requires_attention(self):
        p=self.plan(book=book(bids=(('.4','9'),)),terms=terms(flatten_at=NOW))
        self.assertEqual(p.mode,'attention'); self.assertIsNone(p.limit_price)

    def test_ioc_works_without_passive_side(self):
        self.assertEqual(self.due(book=book(asks=())).mode,'ioc')

    def test_building_order_cancel_selected_before_reducer(self):
        p=self.due(orders=(receipt('a'),receipt('z',side='bid',reducing=False)))
        self.assertEqual((p.mode,p.passive.cancel_ids),('cancel_before_ioc',('z',)))
        self.assertEqual(p.quantity,0)

    def test_cancel_ack_and_snapshot_absence_not_terminal_proof(self):
        p=self.due(journal=ExitJournal(cancel_ids=('gone',),cancel_started_at=NOW))
        self.assertEqual(p.mode,'wait'); self.assertNotEqual(p.mode,'ioc')

    def test_cancel_timeout_attention(self):
        p=self.due(journal=ExitJournal(cancel_ids=('r',),cancel_started_at=NOW-timedelta(seconds=6)))
        self.assertEqual(p.mode,'attention')

    def test_terminal_unaccounted_fills_block_ioc(self):
        p=self.due(orders=(receipt(terminal=True,waiting=True),))
        self.assertEqual(p.mode,'blocked')

    def test_foreign_order_blocks_ioc(self):
        self.assertEqual(self.due(orders=(receipt(owned=False),)).mode,'blocked')

    def test_pending_ioc_never_blindly_retried(self):
        self.assertEqual(self.due(journal=ExitJournal(1,NOW,True)).mode,'wait')
        self.assertEqual(self.due(journal=ExitJournal(1,NOW-timedelta(seconds=11),True)).mode,'attention')

    def test_pending_ioc_timer_survives_incomplete_reconciliation(self):
        p=self.due(complete_scope=False,journal=ExitJournal(1,NOW,True))
        self.assertEqual((p.mode,p.next_at),('wait',NOW+timedelta(seconds=10)))

    def test_pending_cancel_timer_survives_missing_book_and_scope(self):
        p=self.due(book=None,complete_scope=False,journal=ExitJournal(cancel_ids=('r',),cancel_started_at=NOW))
        self.assertEqual(p.mode,'wait'); self.assertIsNotNone(p.next_at)

    def test_attempt_and_time_budgets(self):
        for j in (ExitJournal(3,NOW),ExitJournal(1,NOW-timedelta(seconds=30))):
            self.assertEqual(self.due(journal=j).mode,'attention')

    def test_unknown_fee_or_event_time_blocks(self):
        for t in (terms(taker_fee_per_contract_bound=None),terms(event_risk_at=None)):
            self.assertEqual(self.due(terms=t).mode,'blocked')

    def test_known_event_time_minus_five_minutes(self):
        p=self.plan(terms=terms(event_risk_at=NOW+timedelta(minutes=5)))
        self.assertEqual(p.mode,'ioc')

    def test_closed_inactive_market_does_not_claim_flat(self):
        for t in (terms(close_at=NOW),terms(active=False)):
            self.assertEqual(self.due(terms=t).mode,'attention')

    def test_missing_stale_wrong_scope_terms(self):
        self.assertEqual(self.due(terms=None).mode,'blocked')
        self.assertEqual(self.due(terms=terms(observed_at=NOW-timedelta(seconds=1),valid_until=NOW),now=NOW).mode,'blocked')

    def test_missing_basis_clock_scope_book(self):
        for kw in ({'basis':None},{'first_seen_at':None},{'complete_scope':False},{'book':None},{'journal':None}):
            self.assertEqual(self.due(**kw).mode,'blocked')

    def test_grid_bounds_and_gaps_rejected(self):
        with self.assertRaises(InvalidData): terms(bands=())
        with self.assertRaises(InvalidData): terms(taker_fee_per_contract_bound=D('-1'))

    def test_no_short_residue_poly_exception_imported(self):
        self.assertEqual(self.plan(position=D('.01'),first_seen_at=NOW-timedelta(seconds=300)).mode,'passive')

    def test_payload_is_exact_reduce_only_ioc_without_expiry(self):
        for pos,side in ((D('3.25'),'ask'),(D('-3.25'),'bid')):
            p=ioc_payload(ticker='A',client_id='id',position=pos,limit_price=D('.4'),bands=BANDS)
            self.assertEqual((p['side'],p['count'],p['price']),(side,'3.25','0.4'))
            self.assertFalse(p['post_only']); self.assertTrue(p['reduce_only'])
            self.assertNotIn('expiration_time',p)
            validate_request('create',p|{'subaccount':0,'exchange_index':0})

    def test_invalid_ioc_combinations_rejected(self):
        p=ioc_payload(ticker='A',client_id='id',position=D(10),limit_price=D('.4'),bands=BANDS)|{'subaccount':0,'exchange_index':0}
        for change in ({'reduce_only':False},{'post_only':True},{'expiration_time':1800000000},{'time_in_force':'fill_or_kill'}):
            with self.assertRaises(InvalidData): validate_request('create',p|change)
        with self.assertRaises(InvalidData): ioc_payload(ticker='A',client_id='id',position=D(0),limit_price=D('.4'),bands=BANDS)


class IntegratedExitTests(management_fixtures.ManagementTests):
    # Inherit the existing management/race/reconnect tests as well as new cases.
    async def prepare_reducer(self, payload, *, attempt='attempt'):
        inventory = await self.writer.market_inventory('A', subaccount=0)
        await self.report(str(abs(inventory.position)))
        selected_terms = (terms(flatten_at=self.now)
                          if payload['time_in_force'] == 'immediate_or_cancel'
                          else terms())
        self.runtime.management.set_terms(selected_terms)
        plan = await self.runtime.management.refresh('A')
        self.assertIs(plan, self.runtime.management.current('A'))
        evidence = await self.writer.reduction_evidence(payload, now=self.now)
        prepared = await self.writer.prepare_reduction(
            attempt, payload, evidence=evidence, now=self.now)
        self.assertTrue(prepared.reserved, prepared.blockers)
        sent = await self.writer.begin_send(prepared.receipt)
        self.assertTrue(sent.dispatch_allowed, sent.blockers)
        return prepared.receipt

    async def test_terms_enable_improvement_and_revoke_on_change(self):
        await self.position(); await self.report()
        self.runtime.management.set_terms(terms())
        p=await self.runtime.management.refresh('A')
        self.assertEqual(p.exit.limit_price,D('.59'))
        self.runtime.management.revoke_terms('A')
        self.assertIsNone(self.runtime.management.current('A'))

    async def test_old_book_cannot_be_refreshed_into_fresh_exit(self):
        await self.position(); await self.report()
        self.runtime.management.set_terms(terms())
        self.now += timedelta(seconds=6); self.monotonic += 6
        await self.report()
        p=await self.runtime.management.refresh('A')
        self.assertIn('exit_book_unavailable',p.exit.blockers)

    async def test_terms_replacement_during_writer_await_revokes(self):
        await self.position(); await self.report()
        self.runtime.management.set_terms(terms())
        original=self.writer.market_inventory
        async def changed(*a,**kw):
            result=await original(*a,**kw)
            self.runtime.management.set_terms(terms(active=False))
            return result
        self.writer.market_inventory=changed
        self.assertIsNone(await self.runtime.management.refresh('A'))

    async def test_durable_ioc_attempt_survives_writer_restart(self):
        await self.position()
        p=ioc_payload(ticker='A',client_id='exit',position=D(10),limit_price=D('.4'),bands=BANDS)|{'subaccount':0,'exchange_index':0}
        receipt=await self.prepare_reducer(p)
        await self.writer.record_outcome('unknown',receipt,{},self.now)
        before=await self.writer.market_inventory('A',subaccount=0)
        self.assertEqual(before.exit_journal.attempts,1); self.assertTrue(before.exit_journal.unresolved_ioc)
        path=self.writer.path if hasattr(self.writer,'path') else Path(self.temp.name)/'manage.db'
        await self.writer.close()
        from kalshi_bot.writer import LedgerWriter
        self.writer=await LedgerWriter(path).start()
        after=await self.writer.market_inventory('A',subaccount=0)
        self.assertEqual(after.exit_journal,before.exit_journal)

    async def test_terminal_partial_ioc_replans_only_remaining_inventory(self):
        await self.position()
        self.runtime.management.set_terms(terms(flatten_at=NOW))
        p=ioc_payload(ticker='A',client_id='exit',position=D(10),limit_price=D('.4'),bands=BANDS)|{'subaccount':0,'exchange_index':0}
        await self.prepare_reducer(p)
        order=OrderUpdate('exit-order','exit','A','ask',D('.4'),D(10),D(4),D(0),'canceled',0,0,2)
        await self.writer.order(order,self.now)
        before=await self.writer.market_inventory('A',subaccount=0)
        self.assertTrue(before.exit_journal.unresolved_ioc)
        await self.writer.fill(Fill('exit-fill','exit-order','A','ask',D(4),D('.4'),D('.01')),self.now)
        await self.report('6')
        plan=await self.runtime.management.refresh('A')
        self.assertEqual((plan.exit.mode,plan.exit.quantity),('ioc',6))
        self.assertEqual(plan.inventory.exit_journal.attempts,1)
        self.assertFalse(plan.inventory.exit_journal.unresolved_ioc)
        self.assertFalse(plan.authorized)

    async def test_cancel_fill_race_recomputes_quantity_after_terminal_proof(self):
        await self.position()
        payload=management_fixtures.request('reduce',side='ask',p='.59',reduce=True,quantity='10')
        await self.prepare_reducer(payload,attempt='reduce-attempt')
        reducer=OrderUpdate('reduce','reduce','A','ask',D('.59'),D(10),D(0),D(10),'resting',0,0,1)
        await self.writer.order(reducer,self.now)
        self.runtime.account._store_order((await self.writer.orders())[-1])
        self.runtime.management.set_terms(terms(flatten_at=NOW))
        cancel=dict(order_id='reduce',market_ticker='A',subaccount=0,exchange_index=0)
        prepared=await self.writer.prepare_cancel('cancel',cancel,
            evidence=await self.writer.cancel_evidence('reduce'),now=self.now)
        self.assertTrue(prepared.reserved,prepared.blockers)
        sent=await self.writer.begin_send(prepared.receipt)
        self.assertTrue(sent.dispatch_allowed,sent.blockers)
        await self.writer.record_outcome('ack',prepared.receipt,
            dict(order_id='reduce',ts_ms=1,reduced_by='6'),self.now)
        await self.report(orders=(reducer,))
        waiting=await self.runtime.management.refresh('A')
        self.assertEqual(waiting.exit.mode,'wait')
        await self.writer.order(replace(reducer,status='canceled',filled=D(4),remaining=D(0),version_us=2),self.now)
        before=await self.writer.market_inventory('A',subaccount=0)
        self.assertEqual(before.exit_journal.cancel_ids,('reduce',))
        await self.writer.fill(Fill('race','reduce','A','ask',D(4),D('.59'),D(0)),self.now)
        await self.report('6')
        plan=await self.runtime.management.refresh('A')
        self.assertEqual((plan.exit.mode,plan.exit.quantity),('ioc',6))
        self.assertFalse(plan.inventory.exit_journal.cancel_ids)

    async def test_delayed_book_queue_does_not_retimestamp_freshness(self):
        await self.position()
        self.runtime.management.set_terms(terms())
        name=self.runtime.engine.market_shard['A']; shard=self.runtime.engine.shards[name]
        self.runtime.engine.submit_book(name,dict(type='orderbook_delta',sid=1,seq=shard.sequences[1]+1,
            msg=dict(market_ticker='A',side='no',price_dollars='.6',delta_fp='1')),generation=shard.generation)
        self.now+=timedelta(seconds=6); self.monotonic+=6
        await self.report()
        while self.runtime.engine.backlog: await self.runtime.engine.step()
        plan=await self.runtime.management.refresh('A')
        self.assertIn('exit_book_unavailable',plan.exit.blockers)

    async def test_event_deadline_scheduled_without_waiting_900_seconds(self):
        await self.position(); await self.report()
        self.runtime.management.set_terms(terms(event_risk_at=NOW+timedelta(seconds=330)))
        await self.runtime.management.refresh('A')
        self.assertEqual(self.runtime.engine.deadlines.due_for('A'),130)


if __name__ == '__main__': unittest.main()
