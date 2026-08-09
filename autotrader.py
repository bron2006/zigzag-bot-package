# autotrader.py
"""Part 3: optional automated order placement on top of the existing signal
pipeline, using the SAME cTrader client (SpotwareConnect / ctrader_open_api)
already used elsewhere in this project for quotes and trendbars. No new
broker SDK is introduced here.

Safety model (see config.py):
  - AUTOTRADE_ENABLED=false by default. maybe_enter_trade() returns
    immediately, at near-zero cost, whenever this is off — the rest of the
    bot (signals, Web App, Telegram) is completely unaffected.
  - AUTOTRADE_ACCOUNT_MODE (demo|live) has NO runtime toggle anywhere in this
    codebase — changing it requires editing the Fly.io env var and
    redeploying, by design.
  - /autotrade_on can only ever resume trading if AUTOTRADE_ENABLED=true in
    the environment; it can never override that env flag upward.
  - MAX_RISK_PERCENT_PER_TRADE sizes every position from account balance and
    the ATR-derived stop-loss distance (never a fixed lot size).
  - MAX_OPEN_POSITIONS caps concurrent open trades.
  - MAX_DAILY_LOSS_PERCENT is a kill switch: once the day's realized loss
    exceeds it, trading stops and stays stopped (even across restarts of
    _runtime_enabled) until an admin explicitly runs /autotrade_on again.
"""
import logging

from twisted.internet import defer, reactor
from twisted.internet.threads import blockingCallFromThread, deferToThreadPool

import ctrader
import db
from config import (
    AUTOTRADE_ACCOUNT_MODE,
    AUTOTRADE_BALANCE_CACHE_SECONDS,
    AUTOTRADE_ENABLED,
    MAX_DAILY_LOSS_PERCENT,
    MAX_OPEN_POSITIONS,
    MAX_RISK_PERCENT_PER_TRADE,
    SIGNAL_SL_ATR_MULTIPLIER,
    SIGNAL_TP_ATR_MULTIPLIER,
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAErrorRes,
    ProtoOAExecutionEvent,
    ProtoOANewOrderReq,
    ProtoOAOrderErrorEvent,
    ProtoOATraderReq,
    ProtoOATraderRes,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAExecutionType,
    ProtoOAOrderType,
    ProtoOAPayloadType,
    ProtoOATradeSide,
)
from state import app_state

logger = logging.getLogger("autotrader")

_runtime_enabled = bool(AUTOTRADE_ENABLED)
_kill_switch_tripped = False

_balance_cache: dict = {"value": None, "ts": 0.0}


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


# ----------------------------------------------------------------------
# Status / admin controls
# ----------------------------------------------------------------------


def is_active() -> bool:
    return bool(AUTOTRADE_ENABLED) and _runtime_enabled and not _kill_switch_tripped


def enable() -> tuple[bool, str]:
    global _runtime_enabled, _kill_switch_tripped

    if not AUTOTRADE_ENABLED:
        return False, "AUTOTRADE_ENABLED=false у конфігурації — зміни змінну середовища на Fly.io і передеплой."

    _runtime_enabled = True
    was_tripped = _kill_switch_tripped
    _kill_switch_tripped = False
    return True, "Автотрейдинг увімкнено." + (" Kill switch скинуто." if was_tripped else "")


def disable() -> tuple[bool, str]:
    global _runtime_enabled
    _runtime_enabled = False
    return True, "Автотрейдинг вимкнено."


def get_status() -> dict:
    import time as _time

    return {
        "config_enabled": bool(AUTOTRADE_ENABLED),
        "runtime_enabled": _runtime_enabled,
        "active": is_active(),
        "account_mode": AUTOTRADE_ACCOUNT_MODE,
        "kill_switch_tripped": _kill_switch_tripped,
        "max_risk_percent_per_trade": MAX_RISK_PERCENT_PER_TRADE,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "max_daily_loss_percent": MAX_DAILY_LOSS_PERCENT,
        "open_positions": db.count_open_auto_trades(AUTOTRADE_ACCOUNT_MODE),
        "daily_pnl": db.get_daily_auto_trade_pnl(AUTOTRADE_ACCOUNT_MODE),
        "cached_balance": _balance_cache.get("value"),
        "cached_balance_age_seconds": (
            round(_time.time() - _balance_cache["ts"]) if _balance_cache.get("ts") else None
        ),
    }


