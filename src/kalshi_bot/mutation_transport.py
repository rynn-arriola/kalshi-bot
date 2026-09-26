"""Bounded Kalshi V2 order transport, disabled without explicit activation.

The runtime injects this object into the existing single mutation owner. It
does not load credentials, retry writes, infer rejection from timeouts, or
create live authority. Tests use an injected wire with ``offline_fixture=True``.
"""
import asyncio
from dataclasses import dataclass, field
import json
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .execution import batch_acknowledgement, validate_entry_pair, validate_request
from .mutation_outcomes import MutationHTTPFailure
from .rest import WireResponse, decode
from .transport import MutationSigner, REST_BASE
from .values import InvalidData, identity, integer
from .live_session import LiveSession, permits


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def mutation_wire(url, method, headers, body, max_bytes, timeout):
    """Blocking bounded wire function; never retries or follows redirects."""
    if method not in {'POST', 'DELETE', 'PUT'} or not isinstance(body, bytes):
        raise InvalidData('invalid mutation wire request')
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(url, data=body or None, headers=headers, method=method)
    deadline = time.monotonic()+timeout
    try:
        response = opener.open(request, timeout=min(5, timeout))
    except HTTPError as exc:
        status = exc.code
        with exc:
            payload = bytearray()
            while True:
                if time.monotonic() > deadline:
                    raise InvalidData('mutation response deadline exhausted')
                reader = getattr(exc, 'read1', exc.read)
                part = reader(min(65536, max_bytes+1-len(payload)))
                payload.extend(part)
                if len(payload) > max_bytes:
                    raise InvalidData('mutation response byte limit exceeded')
                if not part:
                    return WireResponse(status, bytes(payload))
    with response:
        payload = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise InvalidData('mutation response deadline exhausted')
            part = response.read1(min(65536, max_bytes+1-len(payload)))
            payload.extend(part)
            if len(payload) > max_bytes:
                raise InvalidData('mutation response byte limit exceeded')
            if not part:
                return WireResponse(response.status, bytes(payload))


def batch_scope(requests):
    validate_entry_pair(requests)
    encoded = json.dumps(sorted(requests, key=lambda row: row['client_order_id']),
                         sort_keys=True, separators=(',', ':'), allow_nan=False)
    import hashlib
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass
class MutationActivation:
    """Single-use, exact-scope capability for the bounded live canary only."""
    run_id: str | None = None
    ticker: str | None = None
    subaccount: int | None = None
    exchange_index: int | None = None
    client_order_ids: frozenset[str] = field(default_factory=frozenset)
    batch_digest: str | None = None
    _entry_used: bool = field(default=False, init=False, repr=False)
    _order_ids: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self):
        if None in (self.run_id, self.ticker, self.subaccount, self.exchange_index,
                    self.batch_digest):
            raise InvalidData('mutation activation requires exact canary scope')
        identity(self.run_id); identity(self.ticker)
        integer(self.subaccount, 0, 63); integer(self.exchange_index, 0, 2**31-1)
        if (type(self.client_order_ids) is not frozenset
                or len(self.client_order_ids) != 2):
            raise InvalidData('canary activation requires exactly two client orders')
        for value in self.client_order_ids:
            identity(value)
        if (not isinstance(self.batch_digest, str) or len(self.batch_digest) != 64
                or any(c not in '0123456789abcdef' for c in self.batch_digest)):
            raise InvalidData('canary batch digest required')

    def authorize_batch(self, requests):
        if self._entry_used:
            raise InvalidData('canary entry capability already consumed')
        validate_entry_pair(requests)
        if ({row['ticker'] for row in requests} != {self.ticker}
                or {row['subaccount'] for row in requests} != {self.subaccount}
                or {row['exchange_index'] for row in requests} != {self.exchange_index}
                or {row['client_order_id'] for row in requests} != self.client_order_ids
                or batch_scope(requests) != self.batch_digest
                or any(row['count'] != '10' or row['post_only'] is not True
                       or row['reduce_only'] is not False for row in requests)):
            raise InvalidData('batch is outside canary activation scope')
        self._entry_used = True

    def record_outcomes(self, outcomes):
        for row in outcomes:
            if row['state'] == 'ack':
                self._order_ids.add(identity(row['order_id']))

    def authorize_cancel(self, request):
        if (request['subaccount'] != self.subaccount
                or request['exchange_index'] != self.exchange_index
                or request['market_ticker'] != self.ticker
                or request['order_id'] not in self._order_ids):
            raise InvalidData('cancel is outside canary activation scope')


