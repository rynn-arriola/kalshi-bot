"""Bounded advisory queue depletion estimates; never order authority.

Aggregate depth cannot identify which same-price orders canceled. Attribute
observed decreases to protection conservatively; do not credit replenishment
until the next exact queue observation. This is a scenario, not a probability.
"""
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
import math

from .values import InvalidData, count
from .quoting import _reference


@dataclass(frozen=True)
class FillRiskPolicy:
    cancel_floor_seconds: float = 2.0
    margin_seconds: float = 1.0
    cooldown_seconds: float = 300.0  # D-135: re-entry lockout cap after repeats
    trend_seconds: float = 10.0
    capacity: int = 256
    # D-135: first withdrawal in a market locks re-entry this long; each repeat
    # within the hour doubles it up to ``cooldown_seconds``.
    cooldown_min_seconds: float = 60.0

    def __post_init__(self):
        if (not all(type(v) in (float, int) and math.isfinite(v) and v > 0 for v in
                (self.cancel_floor_seconds, self.margin_seconds, self.cooldown_seconds,
                 self.trend_seconds, self.cooldown_min_seconds))
                or self.cooldown_min_seconds > self.cooldown_seconds
                or type(self.capacity) is not int
                or not 1 <= self.capacity <= 4096):
            raise InvalidData('invalid bounded fill-risk policy')

    def cooldown_for(self, repeats):
        """Re-entry lockout for the ``repeats``-th withdrawal within the hour."""
        return min(self.cooldown_seconds,
                   self.cooldown_min_seconds*2**min(max(0, repeats-1), 16))


@dataclass
class _Sample:
    identity: tuple
    queue_at: float
    queue_ahead: Decimal
    depth: Decimal
    ahead: Decimal
    at: float
    rate: Decimal = Decimal(0)
    rate_at: float = 0.0


class FillRisk:
    def __init__(self, policy=None):
        self.policy = policy or FillRiskPolicy()
        self.samples = {}
        self.cancel_seconds = deque(maxlen=128)

    def cancel_ack(self, seconds):
        if math.isfinite(seconds) and seconds >= 0:
            self.cancel_seconds.append(float(seconds))

    def cancel_budget(self):
        rows = sorted(self.cancel_seconds)
        p95 = rows[math.ceil(.95*len(rows))-1] if rows else 0
        return max(self.policy.cancel_floor_seconds, p95)

    def prune(self, order_ids):
        keep = set(order_ids)
        for key in tuple(self.samples):
            if key not in keep:
                self.samples.pop(key)

    @staticmethod
    def depth(book, order):
        ladder = book.bids if order.side == 'bid' else book.asks
        prices = reversed(ladder.prices) if order.side == 'bid' else iter(ladder.prices)
        total = Decimal(0)
        for price in prices:
            if (order.side == 'bid' and price < order.yes_price
                    or order.side == 'ask' and price > order.yes_price):
                break
            total += ladder.levels[price]
        # Exclude this order. Other same-price liquidity may be behind it;
        # the exact queue number is always the other cap on protection.
        return max(Decimal(0), total-order.remaining)

    def observe(self, *, order, book, program, identity, ahead, queue_at, now, interval):
        ahead = count(ahead, zero=True)
        if (not book.valid or order.ticker != book.ticker or program.ticker != book.ticker
                or order.side not in {'bid', 'ask'}
                or not all(math.isfinite(v) for v in (queue_at, now, interval))
                or interval <= 0 or not 0 <= now-queue_at < 5):
            return None
        depth = self.depth(book, order)
        key = order.order_id
        identity = (identity, program, key, order.side, order.yes_price, order.remaining)
        old = self.samples.get(key)
        if (old is not None and (old.identity != identity or now < old.at
                or now-old.at > self.policy.trend_seconds or queue_at < old.queue_at)):
            old = None
        estimate = min(ahead, depth)
        rate, rate_at = Decimal(0), now
        if old is not None:
            if now-old.rate_at <= self.policy.trend_seconds:
                rate, rate_at = old.rate, old.rate_at
            elapsed = now-old.at
            loss = max(Decimal(0), old.depth-depth)
            if elapsed > 0 and loss:
                measured = loss/Decimal(str(elapsed))
                if measured >= rate:
                    rate, rate_at = measured, now
            if queue_at == old.queue_at:
                estimate = min(estimate, max(Decimal(0), old.ahead-loss))
            elif ahead < old.queue_ahead:
                measured = (old.queue_ahead-ahead)/Decimal(str(queue_at-old.queue_at))
                if measured >= rate:
                    rate, rate_at = measured, now
        if key not in self.samples and len(self.samples) >= self.policy.capacity:
            return None  # Bounded unknown, never evict another live order's proof.
        self.samples[key] = _Sample(identity, queue_at, ahead, depth, estimate, now, rate, rate_at)
        seconds = (Decimal(0) if estimate == 0 else estimate/rate if rate else None)
        horizon = self.cancel_budget()+interval+self.policy.margin_seconds+(now-queue_at)
        reference_depth = program.target/5
        levels = book.bids.levels if order.side == 'bid' else book.asks.levels
        reference = _reference(levels, program.target, order.side)
        return dict(order_id=key, side=order.side, ahead_estimate=str(estimate),
            observed_mono=now,
            target_size=str(program.target), reference_depth=str(reference_depth),
            reference_price=None if reference is None else str(reference),
            ahead_fraction_of_reference_depth=str(estimate/reference_depth),
            queue_ahead=str(ahead), depletion_per_second=str(rate),
            visible_depth=str(depth),
            seconds_to_reach=None if seconds is None else str(seconds),
            cancel_budget_seconds=self.cancel_budget(), horizon_seconds=horizon,
            queue_age_seconds=now-queue_at,
            withdraw=seconds is not None and seconds <= Decimal(str(horizon)),
            state='ESTIMATED' if seconds is not None else 'WARMING_UP',
            estimate_only=True)

    def status(self):
        return dict(tracked_orders=len(self.samples), cancel_samples=len(self.cancel_seconds),
            cancel_budget_seconds=self.cancel_budget(),
            cancel_floor_seconds=self.policy.cancel_floor_seconds,
            margin_seconds=self.policy.margin_seconds,
            cooldown_seconds=self.policy.cooldown_seconds,
            cooldown_min_seconds=self.policy.cooldown_min_seconds,
            trend_seconds=self.policy.trend_seconds, estimate_only=True)
