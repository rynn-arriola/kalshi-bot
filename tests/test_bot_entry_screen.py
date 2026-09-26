"""Review #9: shadow-only entry screen; logs proposed rules, never blocks."""
from decimal import Decimal as D
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kalshi_bot.dispatch import ENTRY_PAIR, EntryPairCandidate
from kalshi_bot.entry_screen import screen, worst_fill_loss
from kalshi_bot.market_inputs import _optional_volume
import test_bot_entry_dispatch as entry_fixture


def quotes(bid='0.82', ask='0.90', size=30):
    return (SimpleNamespace(side='bid', yes_price=D(bid), quantity=D(size)),
            SimpleNamespace(side='ask', yes_price=D(ask), quantity=D(size)))


class ScreenTests(unittest.TestCase):
    def test_worst_fill_loss_is_the_larger_leg(self):
        # 2026-09-26 KXBROSFT: a 30-contract bid at 0.82 risks $24.60.
        self.assertEqual(worst_fill_loss(quotes()), D('24.60'))
        self.assertEqual(worst_fill_loss(quotes('0.10', '0.20')), D('24.00'))
        self.assertIsNone(worst_fill_loss(()))

    def test_verdicts(self):
        cases = {
            ('volume', D('10'), D('300')),       # 2,100/week > 2,000
            ('reward_risk', D('3'), D('10')),     # $3 < 25% of $24.60
            ('both', D('3'), D('300')),
            ('pass', D('10'), D('10')),
            ('unknown', D('10'), None),
            ('unknown', None, D('10')),
        }
        for verdict, reward, volume in cases:
            with self.subTest(verdict=verdict, reward=reward, volume=volume):
                self.assertEqual(screen(remaining_reward=reward, quotes=quotes(),
                                        volume_24h=volume)['verdict'], verdict)

    def test_boundaries_are_exclusive(self):
        at_limit = D(2000)/7
        self.assertEqual(screen(remaining_reward=D('100'), quotes=quotes(),
                                volume_24h=at_limit)['verdict'], 'pass')
        self.assertEqual(screen(remaining_reward=D('6.15'), quotes=quotes(),
                                volume_24h=D(1))['verdict'], 'pass')

    def test_volume_never_makes_a_market_look_changed(self):
        from dataclasses import replace
        from datetime import datetime, timezone
        from kalshi_bot.market_inputs import Market
        t = datetime(2026, 9, 26, tzinfo=timezone.utc)
        market = Market('A', 'E', 0, (), t, t.replace(month=10), True, False, None, None, 'h',
                        volume_24h=D(10))
        self.assertEqual(market, replace(market, volume_24h=D(9999)))
        self.assertEqual(hash(market), hash(replace(market, volume_24h=None)))

    def test_market_volume_is_optional_and_never_an_error(self):
        self.assertEqual(_optional_volume({'volume_24h_fp': '487.62'}), D('487.62'))
        for row in ({}, {'volume_24h_fp': 'abc'}, {'volume_24h_fp': '-1'},
                    {'volume_24h_fp': 1.5}):
            with self.subTest(row=row):
                self.assertIsNone(_optional_volume(row))


class ShadowEmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = entry_fixture.EntrySourceTests('test_ranked_market_becomes_exact_source_bound_pair')
        await self.f.asyncSetUp()
        self.events = []
        self.f.runtime.diagnostics = SimpleNamespace(
            emit=lambda name, **fields: self.events.append((name, fields)),
            ensure_healthy=lambda: None)

    async def asyncTearDown(self):
        await self.f.asyncTearDown()

    async def test_each_prepared_entry_is_scored_and_still_placed(self):
        candidate = await self.f.source.refresh('A', ENTRY_PAIR)
        self.assertIsInstance(candidate, EntryPairCandidate)
        shadow = [fields for name, fields in self.events if name == 'entry_screen_shadow']
        self.assertEqual(len(shadow), 1)
        self.assertEqual(shadow[0]['market'], 'A')
        self.assertIn(shadow[0]['screen'], {'pass', 'volume', 'reward_risk', 'both', 'unknown'})
        self.assertGreater(shadow[0]['risk_cents'], 0)

    async def test_a_screen_failure_never_blocks_the_entry(self):
        with patch('kalshi_bot.entry_screen.screen', side_effect=RuntimeError('bad')):
            candidate = await self.f.source.refresh('A', ENTRY_PAIR)
        self.assertIsInstance(candidate, EntryPairCandidate)
        self.assertEqual(self.f.source.shadow_screen_failures, 1)


if __name__ == '__main__':
    unittest.main()
