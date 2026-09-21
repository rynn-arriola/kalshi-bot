from __future__ import annotations

import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from record_books import NETWORK_ERROR_STATUS, get_json  # noqa: E402


class FakeLimiter:
    def __init__(self) -> None:
        self.calls = 0

    def wait(self) -> None:
        self.calls += 1


class GetJsonTests(unittest.TestCase):
    @patch("record_books.time.sleep")
    @patch("record_books.urllib.request.urlopen")
    def test_transient_tls_failure_retries_then_succeeds(
            self, urlopen: MagicMock, sleep: MagicMock) -> None:
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"ok": true}'
        response.__enter__.return_value = response
        urlopen.side_effect = [
            urllib.error.URLError("temporary TLS EOF"), response]
        limiter = FakeLimiter()

        with patch("builtins.print"):
            status, payload = get_json(
                limiter, "https://example.invalid/public", attempts=3)

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(limiter.calls, 2)
        sleep.assert_called_once_with(1)

    @patch("record_books.time.sleep")
    @patch("record_books.urllib.request.urlopen")
    def test_exhausted_network_failures_return_recordable_status(
            self, urlopen: MagicMock, sleep: MagicMock) -> None:
        urlopen.side_effect = urllib.error.URLError("temporary TLS EOF")
        limiter = FakeLimiter()

        with patch("builtins.print"):
            status, payload = get_json(
                limiter, "https://example.invalid/public", attempts=3)

        self.assertEqual(status, NETWORK_ERROR_STATUS)
        self.assertIsNone(payload)
        self.assertEqual(limiter.calls, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
