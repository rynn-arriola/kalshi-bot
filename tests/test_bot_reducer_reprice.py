"""D-132 passive-reducer reprice settling; pure planner inputs, no venue I/O."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
import unittest

from kalshi_bot.adapters import PriceBand
from kalshi_bot.books import Book, Ladder
from kalshi_bot.exits import ExitJournal, ExitTerms, plan_exit
from kalshi_bot.management import InventoryManager
from kalshi_bot.orders import OrderReceipt, OrderUpdate

NOW = datetime(2026, 9, 25, 22, 53, tzinfo=timezone.utc)
BANDS = (PriceBand(D(0), D(1), D('0.01')),)
TERMS = ExitTerms('W', BANDS, NOW-timedelta(seconds=1), NOW+timedelta(minutes=5),
                  NOW+timedelta(days=100), event_risk_at=NOW+timedelta(days=100),
                  taker_fee_per_contract_bound=D('.02'))


def book(bids, asks):
    result = Book('W', Ladder(100), Ladder(100), True)
    for p, q in bids:
        result.bids.set(D(p), D(q))
    for p, q in asks:
        result.asks.set(D(p), D(q))
    return result


def reducer(price='.33', remaining=10, order_id='r1'):
    return OrderReceipt(OrderUpdate(order_id, 'c'+order_id, 'W', 'ask', D(price), D(10), D(0),
        D(remaining), 'resting', 0, 0, 1), True, False, False, 'ACKNOWLEDGED', True)


# The live episode: our 0.33 exit rests; another seller flickers at 0.32.
STEADY = book([('.30', '50')], [('.33', '10'), ('.34', '100')])
UNDERCUT = book([('.30', '50')], [('.32', '20'), ('.33', '10')])


class ReducerRepriceTests(unittest.TestCase):
    def setUp(self):
        self.m = InventoryManager.__new__(InventoryManager)
        self.m._reprice_seen, self.m.reprice_holds, self.m.reprice_releases = {}, 0, 0
        self.inventory = SimpleNamespace(position=D(10), orders=(reducer(),))

    def plan(self, current):
        return plan_exit(ticker='W', position=D(10), basis=D('.33'),
            first_seen_at=NOW-timedelta(seconds=60), orders=self.inventory.orders,
            book=current, terms=TERMS, journal=ExitJournal(), now=NOW, complete_scope=True)

    def test_flickering_undercut_does_not_cancel_the_resting_exit(self):
        cancels = 0
        for step in range(30):  # 0.5 s ticks alternating like a flickering quote.
            raw = self.plan(UNDERCUT if step % 2 else STEADY)
            held = self.m._settle_reprice('W', self.inventory, raw, step*.5)
            cancels += bool(held.passive.cancel_ids)
        self.assertEqual(cancels, 0)
        self.assertGreater(self.m.reprice_holds, 0)

    def test_settled_new_target_still_reprices(self):
        results = [self.m._settle_reprice('W', self.inventory, self.plan(UNDERCUT), t)
                   for t in (0, 2, 4, 5.1)]
        self.assertEqual([bool(r.passive.cancel_ids) for r in results],
                         [False, False, False, True])
        self.assertEqual(results[-1].limit_price, D('.32'))
        self.assertEqual(self.m.reprice_releases, 1)

    def test_only_a_lone_exact_reducer_is_ever_held(self):
        for orders in ((reducer(remaining=4),), (reducer(), reducer(order_id='r2'))):
            self.m._reprice_seen.clear()
            inventory = SimpleNamespace(position=D(10), orders=orders)
            raw = plan_exit(ticker='W', position=D(10), basis=D('.33'),
                first_seen_at=NOW-timedelta(seconds=60), orders=orders, book=UNDERCUT,
                terms=TERMS, journal=ExitJournal(), now=NOW, complete_scope=True)
            self.assertIs(self.m._settle_reprice('W', inventory, raw, 0), raw)

    def test_forced_ioc_is_never_delayed(self):
        due = self.plan(STEADY)
        forced = type(due)(due.passive, 'ioc', D('.30'), D(10))
        self.assertIs(self.m._settle_reprice('W', self.inventory, forced, 0), forced)


if __name__ == '__main__':
    unittest.main()
