"""Synthetic selection and runtime observations; no credentials or venue calls."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D, localcontext
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalshi_bot.account import normalize_snapshot
from kalshi_bot.exits import ExitTerms
from kalshi_bot.portfolio import PortfolioView
from kalshi_bot.quoting import Quote, program_plans, reference_plan
from kalshi_bot.ranking import RankingBoard
from kalshi_bot.risk import WindowState, window_bounds
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.selection import MarketSelector
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_engine import NOW, BANDS, book, program


def terms(ticker='A', **kwargs):
    return replace(ExitTerms(ticker, BANDS, NOW, NOW+timedelta(minutes=30),
        NOW+timedelta(hours=4), event_risk_at=NOW+timedelta(hours=2),
        taker_fee_per_contract_bound=D('.02')), **kwargs)


def view(**kwargs):
    return replace(PortfolioView('fixture', 1, 0, NOW, (), (), D(0), 0, ()), **kwargs)


def window(**kwargs):
    return replace(WindowState(*window_bounds(NOW), D(0), 30, False, NOW), **kwargs)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.s = MarketSelector(128)

    def add(self, ticker='A', **kwargs):
        b = kwargs.pop('book', replace(book(), ticker=ticker))
        ps = kwargs.pop('programs', (program(ticker=ticker),))
        t = kwargs.pop('terms', terms(ticker))
        self.s.update(b, ps, terms=t, now=NOW, valid_until=NOW+timedelta(seconds=10), **kwargs)

    def choose(self, **kwargs):
        args = dict(view=view(), window=window(), free_cash=D(500), account_known=True,
                    now=NOW, current=lambda t: True)
        args.update(kwargs)
        return self.s.propose(**args)

    def test_smaller_pool_beats_crowded_large_pool(self):
        self.add('A', programs=(program(pool_centicents=1000000),))
        crowded = replace(book(bids=(('.5', '10000'),), asks=(('.6', '10000'),)), ticker='B')
        self.add('B', book=crowded, programs=(program(ticker='B', pool_centicents=2000000),))
        result = self.choose()
        self.assertEqual([r.ticker for r in result.additions], ['A', 'B'])
        self.assertFalse(result.authorized)
        self.assertIsNone(result.additions[0].net_profit_usd)

    def test_duration_not_headline_pool(self):
        self.add('A', programs=(program(end=NOW+timedelta(hours=9), pool_centicents=2000000),))
        self.add('B')
        self.assertEqual(self.choose().additions[0].ticker, 'B')

    def test_capital_efficiency_breaks_equal_rate_tie(self):
        self.add('A', book=book(bids=(('.49', '1000'),), asks=(('.51', '1000'),)))
        self.add('B', book=replace(book(bids=(('.4', '1000'),), asks=(('.6', '1000'),)), ticker='B'))
        rows = self.choose().additions
        self.assertEqual(rows[0].gross_hourly_usd, rows[1].gross_hourly_usd)
        self.assertEqual(rows[0].ticker, 'B')

    def test_identity_breaks_complete_tie(self):
        self.add('B')
        self.add('A')
        self.assertEqual([r.ticker for r in self.choose().additions], ['A', 'B'])

    def test_deadline_caps_remaining_and_expires_without_tick(self):
        self.add(terms=terms(flatten_at=NOW+timedelta(seconds=5)))
        row = self.choose().additions[0]
        self.assertEqual(row.earning_until, NOW+timedelta(seconds=5))
        with localcontext() as ctx:
            ctx.prec = 40
            self.assertEqual(row.gross_remaining_usd, row.gross_hourly_usd*D(5)/3600)
        self.assertIn('remaining_projection_below_program_minimum_accrual_unknown', row.warnings)
        self.assertFalse(self.choose(now=NOW+timedelta(seconds=5)).additions)

    def test_resting_quote_discounted_then_excluded_not_replaced_with_reference(self):
        proposed = (Quote('bid', D('.48'), D(10)), Quote('ask', D('.62'), D(10)))
        self.add(proposed=proposed)
        row = self.s.board.ranked(now=NOW, by='selection')[0]
        self.assertEqual(row.quote_basis, 'explicit_quotes')
        self.assertEqual(row.quote_statuses, ('discounted', 'discounted'))
        self.assertFalse(self.choose().additions)  # actual-order review is not fresh entry authority
        self.add(book=book(bids=(('.5', '1000'), ('.48', '100')),
                           asks=(('.6', '1000'), ('.62', '100'))), proposed=proposed)
        row = self.s.board.ranked(now=NOW, by='selection')[0]
        self.assertEqual(row.quote_statuses, ('outside_reward_cutoff', 'outside_reward_cutoff'))
        self.assertIn('proposed_quote_not_scoring', row.blockers)
        self.assertFalse(row.quotes)

    def test_equal_price_weight_no_extra_score_for_touch(self):
        rows = []
        for p in ('.49', '.50'):
            self.add(proposed=(Quote('bid', D(p), D(10)), Quote('ask', D('.61'), D(10))))
            rows.append(self.s.board.ranked(now=NOW, by='selection')[0])
        self.assertEqual(rows[0].snapshot_share, rows[1].snapshot_share)
        self.assertEqual(rows[0].quote_statuses, ('full_price_weight', 'full_price_weight'))

    def test_reflected_orders_count_once(self):
        qs = (Quote('bid', D('.49'), D(10)), Quote('ask', D('.61'), D(10)))
        self.add(proposed=qs)
        before = self.s.board.ranked(now=NOW, by='selection')[0]
        b = book(bids=(('.5','100'),('.49','110'),('.48','1000')),
                 asks=(('.6','100'),('.61','110'),('.62','1000')))
        self.add(book=b, proposed=qs, reflected=qs)
        after = self.s.board.ranked(now=NOW, by='selection')[0]
        self.assertEqual(before.snapshot_share, after.snapshot_share)

    def test_thin_opposite_book_blocks_even_full_price_weight(self):
        self.add(book=book(asks=(('.6','980'),)))
        self.assertFalse(self.choose().additions)
        self.assertIn('insufficient_two_sided_depth', self.choose().exclusions[0][1])

    def test_one_ineligible_leg_never_scores_as_admissible_pair(self):
        self.add(proposed=(Quote('bid',D('.47'),D(10)), Quote('ask',D('.61'),D(10))))
        row = self.s.board.ranked(now=NOW, by='selection')[0]
        self.assertIsNone(row.gross_hourly_usd)
        self.assertIn('proposed_quote_not_scoring', row.blockers)

    def test_entry_slots_are_pairs_not_fixed_market_count(self):
        for i in range(20): self.add(str(i))
        self.assertEqual(len(self.choose().additions), 15)
        self.assertEqual(len(self.choose(window=window(cap=25)).additions), 12)
        self.assertFalse(self.choose(view=view(entry_count=29)).additions)

    def test_capital_skips_unaffordable_and_tries_next_candidate(self):
        self.add('A', programs=(program(pool_centicents=2000000),))
        self.add('B', book=replace(book(bids=(('.1','1000'),), asks=(('.9','1000'),)), ticker='B'))
        result = self.choose(free_cash=D(3))
        self.assertEqual([r.ticker for r in result.additions], ['B'])
        self.assertLessEqual(result.estimated_capital, 3)

    def test_portfolio_cash_and_fee_reserve(self):
        self.add()
        self.assertFalse(self.choose(view=view(exposure=(('OTHER',D(295)),))).additions)
        self.assertFalse(self.choose(free_cash=D('8.8')).additions)
        self.assertEqual(self.choose().estimated_capital, D('9.20'))

    def test_incumbents_and_inventory_are_not_rotated_for_better_reward(self):
        self.add('A')
        self.add('B', programs=(program(ticker='B',pool_centicents=9000000),))
        result = self.choose(view=view(entry_count=30,exposure=(('A',D(9)),)))
        self.assertFalse(result.additions)
        self.assertEqual(result.retained, ('A',))
        result = self.choose(view=view(positions=(('A',D(10)),)), protected=('UNKNOWN',))
        self.assertEqual(result.retained, ('A','UNKNOWN'))
        self.assertEqual([r.ticker for r in result.additions], ['B'])

    def test_account_unknown_or_uncertain_blocks_all_new_risk(self):
        self.add()
        for kw in (dict(account_known=False),dict(view=view(blockers=('ambiguous_send',))),
                   dict(window=window(held=True)),dict(window=window(cap=0)),
                   dict(now=NOW+timedelta(seconds=6)),dict(now=NOW-timedelta(seconds=1))):
            with self.subTest(kw=kw): self.assertFalse(self.choose(**kw).additions)

    def test_source_check_defaults_closed_and_rechecks_every_row(self):
        self.add('A'); self.add('B')
        result = self.s.propose(view=view(),window=window(),free_cash=D(500),account_known=True,now=NOW)
        self.assertFalse(result.additions)
        self.assertEqual([r.ticker for r in self.choose(current=lambda t: t=='B').additions], ['B'])

    def test_terms_missing_fee_timing_or_inactive_blocks(self):
        for t in (terms(taker_fee_per_contract_bound=None),terms(event_risk_at=None),terms(active=False),
                  terms(flatten_at=NOW)):
            with self.subTest(terms=t):
                self.add(terms=t)
                self.assertFalse(self.choose().additions)

    def test_zero_pool_and_caps_do_not_rank_as_income(self):
        for p in (program(pool_centicents=0),program(max_reward_centicents=10000)):
            self.add(programs=(p,))
            self.assertFalse(self.choose().additions)

    def test_overlapping_programs_not_summed(self):
        self.add(programs=(program(),program(program_id='P2',pool_centicents=2000000)))
        row = self.choose().additions[0]
        self.assertEqual(row.program_id, 'P2')
        self.assertEqual(len(self.choose().additions), 1)

    def test_repeated_invalidation_bounds_auxiliary_state(self):
        for i in range(50):
            self.add(programs=(program(program_id=str(i)),))
            self.assertEqual(len(self.s._fees), 1)
            self.assertEqual(len(self.s.exit_stress), 1)
        self.s.invalidate('A')
        self.assertFalse(self.s._fees or self.s.exit_stress)

    def test_failed_update_revokes_prior_optimistic_row(self):
        self.add()
        with self.assertRaises(InvalidData): self.add(terms=terms('B'))
        self.assertFalse(self.choose().additions)
        self.assertFalse(self.s._fees)

    def test_discount_one_full_weight_and_discount_zero_no_weight(self):
        qs=(Quote('bid',D('.48'),D(10)),Quote('ask',D('.62'),D(10)))
        self.add(programs=(program(discount_bps=10000),),proposed=qs)
        self.assertEqual(self.s.board.ranked(now=NOW,by='selection')[0].quote_statuses,
                         ('full_price_weight','full_price_weight'))
        self.add(programs=(program(discount_bps=0),),proposed=qs)
        self.assertEqual(self.s.board.ranked(now=NOW,by='selection')[0].quote_statuses,
                         ('zero_price_weight','zero_price_weight'))

    def test_program_starts_inclusive_ends_exclusive(self):
        for p, allowed in ((program(start=NOW),True),
                           (program(start=NOW+timedelta(seconds=1)),False),
                           (program(end=NOW),False)):
            self.add(programs=(p,))
            self.assertEqual(bool(self.choose().additions),allowed)

    def test_shared_book_validation_once_and_no_cross_program_contamination(self):
        import kalshi_bot.quoting as quoting
        b=book()
        before=(dict(b.bids.levels),dict(b.asks.levels))
        programs=tuple(program(program_id=str(i),target=D(300+i*100)) for i in range(16))
        with patch.object(quoting,'_base',wraps=quoting._base) as base:
            plans=program_plans(b,programs,BANDS,now=NOW,market_open=True)
            self.assertEqual(base.call_count,1)
        for p, plan in zip(programs,plans):
            self.assertEqual(plan,reference_plan(b,p,BANDS,now=NOW,market_open=True))
        self.assertEqual(before,(b.bids.levels,b.asks.levels))

    def test_selection_failure_during_exit_check_clears_all_side_caches(self):
        self.add()
        with patch('kalshi_bot.selection.cross',side_effect=InvalidData('fixture')):
            with self.assertRaises(InvalidData): self.add()
        self.assertFalse(self.s._fees or self.s.exit_stress or self.s.board.markets)

    def test_unknown_and_negative_capital_inputs_never_get_rounded(self):
        self.add()
        for value in (1.5,True,D('-1')):
            with self.assertRaises(InvalidData): self.choose(free_cash=value)

    def test_one_side_and_resized_order_sets_never_become_entries(self):
        for qs in ((Quote('bid',D('.49'),D(10)),),
                   (Quote('bid',D('.49'),D(9)),Quote('ask',D('.61'),D(9)))):
            self.add(proposed=qs)
            self.assertFalse(self.choose().additions)


class RuntimeSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'fixture.db').start()
        self.now, self.mono = NOW, 100.
        async def noop(*a): pass
        self.r = RecoveryRuntime(self.writer,None,None,tickers=('A',),subaccount=0,
            history_start=NOW-timedelta(hours=1),now=lambda:self.now,clock=lambda:self.mono,
            evaluate=noop,deadline_handler=noop,lifecycle_handler=noop)
        self.s = self.r.attach_selection(offline_fixture=True)
        self.r.account.connect_generation()
        self.r.engine.begin_private_epoch()
        self.w = await self.writer.observe(NOW)
        snap = normalize_snapshot((),(),dict(balance_dollars='500',updated_ts=1),subaccount=0)
        await self.r.account.finish_reconciliation(self.r.account.begin_reconciliation(NOW),snap,NOW)
        self.r.management.set_terms(terms())
        self.publish()
        await self.book_event()

    async def asyncTearDown(self):
        self.r.engine.stop()
        await self.writer.close()
        self.temp.cleanup()

    def publish(self, **kwargs):
        data=dict(observed_at=self.now,valid_until=self.now+timedelta(minutes=5))
        data.update(kwargs)
        self.s.set_programs('A',(program(),),**data)

    async def book_event(self):
        name, shard = next(iter(self.r.engine.shards.items()))
        generation=self.r.engine.begin_book_epoch(name)
        self.r.engine.submit_book(name,dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(
            market_ticker='A',yes_dollars_fp=[['.5','1000']],no_dollars_fp=[['.6','1000']])),generation=generation)
        await self.r.engine.step()

    async def test_engine_updates_selection_no_extra_writer_mutation(self):
        revision=self.writer.revision
        result=await self.s.propose(window=self.w,free_cash=D(500))
        self.assertEqual(len(result.additions),1)
        self.assertEqual(self.writer.revision,revision)
        self.assertFalse(await self.writer.mutations())
        self.assertFalse(result.authorized or self.r.entry_allowed)

    async def test_account_changes_during_await_defeat_proposal(self):
        original=self.r.risk_view
        async def raced():
            result=await original()
            self.r._revoke()
            return result
        self.r.risk_view=raced
        result=await self.s.propose(window=self.w,free_cash=D(500))
        self.assertFalse(result.additions)
        self.assertIn('selection_sources_changed',result.blockers)

    async def test_book_revision_and_pending_ingress_revoke_current(self):
        self.assertTrue(self.s.current('A'))
        name,shard=next(iter(self.r.engine.shards.items()))
        self.r.engine.submit_book(name,dict(type='orderbook_delta',sid=1,seq=2,msg=dict(
            market_ticker='A',side='yes',price_dollars='.5',delta_fp='10')),generation=shard.generation)
        self.assertFalse(self.s.current('A'))
        await self.r.engine.step()
        self.assertTrue(self.s.current('A'))

    async def test_term_and_program_revocation(self):
        self.r.management.revoke_terms('A')
        self.assertFalse((await self.s.propose(window=self.w,free_cash=D(500))).additions)
        self.r.management.set_terms(terms())
        await self.r.engine.step()
        self.s.set_programs('A',(),observed_at=NOW,valid_until=NOW+timedelta(seconds=30))
        self.assertFalse(self.s.selector.board.markets)

    async def test_exact_report_freshness_boundary_does_not_crash(self):
        self.now+=timedelta(seconds=5)
        self.mono+=5
        await self.r._deadline('A')
        self.assertFalse(self.s.selector.board.markets)

    async def test_program_expiry_and_regression(self):
        self.publish(valid_until=NOW+timedelta(seconds=1))
        await self.r.engine.step()
        self.now+=timedelta(seconds=2)
        self.assertFalse(self.s.current('A'))
        with self.assertRaises(InvalidData): self.publish(observed_at=NOW-timedelta(seconds=1))
        self.assertFalse(self.s.selector.board.markets)

    async def test_attach_is_explicit_single_and_before_start(self):
        with self.assertRaises(InvalidData): self.r.attach_selection(offline_fixture=True)
        from kalshi_bot.selection_runtime import RuntimeSelection
        with self.assertRaises(InvalidData): RuntimeSelection(self.r)

    async def test_stopping_revokes_every_row(self):
        self.r.engine.stop()
        self.assertFalse(self.s.selector.board.markets)
        self.assertFalse((await self.s.propose(window=self.w,free_cash=D(500))).additions)

    async def test_failed_publication_keeps_timestamp_high_water(self):
        for _ in range(2):
            with self.assertRaises(InvalidData): self.publish(observed_at=NOW-timedelta(seconds=1))
        self.assertFalse(self.s.programs or self.s.selector.board.markets)

    async def test_program_and_terms_changed_while_portfolio_awaited(self):
        original=self.r.risk_view
        async def changed():
            v=await original()
            self.publish()
            return v
        self.r.risk_view=changed
        self.assertFalse((await self.s.propose(window=self.w,free_cash=D(500))).additions)

    async def test_owned_order_retained_with_reflection_unknown(self):
        # Real writer-created reservation, no venue send or account request.
        from test_bot_inventory_risk import request
        from kalshi_bot.config import BotConfig
        from kalshi_bot.orders import OrderUpdate
        req=request('owned')
        prepared=await self.writer.reserve_entry(req,attempt_id='owned-attempt',
            view=await self.r.risk_view(),config=BotConfig(),now=NOW,free_cash=D(500),
            account_known=True,offline_fixture=True)
        self.assertTrue(prepared.reserved)
        await self.writer.begin_send(prepared.receipt)
        await self.writer.record_outcome('ack',prepared.receipt,
            dict(order_id='o',fill_count='0',remaining_count='10',ts_ms=1),NOW)
        await self.writer.order(OrderUpdate('o','owned','A','bid',D('.5'),D(10),D(0),D(10),
                                            'resting',0,0,1),NOW)
        snapshot=normalize_snapshot((dict(order_id='o',client_order_id='owned',ticker='A',status='resting',
            exchange_index=0,book_side='bid',yes_price_dollars='.5',remaining_count_fp='10'),),(),
            dict(balance_dollars='495',updated_ts=1),subaccount=0)
        await self.r.account.finish_reconciliation(self.r.account.begin_reconciliation(NOW),snapshot,NOW)
        await self.r._evaluate('A',None,0)
        rows=self.s.selector.board.ranked(now=NOW,by='selection')
        self.assertIn('owned_orders_reward_reflection_unverified',rows[0].blockers)
        result=await self.s.propose(window=self.w,free_cash=D(500))
        self.assertFalse(result.additions)
        self.assertIn('A',result.retained)

    async def test_foreign_order_audit_blocks_entries(self):
        report=self.r.account.report
        self.r.account.report=replace(report,audit=replace(report.audit,blockers=('foreign_orders',)))
        await self.r._evaluate('A',None,0)
        self.assertFalse((await self.s.propose(window=self.w,free_cash=D(500))).additions)

    async def test_status_distinguishes_cached_and_current_no_new_reads(self):
        before=self.writer.revision
        self.assertEqual(self.s.status()['current_markets'],1)
        self.mono+=6
        status=self.s.status()
        self.assertEqual(status['current_markets'],0)
        self.assertEqual(status['cached_markets'],1)
        self.assertFalse(status['authorized'])
        self.assertEqual(self.writer.revision,before)

    async def test_unsupported_grid_excludes_market_not_entire_engine(self):
        from kalshi_bot.adapters import PriceBand
        bands=(PriceBand(D(0),D('.5'),D('.01')),PriceBand(D('.5'),D(1),D('.005')))
        self.r.management.set_terms(terms(bands=bands))
        await self.r.engine.step()
        self.assertFalse(self.r.engine.failed)
        result=await self.s.propose(window=self.w,free_cash=D(500))
        self.assertFalse(result.additions)
        self.assertIn(('A',('unsupported_selection_inputs',)),result.exclusions)
        self.r.management.set_terms(terms())
        await self.r.engine.step()
        self.assertTrue((await self.s.propose(window=self.w,free_cash=D(500))).additions)
        self.assertEqual(self.s.status()['rejected_markets'],0)

    async def test_unexpected_bug_is_not_silently_hidden(self):
        with patch.object(self.s.selector,'update',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError): await self.r._evaluate('A',None,0)
        self.assertFalse(self.s.current('A'))


if __name__ == '__main__': unittest.main()
