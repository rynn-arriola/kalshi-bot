"""Bounded incumbent maintenance; keys only, never a second order writer.

One pair withdraws at a time. Exact terminal/fill proof precedes a fresh pair
through the ordinary selector/writer. Recovery-only startup never resumes this
ephemeral policy; the existing supervisor drains durable orders first.
"""
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .selection import MarketSelector
from .fill_risk import FillRisk
from .values import InvalidData, utc


def active_config():
    from .config import active
    return active()


@dataclass(frozen=True)
class MaintenanceCycle:
    ticker: str
    program: object
    order_ids: tuple[str, ...]
    reason: str
    reenter: bool
    evidence_valid_until: datetime | None = None
    evidence_identity: tuple | None = None


@dataclass(frozen=True)
class DriftEvidence:
    identity: tuple
    verified_seconds: float
    observed_at: float
    valid_until: float


@dataclass(frozen=True)
class RiskQueueAnchor:
    writer_epoch: str
    program: object
    account_generation: int
    book_generation: int
    signature: tuple
    queue_positions: tuple
    queue_started_mono: float
    valid_until: datetime


@dataclass(frozen=True)
class QueueAnchor:
    """D-145: one exact Kalshi queue reading, kept until the next one.

    Valid only within the same book lineage (a reconnect or sequence gap
    starts a new one) and for the same order terms; ``marks`` are
    ``FillRisk.anchor_marks`` taken when the read started.
    """
    ticker: str
    side: str
    yes_price: Decimal
    ahead: Decimal
    read_mono: float
    lineage: object
    book_generation: int
    marks: tuple


def taker_orders(rows):
    """D-155/D-156: one taker order = the trades sharing a market, time and side."""
    orders = {}
    for row in rows:
        try:
            key = (row['ticker'], row['created_time'], row['taker_side'])
            orders[key] = orders.get(key, Decimal(0))+Decimal(str(row['count_fp']))
        except (KeyError, TypeError, ArithmeticError):
            continue
    return orders


def sweeps_from_trades(rows, minimum):
    """D-155: newest sweep per market."""
    return latest_sweeps(taker_orders(rows), minimum)


def latest_sweeps(orders, minimum):
    latest = {}
    for (ticker, created, _), size in orders.items():
        if size < minimum:
            continue
        try:
            at = int(datetime.fromisoformat(str(created).replace('Z', '+00:00')).timestamp())
        except ValueError:
            continue
        latest[ticker] = max(at, latest.get(ticker, 0))
    return latest


