"""Narrow one-market live maker canary; not the autonomous production bot."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from .books import Book, Ladder
from .execution import batch_acknowledgement
from .market_inputs import parse_market, rules_digest
from .quoting import Quote, parse_program, program_plans
from .values import InvalidData, decimal, identity, utc


QTY = Decimal("10")
MAX_REST = timedelta(hours=6)


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def plan_digest(plan):
    body = {key: value for key, value in plan.items() if key != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def rest_book(ticker, payload, *, capacity=4096):
    try:
        row = payload["orderbook_fp"]
        yes, no = row["yes_dollars"], row["no_dollars"]
    except (KeyError, TypeError) as exc:
        raise InvalidData("incomplete fixed-point order book") from exc
    if (type(yes) is not list or type(no) is not list
            or len(yes) > capacity or len(no) > capacity):
        raise InvalidData("order book capacity exceeded")
    book = Book(identity(ticker), Ladder(capacity), Ladder(capacity))
    for rows, ladder, complement in ((yes, book.bids, False), (no, book.asks, True)):
        for item in rows:
            if type(item) is not list or len(item) != 2:
                raise InvalidData("invalid fixed-point order-book level")
            value = decimal(item[0])
            ladder.set(Decimal(1)-value if complement else value, item[1])
    if not book.bids.levels or not book.asks.levels:
        raise InvalidData("two-sided order book required")
    if book.bids.best(bid=True) >= book.asks.best(bid=False):
        raise InvalidData("crossed or locked order book")
    book.valid = True
    book.revision = 1
    return book


def candidate(program_row, market_doc, book_payload, now):
    now = utc(now)
    program = parse_program(program_row)
    market = parse_market(market_doc, program.ticker)
    book = rest_book(program.ticker, book_payload)
    plans = program_plans(book, (program,), market.bands, now=now,
                          market_open=market.active)
    quote_plan = plans[0]
    blockers = list(quote_plan.blockers)
    if program.max_reward_centicents is not None:
        blockers.append("account_reward_cap_unsupported")
    if program.end-now < timedelta(seconds=90):
        blockers.append("insufficient_canary_time")
    if market.closes <= now+timedelta(seconds=90):
        blockers.append("market_closes_too_soon")
    if len(market.bands) != 1:
        blockers.append("variable_tick_market")
    if len(quote_plan.quotes) != 2:
        blockers.append("two_sided_quote_unavailable")
    if blockers:
        return None, tuple(dict.fromkeys(blockers))
    bid = next(q for q in quote_plan.quotes if q.side == "bid")
    ask = next(q for q in quote_plan.quotes if q.side == "ask")
    no_bid = Decimal(1)-ask.yes_price
    if (not Decimal("0.05") <= bid.yes_price <= Decimal("0.95")
            or not Decimal("0.05") <= no_bid <= Decimal("0.95")
            or bid.yes_price+no_bid >= Decimal(1)):
        return None, ("canary_price_guard",)
    with localcontext() as ctx:
        ctx.prec = 40
        seconds = Decimal(str((program.end-program.start).total_seconds()))
        planned_end = min(program.end, market.closes, now+MAX_REST)
        remaining = Decimal(str((planned_end-now).total_seconds()))
        pool = Decimal(program.pool_centicents)/10000
        estimated = pool*quote_plan.snapshot_share*remaining/seconds
        collateral = QTY*(bid.yes_price+no_bid)
    expiration = planned_end-timedelta(seconds=15)
    return {
        "program_id": program.program_id,
        "ticker": program.ticker,
        "event_ticker": market.event,
        "exchange_index": market.exchange,
        "rules_digest": rules_digest(market_doc["market"]),
        "program_start": program.start.isoformat(),
        "program_end": program.end.isoformat(),
        "market_close": market.closes.isoformat(),
        "can_close_early": market.early,
        "expiration_time": int(expiration.timestamp()),
        "planned_rest_end": planned_end.isoformat(),
        "bid_price": str(bid.yes_price),
        "ask_price": str(ask.yes_price),
        "no_bid_price": str(no_bid),
        "quantity_each_side": str(QTY),
        "snapshot_share": str(quote_plan.snapshot_share),
        "estimated_remaining_reward_usd": str(estimated),
        "maximum_combined_entry_cost_usd": str(collateral),
        "maximum_one_sided_contract_loss_usd": str(QTY*max(bid.yes_price, no_bid)),
    }, ()


def make_plan(candidate_row, *, balance, now=None):
    now = utc(now or datetime.now(timezone.utc))
    run_id = str(uuid4())
    clients = {"bid": str(uuid4()), "ask": str(uuid4())}
    plan = {
        "schema": 1,
        "run_id": run_id,
        "created_at": now.isoformat(),
        "valid_until": (now+timedelta(seconds=45)).isoformat(),
        "subaccount": 0,
        "starting_balance_usd": str(decimal(balance)),
        "client_order_ids": clients,
        **candidate_row,
    }
    plan["digest"] = plan_digest(plan)
    return plan


def validate_plan(plan, *, now=None):
    now = utc(now or datetime.now(timezone.utc))
    if not isinstance(plan, dict) or plan.get("schema") != 1 or plan.get("digest") != plan_digest(plan):
        raise InvalidData("canary plan integrity check failed")
    UUID(plan["run_id"])
    if utc(datetime.fromisoformat(plan["valid_until"])) <= now:
        raise InvalidData("canary plan expired; prepare a fresh plan")
    if (plan.get("subaccount") != 0 or plan.get("quantity_each_side") != "10"
            or set(plan.get("client_order_ids", {})) != {"bid", "ask"}):
        raise InvalidData("canary plan exceeds fixed scope")
    for value in plan["client_order_ids"].values():
        UUID(value)
    return plan


def order_requests(plan, *, now=None):
    validate_plan(plan, now=now)
    common = dict(ticker=plan["ticker"], count="10",
        time_in_force="good_till_canceled", self_trade_prevention_type="taker_at_cross",
        post_only=True, reduce_only=False, cancel_order_on_pause=True,
        subaccount=0, exchange_index=plan["exchange_index"],
        expiration_time=plan["expiration_time"])
    return (
        dict(common, side="bid", price=plan["bid_price"],
             client_order_id=plan["client_order_ids"]["bid"]),
        dict(common, side="ask", price=plan["ask_price"],
             client_order_id=plan["client_order_ids"]["ask"]),
    )


def validated_batch_result(plan, response):
    return batch_acknowledgement(order_requests(plan), response)
