from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from program_timeline import ProgramTimeline, parse_ts  # noqa: E402
from sizing import time_aligned_portfolio  # noqa: E402


def row(program_id, ticker, start, end, reward=100000, target="1000.00"):
    return json.dumps({
        "id": program_id,
        "market_ticker": ticker,
        "start_date": start,
        "end_date": end,
        "period_reward": reward,
        "target_size_fp": target,
        "discount_factor_bps": 5000,
    })


class ProgramTimelineTests(unittest.TestCase):
    def test_program_is_used_only_after_observation_and_inside_period(self):
        timeline = ProgramTimeline([(
            "2026-09-01T01:00:00Z",
            row("p1", "M", "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"),
        )])
        self.assertEqual(timeline.active_at("M", parse_ts("2026-09-01T00:30:00Z")), [])
        self.assertEqual(len(timeline.active_at("M", parse_ts("2026-09-01T12:00:00Z"))), 1)
        self.assertEqual(timeline.active_at("M", parse_ts("2026-09-02T00:00:00Z")), [])

    def test_distinct_programs_on_one_market_are_retained(self):
        rows = [
            ("2026-09-01T00:00:00Z", row("p1", "M", "2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z")),
            ("2026-09-01T00:00:00Z", row("p2", "M", "2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z")),
        ]
        active = ProgramTimeline(rows).active_at("M", parse_ts("2026-09-02T00:00:00Z"))
        self.assertEqual({p.program_id for p in active}, {"p1", "p2"})

    def test_edited_program_is_excluded(self):
        rows = [
            ("2026-09-01T00:00:00Z", row("p1", "M", "2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z")),
            ("2026-09-01T01:00:00Z", row("p1", "M", "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z")),
        ]
        timeline = ProgramTimeline(rows)
        self.assertEqual(timeline.unstable_ids, {"p1"})
        self.assertEqual(timeline.active_at("M", parse_ts("2026-09-02T00:00:00Z")), [])

    def test_invalid_period_is_dropped(self):
        timeline = ProgramTimeline([(
            "2026-09-01T00:00:00Z",
            row("p1", "M", "2026-09-02T00:00:00Z", "2026-09-01T00:00:00Z"),
        )])
        self.assertEqual(timeline.active_at("M", parse_ts("2026-09-01T12:00:00Z")), [])

    def test_portfolio_does_not_sum_programs_from_different_days(self):
        rows = []
        for ticker, start, end, rate in (
            ("A", "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", 5.0),
            ("B", "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z", 7.0),
        ):
            rows.append({
                "ticker": ticker, "start": parse_ts(start), "end": parse_ts(end),
                "paid": True, "per_day": rate, "collateral": 10.0,
                "program_id": ticker + "-program", "target_size": 100.0,
                "discount_factor": 0.5,
            })
        result = time_aligned_portfolio(
            rows, parse_ts("2026-09-01T00:00:00Z"),
            parse_ts("2026-09-03T00:00:00Z"), markets=1, capital=10.0)
        self.assertAlmostEqual(result["reward"], 12.0)
        self.assertAlmostEqual(result["reward_per_day"], 6.0)

    def test_overlapping_programs_on_one_ticker_share_collateral(self):
        start, end = map(parse_ts, (
            "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"))
        rows = [
            {"ticker": "A", "start": start, "end": end, "paid": True,
             "per_day": 3.0, "collateral": 10.0, "program_id": "p1",
             "target_size": 100.0, "discount_factor": 0.5},
            {"ticker": "A", "start": start, "end": end, "paid": True,
             "per_day": 2.0, "collateral": 10.0, "program_id": "p2",
             "target_size": 100.0, "discount_factor": 0.5},
        ]
        result = time_aligned_portfolio(
            rows, start, end, markets=1, capital=10.0)
        self.assertAlmostEqual(result["reward"], 5.0)
        self.assertAlmostEqual(result["average_collateral"], 10.0)


if __name__ == "__main__":
    unittest.main()
