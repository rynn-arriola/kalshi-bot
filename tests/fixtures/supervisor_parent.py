"""Fixed native S2A parent-death fixture; never imports account/runtime code."""
import argparse
import asyncio
import os
from pathlib import Path

from kalshi_bot.process_supervisor import SupervisorHost, fixture_fingerprints
from kalshi_bot.supervision import SupervisorState
from kalshi_bot.supervisor_control import ControlOwner, ScopeSpec, SupervisorController


async def run(args):
    scope = ScopeSpec(args.environment, args.account_scope,
                      args.approved_user_sid, Path(args.control_root))
    host = SupervisorHost(scope)
    task = asyncio.create_task(host.run())
    await asyncio.wait_for(host.started.wait(), 5)
    owner = ControlOwner(scope)
    controller = SupervisorController(scope, owner)
    state = (await controller.inspect()).state
    build, config = fixture_fingerprints()
    await controller.arm(expected_generation=state.generation,
                         build_fingerprint=build,
                         config_fingerprint=config)
    async with asyncio.timeout(10):
        while (host.controller_state is None
               or host.controller_state.state != SupervisorState.HEALTHY):
            if task.done():
                await task
                raise RuntimeError("fixture supervisor stopped before health")
            await asyncio.sleep(.02)
    print(host.child.process.pid, flush=True)
    os._exit(77)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--account-scope", required=True)
    parser.add_argument("--approved-user-sid", required=True)
    parser.add_argument("--control-root", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