def _notify_admin_async(text: str) -> None:
    def _send():
        try:
            from notifier import notify_admin

            notify_admin(text, parse_mode="HTML")
        except Exception:
            logger.exception("Autotrader: failed to notify admin")

    deferToThreadPool(reactor, _blocking_pool(), _send)


def _trip_kill_switch(daily_pnl: float, max_daily_loss: float) -> None:
    global _kill_switch_tripped

    if _kill_switch_tripped:
        return

    _kill_switch_tripped = True
    logger.critical(
        "AUTOTRADE KILL SWITCH: daily pnl %.2f breached limit -%.2f (%.2f%% of balance)",
        daily_pnl,
        max_daily_loss,
        MAX_DAILY_LOSS_PERCENT,
    )
    _notify_admin_async(
        "🛑 <b>AUTOTRADE KILL SWITCH</b>\n"
        f"Денний PnL: {daily_pnl:.2f}\n"
        f"Ліміт: -{max_daily_loss:.2f} ({MAX_DAILY_LOSS_PERCENT}% балансу)\n"
        "Автотрейдинг ЗУПИНЕНО і не відновиться сам.\n"
        "Перевір рахунок вручну, тоді /autotrade_on, щоб відновити."
    )


# ----------------------------------------------------------------------
# Account balance (cached; fetched via the shared cTrader client)
# ----------------------------------------------------------------------


@defer.inlineCallbacks
def _fetch_balance_in_reactor():
    client = app_state.client
    account_id = getattr(getattr(client, "_client", None), "account_id", None)
    if not client or not account_id:
        return None

    req = ProtoOATraderReq(ctidTraderAccountId=account_id)
    msg = yield client.send(req, responseTimeoutInSeconds=15)

    res = ProtoOATraderRes()
    res.ParseFromString(msg.payload)
    money_digits = res.trader.moneyDigits or 2
    return res.trader.balance / (10 ** money_digits)


def _get_account_balance() -> float | None:
    import time as _time

    now = _time.time()
    cached = _balance_cache.get("value")
    if cached is not None and (now - _balance_cache.get("ts", 0)) < AUTOTRADE_BALANCE_CACHE_SECONDS:
        return cached

    try:
        balance = blockingCallFromThread(reactor, _fetch_balance_in_reactor)
    except Exception:
        logger.exception("Autotrader: failed to fetch account balance")
        return cached  # stale cache is better than nothing here

    if balance is not None:
        _balance_cache["value"] = balance
        _balance_cache["ts"] = now
    return balance


# ----------------------------------------------------------------------
# Position sizing
# ----------------------------------------------------------------------


def _compute_tp_sl(verdict: str, entry_price: float, atr: float) -> tuple[float, float] | None:
    """Sizes TP/SL for a real cTrader order from ATR. Deliberately
    self-contained (not shared with signal_tracking.py, which tracks
    horizon-based binary-option-style outcomes and has no notion of
    TP/SL) — this executor and the signal layer stay decoupled."""
    if not isinstance(entry_price, (int, float)) or not isinstance(atr, (int, float)):
        return None
    if entry_price <= 0 or atr <= 0:
        return None

    tp_distance = atr * SIGNAL_TP_ATR_MULTIPLIER
    sl_distance = atr * SIGNAL_SL_ATR_MULTIPLIER

    if verdict == "BUY":
        return entry_price + tp_distance, entry_price - sl_distance
    if verdict == "SELL":
        return entry_price - tp_distance, entry_price + sl_distance
    return None


