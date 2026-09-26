"""D-143 UNKNOWN creates: pre-send refusal is NOT_SENT; stale ones resolve by absence."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import sqlite3
from contextlib import closing
import unittest

from kalshi_bot.execution import resolve_unknown_create_absent, unknown_creates
from kalshi_bot.ledger import Ledger
from kalshi_bot.rest import ReadResult
from tests import test_bot_account_release as baseline
from tests import test_bot_routine_refresh as routine


class UnknownCreateTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch
    refresh = baseline.AccountReleaseTests.refresh
    reserve = baseline.AccountReleaseTests.reserve
    runtime = routine.RoutineRefreshTests.runtime
    advance = routine.RoutineRefreshTests.advance

    async def unknown(self, client='uncertain'):
        reserved = await self.reserve(client, req=dict(baseline.request(client), price='0.01'))
        self.assertTrue(reserved.reserved, reserved.blockers)
        self.assertTrue((await self.writer.begin_send(reserved.receipt)).dispatch_allowed)
        await self.writer.record_outcome('unknown', reserved.receipt, None, self.now)
        return reserved.receipt

    def state(self, client):
        with closing(sqlite3.connect(self.path)) as conn:
            intent = conn.execute('SELECT state FROM intents WHERE client_id=?', (client,)).fetchone()[0]
            phase = conn.execute("SELECT phase FROM mutation_attempts WHERE kind='create' AND "
                                 "json_extract(request,'$.client_order_id')=?", (client,)).fetchone()[0]
        return intent, phase

    async def with_runtime(self):
        runtime = await self.runtime()
        original = runtime.reads.read
        async def read(name, **kwargs):
            if name == 'cutoff':
                return ReadResult(dict(trades_created_ts=baseline.BOUNDARY.isoformat(),
                                       orders_updated_ts=baseline.BOUNDARY.isoformat()), 1)
            return await original(name, **kwargs)
        runtime.reads.read = read
        collect = runtime.reads.collect
        async def complete(name, **kwargs):
            result = await collect(name, **kwargs)
            # Production enumeration is complete or raises; mirror that here.
            return replace(result, exhausted=True) if name == 'orders' else result
        runtime.reads.collect = complete
        return runtime

    async def test_stale_absent_unknown_create_is_resolved_by_recovery(self):
        runtime = await self.with_runtime()
        receipt = await self.unknown()
        self.assertEqual(self.state('uncertain'), ('UNKNOWN', 'UNKNOWN'))
        self.advance(599)
        runtime.request_recovery()
        runtime.recovery_requested.clear()
        self.assertFalse(await runtime.recover_once())  # Too young: still blocks.
        self.assertEqual(self.state('uncertain'), ('UNKNOWN', 'UNKNOWN'))
        self.advance(2)
        runtime.request_recovery()
        runtime.recovery_requested.clear()
        self.assertTrue(await runtime.recover_once())
        self.assertEqual(self.state('uncertain'), ('REJECTED', 'REJECTED'))
        self.assertEqual(runtime.status()['unknown_creates_resolved'], 1)
        self.assertEqual(await self.writer.unknown_creates(), ())

    async def test_incomplete_venue_listing_never_proves_absence(self):
        runtime = await self.runtime()  # Fixture listing is not marked complete.
        original = runtime.reads.read
        async def read(name, **kwargs):
            if name == 'cutoff':
                return ReadResult(dict(trades_created_ts=baseline.BOUNDARY.isoformat(),
                                       orders_updated_ts=baseline.BOUNDARY.isoformat()), 1)
            return await original(name, **kwargs)
        runtime.reads.read = read
        await self.unknown()
        self.advance(601)
        runtime.request_recovery()
        runtime.recovery_requested.clear()
        self.assertFalse(await runtime.recover_once())
        self.assertEqual(self.state('uncertain'), ('UNKNOWN', 'UNKNOWN'))

    async def test_unknown_create_found_at_the_venue_is_bound_not_rejected(self):
        runtime = await self.with_runtime()
        await self.unknown('found')
        runtime.reads.orders = (dict(order_id='order-found', client_order_id='found',
            ticker='A', book_side='bid', yes_price_dollars='.01', initial_count_fp='10',
            fill_count_fp='0', remaining_count_fp='10', status='resting', subaccount=0,
            exchange_index=1, last_update_time='1970-01-01T00:00:00.000001Z'),)
        self.advance(601)
        runtime.request_recovery()
        runtime.recovery_requested.clear()
        await runtime.recover_once()
        intent, phase = self.state('found')
        self.assertNotEqual(intent, 'REJECTED')
        self.assertEqual(await self.writer.unknown_creates(), ())  # Bound to venue evidence.

    async def test_writer_preconditions_fail_closed(self):
        await self.runtime()  # A proven account can reserve an entry.
        await self.unknown('young')
        await self.writer.close()
        with closing(Ledger(self.path)) as ledger:
            (attempt, client, ticker, created), = unknown_creates(ledger)
            with ledger.transaction():
                self.assertFalse(resolve_unknown_create_absent(ledger, attempt,
                    evidence_digest='e', now=self.now+timedelta(seconds=10)))  # too young
            ledger.connection.execute(
                "INSERT INTO pending_fills VALUES ('p','{\"ticker\":\"A\"}',0,0,1,?)",
                (self.now.isoformat(),))
            with ledger.transaction():
                self.assertFalse(resolve_unknown_create_absent(ledger, attempt,
                    evidence_digest='e', now=self.now+timedelta(seconds=700)))  # fill pending
            ledger.connection.execute("DELETE FROM pending_fills")
            with ledger.transaction():
                self.assertTrue(resolve_unknown_create_absent(ledger, attempt,
                    evidence_digest='e', now=self.now+timedelta(seconds=700)))
                self.assertFalse(resolve_unknown_create_absent(ledger, attempt,
                    evidence_digest='e', now=self.now+timedelta(seconds=700)))  # once only
        self.writer = await baseline.LedgerWriter(self.path).start()


class LiveGateSizeTests(unittest.TestCase):
    def pair(self, count):
        from tests.test_bot_command_handoff import request
        return tuple(dict(request(c), ticker='A', count=count, side=s,
                          price='0.4' if s == 'bid' else '0.6')
                     for c, s in (('b', 'bid'), ('a', 'ask')))

    def test_real_live_session_gate_uses_active_size(self):
        # The gate that refused the first 30-contract pair in production.
        import kalshi_bot.config as bot_config
        from types import SimpleNamespace
        from kalshi_bot.config import BotConfig
        from kalshi_bot.live_session import LiveSession
        from kalshi_bot.values import InvalidData
        self.addCleanup(setattr, bot_config, '_ACTIVE', bot_config._ACTIVE)
        session = LiveSession(run_id='run', tickers=('A',))
        session.bind(SimpleNamespace(failed=False))
        bot_config.activate(BotConfig(capital_usd=D(780), entry_contracts=D(30),
                                      managed_market_slots=16))
        session.check('batch_create', self.pair('30.00'))
        with self.assertRaises(InvalidData):
            session.check('batch_create', self.pair('10.00'))
        bot_config._ACTIVE = None
        session.check('batch_create', self.pair('10.00'))

    def test_live_entry_gate_follows_the_active_approved_size(self):
        import kalshi_bot.config as bot_config
        from kalshi_bot.config import BotConfig, APPROVED_MONEY
        self.addCleanup(setattr, bot_config, '_ACTIVE', bot_config._ACTIVE)
        bot_config.activate(BotConfig(capital_usd=D(780), entry_contracts=D(30),
                                      managed_market_slots=16))
        self.assertIn((D(780), D(30), D(25)), APPROVED_MONEY)
        self.assertEqual(bot_config.active().entry_contracts, D(30))


if __name__ == '__main__':
    unittest.main()
