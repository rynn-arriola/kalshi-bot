"""Composed exploration/partial admission arithmetic; no network or account I/O.

Freshness/ownership checks are covered by test_bot_admission. Here fake immediate
joins isolate fair coverage and connect the admitted scope to the real selector.
"""
import unittest
from types import SimpleNamespace

from kalshi_bot.admission import MarketAdmission
from kalshi_bot.discovery_candidates import CandidateDiscovery
from test_bot_discovery_candidates import catalog, NOW
import test_bot_selection as selection


class CoverageTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, count=1024, owners=14):
        data, discovery = catalog(count), CandidateDiscovery()
        tickers = sorted(data.observations)
        protected = tuple(tickers[:owners])
        engine = SimpleNamespace(
            shards={n: SimpleNamespace(tickers=frozenset(tickers[start:start+64]))
                    for n, start in (('b0', 0), ('b1', 64))},
            market_shard={t: 'b'+str(i//64) for i, t in enumerate(tickers[:128])})
        seen = set(engine.market_shard)

        async def choose():
            return discovery.choose(data, now=NOW, budget=128, protected=protected,
                                    subscribed=tuple(sorted(engine.market_shard)))

        runtime = SimpleNamespace(engine=engine,
            selection=SimpleNamespace(discovery_candidates=choose), clock=lambda: 0,
            writer=SimpleNamespace(market_capacity=128), metadata_scheduler=None,
            reader_states={'b0': 'subscribed', 'b1': 'subscribed'},
            reader_failures={'b0': 0, 'b1': 0}, attempt_limit=3)
        admission = object.__new__(MarketAdmission)
        admission.runtime = runtime
        admission.cursor = admission.completed = admission.deferred = 0
        admission.pending = admission.last_change_at = None
        admission._ready = lambda: True
        async def removable(change):
            return True
        admission.removable = removable

        def joined():
            change = admission.pending
            self.assertLessEqual(len(set(change.after)-change.before), 16)
            engine.shards[change.name].tickers = frozenset(change.after)
            engine.market_shard = {t: n for n, s in engine.shards.items() for t in s.tickers}
            self.assertLessEqual(len(engine.market_shard), 128)
            self.assertTrue(set(protected) <= set(engine.market_shard))
            seen.update(engine.market_shard)
            change.result.set_result(True)
        admission.signals = {n: SimpleNamespace(set=joined) for n in engine.shards}
        return admission, discovery, engine, seen, protected

    async def test_partial_admission_covers_full_universe_with_protected_owners(self):
        for owners in (0, 14, 30):
            with self.subTest(owners=owners):
                admission, _, _, seen, _ = self.fixture(owners=owners)
                for _ in range(128):
                    await admission._cycle()
                    if len(seen) == 1024:
                        break
                self.assertEqual(len(seen), 1024)

    async def test_deferred_join_does_not_skip_unsubscribed_candidates(self):
        admission, discovery, engine, seen, _ = self.fixture()
        original = admission.removable
        async def deferred(change):
            return False
        admission.removable = deferred
        for _ in range(4):
            self.assertFalse(await admission._cycle())
        self.assertEqual(len(seen), 128)
        first = await admission.runtime.selection.discovery_candidates()
        expected = [t for t in first.tickers if t not in engine.market_shard][:16]
        admission.removable = original
        self.assertTrue(await admission._cycle())
        self.assertTrue(set(expected) <= set(engine.market_shard))
        self.assertEqual(len(discovery.pending), 1024)

    async def test_eligible_fifteenth_pair_outside_initial_scope_reaches_selector(self):
        admission, _, engine, _, protected = self.fixture()
        target = sorted(catalog(1024).observations)[140]
        self.assertNotIn(target, engine.market_shard)
        selector = selection.SelectionTests()
        selector.setUp()
        selector.add(target)
        view = selection.view(entry_count=28,
            exposure=tuple((t, selection.D('9')) for t in protected))
        def choose():
            return selector.choose(view=view, protected=protected,
                                   current=lambda t: t in engine.market_shard)
        self.assertFalse(choose().additions)
        for _ in range(2):
            await admission._cycle()
            if target in engine.market_shard:
                break
        result = choose()
        self.assertEqual([row.ticker for row in result.additions], [target])
        self.assertEqual(sum(len(row.quotes) for row in result.additions), 2)
        self.assertFalse(result.authorized)


if __name__ == '__main__':
    unittest.main()
