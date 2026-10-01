"""D-031 reference-calibrated exposure, separate from capital and entry count."""
from contextlib import redirect_stdout
from dataclasses import replace
from decimal import Decimal as D
from io import StringIO
import json
from pathlib import Path
import unittest

from kalshi_bot.cli import main
from kalshi_bot.config import BotConfig
from kalshi_bot.risk import WindowState, admit_entry, window_bounds
from test_bot_foundation import NOW


class PolyExposureTests(unittest.TestCase):
    def setUp(self):
        self.config = BotConfig()
        start, end = window_bounds(NOW)
        self.window = WindowState(start, end, D(0), 30, False, NOW)

    def gate(self, **kwargs):
        values = dict(window=self.window, ticker="new", current_position=D(0),
                      resting_entries=0, candidate_loss=D(5), exposure={},
                      free_capital=D(500), account_known=True, now=NOW)
        return admit_entry(self.config, **(values | kwargs))

    def test_default_matches_reference_20_plus_ten_at_size_ten(self):
        self.assertEqual(self.config.portfolio_exposure_usd, D(10)*(20+10))
        self.assertEqual((self.config.capital_usd, self.config.market_exposure_usd,
                          self.config.max_resting_entries), (500, 90, 50))

    def test_exact_portfolio_boundary_allowed_by_exposure_gate(self):
        self.assertEqual(self.gate(exposure={str(i):D(59) for i in range(5)}), ())

    def test_subcent_overage_blocked_even_with_500_cash(self):
        exposure={str(i):D(59) for i in range(5)}
        exposure['0'] += D('.0001')
        self.assertIn('portfolio_exposure', self.gate(exposure=exposure))

    def test_cap_never_grows_with_existing_market_count(self):
        for markets in (5, 20, 30, 100):
            exposure={str(i): D(300)/markets for i in range(markets)}
            self.assertIn('portfolio_exposure', self.gate(exposure=exposure))
            self.assertEqual(self.config.portfolio_exposure_usd, 300)

    def test_reference_is_not_a_new_20_market_admission_ceiling(self):
        self.assertEqual(self.gate(resting_entries=29,
            exposure={str(i):D(5) for i in range(29)}), ())

    def test_count_limit_applies_below_dollar_limit(self):
        self.assertIn('entry_cap', self.gate(resting_entries=30))

    def test_cash_limit_applies_below_exposure_limit(self):
        self.assertIn('capital', self.gate(free_capital=D('4.9999')))

    def test_market_limit_applies_below_portfolio_limit(self):
        self.assertIn('market_exposure', self.gate(exposure={'new':D('85.0001')}))

    def test_reducer_count_exemption_does_not_exempt_dollars(self):
        # Portfolio projection supplies all conservative dollar exposure,
        # independently of how many of those orders are entry orders.
        self.assertIn('portfolio_exposure', self.gate(resting_entries=0,
            exposure={str(i):D(60) for i in range(5)}))

    def test_unresolved_explicit_config_still_fails_closed(self):
        self.config=replace(self.config, managed_market_slots=None)
        self.assertIn('market_capacity_undecided', self.gate())

    def test_policy_cli_exposes_reference_and_never_live_ready(self):
        root=Path(__file__).resolve().parents[1]
        output=StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['policy','--config',str(root/'config/bot.json')]),0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['exposure_reference_slots'],11)  # D-167
        self.assertEqual(result['portfolio_exposure_usd'],'1050')
        self.assertFalse(result['live_enabled'])


if __name__ == '__main__': unittest.main()
