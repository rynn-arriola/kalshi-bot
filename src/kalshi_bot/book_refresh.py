"""Connection-local quiet-book snapshot requests; never grants book authority.

Actual snapshots/deltas still traverse the existing sequence-validating engine.
No heartbeat, sent request or successful command ACK makes a book fresh.
"""
from .values import InvalidData, identity, integer


class BookRefresh:
    QUIET_SECONDS = 3.
    RESPONSE_SECONDS = 5.
    BATCH = 100

    def __init__(self, tickers):
        if not tickers or len(tickers) > 1024 or len(set(tickers)) != len(tickers):
            raise InvalidData('invalid snapshot refresh scope')
        self.tickers = tuple(sorted(identity(t) for t in tickers))
        self.scope = frozenset(self.tickers)
        self.last = {}
        self.sid = None
        self.command_id = 1
        self.pending = set()
        self.deadline = None
        self.ack_at = None

    def observe(self, event, now):
        if self.pending and now >= self.deadline:
            raise InvalidData('snapshot response deadline exceeded')
        kind = event.get('type')
        if kind == 'subscribed':
            msg = event.get('msg', {})
            if (self.sid is not None or event.get('id') != 1
                    or msg.get('channel') != 'orderbook_delta'):
                raise InvalidData('unexpected book acknowledgment')
            self.sid = integer(msg.get('sid'), 1, 2**63-1)
            self.ack_at = now
        elif kind in {'orderbook_snapshot', 'orderbook_delta'}:
            ticker = identity(event.get('msg', {}).get('market_ticker'))
            if (self.sid is None or type(event.get('sid')) is not int
                    or event.get('sid') != self.sid or ticker not in self.scope):
                raise InvalidData('snapshot refresh source mismatch')
            reply = event.get('id')
            if kind == 'orderbook_snapshot':
                if reply is not None and (type(reply) is not int
                        or reply != self.command_id or ticker not in self.pending):
                    raise InvalidData('unexpected snapshot response identity')
                # Command ID is optional in the published schema. Exact SID,
                # ticker, connection generation and downstream sequence still bind it.
                self.pending.discard(ticker)
                if not self.pending:
                    self.deadline = None
            self.last[ticker] = now

    def next_command(self, now):
        if self.sid is None:
            return None
        if self.pending:
            if now >= self.deadline:
                raise InvalidData('snapshot response deadline exceeded')
            return None
        due = [t for t in self.tickers
               if now - self.last.get(t, self.ack_at) >= self.QUIET_SECONDS]
        if not due:
            return None
        # Oldest first avoids starving quiet tail markets when scope exceeds a batch.
        due.sort(key=lambda t: (self.last.get(t, self.ack_at), t))
        selected = due[:self.BATCH]
        self.command_id = integer(self.command_id + 1, 2, 2**31-1)
        self.pending = set(selected)
        self.deadline = now + self.RESPONSE_SECONDS
        return dict(id=self.command_id, cmd='update_subscription',
                    params=dict(sids=[self.sid], market_tickers=selected,
                                action='get_snapshot'))
