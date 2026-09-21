import asyncio
import json
import unittest

from kalshi_bot.diagnostics import PRIVATE_SPEC, ProbeState, probe_private_streams
from kalshi_bot.runtime import readonly_reader_factory
from kalshi_bot.values import InvalidData


def acknowledgments():
    return [{"id": 1, "type": "subscribed", "msg": {"channel": c, "sid": i}}
            for i, c in enumerate(PRIVATE_SPEC.channels, 1)]


class ProbeStateTests(unittest.TestCase):
    def ready(self):
        state = ProbeState()
        for message in acknowledgments():
            state.consume("account", message)
        return state

    def test_all_channels_required(self):
        state = ProbeState()
        for message in acknowledgments()[:-1]: state.consume("account", message)
        self.assertFalse(state.acknowledged)
        state.consume("account", acknowledgments()[-1])
        self.assertTrue(state.acknowledged)

    def test_duplicate_channel_rejected(self):
        with self.assertRaises(InvalidData): self.ready().consume("account", acknowledgments()[0])

    def test_duplicate_sid_rejected(self):
        state = ProbeState()
        state.consume("account", acknowledgments()[0])
        message = acknowledgments()[1]; message["msg"]["sid"] = 1
        with self.assertRaises(InvalidData): state.consume("account", message)

    def test_wrong_command_ids_rejected(self):
        for value in (True, None, 2, "1"):
            with self.subTest(value=value):
                message = acknowledgments()[0]; message["id"] = value
                with self.assertRaises(InvalidData): ProbeState().consume("account", message)

    def test_unexpected_channel_rejected(self):
        message = acknowledgments()[0]; message["msg"]["channel"] = "trade"
        with self.assertRaises(InvalidData): ProbeState().consume("account", message)

    def test_wrong_source_rejected(self):
        with self.assertRaises(InvalidData): ProbeState().consume("book-0", acknowledgments()[0])

    def test_event_requires_channel_ack_and_matching_sid(self):
        event = {"type": "fill", "sid": 2, "msg": {}}
        with self.assertRaises(InvalidData): ProbeState().consume("account", event)
        event["sid"] = 1
        with self.assertRaises(InvalidData): self.ready().consume("account", event)

    def test_deliveries_count_without_retaining_account_payload(self):
        state = self.ready()
        state.consume("account", {"type": "fill", "sid": 2, "msg": {"private": "secret-sentinel"}})
        self.assertEqual(state.event_counts["fill"], 1)
        self.assertNotIn("secret-sentinel", repr(state))

    def test_documented_order_group_type(self):
        state = self.ready()
        state.consume("account", {"type": "order_group_updates", "sid": 4, "msg": {}})
        self.assertEqual(state.event_counts["order_group_updates"], 1)

    def test_errors_and_malformed_messages_rejected(self):
        for message in ([], {}, {"type":"error","msg":{"code":10}},
                        {"type":"fill","sid":2,"msg":None}):
            with self.subTest(message=message):
                with self.assertRaises(InvalidData): ProbeState().consume("account", message)

    def test_message_budget_enforced(self):
        state=ProbeState(max_messages=1)
        state.consume("account", acknowledgments()[0])
        with self.assertRaises(InvalidData): state.consume("account", acknowledgments()[1])

    def test_byte_budget_enforced(self):
        with self.assertRaises(InvalidData): ProbeState(max_bytes=1).consume("account", acknowledgments()[0])


class FakeReader:
    def __init__(self, messages=None, fail=False):
        self.messages = acknowledgments() if messages is None else messages
        self.fail = fail
        self.closed = False

    async def run(self, consume):
        try:
            for message in self.messages: await consume("account", message)
            if self.fail: raise ValueError("never-print-this-secret")
            await asyncio.Event().wait()
        finally:
            self.closed = True


class ProbeAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_fresh_readers_closed_and_no_false_recovery_claim(self):
        readers=[]
        def factory(spec):
            self.assertEqual(spec, PRIVATE_SPEC)
            readers.append(FakeReader())
            return readers[-1]
        result=await probe_private_streams(factory, observe_seconds=1, ack_seconds=1)
        self.assertTrue(result["subscription_access_verified"])
        self.assertTrue(result["resubscription_verified"])
        self.assertEqual(len(readers), 2)
        self.assertTrue(all(r.closed for r in readers))
        for k in ("live_event_delivery_observed", "gap_recovery_verified", "complete_account_proof", "live_ready"):
            self.assertFalse(result[k])

    async def test_failed_reader_stops_without_retry_or_secret_output(self):
        readers=[]
        def factory(_):
            readers.append(FakeReader(fail=True)); return readers[-1]
        result=await probe_private_streams(factory, observe_seconds=1)
        self.assertFalse(result["subscription_access_verified"])
        self.assertEqual(len(readers), 1)
        self.assertTrue(readers[0].closed)
        self.assertNotIn("never-print-this-secret", json.dumps(result))

    async def test_timeout_closes_reader(self):
        reader=FakeReader(messages=[])
        result=await probe_private_streams(lambda _:reader, observe_seconds=1, ack_seconds=1)
        self.assertEqual(result["rounds"][0]["status"], "acknowledgment_timeout")
        self.assertFalse(result["resubscription_verified"])
        self.assertTrue(reader.closed)

    async def test_delivery_not_labeled_gap_recovery(self):
        reader=FakeReader(acknowledgments()+[{"type":"fill","sid":2,"msg":{}}])
        result=await probe_private_streams(lambda _:reader, rounds=1, observe_seconds=1)
        self.assertTrue(result["live_event_delivery_observed"])
        self.assertFalse(result["gap_recovery_verified"])

    async def test_cancel_joins_reader(self):
        reader=FakeReader()
        task=asyncio.create_task(probe_private_streams(lambda _:reader))
        for _ in range(5): await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(reader.closed)

    async def test_invalid_bounds_do_not_construct_reader(self):
        def factory(_): self.fail("must validate before constructing")
        for kwargs in ({"rounds":3}, {"rounds":True}, {"observe_seconds":0}, {"ack_seconds":16}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(InvalidData): await probe_private_streams(factory, **kwargs)

    async def test_real_reader_only_sends_subscription_and_closes(self):
        class Socket:
            sent=[]
            closed=False
            messages=[json.dumps(m) for m in acknowledgments()]
            async def __aenter__(self): return self
            async def __aexit__(self,*args): self.closed=True
            async def send(self, raw): self.sent.append(json.loads(raw))
            def __aiter__(self): return self
            async def __anext__(self):
                if self.messages: return self.messages.pop(0)
                await asyncio.Event().wait()
        class Signer:
            def headers(self,method,path):
                self_outer.assertEqual((method,path),("GET","/trade-api/ws/v2"))
                return {}
        self_outer=self
        socket=Socket()
        def connector(url,**kwargs):
            self.assertEqual(url,"wss://external-api-ws.kalshi.com/trade-api/ws/v2")
            self.assertIsNone(kwargs["proxy"])
            return socket
        result=await probe_private_streams(readonly_reader_factory(Signer(),connector=connector),
                                           rounds=1, observe_seconds=1)
        self.assertTrue(result["subscription_access_verified"])
        self.assertEqual(socket.sent,[PRIVATE_SPEC.command()])
        self.assertTrue(socket.closed)


if __name__ == "__main__": unittest.main()
