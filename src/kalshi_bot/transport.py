"""WebSocket transport and path-scoped signers; no automatic live runner."""
import asyncio
import base64
from dataclasses import dataclass
import hashlib
import json
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from websockets.asyncio.client import connect

from .book_refresh import BookRefresh
from .values import InvalidData, identity, integer

WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
REST_BASE = "https://external-api.kalshi.com/trade-api/v2"


class Signer:
    def __init__(self, key_id: str, private_pem: bytes):
        self._key_id = identity(key_id)
        self._key = serialization.load_pem_private_key(private_pem, password=None)
        if not isinstance(self._key, rsa.RSAPrivateKey) or self._key.key_size < 2048:
            raise InvalidData("RSA key of at least 2048 bits required")

    def _headers(self, method: str, path: str, timestamp_ms: int | None = None) -> dict:
        stamp = integer(timestamp_ms if timestamp_ms is not None else time.time_ns()//1000000,
                        1, 2**63-1)
        message = f"{stamp}{method}{path.split('?')[0]}".encode()
        signature = self._key.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                  salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        return {"KALSHI-ACCESS-KEY": self._key_id, "KALSHI-ACCESS-TIMESTAMP": str(stamp),
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()}

    def headers(self, method: str, path: str, timestamp_ms: int | None = None) -> dict:
        if method != "GET" or not path.startswith("/trade-api/") or "://" in path:
            raise InvalidData("this foundation signer is read-only and path-scoped")
        return self._headers(method, path, timestamp_ms)

    def __repr__(self):
        return "Signer(<redacted>)"


class MutationSigner(Signer):
    """Explicit order-path signer; construction still performs no I/O."""
    def headers(self, method: str, path: str, timestamp_ms: int | None = None) -> dict:
        clean = path.split('?', 1)[0]
        prefix = '/trade-api/v2/portfolio/events/orders'
        suffix = clean[len(prefix):] if clean.startswith(prefix) else None
        allowed = ((method == 'POST' and suffix in {'', '/batched'})
                   or (method == 'DELETE' and suffix is not None
                       and suffix.startswith('/') and suffix != '/batched'
                       and '/' not in suffix[1:] and len(suffix) > 1))
        if not allowed or '://' in path:
            raise InvalidData('mutation signer is restricted to event-order paths')
        return self._headers(method, path, timestamp_ms)


@dataclass(frozen=True)
class Subscription:
    name: str
    channels: tuple[str, ...]
    tickers: tuple[str, ...] = ()
    yes_prices: bool = False

    def command(self) -> dict:
        params = {"channels": list(self.channels)}
        if self.tickers:
            params["market_tickers"] = list(self.tickers)
        if self.yes_prices:
            params["use_yes_price"] = True
        return {"id": 1, "cmd": "subscribe", "params": params}


def topology(tickers: tuple[str, ...], *, market_capacity: int = 128) -> tuple[Subscription, ...]:
    integer(market_capacity, 1, 1024)
    if not tickers or len(set(tickers)) != len(tickers) or len(tickers) > market_capacity:
        raise InvalidData("invalid stream market scope")
    groups: list[list[str]] = [[], []]
    for ticker in sorted(tickers):
        identity(ticker)
        bucket = int.from_bytes(hashlib.blake2b(ticker.encode(), digest_size=8).digest(), "big") % 2
        groups[bucket].append(ticker)
    books = [Subscription(f"book-{index}", ("orderbook_delta",), tuple(group), True)
             for index, group in enumerate(groups) if group]
    return tuple(books + [Subscription("account", ("user_orders", "fill", "market_positions", "order_group_updates")),
                          Subscription("lifecycle", ("market_lifecycle_v2",))])


class WebSocketReaders:
    """One bounded merger, serial callback owner; failure cancels all readers.

    No automatic reconnect yet: caller must invalidate proof and explicitly
    create a new generation. No connection is opened by construction/import.
    """
    def __init__(self, signer: Signer, subscriptions: tuple[Subscription, ...], *,
                 capacity: int = 8192, byte_capacity: int = 16777216, connector=connect):
        integer(capacity, 1, 65536)
        integer(byte_capacity, 1, 67108864)
        if not 1 <= len(subscriptions) <= 4 or len({s.name for s in subscriptions}) != len(subscriptions):
            raise InvalidData("invalid connection topology")
        self.signer, self.subscriptions, self.connector = signer, subscriptions, connector
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=capacity)
        self.byte_capacity, self.queued_bytes = byte_capacity, 0
        self.invalid = True
        self._used = False

    async def _refresh_books(self, socket, refresh):
        # One bounded control worker per book connection, not per market. Its
        # lifetime is joined with the receiver, including timeout/cancellation.
        while True:
            await asyncio.sleep(.5)
            command = refresh.next_command(time.monotonic())
            if command is not None:
                async with asyncio.timeout(2):
                    await socket.send(json.dumps(command))

    async def _pump(self, spec: Subscription):
        headers = self.signer.headers("GET", urlsplit(WS_URL).path)
        async with self.connector(WS_URL, additional_headers=headers, open_timeout=10,
                                  close_timeout=5, ping_interval=10, ping_timeout=10,
                                  max_size=1048576, max_queue=32, proxy=None,
                                  compression=None) as socket:
            await socket.send(json.dumps(spec.command()))
            async with asyncio.TaskGroup() as group:
                refresh = (BookRefresh(spec.tickers)
                           if spec.channels == ('orderbook_delta',) else None)
                if refresh is not None:
                    group.create_task(self._refresh_books(socket, refresh),
                                      name='kalshi-snapshot-'+spec.name)
                await self._receive(socket, spec, refresh)

    async def _receive(self, socket, spec, refresh):
        async for raw in socket:
            received = time.monotonic()
            wire_bytes = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
            if wire_bytes > 1048576 or self.queued_bytes + wire_bytes > self.byte_capacity:
                raise InvalidData("event byte budget exceeded: proof lost")
            event = json.loads(raw)
            if not isinstance(event, dict) or event.get("type") == "error":
                raise InvalidData("invalid or rejected WebSocket subscription")
            if refresh is not None:
                refresh.observe(event, received)
                # Transport-owned timestamp, never trust a wire-supplied value.
                event['_received_mono'] = received
            try:
                self.queue.put_nowait((spec.name, event, wire_bytes))
                self.queued_bytes += wire_bytes
            except asyncio.QueueFull as exc:
                raise InvalidData("event queue overflow: account/book proof lost") from exc
        raise InvalidData("WebSocket ended: proof lost")

    async def run(self, consume):
        if self._used:
            raise InvalidData("reader instance cannot be reused")
        self._used = True
        self.invalid = False
        try:
            async with asyncio.TaskGroup() as group:
                for spec in self.subscriptions:
                    group.create_task(self._pump(spec), name=spec.name)
                while True:
                    name, event, wire_bytes = await self.queue.get()
                    self.queued_bytes -= wire_bytes
                    await consume(name, event)
        finally:
            self.invalid = True
