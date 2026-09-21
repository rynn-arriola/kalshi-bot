"""Archived-order recovery checks; injected reads and temporary ledgers only."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalshi_bot.account import AccountCoordinator
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate, timestamp_us
from kalshi_bot.recovery import HistoricalFill, HistoryEvidence, fetch_archived_orders, stage_history
from kalshi_bot.rest import PageSet, ReadFailure, ReadResult, RestReads, TokenBudget, WireResponse, request_path
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter

NOW = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)


def row(**kwargs):
    return dict(order_id="o", client_order_id="c", ticker="A", book_side="bid",
                yes_price_dollars="0.5", initial_count_fp="10", fill_count_fp="0",
                remaining_count_fp="0", status="canceled", subaccount_number=0,
                exchange_index=0, last_update_time=(NOW-timedelta(days=2)).isoformat()) | kwargs


def intent(**kwargs):
    return dict(ticker="A", side="bid", price="0.5", count="10", subaccount=0,
                exchange_index=0, reduce_only=False) | kwargs


class Reads:
    def __init__(self, rows=(), *, status=404, changed=False):
        self.rows = tuple(rows)
        self.status, self.changed = status, changed
        self.calls, self.cutoffs = [], 0
        self.hook = None

    async def read(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if name == "order":
            if self.status != 200:
                raise ReadFailure(self.status)
            return ReadResult({"order": row()}, 100)
        self.cutoffs += 1
        cutoff = NOW-timedelta(days=1)
        if self.changed and self.cutoffs > 1:
            cutoff += timedelta(seconds=1)
        return ReadResult({"orders_updated_ts": cutoff.isoformat()}, 100)

    async def collect(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.hook:
            self.hook()
        return PageSet(self.rows, 1, 100)


class ArchiveFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_bound_endpoint_and_no_unsupported_account_filter(self):
        spec, path = request_path("historical_orders", {"ticker": "A"}, "history")
        self.assertTrue(spec.authenticated)
        self.assertEqual(path, "/historical/orders?ticker=A")
        for params in ({"subaccount": 0}, {"order_id": "o"}, {"exchange_index": 0}, {"status": "canceled"}):
            with self.assertRaises(InvalidData):
                request_path("historical_orders", params, "history")

    async def test_valid_terminal_scope_and_duplicate_dedup(self):
        reads = Reads([row(), row(), row(order_id="other", subaccount_number=1)])
        result = await fetch_archived_orders(reads, subaccount=0, ticker="A")
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(result.excluded_other_accounts, 1)
        self.assertEqual(reads.cutoffs, 2)
        self.assertNotIn("subaccount", reads.calls[1][1])
        self.assertNotIn("min_ts", reads.calls[1][1])

    async def test_missing_scope_is_not_assumed_primary(self):
        for scope in (None, True, -1, 64):
            with self.subTest(scope=scope), self.assertRaises(InvalidData):
                await fetch_archived_orders(Reads([row(subaccount_number=scope)]), subaccount=0)

    async def test_active_or_wrong_ticker_rejected(self):
        for changes in ({"status": "resting", "remaining_count_fp": "10"}, {"ticker": "B"}):
            with self.assertRaises(InvalidData):
                await fetch_archived_orders(Reads([row(**changes)]), subaccount=0, ticker="A")

    async def test_duplicate_economic_conflict_rejected(self):
        with self.assertRaisesRegex(InvalidData, "duplicate"):
            await fetch_archived_orders(Reads([row(), row(yes_price_dollars="0.6")]), subaccount=0)

    async def test_cutoff_change_rejects_even_empty_enumeration(self):
        with self.assertRaisesRegex(InvalidData, "cutoff moved"):
            await fetch_archived_orders(Reads(changed=True), subaccount=0)

    async def test_missing_cutoff_rejected(self):
        class NoCutoff(Reads):
            async def read(self, *args, **kwargs):
                return ReadResult({}, 10)
        with self.assertRaisesRegex(InvalidData, "cutoff"):
            await fetch_archived_orders(NoCutoff(), subaccount=0)

    async def test_resource_limits_not_partial_success(self):
        for kwargs in ({"max_rows": 1}, {"max_bytes": 1}):
            with self.assertRaises(InvalidData):
                await fetch_archived_orders(Reads([row(), row(order_id="o2")]), subaccount=0, **kwargs)

    async def test_normalization_yields_in_bounded_chunks(self):
        rows = [row(order_id=str(i)) for i in range(100)]
        with patch("kalshi_bot.recovery.asyncio.sleep", wraps=asyncio.sleep) as sleep:
            await fetch_archived_orders(Reads(rows), subaccount=0)
        self.assertEqual(sleep.await_count, 3)

    async def test_cursor_required_and_pagination_exhausted(self):
        class Signer:
            def headers(self, *args):
                return {}
        for missing in (True, False):
            calls = []
            def wire(url, *_):
                calls.append(url)
                data = {"orders": [row(order_id=str(len(calls)))]}
                if not missing:
                    data["cursor"] = "next" if len(calls) == 1 else ""
                return WireResponse(200, json.dumps(data).encode())
            reads = RestReads(TokenBudget(rate=1000, capacity=1000, default_cost=1), Signer(), wire=wire)
            try:
                if missing:
                    with self.assertRaisesRegex(InvalidData, "cursor missing"):
                        await reads.collect("historical_orders", reason="history")
                else:
                    result = await reads.collect("historical_orders", reason="history")
                    self.assertEqual((result.pages, len(result.rows)), (2, 2))
                    self.assertIn("cursor=next", calls[1])
            finally:
                await reads.close()


class ArchiveOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"ledger.db"
        self.writer = await LedgerWriter(self.path).start()
        self.owner = AccountCoordinator(self.writer, subaccount=0)
        self.owner.connect_generation()
        await self.writer.reserve_intent("c", intent(), NOW-timedelta(days=3))
        await self.writer.transition_intent("c", "SENDING")

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def bind(self):
        await self.writer.order(OrderUpdate("o", "c", "A", "bid", D("0.5"), D(10), D(0),
            D(10), "resting", 0, 0, timestamp_us((NOW-timedelta(days=3)).isoformat())), NOW)

    async def test_archive_binds_unknown_send_only_by_exact_intent(self):
        report = await self.owner.recover_archived_orders(Reads([row()]), now=lambda: NOW)
        self.assertEqual((report.seen, report.owned, report.foreign), (1, 1, 0))
        self.assertFalse(report.ready_for_entry)
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 0)
        self.assertEqual(self.owner.order_states["o"].intent_state, "TERMINAL")

    async def test_terminal_with_missing_fills_keeps_reservation(self):
        report = await self.owner.recover_archived_orders(
            Reads([row(status="executed", fill_count_fp="10")]), now=lambda: NOW)
        self.assertEqual(report.awaiting_fill_order_ids, ("o",))
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_other_clients_cannot_bind_or_change_inventory(self):
        report = await self.owner.recover_archived_orders(Reads([row(client_order_id="foreign")]), now=lambda: NOW)
        self.assertEqual((report.owned, report.foreign), (0, 1))
        self.assertEqual(await self.writer.orders(), ())
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_conflicting_owned_terms_roll_back_and_poison_writer(self):
        with self.assertRaises(InvalidData):
            await self.owner.recover_archived_orders(Reads([row(yes_price_dollars="0.8")]), now=lambda: NOW)
        self.assertTrue(self.writer.failed)
        self.assertIsNone(self.owner.archive_report)

    async def test_archive_absence_never_releases_intent(self):
        report = await self.owner.recover_archived_orders(Reads(), now=lambda: NOW)
        self.assertEqual(report.seen, 0)
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_404_falls_back_only_for_known_order_and_exact_ticker(self):
        await self.bind()
        reads = Reads([row()])
        receipt = await self.owner.recover_order(reads, "o", now=lambda: NOW)
        self.assertEqual(receipt.intent_state, "TERMINAL")
        archive_call = next(p for name, p in reads.calls if name == "historical_orders")
        self.assertEqual(archive_call["ticker"], "A")

    async def test_404_unknown_order_does_not_scan_arbitrary_archive(self):
        reads = Reads([row()])
        with self.assertRaises(ReadFailure):
            await self.owner.recover_order(reads, "unbound", now=lambda: NOW)
        self.assertEqual([n for n, _ in reads.calls], ["order"])

    async def test_401_and_timeout_do_not_trigger_archive_fallback(self):
        await self.bind()
        for status in (401, 403, 429, 503):
            reads = Reads([row()], status=status)
            with self.assertRaises(ReadFailure):
                await self.owner.recover_order(reads, "o", now=lambda: NOW)
            self.assertEqual([n for n, _ in reads.calls], ["order"])
        class Timeout(Reads):
            async def read(self, name, **kwargs):
                self.calls.append((name, kwargs))
                raise InvalidData("read transport failed; no proof obtained")
        reads = Timeout()
        with self.assertRaises(InvalidData):
            await self.owner.recover_order(reads, "o", now=lambda: NOW)
        self.assertEqual([n for n, _ in reads.calls], ["order"])

    async def test_404_then_archive_absence_stays_unresolved(self):
        await self.bind()
        with self.assertRaisesRegex(InvalidData, "absent from archive"):
            await self.owner.recover_order(Reads(), "o", now=lambda: NOW)
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_fresh_direct_response_does_not_read_archive(self):
        await self.bind()
        reads = Reads(status=200)
        await self.owner.recover_order(reads, "o", now=lambda: NOW)
        self.assertEqual([n for n, _ in reads.calls], ["order"])

    async def test_disconnect_during_archive_fetch_discards_result(self):
        reads = Reads([row()])
        reads.hook = self.owner.disconnect
        self.assertIsNone(await self.owner.recover_archived_orders(reads, now=lambda: NOW))
        self.assertEqual(await self.writer.orders(), ())
        self.assertIsNone(self.owner.archive_report)

    async def test_superseding_generation_discards_404_fallback(self):
        await self.bind()
        reads = Reads([row()])
        reads.hook = self.owner.connect_generation
        self.assertIsNone(await self.owner.recover_order(reads, "o", now=lambda: NOW))
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_archive_proof_invalidated_by_later_private_event(self):
        await self.owner.recover_archived_orders(Reads([row()]), now=lambda: NOW)
        await self.owner.on_event({"type": "order_group_updates", "msg": {}},
                                  generation=self.owner.generation, received_at=NOW)
        self.assertIsNone(self.owner.archive_report)

    async def test_terminal_proof_persists_across_restart(self):
        await self.owner.recover_archived_orders(Reads([row()]), now=lambda: NOW)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual((await self.writer.orders())[0].intent_state, "TERMINAL")

    async def test_archive_batches_bounded_and_incomplete_run_never_publishes(self):
        rows = [row(order_id=str(i), client_order_id="foreign-"+str(i)) for i in range(65)]
        original = self.writer.order_batch
        sizes = []
        async def batch(updates, now):
            sizes.append(len(updates))
            result = await original(updates, now)
            if len(sizes) == 2:
                self.owner.disconnect()
            return result
        with patch.object(self.writer, "order_batch", side_effect=batch):
            self.assertIsNone(await self.owner.recover_archived_orders(Reads(rows), now=lambda: NOW))
        self.assertEqual(sizes, [32, 32])
        self.assertIsNone(self.owner.archive_report)

    async def test_stale_archive_token_never_binds(self):
        ticks = [0.0]
        self.owner.clock = lambda: ticks[0]
        reads = Reads([row()])
        reads.hook = lambda: ticks.__setitem__(0, 6.0)
        self.assertIsNone(await self.owner.recover_archived_orders(reads, now=lambda: NOW))
        self.assertEqual(await self.writer.orders(), ())

    async def test_new_reconciliation_clears_previous_archive_report(self):
        await self.owner.recover_archived_orders(Reads([row()]), now=lambda: NOW)
        self.assertIsNotNone(self.owner.archive_report)
        self.owner.begin_reconciliation(NOW)
        self.assertIsNone(self.owner.archive_report)


class HistoryTimestampAuditTests(unittest.TestCase):
    def test_conflicting_execution_time_cannot_enter_staging(self):
        with TemporaryDirectory() as temp:
            db = Ledger(Path(temp)/"ledger.db")
            try:
                ts = timestamp_us(NOW.isoformat())
                f = Fill("t", "o", "A", "bid", D(10), D("0.5"), D("0.01"), ts)
                db.record_fill(f, NOW)
                changed = replace(f, executed_us=ts+1)
                evidence = HistoryEvidence(ts-1, ts+1000, ts, 0,
                    (HistoricalFill(changed, ts+1, 0, 0),), 1, 0)
                with self.assertRaisesRegex(InvalidData, "execution time conflicts"):
                    stage_history(db, evidence, NOW)
                self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM recovery_fills").fetchone()[0], 0)
                self.assertEqual(db.position("A"), 10)
            finally:
                db.close()

    def test_finer_compatible_time_can_be_staged_without_reaccounting(self):
        db = Ledger(":memory:")
        try:
            ts = timestamp_us(NOW.isoformat())
            f = Fill("t", "o", "A", "bid", D(10), D("0.5"), D("0.01"), ts, 1000)
            db.record_fill(f, NOW)
            finer = replace(f, executed_us=ts+123, execution_precision_us=1)
            evidence = HistoryEvidence(ts-1, ts+1000, ts, 0,
                (HistoricalFill(finer, ts+123, 0, 0),), 1, 0)
            self.assertEqual(stage_history(db, evidence, NOW).already_recorded, 1)
            self.assertEqual(db.realized(NOW, NOW+timedelta(seconds=1)), D("-0.01"))
        finally:
            db.close()
