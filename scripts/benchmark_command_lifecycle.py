"""D-059 offline command-lifecycle resource check; no keys, network or live writes.

Uses disposable native Windows WAL/FULL ledgers at 30/120 market scope. At most
30 entry orders are admitted; additional markets exercise actual reduction
preparation and proven-unsent aborts. Small and 4,000-row complete lifecycle
histories measure preparation, consume, cancel/reducer preparation, capacity
checks, loop lag, CPU and incremental Python memory.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import tracemalloc
from types import SimpleNamespace

from benchmark_archive import percentiles
from kalshi_bot.adapters import PriceBand
from kalshi_bot.books import Book, Ladder
from kalshi_bot.command_capacity import validate_capacity
from kalshi_bot.config import BotConfig
from kalshi_bot.execution import acknowledgement, validate_request
from kalshi_bot.exits import ExitTerms, plan_exit
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.management import InventoryManager, ManagedPlan
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.writer import LedgerWriter


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def request(i):
    return dict(ticker=f"M{i}", client_order_id=f"client-{i}", side="bid",
        count="10", price="0.4", time_in_force="good_till_canceled",
        self_trade_prevention_type="taker_at_cross", post_only=True,
        reduce_only=False, cancel_order_on_pause=True, subaccount=0,
        exchange_index=1)


def seed(path, markets, history):
    db = Ledger(path)
    try:
        with db.transaction():
            active = max(0, markets-30)
            terminal_history = max(0, history-(2*active))
            if terminal_history % 2:
                raise ValueError('history must contain complete create/cancel pairs')
            stamp = NOW.isoformat()
            for i in range(terminal_history//2):
                ticker, client = f"H{i%max(markets, 1)}", f"history-client-{i}"
                episode, order_id = f"history-episode-{i}", f"history-order-{i}"
                create = request(i) | {"ticker": ticker, "client_order_id": client}
                cancel = dict(order_id=order_id, market_ticker=ticker,
                              subaccount=0, exchange_index=1)
                create_json = json.dumps(create, sort_keys=True, separators=(",", ":"))
                cancel_json = json.dumps(cancel, sort_keys=True, separators=(",", ":"))
                db.connection.execute("INSERT INTO command_episodes VALUES (?,?,?,'RETIRED',?)",
                                      (episode, 0, ticker, stamp))
                db.connection.execute("INSERT INTO intents VALUES (?,?, 'TERMINAL',?)",
                                      (client, create_json, stamp))
                order = OrderUpdate(order_id, client, ticker, "bid", D(".4"),
                    D(10), D(0), D(0), "canceled", 0, 1, i+1)
                db.connection.execute("INSERT INTO order_evidence VALUES (?,?,?,?)",
                                      (order_id, client, order.encode(), stamp))
                mutations = ((f"history-create-{i}", 'create', create_json),
                             (f"history-cancel-{i}", 'cancel', cancel_json))
                for mutation_id, kind, payload in mutations:
                    response = ({'order_id': order_id, 'client_order_id': client,
                        'fill_count': '0', 'remaining_count': '10', 'ts_ms': 2*i+1}
                        if kind == 'create' else
                        {'order_id': order_id, 'reduced_by': '10', 'ts_ms': 2*i+2})
                    proof = ({'type': 'entry_reservation', 'portfolio_epoch': 'history-epoch',
                              'portfolio_revision': 8*i}
                             if kind == 'create' else
                             {'type': 'cancel_evidence', 'writer_epoch': 'history-epoch',
                              'writer_revision': 8*i+4, 'order_id': order_id})
                    db.connection.execute(
                        "INSERT INTO mutation_attempts VALUES (?,?,?,'ACK',?,?)",
                        (mutation_id, kind, payload,
                         json.dumps(response, sort_keys=True), stamp))
                    db.connection.execute(
                        "INSERT INTO command_authorizations VALUES (?,?,?,?,?,?,?,?,?, 'ACK',?)",
                        (mutation_id, mutation_id, 'history-epoch',
                         8*i+(1 if kind == 'create' else 5),
                         kind, client if kind == 'create' else order_id,
                         episode, payload, json.dumps(proof, sort_keys=True,
                                                      separators=(',', ':')), stamp))
                for slot in ('passive','ioc-1','ioc-2','ioc-3'):
                    for resource, suffix in (('mutation','create'),('mutation','cancel'),
                                             ('intent','intent'),('order','order')):
                        db.connection.execute(
                            "INSERT INTO command_credits VALUES (?,?,?,?,?,'RELEASED',?)",
                            (f"history-{i}-{slot}-{resource}-{suffix}", episode,
                             resource, f"{slot}:{suffix}", None, stamp))
                db.connection.execute(
                    "INSERT INTO command_credits VALUES (?,?,?,?,?,'SPENT',?)",
                    (f"history-{i}-entry-order", episode, 'order', 'order', client, stamp))
                db.connection.execute(
                    "INSERT INTO command_credits VALUES (?,?,?,?,?,'SPENT',?)",
                    (f"history-{i}-entry-cancel", episode, 'mutation', 'cancel', client, stamp))

            # Additional markets are complete active inventory episodes. Their
            # protected drain credits are real and reconciled at startup.
            for i in range(active):
                ticker, client = f"P{i}", f"position-client-{i}"
                episode, order_id = f"position-episode-{i}", f"position-order-{i}"
                create = request(i) | {"ticker": ticker, "client_order_id": client,
                                       "count": "10", "price": "0.1"}
                payload = json.dumps(create, sort_keys=True, separators=(",", ":"))
                mutation = f"position-create-{i}"
                cancel_mutation = f"position-cancel-{i}"
                cancel = dict(order_id=order_id, market_ticker=ticker,
                              subaccount=0, exchange_index=1)
                cancel_payload = json.dumps(cancel, sort_keys=True, separators=(',', ':'))
                db.connection.execute("INSERT INTO command_episodes VALUES (?,?,?,'ACTIVE',?)",
                                      (episode, 0, ticker, stamp))
                db.connection.execute("INSERT INTO intents VALUES (?,?, 'TERMINAL',?)",
                                      (client, payload, stamp))
                order = OrderUpdate(order_id, client, ticker, "bid", D(".1"),
                    D(10), D(".1"), D(0), "canceled", 0, 1, i+1)
                db.connection.execute("INSERT INTO order_evidence VALUES (?,?,?,?)",
                                      (order_id, client, order.encode(), stamp))
                db.connection.execute(
                    "INSERT INTO mutation_attempts VALUES (?, 'create', ?, 'ACK',?,?)",
                    (mutation, payload, json.dumps({'order_id': order_id,
                        'client_order_id': client, 'fill_count': '0.1',
                        'remaining_count': '9.9', 'ts_ms': i+1}, sort_keys=True), stamp))
                db.connection.execute(
                    "INSERT INTO command_authorizations VALUES (?,?,?,?,?,?,?,?,?, 'ACK',?)",
                    (mutation, mutation, 'position-epoch', 8*i+1,
                     'create', client, episode, payload,
                     json.dumps({'type': 'entry_reservation',
                        'portfolio_epoch': 'position-epoch',
                        'portfolio_revision': 8*i},
                        sort_keys=True, separators=(',', ':')), stamp))
                db.connection.execute(
                    "INSERT INTO mutation_attempts VALUES (?, 'cancel', ?, 'ACK',?,?)",
                    (cancel_mutation, cancel_payload, json.dumps({'order_id': order_id,
                        'reduced_by': '9.9', 'ts_ms': i+2}, sort_keys=True), stamp))
                db.connection.execute(
                    "INSERT INTO command_authorizations VALUES (?,?,?,?,?,?,?,?,?, 'ACK',?)",
                    (cancel_mutation, cancel_mutation, 'position-epoch',
                     8*i+5, 'cancel', order_id, episode,
                     cancel_payload, json.dumps({'type': 'cancel_evidence',
                        'writer_epoch': 'position-epoch',
                        'writer_revision': 8*i+4,
                        'order_id': order_id}, sort_keys=True,
                        separators=(',', ':')), stamp))
                db.record_fill(Fill(f"position-fill-{i}", order_id, ticker,
                    "bid", D("0.1"), D("0.1"), D(0)), NOW)
                for slot in ('passive','ioc-1','ioc-2','ioc-3'):
                    for resource, suffix in (('mutation','create'),('mutation','cancel'),
                                             ('intent','intent'),('order','order')):
                        db.connection.execute(
                            "INSERT INTO command_credits VALUES (?,?,?,?,?,'HELD',?)",
                            (f"position-{i}-{slot}-{resource}-{suffix}", episode,
                             resource, f"{slot}:{suffix}", None, stamp))
                db.connection.execute(
                    "INSERT INTO command_credits VALUES (?,?,?,?,?,'SPENT',?)",
                    (f"position-{i}-entry-order", episode, 'order', 'order', client, stamp))
                db.connection.execute(
                    "INSERT INTO command_credits VALUES (?,?,?,?,?,'SPENT',?)",
                    (f"position-{i}-entry-cancel", episode, 'mutation', 'cancel', client, stamp))
            if active:
                for resource in ('mutation','intent','order'):
                    per_episode = 8 if resource == 'mutation' else 4
                    db.connection.execute(
                        "UPDATE command_capacity_counters SET held=held+? WHERE resource=?",
                        (active*per_episode, resource))
    finally:
        db.close()


def validate_seed_fixture(path, markets, history):
    """Reject benchmark states that the validated command lifecycle cannot emit."""
    db = Ledger(path)
    try:
        validate_capacity(db)
        rows = db.connection.execute(
            "SELECT m.*,a.writer_epoch,a.writer_revision,a.kind AS auth_kind,"
            "a.subject_id,a.episode_id,a.request AS auth_request,a.proof,a.state "
            "FROM mutation_attempts m JOIN command_authorizations a "
            "ON a.mutation_id=m.id ORDER BY a.writer_epoch,a.writer_revision").fetchall()
        expected = max(history, 2*max(0, markets-30))
        if len(rows) != expected:
            raise AssertionError('benchmark mutation history size mismatch')
        revisions = {}
        for row in rows:
            request_doc = json.loads(row['request'])
            validate_request(row['kind'], request_doc)
            if (row['phase'] != 'ACK' or row['state'] != 'ACK'
                    or row['kind'] != row['auth_kind']
                    or row['request'] != row['auth_request']):
                raise AssertionError('benchmark authorization lifecycle mismatch')
            if acknowledgement(row['kind'], request_doc,
                               json.loads(row['response'])) != json.loads(row['response']):
                raise AssertionError('benchmark acknowledgement is not canonical')
            proof = json.loads(row['proof'])
            if row['kind'] == 'create':
                if (set(proof) != {'type','portfolio_epoch','portfolio_revision'}
                        or proof['type'] != 'entry_reservation'
                        or proof['portfolio_epoch'] != row['writer_epoch']
                        or type(proof['portfolio_revision']) is not int
                        or row['writer_revision'] != proof['portfolio_revision']+1):
                    raise AssertionError('benchmark entry proof is not lifecycle-valid')
            elif (set(proof) != {'type','writer_epoch','writer_revision','order_id'}
                    or proof['type'] != 'cancel_evidence'
                    or proof['writer_epoch'] != row['writer_epoch']
                    or type(proof['writer_revision']) is not int
                    or row['writer_revision'] != proof['writer_revision']+1
                    or proof['order_id'] != row['subject_id']):
                raise AssertionError('benchmark cancel proof is not lifecycle-valid')
            episode = db.connection.execute(
                'SELECT 1 FROM command_episodes WHERE id=?',
                (row['episode_id'],)).fetchone()
            if episode is None:
                raise AssertionError('benchmark command episode missing')
            if row['kind'] == 'create':
                intent = db.connection.execute(
                    'SELECT payload FROM intents WHERE client_id=?',
                    (row['subject_id'],)).fetchone()
                order = db.connection.execute(
                    'SELECT order_id FROM order_evidence WHERE client_id=?',
                    (row['subject_id'],)).fetchone()
                if (row['subject_id'] != request_doc['client_order_id']
                        or intent is None or intent[0] != row['request']
                        or order is None):
                    raise AssertionError('benchmark create lifecycle is incomplete')
            else:
                order = db.connection.execute(
                    'SELECT client_id FROM order_evidence WHERE order_id=?',
                    (row['subject_id'],)).fetchone()
                owner = (db.connection.execute(
                    'SELECT episode_id FROM command_credits WHERE owner_id=? LIMIT 1',
                    (order[0],)).fetchone() if order else None)
                if (row['subject_id'] != request_doc['order_id'] or order is None
                        or owner is None or owner[0] != row['episode_id']):
                    raise AssertionError('benchmark cancel lifecycle is incomplete')
            previous = revisions.get(row['writer_epoch'], -1)
            if row['writer_revision'] <= previous:
                raise AssertionError('benchmark writer revisions are not monotonic')
            revisions[row['writer_epoch']] = row['writer_revision']
    finally:
        db.close()


async def measure(markets, history):
    with TemporaryDirectory(prefix="kalshi-command-check-") as folder:
        path = Path(folder)/"ledger.db"
        seed(path, markets, history)
        validate_seed_fixture(path, markets, history)
        baseline_threads = threading.active_count()
        async with LedgerWriter(path, market_capacity=128) as writer:
            runtime = SimpleNamespace(writer=writer, current_now=NOW)
            runtime.clock = lambda: 100.0
            runtime.now = lambda: runtime.current_now
            manager = InventoryManager(runtime)
            samples = {name: [] for name in ("prepare", "consume", "cancel",
                                              "reducer", "capacity")}
            lags = []
            stopped = asyncio.Event()

            async def heartbeat():
                while not stopped.is_set():
                    due = time.perf_counter()+.002
                    await asyncio.sleep(.002)
                    lags.append(max(0, time.perf_counter()-due))

            pulse = asyncio.create_task(heartbeat())
            await asyncio.sleep(0)
            tracemalloc.start()
            wall_started, cpu_started = time.perf_counter(), time.process_time()
            try:
                for i in range(30):
                    req = request(i)
                    started = time.perf_counter()
                    prepared = await writer.reserve_entry(req, attempt_id=f"create-{i}",
                        view=await writer.portfolio(subaccount=0, now=NOW),
                        config=BotConfig(managed_market_slots=30), now=NOW,
                        free_cash=D(500), account_known=True, offline_fixture=True)
                    samples["prepare"].append(time.perf_counter()-started)
                    assert prepared.reserved, prepared.blockers

                    started = time.perf_counter()
                    sent = await writer.begin_send(prepared.receipt)
                    samples["consume"].append(time.perf_counter()-started)
                    assert sent.dispatch_allowed
                    await writer.record_outcome("ack", prepared.receipt, dict(
                        order_id=f"order-{i}", client_order_id=f"client-{i}",
                        fill_count="0", remaining_count="10", ts_ms=i+1), NOW)
                    await writer.order(OrderUpdate(f"order-{i}", f"client-{i}",
                        f"M{i}", "bid", D(".4"), D(10), D(0), D(10), "resting",
                        0, 1, i+1), NOW)

                    started = time.perf_counter()
                    cancel = await writer.prepare_cancel(f"cancel-{i}", dict(
                        order_id=f"order-{i}", market_ticker=f"M{i}", subaccount=0,
                        exchange_index=1), evidence=await writer.cancel_evidence(
                            f"order-{i}"), now=NOW)
                    samples["cancel"].append(time.perf_counter()-started)
                    assert cancel.reserved, cancel.blockers

                    sent_cancel = await writer.begin_send(cancel.receipt)
                    assert sent_cancel.dispatch_allowed
                    await writer.record_outcome("ack", cancel.receipt, dict(
                        order_id=f"order-{i}", reduced_by="10", ts_ms=i+100), NOW)
                    await writer.order(OrderUpdate(f"order-{i}", f"client-{i}",
                        f"M{i}", "bid", D(".4"), D(10), D(0), D(0), "canceled",
                        0, 1, i+100), NOW)

                    started = time.perf_counter()
                    await writer.command_capacity()
                    samples["capacity"].append(time.perf_counter()-started)
                for i in range(max(0, markets-30)):
                    decision_now = NOW+timedelta(seconds=900)
                    req = dict(ticker=f"P{i}", client_order_id=f"reducer-{i}",
                        side="ask", count="0.1", price="0.5",
                        time_in_force="immediate_or_cancel",
                        self_trade_prevention_type="taker_at_cross", post_only=False,
                        reduce_only=True, cancel_order_on_pause=True, subaccount=0,
                        exchange_index=1)
                    started = time.perf_counter()
                    inventory = await writer.market_inventory(f"P{i}", subaccount=0)
                    book = Book(f"P{i}", Ladder(8), Ladder(8), True)
                    book.bids.set(D('.5'), D(10)); book.asks.set(D('.6'), D(10))
                    bands = (PriceBand(D(0), D(1), D('.01')),)
                    terms = ExitTerms(f"P{i}", bands, decision_now,
                        decision_now+timedelta(hours=1),
                        decision_now+timedelta(hours=2),
                        event_risk_at=decision_now+timedelta(hours=1),
                        taker_fee_per_contract_bound=D('.01'))
                    exit_plan = plan_exit(ticker=f"P{i}", position=inventory.position,
                        basis=inventory.yes_basis, first_seen_at=inventory.first_seen_at,
                        orders=inventory.orders, book=book, terms=terms,
                        journal=inventory.exit_journal, now=decision_now,
                        complete_scope=True)
                    plan = ManagedPlan(f"P{i}", decision_now, 1, 1, 1,
                        book.revision, inventory, exit_plan.passive, (),
                        exit=exit_plan, terms=terms)
                    runtime.current_now = decision_now
                    runtime.account = SimpleNamespace(
                        connected=True, generation=1, revision=1)
                    runtime.engine = SimpleNamespace(stopped=False,
                        market_shard={f"P{i}": 'fixture'},
                        book_received={f"P{i}": 100.0},
                        public={'fixture': False},
                        shards={'fixture': SimpleNamespace(generation=1,
                            failed=False, books={f"P{i}": book})})
                    manager.terms[f"P{i}"] = terms
                    manager._plans[f"P{i}"] = plan
                    evidence = await writer.reduction_evidence(req, now=decision_now)
                    reducer = await writer.prepare_reduction(
                        f"reduce-{i}", req, evidence=evidence, now=decision_now)
                    assert reducer.reserved, reducer.blockers
                    await writer.abort_prepared(reducer.receipt)
                    samples["reducer"].append(time.perf_counter()-started)
                wall = time.perf_counter()-wall_started
                cpu = time.process_time()-cpu_started
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
                stopped.set()
                await pulse
            lifecycles = 30+max(0, markets-30)
            measured = {name: percentiles(values)
                        for name, values in samples.items() if values}
            result = dict(markets=markets, history_rows=max(history, 2*(markets-30)),
                entry_lifecycles=30, management_lifecycles=max(0, markets-30),
                wall_seconds=round(wall, 4), cpu_seconds=round(cpu, 4),
                cpu_seconds_per_lifecycle=round(cpu/lifecycles, 6),
                incremental_peak_bytes=peak,
                max_writer_backlog=writer.max_backlog_observed,
                thread_delta=threading.active_count()-baseline_threads,
                loop_lag=percentiles(lags), **measured)
            result["diagnostic_pass"] = (all(result[name]["p99_ms"] < 250
                for name in measured) and result["loop_lag"]["p99_ms"] < 50
                and peak < 40*1024*1024 and result["max_writer_backlog"] <= 256
                and result["thread_delta"] == 1)
            return result


async def main():
    results = []
    for markets in (30, 120):
        small = await measure(markets, 0)
        near = await measure(markets, 4000)
        ratio = near["cpu_seconds_per_lifecycle"]/max(
            small["cpu_seconds_per_lifecycle"], .000001)
        near["cpu_ratio_vs_small"] = round(ratio, 3)
        near["diagnostic_pass"] &= ratio <= 2
        results.extend((small, near))
    for result in results:
        print(json.dumps(result, sort_keys=True))
    if not all(result["diagnostic_pass"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