def _normalize_volume(pair: str, raw_units: float) -> int | None:
    symbol = ctrader._resolve_broker_symbol(pair)
    if symbol is None or raw_units <= 0:
        return None

    min_volume = getattr(symbol, "minVolume", 0) or 1000
    max_volume = getattr(symbol, "maxVolume", 0) or None
    step_volume = getattr(symbol, "stepVolume", 0) or min_volume or 1

    # cTrader volume field is units * 100 (e.g. 1 standard FX lot = 100,000
    # units -> volume=10,000,000).
    volume = int(raw_units * 100)
    volume = (volume // step_volume) * step_volume

    if volume < min_volume:
        return None
    if max_volume and volume > max_volume:
        volume = (max_volume // step_volume) * step_volume

    return volume if volume > 0 else None


def _prepare_and_check_risk(pair: str, verdict: str, entry_price: float, atr: float) -> dict | None:
    """Runs on a worker thread: blocking DB reads + balance fetch, all risk
    checks, and (if everything passes) the initial 'submitted' AutoTrade
    row. Returns None if the trade should not be placed."""
    balance = _get_account_balance()
    if not isinstance(balance, (int, float)) or balance <= 0:
        logger.warning("Autotrader: no account balance available, skipping %s", pair)
        return None

    daily_pnl = db.get_daily_auto_trade_pnl(AUTOTRADE_ACCOUNT_MODE)
    max_daily_loss = balance * (MAX_DAILY_LOSS_PERCENT / 100.0)
    if daily_pnl <= -max_daily_loss:
        _trip_kill_switch(daily_pnl, max_daily_loss)
        return None

    open_count = db.count_open_auto_trades(AUTOTRADE_ACCOUNT_MODE)
    if open_count >= MAX_OPEN_POSITIONS:
        logger.info("Autotrader: MAX_OPEN_POSITIONS (%s) reached, skipping %s", MAX_OPEN_POSITIONS, pair)
        return None

    levels = _compute_tp_sl(verdict, entry_price, atr)
    if levels is None:
        return None
    tp_price, sl_price = levels

    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return None

    risk_amount = balance * (MAX_RISK_PERCENT_PER_TRADE / 100.0)
    raw_units = risk_amount / sl_distance

    volume = _normalize_volume(pair, raw_units)
    if not volume:
        logger.info("Autotrader: computed volume invalid for %s (raw_units=%.4f)", pair, raw_units)
        return None

    trade_id = db.create_auto_trade(
        pair=pair,
        direction=verdict,
        volume=volume,
        sl_price=sl_price,
        tp_price=tp_price,
        account_mode=AUTOTRADE_ACCOUNT_MODE,
    )
    if not trade_id:
        return None

    return {
        "trade_id": trade_id,
        "pair": pair,
        "verdict": verdict,
        "volume": volume,
        "sl_price": sl_price,
        "tp_price": tp_price,
    }


# ----------------------------------------------------------------------
# Order submission (must run on the reactor thread — the cTrader client is
# not thread-safe)
# ----------------------------------------------------------------------


def _submit_order_on_reactor_thread(prepared: dict | None):
    if not prepared:
        return

    trade_id = prepared["trade_id"]
    pair = prepared["pair"]

    client = app_state.client
    account_id = getattr(getattr(client, "_client", None), "account_id", None)
    symbol = ctrader._resolve_broker_symbol(pair)

    if not client or not account_id or symbol is None:
        logger.warning("Autotrader: client/account/symbol not ready, aborting order for %s", pair)
        deferToThreadPool(reactor, _blocking_pool(), db.mark_auto_trade_error, trade_id, "client_or_symbol_not_ready")
        return

    side = ProtoOATradeSide.BUY if prepared["verdict"] == "BUY" else ProtoOATradeSide.SELL

    req = ProtoOANewOrderReq(
        ctidTraderAccountId=account_id,
        symbolId=symbol.symbolId,
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=side,
        volume=prepared["volume"],
        stopLoss=prepared["sl_price"],
        takeProfit=prepared["tp_price"],
        label=f"zigzag-autotrade-{trade_id}",
    )

    logger.info(
        "AUTOTRADE: submitting order #%s %s %s volume=%s sl=%.5f tp=%.5f (mode=%s)",
        trade_id, pair, prepared["verdict"], prepared["volume"],
        prepared["sl_price"], prepared["tp_price"], AUTOTRADE_ACCOUNT_MODE,
    )

    d = client.send(req, responseTimeoutInSeconds=20)
    d.addCallbacks(
        lambda msg: _handle_order_submit_response(trade_id, prepared, msg),
        lambda failure: _handle_order_submit_failure(trade_id, prepared, failure),
    )


def _handle_order_submit_failure(trade_id: int, prepared: dict, failure) -> None:
    logger.error("Autotrader: order submit failed for trade #%s: %s", trade_id, failure.getErrorMessage())
    deferToThreadPool(
        reactor, _blocking_pool(), db.mark_auto_trade_error, trade_id, str(failure.getErrorMessage())[:255]
    )
    _notify_admin_async(
        f"❌ Автотрейд #{trade_id} {prepared['pair']} {prepared['verdict']}: "
        f"не вдалося виставити ордер ({failure.getErrorMessage()})"
    )


def _handle_order_submit_response(trade_id: int, prepared: dict, msg) -> None:
    pt = msg.payloadType

    if pt == ProtoOAPayloadType.PROTO_OA_EXECUTION_EVENT:
        event = ProtoOAExecutionEvent()
        event.ParseFromString(msg.payload)
        _apply_execution_event(event, trade_id_hint=trade_id, prepared=prepared)
        return

    if pt == ProtoOAPayloadType.PROTO_OA_ORDER_ERROR_EVENT:
        event = ProtoOAOrderErrorEvent()
        event.ParseFromString(msg.payload)
        message = f"{event.errorCode}: {event.description}"
        deferToThreadPool(reactor, _blocking_pool(), db.mark_auto_trade_error, trade_id, message[:255])
        _notify_admin_async(f"❌ Автотрейд #{trade_id} {prepared['pair']} {prepared['verdict']}: {message}")
        return

    if pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
        res = ProtoOAErrorRes()
        res.ParseFromString(msg.payload)
        message = f"{res.errorCode}: {res.description}"
        deferToThreadPool(reactor, _blocking_pool(), db.mark_auto_trade_error, trade_id, message[:255])
        _notify_admin_async(f"❌ Автотрейд #{trade_id} {prepared['pair']} {prepared['verdict']}: {message}")
        return

    logger.warning("Autotrader: unexpected response payloadType=%s for trade #%s", pt, trade_id)


# ----------------------------------------------------------------------
# Execution events (entries + exits) — registered on the shared client by
# ctrader.start_ctrader_client() so this also catches events we didn't
# directly request, like a position auto-closing on TP/SL.
# ----------------------------------------------------------------------


def handle_execution_event(event: ProtoOAExecutionEvent) -> None:
    try:
        _apply_execution_event(event)
    except Exception:
        logger.exception("Autotrader: failed to process execution event")


def _apply_execution_event(event: ProtoOAExecutionEvent, *, trade_id_hint: int | None = None, prepared: dict | None = None) -> None:
    order = event.order if event.HasField("order") else None
    deal = event.deal if event.HasField("deal") else None
    position = event.position if event.HasField("position") else None

    broker_order_id = str(order.orderId) if order else None
    broker_position_id = None
    if position is not None:
        broker_position_id = str(position.positionId)
    elif deal is not None:
        broker_position_id = str(deal.positionId)

    deferToThreadPool(
        reactor,
        _blocking_pool(),
        _persist_execution_event,
        event.executionType,
        trade_id_hint,
        broker_order_id,
        broker_position_id,
        order,
        deal,
        prepared,
    )


def _entry_price_from_event(order, deal, position) -> float | None:
    if order is not None and order.executionPrice:
        return order.executionPrice
    if deal is not None and deal.executionPrice:
        return deal.executionPrice
    if position is not None and position.price:
        return position.price
    return None


def _classify_close(exec_price: float | None, tp_price: float | None, sl_price: float | None) -> str:
    if exec_price is None:
        return "closed_manual"

    candidates = []
    if tp_price is not None:
        candidates.append(("closed_tp", abs(exec_price - tp_price)))
    if sl_price is not None:
        candidates.append(("closed_sl", abs(exec_price - sl_price)))
    if not candidates:
        return "closed_manual"

    candidates.sort(key=lambda item: item[1])
    label, distance = candidates[0]

    tolerance = abs(tp_price - sl_price) * 0.15 if (tp_price is not None and sl_price is not None) else None
    if tolerance is not None and distance <= tolerance:
        return label
    return "closed_manual"


def _persist_execution_event(execution_type, trade_id_hint, broker_order_id, broker_position_id, order, deal, prepared) -> None:
    trade = None
    if trade_id_hint:
        trade = db.get_auto_trade(trade_id_hint)
    if trade is None and broker_position_id:
        trade = db.find_auto_trade_by_broker_position_id(broker_position_id)
    if trade is None and broker_order_id:
        trade = db.find_auto_trade_by_broker_order_id(broker_order_id)

    if trade is None:
        return  # not one of ours

    # Closing deal: cTrader always attaches closePositionDetail to a deal
    # that closes (or partially closes) a position.
    if deal is not None and deal.HasField("closePositionDetail"):
        detail = deal.closePositionDetail
        money_digits = detail.moneyDigits or 2
        pnl_amount = (detail.grossProfit + detail.swap) / (10 ** money_digits)
        status = _classify_close(deal.executionPrice or None, trade.get("tp_price"), trade.get("sl_price"))

        if db.mark_auto_trade_closed(trade["id"], status=status, pnl_amount=pnl_amount):
            logger.info(
                "AUTOTRADE: #%s %s %s closed (%s), pnl=%.2f",
                trade["id"], trade["pair"], trade["direction"], status, pnl_amount,
            )
            _notify_admin_async(
                f"📤 Автотрейд #{trade['id']} {trade['pair']} {trade['direction']} закрито ({status})\n"
                f"PnL: {pnl_amount:.2f}"
            )
        return

    if execution_type in (ProtoOAExecutionType.ORDER_REJECTED, ProtoOAExecutionType.ORDER_CANCELLED, ProtoOAExecutionType.ORDER_EXPIRED):
        if trade["status"] in {"submitted"}:
            db.mark_auto_trade_error(trade["id"], f"execution_type={execution_type}")
            _notify_admin_async(f"❌ Автотрейд #{trade['id']} {trade['pair']}: ордер не виконано ({execution_type})")
        return

    if execution_type in (ProtoOAExecutionType.ORDER_ACCEPTED, ProtoOAExecutionType.ORDER_FILLED):
        if trade["status"] != "submitted":
            return  # already opened

        entry_price = _entry_price_from_event(order, deal, None)
        if db.mark_auto_trade_open(
            trade["id"],
            broker_order_id=broker_order_id,
            broker_position_id=broker_position_id,
            entry_price=entry_price,
        ):
            entry_price_label = f"{entry_price:.5f}" if isinstance(entry_price, (int, float)) else "n/a"
            logger.info(
                "AUTOTRADE: #%s %s %s відкрито entry=%s (mode=%s)",
                trade["id"], trade["pair"], trade["direction"], entry_price_label, trade["account_mode"],
            )
            _notify_admin_async(
                f"📥 Автотрейд #{trade['id']} {trade['pair']} {trade['direction']} відкрито\n"
                f"Entry: {entry_price_label} · SL: {trade.get('sl_price')} · TP: {trade.get('tp_price')} "
                f"· volume: {trade.get('volume')} · режим: {trade['account_mode']}"
            )


# ----------------------------------------------------------------------
# Entry point — called from scanner.py alongside signal_tracking
# ----------------------------------------------------------------------


def maybe_enter_trade(result: dict):
    if not is_active():
        return None

    if not isinstance(result, dict) or not result.get("is_trade_allowed"):
        return None

    verdict = str(result.get("verdict_text") or "").upper()
    if verdict not in {"BUY", "SELL"}:
        return None

    pair = result.get("pair")
    entry_price = result.get("price")
    atr = result.get("atr")

    if not pair or not isinstance(entry_price, (int, float)):
        return None
    if not isinstance(atr, (int, float)) or atr <= 0:
        return None

    d = deferToThreadPool(reactor, _blocking_pool(), _prepare_and_check_risk, pair, verdict, entry_price, atr)
    d.addCallback(_submit_order_on_reactor_thread)
    d.addErrback(lambda failure: logger.error("Autotrader: risk check failed for %s: %s", pair, failure.getErrorMessage()))
    return d
