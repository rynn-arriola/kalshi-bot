from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from kalshi_bot.adapters import PriceBand, create_payload, parse_fill, validate_tick
from kalshi_bot.cli import main
from kalshi_bot.config import BotConfig
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.risk import OrderExposure, WindowRisk, admit_entry, entry_cap, exposure_total, window_bounds
from kalshi_bot.values import InvalidData, count, decimal, price
from kalshi_bot.windows import WindowsLease
from kalshi_bot.risk import MAX_RESTING_ENTRIES as CAP

UTC = timezone.utc
NOW = datetime(2026, 9, 19, 5, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def fill(key, *, side="bid", qty="10", p="0.5", fee="0", ticker="A"):
    return Fill(key, "o-"+key, ticker, side, D(qty), D(p), D(fee))


class ValueConfigTests(unittest.TestCase):
    def test_rejects_inexact_and_nonfinite_values(self):
        for value in (True, 0.1, "NaN", "Infinity", "-Infinity", "1e-20", None):
            with self.subTest(value=value), self.assertRaises(InvalidData): decimal(value)

    def test_quantity_grid(self):
        self.assertEqual(count("0.01"), D("0.01"))
        for value in ("0", "-1", "0.001"):
            with self.subTest(value=value), self.assertRaises(InvalidData): count(value)

    def test_prices(self):
        for value in (0, 1, -1):
            with self.assertRaises(InvalidData): price(value)

    def test_policy_defaults_follow_verified_poly_exposure_reference(self):
        # D-142: the running bot uses the approved file; defaults stay the
        # original reference profile used by offline fixtures.
        config = BotConfig.load(ROOT / "config/bot.json")
        self.assertEqual((config.capital_usd, config.entry_contracts, config.window_stop_usd),
                         (D(780), D(30), D(25)))
        self.assertEqual(config.managed_market_slots, 16)
        self.assertEqual(config.minimum_entry_retained_value, D('.70'))
        self.assertEqual(config.minimum_projected_reward_usd, D(1))
        self.assertEqual(config.priority_projected_reward_usd, D(2))
        self.assertEqual(config.portfolio_exposure_usd, 780)
        self.assertLessEqual(config.portfolio_exposure_usd, config.capital_usd)
        self.assertEqual(config.market_exposure_usd, 270)
        self.assertEqual(BotConfig().portfolio_exposure_usd, 300)  # reference
        self.assertTrue(config.live_blockers())

    def test_portfolio_formula(self):
        for slots, dollars in ((20,300),(30,400),(32,420)):
            self.assertEqual(BotConfig(managed_market_slots=slots).portfolio_exposure_usd, dollars)

    def test_four_book_connections_is_supported_engineering_limit(self):
        self.assertEqual(BotConfig(book_connections=4).book_connections,4)

    def test_drift_and_bool_settings_rejected(self):
        for kwargs in ({"entry_contracts": "9"}, {"capital_usd":"501"},
                       {"window_stop_usd":"10"}, {"live_enabled":True},
                       {"minimum_entry_retained_value":".69"},
                       {"minimum_projected_reward_usd":".99"},
                       {"priority_projected_reward_usd":"1.99"},
                       {"live_enabled":0}, {"managed_market_slots":True},
                       {"managed_market_slots":41}, {"book_connections":1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidData): BotConfig(**kwargs)

    def test_unknown_config_fields_rejected(self):
        raw = json.loads((ROOT / "config/bot.json").read_text())
        raw["arm_live"] = True
        with TemporaryDirectory() as folder:
            path = Path(folder)/"bad.json"
            path.write_text(json.dumps(raw))
            with self.assertRaises(InvalidData): BotConfig.load(path)

    def test_preflight_is_blocked_and_has_no_side_effects(self):
        output = StringIO()
        with redirect_stdout(output):
            result = main(["preflight","--config",str(ROOT / "config/bot.json")])
        report = json.loads(output.getvalue())
        self.assertEqual(result, 2)
        self.assertFalse(report["live_ready"])
        self.assertFalse(report["network_accessed"])
        self.assertFalse(report["credentials_accessed"])


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"ledger.db"
        self.ledger = Ledger(self.path)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: self.ledger.close())

    def pnl(self):
        return self.ledger.realized(NOW, NOW+timedelta(days=1))

    def test_open_position_is_unmarked_but_actual_fee_is_immediate(self):
        self.ledger.record_fill(fill("1",fee="0.20"), NOW)
        self.assertEqual(self.ledger.position("A"),10)
        self.assertEqual(self.pnl(),D("-0.20"))

    def test_closed_long_includes_both_fees(self):
        self.ledger.record_fill(fill("1",p="0.6",fee="0.10"), NOW)
        self.ledger.record_fill(fill("2",side="ask",p="0.4",fee="0.20"), NOW)
        self.assertEqual(self.pnl(), D("-2.30"))
        self.assertEqual(self.ledger.position("A"),0)

    def test_short_close(self):
        self.ledger.record_fill(fill("1",side="ask",p="0.6"), NOW)
        self.ledger.record_fill(fill("2",side="bid",p="0.4"), NOW)
        self.assertEqual(self.pnl(),2)

    def test_partial_close_realizes_matched_gross_and_all_actual_fees(self):
        self.ledger.record_fill(fill("1",p="0.6",fee="0.10"), NOW)
        self.ledger.record_fill(fill("2",side="ask",qty="4",p="0.5",fee="0.04"), NOW)
        self.assertEqual(self.pnl(),D("-0.54"))
        self.assertEqual(self.ledger.position("A"),6)
        self.ledger.record_fill(fill("3",side="ask",qty="6",p="0.5",fee="0.06"), NOW)
        self.assertEqual(self.pnl(),D("-1.20"))

    def test_overclose_records_reversal_without_hiding_exposure(self):
        self.ledger.record_fill(fill("1",qty="4"), NOW)
        self.ledger.record_fill(fill("2",side="ask",qty="10",fee="0.10"), NOW)
        self.assertEqual(self.ledger.position("A"),-6)
        self.assertEqual(self.pnl(),D("-0.10"))

    def test_duplicate_fill_is_idempotent_after_restart(self):
        self.ledger.record_fill(fill("1"), NOW)
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.assertFalse(self.ledger.record_fill(fill("1"), NOW+timedelta(seconds=5)))
        self.assertEqual(self.ledger.position("A"),10)

    def test_conflicting_duplicate_fails_without_mutation(self):
        self.ledger.record_fill(fill("1"), NOW)
        with self.assertRaises(InvalidData): self.ledger.record_fill(fill("1",qty="2"), NOW)
        self.assertEqual(self.ledger.position("A"),10)

    def test_backwards_receipt_clock_rejected(self):
        self.ledger.record_fill(fill("1"), NOW)
        with self.assertRaises(InvalidData): self.ledger.record_fill(fill("2"), NOW-timedelta(seconds=1))

    def test_receipt_at_boundary_charges_new_window(self):
        boundary = datetime(2026,9,19,10,tzinfo=UTC)
        self.ledger.record_fill(fill("1",p="0.6"), boundary-timedelta(seconds=1))
        self.ledger.record_fill(fill("2",side="ask",p="0.4"), boundary)
        self.assertEqual(WindowRisk(self.ledger).observe(boundary).realized_pnl,-2)

    def test_intent_never_retried_when_unknown(self):
        self.ledger.reserve_intent("id", {"ticker":"A"}, NOW)
        self.ledger.transition_intent("id","SENDING")
        self.ledger.transition_intent("id","UNKNOWN")
        with self.assertRaises(InvalidData): self.ledger.reserve_intent("id",{},NOW)
        with self.assertRaises(InvalidData): self.ledger.transition_intent("id","SENDING")
        self.assertEqual(self.ledger.unresolved_intents(),1)

    def test_fill_id_same_trade_different_order_is_distinct(self):
        a=fill("1")
        b=Fill(a.trade_id,"different-order","A","bid",D(10),D("0.5"),D(0))
        self.ledger.record_fill(a,NOW)
        self.ledger.record_fill(b,NOW)
        self.assertEqual(self.ledger.position("A"),20)


class RiskTests(unittest.TestCase):
    setUp = LedgerTests.setUp

    def closed_loss(self, loss, key="a", now=NOW):
        self.ledger.record_fill(fill(key,qty=str(loss*2),p="0.75"),now)
        self.ledger.record_fill(fill(key+"x",side="ask",qty=str(loss*2),p="0.25"),now)

    def test_exact_thresholds(self):
        # D-138: 50-entry cap; same $5 steps and $25 stop at 6/6..2/6 of it.
        for loss, expected in (("0",50),("4.99",50),("5",41),("9.99",41),("10",33),
                               ("15",25),("20",16),("24.99",16),("25",0),("30",0),("-5",50)):
            self.assertEqual(entry_cap(D(loss)),expected)

    def test_restart_and_recovery_cannot_widen_cap(self):
        self.closed_loss(10)
        self.assertEqual(WindowRisk(self.ledger).observe(NOW).cap,33)
        self.ledger.record_fill(fill("profit",qty="30",p="0.25"),NOW)
        self.ledger.record_fill(fill("profit-close",side="ask",qty="30",p="0.75"),NOW)
        self.ledger.close()
        self.ledger=Ledger(self.path)
        self.assertEqual(WindowRisk(self.ledger).observe(NOW).cap,33)

    def test_hard_hold_survives_next_window_until_proof(self):
        self.closed_loss(25)
        risk=WindowRisk(self.ledger)
        self.assertTrue(risk.observe(NOW).held)
        next_window=NOW+timedelta(hours=6)
        self.assertEqual(risk.observe(next_window).cap,0)
        with self.assertRaises(InvalidData):
            risk.release_previous(next_window,account_observed_at=next_window,
                                  orders=1,positions=0,unknowns=0,complete=True)
        self.assertEqual(risk.release_previous(next_window,account_observed_at=next_window,
                                               orders=0,positions=0,unknowns=0,complete=True).cap,50)

    def test_current_window_hard_cannot_release(self):
        self.closed_loss(25)
        risk=WindowRisk(self.ledger)
        risk.observe(NOW)
        self.assertEqual(risk.release_previous(NOW,account_observed_at=NOW,
                          orders=0,positions=0,unknowns=0,complete=True).cap,0)

    def test_dst_civil_windows(self):
        for month,day,expected in ((3,8,5),(11,1,7)):
            start,end=window_bounds(datetime(2026,month,day,7,tzinfo=UTC))
            self.assertEqual((end-start).total_seconds()/3600,expected)

    def test_backwards_risk_clock_fails_closed(self):
        risk=WindowRisk(self.ledger)
        risk.observe(NOW)
        with self.assertRaises(InvalidData): risk.observe(NOW-timedelta(seconds=1))

    def test_all_resting_exposure_counted_and_duplicate_reserved_once(self):
        order=OrderExposure("one","A","ask",D("0.4"),D("2"))
        self.assertEqual(exposure_total({"A":D(5)},[order,order]),{"A":D("6.2")})

    def test_conflicting_reservations_are_not_silently_deduplicated(self):
        orders=[OrderExposure("one","A","ask",D("0.4"),D(2)),
                OrderExposure("one","A","ask",D("0.4"),D(3))]
        with self.assertRaises(InvalidData): exposure_total({},orders)

    def test_admission_blocks_unknown_inventory_and_budget(self):
        state=WindowRisk(self.ledger).observe(NOW)
        base=dict(window=state,ticker="A",current_position=D(0),resting_entries=CAP-1,
                  candidate_loss=D(5),exposure={},free_capital=D(500),account_known=True,now=NOW)
        config=BotConfig(managed_market_slots=30)
        self.assertEqual(admit_entry(config,**base),())
        for field,value,reason in (("current_position",D(1),"position_is_reduce_only"),
                                  ("resting_entries",CAP,"entry_cap"),
                                  ("account_known",False,"unknown_account"),
                                  ("exposure",{"B":D(399)},"portfolio_exposure"),
                                  ("free_capital",D(4),"capital")):
            self.assertIn(reason,admit_entry(config,**(base|{field:value})))
        self.assertIn("market_capacity_undecided",admit_entry(BotConfig(managed_market_slots=None),**base))

    def test_stale_and_next_window_risk_cannot_authorize_entry(self):
        state=WindowRisk(self.ledger).observe(NOW)
        base=dict(window=state,ticker="A",current_position=D(0),resting_entries=0,
                  candidate_loss=D(5),exposure={},free_capital=D(500),account_known=True)
        config=BotConfig(managed_market_slots=30)
        self.assertIn("stale_risk_window",admit_entry(config,now=NOW+timedelta(seconds=6),**base))
        self.assertIn("invalid_risk_window",admit_entry(config,now=NOW+timedelta(hours=6),**base))

    def test_small_fee_is_charged_once_without_proration(self):
        self.ledger.record_fill(fill("fraction-open",qty="3",fee="0.01"),NOW)
        self.ledger.record_fill(fill("fraction-close",side="ask",qty="1"),NOW)
        self.assertEqual(WindowRisk(self.ledger).observe(NOW).cap,50)
        self.assertEqual(WindowRisk(self.ledger).observe(NOW).realized_pnl,D("-0.01"))


class AdapterTests(unittest.TestCase):
    bands=(PriceBand(D(0),D("0.5"),D("0.01")),PriceBand(D("0.5"),D(1),D("0.005")))

    def payload(self,**kwargs):
        return create_payload(ticker="A",client_id="id",outcome="no",outcome_price=D("0.30"),
                              quantity=D(10),bands=self.bands,**kwargs)

    def test_no_bid_becomes_yes_frame_ask(self):
        p=self.payload()
        self.assertEqual(p["side"],"ask")
        self.assertEqual(D(p["price"]),D("0.70"))
        self.assertTrue(p["post_only"])

    def test_price_band_specific_grid(self):
        self.assertEqual(validate_tick(D("0.505"),self.bands),D("0.505"))
        with self.assertRaises(InvalidData): validate_tick(D("0.495"),self.bands)

    def test_reducer_never_overcloses(self):
        with self.assertRaises(InvalidData): self.payload(reducing=True,position=D(4))
        self.assertFalse(self.payload(reducing=True,position=D(10))["reduce_only"])

    def test_expiration_field_uses_v2_contract(self):
        p=self.payload(expiration_time=1800000000)
        self.assertEqual(p["expiration_time"],1800000000)
        self.assertNotIn("expiration_ts",p)

    def test_canonical_fill_required(self):
        msg=dict(trade_id="t",order_id="o",market_ticker="A",book_side="ask",
                 count_fp="0.01",yes_price_dollars="0.7",fee_cost="0.00001")
        self.assertEqual(parse_fill({"type":"fill","msg":msg}).quantity,D("0.01"))
        del msg["book_side"]
        with self.assertRaises(InvalidData): parse_fill({"type":"fill","msg":msg})


@unittest.skipUnless(os.name=="nt","native Windows test")
class WindowsTests(unittest.TestCase):
    def test_kernel_lease_blocks_duplicate_and_releases(self):
        key="test-"+str(uuid4())
        with WindowsLease(key):
            with self.assertRaises(InvalidData):
                with WindowsLease(key): pass
        with WindowsLease(key): pass

    def test_kernel_lease_excludes_other_process(self):
        key="test-"+str(uuid4())
        with WindowsLease(key):
            result=subprocess.run([sys.executable,"-B","-c",
                                   "from kalshi_bot.windows import WindowsLease; "
                                   f"WindowsLease({key!r}).__enter__()"],capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b"another process",result.stderr)
