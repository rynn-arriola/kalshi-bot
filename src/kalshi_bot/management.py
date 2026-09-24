"""Bounded advisory inventory plans. Never dispatches orders/cancels/IOC."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .orders import InventoryPlan, inventory_plan
from .exits import ExitTerms, ExitPlan, plan_exit
from .values import InvalidData, utc


@dataclass(frozen=True)
class ManagedPlan:
    ticker: str
    observed_at: datetime
    generation: int
    account_revision: int
    book_generation: int
    book_revision: int
    inventory: object
    passive: InventoryPlan
    blockers: tuple[str, ...]
    authorized: bool = False
    exit: ExitPlan | None = None
    terms: ExitTerms | None = None


class InventoryManager:
    def __init__(self, runtime):
        self.runtime = runtime
        runtime.writer.claim_management_owner(self)
        self._plans = {}
        self.unmanaged = set()
        self.terms = {}
        self._logged_states = {}  # bounded by managed market scope, no tick-by-tick logs
        self._inventory_revision = None
        self._inventory_cache = {}

    def set_terms(self, terms):
        if not isinstance(terms, ExitTerms) or terms.ticker not in self.runtime.engine.market_shard:
            raise InvalidData("exit terms outside managed scope")
        self.terms[terms.ticker] = terms
        self.invalidate(terms.ticker)
        self.runtime.engine.dirty.mark(terms.ticker)
        self.runtime.engine.wake.set()

    def revoke_terms(self, ticker):
        self.terms.pop(ticker, None)
        self.invalidate(ticker)

    def invalidate(self, ticker):
        self._plans.pop(ticker, None)

    def _book(self, ticker):
        engine = self.runtime.engine
        name = engine.market_shard.get(ticker)
        if name is None:
            return None, None
        shard = engine.shards[name]
        book = shard.books.get(ticker)
        received = engine.book_received.get(ticker)
        if (shard.failed or book is None or not book.valid or engine.public[name]
                or received is None or not 0 <= self.runtime.clock()-received <= 5):
            return shard, None
        return shard, book

    def _current(self, ticker, *, plan_writer_revision, current_writer_revision,
                 require_market=True):
        plan = self._plans.get(ticker)
        account = self.runtime.account
        writer = self.runtime.writer
        if (plan is None or not account.connected or self.runtime.engine.stopped
                or writer.failed or writer.revision != current_writer_revision):
            return None
        if require_market and plan.terms is not self.terms.get(ticker):
            return None
        if (require_market and plan.terms is not None
                and not plan.terms.observed_at <= utc(self.runtime.now()) < plan.terms.valid_until):
            return None
        shard, book = self._book(ticker) if require_market else (None, None)
        if ((plan.generation, plan.account_revision) != (account.generation, account.revision)
                or (plan.inventory.writer_epoch, plan.inventory.writer_revision) !=
                   (writer.epoch, plan_writer_revision)
                or not timedelta(0) <= utc(self.runtime.now())-plan.observed_at <= timedelta(seconds=5)
                or (require_market and plan.book_generation != (shard.generation if shard else 0))
                or (require_market and plan.book_revision != (book.revision if book else -1))):
            return None
        return plan

    def current(self, ticker, *, require_market=True):
        revision = self.runtime.writer.revision
        return self._current(ticker, plan_writer_revision=revision,
                             current_writer_revision=revision,
                             require_market=require_market)

    def current_after_prepare(self, ticker, *, prior_revision, prepared_revision):
        if prepared_revision != prior_revision+1:
            return None
        return self._current(ticker, plan_writer_revision=prior_revision,
                             current_writer_revision=prepared_revision)

    def current_for_dispatch(self, ticker, *, prior_revision, require_market=True):
        """Source fence only, never a substitute for a prepared receipt.

        The sole executor checks the exact receipt/revision around begin_send;
        these are its one prepare and one SENDING revision advances. Any other
        write invalidates the receipt in the writer, even if sources agree.
        """
        revision = self.runtime.writer.revision
        if revision not in (prior_revision+1, prior_revision+2):
            return None
        return self._current(ticker, plan_writer_revision=prior_revision,
                             current_writer_revision=revision,
                             require_market=require_market)

    async def refresh(self, ticker, *, background=False):
        runtime, account = self.runtime, self.runtime.account
        if ticker not in runtime.engine.market_shard:
            if len(self.unmanaged) < runtime.writer.market_capacity:
                self.unmanaged.add(ticker)
            return None
        now = utc(runtime.now())
        generation, revision = account.generation, account.revision
        report = account.current_report(now)
        shard, book = self._book(ticker)
        book_generation = shard.generation
        book_revision = book.revision if book else -1
        terms = self.terms.get(ticker)
        # Pure durable inventory is independent of book/time. Reuse only within
        # the exact writer epoch/revision; plans and all source checks below are
        # still recomputed. One mutation invalidates the entire bounded cache.
        version = (runtime.writer.epoch, runtime.writer.revision, account.subaccount)
        if version != self._inventory_revision:
            self._inventory_cache.clear()
            self._inventory_revision = version
        inventory = self._inventory_cache.get(ticker) if runtime.broad_discovery else None
        if inventory is None:
            inventory = await runtime.writer.market_inventory(ticker, subaccount=account.subaccount)
            if (runtime.broad_discovery and version == self._inventory_revision
                    and version == (inventory.writer_epoch, inventory.writer_revision, account.subaccount)
                    and version == (runtime.writer.epoch, runtime.writer.revision, account.subaccount)):
                self._inventory_cache[ticker] = inventory
        # An advisory read can start before dispatch and complete after it has
        # pinned its own plan. Only the dispatch source may replace that plan;
        # real source changes remain visible to its unchanged final fences.
        if background and runtime.entry_dispatch_active(ticker):
            return None
        new_shard, new_book = self._book(ticker)
        if ((generation, revision) != (account.generation, account.revision) or not account.connected
                or (inventory.writer_epoch, inventory.writer_revision) !=
                   (runtime.writer.epoch, runtime.writer.revision)
                or runtime.engine.stopped or shard is not new_shard
                or book_generation != shard.generation
                or book_revision != (new_book.revision if new_book else -1)
                or terms is not self.terms.get(ticker)):
            self.invalidate(ticker)
            return None
        complete = (report is not None and report is account.current_report(now) and report.positions_match
                    and timedelta(0) <= now-report.observed_at <= timedelta(seconds=5)
                    and not inventory.blockers)
        if complete:
            # Complete enumeration must agree with exact durable working terms.
            visible = {o.order_id: (o.book_side, o.yes_price, o.remaining, o.exchange_index)
                       for o in report.snapshot.orders if o.ticker == ticker}
            owned = {r.order.order_id: (r.order.side, r.order.yes_price, r.order.remaining, r.order.exchange_index)
                     for r in inventory.orders if not r.order.terminal}
            complete = visible == owned
        touch = None
        if new_book is not None and inventory.position:
            touch = (new_book.asks.best(bid=False) if inventory.position > 0 else new_book.bids.best(bid=True))
        passive = inventory_plan(inventory.position, inventory.orders, ticker=ticker,
                                 touch=touch, complete_scope=complete)
        exit_plan = plan_exit(ticker=ticker, position=inventory.position, basis=inventory.yes_basis,
            first_seen_at=inventory.first_seen_at, orders=inventory.orders, book=new_book,
            terms=terms, journal=inventory.exit_journal, now=now, complete_scope=complete)
        if terms is not None:
            passive = exit_plan.passive
        blockers = list(inventory.blockers)+list(passive.blockers)
        if not runtime.live_components_enabled:
            blockers.append('live_authorization_missing')
        blockers.extend(exit_plan.blockers)
        if exit_plan.next_at is not None and exit_plan.next_at > now:
            due = runtime.clock()+(exit_plan.next_at-now).total_seconds()
            existing = runtime.engine.deadlines.due_for(ticker)
            if existing is None or due < existing: runtime.engine.schedule(ticker, due)
        if inventory.position:
            first = inventory.first_seen_at
            if first is None:
                blockers.append("inventory_age_unknown")
            elif now < first:
                blockers.append("inventory_clock_regressed")
            elif now-first >= timedelta(seconds=900):
                if terms is None: blockers.append("exit_terms_missing")
                # One notification, not an immediate-deadline busy loop.
            else:
                due = runtime.clock()+900-(now-first).total_seconds()
                existing = runtime.engine.deadlines.due_for(ticker)
                if existing is None or due < existing:
                    # Never postpone another component's earlier safety deadline.
                    # When it fires, refresh schedules any remaining age timer.
                    runtime.engine.schedule(ticker, due)
        result = ManagedPlan(ticker, now, generation, revision, book_generation, book_revision,
                             inventory, passive, tuple(dict.fromkeys(blockers)), exit=exit_plan, terms=terms)
        self._plans[ticker] = result
        state = (exit_plan.mode, result.blockers)
        previous = self._logged_states.get(ticker)
        journal = inventory.exit_journal
        material = bool(inventory.position or inventory.orders or (journal is not None and
                        (journal.unresolved_ioc or journal.cancel_ids)))
        # Broad discovery refreshes hundreds of empty markets. Account-scope
        # completeness can toggle their advisory blockers in bulk, but those
        # empty plans have no inventory action to diagnose. Retain logs only
        # for material markets and one final transition after they become empty.
        should_log = material or previous is not None
        if should_log and previous != state:
            runtime.diagnostics.emit('inventory_plan_changed', market=ticker, mode=exit_plan.mode,
                                     blocker_count=len(result.blockers), blockers=result.blockers,
                                     generation=generation, revision=inventory.writer_revision)
        if material:
            self._logged_states[ticker] = state
        else:
            self._logged_states.pop(ticker, None)
        return result
