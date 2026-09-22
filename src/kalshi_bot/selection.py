"""Bounded advisory selection. No mutation, I/O, profitability or authority claim."""
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal, localcontext

from .config import BotConfig
from .exits import ExitTerms, cross
from .portfolio import PortfolioView
from .ranking import RankingBoard, RankedMarket
from .risk import WindowState, admit_entry
from .values import InvalidData, decimal, identity, integer, utc


@dataclass(frozen=True)
class SelectionReport:
    additions: tuple[RankedMarket, ...]
    retained: tuple[str, ...]
    exclusions: tuple[tuple[str, tuple[str, ...]], ...]
    blockers: tuple[str, ...]
    estimated_capital: Decimal = Decimal(0)
    authorized: bool = False


class MarketSelector:
    def __init__(self, capacity=128):
        self.board = RankingBoard(capacity)
        self._fees = {}
        self.exit_stress = {}  # Diagnostic loss on current visible depth, not expected loss.

    def invalidate(self, ticker):
        for row in self.board.markets.get(ticker, ()):
            self._fees.pop((ticker, row.program_id), None)
            self.exit_stress.pop((ticker, row.program_id), None)
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
        rows = []
        for row in self.board.markets[book.ticker]:
            if row.blockers:
                rows.append(row)
                continue
            losses, complete = [], True
            with localcontext() as ctx:
                ctx.prec = 40
                for q in row.quotes:
                    ok, _, pnl = cross(book, q.quantity if q.side == 'bid' else -q.quantity,
                                       q.yes_price, terms.bands, fee, Decimal(1))
                    complete &= ok
                    losses.append(max(Decimal(0), -pnl))
                reserve = sum((q.quantity for q in row.quotes), Decimal(0))*fee
            if not complete:
                row = replace(row, quotes=(), gross_hourly_usd=None, gross_remaining_usd=None,
                              gross_hourly_per_capital=None, blockers=('exit_depth_missing',))
            else:
                self._fees[(row.ticker, row.program_id)] = reserve
                self.exit_stress[(row.ticker, row.program_id)] = tuple(losses)
            rows.append(row)
        self.board.markets[book.ticker] = tuple(rows)

    def propose(self, *, view, window, free_cash, account_known, now, protected=(),
                current=lambda ticker: False):
        """Greedy two-slot additions, not reservations; source check defaults closed.

        Existing exposure/positions and explicit unresolved owners stay managed.
        All money must be revalidated by the writer at actual consumption.
        """
        now = utc(now)
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
        integer(window.cap, 0, 30)
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
        config = BotConfig()
        with localcontext() as ctx:
            ctx.prec = 40
            for row in self.board.ranked(now=now, by='selection'):
                blocked = row.blockers
                if row.ticker in retained:
                    blocked += ('existing_owner_retained',)
                if current(row.ticker) is not True:
                    blocked += ('selection_sources_changed',)
                if not blocked:
                    # No partial pair, duplicates, resized or zero-reward order set.
                    if (len(row.quotes) != 2 or {q.side for q in row.quotes} != {'bid', 'ask'}
                            or any(q.quantity != config.entry_contracts for q in row.quotes)
                            or row.quote_basis != 'hypothetical_reference'):
                        blocked += ('unsupported_entry_pair',)
                    elif row.gross_hourly_usd <= 0:
                        blocked += ('no_projected_reward',)
                if not blocked:
                    cost = row.capital_usd + self._fees[(row.ticker, row.program_id)]
                    blocked = admit_entry(config, window=window, ticker=row.ticker,
                        current_position=positions.get(row.ticker, Decimal(0)),
                        resting_entries=entries+1, candidate_loss=cost, exposure=exposure,
                        free_capital=cash-spent, account_known=True, now=now)
                if blocked:
                    exclusions.append((row.ticker, tuple(dict.fromkeys(blocked))))
                    continue
                additions.append(row)
                entries += 2
                spent += cost
                exposure[row.ticker] = exposure.get(row.ticker, Decimal(0))+cost
        return SelectionReport(tuple(additions), tuple(sorted(retained)), tuple(exclusions), (), spent)
