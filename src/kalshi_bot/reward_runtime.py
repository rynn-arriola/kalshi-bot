"""Actual-order reward telemetry on existing runtime sources; no order authority."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib

from .quota import QuotaUnavailable
from .quoting import Quote
from .reward_checkpoint import RewardCheckpoint
from .reward_tracker import RewardTracker
from .values import InvalidData, count, identity, integer, utc


@dataclass(frozen=True)
class ReflectionProof:
    """Short-lived join of a complete private snapshot and venue queue evidence."""
    report: object
    account_generation: int
    account_revision: int
    signature: tuple
    valid_until: datetime


class RuntimeRewards:
    def __init__(self, runtime, *, scope, offline_fixture=False, checkpoint_path=None,
                 reflection_interval=4, checkpoint_interval=60):
        from .runtime import RecoveryRuntime
        if (not isinstance(runtime, RecoveryRuntime)
                or not (offline_fixture is True or runtime.observation_only
                        or runtime.live_components_enabled)
                or runtime.used or runtime.selection is None or runtime.rewards is not None
                or runtime.stop_requested.is_set()):
            raise InvalidData('unused matching offline reward runtime required')
        self.runtime = runtime
        self.tracker = RewardTracker(scope=scope)
        self.checkpoint = None if checkpoint_path is None else RewardCheckpoint(checkpoint_path)
        self.reflection_interval = integer(reflection_interval, 1, 5)
        self.checkpoint_interval = integer(checkpoint_interval, 10, 3600)
        self._reflection, self._proofs = {}, {}
        self.blocker = None
        self.started = self.used = self.running = self.stopping = self.failed = False
        self.task = None
        self.wake = asyncio.Event()
        self.reflection_requested = False
        self.reflection_attempts = self.reflection_completed = self.reflection_failures = 0
        self.checkpoint_saves = self.checkpoint_failures = 0
        self.last_reflection_at = self.last_checkpoint_at = None
        self.last_reflection_error = self.last_checkpoint_error = None

    @property
    def service_required(self):
        return self.runtime.reads is not None or self.checkpoint is not None

    def invalidate(self, ticker):
        self._reflection.pop(ticker,None)
        self._proofs.pop(ticker,None)
        self.tracker.invalidate(ticker)

    def _invalidate_all(self):
        self._reflection.clear()
        self._proofs.clear()
        for ticker in tuple(self.tracker._by_market):
            self.tracker.invalidate(ticker)

    def _sources(self, ticker):
        r = self.runtime
        if ticker not in r.engine.market_shard or not r.selection._available():
            return None
        plan = r.management.current(ticker)
        observation = r.selection._observation(ticker)
        report = r.account.current_report(r.now())
        now = utc(r.now())
        if (plan is None or plan.terms is None or observation is None or report is None
                or not observation.observed_at <= now < observation.valid_until
                or not report.positions_match or report.audit.blockers or plan.inventory.blockers):
            return None
        _, book = r.management._book(ticker)
        if book is None: return None
        return plan, observation, report, book

    @staticmethod
    def _orders(plan):
        receipts = plan.inventory.orders
        if len(receipts) > 30 or any(not r.owned or r.awaiting_fills or r.order.terminal
                or r.order.status != 'resting' or r.order.remaining <= 0 for r in receipts):
            return None
        return tuple(Quote(r.order.side,r.order.yes_price,r.order.remaining) for r in receipts)

    @staticmethod
    def _signature(plan):
        if RuntimeRewards._orders(plan) is None:
            return None
        return tuple(sorted((r.order.order_id,r.order.ticker,r.order.side,r.order.yes_price,
                             r.order.remaining,r.order.exchange_index)
                            for r in plan.inventory.orders))

    @staticmethod
    def _snapshot_signature(report, ticker):
        return tuple(sorted((o.order_id,o.ticker,o.book_side,o.yes_price,o.remaining,
                             o.exchange_index) for o in report.snapshot.orders
                            if o.ticker == ticker))

    @staticmethod
    def _queue_rows(payload):
        try:
            rows = payload['queue_positions']
            if not isinstance(rows,list) or len(rows) > 4096:
                raise InvalidData('invalid queue-position row bound')
            result = {}
            for row in rows:
                if not isinstance(row,dict):
                    raise InvalidData('invalid queue-position row')
                order_id = identity(row['order_id'])
                ticker = identity(row['market_ticker'])
                count(row['queue_position_fp'],zero=True)
                if order_id in result:
                    raise InvalidData('duplicate queue-position order')
                result[order_id] = ticker
            return result
        except (KeyError,TypeError) as exc:
            raise InvalidData('incomplete queue-position response') from exc

    def confirm_reflection_fixture(self, ticker, *, offline_fixture=False):
        """Test-only proof injection; production uses account-wide queue evidence."""
        if offline_fixture is not True:
            raise InvalidData('offline fixture proof flag required')
        source = self._sources(ticker)
        if source is None or self._orders(source[0]) is None:
            self.invalidate(ticker)
            raise InvalidData('current actual-order sources required')
        self._reflection[ticker] = source[:3]

    def _production_known(self, ticker, source, signature, now):
        proof = self._reflection.get(ticker)
        if not isinstance(proof,ReflectionProof):
            return False
        return (proof.report is source[2] and proof.account_generation == self.runtime.account.generation
                and proof.account_revision == self.runtime.account.revision
                and proof.signature == signature and now < proof.valid_until)

    def reflected_quotes(self, ticker):
        """Current operational reflection join, not atomic venue/payout proof."""
        if self.blocker is not None or self.failed or self.stopping:
            return None
        source = self._sources(ticker)
        if source is None:
            return None
        proof = self._reflection.get(ticker)
        fixture = isinstance(proof, tuple) and all(a is b for a,b in zip(proof, source[:3]))
        if fixture or self._production_known(ticker, source, self._signature(source[0]), utc(self.runtime.now())):
            return self._orders(source[0])
        return None

    def reflection_valid_until(self, ticker):
        proof = self._reflection.get(ticker)
        return (proof.valid_until if isinstance(proof, ReflectionProof)
                else utc(self.runtime.now())+timedelta(seconds=5))

    async def reflect_once(self):
        """Join one complete private snapshot to the all-resting queue endpoint.

        The queue endpoint supplies identity evidence absent from aggregate book
        WebSockets. It is not an atomic venue snapshot or payout confirmation.
        """
        r = self.runtime
        if self.stopping or r.reads is None:
            raise InvalidData('reflection reads unavailable')
        report = r.account.current_report(r.now())
        if report is None or report.audit is None or report.audit.blockers:
            raise InvalidData('current private account snapshot required')
        generation, revision = r.account.generation, r.account.revision
        expected = {o.order_id:o.ticker for o in report.snapshot.orders}
        if len(expected) != len(report.snapshot.orders) or len(expected) > 4096:
            raise InvalidData('invalid private resting-order scope')
        if not expected:
            self._invalidate_all()
            self.last_reflection_at = utc(r.now())
            return 0
        # Explicit complete market scope: the live endpoint can reject an
        # unfiltered request. Chunk only to the existing query-byte bound.
        groups, current_group = [], ''
        for ticker in sorted(set(expected.values())):
            if len(ticker) > 2048:
                raise InvalidData('reward market query exceeds bound')
            value = current_group+','+ticker if current_group else ticker
            if len(value) > 2048:
                groups.append(current_group)
                current_group = ticker
            else:
                current_group = value
        groups.append(current_group)
        actual = {}
        for group in groups:
            result = await r.reads.read('queue_positions',reason='reflection',
                coalesce_scope=('reward-reflection',r.account.subaccount,generation,revision),
                subaccount=r.account.subaccount, market_tickers=group)
            rows = self._queue_rows(result.payload)
            if (set(actual) & set(rows) or any(t not in group.split(',') for t in rows.values())):
                raise InvalidData('queue position chunk scope conflict')
            actual.update(rows)
        current = r.account.current_report(r.now())
        if (self.stopping or current is not report or (generation,revision) !=
                (r.account.generation,r.account.revision)):
            raise InvalidData('private account source changed during reflection')
        if actual != expected:
            raise InvalidData('queue positions disagree with complete resting-order snapshot')
        now = utc(r.now())
        valid_until = min(now+timedelta(seconds=5),report.observed_at+timedelta(seconds=5))
        if valid_until <= now:
            raise InvalidData('reflection source expired')
        proofs = {}
        for ticker in sorted(set(expected.values())):
            source = self._sources(ticker)
            signature = None if source is None else self._signature(source[0])
            if (source is None or source[2] is not report or signature is None
                    or signature != self._snapshot_signature(report,ticker)):
                continue
            proofs[ticker] = ReflectionProof(report,generation,revision,signature,valid_until)
        published = tuple(proofs)
        self._reflection = proofs
        for ticker in tuple(self.tracker._by_market):
            if ticker not in proofs:
                self.tracker.invalidate(ticker)
        # refresh() may invalidate the just-published proof when its joined
        # sources race forward.  Iterate a snapshot, not the same dictionary
        # that invalidate() is allowed to mutate.
        for ticker in published:
            self.refresh(ticker)
            if r.maintenance is not None:
                r.maintenance.refresh(ticker)
                r._request_quote_dispatch(ticker)
            # Deep-book arithmetic is bounded but may be expensive. Service
            # private ingress between owners; each following refresh rechecks
            # its sources rather than trusting the pre-yield reflection join.
            await asyncio.sleep(0)
        self.last_reflection_at = now
        return len(published)

    def refresh(self, ticker):
        if self.blocker is not None:
            return
        try:
            self._refresh(ticker)
        except InvalidData:
            self.blocker = 'reward_observation_rejected'
            self._invalidate_all()

    def _refresh(self, ticker):
        r = self.runtime
        source = self._sources(ticker)
        if source is None:
            self.invalidate(ticker)
            return
        plan, observation, report, book = source
        quotes = self._orders(plan)
        signature = self._signature(plan)
        reflected = self._reflection.get(ticker)
        now = utc(r.now())
        fixture_known = (isinstance(reflected,tuple) and all(
            a is b for a,b in zip(reflected,source[:3])))
        known = quotes == () or fixture_known or self._production_known(
            ticker,source,signature,now)
        ownership = repr(tuple(sorted((o.order.order_id,o.order.side,str(o.order.yes_price),
                                      str(o.order.remaining)) for o in plan.inventory.orders)))
        continuity = (r.writer.epoch,plan.generation,plan.book_generation,
                      hashlib.sha256(ownership.encode()).hexdigest())
        until = min(now+timedelta(seconds=5),observation.valid_until,plan.terms.valid_until,
                    report.observed_at+timedelta(seconds=5))
        if isinstance(reflected,ReflectionProof):
            until = min(until,reflected.valid_until)
        if until <= now:
            self.invalidate(ticker)
            return
        programs = tuple(p for p in observation.programs
                         if plan.inventory.orders or p.program_id in self.tracker.records)
        if programs and quotes is not None:
            try:
                self.tracker.observe_many(programs,book=book,bands=plan.terms.bands,quotes=quotes,
                    reflected_known=known,at=now,valid_until=until,continuity=continuity,
                    market_open=plan.terms.active)
            except InvalidData:
                for program in programs:
                    self.tracker.record(program,at=now,valid_until=until,rate=None,
                                        reason='unsupported_terms')
        elif programs:
            for program in programs:
                self.tracker.record(program,at=now,valid_until=until,rate=None,
                                    reason='source_unverified')
        self._proofs[ticker] = source[:3]

    def current(self, ticker):
        if self.blocker is not None:
            return False
        source = self._sources(ticker)
        if source is None:
            self.invalidate(ticker)
            return False
        proof = self._proofs.get(ticker)
        return proof is not None and all(a is b for a,b in zip(proof,source[:3]))

    def progress(self, program_id):
        record = self.tracker.records[program_id]
        ticker = record.program.ticker
        plan = self.runtime.management.current(ticker)
        exit_at = plan.terms.deadline if plan is not None and plan.terms is not None else self.runtime.now()
        return self.tracker.progress(program_id,now=self.runtime.now(),exit_at=exit_at,
                                     source_current=self.current(ticker))

    async def start(self):
        if self.started or self.used or self.stopping:
            raise InvalidData('reward service cannot be started')
        if self.checkpoint is not None:
            if not self.checkpoint.path.parent.is_dir():
                raise InvalidData('reward checkpoint parent does not exist')
            if self.checkpoint.path.exists():
                await self.checkpoint.load(self.tracker)
        self.started = True

    async def _save(self):
        if self.checkpoint is None:
            return
        try:
            await self.checkpoint.save(self.tracker)
            self.checkpoint_saves += 1
            self.last_checkpoint_at = utc(self.runtime.now())
            self.last_checkpoint_error = None
        except (InvalidData,OSError) as exc:
            self.checkpoint_failures += 1
            self.last_checkpoint_error = type(exc).__name__
            self.blocker = self.blocker or 'reward_checkpoint_failed'
            self._invalidate_all()

    async def _reflect(self):
        self.reflection_attempts += 1
        try:
            await self.reflect_once()
            self.reflection_completed += 1
            self.last_reflection_error = None
        except (InvalidData,QuotaUnavailable,TimeoutError,OSError) as exc:
            self.reflection_failures += 1
            self.last_reflection_error = type(exc).__name__
            self._invalidate_all()

    def stop(self):
        self.stopping = True
        self._invalidate_all()
        self.wake.set()

    def request_reflection(self):
        """Align the next queue join with a newly reconciled account report."""
        if (self.runtime.reads is not None and self.started
                and not self.stopping and not self.failed):
            self.reflection_requested = True
            self.wake.set()

    async def close(self):
        self.stop()
        task = self.task
        if task is None or task is asyncio.current_task():
            return
        cancelled = False
        while not task.done():
            try:
                await asyncio.wait((task,))
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def run(self):
        if not self.started or self.used or not self.service_required:
            raise InvalidData('reward service is not ready')
        self.used = self.running = True
        self.task = asyncio.current_task()
        next_reflection = self.runtime.clock()
        next_checkpoint = self.runtime.clock()+self.checkpoint_interval
        try:
            while not self.stopping:
                self.wake.clear()
                now = self.runtime.clock()
                if (self.runtime.reads is not None
                        and (now >= next_reflection or self.reflection_requested)):
                    self.reflection_requested = False
                    await self._reflect()
                    next_reflection = self.runtime.clock()+self.reflection_interval
                if self.checkpoint is not None and self.runtime.clock() >= next_checkpoint:
                    await self._save()
                    next_checkpoint = self.runtime.clock()+self.checkpoint_interval
                if self.stopping:
                    break
                deadlines = []
                if self.runtime.reads is not None: deadlines.append(next_reflection)
                if self.checkpoint is not None: deadlines.append(next_checkpoint)
                delay = max(.01,min(deadlines)-self.runtime.clock())
                try:
                    await asyncio.wait_for(self.wake.wait(),delay)
                except TimeoutError:
                    pass
        except Exception:
            self.failed = True
            raise
        finally:
            try:
                if self.checkpoint is not None:
                    await self._save()
            finally:
                self.running = False

    def status(self):
        return dict(tracked_programs=len(self.tracker.records), revision=self.tracker.revision,
                    blocker=self.blocker, started=self.started, running=self.running,
                    stopping=self.stopping, failed=self.failed,
                    reflection_attempts=self.reflection_attempts,
                    reflection_completed=self.reflection_completed,
                    reflection_failures=self.reflection_failures,
                    reflection_requested=self.reflection_requested,
                    checkpoint_configured=self.checkpoint is not None,
                    checkpoint_saves=self.checkpoint_saves,
                    checkpoint_failures=self.checkpoint_failures,
                    last_reflection_at=(self.last_reflection_at.isoformat()
                                        if self.last_reflection_at else None),
                    last_checkpoint_at=(self.last_checkpoint_at.isoformat()
                                        if self.last_checkpoint_at else None),
                    last_reflection_error=self.last_reflection_error,
                    last_checkpoint_error=self.last_checkpoint_error,
                    estimate_only=True, paid_rewards_verified=False,
                    production_reflection_available=(self.runtime.reads is not None
                        and self.started and not self.stopping and not self.failed),
                    program_progress=self._progress_status(), authorized=False)

    def _progress_status(self):
        # Report only currently managed owners (30 orders, <=16 programs each).
        # No filesystem/network work and no scan of archived reward history.
        from dataclasses import asdict
        result = []
        for ticker, plan in self.runtime.management._plans.items():
            if not plan.inventory.orders and not plan.inventory.position:
                continue
            for key in sorted(self.tracker._by_market.get(ticker, ())):
                if len(result) >= 480:
                    return result
                result.append(asdict(self.progress(key)))
        return result
