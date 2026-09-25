"""Bounded incumbent maintenance; keys only, never a second order writer.

One pair withdraws at a time. Exact terminal/fill proof precedes a fresh pair
through the ordinary selector/writer. Recovery-only startup never resumes this
ephemeral policy; the existing supervisor drains durable orders first.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .selection import MarketSelector
from .fill_risk import FillRisk
from .values import InvalidData, utc


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


class QuoteMaintenance:
    REPRICE_DWELL_SECONDS = 30
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
        self._cycle_started = None
        self._cycle_acks = set()
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
                              self._risk_cooldown, self._risk_since):
                    table.pop(old, None)
        if self.bindings.get(program.ticker) != program:
            self._dwell.pop(program.ticker, None)
        self.bindings[program.ticker] = program

    def entry_allowed(self, ticker, program_id):
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
        if self.cycle is not None and self.cycle.reason == 'fill_risk_withdrawal':
            self._risk_cooldown[ticker] = self.runtime.clock()+self.fill_risk.policy.cooldown_seconds
        self.cycle = None
        self._cycle_started = None
        self._cycle_acks.clear()
        self._risk_since.pop(ticker, None)
        self._dwell.pop(ticker, None)
        self._cooldown[ticker] = self.runtime.clock()+30
        self.runtime._entry_dirty = True

    def dispatch_result(self, result):
        """Decision-to-durable-ACK time includes dispatch/reconciliation waiting."""
        from .dispatch import QUOTE_CANCEL
        c = self.cycle
        if (c is not None and self._cycle_started is not None
                and result.priority == QUOTE_CANCEL and result.state == 'ACK'
                and result.ticker == c.ticker and result.order_id in c.order_ids
                and result.order_id not in self._cycle_acks):
            self.fill_risk.cancel_ack(self.runtime.clock()-self._cycle_started)
            self._cycle_acks.add(result.order_id)

    def _fill_risk(self, plan, program):
        r, ticker = self.runtime, plan.ticker
        rewards = r.rewards
        source = rewards._sources(ticker) if rewards else None
        if source is not None and program not in source[1].programs:
            return False
        proof = rewards.queue_evidence(ticker, plan) if source is not None else None
        if proof is None:
            return False
        book = source[3]
        queue = dict(proof.queue_positions)
        samples = []
        self.fill_risk.prune(o.order.order_id for p in r.management._plans.values()
                             for o in p.inventory.orders)
        for row in plan.inventory.orders:
            if row.order.order_id not in queue:
                return False
            sample = self.fill_risk.observe(order=row.order, book=book, program=program,
                identity=(r.writer.epoch, r.account.generation, plan.book_generation),
                ahead=queue[row.order.order_id], queue_at=proof.queue_started_mono,
                now=r.clock(), interval=rewards.reflection_interval)
            if sample is not None:
                samples.append(sample)
        if not samples:
            return False
        self.samples[ticker] = dict(state='FILL_RISK_ESTIMATE',
            observed_at=utc(r.now()).isoformat(), valid_until=proof.valid_until.isoformat(),
            fill_risk=samples, action='retain')
        if not any(s['withdraw'] for s in samples):
            self._risk_since.pop(ticker, None)
            return False
        self._risk_since.setdefault(ticker, r.clock())
        if self.cycle is not None:
            if self.cycle.reason == 'fill_risk_withdrawal':
                return self.cycle.ticker == ticker
            service = r.dispatch_supervisor
            if service is not None and service.dispatcher.status().active is not None:
                return False
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
        if service is not None and service.dispatcher.status().active is not None:
            return  # No new maintenance episode during an in-flight mutation.
        ids = tuple(sorted(o.order.order_id for o in plan.inventory.orders))
        self.cycle = MaintenanceCycle(plan.ticker, program, ids, reason, reenter,
                                      evidence_valid_until, evidence_identity)
        self._cycle_started = r.clock()
        self._cycle_acks.clear()
        if reason == 'fill_risk_withdrawal':
            self._cycle_started = self._risk_since.get(plan.ticker, self._cycle_started)
            # The decision is latched for exact owned IDs through cancellation
            # reconciliation. No score lease can authorize new entries here.
            self._risk_cooldown = {t:until for t,until in self._risk_cooldown.items()
                                   if until > r.clock()}
            self._risk_cooldown[plan.ticker] = r.clock()+self.fill_risk.policy.cooldown_seconds
            r.diagnostics.emit('fill_risk_withdrawal', market=plan.ticker)
        if evidence_valid_until is None:
            self._dwell.pop(plan.ticker, None)
        self.samples[plan.ticker]['action'] = reason

    def refresh(self, ticker):
        r, now = self.runtime, utc(self.runtime.now())
        program = self.bindings.get(ticker)
        if program is None:
            return
        plan = r.management.current(ticker, require_market=False)
        report = r.account.current_report(now)
        if (plan is None or report is None or not report.positions_match
                or report.audit.blockers or plan.inventory.blockers):
            return
        inventory = plan.inventory
        c = self.cycle
        if inventory.position:
            if c is not None and c.ticker == ticker:
                self._finish(ticker)
            self._dwell.pop(ticker, None)
            self._risk_since.pop(ticker, None)
            self.samples[ticker] = dict(state='INVENTORY', action='existing_exit_policy')
            return
        orders = inventory.orders
        if any(not o.owned or o.awaiting_fills or o.reducing or o.order.terminal
               for o in orders):
            return
        journal = inventory.exit_journal
        if journal is None or journal.cancel_ids or journal.unresolved_ioc:
            return
        if orders and (c is None or c.ticker != ticker or c.reason != 'fill_risk_withdrawal'):
            self._fill_risk(plan, program)
            c = self.cycle
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
                          'market_or_program_inactive', 'entry_horizon_ended'}
        if set(actual.blockers+target.blockers)-known_failures:
            self.samples[ticker]['state'] = 'UNKNOWN'
            return
        # A qualifying incumbent is never displaced by the global rank or by
        # reaching $1. Only lost price weight/qualification or an incomplete
        # pair requests maintenance. Better-than-reference full-weight stays.
        complete = (len(quotes) == 2 and {q.side for q in quotes} == {'bid','ask'}
                    and all(q.quantity == 10 for q in quotes))
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
        current = {t for t,p in self.runtime.management._plans.items()
                   if p.inventory.orders or p.inventory.position}
        if c is not None:
            current.add(c.ticker)
        return dict(cycle=None if c is None else dict(ticker=c.ticker,
            program_id=c.program.program_id, reason=c.reason, reenter=c.reenter),
            markets={t:self.samples[t] for t in sorted(current)[:30] if t in self.samples},
            historical_samples=True, reprice_dwell_seconds=self.REPRICE_DWELL_SECONDS,
            unscoring_dwell_seconds=self.UNSCORING_DWELL_SECONDS,
            evidence_gap_limit_seconds=self.MAX_EVIDENCE_GAP_SECONDS,
            cooldown_seconds=30,
            fill_risk=self.fill_risk.status(),
            risk_cooldowns={t:max(0, until-self.runtime.clock()) for t,until in self._risk_cooldown.items()
                            if until > self.runtime.clock()},
            replaces_for_better_rank=False, estimate_only=True)
