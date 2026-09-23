"""Explicit process-local activation for the original single-writer runtime.

Not a source of risk/account proof: every command still needs the existing
durable reservation, source fence, cash lease and quota permit.
"""
from .values import InvalidData, identity, decimal


class LiveSession:
    def __init__(self, *, run_id, tickers):
        self.run_id = identity(run_id)
        if type(tickers) is not tuple or not 1 <= len(tickers) <= 1024:
            raise InvalidData('bounded explicit live market scope required')
        self.tickers = frozenset(identity(t) for t in tickers)
        if len(self.tickers) != len(tickers):
            raise InvalidData('duplicate live market')
        self.writer = None
        self.closed = False
        self.entries_paused = False
        self._armed_single_create = None

    def bind(self, writer):
        if self.closed or self.writer is not None:
            raise InvalidData('live session can bind exactly one writer')
        self.writer = writer

    def close(self):
        self.entries_paused = True
        self.closed = True
        self._armed_single_create = None

    def arm_single_create(self, receipt):
        """Bind one single-create transport call to a prepared managed exit."""
        from .command_types import PreparedMutation
        if (not permits(self) or not isinstance(receipt, PreparedMutation)
                or receipt.kind != 'create' or not receipt.reduction
                or self._armed_single_create is not None):
            raise InvalidData('single create lacks prepared reduction authority')
        self._armed_single_create = receipt.request_json

    def disarm_single_create(self):
        self._armed_single_create = None

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
            elif kind == 'create':
                from .execution import encoded_request
                if self._armed_single_create != encoded_request(row):
                    raise InvalidData('single create is reserved for prepared inventory reducers')
                self._armed_single_create = None


def permits(session, writer=None):
    return (type(session) is LiveSession and not session.closed
            and session.writer is not None
            and (writer is None or session.writer is writer)
            and not session.writer.failed)
