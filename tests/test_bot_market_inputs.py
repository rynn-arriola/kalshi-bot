"""Offline source/input, revocation and runtime wiring tests."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import unittest

from kalshi_bot.market_inputs import (ExitInputService, FeeProfile,
    SCHEDULED_RELEASE_CONDITION, SCHEDULED_RELEASE_REVIEW, TimingReview,
    parse_market, parse_event, parse_series, rules_digest, taker_bound,
    tick_bands, timestamp, fee_changes)
from kalshi_bot.rest import PageSet, ReadResult, RestReads, TokenBudget, WireResponse, request_path
from kalshi_bot.quota import QuotaUnavailable
from kalshi_bot.values import InvalidData
from test_bot_engine import NOW


def market(ticker='A', **kw):
    return dict(ticker=ticker,event_ticker='E',market_type='binary',exchange_index=0,
        open_time=(NOW-timedelta(hours=1)).isoformat(),close_time=(NOW+timedelta(hours=3)).isoformat(),
        status='active',can_close_early=False,notional_value_dollars='1.0000',rules_primary='Reviewed test fixture, not real market rules.',
        rules_secondary='',price_ranges=[dict(start='0',end='1',step='.01')],**kw)


class Reads:
    def __init__(self, tickers=('A',)):
        self.markets = {t:market(t) for t in tickers}
        self.event = dict(event_ticker='E',series_ticker='S',exchange_index=0,
                          fee_type_override=None,fee_multiplier_override=None)
        self.series = dict(ticker='S',fee_type='quadratic',fee_multiplier=D(1))
        self.milestone = dict(id='M',type='football_game',start_date=(NOW+timedelta(hours=1)).isoformat(),
                             primary_event_tickers=['E'])
        self.event_changes, self.series_changes, self.calls = [], [], []
        self.before = None

    async def read(self, name, **params):
        self.calls.append((name,params))
        if self.before: await self.before(name)
        values = {'market':{'market':self.markets.get(params.get('ticker'))}, 'event':{'event':self.event},
                  'series':{'series':self.series}, 'milestone':{'milestone':self.milestone},
                  'series_fees':{'series_fee_change_arr':self.series_changes}}
        return ReadResult(deepcopy(values[name]),100)

    async def collect(self, name, **params):
        self.calls.append((name,params))
        if self.before: await self.before(name)
        return PageSet(tuple(deepcopy(self.event_changes)),1,100)


def review(row):
    return TimingReview(row['ticker'],'E','M','football_game',rules_digest(row),'fixture-only',
                        NOW+timedelta(hours=2),early_close_reviewed=True)


class ParsingTests(unittest.TestCase):
    def test_variable_tick_grid_uses_ranges_not_label(self):
        doc = market()
        doc['price_ranges'] = [dict(start='0',end='.1',step='.001'),
            dict(start='.1',end='.9',step='.01'),dict(start='.9',end='1',step='.001')]
        doc['price_level_structure']='future-label-not-hardcoded'
        self.assertEqual(parse_market({'market':doc},'A').bands[1].step,D('.01'))

    def test_gaps_overlap_inverted_and_overprecision_rejected(self):
        for rows in ([dict(start='.1',end='1',step='.01')],
                     [dict(start='0',end='.6',step='.01'),dict(start='.5',end='1',step='.01')],
                     [dict(start='0',end='1',step='.00001')],[]):
            with self.subTest(rows=rows), self.assertRaises(InvalidData): tick_bands(rows)

    def test_scalar_and_multivariate_are_not_silently_supported(self):
        for extra in ({'market_type':'scalar'},{'mve_collection_ticker':'COMBO'},{'notional_value_dollars':'10'}):
            doc = {**market(),**extra}
            with self.assertRaises(InvalidData): parse_market({'market':doc},'A')

    def test_expiry_and_occurrence_do_not_become_event_start(self):
        doc = market(expected_expiration_time=NOW.isoformat(),occurrence_datetime=NOW.isoformat())
        parsed = parse_market({'market':doc},'A')
        self.assertFalse(hasattr(parsed,'event_risk_at'))
        self.assertEqual(parsed.occurrence_at,NOW)
        self.assertEqual(parsed.closes,NOW+timedelta(hours=3))

    def test_naive_timestamps_and_float_fees_rejected(self):
        with self.assertRaises(InvalidData): timestamp('2026-09-20T12:00:00')
        with self.assertRaises(InvalidData): parse_series({'series':dict(ticker='S',fee_type='quadratic',fee_multiplier=1.0)},'S')

    def test_partial_override_not_defaulted(self):
        row=Reads().event
        row['fee_type_override']='quadratic'
        with self.assertRaises(InvalidData): parse_event({'event':row},'E')

    def test_candidate_list_endpoints_are_public_and_scoped(self):
        spec, path = request_path('markets',
            {'tickers':'A,B','limit':1000,'mve_filter':'exclude'}, 'candidate')
        self.assertFalse(spec.authenticated)
        self.assertIn('tickers=A%2CB', path)
        spec, path = request_path('milestones',
            {'minimum_start_date':'2026-09-22T00:00:00+00:00','limit':500}, 'candidate')
        self.assertFalse(spec.authenticated)
        self.assertIn('minimum_start_date=', path)
        with self.assertRaises(InvalidData):
            request_path('markets', {'status':'open'}, 'metadata')

    def test_rules_hash_tracks_early_close_and_rule_changes_not_prices(self):
        row=market()
        self.assertNotEqual(rules_digest(row),rules_digest({**row,'can_close_early':True}))
        self.assertNotEqual(rules_digest(row),rules_digest({**row,'rules_secondary':'changed'}))
        self.assertNotEqual(rules_digest(row),rules_digest({**row,'floor_strike':D('5.12')}))
        self.assertNotEqual(rules_digest(row),rules_digest({**row,
            'occurrence_datetime':NOW.isoformat()}))
        self.assertEqual(rules_digest(row),rules_digest({**row,'yes_bid_dollars':'.6'}))

    def test_fee_bound_covers_fragmented_fills_both_directions(self):
        for quantum in (D('.0001'),D('.01')):
            profile=FeeProfile(quantum,'fixture',NOW+timedelta(hours=1))
            bound=taker_bound(('quadratic',D('1.5')),profile)
            for p in (D('.0001'),D('.1234'),D('.5'),D('.9999')):
                for direction in (-1,1):
                    qty=D('.01')
                    trade=(D('.07')*D('1.5')*qty*p*(1-p)).quantize(D('.000001'),rounding=ROUND_CEILING)
                    revenue=direction*qty*p
                    aligned=((revenue-trade)/quantum).to_integral_value(rounding=ROUND_FLOOR)*quantum
                    net=trade+(revenue-trade-aligned) # omit rebates, worst bound
                    self.assertLessEqual(net,bound*qty)

    def test_flat_model_no_guessed_fee(self):
        self.assertIsNone(taker_bound(('flat',D(1)),FeeProfile(D('.0001'),'fixture',NOW+timedelta(hours=1))))

    def test_direct_bound_includes_rounding_and_multiplier(self):
        profile=FeeProfile(D('.0001'),'fixture',NOW+timedelta(hours=1))
        self.assertEqual(taker_bound(('quadratic',D(1)),profile),D('.0276'))

    def test_fee_schedule_scope_and_duplicate_rows_rejected(self):
        row=dict(id='F',series_ticker='S',fee_type='quadratic',fee_multiplier=D(1),scheduled_ts=NOW.isoformat())
        for rows,key in (([row,row],'S'),([row],'OTHER')):
            with self.assertRaises(InvalidData): fee_changes(rows,key)

    def test_new_public_routes_are_scoped_get_metadata(self):
        for name,param,path in (('event','event_ticker','/events/E'),('series','series_ticker','/series/E'),
                                ('milestone','milestone_id','/milestones/E')):
            spec,actual=request_path(name,{param:'E'},'metadata')
            self.assertEqual(actual,path)
            self.assertFalse(spec.authenticated)
            with self.assertRaises(InvalidData): request_path(name,{param:'../secrets'},'metadata')


class InputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reads=Reads(('A','B'))
        self.now,self.mono=NOW,100.
        self.published,self.revoked={},[]
        self.service=ExitInputService(self.reads,('A','B'),now=lambda:self.now,clock=lambda:self.mono,ttl=30,
            timing_reviews=tuple(review(r) for r in self.reads.markets.values()),
            fee_profile=FeeProfile(D('.0001'),'fixture',NOW+timedelta(hours=1)))
        self.service.bind(lambda terms:self.published.__setitem__(terms.ticker,terms),self.revoke)
        self.service.begin(1)
        self.service.subscribed(1,7)

    def revoke(self,ticker):
        self.revoked.append(ticker)
        self.published.pop(ticker,None)

    async def asyncTearDown(self): await self.service.close()

    def stream(self,kind='market_lifecycle_v2',seq=1,**msg):
        self.service.ingest(dict(type=kind,sid=7,seq=seq,msg=msg),generation=1)

    async def test_complete_reviewed_inputs_publish_exact_terms(self):
        result=await self.service.refresh('A')
        self.assertEqual(result.blockers,())
        self.assertEqual(result.terms.event_risk_at,NOW+timedelta(hours=1))
        self.assertEqual(result.terms.deadline,NOW+timedelta(minutes=55))
        self.assertEqual(result.terms.taker_fee_per_contract_bound,D('.0276'))
        self.assertEqual(len(result.provenance),6)

    async def test_unreviewed_timing_is_explicit_not_inferred(self):
        self.service.reviews.clear()
        result=await self.service.refresh('A')
        self.assertIsNone(result.terms.event_risk_at)
        self.assertIn('timing_review_missing',result.blockers)
        self.assertFalse(any(name=='milestone' for name,_ in self.reads.calls))

    async def test_unknown_member_profile_blocks_fee_estimate(self):
        self.service.fee_profile=None
        result=await self.service.refresh('A')
        self.assertIsNone(result.terms.taker_fee_per_contract_bound)
        self.assertIn('fee_profile_missing',result.blockers)

    async def test_changed_rules_invalidate_timing_review(self):
        self.reads.markets['A']['rules_primary']='new rule'
        result=await self.service.refresh('A')
        self.assertIn('timing_review_conflict',result.blockers)
        self.assertIsNone(result.terms.event_risk_at)

    async def test_early_close_needs_explicit_review(self):
        row=self.reads.markets['A']
        row['can_close_early']=True
        self.service.reviews['A']=replace(review(row),early_close_reviewed=False)
        self.assertIn('timing_review_conflict',(await self.service.refresh('A')).blockers)

    async def test_scheduled_release_rechecks_current_milestone_clock(self):
        row=self.reads.markets['A']
        row.update(can_close_early=True,
            early_close_condition=SCHEDULED_RELEASE_CONDITION,
            occurrence_datetime=(NOW+timedelta(hours=2)).isoformat())
        self.reads.milestone['type']='company_report'
        self.service.reviews['A']=TimingReview('A','E','M','company_report',
            rules_digest(row),SCHEDULED_RELEASE_REVIEW,NOW+timedelta(hours=2),
            early_close_reviewed=True)
        self.assertEqual((await self.service.refresh('A')).blockers,())
        self.reads.milestone['start_date']=(NOW+timedelta(hours=3)).isoformat()
        self.service.values.pop(('milestone','M'))
        self.assertIn('timing_review_conflict',
            (await self.service.refresh('A')).blockers)

    async def test_related_only_milestone_is_not_a_primary_binding(self):
        self.reads.milestone['primary_event_tickers']=[]
        self.reads.milestone['related_event_tickers']=['E']
        self.assertIn('milestone_binding_conflict',(await self.service.refresh('A')).blockers)

    async def test_event_override_takes_precedence_and_clear_uses_series(self):
        await self.service.refresh('A')
        count=len(self.reads.calls)
        self.stream('event_fee_update',event_ticker='E',fee_type_override='quadratic',fee_multiplier_override=D(2))
        self.assertNotIn('A',self.published)
        result=await self.service.refresh('A')
        self.assertEqual(result.terms.taker_fee_per_contract_bound,D('.0451'))
        self.assertEqual(len(self.reads.calls),count)
        self.stream('event_fee_update',seq=2,event_ticker='E',fee_type_override=None,fee_multiplier_override=None)
        self.assertEqual((await self.service.refresh('A')).terms.taker_fee_per_contract_bound,D('.0276'))

    async def test_tick_update_uses_stream_without_redundant_rest(self):
        await self.service.refresh('A')
        calls=len(self.reads.calls)
        self.stream(market_ticker='A',event_type='price_level_structure_updated',
                    price_ranges=[dict(start='0',end='1',step='.001')])
        self.assertNotIn('A',self.published)
        self.assertEqual((await self.service.refresh('A')).terms.bands[0].step,D('.001'))
        self.assertEqual(len(self.reads.calls),calls)

    async def test_close_and_pause_updates_invalidate_immediately(self):
        await self.service.refresh('A')
        close=NOW+timedelta(minutes=10)
        self.stream(market_ticker='A',event_type='close_date_updated',close_ts=int(close.timestamp()))
        self.assertEqual((await self.service.refresh('A')).terms.close_at,close)
        self.stream(seq=2,market_ticker='A',event_type='deactivated')
        self.assertFalse((await self.service.refresh('A')).terms.active)

    async def test_fee_change_clamps_terms_expiry(self):
        due=NOW+timedelta(seconds=10)
        self.reads.series_changes=[dict(id='F',series_ticker='S',fee_type='quadratic',fee_multiplier=D(2),scheduled_ts=due.isoformat())]
        self.assertEqual((await self.service.refresh('A')).terms.valid_until,due)

    async def test_effective_fee_change_must_match_current_metadata(self):
        self.reads.event_changes=[dict(id='F',event_ticker='E',series_ticker='S',fee_type_override='quadratic',
                                      fee_multiplier_override=D(2),scheduled_ts=NOW.isoformat())]
        with self.assertRaises(InvalidData): await self.service.refresh('A')
        self.assertNotIn('A',self.published)

    async def test_stream_update_cannot_be_overwritten_by_pending_rest(self):
        entered,release=asyncio.Event(),asyncio.Event()
        async def wait(name):
            if name=='market':
                entered.set()
                await release.wait()
        self.reads.before=wait
        task=asyncio.create_task(self.service.refresh('A'))
        await entered.wait()
        self.stream(market_ticker='A',event_type='deactivated')
        release.set()
        with self.assertRaises(InvalidData): await task
        self.assertNotIn('A',self.published)

    async def test_rest_conflicting_with_stream_after_ttl_stays_blocked(self):
        await self.service.refresh('A')
        self.stream(market_ticker='A',event_type='deactivated')
        self.now+=timedelta(seconds=31); self.mono+=31
        with self.assertRaises(InvalidData): await self.service.refresh('A')
        self.assertNotIn('A',self.published)

    async def test_stream_before_first_rest_is_preserved_until_metadata_agrees(self):
        self.stream(market_ticker='A',event_type='deactivated')
        with self.assertRaises(InvalidData): await self.service.refresh('A')
        self.reads.markets['A']['status']='inactive'
        self.assertFalse((await self.service.refresh('A')).terms.active)

    async def test_fee_stream_before_bootstrap_cannot_be_lost(self):
        self.stream('event_fee_update',event_ticker='E',fee_type_override='quadratic',fee_multiplier_override=D(2))
        with self.assertRaises(InvalidData): await self.service.refresh('A')
        self.reads.event.update(fee_type_override='quadratic',fee_multiplier_override=D(2))
        self.assertEqual((await self.service.refresh('A')).terms.taker_fee_per_contract_bound,D('.0451'))

    async def test_expired_baseline_does_not_discard_new_stream_override(self):
        await self.service.refresh('A')
        self.now+=timedelta(seconds=31); self.mono+=31
        self.stream('event_fee_update',event_ticker='E',fee_type_override='quadratic',fee_multiplier_override=D(3))
        with self.assertRaises(InvalidData): await self.service.refresh('A')

    async def test_reconnect_revokes_terms_and_old_responses(self):
        await self.service.refresh('A')
        self.service.begin(2)
        self.assertFalse(self.published)
        with self.assertRaises(InvalidData): await self.service.refresh('A')
        self.assertFalse(self.service.ingest({},generation=1))

    async def test_gap_or_unknown_message_revokes_all(self):
        await self.service.refresh('A')
        self.stream(market_ticker='UNTRACKED',event_type='activated')
        with self.assertRaises(InvalidData): self.stream(seq=3,market_ticker='A',event_type='deactivated')
        self.assertFalse(self.service.connected)
        self.assertFalse(self.published)

    async def test_missing_ranges_never_hardcodes_label(self):
        await self.service.refresh('A')
        with self.assertRaises(KeyError):
            self.stream(market_ticker='A',event_type='price_level_structure_updated',price_level_structure='linear_cent')
        self.assertFalse(self.published)

    async def test_shared_dependencies_and_cached_reads(self):
        await asyncio.gather(self.service.refresh('A'),self.service.refresh('B'))
        self.assertEqual(len(self.reads.calls),7) # two markets + five shared dependencies
        await self.service.refresh('A')
        self.assertEqual(len(self.reads.calls),7)

    async def test_review_replacements_retire_old_dependencies_without_reusing_revisions(self):
        service=ExitInputService(self.reads,('A',),now=lambda:self.now,clock=lambda:self.mono,ttl=30,
            timing_reviews=(self.service.reviews['A'],),fee_profile=self.service.fee_profile)
        published={}
        service.bind(lambda terms:published.__setitem__(terms.ticker,terms),
                     lambda ticker:published.pop(ticker,None))
        try:
            service.begin(1); service.subscribed(1,7)
            await service.refresh('A')
            for number in range(25):
                milestone=f'M{number}'
                service.set_review('A',replace(service.reviews['A'],milestone_id=milestone))
                self.reads.milestone['id']=milestone
                result=await service.refresh('A')
                self.assertEqual(result.blockers,())
                self.assertEqual(len(service.epochs),6)
            service.begin(2); service.subscribed(2,7)
            self.assertEqual((await service.refresh('A')).blockers,())
            self.assertEqual(len(service.epochs),6)
        finally: await service.close()

    async def test_review_retirement_keeps_other_market_shared_milestone(self):
        await asyncio.gather(self.service.refresh('A'),self.service.refresh('B'))
        self.service.set_review('A',replace(self.service.reviews['A'],milestone_id='M2'))
        self.assertIn(('milestone','M'),self.service.values)
        self.reads.milestone['id']='M2'
        await self.service.refresh('A')
        calls=len(self.reads.calls)
        await self.service.refresh('B')
        self.assertEqual(len(self.reads.calls),calls)

    async def test_pending_retired_review_cannot_restore_its_old_milestone(self):
        entered,release=asyncio.Event(),asyncio.Event()
        calls=0
        async def slow(name):
            nonlocal calls
            if name=='milestone':
                calls+=1
                if calls==1:
                    entered.set()
                    await release.wait()
        self.reads.before=slow
        old=asyncio.create_task(self.service.refresh('A'))
        try:
            await asyncio.wait_for(entered.wait(),1)
            self.service.set_review('A',replace(self.service.reviews['A'],milestone_id='M2'))
            self.service.set_review('B',replace(self.service.reviews['B'],milestone_id='M2'))
            self.reads.milestone['id']='M2'
            with self.assertRaises(InvalidData): await old
            current=await self.service.refresh('A')
            self.assertEqual(current.blockers,())
            self.assertNotIn(('milestone','M'),self.service.values)
            self.assertLessEqual(len(self.service.epochs),7)
        finally:
            release.set()
            await asyncio.gather(old,return_exceptions=True)

    async def test_read_ttl_starts_before_network_wait(self):
        async def delay(name):
            if name=='market':
                self.now+=timedelta(seconds=31); self.mono+=31
        self.reads.before=delay
        with self.assertRaises(InvalidData): await self.service.refresh('A')

    async def test_unknown_universe_events_do_not_grow_cache(self):
        for n in range(100):
            self.stream('event_fee_update',seq=n+1,event_ticker='OTHER'+str(n),fee_type_override=None,fee_multiplier_override=None)
        self.assertEqual(len(self.service.epochs),0)

    async def test_foreign_exchange_blocks_publication(self):
        self.reads.event['exchange_index']=1
        with self.assertRaises(InvalidData): await self.service.refresh('A')

    async def test_optional_expiry_waiver_does_not_zero_fees(self):
        self.reads.markets['A']['fee_waiver_expiration_time']=(NOW+timedelta(hours=1)).isoformat()
        self.assertEqual((await self.service.refresh('A')).terms.taker_fee_per_contract_bound,D('.0276'))

    async def test_failed_refresh_revokes_previous_published_terms(self):
        await self.service.refresh('A')
        self.now+=timedelta(seconds=31); self.mono+=31
        self.reads.markets['A']['price_ranges']=[]
        with self.assertRaises(InvalidData): await self.service.refresh('A')
        self.assertNotIn('A',self.published)

    async def test_quota_deferral_is_not_logged_as_metadata_failure(self):
        events=[]
        class Log:
            def emit(self,name,**fields): events.append(name)
        self.service.diagnostics=Log()
        async def unavailable(name):
            raise QuotaUnavailable()
        self.reads.before=unavailable
        with self.assertRaises(QuotaUnavailable):
            await self.service.refresh('A')
        await asyncio.sleep(0)
        self.assertIn('exit_inputs_deferred',events)
        self.assertNotIn('exit_inputs_failed',events)
        self.assertNotIn('metadata_dependency_failed',events)

    async def test_review_revocation_during_milestone_read_wins(self):
        async def revoke(name):
            if name=='milestone': self.service.reviews.clear()
        self.reads.before=revoke
        with self.assertRaises(InvalidData): await self.service.refresh('A')
        self.assertNotIn('A',self.published)

    async def test_profile_expiring_during_read_cannot_publish(self):
        self.service.fee_profile=FeeProfile(D('.0001'),'fixture',NOW+timedelta(seconds=1))
        async def expire(name):
            if name=='milestone':
                self.now+=timedelta(seconds=2); self.mono+=2
        self.reads.before=expire
        with self.assertRaises(InvalidData): await self.service.refresh('A')

    async def test_runtime_routes_lifecycle_updates_and_disconnect_to_manager(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from kalshi_bot.writer import LedgerWriter
        from kalshi_bot.runtime import RecoveryRuntime
        from test_bot_recovery_runtime import FakeReader
        async def noop(*_): pass
        service=ExitInputService(self.reads,('A','B'),now=lambda:self.now,clock=lambda:self.mono,ttl=30,
            timing_reviews=tuple(self.service.reviews.values()),fee_profile=self.service.fee_profile)
        with TemporaryDirectory() as folder:
            async with LedgerWriter(Path(folder)/'test.db') as writer:
                runtime=RecoveryRuntime(writer,self.reads,FakeReader,tickers=('A','B'),subaccount=0,
                    history_start=NOW-timedelta(hours=1),now=lambda:self.now,evaluate=noop,deadline_handler=noop,
                    lifecycle_handler=noop,clock=lambda:self.mono,market_inputs=service)
                spec=next(s for s in runtime.specs if s.name=='lifecycle')
                task=asyncio.create_task(runtime._connection(spec))
                try:
                    async with asyncio.timeout(2):
                        while not service.connected: await asyncio.sleep(.001)
                    await runtime.refresh_exit_inputs('A')
                    self.assertIn('A',runtime.management.terms)
                    await runtime._consume(spec,dict(type='market_lifecycle_v2',sid=1,seq=1,
                        msg=dict(market_ticker='A',event_type='deactivated')),1,set())
                    self.assertNotIn('A',runtime.management.terms)
                    await runtime.refresh_exit_inputs('A')
                    self.assertFalse(runtime.management.terms['A'].active)
                    runtime.stop()
                    self.assertFalse(runtime.management.terms)
                finally:
                    runtime.stop(); task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
                    await service.close()

    async def test_lifecycle_exhaustion_waits_then_recovers_without_resetting_generation(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from kalshi_bot.writer import LedgerWriter
        from kalshi_bot.runtime import RecoveryRuntime
        async def noop(*_): pass
        service=ExitInputService(self.reads,('A',),now=lambda:self.now,clock=lambda:self.mono,ttl=30,
            timing_reviews=(self.service.reviews['A'],),fee_profile=self.service.fee_profile)
        attempts, delays = 0, []
        hold = asyncio.Event()
        class Flaky:
            async def run(inner, consume):
                nonlocal attempts
                attempts += 1
                if attempts <= 3:
                    raise OSError('fixture transient')
                await consume('lifecycle',dict(type='subscribed',id=1,
                    msg=dict(channel='market_lifecycle_v2',sid=attempts)))
                await hold.wait()
        async def sleep(delay):
            delays.append(delay)
            self.mono += delay
        with TemporaryDirectory() as folder:
            async with LedgerWriter(Path(folder)/'test.db') as writer:
                runtime=RecoveryRuntime(writer,self.reads,lambda spec:Flaky(),tickers=('A',),subaccount=0,
                    history_start=NOW-timedelta(hours=1),now=lambda:self.now,evaluate=noop,
                    deadline_handler=noop,lifecycle_handler=noop,clock=lambda:self.mono,
                    sleep=sleep,jitter=lambda:1,market_inputs=service)
                spec=next(s for s in runtime.specs if s.name=='lifecycle')
                task=asyncio.create_task(runtime._connection(spec))
                try:
                    async with asyncio.timeout(2):
                        while not service.connected: await asyncio.sleep(.001)
                    self.assertEqual(attempts,4)
                    self.assertEqual(runtime.connection_attempts['lifecycle'],4)
                    self.assertEqual(runtime.reader_retry_rounds['lifecycle'],1)
                    self.assertEqual(runtime.reader_states['lifecycle'],'subscribed')
                    self.assertEqual(tuple(delays),(1,2,30))
                    self.assertEqual(service.generation,4)
                    self.assertEqual(runtime.reader_failures['lifecycle'],3)
                finally:
                    hold.set(); runtime.stop(); task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
                    await service.close()


class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_fee_cursor_required(self):
        reads=RestReads(TokenBudget(rate=100,capacity=100,default_cost=1),
                        wire=lambda *_:WireResponse(200,b'{"event_fee_changes":[]}'))
        try:
            with self.assertRaises(InvalidData):
                await reads.collect('event_fees',reason='metadata',event_ticker='E')
        finally: await reads.close()
