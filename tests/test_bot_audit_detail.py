"""D-153: which owned-order terms differed from Kalshi's snapshot (diagnostics only)."""
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

from kalshi_bot.account_proof import audit_detail_fields
from kalshi_bot.observability import Diagnostics
from kalshi_bot.verification import AccountAudit, mismatch_kinds

NOW = datetime(2026, 9, 27, 2, 0, tzinfo=timezone.utc)
NOW_US = int(NOW.timestamp()*1_000_000)


def ours(**kw):
    base = dict(terminal=False, remaining=D(10), yes_price=D('.5'), side='bid', client_id='c1',
                ticker='A', exchange_index=0)
    return NS(**dict(base, **kw))


def theirs(**kw):
    base = dict(remaining=D(10), yes_price=D('.5'), book_side='bid', client_id='c1',
                ticker='A', exchange_index=0)
    return NS(**dict(base, **kw))


def audit(details):
    return AccountAudit('e', 1, True, 0, (), (), (), (), (), 0, ('owned_order_terms_mismatch',), details)


class KindTests(unittest.TestCase):
    def test_each_difference_has_its_own_label(self):
        self.assertEqual(mismatch_kinds(ours(terminal=True, remaining=D(0)), theirs()),
                         ('terminal_but_resting',))
        self.assertEqual(mismatch_kinds(ours(remaining=D(7)), theirs()), ('remaining_venue_higher',))
        self.assertEqual(mismatch_kinds(ours(), theirs(remaining=D(3))), ('remaining_venue_lower',))
        self.assertEqual(mismatch_kinds(ours(), theirs(yes_price=D('.6'), book_side='ask')),
                         ('price_differs', 'side_differs'))
        self.assertEqual(mismatch_kinds(ours(), theirs(client_id='x', ticker='B', exchange_index=1)),
                         ('client_differs', 'ticker_differs', 'exchange_index_differs'))
        self.assertEqual(mismatch_kinds(ours(), theirs()), ())

    def test_details_never_change_audit_equality(self):
        self.assertEqual(audit((('mismatch', ('price_differs',), 1),)), audit(()))
        self.assertEqual(hash(audit((('missing', (), 1),))), hash(audit(())))


class FieldTests(unittest.TestCase):
    def test_counts_ages_and_labels(self):
        fields = audit_detail_fields(audit((
            ('mismatch', ('terminal_but_resting',), NOW_US-8_000_000),
            ('mismatch', ('remaining_venue_lower',), NOW_US-1_500_000),
            ('missing', (), NOW_US-900_000),
            ('missing', (), None))), NOW)
        self.assertEqual(fields, dict(mismatch_count=2, mismatch_age_min_ms=1500, mismatch_age_max_ms=8000,
                                      missing_count=2, missing_age_min_ms=900, missing_age_max_ms=900,
                                      mismatch_kinds=['remaining_venue_lower', 'terminal_but_resting']))

    def test_nothing_or_garbage_gives_no_fields(self):
        self.assertEqual(audit_detail_fields(None, NOW), {})
        self.assertEqual(audit_detail_fields(audit(()), NOW), {})
        self.assertEqual(audit_detail_fields(NS(details=(('mismatch',),)), NOW), {})
        future = audit_detail_fields(audit((('missing', (), NOW_US+5_000_000),)), NOW)
        self.assertEqual(future['missing_age_min_ms'], 0)


class LagTests(unittest.TestCase):
    def test_only_fresh_terminal_but_resting_counts_as_snapshot_lag(self):
        from kalshi_bot.account_proof import snapshot_lag_only
        fresh = (('mismatch', ('terminal_but_resting',), NOW_US-1_500_000),)
        self.assertTrue(snapshot_lag_only(audit(fresh), NOW))
        self.assertFalse(snapshot_lag_only(None, NOW))
        self.assertFalse(snapshot_lag_only(audit(()), NOW))
        other = AccountAudit('e', 1, True, 0, (), (), (), (), (), 0,
                             ('owned_order_terms_mismatch', 'foreign_resting_orders'), fresh)
        self.assertFalse(snapshot_lag_only(other, NOW))
        self.assertFalse(snapshot_lag_only(audit((('mismatch', ('price_differs',), NOW_US-1_000),)), NOW))
        self.assertFalse(snapshot_lag_only(audit((('mismatch', ('terminal_but_resting', 'price_differs'),
                                                   NOW_US-1_000),)), NOW))
        self.assertFalse(snapshot_lag_only(audit((('missing', (), NOW_US-1_000),)), NOW))
        self.assertFalse(snapshot_lag_only(audit((('mismatch', ('terminal_but_resting',),
                                                   NOW_US-11_000_000),)), NOW))
        self.assertFalse(snapshot_lag_only(audit(fresh+(('mismatch', ('terminal_but_resting',), None),)), NOW))


class LogTests(unittest.TestCase):
    def test_only_known_labels_and_numbers_reach_the_log(self):
        with TemporaryDirectory() as temp:
            log = Diagnostics(Path(temp)).start()
            log.emit('account_refresh_failed', cause='own_order_renewal_failed', outcome='audit_blocked',
                     blockers=('owned_order_terms_mismatch',), mismatch_count=2, mismatch_age_min_ms=1500,
                     mismatch_kinds=['terminal_but_resting', 'order-secret-123'])
            log.close()
            [row] = [json.loads(line) for f in Path(temp).glob('events.jsonl*')
                     for line in f.read_text(encoding='utf-8').splitlines()
                     if '"account_refresh_failed"' in line]
        context = row['context']
        self.assertEqual(context['mismatch_kinds'], ['terminal_but_resting'])
        self.assertEqual((context['mismatch_count'], context['mismatch_age_min_ms']), (2, 1500))
        self.assertNotIn('order-secret-123', json.dumps(row))


if __name__ == '__main__':
    unittest.main()
