"""Bounded advisory selection. No mutation, I/O, profitability or authority claim."""
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal, localcontext

from .config import BotConfig, active as active_config, activate as activate_config
from .exits import ExitTerms, cross
from .portfolio import PortfolioView
from .ranking import RankingBoard, RankedMarket
from .risk import WindowState, admit_entry
from .values import InvalidData, decimal, identity, integer, utc
from .risk import MAX_RESTING_ENTRIES


@dataclass(frozen=True)
class SelectionReport:
    additions: tuple[RankedMarket, ...]
    retained: tuple[str, ...]
    exclusions: tuple[tuple[str, tuple[str, ...]], ...]
    blockers: tuple[str, ...]
    estimated_capital: Decimal = Decimal(0)
    authorized: bool = False


class MarketSelector:
    def __init__(self, capacity=128, quantity=None):
        self.board = RankingBoard(capacity, quantity)
        self._fees = {}
        self.exit_stress = {}  # Diagnostic loss on current visible depth, not expected loss.
        self.entry_retained_value = {}  # Per-side current-depth value ratio after fee bound.

    def invalidate(self, ticker):
        for row in self.board.markets.get(ticker, ()):
            self._fees.pop((ticker, row.program_id), None)
            self.exit_stress.pop((ticker, row.program_id), None)
            self.entry_retained_value.pop((ticker, row.program_id), None)
        self.board.invalidate(ticker)

    def update(self, book, programs, *, terms, now, valid_until, position=Decimal(0),
               blockers=(), proposed=None, reflected=()):
        self.invalidate(book.ticker)
        try:
            self._update(book, programs, terms=terms, now=now, valid_until=valid_until,
                         position=position, blockers=blockers, proposed=proposed, reflected=reflected)
        except BaseException:
            self.invalidate(book.ticker)
            raise

    def _update(self, book, programs, *, terms, now, valid_until, position,
                blockers, proposed, reflected):
        now = utc(now)
        if not isinstance(terms, ExitTerms) or terms.ticker != book.ticker:
            raise InvalidData('matching reviewed exit terms required')
        if type(blockers) is not tuple:
            raise InvalidData('immutable blocker codes required')
        reasons = blockers
        if not terms.observed_at <= now < terms.valid_until:
            reasons += ('exit_terms_stale',)
        if terms.event_risk_at is None:
            reasons += ('event_risk_clock_missing',)
        fee = terms.taker_fee_per_contract_bound
        if fee is None:
            reasons += ('exit_fee_bound_missing',)
        self.board.update(book, programs, terms.bands, now=now,
            valid_until=min(utc(valid_until), terms.valid_until), market_open=terms.active,
            position=position, blockers=reasons, proposed=proposed, reflected=reflected,
            entry_until=terms.deadline)
        # Check every program's actual quote set, not just the current best row.
        rows, config = [], active_config()
        for row in self.board.markets[book.ticker]:
            if row.blockers:
                rows.append(row)
                continue
            losses, retained_values, complete = [], [], True
            with localcontext() as ctx:
                ctx.prec = 40
                for q in row.quotes:
                    ok, _, pnl = cross(book, q.quantity if q.side == 'bid' else -q.quantity,
                                       q.yes_price, terms.bands, fee, Decimal(1), excluded=reflected)
                    complete &= ok
                    losses.append(max(Decimal(0), -pnl))
                    stake = q.quantity*(q.yes_price if q.side == 'bid' else 1-q.yes_price)
                    retained_values.append((stake+pnl)/stake)
                reserve = sum((q.quantity for q in row.quotes), Decimal(0))*fee
            if not complete:
                row = replace(row, quotes=(), gross_hourly_usd=None, gross_remaining_usd=None,
                              gross_hourly_per_capital=None,
                              blockers=row.blockers+('exit_depth_missing',))
            else:
                self.exit_stress[(row.ticker, row.program_id)] = tuple(losses)
                self.entry_retained_value[(row.ticker, row.program_id)] = tuple(retained_values)
                if any(value < config.minimum_entry_retained_value for value in retained_values):
                    row = replace(row, quotes=(), gross_hourly_usd=None,
                                  gross_remaining_usd=None, gross_hourly_per_capital=None,
                                  blockers=row.blockers+('entry_retained_value_below_minimum',))
                elif any((q.yes_price if q.side == 'bid' else 1-q.yes_price)
                         > config.maximum_entry_downside for q in row.quotes):
                    # D-155: one fill on this leg could lose too much per contract.
                    row = replace(row, quotes=(), gross_hourly_usd=None,
                                  gross_remaining_usd=None, gross_hourly_per_capital=None,
                                  blockers=row.blockers+('entry_downside_above_cap',))
                else:
                    self._fees[(row.ticker, row.program_id)] = reserve
            rows.append(row)
        self.board.markets[book.ticker] = tuple(rows)

    def propose(self, *, view, window, free_cash, account_known, now, protected=(),
                current=lambda ticker: False, continuations=None, entry_allowed=lambda t,p: True,
                finish=None):
        """Greedy two-slot additions, not reservations; source check defaults closed.

        Existing exposure/positions and explicit unresolved owners stay managed.
        All money must be revalidated by the writer at actual consumption.
        """
        now = utc(now)
        continuations = {} if continuations is None else continuations
        if type(continuations) is not dict or len(continuations) > 1:
            raise InvalidData('one bounded same-program maintenance continuation required')
        for ticker, (program_id, credit) in continuations.items():
            identity(ticker); identity(program_id)
            if decimal(credit) < 0:
                raise InvalidData('negative estimated continuation reward')
        if not isinstance(view, PortfolioView) or not isinstance(window, WindowState):
            raise InvalidData('writer portfolio and risk-window observations required')
        if type(protected) is not tuple or len(protected) > self.board.capacity:
            raise InvalidData('bounded protected owner set required')
        for ticker in protected:
            identity(ticker)
        if len(view.exposure) > self.board.capacity or len(view.positions) > self.board.capacity:
            raise InvalidData('portfolio exceeds selector scope')
        exposure, positions = dict(view.exposure), dict(view.positions)
        if len(exposure) != len(view.exposure) or len(positions) != len(view.positions):
            raise InvalidData('duplicate portfolio market')
        exposure = {identity(t): decimal(v) for t, v in exposure.items()}
        positions = {identity(t): decimal(v) for t, v in positions.items()}
        if any(v < 0 for v in exposure.values()):
            raise InvalidData('negative portfolio exposure')
        retained = set(protected) | {t for t, v in exposure.items() if v} | {t for t, v in positions.items() if v}
        cash = decimal(free_cash)
        if cash < 0:
            raise InvalidData('negative free cash')
        integer(view.entry_count, 0, 4096)
        integer(window.cap, 0, MAX_RESTING_ENTRIES)
        reasons = tuple(view.blockers)
        if account_known is not True:
            reasons += ('unknown_account',)
        if not timedelta(0) <= now-utc(view.observed_at) <= timedelta(seconds=5):
            reasons += ('stale_portfolio',)
        if (not window.start <= now < window.end or
                not timedelta(0) <= now-utc(window.observed_at) <= timedelta(seconds=5)):
            reasons += ('stale_risk_window',)
        if window.held or view.entry_count >= window.cap:
            reasons += ('entry_cap',)
        if reasons:
            return SelectionReport((), tuple(sorted(retained)), (), tuple(dict.fromkeys(reasons)))
        additions, exclusions = [], []
        entries, spent = view.entry_count, Decimal(0)
        config = active_config()
        ranked = self.board.ranked_programs(now=now, by='selection')
        # Stable tiers preserve the existing reward-rate/capital ordering within
        # each tier while reserving available slots for projected $2+ programs.
        plans = {}
        def finish_plan(row):
            key = (row.ticker, row.program_id)
            if key not in plans:
                plans[key] = finish.plan(row, now)
            return plans[key]
        if finish is not None:
            # D-161 phase 3: projects first (closest to $1), then new projects
            # while the list has room, then contracts already past $1.
            finish.review(now)
            ranked = tuple(sorted(ranked, key=lambda row: (
                (True,) if row.blockers else
                (False, 9, 0) if isinstance(finish_plan(row), str) else (False,)+finish_plan(row))))
        else:
            ranked = tuple(sorted(ranked, key=lambda row: (
                bool(row.blockers),
                row.gross_remaining_usd is None
                or row.gross_remaining_usd < config.priority_projected_reward_usd,
            )))
        source_current = {}
        def entry_blockers(row):
            blocked = row.blockers
            if not entry_allowed(row.ticker, row.program_id):
                blocked += ('incumbent_maintenance_reserved',)
            if row.ticker in retained:
                blocked += ('existing_owner_retained',)
            if row.ticker not in source_current:
                source_current[row.ticker] = current(row.ticker) is True
            if not source_current[row.ticker]:
                blocked += ('selection_sources_changed',)
            if not blocked:
                # No partial pair, duplicates, resized or zero-reward order set.
                if (len(row.quotes) != 2 or {q.side for q in row.quotes} != {'bid', 'ask'}
                        or any(q.quantity != config.entry_contracts for q in row.quotes)
                        or row.quote_basis != 'hypothetical_reference'):
                    blocked += ('unsupported_entry_pair',)
                elif (row.quote_statuses != ('full_price_weight', 'full_price_weight')
                      or any(q.yes_price != (row.bid_reference if q.side == 'bid'
                                            else row.ask_reference)
                             for q in row.quotes)):
                    blocked += ('initial_quote_not_at_full_weight_reference',)
                elif row.gross_hourly_usd is None or row.gross_hourly_usd <= 0:
                    blocked += ('no_projected_reward',)
                elif (row.gross_remaining_usd is None
                      or row.gross_remaining_usd + (continuations[row.ticker][1]
                          if row.ticker in continuations
                          and continuations[row.ticker][0] == row.program_id else Decimal(0))
                      < config.minimum_projected_reward_usd):
                    blocked += ('projected_reward_below_minimum',)
                elif finish is not None and isinstance(finish_plan(row), str):
                    blocked += (finish_plan(row),)
            return blocked

        # Qualify every overlapping program before retaining exactly one market
        # row. Otherwise a short high-rate program can hide an eligible longer one.
        selected, first_blocked, chosen = set(), {}, []
        for row in ranked:
            if row.ticker in selected:
                continue
            blocked = entry_blockers(row)
            if blocked:
                first_blocked.setdefault(row.ticker, row)
                continue
            selected.add(row.ticker)
            chosen.append(row)
        chosen.extend(row for ticker, row in first_blocked.items() if ticker not in selected)
        ranked = tuple(chosen)
        with localcontext() as ctx:
            ctx.prec = 40
            for row in ranked:
                blocked = entry_blockers(row)
                if not blocked:
                    cost = row.capital_usd + self._fees[(row.ticker, row.program_id)]
                    blocked = admit_entry(config, window=window, ticker=row.ticker,
                        current_position=positions.get(row.ticker, Decimal(0)),
                        resting_entries=entries+1, candidate_loss=cost, exposure=exposure,
                        free_capital=cash-spent, account_known=True, now=now)
                if not blocked and finish is not None and not finish.claim(row, now):
                    blocked = ('project_list_full',)
                if blocked:
                    exclusions.append((row.ticker, tuple(dict.fromkeys(blocked))))
                    continue
                additions.append(row)
                entries += 2
                spent += cost
                exposure[row.ticker] = exposure.get(row.ticker, Decimal(0))+cost
        return SelectionReport(tuple(additions), tuple(sorted(retained)), tuple(exclusions), (), spent)
