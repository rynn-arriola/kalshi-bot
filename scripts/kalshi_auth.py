"""Signed read-only access to the Kalshi private API.

There is deliberately no order function in this module. It can read the
portfolio and the account, and it has no code path to POST an order.

Kalshi signs `timestamp + METHOD + path` with RSA-PSS/SHA-256. Two details
are easy to get wrong and both fail with the same opaque
`token_authentication_failure`:

  * the signed path EXCLUDES the query string, but INCLUDES the `/trade-api/v2`
    prefix -- so `/trade-api/v2/portfolio/orders`, not `/portfolio/orders` and
    not `...orders?limit=10`;
  * the timestamp is milliseconds since epoch, as a string, and the same value
    must appear in the header and in the signed payload.

Salt length is the digest length (PSS "max length" in some libraries maps to a
different value; Kalshi expects DIGEST_LENGTH).
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


DEFAULT_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiAuthError(RuntimeError):
    """Credentials are missing, malformed, or rejected."""


def load_env(path: Path) -> dict[str, str]:
    """Read a KEY=VALUE file. Values are never logged."""

    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


class KalshiReadOnlyClient:
    def __init__(self, key_id: str, private_key_pem: bytes, base: str = DEFAULT_BASE):
        if not key_id:
            raise KalshiAuthError("KALSHI_API_KEY_ID is empty")
        self.key_id = key_id
        self.base = base.rstrip("/")
        # The path prefix that must be signed, derived from the base URL rather
        # than hardcoded, so demo and production both work.
        self.path_prefix = urllib.parse.urlparse(self.base).path or ""
        try:
            self._key = serialization.load_pem_private_key(
                private_key_pem, password=None)
        except Exception as exc:
            raise KalshiAuthError(f"private key could not be loaded: {exc}") from exc

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "KalshiReadOnlyClient":
        """Environment variables win; the .env file is the fallback."""

        env_path = env_path or Path(__file__).resolve().parent.parent / ".env"
        file_values = load_env(env_path)
        key_id = os.environ.get("KALSHI_API_KEY_ID") or file_values.get(
            "KALSHI_API_KEY_ID", "")
        key_file = os.environ.get("KALSHI_PRIVATE_KEY_FILE") or file_values.get(
            "KALSHI_PRIVATE_KEY_FILE", "")
        base = os.environ.get("KALSHI_API_BASE") or file_values.get(
            "KALSHI_API_BASE", DEFAULT_BASE)
        if not key_file:
            raise KalshiAuthError("KALSHI_PRIVATE_KEY_FILE is not set")
        resolved = Path(key_file)
        if not resolved.exists():
            raise KalshiAuthError(f"private key file not found: {resolved}")
        return cls(key_id, resolved.read_bytes(), base)

    def _sign(self, method: str, path: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method}{path}".encode("utf-8")
        signature = self._key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=hashes.SHA256.digest_size),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Accept": "application/json",
        }

    def get(self, route: str, timeout: float = 30.0) -> tuple[int, object]:
        """GET a private route. `route` starts with '/', query string allowed.

        Returns (status, parsed) and does not raise on an HTTP error status, so
        a probe can report every route's outcome rather than stopping at the
        first refusal.
        """

        route_path, _, query = route.partition("?")
        signed_path = f"{self.path_prefix}{route_path}"
        url = f"{self.base}{route_path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers=self._sign("GET", signed_path))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, body[:400]
