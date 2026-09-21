"""Deterministic offline write-budget contracts; no transport or real clocks."""
from copy import copy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
import math
import unittest

from kalshi_bot.quota import QuotaScope, QuotaUnavailable
from kalshi_bot.values import InvalidData
from kalshi_bot.write_budget import (
    CANCEL, ORDERS, WriteBudget, WritePermit, WriteQuotaSnapshot,
)


WALL = 1700000000
ORDER = ORDERS + '/order-a'


def now(mono=0, wall=None):
    return mono, WALL + mono if wall is None else wall


def documents(*, rate=10, capacity=20, default=10, rows=None, grants=None):
    return (
        dict(usage_tier='fixture',
             read=dict(refill_rate=100, bucket_capacity=100),
             write=dict(refill_rate=rate, bucket_capacity=capacity),
             grants=[] if grants is None else grants),
        dict(default_cost=default, endpoint_costs=[
            dict(method='DELETE', path=CANCEL, cost=2),
        ] if rows is None else rows),
    )


def snapshot(*, scope=None, epoch=1, sequence=1, start=None, end=None,
             ttl=300, **kwargs):
    start = now() if start is None else start
    return WriteQuotaSnapshot(
        *documents(**kwargs), scope=QuotaScope() if scope is None else scope,
        epoch=epoch, sequence=sequence, start=start,
        end=start if end is None else end, ttl=ttl,
    )


def budget(evidence=None, *, shards=(0, 1, 2), at=None, **kwargs):
    return WriteBudget(snapshot() if evidence is None else evidence,
                       shards=shards, now=now() if at is None else at,
                       offline_fixture=True, **kwargs)


