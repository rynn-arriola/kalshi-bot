"""Bounded private-stream access probe, not a trading or recovery authority.

Uses the existing read-only reader. Retains counts only, never raw account
messages. Closing and reopening a socket tests re-subscription, NOT lost-fill
recovery, complete history, or eligibility to earn rewards.
"""
import asyncio
from dataclasses import dataclass, field
import time

from .transport import Subscription
from .values import InvalidData, integer


PRIVATE_SPEC = Subscription("account", ("user_orders", "fill", "market_positions", "order_group_updates"))
EVENT_CHANNELS = {
    "user_order": "user_orders", "fill": "fill",
    "market_position": "market_positions", "order_group_updates": "order_group_updates",
}


@dataclass
class ProbeState:
    max_messages: int = 256
    max_bytes: int = 2097152
    messages: int = 0
    wire_bytes: int = 0
    subscriptions: dict = field(default_factory=dict)
    event_counts: dict = field(default_factory=lambda: dict.fromkeys(EVENT_CHANNELS, 0))

    def __post_init__(self):
        integer(self.max_messages, 1, 4096)
        integer(self.max_bytes, 1, 4194304)

    @property
    def acknowledged(self):
        return set(self.subscriptions) == set(PRIVATE_SPEC.channels)

    def consume(self, name, event):
        # Existing transport bounds raw frame size/queue; bound the whole probe too.
        import json
        if name != "account" or not isinstance(event, dict):
            raise InvalidData("unexpected probe source or message")
        self.messages += 1
        self.wire_bytes += len(json.dumps(event, separators=(",", ":")).encode())
        if self.messages > self.max_messages or self.wire_bytes > self.max_bytes:
            raise InvalidData("probe resource budget exceeded")
        kind, msg = event.get("type"), event.get("msg")
        if not isinstance(msg, dict):
            raise InvalidData("invalid probe message body")
        if kind == "subscribed":
            channel, sid = msg.get("channel"), msg.get("sid")
            integer(sid, 1, 2**63-1)
            if (type(event.get("id")) is not int or event["id"] != 1
                    or channel not in PRIVATE_SPEC.channels
                    or channel in self.subscriptions or sid in self.subscriptions.values()):
                raise InvalidData("unexpected probe acknowledgment")
            self.subscriptions[channel] = sid
        elif kind in EVENT_CHANNELS:
            channel = EVENT_CHANNELS[kind]
            sid = integer(event.get("sid"), 1, 2**63-1)
            if self.subscriptions.get(channel) != sid:
                raise InvalidData("unacknowledged probe event")
            # Count deliveries, not unique fills or validated economic updates.
            self.event_counts[kind] += 1
        else:
            raise InvalidData("unexpected probe event type")


async def probe_private_streams(reader_factory, *, rounds=2, observe_seconds=15,
                                ack_seconds=10):
    """Explicit opt-in caller supplies credentials through a reader factory.

    No files, ledger, REST requests, mutation callbacks, automatic retries or
    live authorizations. At most two sequential connections; fail-fast on any
    reader error. Reports omit raw exception text and venue payloads.
    """
    integer(rounds, 1, 2)
    integer(observe_seconds, 1, 30)
    integer(ack_seconds, 1, 15)
    results = []
    for generation in range(1, rounds + 1):
        state = ProbeState()
        ready = asyncio.Event()
        started = time.monotonic()
        acknowledged_at = None

        async def consume(name, event):
            nonlocal acknowledged_at
            state.consume(name, event)
            if state.acknowledged and not ready.is_set():
                acknowledged_at = time.monotonic()
                ready.set()

        reader = asyncio.create_task(reader_factory(PRIVATE_SPEC).run(consume))
        handshake = asyncio.create_task(ready.wait())
        status = "failed"
        try:
            done, _ = await asyncio.wait((reader, handshake), timeout=ack_seconds,
                                         return_when=asyncio.FIRST_COMPLETED)
            if reader in done:
                status = "reader_ended_or_failed"
            elif handshake not in done:
                status = "acknowledgment_timeout"
            else:
                done, _ = await asyncio.wait((reader,), timeout=observe_seconds)
                status = "reader_ended_or_failed" if done else "observed"
        finally:
            reader.cancel()
            handshake.cancel()
            # Structured cancellation joins the reader and closes its socket.
            await asyncio.gather(reader, handshake, return_exceptions=True)
        results.append(dict(generation=generation, status=status,
            acknowledged_channels=sorted(state.subscriptions),
            delivered_events=dict(state.event_counts), messages=state.messages,
            normalized_message_bytes=state.wire_bytes,
            acknowledgment_ms=(round((acknowledged_at-started)*1000, 3)
                                if acknowledged_at is not None else None),
            elapsed_seconds=round(time.monotonic()-started, 3)))
        if status != "observed":
            break
    return dict(rounds=results,
        subscription_access_verified=len(results) == rounds and all(r["status"] == "observed" for r in results),
        resubscription_verified=rounds == 2 and len(results) == 2 and all(r["status"] == "observed" for r in results),
        live_event_delivery_observed=any(sum(r["delivered_events"].values()) for r in results),
        gap_recovery_verified=False, complete_account_proof=False, live_ready=False)
