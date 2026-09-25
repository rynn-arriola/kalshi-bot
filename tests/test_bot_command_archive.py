"""D-129 terminal-episode command archival; disposable offline ledgers only."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from kalshi_bot import command_capacity
from kalshi_bot.command_capacity import CapacityPolicy
from kalshi_bot.config import BotConfig
from kalshi_bot.ledger import Ledger
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
LATER = NOW+timedelta(hours=1)
POLICY = CapacityPolicy(entry_mutation_limit=4, mutation_limit=64,
                        intent_limit=32, order_limit=32)


def request(client, ticker='A'):
    return dict(ticker=ticker, client_order_id=client, side='bid', count='10',
        price='0.4', time_in_force='good_till_canceled',
        self_trade_prevention_type='taker_at_cross', post_only=True,
        reduce_only=False, cancel_order_on_pause=True, subaccount=0,
        exchange_index=1)


class TerminalEpisodeArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'commands.db'
        self.writer = None

    async def asyncTearDown(self):
        if self.writer is not None:
            await self.writer.close()
        self.temp.cleanup()

    async def start(self, policy=POLICY):
        self.writer = await LedgerWriter(self.path, command_policy=policy).start()

    async def stop(self):
        await self.writer.close()
        self.writer = None

    async def reserve(self, client, now=NOW, ticker='A'):
        return await self.writer.reserve_entry(request(client, ticker),
            attempt_id='create-'+client,
            view=await self.writer.portfolio(subaccount=0, now=now),
            config=BotConfig(managed_market_slots=30), now=now,
            free_cash=D(500), account_known=True, offline_fixture=True)

    async def cycle(self, client, *, ticker='A', at=NOW):
        """Create, acknowledge, cancel and terminally prove one entry order."""
        order_id = 'order-'+client
        prepared = await self.reserve(client, ticker=ticker, now=at)
        self.assertTrue(prepared.reserved, prepared.blockers)
        self.assertTrue((await self.writer.begin_send(prepared.receipt)).dispatch_allowed)
        await self.writer.record_outcome('ack', prepared.receipt, dict(
            order_id=order_id, client_order_id=client, fill_count='0',
            remaining_count='10', ts_ms=1), at)
        await self.writer.order(OrderUpdate(order_id, client, ticker, 'bid', D('.4'),
            D(10), D(0), D(10), 'resting', 0, 1, 1), at)
        evidence = await self.writer.cancel_evidence(order_id)
        cancel = await self.writer.prepare_cancel('cancel-'+client, dict(
            order_id=order_id, market_ticker=ticker, subaccount=0, exchange_index=1),
            evidence=evidence, now=at)
        self.assertTrue(cancel.reserved, cancel.blockers)
        self.assertTrue((await self.writer.begin_send(cancel.receipt)).dispatch_allowed)
        await self.writer.record_outcome('ack', cancel.receipt, dict(
            order_id=order_id, ts_ms=2, reduced_by='10'), at)
        await self.writer.order(OrderUpdate(order_id, client, ticker, 'bid', D('.4'),
            D(10), D(0), D(0), 'canceled', 0, 1, 2), at)

    def db(self):
        return Ledger(self.path)

    def count(self, sql):
        db = self.db()
        try:
            return db.connection.execute(sql).fetchone()[0]
        finally:
            db.close()

    async def test_terminal_zero_fill_episodes_archive_and_entries_continue(self):
        await self.start()
        await self.cycle('one')
        await self.cycle('two')
        before = await self.writer.command_capacity()
        self.assertEqual(before.mutation_used, 4)  # Old behavior: blocked here.
        admitted = await self.reserve('three', now=LATER)
        self.assertTrue(admitted.reserved, admitted.blockers)
        after = await self.writer.command_capacity()
        self.assertEqual((after.mutation_used, after.intent_used, after.order_used), (1, 1, 0))
        await self.stop()
        self.assertEqual(self.count("SELECT COUNT(*) FROM command_episodes "
                                    "WHERE ticker='A' AND state<>'ACTIVE'"), 0)
        self.assertEqual(self.count('SELECT COUNT(*) FROM order_evidence'), 0)
        # A cold start revalidates exact archive digests and hot disjointness.
        await self.start()
        self.assertFalse(self.writer.failed)

    async def test_quiet_window_keeps_recent_episode_hot(self):
        await self.start()
        await self.cycle('one')
        await self.cycle('two')
        denied = await self.reserve('three', now=NOW+timedelta(minutes=5))
        self.assertEqual(denied.blockers, ('capacity_entries_held',))
        self.assertFalse(self.writer.failed)
        self.assertEqual((await self.writer.command_capacity()).mutation_used, 4)

    async def test_episode_with_fills_is_never_archived(self):
        await self.start()
        await self.cycle('one')
        await self.cycle('two', ticker='B')
        await self.stop()
        # Any retained execution evidence for an order keeps its episode hot.
        connection = sqlite3.connect(self.path)
        with connection:
            connection.execute("INSERT INTO recovery_fills VALUES (?,?,?,?,?,?)",
                ('["order-one","trade"]', '[]', 1, 0, 1, NOW.isoformat()))
        connection.close()
        await self.start()
        admitted = await self.reserve('three', now=LATER, ticker='C')
        self.assertTrue(admitted.reserved, admitted.blockers)
        await self.stop()
        self.assertEqual(self.count("SELECT COUNT(*) FROM order_evidence "
                                    "WHERE order_id='order-one'"), 1)
        self.assertEqual(self.count("SELECT COUNT(*) FROM order_evidence "
                                    "WHERE order_id='order-two'"), 0)
        await self.start()
        self.assertFalse(self.writer.failed)

    async def test_below_pressure_nothing_is_archived(self):
        await self.start(CapacityPolicy())
        await self.cycle('one')
        self.assertTrue((await self.reserve('two', now=LATER)).reserved)
        await self.stop()
        self.assertEqual(self.count('SELECT COUNT(*) FROM command_history_archives'), 0)

    async def test_tampered_episode_archive_blocks_startup(self):
        await self.start()
        await self.cycle('one')
        await self.cycle('two')
        self.assertTrue((await self.reserve('three', now=LATER)).reserved)
        await self.stop()
        connection = sqlite3.connect(self.path)
        with connection:
            # Restoring an archived episode row to the hot table must fail closed.
            archive = connection.execute("SELECT payload FROM command_history_archives").fetchone()[0]
            import json as _json, zlib as _zlib
            episode = _json.loads(_zlib.decompress(archive))['episodes'][0]['episode']
            connection.execute("INSERT INTO command_episodes VALUES (?,?,?,'RETIRED',?)",
                (episode['id'], episode['subaccount'], episode['ticker'], episode['created_at']))
        connection.close()
        self.writer = LedgerWriter(self.path, command_policy=POLICY)
        with self.assertRaisesRegex(InvalidData, 'ledger startup failed'):
            await self.writer.start()
        self.writer = None

    async def test_archived_rows_restored_to_hot_tables_block_startup(self):
        await self.start()
        await self.cycle('one')
        await self.cycle('two')
        self.assertTrue((await self.reserve('three', now=LATER)).reserved)
        await self.stop()
        connection = sqlite3.connect(self.path)
        with connection:
            connection.execute("INSERT INTO intents VALUES ('one','{}','TERMINAL',?)",
                               (NOW.isoformat(),))
        connection.close()
        self.writer = LedgerWriter(self.path, command_policy=POLICY)
        with self.assertRaisesRegex(InvalidData, 'ledger startup failed'):
            await self.writer.start()
        self.writer = None

    async def test_archive_table_rolls_into_hash_chain_instead_of_stopping(self):
        with mock.patch.object(command_capacity, 'MAX_ARCHIVES', 2), \
                mock.patch.object(command_capacity, 'ROLL_ARCHIVES', 1):
            await self.start()
            for index in range(4):
                at = NOW+timedelta(hours=index)
                for client in (f'{index}-a', f'{index}-b'):
                    await self.cycle(client, ticker=f'T{index}{client[-1]}', at=at)
                admitted = await self.reserve(f'{index}-entry',
                    now=at+timedelta(minutes=30), ticker=f'N{index}')
                self.assertTrue(admitted.reserved, admitted.blockers)
                await self.writer.abort_prepared(admitted.receipt)
            await self.stop()
            self.assertLessEqual(self.count('SELECT COUNT(*) FROM command_history_archives'), 2)
            self.assertEqual(self.count('SELECT COUNT(*) FROM command_archive_rollup'), 1)
            await self.start()
            self.assertFalse(self.writer.failed)
            await self.stop()
            connection = sqlite3.connect(self.path)
            with connection:
                connection.execute("UPDATE command_archive_rollup SET archive_count=archive_count+1")
            connection.close()
            self.writer = LedgerWriter(self.path, command_policy=POLICY)
            with self.assertRaisesRegex(InvalidData, 'ledger startup failed'):
                await self.writer.start()
            self.writer = None


    async def test_orphan_fee_bounds_are_swept_but_owned_bounds_kept(self):
        await self.start()
        await self.cycle('one')
        await self.stop()
        connection = sqlite3.connect(self.path)
        with connection:
            connection.executemany('INSERT INTO accounting_fees VALUES (?,?)',
                [('gone-'+str(i), '0.02') for i in range(10)] + [('one', '0.02')])
        connection.close()
        await self.start()
        await self.cycle('two')
        self.assertTrue((await self.reserve('three', now=LATER)).reserved)
        await self.stop()
        self.assertEqual(self.count("SELECT COUNT(*) FROM accounting_fees "
                                    "WHERE client_id LIKE 'gone-%'"), 0)
        await self.start()
        self.assertFalse(self.writer.failed)

    async def test_archival_failure_never_poisons_writer_or_admits_past_limits(self):
        from kalshi_bot.values import InvalidData as Invalid
        await self.start()
        await self.cycle('one')
        await self.cycle('two')
        state = dict(command_capacity._RECLAIM_STATE)
        try:
            with mock.patch.object(command_capacity, '_archive_terminal_episodes',
                                   side_effect=Invalid('synthetic archive fault')):
                denied = await self.reserve('three', now=LATER)
            self.assertEqual(denied.blockers, ('capacity_entries_held',))
            self.assertFalse(self.writer.failed)
            self.assertEqual(command_capacity.reclaim_failures(), state['failures']+1)
            # After the cooldown the next reservation archives normally.
            command_capacity._RECLAIM_STATE['retry_at'] = 0.0
            admitted = await self.reserve('four', now=LATER+timedelta(minutes=1))
            self.assertTrue(admitted.reserved, admitted.blockers)
        finally:
            command_capacity._RECLAIM_STATE.update(state)


class OrderProjectionTests(unittest.TestCase):
    def test_terminal_reconciled_orders_do_not_exhaust_projection(self):
        from kalshi_bot.account import AccountCoordinator
        from kalshi_bot.orders import OrderReceipt
        owner = AccountCoordinator(object(), subaccount=0)
        def receipt(index, status, filled=D(0), waiting=False):
            remaining = D(10) if status == 'resting' else D(0)
            order = OrderUpdate(f'o{index}', f'c{index}', 'A', 'bid', D('.4'), D(10),
                                filled, remaining, status, 0, 1, 1)
            return OrderReceipt(order, True, True, waiting, 'TERMINAL')
        for index in range(5000):
            owner._store_order(receipt(index, 'resting'))
            owner._store_order(receipt(index, 'canceled'))
        self.assertEqual(owner.order_states, {})
        # Fill-pending terminal and working orders remain visible and bounded.
        owner._store_order(receipt('w', 'resting'))
        owner._store_order(receipt('p', 'canceled', D(1), waiting=True))
        self.assertEqual(set(owner.order_states), {'ow', 'op'})


if __name__ == '__main__':
    unittest.main()