class QuoteMaintenance:
    REPRICE_DWELL_SECONDS = 30
    # D-145 fill protection: a dedicated queue reader anchors every resting
    # entry; an order without a valid anchor for longer than BLIND_SECONDS is
    # treated as threatened rather than safe.
    QUEUE_READ_SECONDS = 2.0
    QUEUE_MIN_GAP_SECONDS = 0.5
    BLIND_SECONDS = 10.0
    # D-131 item 7: bounded concurrent protective withdrawals (primary cycle
    # plus latched secondaries). Cancels still dispatch one at a time.
    MAX_RISK_CYCLES = 4
    UNSCORING_DWELL_SECONDS = 90
    MAX_EVIDENCE_GAP_SECONDS = 15

    def __init__(self, runtime):
        self.runtime = runtime
        self.bindings = {}
        self.cycle = None
        self.samples = {}
        self._dwell = {}
        self._cooldown = {}
        self.fill_risk = FillRisk()
        self._risk_cooldown = {}
        self._risk_since = {}
        self._cycle_started = None  # First warning; diagnostic decision delay.
        self._cycle_latched = None  # Latched decision; D-129 cancel budget.
        self._cycle_acks = set()
        # ticker -> latched secondary risk cycle and its (warned, latched, acks).
        self.risk_latched = {}
        self._latched_timing = {}
        self._withdrawals = {}  # ticker -> recent withdrawal clocks (item 8)
        self._risk_queues = {}
        self._risk_log_at = {}
        self._risk_gap_counts = {}
        self._anchors = {}      # order_id -> QueueAnchor (D-145)
        self._research_marks_pending = 0  # D-151 #4
        # D-154: ticker -> newest own fill (venue microseconds); None until the
        # first ledger load. Live composition sets ``fill_cooldown_required``.
        self.fill_cooldown_required = False
        self.fill_cooldown = None
        self.fill_cooldown_loaded_mono = None
        self.fill_cooldown_failures = 0
        self.fill_cooldown_blocks = 0
        # D-155: ticker -> newest big sweep (epoch seconds), any direction.
        self.sweep_filter_required = False
        self.sweeps = {}
        self.sweeps_loaded_mono = None
        self.sweeps_polled_s = None
        self.sweep_failures = 0
        self.sweep_blocks = 0
        self._blind_since = {}  # order_id -> first clock seen without an anchor
        self.queue_reader_active = False
        self._queue_wake = None
        self._queue_ok_at = None
        self.queue_reads = 0
        self.queue_read_failures = 0
        self.risk_triggers = dict(time_to_fill=0, short_queue=0, blind=0)
        self._actual = MarketSelector(1)
        self._target = MarketSelector(1)

    def bind(self, program):
        # Selection identity is advisory; only durable order evidence proves
        # a pair was placed. Scope is bounded by the existing subscribed universe.
        if program.ticker not in self.runtime.engine.market_shard:
            raise InvalidData('maintenance binding outside runtime scope')
        for old in tuple(self.bindings):
            if old not in self.runtime.engine.market_shard:
                for table in (self.bindings, self.samples, self._dwell, self._cooldown,
                              self._risk_cooldown, self._risk_since, self._risk_queues,
                              self._risk_log_at, self._risk_gap_counts):
                    table.pop(old, None)
        if self.bindings.get(program.ticker) != program:
            self._dwell.pop(program.ticker, None)
            self._risk_queues.pop(program.ticker, None)
        self.bindings[program.ticker] = program

    def protection_current(self):
        """D-145: the queue reader has succeeded within the blind limit."""
        return (self._queue_ok_at is not None
                and 0 <= self.runtime.clock()-self._queue_ok_at <= self.BLIND_SECONDS)

    FILL_COOLDOWN_SECONDS = 7*24*3600  # D-154, widened by D-155 to 7 days

    @staticmethod
    def market_family(ticker):
        """D-155: the series part of a ticker (KXTXOIL-27MAR31-T5.8 -> KXTXOIL)."""
        return ticker.split('-', 1)[0]
    FILL_COOLDOWN_STALE_SECONDS = 300

    def set_fill_history(self, rows, mono):
        """D-154/D-155: newest own fill per market family, from the ledger."""
        newest = {}
        for _, payload, executed in rows:
            if type(executed) is int and payload:
                family = self.market_family(payload[0])
                newest[family] = max(executed, newest.get(family, 0))
        self.fill_cooldown = newest
        self.fill_cooldown_loaded_mono = mono

    def fill_cooldown_allows(self, ticker):
        """D-154/D-155: no new entry in a market family that filled us within 7 days.

        Fails closed until the ledger has been read, and when that read is
        more than five minutes old, so a restart never re-enters blindly.
        """
        if not self.fill_cooldown_required:
            return True
        loaded = self.fill_cooldown_loaded_mono
        if (self.fill_cooldown is None or loaded is None
                or self.runtime.clock()-loaded > self.FILL_COOLDOWN_STALE_SECONDS):
            return False
        last = self.fill_cooldown.get(self.market_family(ticker))
        if last is None:
            return True
        now_us = int(utc(self.runtime.now()).timestamp()*1_000_000)
        return now_us-last >= self.FILL_COOLDOWN_SECONDS*1_000_000

    def fill_cooldown_status(self):
        if not self.fill_cooldown_required:
            return dict(required=False)
        now_us = int(utc(self.runtime.now()).timestamp()*1_000_000)
        horizon = self.FILL_COOLDOWN_SECONDS*1_000_000
        cooling = {t: round((last+horizon-now_us)/3.6e9, 2)
                   for t, last in (self.fill_cooldown or {}).items() if now_us-last < horizon}
        age = (None if self.fill_cooldown_loaded_mono is None
               else round(self.runtime.clock()-self.fill_cooldown_loaded_mono, 1))
        return dict(required=True, loaded=self.fill_cooldown is not None, load_age_seconds=age,
                    failures=self.fill_cooldown_failures, blocks=self.fill_cooldown_blocks,
                    hours_left=dict(sorted(cooling.items())[:30]), markets=len(cooling))

    SWEEP_MIN_CONTRACTS = Decimal(150)  # D-155 / Finding 215
    SWEEP_BLOCK_SECONDS = 3600
    SWEEP_STALE_SECONDS = 300

    def record_sweeps(self, latest, *, mono, polled_s):
        """D-155: merge a completed poll's sweeps and drop the expired ones."""
        for ticker, at in latest.items():
            self.sweeps[ticker] = max(at, self.sweeps.get(ticker, 0))
        horizon = polled_s-self.SWEEP_BLOCK_SECONDS
        self.sweeps = {t: at for t, at in self.sweeps.items() if at > horizon}
        self.sweeps_loaded_mono, self.sweeps_polled_s = mono, polled_s

    def sweep_allows(self, ticker):
        """D-155: no new entry for an hour after a sweep of 150+ contracts.

        Fails closed until the first complete poll and when the last complete
        poll is more than five minutes old.
        """
        if not self.sweep_filter_required:
            return True
        loaded = self.sweeps_loaded_mono
        if loaded is None or self.runtime.clock()-loaded > self.SWEEP_STALE_SECONDS:
            return False
        last = self.sweeps.get(ticker)
        now_s = int(utc(self.runtime.now()).timestamp())
        return last is None or now_s-last >= self.SWEEP_BLOCK_SECONDS

    def sweep_status(self):
        if not self.sweep_filter_required:
            return dict(required=False)
        now_s = int(utc(self.runtime.now()).timestamp())
        age = (None if self.sweeps_loaded_mono is None
               else round(self.runtime.clock()-self.sweeps_loaded_mono, 1))
        blocked = sorted(((round((at+self.SWEEP_BLOCK_SECONDS-now_s)/60, 1), t)
                          for t, at in self.sweeps.items() if now_s-at < self.SWEEP_BLOCK_SECONDS),
                         reverse=True)
        return dict(required=True, loaded=self.sweeps_loaded_mono is not None, poll_age_seconds=age,
                    failures=self.sweep_failures, blocks=self.sweep_blocks,
                    markets_blocked=len(blocked))

    def entry_allowed(self, ticker, program_id):
        if self.queue_reader_active and not self.protection_current():
            return False  # Never place an entry that cannot be protected.
        if not self.fill_cooldown_allows(ticker):
            self.fill_cooldown_blocks += 1
            return False
        if not self.sweep_allows(ticker):
            self.sweep_blocks += 1
            return False
        deadline = self._risk_cooldown.get(ticker)
        if deadline is not None:
            if self.runtime.clock() < deadline:
                return False
            self._risk_cooldown.pop(ticker, None)
        c = self.cycle
        if c is None or c.ticker != ticker:
            # The cycle coordinates only this market's withdrawal/re-entry.
            # Other markets still pass ordinary ranked admission and the sole
            # writer's shared risk/cap checks; never reserve all free slots.
            return True
        observation = self.runtime.selection._observation(ticker)
        return (c.reenter and c.ticker == ticker and c.program.program_id == program_id
                and observation is not None and c.program in observation.programs)

    def risk_cycle_for(self, ticker):
        """The latched protective cycle owning this market, if any."""
        c = self.cycle
        if c is not None and c.reason == 'fill_risk_withdrawal' and c.ticker == ticker:
            return c
        return self.risk_latched.get(ticker)

    def risk_cycles(self):
        c = self.cycle
        primary = ((c,) if c is not None and c.reason == 'fill_risk_withdrawal' else ())
        return primary+tuple(self.risk_latched.values())

    def _latch_secondary(self, plan, program):
        """Latch another threatened market while a primary cycle is draining."""
        r, ticker = self.runtime, plan.ticker
        if (ticker in self.risk_latched or r.entry_pause_active
                or len(self.risk_cycles()) >= self.MAX_RISK_CYCLES):
            return ticker in self.risk_latched
        service = r.dispatch_supervisor
        active = service.dispatcher.status().active if service is not None else None
        if active is not None and active[0] == ticker:
            return False  # Join an in-flight command for this same market.
        ids = tuple(sorted(o.order.order_id for o in plan.inventory.orders))
        cycle = MaintenanceCycle(ticker, program, ids, 'fill_risk_withdrawal', False)
        now = r.clock()
        self.risk_latched[ticker] = cycle
        self._latched_timing[ticker] = (self._risk_since.get(ticker, now), now, set())
        repeats = self._record_withdrawal(ticker)
        self._risk_cooldown[ticker] = now+self._risk_cooldown_seconds(ticker)
        if ticker in self.samples:
            self.samples[ticker]['action'] = 'fill_risk_withdrawal'
        self._research_withdrawal(plan, 'secondary')
        r.diagnostics.emit('fill_risk_withdrawal', market=ticker, count=repeats)
        r.diagnostics.emit('maintenance_cycle_started', market=ticker,
            maintenance_reason='fill_risk_withdrawal', count=len(ids))
        source = getattr(service, 'source', None)
        if source is not None:
            source.request_risk_drain(ticker)  # Never depend on the caller's wake.
        return True

    RESEARCH_MARK_SECONDS = (30, 60)
    RESEARCH_MAX_PENDING_MARKS = 200

    def _research_withdrawal(self, plan, kind):
        """D-151 #4: why a protective pull fired; the market is checked later."""
        r = self.runtime
        if getattr(r, 'research', None) is None:
            return
        r._research_safely(self._record_research_withdrawal, plan, kind)

    def _record_research_withdrawal(self, plan, kind):
        from uuid import uuid4
        r, ticker = self.runtime, plan.ticker
        rows = [row for row in (self.samples.get(ticker) or {}).get('fill_risk', ())
                if row.get('withdraw')]
        orders = [dict(order_id=o.order.order_id, side=o.order.side, price=o.order.yes_price,
                       remaining=o.order.remaining) for o in plan.inventory.orders]
        key = uuid4().hex
        r.research.record('withdrawals', key, ticker=ticker, kind=kind, orders=orders,
            triggers=sorted({row.get('trigger') for row in rows} - {None}),
            samples=[{field: row.get(field) for field in (
                'order_id', 'trigger', 'ahead_estimate', 'queue_ahead', 'depletion_per_second',
                'seconds_to_reach', 'horizon_seconds', 'blind_seconds', 'anchored')}
                for row in rows],
            repeats_last_hour=len(self._withdrawals.get(ticker, ())),
            **r._research_top(r.management._book(ticker)[1]))
        if self._research_marks_pending + len(self.RESEARCH_MARK_SECONDS) > self.RESEARCH_MAX_PENDING_MARKS:
            return
        loop = asyncio.get_running_loop()
        for delay in self.RESEARCH_MARK_SECONDS:
            self._research_marks_pending += 1
            loop.call_later(delay, self._research_withdrawal_mark, key, ticker, orders, delay)

    def _research_withdrawal_mark(self, key, ticker, orders, delay):
        """Did the market reach our prices after the pull? (level gone = yes)."""
        self._research_marks_pending = max(0, self._research_marks_pending-1)
        r = self.runtime
        if getattr(r, 'research', None) is None or r.stop_requested.is_set():
            return
        def mark():
            book = r.management._book(ticker)[1]
            top = r._research_top(book)
            bid, ask = top['best_bid'], top['best_ask']
            # No book at all is unknown, not "gone"; an empty side is gone.
            reached = None if book is None else [o['order_id'] for o in orders
                       if (o['side'] == 'bid' and (bid is None or bid < o['price']))
                       or (o['side'] == 'ask' and (ask is None or ask > o['price']))]
            r.research.record('withdrawal_marks', f'{key}@{delay}', ticker=ticker,
                              delay_seconds=delay, level_gone=reached, **top)
        r._research_safely(mark)

    REPEAT_WINDOW_SECONDS = 3600

    def _risk_cooldown_seconds(self, ticker):
        """D-135: adaptive re-entry lockout from this hour's withdrawal count.

        Live evidence (Finding 206): the real sweep followed its withdrawal
        within seconds, while almost every other trigger saw no trades at all.
        A short first lockout restores quoting; repeats still back off to the
        original five minutes. The withdrawal trigger itself is unchanged.
        """
        return self.fill_risk.policy.cooldown_for(len(self._withdrawals.get(ticker, ())))

    def _record_withdrawal(self, ticker):
        """D-131 item 8: bounded per-market withdrawals in the last hour.

        D-135: the count also sets the adaptive re-entry lockout; no ranking
        or trigger threshold uses it.
        """
        now = self.runtime.clock()
        horizon = now-self.REPEAT_WINDOW_SECONDS
        for key in tuple(self._withdrawals):
            times = self._withdrawals[key]
            while times and times[0] < horizon:
                times.popleft()
            if not times:
                del self._withdrawals[key]
        times = self._withdrawals.setdefault(ticker, deque(maxlen=64))
        times.append(now)
        return len(times)

    def _finish_secondary(self, ticker):
        cycle = self.risk_latched.pop(ticker, None)
        timing = self._latched_timing.pop(ticker, None)
        if cycle is None:
            return
        self.runtime.diagnostics.emit('maintenance_cycle_finished', market=ticker,
            maintenance_reason=cycle.reason,
            elapsed_ms=max(0, int((self.runtime.clock()-timing[1])*1000)) if timing else None)
        self._risk_cooldown[ticker] = self.runtime.clock()+self._risk_cooldown_seconds(ticker)
        self._risk_since.pop(ticker, None)
        self._dwell.pop(ticker, None)
        self._cooldown[ticker] = self.runtime.clock()+30
        self.runtime._entry_dirty = True

    def credit(self, program):
        rewards = self.runtime.rewards
        record = rewards.tracker.records.get(program.program_id) if rewards else None
        # Never combine programs, changed terms, unknown periods or paid cash.
        return (record.estimate if record is not None and not record.conflict
                and record.program == program else Decimal(0))

    def continuation(self):
        c = self.cycle
        return ({c.ticker: (c.program.program_id, self.credit(c.program))}
                if c is not None and c.reenter else {})

    def _finish(self, ticker):
        if self.cycle is not None:
            # D-130: bounded cycle diagnostics; reason is a fixed vocabulary.
            self.runtime.diagnostics.emit('maintenance_cycle_finished', market=self.cycle.ticker,
                maintenance_reason=self.cycle.reason,
                elapsed_ms=max(0, int((self.runtime.clock()-self._cycle_latched)*1000))
                    if self._cycle_latched is not None else None)
        if self.cycle is not None and self.cycle.reason == 'fill_risk_withdrawal':
            self._risk_cooldown[ticker] = self.runtime.clock()+self._risk_cooldown_seconds(ticker)
        self.cycle = None
        self._cycle_started = None
        self._cycle_latched = None
        self._cycle_acks.clear()
        self._risk_since.pop(ticker, None)
        self._dwell.pop(ticker, None)
        self._cooldown[ticker] = self.runtime.clock()+30
        self.runtime._entry_dirty = True
        self.wake_deferred_risk()

    def wake_deferred_risk(self):
        """Reevaluate warnings deferred by another mutation/cycle, not old proof."""
        r = self.runtime
        if (r.stop_requested.is_set() or r.engine.failed
                or (self.cycle is not None and self.cycle.reason == 'fill_risk_withdrawal')):
            return
        for ticker in self._risk_since:
            if ticker in r.engine.market_shard:
                r.engine.dirty.mark(ticker)
                r.engine.wake.set()

    def dispatch_result(self, result):
        """Decision-to-durable-ACK time includes dispatch/reconciliation waiting."""
        from .dispatch import QUOTE_CANCEL
        latched = self.risk_latched.get(result.ticker)
        timing = self._latched_timing.get(result.ticker)
        if (latched is not None and timing is not None and result.priority == QUOTE_CANCEL
                and result.state == 'ACK' and result.order_id in latched.order_ids
                and result.order_id not in timing[2]):
            now = self.runtime.clock()
            self.fill_risk.cancel_ack(now-timing[1])
            timing[2].add(result.order_id)
            self.runtime.diagnostics.emit('fill_risk_cancel_ack', market=result.ticker,
                order=result.order_id, elapsed_ms=max(0, int((now-timing[0])*1000)),
                latch_ms=max(0, int((now-timing[1])*1000)))
            return
        c = self.cycle
        if (c is not None and self._cycle_started is not None
                and result.priority == QUOTE_CANCEL and result.state == 'ACK'
                and result.ticker == c.ticker and result.order_id in c.order_ids
                and result.order_id not in self._cycle_acks):
            now = self.runtime.clock()
            latched = self._cycle_latched if self._cycle_latched is not None else self._cycle_started
            # D-129: the budget estimates latched-decision-to-ACK latency. Time a
            # warning waited behind another cycle/recovery is reported, but
            # must not widen every order's future withdrawal horizon.
            self.fill_risk.cancel_ack(now-latched)
            self._cycle_acks.add(result.order_id)
            if c.reason == 'fill_risk_withdrawal':
                self.runtime.diagnostics.emit('fill_risk_cancel_ack', market=c.ticker,
                    order=result.order_id,
                    elapsed_ms=max(0, int((now-self._cycle_started)*1000)),
                    latch_ms=max(0, int((now-latched)*1000)))

    def accept_risk_queues(self, proofs):
        """Retain the original successful queue join for cancellation only.

        Called synchronously by the existing reflection reader before optional
        reward/metadata joins. No new read, lease renewal or entry authority.
        """
        r, anchors, count = self.runtime, {}, 0
        for ticker, proof in proofs.items():
            program = self.bindings.get(ticker)
            if program is None or proof.queue_started_mono is None:
                continue
            count += len(proof.queue_positions)
            if count > self.fill_risk.policy.capacity:
                self._risk_queues.clear()
                self.fill_risk.prune(())
                return
            anchors[ticker] = RiskQueueAnchor(r.writer.epoch, program,
                proof.account_generation, proof.book_generation, proof.signature,
                proof.queue_positions, proof.queue_started_mono, proof.valid_until)
        self._risk_queues = anchors
        self.fill_risk.prune(key for a in anchors.values() for key, _ in a.queue_positions)

    def _risk_gap(self, ticker, code):
        # Each fixed reason has an exact count; emit powers of two only.
        counts = self._risk_gap_counts.setdefault(ticker, {})
        count = counts[code] = min(counts.get(code, 0)+1, 2**62)
        if count & (count-1) == 0:
            self.runtime.diagnostics.emit('fill_risk_observation_gap', market=ticker,
                                          risk_state=code, count=count)

    def _risk_sample_log(self, ticker, samples):
        now = self.runtime.clock()
        threatened = any(row['withdraw'] for row in samples)
        previous = self._risk_log_at.get(ticker)
        if (previous is not None and now-previous[0] < 5
                and threatened == previous[1]):
            return
        self._risk_log_at[ticker] = (now, threatened)
        for row in samples:
            if row.get('trigger') == 'blind':
                self.runtime.diagnostics.emit('fill_risk_sample', market=ticker,
                    order=row['order_id'], risk_state='blind',
                    queue_age_ms=int(row['blind_seconds']*1000))
                continue
            eta = row['seconds_to_reach']
            self.runtime.diagnostics.emit('fill_risk_sample', market=ticker,
                order=row['order_id'], risk_state=('short_queue' if row.get('trigger') == 'short_queue'
                    else 'threat' if row['withdraw'] else 'observed'),
                ahead_hundredths=int(Decimal(row['ahead_estimate'])*100),
                queue_hundredths=int(Decimal(row['queue_ahead'])*100),
                depth_hundredths=int(Decimal(row['visible_depth'])*100),
                depletion_hundredths=int(Decimal(row['depletion_per_second'])*100),
                queue_age_ms=max(0, int(row['queue_age_seconds']*1000)),
                horizon_ms=int(row['horizon_seconds']*1000),
                eta_ms=None if eta is None else int(Decimal(eta)*1000))

    async def run_queue_reader(self):
        """D-145 Layer 2/4: read queue positions for every resting entry.

        Every QUEUE_READ_SECONDS, and sooner (at most every
        QUEUE_MIN_GAP_SECONDS) when an order is found without an anchor, such
        as right after an entry is acknowledged. A failed read changes nothing
        but the blind clock; it never raises out of the loop.
        """
        r = self.runtime
        self.queue_reader_active = True
        self._queue_wake = asyncio.Event()
        while not r.stop_requested.is_set():
            started = r.clock()
            self._queue_wake.clear()
            try:
                await self.read_queues_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.queue_read_failures += 1
            await asyncio.sleep(max(0.0, self.QUEUE_MIN_GAP_SECONDS-(r.clock()-started)))
            try:
                await asyncio.wait_for(self._queue_wake.wait(),
                                       max(0.0, self.QUEUE_READ_SECONDS-(r.clock()-started)))
            except TimeoutError:
                pass

    def _resting_entries(self):
        r, orders = self.runtime, {}
        for ticker in sorted(self.bindings):
            plan = r.management.current(ticker, require_market=False)
            if plan is None or plan.inventory.blockers:
                continue
            rows = tuple(row.order for row in plan.inventory.orders if not row.order.terminal)
            if rows:
                orders[ticker] = rows
        return orders

    async def read_queues_once(self):
        """One anchored reading of every resting entry; returns reads made."""
        from .reward_runtime import RuntimeRewards
        r = self.runtime
        if r.reads is None or r.stop_requested.is_set():
            return 0
        orders = self._resting_entries()
        live = {o.order_id for rows in orders.values() for o in rows}
        for table in (self._anchors, self._blind_since):
            for key in tuple(table):
                if key not in live:
                    table.pop(key)
        groups, current = [], ''
        for ticker in orders:
            value = current+','+ticker if current else ticker
            if len(value) > 2048 and current:
                groups.append(current)
                current = ticker
            else:
                current = value
        if current:
            groups.append(current)
        reads = 0
        for group in groups:
            marks = {}
            for ticker in group.split(','):
                shard, book = r.management._book(ticker)
                if book is None or not book.valid:
                    continue
                for order in orders[ticker]:
                    marks[order.order_id] = (ticker, order, book, shard.generation,
                                             FillRisk.anchor_marks(book, order))
            if not marks:
                continue
            started = r.clock()
            result = await r.reads.read('queue_positions', reason='protection',
                subaccount=r.account.subaccount, market_tickers=group)
            reads += 1
            for order_id, (ticker, ahead) in RuntimeRewards._queue_rows(result.payload).items():
                mark = marks.get(order_id)
                if mark is None or mark[0] != ticker:
                    continue
                _, order, book, generation, anchor = mark
                self._anchors[order_id] = QueueAnchor(ticker, order.side, order.yes_price,
                    ahead, started, book.lineage, generation, anchor)
        self.queue_reads += reads
        self._queue_ok_at = r.clock()
        for ticker in orders:
            if r.stop_requested.is_set():
                break
            self.refresh(ticker)
            r._request_quote_dispatch(ticker)
            await asyncio.sleep(0)
        return reads

    def _anchor_for(self, plan, order, shard, book):
        a = self._anchors.get(order.order_id)
        if a is None:
            return None, 'anchor_missing'
        if (book is None or not book.valid or a.lineage is not book.lineage
                or a.ticker != plan.ticker
                or not a.book_generation == shard.generation == plan.book_generation
                or (a.side, a.yes_price) != (order.side, order.yes_price)):
            return None, 'anchor_invalid'
        return a, None

    def _fill_risk_anchored(self, plan, program):
        """D-145 Layer 3: time-to-fill, short queue, or blind for too long."""
        r, ticker, now = self.runtime, plan.ticker, self.runtime.clock()
        shard, book = r.management._book(ticker)
        floor = active_config().entry_contracts
        samples = []
        for row in plan.inventory.orders:
            order = row.order
            anchor, gap = self._anchor_for(plan, order, shard, book)
            sample = None
            if anchor is not None:
                sample = self.fill_risk.observe(order=order, book=book, program=program,
                    identity=(r.writer.epoch, r.account.generation, plan.book_generation),
                    ahead=anchor.ahead, queue_at=anchor.read_mono, now=now,
                    interval=self.QUEUE_READ_SECONDS, anchor=anchor.marks, floor=floor)
                gap = gap or ('book_unavailable' if sample is None else None)
            if sample is not None:
                self._blind_since.pop(order.order_id, None)
                samples.append(sample)
                continue
            if self._queue_wake is not None:
                self._queue_wake.set()
            self._risk_gap(ticker, gap)
            blind = now-self._blind_since.setdefault(order.order_id, now)
            if blind > self.BLIND_SECONDS:
                samples.append(dict(order_id=order.order_id, side=order.side,
                    observed_mono=now, withdraw=True, trigger='blind', anchored=False,
                    state='BLIND', blind_seconds=blind))
        if not samples:
            return False
        return self._risk_decision(plan, program, samples, None)

    def _fill_risk(self, plan, program):
        if self.queue_reader_active:
            return self._fill_risk_anchored(plan, program)
        r, ticker = self.runtime, plan.ticker
        proof = self._risk_queues.get(ticker)
        if proof is None:
            self._risk_gap(ticker, 'queue_missing')
            return False
        if (proof.writer_epoch != r.writer.epoch or proof.program != program
                or proof.account_generation != r.account.generation
                or proof.book_generation != plan.book_generation
                or proof.signature != r.rewards._signature(plan)):
            self._risk_queues.pop(ticker, None)
            self._risk_gap(ticker, 'identity_changed')
            return False
        if (utc(r.now()) >= proof.valid_until
                or not 0 <= r.clock()-proof.queue_started_mono < 5):
            self._risk_queues.pop(ticker, None)
            self._risk_gap(ticker, 'queue_expired')
            return False
        shard, book = r.management._book(ticker)
        if book is None or shard.generation != proof.book_generation:
            self._risk_gap(ticker, 'book_unavailable')
            return False
        queue = dict(proof.queue_positions)
        samples = []
        for row in plan.inventory.orders:
            if row.order.order_id not in queue:
                return False
            sample = self.fill_risk.observe(order=row.order, book=book, program=program,
                identity=(r.writer.epoch, r.account.generation, plan.book_generation),
                ahead=queue[row.order.order_id], queue_at=proof.queue_started_mono,
                now=r.clock(), interval=r.rewards.reflection_interval)
            if sample is not None:
                samples.append(sample)
        if not samples:
            return False
        return self._risk_decision(plan, program, samples, proof.valid_until)

    def _risk_decision(self, plan, program, samples, valid_until):
        r, ticker = self.runtime, plan.ticker
        self.samples[ticker] = dict(state='FILL_RISK_ESTIMATE',
            observed_at=utc(r.now()).isoformat(),
            valid_until=None if valid_until is None else valid_until.isoformat(),
            fill_risk=samples, action='retain')
        self._risk_sample_log(ticker, samples)
        if not any(s['withdraw'] for s in samples):
            self._risk_since.pop(ticker, None)
            return False
        if ticker not in self._risk_since:
            for trigger in {s.get('trigger') for s in samples if s['withdraw']}:
                if trigger in self.risk_triggers:
                    self.risk_triggers[trigger] += 1
        self._risk_since.setdefault(ticker, r.clock())
        if self.cycle is not None:
            if self.cycle.reason == 'fill_risk_withdrawal':
                if self.cycle.ticker == ticker:
                    return True
                # D-131 item 7: latch now instead of waiting for the primary
                # cycle's full terminal/fill reconciliation.
                return self._latch_secondary(plan, program)
            service = r.dispatch_supervisor
            active = service.dispatcher.status().active if service is not None else None
            if active is not None and active[0] in {self.cycle.ticker, plan.ticker}:
                return False  # Join an in-flight command for either market.
            # A flat market waiting for ordinary repricing must not monopolize
            # emergency withdrawal. Its exact outstanding orders remain owned
            # and will be reevaluated through the same manager later.
            r.engine.dirty.mark(self.cycle.ticker)
            r.engine.wake.set()
            self.cycle = None
        self._start(plan, program, 'fill_risk_withdrawal', False)
        return self.cycle is not None and self.cycle.ticker == ticker

    def _identity(self, plan, program):
        return (program, self.runtime.writer.epoch, self.runtime.account.generation,
                tuple(sorted((row.order.order_id, row.order.side, row.order.yes_price,
                              row.order.remaining, row.order.exchange_index)
                             for row in plan.inventory.orders)))

    def _observe_drift(self, ticker, identity, mono, valid_for):
        """Accumulate only time covered by prior fresh evidence.

        Brief source-join gaps remain unknown rather than erasing established
        evidence. A long gap or any ownership/generation change starts over.
        """
        previous = self._dwell.get(ticker)
        verified = 0.0
        if (isinstance(previous, DriftEvidence) and previous.identity == identity
                and 0 <= mono-previous.observed_at <= self.MAX_EVIDENCE_GAP_SECONDS):
            verified = previous.verified_seconds + max(
                0.0, min(mono, previous.valid_until)-previous.observed_at)
        current = DriftEvidence(identity, verified, mono, mono+max(0.0, valid_for))
        self._dwell[ticker] = current
        return current

    def _cycle_identity_current(self, plan, cycle):
        current = self._identity(plan, cycle.program)
        expected = cycle.evidence_identity
        return (isinstance(expected, tuple) and len(expected) == 4
                and current[:3] == expected[:3]
                and set(current[3]).issubset(set(expected[3])))

    def _cycle_current(self, plan, cycle):
        return (cycle.evidence_valid_until is None
                or (utc(self.runtime.now()) < cycle.evidence_valid_until
                    and self._cycle_identity_current(plan, cycle)))

    def _start(self, plan, program, reason, reenter, *, evidence_valid_until=None,
               evidence_identity=None):
        r = self.runtime
        if self.cycle is not None or r.entry_pause_active:
            return
        if reenter:
            rows = r.current_entry_orders()
            window = getattr(r.accounting_result, 'window', None)
            if rows is None or window is None or len(rows)-len(plan.inventory.orders)+2 > window.cap:
                return  # In particular, do not churn an intentional odd-cap orphan.
        service = r.dispatch_supervisor
        active = service.dispatcher.status().active if service is not None else None
        # No new repricing episode during an in-flight mutation. D-130: a risk
        # withdrawal latches during another market's command (its cancel
        # queues behind it), but still joins a command for this same market.
        if active is not None and (reason != 'fill_risk_withdrawal'
                                   or active[0] == plan.ticker):
            return
        ids = tuple(sorted(o.order.order_id for o in plan.inventory.orders))
        self.cycle = MaintenanceCycle(plan.ticker, program, ids, reason, reenter,
                                      evidence_valid_until, evidence_identity)
        self._cycle_started = self._cycle_latched = r.clock()
        self._cycle_acks.clear()
        if reason == 'fill_risk_withdrawal':
            self._cycle_started = self._risk_since.get(plan.ticker, self._cycle_started)
            # The decision is latched for exact owned IDs through cancellation
            # reconciliation. No score lease can authorize new entries here.
            self._risk_cooldown = {t:until for t,until in self._risk_cooldown.items()
                                   if until > r.clock()}
            repeats = self._record_withdrawal(plan.ticker)
            self._research_withdrawal(plan, 'primary')
            self._risk_cooldown[plan.ticker] = r.clock()+self._risk_cooldown_seconds(plan.ticker)
            r.diagnostics.emit('fill_risk_withdrawal', market=plan.ticker, count=repeats)
        if evidence_valid_until is None:
            self._dwell.pop(plan.ticker, None)
        self.samples[plan.ticker]['action'] = reason
        dwell = self._dwell.get(plan.ticker)
        r.diagnostics.emit('maintenance_cycle_started', market=plan.ticker,
            maintenance_reason=reason, count=len(ids),
            dwell_ms=int(dwell.verified_seconds*1000) if isinstance(dwell, DriftEvidence) else None)

    def refresh(self, ticker):
        r, now = self.runtime, utc(self.runtime.now())
        program = self.bindings.get(ticker)
        if program is None:
            return
        plan = r.management.current(ticker, require_market=False)
        if (r.stop_requested.is_set() or r.engine.failed or r.writer.failed
                or not r.account.connected or r.engine.private or r.account._processing):
            if ticker in self._risk_queues:
                self._risk_gap(ticker, 'private_unavailable')
            return
        if plan is None or plan.inventory.blockers:
            if ticker in self._risk_queues:
                self._risk_gap(ticker, 'inventory_unavailable')
            return
        inventory = plan.inventory
        c = self.cycle
        if inventory.position:
            self._risk_queues.pop(ticker, None)
            if c is not None and c.ticker == ticker:
                self._finish(ticker)
            self._finish_secondary(ticker)  # Inventory policy takes over.
            self._dwell.pop(ticker, None)
            self._risk_since.pop(ticker, None)
            self.samples[ticker] = dict(state='INVENTORY', action='existing_exit_policy')
            return
        orders = inventory.orders
        if any(not o.owned or o.awaiting_fills or o.reducing or o.order.terminal
               for o in orders):
            self._risk_queues.pop(ticker, None)
            return
        journal = inventory.exit_journal
        if journal is None or journal.cancel_ids or journal.unresolved_ioc:
            return
        latched = self.risk_latched.get(ticker)
        if latched is not None:
            # Exact latched IDs drain without report/score renewal; the cycle
            # ends only when durable inventory no longer holds any of them.
            if not set(latched.order_ids) & {o.order.order_id for o in orders}:
                self._finish_secondary(ticker)
            return
        if orders and (c is None or c.ticker != ticker or c.reason != 'fill_risk_withdrawal'):
            self._fill_risk(plan, program)
            c = self.cycle
        # Only a latched cancellation decision may bypass report/score renewal.
        # Repricing, reentry, completion and capacity still need current account
        # proof. The dispatcher independently rereads exact owned entry IDs.
        if (c is not None and c.ticker == ticker and c.reason == 'fill_risk_withdrawal'
                and set(c.order_ids) & {o.order.order_id for o in orders}):
            return
        report = r.account.current_report(now)
        if report is None or not report.positions_match or report.audit.blockers:
            return
        if c is not None and c.ticker == ticker:
            if orders:
                if not set(c.order_ids) & {o.order.order_id for o in orders}:
                    self._finish(ticker)  # Acknowledged replacement, not cancel ACK.
                    return
                if self._cycle_current(plan, c):
                    return
                # A stale scoring decision cannot authorize cancellation. Keep
                # accumulated verified coverage and require a fresh observation
                # to recreate the cycle and dispatch proof.
                previous = self._dwell.get(ticker)
                if (isinstance(previous, DriftEvidence)
                        and self._cycle_identity_current(plan, c)):
                    mono = r.clock()
                    self._dwell[ticker] = DriftEvidence(
                        self._identity(plan, program), previous.verified_seconds,
                        mono, mono)
                self.cycle = None
                return self.refresh(ticker)
            if not c.reenter or now >= c.program.end:
                self._finish(ticker)
                self.bindings.pop(ticker, None)
                return
            window = getattr(r.accounting_result, 'window', None)
            entries = r.current_entry_orders()
            if (window is not None and window.start <= now < window.end
                    and entries is not None and len(entries)+2 > window.cap):
                self._finish(ticker)
                self.bindings.pop(ticker, None)
                return  # The ratchet may tighten while cancellation is pending.
            # Only the same program can re-enter this ticker. Other markets may
            # use free capacity; unknown local sources cannot stall their entries.
            # A freshly evaluated failed gate releases a flat/clear owner.
            if r.selection.current(ticker):
                observation = r.selection._observation(ticker)
                if observation is not None and c.program not in observation.programs:
                    self._finish(ticker)
                    self.bindings.pop(ticker, None)
                    return
                rows = r.selection.selector.board.markets.get(ticker, ())
                row = next((row for row in rows if row.program_id == c.program.program_id), None)
                if row is not None and (row.blockers or row.gross_remaining_usd is None
                        or row.gross_remaining_usd+self.credit(c.program) < 1):
                    self._finish(ticker)
                    self.bindings.pop(ticker, None)
                else:
                    r._entry_dirty = True
            return
        if not orders:
            self._risk_since.pop(ticker, None)
            return
        # Exact lifecycle deadlines do not require reward/reflection estimates.
        terms = plan.terms
        if program.end > now:
            due = r.clock()+(program.end-now).total_seconds()
            current_due = r.engine.deadlines.due_for(ticker)
            if current_due is None or due < current_due:
                r.engine.schedule(ticker, due)
        expired = now >= program.end
        if (terms is not None and terms.observed_at <= now < terms.valid_until
                and (not terms.active or now >= terms.deadline)):
            expired = True
        risk_samples = self.samples.get(ticker, {}).get('fill_risk', [])
        self.samples[ticker] = dict(state='UNKNOWN', action='retain_pending_evidence',
                                   fill_risk=risk_samples)
        if expired:
            self._start(plan, program, 'earning_window_ended', False)
            return
        rewards = r.rewards
        source = rewards._sources(ticker) if rewards else None
        quotes = rewards.reflected_quotes(ticker) if rewards else None
        if source is None or quotes is None or not quotes:
            return
        if not any(p == program for p in source[1].programs):
            return  # Missing/changed terms are not proof of zero earnings.
        plan, observation, report, book = source
        if r.selection.candidate_inputs is not None:
            if r.selection.candidate_inputs.blockers(ticker, now):
                return
        until = min(observation.valid_until, plan.terms.valid_until,
                    rewards.reflection_valid_until(ticker))
        if until <= now:
            return
        try:
            self._actual.invalidate(next(iter(self._actual.board.markets), ticker))
            self._actual.update(book, (program,), terms=plan.terms, now=now,
                valid_until=until, reflected=quotes, proposed=quotes)
            actual = self._actual.board.markets[ticker][0]
            self._target.invalidate(next(iter(self._target.board.markets), ticker))
            self._target.update(book, (program,), terms=plan.terms, now=now,
                valid_until=until, reflected=quotes)
            target = self._target.board.markets[ticker][0]
        except InvalidData:
            return
        self.samples[ticker] = dict(state='OBSERVED', observed_at=now.isoformat(),
            fill_risk=risk_samples,
            valid_until=until.isoformat(), program_id=program.program_id,
            orders=[dict(side=q.side, price=str(q.yes_price), remaining=str(q.quantity)) for q in quotes],
            quote_statuses=actual.quote_statuses,
            bid_reference=str(actual.bid_reference), ask_reference=str(actual.ask_reference),
            bid_cutoff=str(actual.bid_cutoff), ask_cutoff=str(actual.ask_cutoff),
            target_blockers=target.blockers, action='retain')
        known_failures = {'proposed_quote_not_scoring', 'insufficient_two_sided_depth',
                          'exit_depth_missing', 'entry_retained_value_below_minimum',
                          'entry_downside_above_cap',
                          'market_or_program_inactive', 'entry_horizon_ended'}
        if set(actual.blockers+target.blockers)-known_failures:
            self.samples[ticker]['state'] = 'UNKNOWN'
            return
        # D-161 stop the waste: a contract that cannot reach Kalshi's $1 floor
        # even resting all of its remaining earning time pays nothing, so our
        # orders there are pure fill risk. Needs a live reward estimate.
        finish = getattr(r, 'finish_line', None)
        if (finish is not None and actual.gross_hourly_usd is not None
                and finish.hopeless(program.program_id, actual.gross_hourly_usd,
                                    actual.earning_until or actual.program_end, now)):
            finish.drop(program.program_id, now)
            self._start(plan, program, 'cannot_reach_payout_minimum', False)
            return
        # A qualifying incumbent is never displaced by the global rank or by
        # reaching $1. Only lost price weight/qualification or an incomplete
        # pair requests maintenance. Better-than-reference full-weight stays.
        complete = (len(quotes) == 2 and {q.side for q in quotes} == {'bid','ask'}
                    and all(q.quantity == active_config().entry_contracts for q in quotes))
        drift = (actual.quote_statuses != ('full_price_weight','full_price_weight')
                 or not complete or bool(actual.blockers))
        target_ok = (not target.blockers and target.gross_remaining_usd is not None
                     and target.gross_remaining_usd+self.credit(program) >= 1)
        if not drift:
            self._dwell.pop(ticker, None)
            return
        # Count only intervals covered by fresh observations. Brief unknown gaps
        # do not count and do not erase prior evidence; long gaps and identity
        # changes reset it. This avoids starvation at the normal account/
        # reflection cadence without treating missing evidence as bad economics.
        mono = r.clock()
        identity = self._identity(plan, program)
        evidence = self._observe_drift(
            ticker, identity, mono, (until-now).total_seconds())
        self.samples[ticker]['dwell_verified_seconds'] = evidence.verified_seconds
        self.samples[ticker]['dwell_gap_limit_seconds'] = self.MAX_EVIDENCE_GAP_SECONDS
        delay = self.REPRICE_DWELL_SECONDS if target_ok else self.UNSCORING_DWELL_SECONDS
        if evidence.verified_seconds < delay or mono < self._cooldown.get(ticker, 0):
            return
        if target_ok:
            self._start(plan, program, 'restore_reference_pair', True,
                        evidence_valid_until=until, evidence_identity=identity)
        elif not complete:
            # A lone surviving entry cannot earn the intended two-sided score.
            # If a fresh replacement pair no longer clears the minimum reward
            # gate, withdraw the orphan after the conservative unscoring dwell
            # and let ordinary ranked selection use the released capacity.
            self._start(plan, program, 'incomplete_pair_below_minimum', False,
                        evidence_valid_until=until, evidence_identity=identity)
        elif actual.blockers:
            self._start(plan, program, 'persistently_unscoring', False,
                        evidence_valid_until=until, evidence_identity=identity)

    def cancel_target(self, plan):
        latched = self.risk_latched.get(plan.ticker) if plan is not None else None
        if latched is not None and not plan.inventory.position:
            for row in plan.inventory.orders:
                if (row.order.order_id in latched.order_ids and row.owned
                        and not row.reducing and not row.awaiting_fills
                        and not row.order.terminal):
                    return row.order.order_id
            return None
        c = self.cycle
        if (c is None or plan is None or c.ticker != plan.ticker or plan.inventory.position
                or not self._cycle_current(plan, c)):
            return None
        for row in plan.inventory.orders:
            if (row.order.order_id in c.order_ids and row.owned and not row.reducing
                    and not row.awaiting_fills and not row.order.terminal):
                return row.order.order_id
        return None

    def status(self):
        c = self.cycle
        r = self.runtime
        current = {t for t,p in r.management._plans.items()
                   if p.inventory.orders or p.inventory.position}
        # D-130: owned working orders stay visible while their plan is being
        # rebuilt (for example during recovery), reported as UNKNOWN.
        current.update(rc.order.ticker for rc in r.account.order_states.values()
                       if rc.owned and not rc.order.terminal)
        if c is not None:
            current.add(c.ticker)
        current.update(self.risk_latched)
        now = utc(r.now())
        markets, observed, risk_current = {}, 0, 0
        for ticker in sorted(current):
            sample = self.samples.get(ticker)
            entry = (dict(sample) if sample is not None else
                     dict(state='UNKNOWN', action='retain_pending_evidence',
                          reason='no_current_sample'))
            until = entry.get('valid_until')
            if until is not None:
                fresh = now < datetime.fromisoformat(until)
                entry['source_current'] = fresh
                if fresh and entry.get('state') == 'OBSERVED':
                    observed += 1
            if any(0 <= r.clock()-row.get('observed_mono', -1e18) < 5
                   for row in entry.get('fill_risk', ())):
                risk_current += 1
            if len(markets) < 30:
                markets[ticker] = entry
        horizon = r.clock()-self.REPEAT_WINDOW_SECONDS
        repeats = {t: sum(1 for at in times if at >= horizon)
                   for t, times in self._withdrawals.items()}
        return dict(cycle=None if c is None else dict(ticker=c.ticker,
            program_id=c.program.program_id, reason=c.reason, reenter=c.reenter),
            latched_risk_cycles=sorted(self.risk_latched),
            max_risk_cycles=self.MAX_RISK_CYCLES,
            repeat_withdrawals_last_hour={t: n for t, n in sorted(
                repeats.items(), key=lambda item: -item[1])[:30] if n >= 2},
            coverage=dict(owned_markets=len(current), reward_observed_current=observed,
                          fill_risk_observed_last_5s=risk_current, historical_only=True),
            markets=markets,
            historical_samples=True, reprice_dwell_seconds=self.REPRICE_DWELL_SECONDS,
            unscoring_dwell_seconds=self.UNSCORING_DWELL_SECONDS,
            evidence_gap_limit_seconds=self.MAX_EVIDENCE_GAP_SECONDS,
            cooldown_seconds=30,
            fill_risk=self.fill_risk.status(),
            fill_cooldown=self.fill_cooldown_status(),
            sweep_filter=self.sweep_status(),
            risk_cooldowns={t:max(0, until-self.runtime.clock()) for t,until in self._risk_cooldown.items()
                            if until > self.runtime.clock()},
            fill_protection=dict(reader_active=self.queue_reader_active,
                current=self.protection_current(), anchored_orders=len(self._anchors),
                blind_orders=len(self._blind_since), reads=self.queue_reads,
                read_failures=self.queue_read_failures, triggers=dict(self.risk_triggers),
                read_seconds=self.QUEUE_READ_SECONDS, blind_limit_seconds=self.BLIND_SECONDS),
            risk_observation=dict(retained_markets=len(self._risk_queues),
                gap_counts={t:dict(c) for t,c in self._risk_gap_counts.items() if t in current}),
            replaces_for_better_rank=False, estimate_only=True)
