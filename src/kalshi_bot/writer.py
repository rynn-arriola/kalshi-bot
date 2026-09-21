"""Bounded, one-thread SQLite owner. Accepted commands survive caller cancellation.

No trading/network actions. A failed command poisons this owner; restart and
reconcile instead of allowing later risk decisions to overtake a failed write.
"""
import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from queue import Full, Queue
from threading import Lock, Thread
from uuid import uuid4

from .ledger import Fill, Ledger
from .inbox import pending, stage
from .orders import OrderUpdate, record_order, settle_order
from .position_basis import VenueCost, exit_basis, observe_cost, observe_costs
from .recovery import HistoricalFill, HistoryAudit, HistoryEvidence, stage_history
from .risk import WindowRisk, WindowState
from .observability import NO_LOG
from .values import InvalidData, identity, integer, utc


@dataclass(frozen=True)
class FillReceipt:
    inserted: bool
    position: Decimal
    window: WindowState
    order: object | None = None


@dataclass(frozen=True)
class Inventory:
    positions: tuple[tuple[str, Decimal], ...]
    unresolved_intents: int


@dataclass(frozen=True)
class RecoveredChunk:
    receipts: tuple[FillReceipt, ...]
    unbound_fill_keys: tuple[str, ...]


class LedgerWriter:
    def __init__(self, path: Path | str, *, capacity: int = 256, market_capacity: int = 128,
                 diagnostics=NO_LOG):
        self.diagnostics = diagnostics
        self.path = path
        self.epoch = uuid4().hex
        self._revision = 0
        self.market_capacity = integer(market_capacity, 1, 1024)
        self._queue = Queue(maxsize=integer(capacity, 1, 8192))
        self._lock = Lock()
        self._closing = False
        self._failed = False
        self._started = False
        self._ready = Future()
        self._close_task = None
        self._thread = Thread(target=self._run, name="kalshi-ledger", daemon=False)

    @property
    def revision(self):
        return self._revision

    @property
    def failed(self):
        with self._lock:
            return self._failed

    @property
    def backlog(self):
        return self._queue.qsize()

    async def start(self):
        with self._lock:
            if self._started or self._closing:
                raise InvalidData("writer cannot be started twice or after close")
            self._started = True
            self._thread.start()
        try:
            await self._wait(self._ready)
        except BaseException:
            await self.close()
            raise
        return self

    @staticmethod
    async def _wait(future):
        wrapped = asyncio.wrap_future(future)
        # Consume exceptions even if the original caller stops awaiting.
        wrapped.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        return await asyncio.shield(wrapped)

    def _submit(self, command, *args):
        future = Future()
        with self._lock:
            if not self._started or self._closing or self._failed:
                raise InvalidData("ledger owner unavailable; reconciliation required")
            try:
                self._queue.put_nowait((command, args, future))
            except Full as exc:
                self._failed = True
                self.diagnostics.emit('writer_overflow', error=exc, backlog=self.backlog)
                raise InvalidData("ledger backlog exceeded; proof lost") from exc
        return future

    async def fill(self, fill: Fill, received_at: datetime) -> FillReceipt:
        if not isinstance(fill, Fill):
            raise InvalidData("validated Fill required")
        return await self._wait(self._submit("fill", fill, utc(received_at)))

    async def stage_fill(self, fill: Fill, *, owner: int, scope=None, exchange_index=None, now):
        return await self._wait(self._submit("stage_fill", fill, owner, scope, exchange_index, utc(now)))

    async def pending_fills(self, owner: int, order_id=None):
        return await self._wait(self._submit("pending_fills", integer(owner, 0, 63), order_id))

    async def apply_pending(self, key: str, *, owner: int, now):
        if not isinstance(key, str) or len(key) > 1024:
            raise InvalidData("invalid pending identity")
        return await self._wait(self._submit("apply_pending", key, integer(owner, 0, 63), utc(now)))

    async def observe(self, now: datetime) -> WindowState:
        return await self._wait(self._submit("observe", utc(now)))

    async def market_inventory(self, ticker, *, subaccount):
        return await self._wait(self._submit("market_inventory", identity(ticker), integer(subaccount, 0, 63)))

    async def portfolio(self, *, subaccount, now):
        return await self._wait(self._submit("portfolio", integer(subaccount, 0, 63), utc(now)))

    async def reserve_entry(self, request, *, view, config, now, free_cash,
                            account_known=False, offline_fixture=False):
        frozen = json.dumps(request, allow_nan=False, separators=(",", ":"))
        if len(frozen.encode()) > 16384:
            raise InvalidData("entry request exceeds byte budget")
        return await self._wait(self._submit("reserve_entry", frozen, view, config, utc(now),
                                            free_cash, account_known, offline_fixture))

    async def inventory(self) -> Inventory:
        return await self._wait(self._submit("inventory"))

    async def reconcile_snapshot(self, snapshot, *, now):
        from .account import Snapshot
        if (not isinstance(snapshot, Snapshot) or type(snapshot.orders) is not tuple
                or type(snapshot.positions) is not tuple or len(snapshot.orders) > 4096
                or len(snapshot.positions) > self.market_capacity):
            raise InvalidData("bounded immutable account snapshot required")
        return await self._wait(self._submit("reconcile_snapshot", snapshot, utc(now)))

    async def order(self, update: OrderUpdate, now: datetime):
        if not isinstance(update, OrderUpdate):
            raise InvalidData("validated order update required")
        return await self._wait(self._submit("order", update, utc(now)))

    async def orders(self):
        return await self._wait(self._submit("orders"))

    async def order_batch(self, updates: tuple[OrderUpdate, ...], now: datetime):
        if type(updates) is not tuple or not 1 <= len(updates) <= 32 or any(not isinstance(u, OrderUpdate) for u in updates):
            raise InvalidData("order evidence batch must contain 1 to 32 validated updates")
        return await self._wait(self._submit("order_batch", updates, utc(now)))

    async def fill_scope(self, order_id: str):
        return await self._wait(self._submit("fill_scope", identity(order_id)))

    async def order_evidence(self, order_id: str) -> OrderUpdate | None:
        return await self._wait(self._submit("order_evidence", identity(order_id)))

    async def recover_fills(self, records: tuple[HistoricalFill, ...], *, subaccount: int, now: datetime):
        if (type(records) is not tuple or not 1 <= len(records) <= 32
                or any(not isinstance(r, HistoricalFill) for r in records)):
            raise InvalidData("replay batch requires 1 to 32 immutable historical fills")
        return await self._wait(self._submit("recover_fills", records, integer(subaccount, 0, 63), utc(now)))

    async def venue_snapshot(self, observations: tuple[VenueCost, ...], *, subaccount: int, now: datetime):
        integer(subaccount, 0, 63)
        if (type(observations) is not tuple or len(observations) > self.market_capacity
                or any(not isinstance(o, VenueCost) or o.subaccount != subaccount for o in observations)
                or len({o.ticker for o in observations}) != len(observations)):
            raise InvalidData("bounded account-scoped venue cost snapshot required")
        return await self._wait(self._submit("venue_snapshot", observations, subaccount, utc(now)))

    async def stream_cost(self, ticker, quantity, cost, *, subaccount, now):
        from .values import decimal
        return await self._wait(self._submit("stream_cost", identity(ticker), decimal(quantity), decimal(cost),
                                            integer(subaccount, 0, 63), utc(now)))

    async def exit_basis(self, observation: VenueCost, now: datetime):
        if not isinstance(observation, VenueCost):
            raise InvalidData("validated venue cost required")
        return await self._wait(self._submit("exit_basis", observation, utc(now)))

    async def history_coverage(self, *, subaccount, start, end):
        from .orders import timestamp_us
        scope = integer(subaccount, 0, 63)
        start_us, end_us = timestamp_us(utc(start).isoformat()), timestamp_us(utc(end).isoformat())
        integer(end_us, start_us+1, 2**63-1)
        return await self._wait(self._submit('history_coverage', scope, start_us, end_us))

    async def audit_history(self, evidence: HistoryEvidence, now: datetime, *, read_started_at=None,
                            generation=None, source_revision=None):
        if not isinstance(evidence, HistoryEvidence) or len(evidence.records) > 10000:
            raise InvalidData("bounded history evidence required")
        # Evidence is not trading accounting: commit bounded chunks and yield
        # between them so fill/order commands can interleave. A partial run
        # never returns a completed audit and never changes lots/risk windows.
        now = utc(now)
        read_started_at = now if read_started_at is None else utc(read_started_at)
        if read_started_at > now or (generation is None) != (source_revision is None):
            raise InvalidData('invalid history clock/source provenance')
        if generation is not None:
            integer(generation, 1, 2**63-1)
            integer(source_revision, 0, 2**63-1)
        recorded, missing, blockers = 0, [], []
        for offset in range(0, max(1, len(evidence.records)), 256):
            chunk = replace(evidence, records=evidence.records[offset:offset+256])
            result = await self._wait(self._submit("history", chunk, now))
            recorded += result.already_recorded
            missing.extend(result.missing_fill_keys)
            for blocker in result.blockers:
                if blocker not in blockers:
                    blockers.append(blocker)
        receipt = await self._wait(self._submit('history_complete', evidence, uuid4().hex,
            read_started_at, now, generation, source_revision))
        if receipt.omitted_rows:
            blockers.append('previously_observed_fills_omitted')
            self.diagnostics.emit('history_omission', blocker_count=1)
        self.diagnostics.emit('history_enumerated', blocker_count=len(blockers))
        return HistoryAudit(len(evidence.records), recorded, tuple(missing), tuple(blockers), receipt)

    async def reserve_intent(self, client_id: str, payload: dict, now: datetime):
        identity(client_id)
        if not isinstance(payload, dict):
            raise InvalidData("intent payload must be an object")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 16384:
            raise InvalidData("intent payload exceeds byte budget")
        # Freeze caller-owned mutable data before submitting to another thread.
        return await self._wait(self._submit("reserve", client_id, encoded, utc(now)))

    async def transition_intent(self, client_id: str, target: str):
        identity(client_id)
        if target not in {"SENDING", "ABORTED", "UNKNOWN", "ACKNOWLEDGED", "REJECTED", "TERMINAL"}:
            raise InvalidData("unsupported intent state")
        return await self._wait(self._submit("transition", client_id, target))

    async def mutation(self, operation: str, attempt_id: str, document: dict, now: datetime):
        if operation not in {"prepare_create", "prepare_cancel", "sending", "unknown", "ack"}:
            raise InvalidData("invalid mutation journal operation")
        identity(attempt_id)
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) > 16384:
            raise InvalidData("mutation journal document too large")
        return await self._wait(self._submit("mutation", operation, attempt_id, encoded, utc(now)))

    async def mutations(self):
        return await self._wait(self._submit("mutations"))

    def _execute(self, ledger, command, args):
        if command == 'history_complete':
            from .history_coverage import complete_enumeration
            evidence, receipt_id, started, observed, generation, revision = args
            return complete_enumeration(ledger, evidence, receipt_id=receipt_id, writer_epoch=self.epoch,
                read_started_at=started, observed_at=observed, generation=generation, source_revision=revision)
        if command == 'history_coverage':
            from .history_coverage import enumeration_coverage
            scope, start_us, end_us = args
            return enumeration_coverage(ledger, subaccount=scope, start_us=start_us, end_us=end_us)
        if command == "reconcile_snapshot":
            from .verification import audit_snapshot
            snapshot, now = args
            with ledger.transaction():
                self._execute(ledger, "venue_snapshot", (tuple(VenueCost(p.ticker, snapshot.subaccount,
                    p.exchange_index, p.quantity, p.exposure, "rest") for p in snapshot.positions),
                    snapshot.subaccount, now))
                return audit_snapshot(ledger, snapshot, epoch=self.epoch, revision=self._revision,
                                      capacity=self.market_capacity)
        if command == "market_inventory":
            from .portfolio import market_inventory
            return replace(market_inventory(ledger, *args), writer_epoch=self.epoch,
                           writer_revision=self._revision)
        if command == "portfolio":
            from .portfolio import portfolio_view
            scope, now = args
            return portfolio_view(ledger, subaccount=scope, epoch=self.epoch,
                                  revision=self._revision, now=now, capacity=self.market_capacity)
        if command == "reserve_entry":
            from .portfolio import reserve_entry
            encoded, view, config, now, cash, known, fixture = args
            return reserve_entry(ledger, request=json.loads(encoded), view=view, epoch=self.epoch,
                revision=self._revision, config=config, now=now, free_cash=cash,
                account_known=known, offline_fixture=fixture, capacity=self.market_capacity)
        if command == "stage_fill":
            return stage(ledger, *args)
        if command == "pending_fills":
            return pending(ledger, *args)
        if command == "apply_pending":
            key, owner, now = args
            with ledger.transaction():
                row = ledger.connection.execute("SELECT * FROM pending_fills WHERE id=?", (key,)).fetchone()
                if row is None:
                    return None
                fill = Fill(**json.loads(row["payload"]))
                stored = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?",
                                                    (fill.order_id,)).fetchone()
                if stored is None:
                    return None
                order = OrderUpdate.decode(stored[0])
                if (row["owner"] != owner or order.subaccount != owner
                        or (row["scope"] is not None and row["scope"] != owner)
                        or (row["exchange_index"] is not None and row["exchange_index"] != order.exchange_index)):
                    raise InvalidData("pending fill ownership/scope conflicts")
                receipt = self._execute(ledger, "fill", (fill, now))
                if order.terminal and ledger.filled_quantity(fill.order_id) > order.filled:
                    raise InvalidData("pending executions exceed terminal order proof")
                ledger.connection.execute("DELETE FROM pending_fills WHERE id=?", (key,))
                return receipt
        if command == "venue_snapshot":
            observations, scope, now = args
            with ledger.transaction():
                seen = {o.ticker for o in observations}
                old = ledger.connection.execute("SELECT ticker,exchange_index,observed_at FROM venue_costs WHERE subaccount=?",
                                                (scope,)).fetchall()
                # Complete position enumeration can clear the observational
                # clock; never the fill inventory, P&L, orders or reservations.
                for row in old:
                    if now.isoformat() < row[2]:
                        raise InvalidData("position snapshot predates durable venue evidence")
                    if row[0] not in seen:
                        ledger.connection.execute("UPDATE venue_costs SET quantity='0',cost='0',observed_at=? "
                                                  "WHERE subaccount=? AND ticker=?",
                                                  (now.isoformat(), scope, row[0]))
                changed = []
                for observation in observations:
                    prior = ledger.connection.execute("SELECT * FROM venue_costs WHERE subaccount=? AND ticker=?",
                                                      (scope, observation.ticker)).fetchone()
                    if (prior and prior["source"] == "websocket"
                            and timedelta(0) <= now-datetime.fromisoformat(prior["observed_at"]) <= timedelta(seconds=5)
                            and (prior["exchange_index"], Decimal(prior["quantity"]), Decimal(prior["cost"])) == (
                                observation.exchange_index, observation.quantity, observation.cost)):
                        continue  # Preserve sufficient fresh primary-stream cost evidence.
                    changed.append(observation)
                observe_costs(ledger, tuple(changed), now, capacity=self.market_capacity)
            return None
        if command == "stream_cost":
            ticker, quantity, cost, scope, now = args
            rows = ledger.connection.execute("SELECT DISTINCT json_extract(payload,'$.exchange_index') "
                "FROM order_evidence WHERE json_extract(payload,'$.ticker')=? "
                "AND json_extract(payload,'$.subaccount')=? LIMIT 2", (ticker, scope)).fetchall()
            if len(rows) != 1:
                return False  # Stream lacks shard: never guess it from primary account.
            observe_cost(ledger, VenueCost(ticker, scope, rows[0][0], quantity, cost, "websocket"),
                         now, capacity=self.market_capacity)
            return True
        if command == "exit_basis":
            return exit_basis(ledger, *args)
        if command == "recover_fills":
            records, scope, now = args
            receipts, missing = [], []
            with ledger.transaction():
                for record in records:
                    fill = record.fill
                    if record.subaccount != scope:
                        raise InvalidData("recovered fill account scope conflicts")
                    row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?",
                                                    (fill.order_id,)).fetchone()
                    if row is None:
                        missing.append(fill.key)
                        continue
                    order = OrderUpdate.decode(row[0])
                    if (order.subaccount, order.exchange_index, order.ticker, order.side) != (
                            scope, record.exchange_index, fill.ticker, fill.book_side):
                        raise InvalidData("recovered fill differs from owned order scope")
                    # Preserve exact venue time even for a constructed history record.
                    receipt = self._execute(ledger, "fill", (replace(fill, executed_us=record.executed_us,
                                                                  execution_precision_us=1), now))
                    total = ledger.filled_quantity(fill.order_id)
                    if total > order.initial or (order.terminal and total > order.filled):
                        raise InvalidData("recovered executions exceed authoritative order quantity")
                    receipts.append(receipt)
            return RecoveredChunk(tuple(receipts), tuple(missing))
        if command == "fill":
            fill, now = args
            with ledger.transaction():
                row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?", (fill.order_id,)).fetchone()
                if row:
                    order = OrderUpdate.decode(row[0])
                    if fill.ticker != order.ticker or fill.book_side != order.side:
                        raise InvalidData("fill differs from owned order identity")
                inserted = ledger.record_fill(fill, now)
                if row and ledger.filled_quantity(fill.order_id) > order.initial:
                    raise InvalidData("executions exceed owned order size")
                # Schema 2 has exactly one lot per ticker. COUNT(*) avoids
                # allocating every active market on every recovered fill.
                markets = ledger.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
                if markets > self.market_capacity:
                    raise InvalidData("fill exceeds bounded inventory scope")
                window = WindowRisk(ledger).observe(now)
                position = ledger.position(fill.ticker)
                order_receipt = settle_order(ledger, fill.order_id)
            return FillReceipt(inserted, position, window, order_receipt)
        if command == "observe":
            return WindowRisk(ledger).observe(*args)
        if command == "order":
            return record_order(ledger, *args)
        if command == "order_batch":
            updates, now = args
            with ledger.transaction():
                return tuple(record_order(ledger, update, now) for update in updates)
        if command == "history":
            return stage_history(ledger, *args)
        if command == "fill_scope":
            row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?", args).fetchone()
            return OrderUpdate.decode(row[0]).subaccount if row else None
        if command == "order_evidence":
            row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?", args).fetchone()
            return OrderUpdate.decode(row[0]) if row else None
        if command == "orders":
            rows = ledger.connection.execute("SELECT order_id FROM order_evidence LIMIT 4097").fetchall()
            if len(rows) > 4096:
                raise InvalidData("order evidence exceeds bounded capacity")
            with ledger.transaction():
                return tuple(settle_order(ledger, r[0]) for r in rows)
        if command == "inventory":
            rows = ledger.connection.execute(
                "SELECT DISTINCT ticker FROM lots LIMIT ?", (self.market_capacity+1,)).fetchall()
            if len(rows) > self.market_capacity:
                raise InvalidData("inventory exceeds owner capacity")
            return Inventory(tuple(sorted((r[0], ledger.position(r[0])) for r in rows)),
                             ledger.unresolved_intents())
        if command == "reserve":
            client_id, encoded, now = args
            return ledger.reserve_intent(client_id, json.loads(encoded), now)
        if command == "transition":
            return ledger.transition_intent(*args)
        if command == "mutation":
            from .execution import journal_mutation
            return journal_mutation(ledger, *args)
        if command == "mutations":
            rows = ledger.connection.execute("SELECT * FROM mutation_attempts LIMIT 4097").fetchall()
            if len(rows) > 4096:
                raise InvalidData("mutation journal requires archival before further work")
            return tuple(dict(row) for row in rows)
        raise InvalidData("unsupported writer command")

    def _run(self):
        ledger = None
        future = None
        try:
            ledger = Ledger(self.path)  # Construct/use/close on this thread only.
            self._ready.set_result(None)
            while True:
                item = self._queue.get()
                if item is None:
                    break
                command, args, future = item
                try:
                    if self.failed:
                        raise InvalidData("ledger owner failed; queued command not applied")
                    # In-process authority epoch changes on restart. Any command
                    # that can mutate financial/evidence/risk state revokes leases.
                    read_only = {"portfolio", "market_inventory", "inventory", "fill_scope",
                                 "order_evidence", "pending_fills", "exit_basis", "mutations", "history_coverage"}
                    if command not in read_only and command != "reserve_entry":
                        self._revision += 1
                    result = self._execute(ledger, command, args)
                    if command == "reserve_entry":
                        self._revision += 1
                except Exception as exc:
                    self.diagnostics.emit('writer_failed', error=exc, command=command,
                                          revision=self._revision, backlog=self.backlog)
                    with self._lock:
                        self._failed = True
                    future.set_exception(InvalidData("ledger command failed; reconciliation required"))
                else:
                    future.set_result(result)  # Only after transaction commit.
        except BaseException as exc:
            self.diagnostics.emit('writer_failed', error=exc, revision=self._revision)
            with self._lock:
                self._failed = True
            if not self._ready.done():
                self._ready.set_exception(InvalidData("ledger startup failed"))
            if future is not None and not future.done():
                future.set_exception(InvalidData("ledger owner stopped during command"))
        finally:
            # Unexpected worker termination must not leave accepted callers hung.
            while not self._queue.empty():
                item = self._queue.get_nowait()
                if item is not None and not item[2].done():
                    item[2].set_exception(InvalidData("ledger owner stopped before command acknowledgement"))
            if ledger is not None:
                try:
                    ledger.close()
                except Exception as exc:
                    with self._lock:
                        self._failed = True
                    self.diagnostics.emit('writer_failed', error=exc, command='close', revision=self._revision)

    def _finish(self):
        # Queue may be full; block a helper thread, never the event loop.
        if self._thread.is_alive():
            self._queue.put(None)
        self._thread.join()

    async def close(self):
        with self._lock:
            self._closing = True
            if self._started and self._close_task is None:
                self._close_task = asyncio.create_task(asyncio.to_thread(self._finish))
            task = self._close_task
        if task is not None:
            await asyncio.shield(task)

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_):
        await self.close()
