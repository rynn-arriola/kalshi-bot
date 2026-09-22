"""Prepare or run one bounded live liquidity canary on native Windows."""
import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from uuid import UUID

from kalshi_bot.live_canary import (atomic_json, candidate, make_plan, order_requests,
                                    validate_plan, validated_batch_result)
from kalshi_bot.mutation_outcomes import MutationHTTPFailure
from kalshi_bot.mutation_transport import (MutationActivation, OrderMutationTransport,
                                           batch_scope)
from kalshi_bot.rest import RestReads, TokenBudget
from kalshi_bot.transport import MutationSigner, Signer
from kalshi_bot.values import InvalidData


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "data" / "live-canary"


def credentials(key_id_path, private_key_path):
    if key_id_path.stat().st_size > 256 or private_key_path.stat().st_size > 16384:
        raise InvalidData("credential file size invalid")
    key_id = key_id_path.read_text(encoding="utf-8-sig").strip()
    UUID(key_id)
    private = private_key_path.read_bytes()
    return Signer(key_id, private), MutationSigner(key_id, private)


def new_reads(signer):
    # Exactly enough initial credit to read the current account limits/costs pair.
    return RestReads(TokenBudget(rate=1, capacity=20, default_cost=10,
                                 initial_tokens=20), signer, concurrency=2)


async def account_snapshot(reads):
    balance, orders, positions = await asyncio.gather(
        reads.read("balance", reason="cash", subaccount=0),
        reads.collect("orders", reason="bootstrap", status="resting", subaccount=0,
                      max_pages=5, max_rows=100),
        reads.collect("positions", reason="bootstrap", count_filter="position", subaccount=0,
                      max_pages=5, max_rows=100))
    active_positions = tuple(row for row in positions.rows
        if Decimal(str(row.get("position_fp", row.get("position", "0")))) != 0)
    return {
        "balance": balance.payload["balance_dollars"],
        "resting_orders": orders.rows,
        "positions": active_positions,
    }