class WriteBudgetTests(unittest.TestCase):
    def reserve(self, core, *, t=1, method='POST', route=ORDERS, shard=0):
        permit = core.try_reserve(method, route, shard=shard, now=now(t))
        self.assertIsNotNone(permit)
        return permit

    def test_zero_startup_and_no_credit_for_observation_or_install_delay(self):
        evidence = snapshot(start=now(), end=now(5))
        core = budget(evidence, at=now(7))
        self.assertEqual(core.ready_delay('POST', ORDERS, shard=0, now=now(7)), 1)
        self.assertIsNone(core.try_reserve('POST', ORDERS, shard=0, now=now(7)))
        self.assertEqual(core.status(now=now(7)).buckets[0][1], 0)
        self.reserve(core, t=8)

    def test_default_and_method_specific_costs_from_documents(self):
        rows = [dict(method='GET', path=ORDERS, cost=99),
                dict(method='POST', path=CANCEL, cost=88),
                dict(method='DELETE', path='/trade-api/v2' + CANCEL, cost=3)]
        core = budget(snapshot(default=7, rows=rows))
        post = self.reserve(core)
        delete = self.reserve(core, method='DELETE', route=ORDER)
        self.assertEqual((post.cost, delete.cost), (7, 3))
        self.assertEqual(core.status(now=now(1)).buckets[0][1:3], (0, 10))
        other = budget(snapshot(default=6, rows=[]))
        self.assertEqual(self.reserve(other, method='DELETE', route=ORDER).cost, 6)

    def test_prefix_normalization_and_exact_cancel_order_binding(self):
        core = budget()
        permit = self.reserve(core, method='DELETE', route='/trade-api/v2' + ORDER)
        self.assertEqual(permit.route, ORDER)
        self.assertIs(core.consume(permit, 'DELETE', ORDER, shard=0, now=now(1)), permit)
        permit = self.reserve(core, method='DELETE', route=ORDER)
        with self.assertRaisesRegex(InvalidData, 'mismatch'):
            core.consume(permit, 'DELETE', ORDERS + '/order-b', shard=0, now=now(1))
        with self.assertRaises(InvalidData):
            core.consume(permit, 'DELETE', ORDER, shard=0, now=now(1))

    def test_duplicate_normalized_cost_keys_rejected_but_methods_distinct(self):
        for prefix in ('', '/trade-api/v2'):
            with self.subTest(prefix=prefix), self.assertRaises(InvalidData):
                snapshot(rows=[dict(method='DELETE', path=CANCEL, cost=2),
                               dict(method='DELETE', path=prefix + CANCEL, cost=3)])
        snapshot(rows=[dict(method='GET', path=ORDERS, cost=9),
                       dict(method='POST', path=ORDERS, cost=7)])

    def test_strict_cost_document_routes_and_values(self):
        for path in (ORDERS + '/', ORDERS + '?x=1', ORDERS + '#x',
                     '/portfolio//events/orders', '/portfolio/../orders',
                     '/portfolio/%65vents/orders', 'https://example.test/orders',
                     '/portfolio/events\\orders', '/portfolio/é/orders'):
            with self.subTest(path=path), self.assertRaises(InvalidData):
                snapshot(rows=[dict(method='POST', path=path, cost=1)])
        for method in ('post', ' POST', 'POST ', 'UNKNOWN', None, True):
            with self.subTest(method=method), self.assertRaises(InvalidData):
                snapshot(rows=[dict(method=method, path=ORDERS, cost=1)])
        for value in (True, 0, -1, 1.5, '2'):
            with self.subTest(value=value), self.assertRaises(InvalidData):
                snapshot(rows=[dict(method='POST', path=ORDERS, cost=value)])

    def test_full_limits_and_cost_documents_are_required(self):
        for section in ('usage_tier', 'read', 'write', 'grants'):
            limits, costs = documents()
            del limits[section]
            with self.subTest(section=section), self.assertRaises(InvalidData):
                WriteQuotaSnapshot(limits, costs, scope=QuotaScope(), epoch=1,
                                   sequence=1, start=now(), end=now(), ttl=30)
        for section in ('default_cost', 'endpoint_costs'):
            limits, costs = documents()
            del costs[section]
            with self.subTest(section=section), self.assertRaises(InvalidData):
                WriteQuotaSnapshot(limits, costs, scope=QuotaScope(), epoch=1,
                                   sequence=1, start=now(), end=now(), ttl=30)

    def test_evidence_copies_documents_and_is_frozen(self):
        limits, costs = documents()
        evidence = WriteQuotaSnapshot(limits, costs, scope=QuotaScope(), epoch=1,
                                     sequence=1, start=now(), end=now(), ttl=30)
        limits['write']['refill_rate'] = 1000000
        costs['endpoint_costs'][0]['cost'] = 1
        costs['default_cost'] = 1
        with self.assertRaises(FrozenInstanceError):
            evidence.rate = 99
        core = budget(evidence)
        self.assertEqual(core.ready_delay('POST', ORDERS, shard=0, now=now()), 1)
        self.assertEqual(self.reserve(core, method='DELETE', route=ORDER).cost, 2)

    def test_shards_independent_and_subaccounts_share_one_bucket(self):
        core = budget()
        # Subaccount identities deliberately do not partition the budget API.
        primary = self.reserve(core)
        subaccount = core.try_reserve('POST', ORDERS, shard=0, now=now(1))
        self.assertIsNone(subaccount)
        for shard in (1, 2):
            self.reserve(core, shard=shard)
        core.consume(primary, 'POST', ORDERS, shard=0, now=now(1))
        self.assertIsNone(core.try_reserve('POST', ORDERS, shard=0, now=now(1)))
        self.assertEqual(core.status(now=now(1)).outstanding, 2)

    def test_no_claim_of_scope_cloning_or_cross_instance_coordination(self):
        evidence = snapshot()
        first, second = budget(evidence), budget(evidence)
        permit = self.reserve(first)
        with self.assertRaises(InvalidData):
            second.consume(permit, 'POST', ORDERS, shard=0, now=now(1))
        # Sharing a scope is NOT a global registry or an account balance proof.
        self.reserve(second)
        first.consume(permit, 'POST', ORDERS, shard=0, now=now(1))
        self.assertFalse(first.status(now=now(1)).live_ready)

    def test_pre_send_check_does_not_consume_and_rejects_expiry(self):
        core = budget(snapshot(ttl=3))
        permit = self.reserve(core, t=1)
        self.assertIs(core.check_permit(permit, 'POST', ORDERS,
                                        shard=0, now=now(1)), permit)
        self.assertEqual(core.status(now=now(1)).outstanding, 1)
        with self.assertRaisesRegex(InvalidData, 'mismatch'):
            core.check_permit(permit, 'POST', ORDERS,
                              shard=1, now=now(1))
        self.assertIs(core.consume(permit, 'POST', ORDERS,
                                   shard=0, now=now(2)), permit)
        with self.assertRaises(InvalidData):
            core.check_permit(permit, 'POST', ORDERS, shard=0, now=now(2))
        later = budget(snapshot(ttl=3))
        expiring = self.reserve(later, t=1)
        with self.assertRaises(QuotaUnavailable):
            later.check_permit(expiring, 'POST', ORDERS, shard=0, now=now(3))

    def test_debit_once_consume_once_and_discard_without_refund(self):
        core = budget()
        first = self.reserve(core)
        self.assertEqual(core.status(now=now(1)).buckets[0][1], 0)
        core.consume(first, 'POST', ORDERS, shard=0, now=now(1))
        with self.assertRaises(InvalidData):
            core.consume(first, 'POST', ORDERS, shard=0, now=now(1))
        second = self.reserve(core, t=2)
        core.discard(second, now=now(2))
        self.assertEqual(core.status(now=now(2)).buckets[0][1:3], (0, 0))
        with self.assertRaises(InvalidData):
            core.discard(second, now=now(2))

    def test_retained_cleanup_does_not_refund_or_reconsume(self):
        core = budget()
        permit = self.reserve(core)
        self.assertFalse(core.discard_if_outstanding(copy(permit), now=now(1)))
        self.assertTrue(core.discard_if_outstanding(permit, now=now(1)))
        self.assertFalse(core.discard_if_outstanding(permit, now=now(1)))
        self.assertEqual(core.status(now=now(1)).buckets[0][1:3], (0, 0))
        used = self.reserve(core, t=2)
        core.consume(used, 'POST', ORDERS, shard=0, now=now(2))
        self.assertFalse(core.discard_if_outstanding(used, now=now(2)))

    def test_cached_route_rejects_malformed_inputs(self):
        core = budget()
        for method, route in ((None, ORDERS), ('POST', ['bad']),
                              ('POST', ORDERS+'/../x')):
            with self.subTest(method=method, route=route), self.assertRaises(InvalidData):
                core.try_reserve(method, route, shard=0, now=now(1))

    def test_pending_permits_cannot_bank_a_second_burst(self):
        core = budget()
        first = self.reserve(core, t=2)
        second = self.reserve(core, t=2)
        self.assertIsNone(core.ready_delay('POST', ORDERS, shard=0, now=now(100)))
        self.assertEqual(core.status(now=now(100)).buckets[0][1:3], (0, 20))
        core.consume(first, 'POST', ORDERS, shard=0, now=now(100))
        core.discard(second, now=now(100))
        self.assertEqual(core.ready_delay('POST', ORDERS, shard=0, now=now(100)), 1)
        self.assertEqual(core.status(now=now(101)).buckets[0][1], 10)

    def test_frozen_permit_rejects_copy_replace_and_forgery(self):
        core = budget()
        permit = self.reserve(core)
        with self.assertRaises(FrozenInstanceError):
            permit.cost = 1
        for forged in (copy(permit), replace(permit),
                       WritePermit('POST', ORDERS, 0, 1, 10), object(), None):
            with self.subTest(forged=forged), self.assertRaises(InvalidData):
                core.consume(forged, 'POST', ORDERS, shard=0, now=now(1))
        core.consume(permit, 'POST', ORDERS, shard=0, now=now(1))

    def test_bypassed_frozen_fields_checked_against_stored_terms(self):
        for name, value in (('method', 'DELETE'), ('route', ORDER), ('shard', 1),
                            ('revision', 2), ('cost', 1), ('shard', False),
                            ('revision', True), ('cost', 10.0)):
            with self.subTest(name=name, value=value):
                core = budget()
                permit = self.reserve(core)
                object.__setattr__(permit, name, value)
                with self.assertRaisesRegex(InvalidData, 'altered'):
                    core.consume(permit, 'POST', ORDERS, shard=0, now=now(1))
                self.assertEqual(core.status(now=now(1)).outstanding, 0)
                self.assertEqual(core.status(now=now(1)).buckets[0][2], 0)

    def test_dispatch_method_and_shard_must_match_and_failed_use_burns_permit(self):
        for method, route, shard in (('DELETE', ORDER, 0), ('POST', ORDERS, 1)):
            with self.subTest(method=method, shard=shard):
                core = budget()
                permit = self.reserve(core)
                with self.assertRaises(InvalidData):
                    core.consume(permit, method, route, shard=shard, now=now(1))
                with self.assertRaises(InvalidData):
                    core.consume(permit, 'POST', ORDERS, shard=0, now=now(1))

    def test_wall_and_monotonic_expiry_each_block_even_cancel(self):
        for expired in (now(10, WALL + 1), now(1, WALL + 10)):
            with self.subTest(expired=expired):
                core = budget(snapshot(ttl=10))
                permit = self.reserve(core, method='DELETE', route=ORDER)
                self.assertIsNone(core.ready_delay('DELETE', ORDER, shard=0, now=expired))
                self.assertIsNone(core.try_reserve('DELETE', ORDER, shard=0, now=expired))
                with self.assertRaises(QuotaUnavailable):
                    core.consume(permit, 'DELETE', ORDER, shard=0, now=expired)
                self.assertEqual(core.status(now=expired).outstanding, 0)
                self.assertEqual(core.status(now=expired).buckets[0][1], 0)

    def test_earliest_event_grant_expiry_in_both_clock_domains(self):
        grants = [dict(exchange_instance=lane, level='fixture', source='manual',
                       expires_ts=WALL + expiry)
                  for lane, expiry in (('margined', 1), ('event_contract', 20),
                                       ('event_contract', 5))]
        evidence = snapshot(grants=grants)
        self.assertEqual(evidence.grant_expiry, WALL + 5)
        for expired in (now(5, WALL + 2), now(2, WALL + 5)):
            core = budget(evidence)
            permit = self.reserve(core, t=2, method='DELETE', route=ORDER)
            with self.assertRaises(QuotaUnavailable):
                core.consume(permit, 'DELETE', ORDER, shard=0, now=expired)
        grants = [dict(exchange_instance='event_contract', level='fixture', source='manual')]
        self.assertIsNone(snapshot(grants=grants).grant_expiry)
        grants[0]['expires_ts'] = None
        with self.assertRaises(QuotaUnavailable):
            snapshot(grants=grants)

    def test_expiry_uses_start_of_observation_and_no_delay_past_deadline(self):
        core = budget(snapshot(ttl=5, start=now(), end=now(4)), at=now(4))
        self.assertIsNone(core.ready_delay('POST', ORDERS, shard=0, now=now(4)))
        self.assertEqual(core.ready_delay('DELETE', ORDER, shard=0, now=now(4)), .2)
        with self.assertRaises(QuotaUnavailable):
            budget(snapshot(ttl=5, start=now(), end=now(5)), at=now(5))

    def test_refresh_invalidates_permits_zeroes_tokens_and_advances_revision(self):
        evidence = snapshot()
        core = budget(evidence)
        permit = self.reserve(core, t=2)
        fresh = snapshot(scope=evidence.scope, sequence=2, start=now(2), default=4, rows=[])
        core.refresh(fresh, now=now(2))
        with self.assertRaises(InvalidData):
            core.consume(permit, 'POST', ORDERS, shard=0, now=now(2))
        self.assertEqual(core.status(now=now(2)).buckets[0][1:3], (0, 0))
        newer = self.reserve(core, t=3)
        self.assertEqual((newer.revision, newer.cost), (2, 4))

    def test_refresh_can_replace_expired_evidence_without_backfilling_tokens(self):
        evidence = snapshot(ttl=2)
        core = budget(evidence)
        self.assertEqual(core.status(now=now(3)).reason, 'write_quota_expired')
        core.refresh(snapshot(scope=evidence.scope, sequence=2, start=now(3)), now=now(3))
        self.assertIsNone(core.status(now=now(3)).reason)
        self.assertEqual(core.ready_delay('POST', ORDERS, shard=0, now=now(3)), 1)

    def test_refresh_rejects_reordered_future_stale_and_scope_switch(self):
        evidence = snapshot(start=now(2), end=now(3))
        for changes in (dict(sequence=1, start=now(4)),
                        dict(sequence=2, start=now(2)),
                        dict(sequence=2, start=now(3, WALL + 2)),
                        dict(sequence=2, start=now(6)),
                        dict(sequence=2, start=now(4), ttl=1),
                        dict(sequence=2, start=now(4), scope=QuotaScope())):
            core = budget(evidence, at=now(3))
            options = dict(scope=evidence.scope)
            options.update(changes)
            with self.subTest(changes=changes), self.assertRaises(InvalidData):
                core.refresh(snapshot(**options), now=now(5))
            self.assertEqual(core.status(now=now(5)).revision, 1)
        core = budget(evidence, at=now(3))
        core.refresh(snapshot(scope=evidence.scope, epoch=2, start=now(4)), now=now(5))
        self.assertEqual(core.status(now=now(5)).revision, 2)
        with self.assertRaises(InvalidData):
            core.refresh(snapshot(scope=evidence.scope, epoch=1, sequence=99,
                                  start=now(5)), now=now(5))

    def test_constructor_rejects_future_or_expired_observation(self):
        for evidence in (snapshot(start=now(1)),
                         snapshot(start=now(0, WALL + 1)),
                         snapshot(grants=[dict(exchange_instance='event_contract',
                                              level='x', source='manual', expires_ts=WALL)])):
            with self.assertRaises(QuotaUnavailable):
                budget(evidence)
        for kwargs in (dict(end=now(-1)), dict(end=now(0, WALL - 1)),
                       dict(ttl=0), dict(ttl=3601), dict(ttl=True),
                       dict(start=(float('nan'), WALL)), dict(start=(0,))):
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidData):
                snapshot(**kwargs)

    def test_429_invalidates_only_affected_shard_and_does_not_refill_during_pause(self):
        core = budget()
        affected = self.reserve(core)
        other = self.reserve(core, shard=1)
        core.pause_429(shard=0, seconds=5, now=now(1))
        with self.assertRaises(InvalidData):
            core.consume(affected, 'POST', ORDERS, shard=0, now=now(1))
        core.consume(other, 'POST', ORDERS, shard=1, now=now(1))
        self.assertEqual(core.ready_delay('POST', ORDERS, shard=0, now=now(1)), 6)
        self.assertIsNone(core.try_reserve('POST', ORDERS, shard=0, now=now(6)))
        self.reserve(core, t=7)

    def test_refresh_preserves_pause_and_late_429_affects_current_revision(self):
        evidence = snapshot()
        core = budget(evidence)
        core.pause_429(shard=0, seconds=10, now=now(1))
        core.refresh(snapshot(scope=evidence.scope, sequence=2, start=now(2)), now=now(2))
        self.assertEqual(core.ready_delay('POST', ORDERS, shard=0, now=now(2)), 10)
        current = self.reserve(core, t=3, shard=1)
        # A response from an earlier revision supplies its affected shard, not
        # a stale candidate/permit that could cause this signal to be ignored.
        core.pause_429(shard=1, seconds=4, now=now(3))
        with self.assertRaises(InvalidData):
            core.consume(current, 'POST', ORDERS, shard=1, now=now(3))
        self.assertEqual(core.status(now=now(3)).buckets[1][1:3], (0, 0))
        core.pause_429(shard=0, seconds=1, now=now(3))
        self.assertEqual(core.status(now=now(3)).buckets[0][3], 8)

    def test_429_on_expired_evidence_survives_later_refresh(self):
        evidence = snapshot(ttl=2)
        core = budget(evidence)
        core.pause_429(shard=0, seconds=10, now=now(3))
        core.refresh(snapshot(scope=evidence.scope, sequence=2, start=now(4)), now=now(4))
        self.assertEqual(core.ready_delay('POST', ORDERS, shard=0, now=now(4)), 10)

    def test_bounded_shards_and_permits_and_no_retained_tombstones(self):
        for shards in ((), tuple(range(129)), (0, 0), (-1,), (True,), (None,)):
            with self.subTest(shards=shards), self.assertRaises(InvalidData):
                budget(shards=shards)
        for cap in (0, 129, True):
            with self.assertRaises(InvalidData):
                budget(max_permits=cap)
        core = budget(snapshot(rate=1000, capacity=1000, default=1, rows=[]),
                      shards=tuple(range(128)))
        permits = [self.reserve(core, shard=shard) for shard in range(128)]
        self.assertIsNone(core.try_reserve('POST', ORDERS, shard=0, now=now(1)))
        self.assertEqual(core.status(now=now(1)).outstanding, 128)
        for permit in permits:
            core.discard(permit, now=now(1))
        for _ in range(500):
            permit = self.reserve(core)
            core.consume(permit, 'POST', ORDERS, shard=0, now=now(1))
        self.assertEqual(core._permits, {})
        self.assertEqual(len(core._buckets), 128)

    def test_oversized_cost_has_no_ready_time(self):
        core = budget(snapshot(capacity=5))
        self.assertIsNone(core.ready_delay('POST', ORDERS, shard=0, now=now(100)))
        self.assertIsNone(core.try_reserve('POST', ORDERS, shard=0, now=now(100)))
        self.reserve(core, t=100, method='DELETE', route=ORDER)

    def test_literal_offline_flag_and_unsupported_routes_or_routing(self):
        for flag in (False, 1, 'true', None):
            with self.subTest(flag=flag), self.assertRaises(InvalidData):
                WriteBudget(snapshot(), shards=(0,), now=now(), offline_fixture=flag)
        with self.assertRaises(InvalidData):
            WriteBudget(snapshot(), shards=(0,), now=now())
        core = budget()
        for method, route in (('GET', ORDERS), ('DELETE', ORDERS),
                              ('POST', ORDERS + '/batched'), ('DELETE', ORDERS + '/batched'),
                              ('POST', ORDER + '/amend'), ('DELETE', CANCEL),
                              ('POST', '/portfolio/orders'), ('POST', '/portfolio/perps/orders'),
                              ('DELETE', ORDER + '?exchange_index=1'),
                              ('post', ORDERS), ('POST', '/unknown')):
            with self.subTest(method=method, route=route), self.assertRaises(InvalidData):
                core.try_reserve(method, route, shard=0, now=now(1))
        for shard in (-1, 3, None, True, 1.0):
            with self.subTest(shard=shard), self.assertRaises(InvalidData):
                core.try_reserve('POST', ORDERS, shard=shard, now=now(1))

    def test_clock_rollback_permanently_latches_even_after_catchup_and_refresh(self):
        for regressed in (now(1, WALL + 2), now(2, WALL + 1)):
            with self.subTest(regressed=regressed):
                evidence = snapshot()
                core = budget(evidence)
                permit = self.reserve(core, t=2)
                self.assertEqual(core.status(now=regressed).reason, 'write_clock_regressed')
                self.assertEqual(core.status(now=now(5)).reason, 'write_clock_regressed')
                self.assertEqual(core.status(now=now(5)).outstanding, 0)
                with self.assertRaises(QuotaUnavailable):
                    core.consume(permit, 'POST', ORDERS, shard=0, now=now(5))
                fresh = snapshot(scope=evidence.scope, sequence=2, start=now(5))
                with self.assertRaises(QuotaUnavailable):
                    core.refresh(fresh, now=now(5))
                recreated = budget(fresh, at=now(5))
                self.assertEqual(recreated.status(now=now(5)).buckets[0][1], 0)

    def test_rollback_first_seen_by_refresh_or_pause_also_latches(self):
        for action in ('refresh', 'pause'):
            with self.subTest(action=action):
                evidence = snapshot()
                core = budget(evidence)
                self.reserve(core, t=2)
                with self.assertRaises(QuotaUnavailable):
                    if action == 'refresh':
                        core.refresh(snapshot(scope=evidence.scope, sequence=2, start=now(1)),
                                     now=now(1))
                    else:
                        core.pause_429(shard=0, seconds=3, now=now(1))
                self.assertEqual(core.status(now=now(3)).reason, 'write_clock_regressed')

    def test_exact_refill_never_uses_epsilon_to_grant_tokens(self):
        core = budget(snapshot(rate=3, capacity=3, default=1, rows=[]))
        below = 1 / 3
        self.assertLess(Fraction(below) * 3, 1)
        self.assertIsNone(core.try_reserve('POST', ORDERS, shard=0, now=now(below, WALL)))
        self.assertGreater(core.ready_delay('POST', ORDERS, shard=0, now=now(below, WALL)), 0)
        above = math.nextafter(below, math.inf)
        permit = core.try_reserve('POST', ORDERS, shard=0, now=now(above, WALL))
        self.assertIsNotNone(permit)
        self.assertEqual(core.status(now=now(above, WALL)).buckets[0][1], Fraction(above) * 3 - 1)

    def test_fresh_telemetry_and_delay_are_not_live_authority(self):
        core = budget()
        self.assertEqual(core.ready_delay('POST', ORDERS, shard=0, now=now(2)), 0)
        status = core.status(now=now(2))
        self.assertEqual(status.buckets[0][1], 20)
        self.assertEqual(status.outstanding, 0)
        self.assertIsNone(status.reason)
        self.assertFalse(status.live_ready)
        with self.assertRaises(FrozenInstanceError):
            status.live_ready = True


if __name__ == '__main__':
    unittest.main()
