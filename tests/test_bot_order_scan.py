"""Bulk order settlement scan equals the per-order path; offline ledgers only."""
from decimal import Decimal as D
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot import orders
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.values import InvalidData
from kalshi_bot.command_capacity import CapacityPolicy
from tests import test_bot_command_archive as archive
from tests.test_bot_command_archive import NOW


def receipts(values):
    return [(r.order, r.owned, r.applied, r.awaiting_fills, r.intent_state, r.reducing)
            for r in values]


def tables(path):
    connection = sqlite3.connect(path)
    try:
        return [connection.execute(f'SELECT * FROM {name} ORDER BY rowid').fetchall()
                for name in ('intents', 'command_credits', 'command_episodes')]
    finally:
        connection.close()


class OrderScanTests(unittest.IsolatedAsyncioTestCase):
    base = archive.TerminalEpisodeArchiveTests
    asyncSetUp, asyncTearDown = base.asyncSetUp, base.asyncTearDown
    start, stop, reserve, cycle = base.start, base.stop, base.reserve, base.cycle

    async def test_bulk_scan_matches_per_order_results_and_effects(self):
        await self.start(CapacityPolicy(entry_mutation_limit=64, mutation_limit=256,
                                        intent_limit=64, order_limit=64))
        for index in range(3):
            await self.cycle(f'done-{index}', ticker=f'T{index}')
        prepared = await self.reserve('open', ticker='OPEN')
        await self.writer.begin_send(prepared.receipt)
        await self.writer.record_outcome('ack', prepared.receipt, dict(order_id='order-open',
            client_order_id='open', fill_count='0', remaining_count='10', ts_ms=1), NOW)
        await self.writer.order(OrderUpdate('order-open', 'open', 'OPEN', 'bid', D('.4'),
            D(10), D(0), D(10), 'resting', 0, 1, 1), NOW)
        await self.stop()
        # One settled order whose cleanup has not run yet: settlement must
        # still release its held credits in the bulk scan.
        connection = sqlite3.connect(self.path)
        with connection:
            connection.execute("UPDATE intents SET state='ACKNOWLEDGED' WHERE client_id='done-0'")
            connection.execute("UPDATE command_episodes SET state='ACTIVE' WHERE id IN "
                "(SELECT episode_id FROM command_credits WHERE owner_id='done-0')")
        connection.close()
        bulk, single = (Path(self.temp.name)/name for name in ('bulk.db', 'single.db'))
        for target in (bulk, single):
            shutil.copyfile(self.path, target)
        results = []
        for target, run in ((bulk, lambda ledger, ids: orders.settle_orders(ledger, ids)),
                            (single, lambda ledger, ids: tuple(
                                orders._settle_order(ledger, i) for i in ids))):
            ledger = Ledger(target)
            ids = [r[0] for r in ledger.connection.execute('SELECT order_id FROM order_evidence')]
            with ledger.transaction():
                results.append(receipts(run(ledger, ids)))
            ledger.connection.close()
        self.assertEqual(len(results[0]), 4)
        self.assertEqual(results[0], results[1])
        self.assertEqual(tables(bulk), tables(single))
        self.assertEqual([row[2] for row in tables(bulk)[0] if row[0] == 'done-0'], ['TERMINAL'])
        self.assertEqual([row[3] for row in tables(bulk)[2] if row[2] == 'T0'], ['RETIRED'])

    def test_decode_reuses_validated_value_and_still_rejects_invalid_text(self):
        update = OrderUpdate('o', 'c', 'A', 'bid', D('.4'), D(10), D(0), D(10), 'resting', 0, 1, 1)
        text = update.encode()
        self.assertIs(OrderUpdate.decode(text), OrderUpdate.decode(text))
        self.assertEqual(OrderUpdate.decode(text), update)
        bad = text.replace('"resting"', '"lost"')
        for _ in range(2):  # A failure is never cached as a value.
            with self.assertRaises(InvalidData):
                OrderUpdate.decode(bad)

    def test_decode_cache_is_bounded(self):
        saved = orders._DECODED_LIMIT
        orders._DECODED.clear()
        orders._DECODED_LIMIT = 3
        try:
            for index in range(10):
                OrderUpdate.decode(OrderUpdate(f'o{index}', 'c', 'A', 'bid', D('.4'), D(10),
                    D(0), D(10), 'resting', 0, 1, 1).encode())
                self.assertLessEqual(len(orders._DECODED), 3)
        finally:
            orders._DECODED_LIMIT = saved
            orders._DECODED.clear()

    def test_bulk_filled_totals_equal_per_order_totals(self):
        ledger = Ledger(Path(self.temp.name)/'fills.db')
        try:
            for trade, order, quantity in (('t1', 'a', '3'), ('t2', 'a', '2.5'), ('t3', 'b', '1')):
                ledger.record_fill(Fill(trade, order, 'A', 'bid', D(quantity), D('.4'), D(0)), NOW)
            totals = ledger.filled_quantities()
            self.assertEqual(totals, {o: ledger.filled_quantity(o) for o in ('a', 'b')})
            self.assertEqual(totals['a'], D('5.5'))
            self.assertNotIn('c', totals)
            self.assertEqual(ledger.filled_quantity('c'), D(0))
        finally:
            ledger.connection.close()


if __name__ == '__main__':
    unittest.main()
