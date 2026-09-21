"""Match captured books to the liquidity program terms active at that time.

The programs endpoint is a sequence of observations, not a static market
lookup.  A ticker can have several program IDs and a program can be edited
during capture.  Replays must therefore avoid applying the last program row to
the whole database.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass(frozen=True)
class ProgramTerms:
    program_id: str
    market_ticker: str
    observed_at: datetime
    start: datetime
    end: datetime
    period_reward: float
    target_size: float
    discount_factor: float

    @property
    def duration_days(self) -> float:
        return (self.end - self.start).total_seconds() / 86400.0

    def active_at(self, timestamp: datetime) -> bool:
        return self.start <= timestamp < self.end

    @property
    def signature(self) -> tuple:
        return (
            self.start, self.end, self.period_reward,
            self.target_size, self.discount_factor,
        )


def parse_program(raw: str, observed_at: str) -> ProgramTerms | None:
    row = json.loads(raw)
    try:
        terms = ProgramTerms(
            program_id=str(row["id"]),
            market_ticker=str(row["market_ticker"]),
            observed_at=parse_ts(observed_at),
            start=parse_ts(row["start_date"]),
            end=parse_ts(row["end_date"]),
            period_reward=float(row["period_reward"]),
            target_size=float(row["target_size_fp"]),
            discount_factor=float(row["discount_factor_bps"]) / 10000.0,
        )
    except (KeyError, TypeError, ValueError):
        return None
    if terms.end <= terms.start or terms.period_reward < 0:
        return None
    if terms.target_size <= 0 or not 0 < terms.discount_factor <= 1:
        return None
    return terms


class ProgramTimeline:
    """As-of matcher with conservative handling of edited program terms.

    Program IDs whose payout/scoring terms changed during capture are excluded.
    We cannot know from public snapshots which version governed final payout,
    and choosing one would silently bias modeled revenue.
    """

    def __init__(self, rows: Iterable[tuple[str, str]]):
        observations: dict[str, list[ProgramTerms]] = defaultdict(list)
        signatures: dict[str, set[tuple]] = defaultdict(set)
        self.invalid_rows = 0
        for observed_at, raw in rows:
            terms = parse_program(raw, observed_at)
            if terms is None:
                self.invalid_rows += 1
                continue
            observations[terms.market_ticker].append(terms)
            signatures[terms.program_id].add(terms.signature)
        self.unstable_ids = {
            program_id for program_id, values in signatures.items()
            if len(values) > 1
        }
        self.by_ticker: dict[str, list[ProgramTerms]] = {}
        for ticker, values in observations.items():
            stable = [v for v in values if v.program_id not in self.unstable_ids]
            # Stable terms repeat on every program poll.  The first observation
            # is sufficient to establish when the collector knew about them.
            first_by_id: dict[str, ProgramTerms] = {}
            for terms in sorted(stable, key=lambda v: v.observed_at):
                first_by_id.setdefault(terms.program_id, terms)
            self.by_ticker[ticker] = sorted(
                first_by_id.values(), key=lambda v: v.observed_at)
        self.stable_program_count = sum(len(v) for v in self.by_ticker.values())

    @classmethod
    def from_connection(cls, connection):
        return cls(connection.execute(
            "SELECT fetched_at, raw_json FROM programs ORDER BY fetched_at"
        ))

    def active_at(self, ticker: str, timestamp: datetime) -> list[ProgramTerms]:
        latest: dict[str, ProgramTerms] = {}
        for terms in self.by_ticker.get(ticker, ()):
            if terms.observed_at > timestamp:
                break
            latest[terms.program_id] = terms
        return [terms for terms in latest.values() if terms.active_at(timestamp)]
