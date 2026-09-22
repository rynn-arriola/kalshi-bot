"""Offline tests for the deliberately narrow live-canary boundary."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import unittest

from kalshi_bot.live_canary import (candidate, make_plan, order_requests,
                                    rest_book, validate_plan)
from kalshi_bot.mutation_transport import MutationActivation, batch_scope
from kalshi_bot.values import InvalidData


NOW = datetime(2026, 9, 22, 14, tzinfo=timezone.utc)


def market(**updates):
    row = dict(ticker="KXTEST-1", event_ticker="KXTEST", market_type="binary",
        exchange_index=0, open_time=(NOW-timedelta(minutes=1)).isoformat(),
        close_time=(NOW+timedelta(minutes=15)).isoformat(), status="active",
        can_close_early=False, notional_value_dollars="1.0000",
        rules_primary="Synthetic canary test only.", rules_secondary="",
        price_ranges=[dict(start="0", end="1", step=".01")])
    row.update(updates)
    return {"market": row}


def program(**updates):
    row = dict(id="program-1", market_ticker="KXTEST-1", incentive_type="liquidity",
        start_date=NOW.isoformat(), end_date=(NOW+timedelta(minutes=15)).isoformat(),
        target_size_fp="300.00", discount_factor_bps=5000,
        period_reward=1000000, paid_out=False, max_reward_per_account=None)
    row.update(updates)
    return row


def book():
    return {"orderbook_fp": {"yes_dollars": [["0.40", "300.00"]],
                             "no_dollars": [["0.40", "300.00"]]}}


class CanaryTests(unittest.TestCase):
    def test_rest_no_prices_are_complemented_to_yes_asks(self):
        parsed = rest_book("KXTEST-1", book())
        self.assertEqual(parsed.bids.best(bid=True), D(".4"))
        self.assertEqual(parsed.asks.best(bid=False), D(".6"))

    def test_candidate_is_two_sided_bounded_and_reward_eligible(self):
        row, blockers = candidate(program(), market(), book(), NOW+timedelta(seconds=1))
        self.assertEqual(blockers, ())
        self.assertEqual((row["bid_price"], row["ask_price"], row["no_bid_price"]),
                         ("0.40", "0.60", "0.40"))
        self.assertEqual(row["maximum_combined_entry_cost_usd"], "8.00")
        self.assertGreater(D(row["estimated_remaining_reward_usd"]), 1)

    def test_early_close_is_recorded_while_extreme_and_too_late_fail_closed(self):
        early, blockers = candidate(
            program(), market(can_close_early=True), book(), NOW)
        self.assertEqual(blockers, ())
        self.assertTrue(early["can_close_early"])
        self.assertIn("insufficient_canary_time", candidate(
            program(end_date=(NOW+timedelta(seconds=60)).isoformat()),
            market(), book(), NOW)[1])
        extreme = {"orderbook_fp": {"yes_dollars": [["0.94", "300"]],
                                     "no_dollars": [["0.01", "300"]]}}
        self.assertIn("canary_price_guard", candidate(program(), market(), extreme, NOW)[1])

    def test_plan_integrity_expiry_and_exact_requests(self):
        row, _ = candidate(program(), market(), book(), NOW)
        plan = make_plan(row | {"title": "Synthetic"}, balance="500.4268", now=NOW)
        validate_plan(plan, now=NOW)
        requests = order_requests(plan, now=NOW)
        self.assertEqual({r["side"] for r in requests}, {"bid", "ask"})
        self.assertTrue(all(r["count"] == "10" and r["post_only"] for r in requests))
        changed = dict(plan, bid_price="0.39")
        with self.assertRaisesRegex(InvalidData, "integrity"):
            validate_plan(changed, now=NOW)
        with self.assertRaisesRegex(InvalidData, "expired"):
            validate_plan(plan, now=NOW+timedelta(minutes=1))

    def test_activation_is_exact_single_use_and_cancel_scoped(self):
        row, _ = candidate(program(), market(), book(), NOW)
        plan = make_plan(row | {"title": "Synthetic"}, balance="500", now=NOW)
        requests = order_requests(plan, now=NOW)
        activation = MutationActivation(plan["run_id"], plan["ticker"], 0, 0,
            frozenset(plan["client_order_ids"].values()), batch_scope(requests))
        activation.authorize_batch(requests)
        activation.record_outcomes((dict(state="ack", order_id="order-1"),))
        with self.assertRaisesRegex(InvalidData, "already consumed"):
            activation.authorize_batch(requests)
        activation.authorize_cancel(dict(order_id="order-1", subaccount=0,
            exchange_index=0, market_ticker=plan["ticker"]))
        with self.assertRaisesRegex(InvalidData, "outside"):
            activation.authorize_cancel(dict(order_id="order-1", subaccount=0,
                exchange_index=1, market_ticker=plan["ticker"]))


if __name__ == "__main__":
    unittest.main()
