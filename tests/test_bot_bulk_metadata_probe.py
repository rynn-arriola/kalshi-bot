"""Public bulk metadata instrument tests; no network."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from kalshi_bot.rest import WireResponse

spec = importlib.util.spec_from_file_location('bulk_metadata_probe',
    Path(__file__).resolve().parents[1]/'scripts'/'probe_bulk_metadata.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class BulkTests(unittest.TestCase):
    def test_response_must_exactly_cover_requested_identities(self):
        self.assertEqual(probe.indexed([{'ticker':'A'}],'ticker',{'A'}),{'A':{'ticker':'A'}})
        for rows in ([],[{'ticker':'B'}],[{'ticker':'A'},{'ticker':'A'}]):
            with self.assertRaises(probe.InvalidData):
                probe.indexed(rows,'ticker',{'A'})

    def test_private_and_book_reads_forbidden(self):
        with patch.object(probe,'get_wire') as wire:
            for path in ('portfolio/orders','markets/A/orderbook','markets/orderbooks',
                         '../markets','https://example.com','events/multivariate'):
                with self.assertRaises(probe.InvalidData):
                    probe.PublicMetadata().read(path)
            wire.assert_not_called()

    def test_failed_request_is_latched(self):
        client = probe.PublicMetadata()
        with patch.object(probe,'get_wire',return_value=WireResponse(429,b'')) as wire:
            for _ in range(2):
                with self.assertRaises(probe.InvalidData):
                    client.read('markets',tickers='A')
            self.assertEqual(wire.call_count,1)

    def test_unexhausted_page_is_not_complete(self):
        with patch.object(probe,'get_wire',return_value=WireResponse(200,b'{"cursor":"more"}')):
            with self.assertRaises(probe.InvalidData):
                probe.PublicMetadata().read('markets',tickers='A')


if __name__=='__main__':
    unittest.main()
