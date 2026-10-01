"""D-141: attribute external cash movements without stopping trading.

Kalshi credits deposits, debits withdrawals and pays liquidity rewards to the
account outside the bot's own order flow. Before D-141 any of them left local
expected cash unexplained and blocked entries permanently.

Rules (evaluated only when every other release check already passed):
- A funding record after the approved baseline changes expected cash once it
  is final: applied deposits add ``amount - fee``; applied withdrawals subtract
  ``amount + fee``. Failed/returned records change nothing.
- A pending deposit widens the upper cash bound and a pending withdrawal the
  lower bound, so neither blocks nor is counted twice when it completes.
- Venue cash above every explained bound is recorded as an unattributed
  credit (for example a liquidity-reward payout, which has no API record).
  More cash cannot increase trading risk: limits come from configuration.
- Venue cash below every explained bound still blocks: money is missing.
- Transfers between exchange shards or subaccounts still require the operator.

Every adjustment is journaled and kept in ``cash_adjustments`` so the cold
startup cash audit reproduces it exactly.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext
import json

from .values import InvalidData, decimal

ZERO = Decimal(0)
CENTS = Decimal(100)
FUNDING_SHARD = 0  # Account-level member funding settles on the primary shard.


@dataclass(frozen=True)
class CashAdjustment:
    source_key: str
    exchange_index: int
    amount: Decimal
    kind: str  # deposit | withdrawal | unattributed_credit | operator_trade (D-165)


@dataclass(frozen=True)
class CashPlan:
    adjustments: tuple
    unexplained: bool
    activity_explained: bool


def _baseline_activity(conn):
    """Event keys and exact digests of cash activity approved with the baseline."""
    row = conn.execute('SELECT payload FROM accounting_baseline WHERE id=1').fetchone()
    if row is None:
        return set(), set()
    approved = json.loads(row[0]).get('attributed_cash_activity', ())
    keys, digests = set(), set()
    for item in approved:
        digests.add(item.get('digest'))
        event = conn.execute('SELECT event_key FROM accounting_events WHERE digest=?',
                             (item.get('digest'),)).fetchone()
        if event is not None:
            keys.add(event[0])
    return keys, digests


def _funding_key(row):
    from .accounting import encode
    return encode([row.kind, row.record_id])  # Same identity as the journal's.


def plan(conn, evidence, *, local, venue, held, allow_credit):
    """Explain venue cash against local cash plus external movements.

    ``allow_credit`` is true only when every other release check passed; an
    inconsistent account never has its difference labelled a credit.
    """
    from .accounting import _cash_activity_rows
    approved, approved_digests = _baseline_activity(conn)
    recorded = {r[0] for r in conn.execute('SELECT source_key FROM cash_adjustments')}
    adjustments, upper_slack, lower_slack = [], {}, {}
    # Transfers between shards/subaccounts stay operator-attributed: only the
    # exact records approved with the baseline are explained.
    from .operator_trades import activity_digests
    operator = activity_digests(conn)   # D-165: recorded operator-trade transfers
    activity_explained = all(fingerprint in approved_digests
        or operator.get((kind, key)) == fingerprint
        for kind, key, _, fingerprint in _cash_activity_rows(evidence) if kind != 'funding')
    with localcontext() as ctx:
        ctx.prec = 40
        for row in evidence.funding:
            key = _funding_key(row)
            if key in approved or key in recorded:
                continue
            amount, fee = Decimal(row.amount_cents)/CENTS, Decimal(row.fee_cents)/CENTS
            if row.status == 'applied':
                adjustments.append(CashAdjustment(key, FUNDING_SHARD,
                    amount-fee if row.kind == 'deposit' else -(amount+fee), row.kind))
            elif row.status == 'pending':
                slack = upper_slack if row.kind == 'deposit' else lower_slack
                slack[FUNDING_SHARD] = slack.get(FUNDING_SHARD, ZERO)+amount+fee
            # failed/returned: no cash effect and nothing left to explain.
        expected = dict(local)
        for item in adjustments:
            if item.exchange_index not in expected:
                raise InvalidData('funding shard missing from local cash')
            expected[item.exchange_index] += item.amount
        unexplained = set(expected) != set(venue)
        for shard, value in expected.items():
            observed = venue.get(shard, ZERO)
            upper = value+upper_slack.get(shard, ZERO)
            lower = max(ZERO, value-held.get(shard, ZERO)-lower_slack.get(shard, ZERO))
            if observed < lower:
                unexplained = True
            elif observed > upper:
                if allow_credit:
                    adjustments.append(CashAdjustment(
                        f'credit:{shard}:{evidence.observed_at.isoformat()}', shard,
                        observed-upper, 'unattributed_credit'))
                else:
                    unexplained = True
    return CashPlan(tuple(adjustments), unexplained, activity_explained)


def apply(conn, adjustments, *, event_digests, at):
    """Commit inside the release transaction, after its journal events exist."""
    for item, fingerprint in zip(adjustments, event_digests, strict=True):
        row = conn.execute('SELECT cash FROM accounting_cash WHERE exchange_index=?',
                           (item.exchange_index,)).fetchone()
        if row is None:
            raise InvalidData('cash adjustment shard missing')
        with localcontext() as ctx:
            ctx.prec = 40
            cash = decimal(Decimal(row[0]))+item.amount
        conn.execute('UPDATE accounting_cash SET cash=? WHERE exchange_index=?',
                     (format(cash, 'f'), item.exchange_index))
        conn.execute('INSERT INTO cash_adjustments VALUES (?,?,?,?,?,?)',
                     (item.source_key, item.exchange_index, format(item.amount, 'f'),
                      item.kind, fingerprint, at.isoformat()))


def totals(conn):
    """Per-shard sum of journaled adjustments for the cold cash audit."""
    result = {}
    for row in conn.execute('SELECT exchange_index,amount,kind,event_digest FROM cash_adjustments'):
        if row[2] not in {'deposit', 'withdrawal', 'unattributed_credit', 'operator_trade'}:
            raise InvalidData('unknown cash adjustment kind')
        journaled = (conn.execute("SELECT 1 FROM accounting_events WHERE digest=? "
                                  "AND kind='cash_adjustment'", (row[3],)).fetchone()
                     or conn.execute('SELECT 1 FROM accounting_event_archive_members '
                                     'WHERE digest=?', (row[3],)).fetchone())
        if not journaled:
            raise InvalidData('cash adjustment lost its journal event')
        result[row[0]] = result.get(row[0], ZERO)+decimal(Decimal(row[1]))
    return result


def summary(conn):
    rows = conn.execute('SELECT kind,COUNT(*),amount FROM cash_adjustments GROUP BY kind').fetchall()
    out = {}
    for kind, count, _ in rows:
        total = sum((decimal(Decimal(r[0])) for r in conn.execute(
            'SELECT amount FROM cash_adjustments WHERE kind=?', (kind,))), ZERO)
        out[kind] = dict(count=count, total_usd=format(total, 'f'))
    return out
