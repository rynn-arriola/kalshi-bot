"""Credential-free local inspection. Intentionally no live/start command."""
import argparse
import json
from pathlib import Path

from .config import BotConfig
from .observability import Diagnostics, NO_LOG
from .risk import entry_cap
from .values import InvalidData
from .windows import suggested_data_directory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Kalshi Windows foundation (live execution unavailable)")
    parser.add_argument("command", choices=("preflight", "policy"))
    parser.add_argument("--config", type=Path, default=Path("config/bot.json"))
    parser.add_argument("--log-dir", type=Path, help="opt in to bounded secret-safe JSONL diagnostics")
    args = parser.parse_args(argv)
    diagnostics = NO_LOG
    code = 2
    try:
        if args.log_dir is not None:
            diagnostics = Diagnostics(args.log_dir)
            diagnostics.start()
        result, code = inspect(args, diagnostics)
    except Exception as exc:
        diagnostics.emit('cli_failed', error=exc)
        result = {"error": "cli_failed", "live_ready": False,
                  "hint": "Check config and diagnostic health; exception text is withheld."}
    finally:
        if diagnostics is not NO_LOG:
            diagnostics.close()
    if diagnostics is not NO_LOG:
        result['logging'] = diagnostics.status()
        if result['logging']['failure']:
            code = 2
            result['error'] = 'logging_unavailable'
    print(json.dumps(result, indent=2))
    return code


def inspect(args, diagnostics):
    config = BotConfig.load(args.config)
    if args.command == "policy":
        result = dict(entry_contracts=str(config.entry_contracts), capital_usd=str(config.capital_usd),
                          market_exposure_usd=str(config.market_exposure_usd),
                          exposure_reference_slots=config.managed_market_slots,
                          portfolio_exposure_usd=(str(config.portfolio_exposure_usd)
                                                  if config.portfolio_exposure_usd is not None else None),
                          windows="00-06/06-12/12-18/18-00 America/New_York",
                          realized_loss_entry_caps={str(loss): entry_cap(loss) for loss in (0,5,10,15,20,25)},
                          live_enabled=False)
        return result, 0
    blockers = config.live_blockers()
    try:
        data = str(suggested_data_directory())
    except InvalidData:
        data = None
        blockers.append("native Windows environment unavailable")
    diagnostics.emit('preflight_blocked', blocker_count=len(blockers))
    return dict(live_ready=False, blockers=blockers, proposed_data_directory=data,
                creates_files=args.log_dir is not None, credentials_accessed=False, network_accessed=False), 2
