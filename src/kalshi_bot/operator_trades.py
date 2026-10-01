"""D-165: a settled operator trade in a market the bot never traded.

The operator bought a combo on the bot's account by hand (2026-09-30) while the
bot was stopped. Kalshi moved cash to another exchange shard for it, the trade
filled there and the market settled. None of it is the bot's: it must neither
enter the trading ledger (no lots, no realized P&L, no loss limit) nor stay
unexplained (recovery saw a missing fill, accounting a new transfer, a new
settlement and missing cash).

``record`` adopts exactly that evidence once, while the bot is stopped: the
fills, the settlement and the funding transfers must agree with each other to
the last digit, and the market must be closed on the venue. The cash effect per
shard is journaled as an ``operator_trade`` cash adjustment, so the cold cash
audit reproduces it. Recovery, settlement proof and cash-activity checks then
accept only the recorded identities (exact payload digests); anything new or
changed still blocks.
"""
import json
from decimal import Decimal, localcontext

from .values import InvalidData, identity, utc

ZERO = Decimal(0)
MAX_TRADES = 32


def _rows(conn):
    rows = conn.execute('SELECT ticker,payload FROM operator_trades LIMIT ?', (MAX_TRADES+1,)).fetchall()
    if len(rows) > MAX_TRADES:
        raise InvalidData('operator trade capacity exceeded')
    return [(row[0], json.loads(row[1])) for row in rows]


def fill_keys(conn):
    """Venue fill keys that belong to recorded operator trades."""
    return {key for _, value in _rows(conn) for key in value['fills']}


def activity_digests(conn):
    """{(kind, event_key): fingerprint} of recorded operator funding transfers."""
    return {('intra_exchange_transfer', item['event_key']): item['digest']
            for _, value in _rows(conn) for item in value['transfers']}


def settlements(conn):
    """{ticker: (event_key, payload digest)} of recorded operator settlements."""
    return {ticker: (value['settlement']['event_key'], value['settlement']['digest'])
            for ticker, value in _rows(conn)}


def record(ledger, *, records, settlement, transfers, reference, now):
    """Adopt one settled operator trade. Caller holds account ownership with
    the bot stopped, and passes fresh venue evidence: ``records`` (history
    fills of one market), its ``settlement`` and the ``transfers`` that funded
    it. Returns the cash change per shard."""
    from .accounting import _append, digest, encode
    from .cash_attribution import CashAdjustment, apply
    from .opening_account import IntraExchangeTransfer, SettlementObservation
    reference, now = identity(reference), utc(now)
    if (type(records) is not tuple or not 1 <= len(records) <= 64
            or not isinstance(settlement, SettlementObservation)
            or type(transfers) is not tuple or len(transfers) > 8
            or any(not isinstance(t, IntraExchangeTransfer) for t in transfers)):
        raise InvalidData('typed operator trade evidence required')
    ticker, shard = settlement.ticker, settlement.exchange_index
    keys = tuple(record.fill.key for record in records)
    if (len(set(keys)) != len(keys)
            or any(record.fill.ticker != ticker or record.subaccount != 0
                   or record.exchange_index != shard for record in records)
            or settlement.result not in {'yes', 'no'}
            or settlement.value_cents not in (None, 100 if settlement.result == 'yes' else 0)):
        raise InvalidData('operator trade fills and settlement differ')
    with localcontext() as ctx:
        ctx.prec = 40
        yes = [r.fill for r in records if r.fill.book_side == 'bid']
        no = [r.fill for r in records if r.fill.book_side == 'ask']
        yes_count = sum((f.quantity for f in yes), ZERO)
        no_count = sum((f.quantity for f in no), ZERO)
        yes_cost = sum((f.quantity*f.yes_price for f in yes), ZERO)
        no_cost = sum((f.quantity*(1-f.yes_price) for f in no), ZERO)
        fee = sum((r.fill.fee for r in records), ZERO)
        revenue = Decimal(settlement.revenue_cents)/100
        payout = yes_count if settlement.result == 'yes' else no_count
        if ((yes_count, yes_cost, no_count, no_cost, fee) !=
                (settlement.yes_count, settlement.yes_cost, settlement.no_count,
                 settlement.no_cost, settlement.fee) or revenue != payout):
            raise InvalidData('operator trade economics differ from its settlement')
        cash = {shard: revenue-yes_cost-no_cost-fee}
        for t in transfers:
            if (t.status != 'complete' or t.source != 'event_contract'
                    or t.destination != 'event_contract'
                    or t.destination_exchange_index != shard
                    or t.source_exchange_index == shard):
                raise InvalidData('operator trade transfer scope differs')
            cash[t.source_exchange_index] = cash.get(t.source_exchange_index, ZERO)-t.amount
            cash[shard] += t.amount
    conn = ledger.connection
    with ledger.transaction():
        for table, column in (('fills', "json_extract(payload,'$[0]')"), ('lots', 'ticker'),
                              ('position_clocks', 'ticker'),
                              ('pending_fills', "json_extract(payload,'$.ticker')"),
                              ('order_evidence', "json_extract(payload,'$.ticker')"),
                              ('intents', "json_extract(payload,'$.ticker')")):
            if conn.execute(f'SELECT 1 FROM {table} WHERE {column}=? LIMIT 1', (ticker,)).fetchone():
                raise InvalidData('the bot traded this market; not an operator-only trade')
        if conn.execute('SELECT 1 FROM operator_trades WHERE ticker=?', (ticker,)).fetchone():
            raise InvalidData('operator trade already recorded')
        if len(_rows(conn)) >= MAX_TRADES:
            raise InvalidData('operator trade capacity reached')
        local = {r[0] for r in conn.execute('SELECT exchange_index FROM accounting_cash')}
        if not set(cash) <= local:
            raise InvalidData('operator trade shard has no opening baseline')
        settlement_key = encode([0, *settlement.key])
        value = dict(version=1, fills=list(keys),
                     fill_payloads=[r.fill.payload for r in records],
                     settlement=dict(event_key=settlement_key,
                                     digest=digest(encode(settlement))),
                     transfers=[dict(event_key=encode([t.transfer_id]),
                                     digest=digest(encode(['intra_exchange_transfer',
                                                           encode([t.transfer_id]), encode(t)])))
                                for t in transfers],
                     cash={str(k): format(v, 'f') for k, v in sorted(cash.items())})
        conn.execute('INSERT INTO operator_trades VALUES (?,?,?,?)',
                     (ticker, json.dumps(value, sort_keys=True, separators=(',', ':')),
                      reference, now.isoformat()))
        adjustments, fingerprints = [], []
        for index, amount in sorted(cash.items()):
            if not amount:
                continue
            item = CashAdjustment(f'operator_trade:{ticker}:{index}', index, amount, 'operator_trade')
            payload = encode(dict(source_key=item.source_key, exchange_index=index,
                                  amount=amount, kind=item.kind, policy='D-165', reference=reference))
            fingerprint, added = _append(ledger, 'cash_adjustment', encode([item.source_key]), payload, now)
            if not added:
                raise InvalidData('operator trade cash adjustment already journaled')
            adjustments.append(item)
            fingerprints.append(fingerprint)
        apply(conn, adjustments, event_digests=fingerprints, at=now)
    return cash
