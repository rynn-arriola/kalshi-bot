"""D-059 bounded command-capacity regressions; disposable offline ledgers only."""
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.command_capacity import CapacityPolicy
from kalshi_bot.config import BotConfig
from kalshi_bot.ledger import Ledger
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def request(client="client", ticker="A"):
    return dict(ticker=ticker, client_order_id=client, side="bid", count="10",
        price="0.4", time_in_force="good_till_canceled",
        self_trade_prevention_type="taker_at_cross", post_only=True,
        reduce_only=False, cancel_order_on_pause=True, subaccount=0,
        exchange_index=1)


class CommandCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"commands.db"
        self.writer = None

    async def asyncTearDown(self):
        if self.writer is not None:
            await self.writer.close()
        self.temp.cleanup()

    async def start(self, policy=None):
        self.writer = await LedgerWriter(
            self.path, command_policy=policy or CapacityPolicy()).start()

    async def reserve(self, client="client"):
        req = request(client)
        return await self.writer.reserve_entry(req, attempt_id="create-"+client,
            view=await self.writer.portfolio(subaccount=0, now=NOW),
            config=BotConfig(managed_market_slots=30), now=NOW,
            free_cash=D(500), account_known=True, offline_fixture=True)

    async def make_working(self, client="client", order_id="order"):
        prepared = await self.reserve(client)
        self.assertTrue(prepared.reserved, prepared.blockers)
        sent = await self.writer.begin_send(prepared.receipt)
        self.assertTrue(sent.dispatch_allowed)
        await self.writer.record_outcome("ack", prepared.receipt,
            dict(order_id=order_id, client_order_id=client, fill_count="0",
                 remaining_count="10", ts_ms=1), NOW)
        await self.writer.order(OrderUpdate(order_id, client, "A", "bid", D(".4"),
            D(10), D(0), D(10), "resting", 0, 1, 1), NOW)

    async def test_tiny_policy_entry_boundary_denies_without_poisoning_writer(self):
        policy = CapacityPolicy(entry_mutation_limit=2, mutation_limit=16,
                                intent_limit=8, order_limit=8)
        await self.start(policy)
        self.assertTrue((await self.reserve("one")).reserved)
        self.assertTrue((await self.reserve("two")).reserved)
        denied = await self.reserve("three")
        self.assertEqual(denied.blockers, ("capacity_entries_held",))
        self.assertFalse(self.writer.failed)
        self.assertEqual((await self.writer.command_capacity()).mutation_used, 2)

    async def test_proven_unsent_entries_archive_at_boundary_and_admission_continues(self):
        policy = CapacityPolicy(entry_mutation_limit=2, mutation_limit=16,
                                intent_limit=8, order_limit=8)
        await self.start(policy)
        for client in ('one', 'two'):
            prepared = await self.reserve(client)
            self.assertTrue(prepared.reserved, prepared.blockers)
            await self.writer.abort_prepared(prepared.receipt)
        admitted = await self.reserve('three')
        self.assertTrue(admitted.reserved, admitted.blockers)
        self.assertEqual((await self.writer.command_capacity()).mutation_used, 1)
        await self.writer.close(); self.writer = None
        db = Ledger(self.path)
        try:
            archive = db.connection.execute(
                'SELECT attempt_count,intent_count,authorization_count '
                'FROM command_history_archives').fetchone()
            self.assertEqual(tuple(archive), (2, 2, 2))
            self.assertEqual(db.connection.execute(
                "SELECT COUNT(*) FROM intents WHERE state='ABORTED'").fetchone()[0], 0)
        finally:
            db.close()

    async def test_command_archive_tampering_blocks_startup(self):
        policy = CapacityPolicy(entry_mutation_limit=1, mutation_limit=16,
                                intent_limit=8, order_limit=8)
        await self.start(policy)
        prepared = await self.reserve('one')
        await self.writer.abort_prepared(prepared.receipt)
        self.assertTrue((await self.reserve('two')).reserved)
        await self.writer.close(); self.writer = None
        connection = __import__('sqlite3').connect(self.path)
        with connection:
            connection.execute("UPDATE command_history_archives SET payload=x'00'")
        connection.close()
        self.writer = LedgerWriter(self.path, command_policy=policy)
        with self.assertRaisesRegex(InvalidData, 'ledger startup failed'):
            await self.writer.start()

    async def test_proven_unsent_active_episode_is_not_archived(self):
        policy = CapacityPolicy(entry_mutation_limit=1, mutation_limit=16,
                                intent_limit=8, order_limit=8)
        await self.start(policy)
        prepared = await self.reserve('one')
        await self.writer.abort_prepared(prepared.receipt)
        await self.writer.close(); self.writer = None
        connection = __import__('sqlite3').connect(self.path)
        with connection:
            connection.execute("UPDATE command_episodes SET state='ACTIVE'")
        connection.close()
        await self.start(policy)
        denied = await self.reserve('two')
        self.assertEqual(denied.blockers, ('capacity_entries_held',))
        await self.writer.close(); self.writer = None
        db = Ledger(self.path)
        try:
            self.assertEqual(db.connection.execute(
                'SELECT COUNT(*) FROM command_history_archives').fetchone()[0], 0)
        finally:
            db.close()

    async def test_valid_cancel_prepares_at_real_4096_entry_highwater(self):
        await self.start()
        await self.make_working()
        await self.writer.close()
        self.writer = None
        db = Ledger(self.path)
        try:
            payload = json.dumps({"ticker": "A", "subaccount": 0}, separators=(",", ":"))
            stamp = NOW.isoformat()
            with db.transaction():
                db.connection.executemany(
                    "INSERT INTO mutation_attempts VALUES (?, 'create', ?, 'ACK', NULL, ?)",
                    ((f"history-{i}", payload, stamp) for i in range(4095)))
        finally:
            db.close()
        await self.start()
        evidence = await self.writer.cancel_evidence("order")
        prepared = await self.writer.prepare_cancel("cancel-order", dict(
            order_id="order", market_ticker="A", subaccount=0, exchange_index=1),
            evidence=evidence, now=NOW)
        self.assertTrue(prepared.reserved, prepared.blockers)
        self.assertEqual(prepared.capacity.mutation_used, 4097)
        denied = await self.reserve("new-entry")
        self.assertIn("capacity_entries_held", denied.blockers)
        self.assertFalse(self.writer.failed)

    async def test_held_cancel_converts_at_exact_hard_bound(self):
        await self.start()
        await self.make_working()
        await self.writer.close()
        self.writer = None
        db = Ledger(self.path)
        try:
            current = db.connection.execute(
                "SELECT COUNT(*) FROM mutation_attempts").fetchone()[0]
            held = db.connection.execute(
                "SELECT held FROM command_capacity_counters WHERE resource='mutation'").fetchone()[0]
            payload = json.dumps({"ticker": "A", "subaccount": 0}, separators=(",", ":"))
            with db.transaction():
                db.connection.executemany(
                    "INSERT INTO mutation_attempts VALUES (?, 'create', ?, 'ACK', NULL, ?)",
                    ((f"hard-{i}", payload, NOW.isoformat())
                     for i in range(8192-current-held)))
        finally:
            db.close()
        await self.start()
        before = await self.writer.command_capacity()
        self.assertEqual(before.mutation_used+before.mutation_held, 8192)
        prepared = await self.writer.prepare_cancel("hard-cancel", dict(
            order_id="order", market_ticker="A", subaccount=0, exchange_index=1),
            evidence=await self.writer.cancel_evidence("order"), now=NOW)
        self.assertTrue(prepared.reserved, prepared.blockers)
        self.assertEqual(prepared.capacity.mutation_used+prepared.capacity.mutation_held, 8192)

    async def test_all_8192_mutations_are_read_not_truncated(self):
        db = Ledger(self.path)
        try:
            payload = json.dumps({"ticker": "A", "subaccount": 0}, separators=(",", ":"))
            with db.transaction():
                db.connection.executemany(
                    "INSERT INTO mutation_attempts VALUES (?, 'create', ?, 'ACK', NULL, ?)",
                    ((f"m-{i}", payload, NOW.isoformat()) for i in range(8192)))
        finally:
            db.close()
        await self.start()
        self.assertEqual(len(await self.writer.mutations()), 8192)
        inventory = await self.writer.market_inventory("A", subaccount=0)
        self.assertEqual(inventory.exit_journal.attempts, 0)

    async def test_missing_reserved_cancel_credit_fails_closed_without_dispatch_authority(self):
        await self.start()
        await self.make_working()
        await self.writer.close()
        self.writer = None
        db = Ledger(self.path)
        try:
            with db.transaction():
                changed = db.connection.execute(
                    "UPDATE command_credits SET state='RELEASED' WHERE owner_id='client' "
                    "AND purpose='cancel' AND state='HELD'").rowcount
                self.assertEqual(changed, 1)
                db.connection.execute("UPDATE command_capacity_counters SET held=held-1 "
                                      "WHERE resource='mutation'")
        finally:
            db.close()
        await self.start()
        result = await self.writer.prepare_cancel("unfunded-cancel", dict(
            order_id="order", market_ticker="A", subaccount=0, exchange_index=1),
            evidence=await self.writer.cancel_evidence("order"), now=NOW)
        self.assertEqual(result.blockers, ("cancel_capacity_unfunded",))
        self.assertFalse(self.writer.failed)

    async def test_proven_unsent_reauthorization_is_bounded(self):
        await self.start(CapacityPolicy(reauthorization_limit=2))
        await self.make_working()
        request = dict(order_id="order", market_ticker="A", subaccount=0,
                       exchange_index=1)
        first = await self.writer.prepare_cancel("cancel-one", request,
            evidence=await self.writer.cancel_evidence("order"), now=NOW)
        self.assertTrue(first.reserved, first.blockers)
        await self.writer.abort_prepared(first.receipt)
        second = await self.writer.prepare_cancel("cancel-two", request,
            evidence=await self.writer.cancel_evidence("order"), now=NOW)
        self.assertTrue(second.reserved, second.blockers)
        await self.writer.abort_prepared(second.receipt)
        denied = await self.writer.prepare_cancel("cancel-three", request,
            evidence=await self.writer.cancel_evidence("order"), now=NOW)
        self.assertEqual(denied.blockers, ("command_reauthorization_limit",))
        self.assertEqual((await self.writer.command_capacity()).mutation_used, 2)
        self.assertFalse(self.writer.failed)

    async def test_legacy_intent_path_cannot_overrun_configured_capacity(self):
        policy = CapacityPolicy(intent_limit=8, order_limit=8)
        await self.start(policy)
        self.assertTrue((await self.reserve('entry')).reserved)
        for i in range(3):
            await self.writer.reserve_intent(f'legacy-{i}', request(f'legacy-{i}'), NOW)
        with self.assertRaises(InvalidData):
            await self.writer.reserve_intent('legacy-overflow',
                                             request('legacy-overflow'), NOW)
        self.assertTrue(self.writer.failed)
        await self.writer.close(); self.writer = None
        db = Ledger(self.path)
        try:
            row = db.connection.execute(
                "SELECT used,held FROM command_capacity_counters "
                "WHERE resource='intent'").fetchone()
            self.assertEqual(row[0]+row[1], 8)
        finally:
            db.close()

    async def test_legacy_order_path_cannot_overrun_configured_capacity(self):
        policy = CapacityPolicy(intent_limit=16, order_limit=8)
        await self.start(policy)
        self.assertTrue((await self.reserve('entry')).reserved)
        for i in range(3):
            client = f'legacy-{i}'
            await self.writer.reserve_intent(client, request(client), NOW)
            await self.writer.transition_intent(client, 'SENDING')
            await self.writer.order(OrderUpdate(f'order-{i}', client, 'A', 'bid',
                D('.4'), D(10), D(0), D(10), 'resting', 0, 1, i+1), NOW)
        client = 'legacy-overflow'
        await self.writer.reserve_intent(client, request(client), NOW)
        await self.writer.transition_intent(client, 'SENDING')
        with self.assertRaises(InvalidData):
            await self.writer.order(OrderUpdate('order-overflow', client, 'A',
                'bid', D('.4'), D(10), D(0), D(10), 'resting', 0, 1, 9), NOW)
        self.assertTrue(self.writer.failed)
        await self.writer.close(); self.writer = None
        db = Ledger(self.path)
        try:
            row = db.connection.execute(
                "SELECT used,held FROM command_capacity_counters "
                "WHERE resource='order'").fetchone()
            self.assertEqual(row[0]+row[1], 8)
        finally:
            db.close()

    async def test_counter_credit_mismatch_blocks_startup(self):
        db = Ledger(self.path)
        try:
            with db.transaction():
                db.connection.execute("UPDATE command_capacity_counters SET held=1 "
                                      "WHERE resource='mutation'")
        finally:
            db.close()
        self.writer = LedgerWriter(self.path)
        with self.assertRaises(InvalidData):
            await self.writer.start()

    async def test_orphan_credit_blocks_startup(self):
        db = Ledger(self.path)
        try:
            with db.transaction():
                db.connection.execute("INSERT INTO command_credits VALUES "
                    "('credit','missing','mutation','cancel','client','RELEASED',?)",
                    (NOW.isoformat(),))
        finally:
            db.close()
        self.writer = LedgerWriter(self.path)
        with self.assertRaises(InvalidData):
            await self.writer.start()


if __name__ == "__main__":
    unittest.main()