class OrderMutationTransport:
    def __init__(self, signer, *, wire=mutation_wire, activation=None,
                 offline_fixture=False, max_bytes=1048576, timeout=10):
        if not isinstance(signer, MutationSigner) or not callable(wire):
            raise InvalidData('explicit mutation signer and wire required')
        integer(max_bytes, 1024, 4194304)
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise InvalidData('bounded mutation timeout required')
        if (offline_fixture is not True and not isinstance(activation, MutationActivation)
                and not permits(activation)):
            raise InvalidData('live mutation activation unavailable')
        if offline_fixture is True and wire is mutation_wire:
            raise InvalidData('offline fixture requires an injected non-network wire')
        self.signer, self.wire = signer, wire
        self.max_bytes, self.timeout = max_bytes, timeout
        self.offline_fixture = offline_fixture
        self.activation = activation

    @staticmethod
    def _body(request):
        body = json.dumps(request, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode()
        if len(body) > 32768:
            raise InvalidData('mutation request byte limit exceeded')
        return body

    async def _send(self, method, path, body, success, allow_empty=False):
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        if body:
            headers['Content-Type'] = 'application/json'
        headers.update(self.signer.headers(method, '/trade-api/v2'+path))
        response = await asyncio.to_thread(self.wire, REST_BASE+path, method,
            headers, body, self.max_bytes, self.timeout)
        if not isinstance(response, WireResponse):
            raise InvalidData('invalid mutation wire response')
        if response.status != success:
            code = None
            if response.body:
                try:
                    candidate = decode(response.body).get('code')
                    if (isinstance(candidate, str) and len(candidate) <= 100
                            and candidate.isascii()
                            and all(character.isalnum() or character in '._-'
                                    for character in candidate)):
                        code = candidate
                except InvalidData:
                    pass
            raise MutationHTTPFailure(response.status, code)
        if not response.body:
            if allow_empty:
                return {}
            raise InvalidData('mutation success response missing')
        return decode(response.body)

    async def __call__(self, kind, request):
        validate_request(kind, request)
        if not self.offline_fixture:
            if type(self.activation) is LiveSession:
                self.activation.check(kind, request)
            elif kind == 'create':
                raise InvalidData('live canary requires one exact batch create')
            else:
                self.activation.authorize_cancel(request)
        if kind == 'create':
            return await self._send('POST', '/portfolio/events/orders',
                                    self._body(request), 201)
        query = urlencode({'subaccount': request['subaccount'],
            'exchange_index': request['exchange_index'],
            'market_ticker': request['market_ticker']})
        path = '/portfolio/events/orders/'+quote(request['order_id'], safe='')+'?'+query
        return await self._send('DELETE', path, b'', 200)

    async def order_group(self, kind, request):
        """D-145: create or reset one entry order group; never an order."""
        from .order_groups import validate_group_request
        validate_group_request(kind, request)
        if not self.offline_fixture:
            if type(self.activation) is not LiveSession:
                raise InvalidData('order groups require the live session')
            self.activation.check(kind, request)
        if kind == 'group_create':
            return await self._send('POST', '/portfolio/order_groups/create',
                                    self._body(request), 201)
        query = urlencode({'subaccount': request['subaccount'],
                           'exchange_index': request['exchange_index']})
        path = ('/portfolio/order_groups/'+quote(request['order_group_id'], safe='')
                +'/reset?'+query)
        return await self._send('PUT', path, b'', 200, allow_empty=True)

    def preflight(self, kind, requests):
        """D-143: the stateless local gate an entry batch must pass, with no I/O.

        Raising here proves nothing was sent; the executor then aborts the
        prepared commands as not submitted instead of recording UNKNOWN.
        """
        if kind != 'batch_create' or self.offline_fixture:
            return
        validate_entry_pair(requests)
        if type(self.activation) is LiveSession:
            self.activation.check('batch_create', requests)

    async def batch(self, requests):
        validate_entry_pair(requests)
        if not self.offline_fixture:
            if type(self.activation) is LiveSession:
                self.activation.check('batch_create', requests)
            else:
                self.activation.authorize_batch(requests)
        # Batch writes are unscoped for quota accounting even though every leg
        # retains an explicit exchange_index in its immutable request.
        response = await self._send('POST', '/portfolio/events/orders/batched',
                                    self._body({'orders': list(requests)}), 201)
        if not self.offline_fixture and isinstance(self.activation, MutationActivation):
            self.activation.record_outcomes(batch_acknowledgement(requests, response))
        return response

    def __repr__(self):
        return 'OrderMutationTransport(<redacted>, live_ready=False)'
