"""Explicit process-local activation for the original single-writer runtime.

Not a source of risk/account proof: every command still needs the existing
durable reservation, source fence, cash lease and quota permit.
"""
from .values import InvalidData, identity, decimal


class LiveSession:
    def __init__(self, *, run_id, tickers):
        self.run_id = identity(run_id)
        if type(tickers) is not tuple or not 1 <= len(tickers) <= 128:
            raise InvalidData('bounded explicit live market scope required')
        self.tickers = frozenset(identity(t) for t in tickers)
        if len(self.tickers) != len(tickers):
            raise InvalidData('duplicate live market')
        self.writer = None
        self.closed = False
        self.entries_paused = False

    def bind(self, writer):
        if self.closed or self.writer is not None:
            raise InvalidData('live session can bind exactly one writer')
        self.writer = writer

    def close(self):
        self.entries_paused = True
        self.closed = True

    def check(self, kind, requests):
        if not permits(self):
            raise InvalidData('live session closed or unbound')
        rows = requests if kind == 'batch_create' else (requests,)
        for row in rows:
            ticker = row['market_ticker'] if kind == 'cancel' else row['ticker']
            if ticker not in self.tickers or row['subaccount'] != 0:
                raise InvalidData('request outside live session scope')
            if kind == 'batch_create':
                if self.entries_paused or decimal(row['count']) != 10 or row['reduce_only']:
                    raise InvalidData('new entry disabled or outside approved size')
            elif kind == 'create' and row['reduce_only'] is not True:
                raise InvalidData('single create is reserved for exact inventory reducers')


def permits(session, writer=None):
    return (type(session) is LiveSession and not session.closed
            and session.writer is not None
            and (writer is None or session.writer is writer)
            and not session.writer.failed)