async def select_candidate(reads, now):
    programs = await reads.collect("incentives", reason="incentives",
        status="active", type="liquidity", max_pages=60, max_rows=10000)
    short = []
    for row in programs.rows:
        try:
            start = datetime.fromisoformat(row["start_date"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(row["end_date"].replace("Z", "+00:00"))
            duration = (end-start).total_seconds()
            remaining = (end-now).total_seconds()
            if start <= now < end and 90 < remaining and duration <= 86400:
                rate = Decimal(row["period_reward"])/Decimal(str(duration))
                short.append((rate, row))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    short.sort(key=lambda item: (-item[0], item[1].get("market_ticker", "")))
    results = []
    for _, row in short[:128]:
        ticker = row["market_ticker"]
        try:
            market, book = await asyncio.gather(
                reads.read("market", reason="metadata", ticker=ticker),
                reads.read("book", reason="canary", ticker=ticker, depth=100))
            item, blockers = candidate(row, market.payload, book.payload, now)
            if item is not None:
                item["title"] = market.payload["market"]["title"]
                results.append(item)
        except (InvalidData, KeyError, TypeError):
            continue
    if not results:
        raise InvalidData("no supported short-duration live canary market")
    eligible = [row for row in results
                if Decimal(row["estimated_remaining_reward_usd"]) >= 1]
    if not eligible:
        raise InvalidData("no short-duration canary currently estimates the $1 minimum")
    return max(eligible, key=lambda row: (
        Decimal(row["estimated_remaining_reward_usd"])
        / Decimal(row["maximum_combined_entry_cost_usd"]),
        Decimal(row["estimated_remaining_reward_usd"])))


async def prepare(reads):
    await reads.refresh_budget()
    account = await account_snapshot(reads)
    if account["resting_orders"] or account["positions"]:
        raise InvalidData("canary requires a flat account with no resting orders")
    now = datetime.now(timezone.utc)
    selected = await select_candidate(reads, now)
    if Decimal(account["balance"]) < Decimal(selected["maximum_combined_entry_cost_usd"]):
        raise InvalidData("available balance is below canary collateral")
    plan = make_plan(selected, balance=account["balance"], now=now)
    path = RUNS / plan["run_id"] / "plan.json"
    atomic_json(path, plan)
    return path, plan


def public_plan(plan, path):
    return {
        "state": "PREPARED_NOT_SUBMITTED",
        "plan_path": str(path),
        "run_id": plan["run_id"],
        "ticker": plan["ticker"],
        "title": plan["title"],
        "bid_yes": plan["bid_price"],
        "bid_no": plan["no_bid_price"],
        "contracts_each_side": plan["quantity_each_side"],
        "maximum_combined_entry_cost_usd": plan["maximum_combined_entry_cost_usd"],
        "maximum_one_sided_contract_loss_usd": plan["maximum_one_sided_contract_loss_usd"],
        "estimated_remaining_reward_usd": plan["estimated_remaining_reward_usd"],
        "program_end": plan["program_end"],
        "market_close": plan["market_close"],
        "can_close_early": plan["can_close_early"],
        "valid_until": plan["valid_until"],
        "orders_submitted": False,
    }


async def current_program(reads, plan):
    programs = await reads.collect("incentives", reason="incentives",
        status="active", type="liquidity", max_pages=60, max_rows=10000)
    rows = [row for row in programs.rows if row.get("id") == plan["program_id"]]
    if len(rows) != 1:
        raise InvalidData("planned incentive is no longer uniquely active")
    return rows[0]


async def revalidate(reads, plan):
    account = await account_snapshot(reads)
    if account["resting_orders"] or account["positions"]:
        raise InvalidData("account changed after preparation")
    row = await current_program(reads, plan)
    market, book = await asyncio.gather(
        reads.read("market", reason="metadata", ticker=plan["ticker"]),
        reads.read("book", reason="canary", ticker=plan["ticker"], depth=100))
    current, blockers = candidate(row, market.payload, book.payload, datetime.now(timezone.utc))
    if current is None or blockers:
        raise InvalidData("planned market no longer passes canary checks")
    exact = ("ticker", "program_id", "exchange_index", "rules_digest",
             "bid_price", "ask_price", "quantity_each_side")
    if any(current[key] != plan[key] for key in exact):
        raise InvalidData("planned quote changed; prepare a fresh canary")
    return account


def owned_rows(rows, clients, order_ids=()):
    clients, order_ids = set(clients), set(order_ids)
    return tuple(row for row in rows if row.get("client_order_id") in clients
                 or row.get("order_id") in order_ids)


async def cancel_known(transport, plan, order_ids):
    results = []
    for order_id in order_ids:
        request = {"order_id": order_id, "subaccount": 0,
                   "exchange_index": plan["exchange_index"],
                   "market_ticker": plan["ticker"]}
        try:
            reply = await transport("cancel", request)
            results.append({"order_id": order_id, "state": "cancel_ack",
                            "reduced_by": reply.get("reduced_by")})
        except MutationHTTPFailure as exc:
            results.append({"order_id": order_id, "state": "cancel_http_failure",
                            "http_status": exc.status})
        except Exception:
            results.append({"order_id": order_id, "state": "cancel_unknown"})
    return results


async def run_plan(reads, mutation_signer, plan, path):
    raise InvalidData('separate canary retired; use the original liquidity runtime')
    validate_plan(plan)
    await reads.refresh_budget()
    await revalidate(reads, plan)
    requests = order_requests(plan)
    activation = MutationActivation(plan["run_id"], plan["ticker"], 0,
        plan["exchange_index"], frozenset(plan["client_order_ids"].values()),
        batch_scope(requests))
    transport = OrderMutationTransport(mutation_signer, activation=activation)
    run_dir = path.parent
    status_path = run_dir / "status.json"
    atomic_json(status_path, {"state": "SENDING", "run_id": plan["run_id"],
        "ticker": plan["ticker"], "last_update": datetime.now(timezone.utc).isoformat(),
        "blockers": []})
    try:
        response = await transport.batch(requests)
    except BaseException:
        # Never retry an uncertain create. A later explicit reconciliation owns it;
        # the server-side expiration remains the ultimate bounded stop.
        atomic_json(status_path, {"state": "BLOCKED", "run_id": plan["run_id"],
            "ticker": plan["ticker"], "last_update": datetime.now(timezone.utc).isoformat(),
            "blockers": ["batch_submission_outcome_unknown"],
            "server_expiration_time": plan["expiration_time"]})
        raise
    outcomes = validated_batch_result(plan, response)
    atomic_json(run_dir / "submission.json", {"submitted_at": datetime.now(timezone.utc).isoformat(),
        "outcomes": outcomes})
    order_ids = tuple(row["order_id"] for row in outcomes if row["state"] == "ack")
    if len(order_ids) != 2:
        cancels = await cancel_known(transport, plan, order_ids)
        state = {"state": "BLOCKED", "run_id": plan["run_id"],
            "ticker": plan["ticker"], "order_ids": order_ids,
            "last_update": datetime.now(timezone.utc).isoformat(),
            "cancellations": cancels,
            "blockers": ["partial_batch_requires_reconciliation"]}
        atomic_json(status_path, state)
        return state
    state = {"state": "MONITORING", "run_id": plan["run_id"], "ticker": plan["ticker"],
             "order_ids": order_ids, "last_update": datetime.now(timezone.utc).isoformat(),
             "filled_rows": 0, "resting_rows": len(order_ids), "blockers": []}
    atomic_json(status_path, state)
    expiration = datetime.fromtimestamp(plan["expiration_time"], timezone.utc)
    cancel_reason = "planned_expiration"
    try:
        while datetime.now(timezone.utc) < expiration:
            orders, fills = await asyncio.gather(
                reads.collect("orders", reason="reconcile", ticker=plan["ticker"], subaccount=0,
                              max_pages=5, max_rows=100),
                reads.collect("fills", reason="gap", ticker=plan["ticker"], subaccount=0,
                              max_pages=5, max_rows=100))
            owned_orders = owned_rows(orders.rows, plan["client_order_ids"].values(), order_ids)
            owned_fills = owned_rows(fills.rows, plan["client_order_ids"].values(), order_ids)
            state.update(last_update=datetime.now(timezone.utc).isoformat(),
                         filled_rows=len(owned_fills),
                         resting_rows=sum(row.get("status") == "resting" for row in owned_orders))
            atomic_json(status_path, state)
            if owned_fills:
                cancel_reason = "fill_observed"
                break
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        cancel_reason = "interrupted"
        raise
    finally:
        cancels = await asyncio.shield(cancel_known(transport, plan, order_ids))
        state.update(state="RECONCILING", cancel_reason=cancel_reason, cancellations=cancels,
                     last_update=datetime.now(timezone.utc).isoformat())
        atomic_json(status_path, state)
    orders, fills, positions, balance = await asyncio.gather(
        reads.collect("orders", reason="reconcile", ticker=plan["ticker"], subaccount=0,
                      max_pages=5, max_rows=100),
        reads.collect("fills", reason="gap", ticker=plan["ticker"], subaccount=0,
                      max_pages=5, max_rows=100),
        reads.collect("positions", reason="reconcile", ticker=plan["ticker"], subaccount=0,
                      max_pages=5, max_rows=100),
        reads.read("balance", reason="cash", subaccount=0))
    owned_orders = owned_rows(orders.rows, plan["client_order_ids"].values(), order_ids)
    owned_fills = owned_rows(fills.rows, plan["client_order_ids"].values(), order_ids)
    resting = tuple(row for row in owned_orders if row.get("status") == "resting")
    blockers = []
    if resting:
        blockers.append("resting_order_remains")
    if positions.rows:
        blockers.append("open_position_awaiting_settlement")
    state.update(state="PARTIALLY_COMPLETE" if blockers else "OBSERVATION_COMPLETE",
        last_update=datetime.now(timezone.utc).isoformat(), resting_rows=len(resting),
        filled_rows=len(owned_fills), position_rows=len(positions.rows),
        ending_balance_usd=balance.payload.get("balance_dollars"), blockers=blockers)
    atomic_json(status_path, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "status"))
    parser.add_argument("--key-id-file", type=Path)
    parser.add_argument("--private-key-file", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--confirm-run-id")
    args = parser.parse_args(argv)
    if args.command == "status":
        if args.plan is None:
            parser.error("status requires --plan")
        status = args.plan.parent / "status.json"
        print(status.read_text(encoding="utf-8") if status.exists() else json.dumps({"state":"NOT_STARTED"}))
        return 0
    if args.key_id_file is None or args.private_key_file is None:
        parser.error("prepare/run require credential file paths")
    async def action(read_signer, mutation_signer):
        reads = new_reads(read_signer)
        try:
            if args.command == "prepare":
                path, plan = await prepare(reads)
                return 0, public_plan(plan, path)
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            validate_plan(plan)
            if args.confirm_run_id != plan["run_id"]:
                raise InvalidData("confirmation does not match the exact prepared run")
            result = await run_plan(reads, mutation_signer, plan, args.plan)
            return (0 if result["state"] == "OBSERVATION_COMPLETE" else 2), result
        finally:
            await reads.close()

    try:
        read_signer, mutation_signer = credentials(args.key_id_file, args.private_key_file)
        if args.plan is None or args.confirm_run_id is None:
            if args.command == "run":
                parser.error("run requires --plan and --confirm-run-id")
        code, result = asyncio.run(action(read_signer, mutation_signer))
        print(json.dumps(result, indent=2))
        return code
    except KeyboardInterrupt:
        print(json.dumps({"state":"INTERRUPTED", "live_ready":False}))
        return 130
    except Exception:
        print(json.dumps({"state":"FAILED", "live_ready":False,
                          "hint":"Inspect the run status; raw exception text is withheld."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
