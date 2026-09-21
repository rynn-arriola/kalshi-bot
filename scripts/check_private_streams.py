"""Manually invoked bounded live read-only probe; no order/execution path."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID

from kalshi_bot.diagnostics import probe_private_streams
from kalshi_bot.runtime import readonly_reader_factory
from kalshi_bot.transport import Signer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only-live-check", action="store_true", required=True)
    parser.add_argument("--key-id-file", type=Path, required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.key_id_file.stat().st_size > 256 or args.private_key_file.stat().st_size > 16384:
            raise ValueError("credential file size")
        key_id = args.key_id_file.read_text(encoding="utf-8-sig").strip()
        UUID(key_id)
        signer = Signer(key_id, args.private_key_file.read_bytes())
        started = datetime.now(timezone.utc).isoformat()
        result = asyncio.run(probe_private_streams(readonly_reader_factory(signer)))
        print(json.dumps(dict(started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(),
                             **result), indent=2))
        return 0 if result["subscription_access_verified"] else 2
    except (Exception, KeyboardInterrupt):
        # No raw exception text, headers, key IDs or message payloads in diagnostics.
        print(json.dumps({"probe_failed": True, "live_ready": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
