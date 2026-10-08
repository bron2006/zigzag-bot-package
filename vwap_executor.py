"""vwap_executor.py - Крок 3.1 (feature/vwap-long-executor, 2026-08-22): real
cTrader orders for the LONG-only session-VWAP mean-reversion strategy, per
the plan approved by the user 2026-08-22 after the full validation chain
(60-day backtest -> 6-month verification -> pre-execution review) cleared.

    python vwap_executor.py [--poll-seconds 60]

UPDATE 2026-10-08: READ-ONLY now owns a durable local quote-based paper
journal (vwap_paper.py / VWAP_PAPER.md), not repeated would-enter logs.
The historical positive backtest is not proof of executable profitability:
it used hindsight Low entries and different risk/exit assumptions. The
broker-order branch remains unchanged; paper results must not be presented
as actual account PnL or as an exact replay of that older branch.

SAFETY MODEL (see config.py): VWAP_EXECUTOR_ENABLED=false by default;
VWAP_EXECUTOR_ACCOUNT_MODE has no runtime toggle anywhere in this codebase
(same rule as AUTOTRADE_ACCOUNT_MODE - live requires manually editing the
local .env). VWAP_EXECUTOR_READ_ONLY runs the full poll loop and logs every
entry/exit decision without ever calling the Order API - a step past the
shadow logger (which never evaluates entry/exit conditions at all).

WHY A SEPARATE FILE, NOT AN EXTENSION OF autotrader.py OR
vwap_shadow_logger.py: this strategy's exit mechanics are fundamentally
different from autotrader.py's fixed TP/SL bracket - the target is the
LIVE, evolving VWAP (checked every poll, matching the already-validated
backtest's own bar-by-bar logic), not a static broker-side price, plus a
separate hard-time-exit path. Mixing that into autotrader.py would give one
function two incompatible order-management models. Keeping it out of
vwap_shadow_logger.py (which stays exactly as it is, read-only, no orders)
follows this project's established rule of never mixing "just observe" and
"actually trades" in the same code path (CLAUDE.md's "Розділення шарів").

REUSED BY IMPORT, NOT REIMPLEMENTED:
  - compute_causal_vwap_bands, _process_session-equivalent session logic:
    vwap_mean_reversion_event_study.py
  - session window, bar fetch + the two data-quality guards
    (_drop_incomplete_trailing_bars, _filter_anomalous_bars):
    vwap_shadow_logger.py
  - account balance fetch, exact-match symbol resolution, broker
    min/max/step volume normalization: autotrader.py / ctrader.py

ORDER-RETRY SAFETY (commit 2/8): a network timeout on ORDER SUBMISSION is
NOT safe to retry blindly the way vwap_fetch_history.py's read-only fetch
retry is - the first request may have actually succeeded server-side with
the response merely lost/delayed, and a blind retry would place a SECOND
real order. Every entry order carries a unique clientOrderId
(f"vwap-{trade_id}"); before any retry attempt, this queries the account's
current open orders (ProtoOAReconcileReq) for that clientOrderId and adopts
the existing order instead of submitting a duplicate if found.

PARTIAL FILL POLICY (commit 2/8, proposed and approved 2026-08-22): cancel
the unfilled remainder rather than wait for more. The validated backtest
models each trade as a single block at a known entry price; a smaller
filled size with the rest still resting has no equivalent there. At this
strategy's position sizing (0.5% risk/trade), a genuine liquidity shortfall
at the -2sigma level is unlikely for these forex_cross pairs - more likely
a sign of unusual conditions (thin liquidity, a gap) where continuing to
chase the remainder at a now-stale price is riskier than accepting the
smaller filled size.
"""
import argparse
import logging
import os
import threading
import time as time_module
from datetime import datetime, timezone

from twisted.internet import defer, reactor, task
from twisted.internet.threads import deferToThreadPool

import autotrader
import ctrader
import db
import news_filter
from bounded_io import BoundedIO, BoundedIOTimeout
from analysis import _resolve_symbol_details
from config import (
    VWAP_EXECUTOR_ACCOUNT_MODE,
    VWAP_EXECUTOR_ENABLED,
    VWAP_EXECUTOR_MAX_CONSECUTIVE_LOSSES,
    VWAP_EXECUTOR_MAX_DAILY_LOSS_PERCENT,
    VWAP_EXECUTOR_MAX_OPEN_POSITIONS,
    VWAP_EXECUTOR_MAX_RISK_PERCENT_PER_TRADE,
    VWAP_EXECUTOR_MAX_SLIPPAGE_POINTS,
    VWAP_EXECUTOR_ORDER_RETRY_ATTEMPTS,
    VWAP_EXECUTOR_ORDER_TIMEOUT_SECONDS,
    VWAP_EXECUTOR_POLL_SECONDS,
    VWAP_EXECUTOR_READ_ONLY,
    VWAP_EXECUTOR_STALE_POLL_ALERT_SECONDS,
    VWAP_EXECUTOR_STOP_SIGMA,
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOACancelOrderReq,
    ProtoOAExecutionEvent,
    ProtoOANewOrderReq,
    ProtoOAReconcileReq,
    ProtoOAReconcileRes,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAExecutionType,
    ProtoOAOrderType,
    ProtoOATimeInForce,
    ProtoOATradeSide,
)
from state import app_state
from vwap_mean_reversion_event_study import compute_causal_vwap_bands
from vwap_shadow_logger import (
    M5_PERIOD_SECONDS,
    SYMBOLS,
    _current_session_window_utc,
    _drop_incomplete_trailing_bars,
    _fetch_session_bars,
    _filter_anomalous_bars,
    _wait_for_live_client,
)

logger = logging.getLogger("vwap_executor")

_paper_bridge = None

def _get_paper_bridge():
    global _paper_bridge
    if _paper_bridge is None:
        from pathlib import Path
        from vwap_paper_bridge import PaperBridge
        path = Path(__file__).resolve().parent/'logs'/'vwap_paper.sqlite3'
        _paper_bridge = PaperBridge(path,max_positions=VWAP_EXECUTOR_MAX_OPEN_POSITIONS)
    return _paper_bridge

def _paper_spot_event(event):
    if _paper_bridge is None:
        return
    symbol = app_state.symbol_id_map.get(event.symbolId)
    if not symbol:
        return
    # Protocol price scale is fixed 1e5; no digits-dependent remapping.
    bid = event.bid/100000.0 if event.HasField('bid') else None
    ask = event.ask/100000.0 if event.HasField('ask') else None
    _paper_bridge.quote(symbol,ts=time_module.time(),bid=bid,ask=ask)

def _paper_intention(client,symbol,session_id,session_end_ts,df,limit,stop,volume,target):
    import numpy as np
    signal_ts = time_module.time()
    if not session_end_ts-4*3600 <= signal_ts < session_end_ts:
        return False
    if len(df) < 15:
        logger.warning('VWAP paper: insufficient ATR history for %s',symbol)
        return
    high,low,close = (df[field].to_numpy(dtype=float) for field in ('High','Low','Close'))
    tr = np.maximum(high[1:]-low[1:],np.maximum(np.abs(high[1:]-close[:-1]),np.abs(low[1:]-close[:-1])))
    fee = .02*float(np.mean(tr[-14:]))
    bridge = _get_paper_bridge()
    bridge.attach(client,_paper_spot_event,is_current=lambda:app_state.client is client)
    return bridge.signal(symbol=symbol,session=session_id,ts=signal_ts,end_ts=session_end_ts,
                  limit=limit,stop=stop,fee_price=fee,volume=volume,target=target,
                  target_asof=float(df['Timestamp'].iloc[-1])+M5_PERIOD_SECONDS)


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _notify_admin_async(text: str) -> None:
    def _send():
        try:
            from notifier import notify_admin

            notify_admin(text, parse_mode="HTML")
        except Exception:
            logger.exception("VWAP executor: failed to notify admin")

    deferToThreadPool(reactor, _blocking_pool(), _send)


# ----------------------------------------------------------------------
# Entry order construction / submission (commit 2/8)
# ----------------------------------------------------------------------


def _client_order_id(trade_id: int) -> str:
    return f"vwap-{trade_id}"


def _build_limit_entry_request(
    *, trade_id: int, account_id: int, symbol_id: int,
    limit_price: float, stop_price: float, volume: int, expiration_ts_ms: int,
) -> ProtoOANewOrderReq:
    """Pure construction, no I/O - kept separate from submission so the
    request shape itself is directly testable. GOOD_TILL_DATE +
    expirationTimestamp (not GOOD_TILL_CANCEL) lets the broker expire an
    unfilled entry at session end on its own, instead of this process
    having to notice and cancel it - one less thing that can go wrong on
    a missed poll cycle. No takeProfit: the exit target is the live VWAP,
    monitored every poll, never a static broker-side price."""
    return ProtoOANewOrderReq(
        ctidTraderAccountId=account_id,
        symbolId=symbol_id,
        orderType=ProtoOAOrderType.LIMIT,
        tradeSide=ProtoOATradeSide.BUY,  # LONG-only, by the validated hypothesis
        volume=volume,
        limitPrice=limit_price,
        stopLoss=stop_price,
        timeInForce=ProtoOATimeInForce.GOOD_TILL_DATE,
        expirationTimestamp=expiration_ts_ms,
        clientOrderId=_client_order_id(trade_id),
        label=_client_order_id(trade_id),
    )


def _find_order_by_client_id(reconcile_res: ProtoOAReconcileRes, client_order_id: str):
    """Pure lookup over an already-fetched reconcile response - the
    idempotency check a retry attempt runs before ever submitting a
    second order. Returns the matching ProtoOAOrder or None."""
    for order in reconcile_res.order:
        if order.clientOrderId == client_order_id:
            return order
    return None


@defer.inlineCallbacks
def _reconcile(client, account_id: int):
    req = ProtoOAReconcileReq(ctidTraderAccountId=account_id)
    msg = yield client.send(req, responseTimeoutInSeconds=VWAP_EXECUTOR_ORDER_TIMEOUT_SECONDS)
    res = ProtoOAReconcileRes()
    res.ParseFromString(msg.payload)
    defer.returnValue(res)


@defer.inlineCallbacks
def _place_limit_entry_with_retry(
    *, trade_id: int, client, account_id: int, symbol_id: int,
    limit_price: float, stop_price: float, volume: int, expiration_ts_ms: int,
):
    """Submits the entry LIMIT order, retrying up to VWAP_EXECUTOR_ORDER_
    RETRY_ATTEMPTS times on timeout/transient error - but ALWAYS checking
    for an already-placed order (via clientOrderId, through ProtoOA
    ReconcileReq) before any retry beyond the first attempt. See this
    module's own docstring for why this differs from the blind-retry
    pattern used elsewhere in this project for read-only data fetches.

    Returns the execution response message on success, or raises the last
    error after all attempts are exhausted."""
    client_order_id = _client_order_id(trade_id)
    last_error = None

    for attempt in range(1, VWAP_EXECUTOR_ORDER_RETRY_ATTEMPTS + 1):
        if attempt > 1:
            try:
                reconcile_res = yield _reconcile(client, account_id)
            except Exception:
                logger.warning("VWAP entry #%s: reconcile check failed before retry attempt %d", trade_id, attempt, exc_info=True)
                reconcile_res = None

            if reconcile_res is not None:
                existing = _find_order_by_client_id(reconcile_res, client_order_id)
                if existing is not None:
                    logger.info(
                        "VWAP entry #%s: found already-placed order (orderId=%s) via reconcile - "
                        "adopting it instead of submitting a duplicate on retry %d",
                        trade_id, existing.orderId, attempt,
                    )
                    defer.returnValue(("existing", existing))
                    return

        req = _build_limit_entry_request(
            trade_id=trade_id, account_id=account_id, symbol_id=symbol_id,
            limit_price=limit_price, stop_price=stop_price, volume=volume,
            expiration_ts_ms=expiration_ts_ms,
        )
        try:
            msg = yield client.send(req, responseTimeoutInSeconds=VWAP_EXECUTOR_ORDER_TIMEOUT_SECONDS)
            defer.returnValue(("submitted", msg))
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "VWAP entry #%s: order submission attempt %d/%d failed: %s",
                trade_id, attempt, VWAP_EXECUTOR_ORDER_RETRY_ATTEMPTS, exc,
            )

    raise last_error if last_error is not None else RuntimeError("order submission failed with no captured error")


# ----------------------------------------------------------------------
# Partial fill handling (commit 2/8)
# ----------------------------------------------------------------------


def _extract_fill_details(order) -> dict:
    """Pure extraction from a ProtoOAOrder (or None) - entry price and how
    much of the requested volume actually filled. Takes the already-
    extracted order, not the whole event, matching autotrader.py's own
    _apply_execution_event/_persist_execution_event split - separate from
    the event-dispatch/DB-write side effects so it's directly testable."""
    if order is None:
        return {"entry_price": None, "filled_volume": None, "requested_volume": None}

    trade_data = order.tradeData
    return {
        "entry_price": order.executionPrice or None,
        "filled_volume": order.executedVolume or 0,
        "requested_volume": trade_data.volume or None,
    }


def _is_partial_fill(fill: dict) -> bool:
    if fill["filled_volume"] is None or fill["requested_volume"] is None:
        return False
    return 0 < fill["filled_volume"] < fill["requested_volume"]


@defer.inlineCallbacks
def _cancel_order(client, account_id: int, order_id: int):
    req = ProtoOACancelOrderReq(ctidTraderAccountId=account_id, orderId=order_id)
    try:
        yield client.send(req, responseTimeoutInSeconds=VWAP_EXECUTOR_ORDER_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("VWAP: failed to cancel remainder of order %s after partial fill", order_id, exc_info=True)


# ----------------------------------------------------------------------
# Exit decision + market close (commit 3/8)
# ----------------------------------------------------------------------

EXIT_HARD_TIME = "hard_time_exit"
EXIT_VWAP_TOUCH = "vwap_touch"

# Maps a stashed exit_reason (set by mark_vwap_trade_closing when THIS
# process decided to close) to the VwapTrade.status value - a closing deal
# that arrives with NO stashed reason means the broker's own stop-loss
# order fired on its own, the one way a position can close that this
# process never initiated or saw coming in advance.
_EXIT_REASON_TO_STATUS = {
    EXIT_VWAP_TOUCH: "closed_target",
    EXIT_HARD_TIME: "closed_time_exit",
}


def _status_and_reason_for_close(stashed_exit_reason: str | None) -> tuple[str, str]:
    if stashed_exit_reason is None:
        return "closed_stop", "stop_loss"
    return _EXIT_REASON_TO_STATUS.get(stashed_exit_reason, "closed_manual"), stashed_exit_reason


def _decide_exit_reason(now_ts: int, session_end_ts: int, low: float, high: float, vwap: float) -> str | None:
    """Pure decision, no I/O - the whole point of plan item 4 ("hard time
    exit MUST outrank spread filter"). Checked in this exact order: hard
    time exit fires unconditionally once now_ts >= session_end_ts,
    regardless of anything else (spread is never even looked at here -
    there IS no spread check in this function, on purpose, matching the
    plan exactly: closing with a wide spread beats holding overnight).
    Only if the session hasn't ended yet does this check whether the
    live, evolving VWAP has been touched (Low<=vwap<=High on the current
    bar) - the SAME condition the validated backtest's _simulate_event
    checks bar-by-bar, so live and backtest never silently diverge on
    what counts as "target hit"."""
    if now_ts >= session_end_ts:
        return EXIT_HARD_TIME
    if vwap == vwap and low <= vwap <= high:  # vwap==vwap is a NaN check
        return EXIT_VWAP_TOUCH
    return None


def _build_market_close_request(
    *, trade_id: int, account_id: int, symbol_id: int, position_id: int, volume: int,
) -> ProtoOANewOrderReq:
    """MARKET order against the open position (tradeSide=SELL flattens a
    LONG-only position - this strategy never holds SELL), with
    slippageInPoints as the broker-side tolerance the plan asked for on
    exits (unlike the LIMIT entry, a MARKET order genuinely can slip).
    Own clientOrderId namespace (vwap-close-N, not vwap-N) so a reconcile-
    based idempotency check can tell an in-flight close apart from the
    entry that preceded it."""
    return ProtoOANewOrderReq(
        ctidTraderAccountId=account_id,
        symbolId=symbol_id,
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=ProtoOATradeSide.SELL,
        volume=volume,
        positionId=position_id,
        slippageInPoints=VWAP_EXECUTOR_MAX_SLIPPAGE_POINTS,
        clientOrderId=f"vwap-close-{trade_id}",
        label=f"vwap-close-{trade_id}",
    )


@defer.inlineCallbacks
def _place_market_close_with_retry(
    *, trade_id: int, client, account_id: int, symbol_id: int, position_id: int, volume: int,
):
    """Same idempotent-retry shape as _place_limit_entry_with_retry
    (commit 2) - a timeout on a close order is exactly as dangerous to
    retry blindly as one on an entry order (a real close might already
    have gone through), so this reuses the identical
    reconcile-before-retry pattern with its own client_order_id
    namespace."""
    client_order_id = f"vwap-close-{trade_id}"
    last_error = None

    for attempt in range(1, VWAP_EXECUTOR_ORDER_RETRY_ATTEMPTS + 1):
        if attempt > 1:
            try:
                reconcile_res = yield _reconcile(client, account_id)
            except Exception:
                logger.warning("VWAP close #%s: reconcile check failed before retry attempt %d", trade_id, attempt, exc_info=True)
                reconcile_res = None

            if reconcile_res is not None:
                existing = _find_order_by_client_id(reconcile_res, client_order_id)
                if existing is not None:
                    logger.info("VWAP close #%s: found already-placed close order via reconcile on retry %d", trade_id, attempt)
                    defer.returnValue(("existing", existing))
                    return

        req = _build_market_close_request(
            trade_id=trade_id, account_id=account_id, symbol_id=symbol_id,
            position_id=position_id, volume=volume,
        )
        try:
            msg = yield client.send(req, responseTimeoutInSeconds=VWAP_EXECUTOR_ORDER_TIMEOUT_SECONDS)
            defer.returnValue(("submitted", msg))
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "VWAP close #%s: order submission attempt %d/%d failed: %s",
                trade_id, attempt, VWAP_EXECUTOR_ORDER_RETRY_ATTEMPTS, exc,
            )

    raise last_error if last_error is not None else RuntimeError("close order submission failed with no captured error")


# ----------------------------------------------------------------------
# Execution events (fills, expiry, closes) - registered on the shared
# client by ctrader.start_ctrader_client(), same mechanism autotrader.py's
# handle_execution_event already uses (commit 3/8).
# ----------------------------------------------------------------------


def handle_execution_event(event: ProtoOAExecutionEvent) -> None:
    try:
        _apply_execution_event(event)
    except Exception:
        logger.exception("VWAP executor: failed to process execution event")


def _apply_execution_event(event: ProtoOAExecutionEvent) -> None:
    order = event.order if event.HasField("order") else None
    deal = event.deal if event.HasField("deal") else None
    position = event.position if event.HasField("position") else None

    broker_order_id = str(order.orderId) if order else None
    broker_position_id = None
    if position is not None:
        broker_position_id = str(position.positionId)
    elif deal is not None:
        broker_position_id = str(deal.positionId)

    # Partial-fill cancellation (commit 2's approved policy) must happen
    # HERE, on the reactor thread, not inside _persist_execution_event
    # below - that runs on a worker thread purely for blocking DB writes
    # (same division of labor autotrader.py already uses) and has no
    # access to the live client. _extract_fill_details/_is_partial_fill
    # are pure, so checking them here first costs nothing.
    if event.executionType == ProtoOAExecutionType.ORDER_PARTIAL_FILL and order is not None:
        fill = _extract_fill_details(order)
        if _is_partial_fill(fill):
            client = app_state.client
            account_id = getattr(getattr(client, "_client", None), "account_id", None)
            if client and account_id:
                logger.warning(
                    "VWAP: order %s partial fill (%s/%s) - cancelling remainder per approved policy",
                    broker_order_id, fill["filled_volume"], fill["requested_volume"],
                )
                _cancel_order(client, account_id, order.orderId)

    deferToThreadPool(
        reactor, _blocking_pool(), _persist_execution_event,
        event.executionType, broker_order_id, broker_position_id, order, deal,
    )


def _persist_execution_event(execution_type, broker_order_id, broker_position_id, order, deal) -> None:
    trade = None
    if broker_order_id:
        trade = db.find_vwap_trade_by_broker_order_id(broker_order_id)
    if trade is None and broker_position_id:
        trade = db.find_vwap_trade_by_broker_position_id(broker_position_id)
    if trade is None:
        return  # not one of ours

    # Closing deal: cTrader always attaches closePositionDetail to a deal
    # that closes (or partially closes) a position - same shape autotrader.py
    # already relies on (2026-08-15 fix: commission must be included, not
    # just grossProfit+swap, for this to be the true net result).
    if deal is not None and deal.HasField("closePositionDetail"):
        detail = deal.closePositionDetail
        money_digits = detail.moneyDigits or 2
        pnl_amount = (detail.grossProfit + detail.swap + detail.commission) / (10 ** money_digits)
        exit_price = deal.executionPrice or None
        status, exit_reason = _status_and_reason_for_close(trade.get("exit_reason"))

        if db.mark_vwap_trade_closed(
            trade["id"],
            status=status,
            exit_reason=exit_reason,
            exit_price=exit_price,
            expected_exit_price=trade.get("expected_exit_price"),
            pnl_amount=pnl_amount,
        ):
            logger.info(
                "VWAP: #%s %s closed (%s), pnl=%.2f",
                trade["id"], trade["symbol"], exit_reason, pnl_amount,
            )
            _notify_admin_async(
                f"📤 VWAP-угода #{trade['id']} {trade['symbol']} закрито ({exit_reason})\n"
                f"PnL: {pnl_amount:.2f}"
            )
        return

    if execution_type == ProtoOAExecutionType.ORDER_EXPIRED:
        if trade["status"] == "pending":
            db.mark_vwap_trade_expired(trade["id"])
            logger.info("VWAP: #%s %s entry expired unfilled (session ended)", trade["id"], trade["symbol"])
        return

    if execution_type in (ProtoOAExecutionType.ORDER_REJECTED, ProtoOAExecutionType.ORDER_CANCEL_REJECTED):
        if trade["status"] == "pending":
            db.mark_vwap_trade_error(trade["id"], f"execution_type={execution_type}")
            _notify_admin_async(f"❌ VWAP-угода #{trade['id']} {trade['symbol']}: ордер відхилено ({execution_type})")
        return

    if execution_type == ProtoOAExecutionType.ORDER_CANCELLED:
        # Only an error if there was never any fill at all - cancelling the
        # REMAINDER after a partial fill (commit 2's own policy) must not
        # clobber a trade that's already correctly marked open.
        if trade["status"] == "pending":
            db.mark_vwap_trade_error(trade["id"], "order_cancelled_unfilled")
        return

    if execution_type in (ProtoOAExecutionType.ORDER_ACCEPTED, ProtoOAExecutionType.ORDER_FILLED, ProtoOAExecutionType.ORDER_PARTIAL_FILL):
        if trade["status"] != "pending":
            return  # already open or resolved

        fill = _extract_fill_details(order)
        if db.mark_vwap_trade_open(
            trade["id"], broker_order_id=broker_order_id, broker_position_id=broker_position_id,
            entry_price=fill["entry_price"], filled_volume=fill["filled_volume"],
        ):
            logger.info(
                "VWAP: #%s %s entry filled at %s (volume=%s/%s)",
                trade["id"], trade["symbol"], fill["entry_price"], fill["filled_volume"], fill["requested_volume"],
            )
            _notify_admin_async(
                f"📥 VWAP-угода #{trade['id']} {trade['symbol']} відкрито\n"
                f"Entry: {fill['entry_price']} · volume: {fill['filled_volume']}/{fill['requested_volume']}"
            )


# ----------------------------------------------------------------------
# News filter gate (commit 4/8) - reuses news_filter.py directly, the
# same module the main signal pipeline already uses (two independent
# calendar sources, per infra-audit item "news-second-source"). Gates
# ENTRY only, per the plan - EXIT (_decide_exit_reason above) never
# checks news at all: if a position is already open and news starts,
# closing it is safer than holding through it, so exit must never be
# blocked by the same gate that blocks new entries.
# ----------------------------------------------------------------------


@defer.inlineCallbacks
def _news_allows_entry(symbol: str):
    result = yield news_filter.get_latest_news_sentiment_async(symbol)
    defer.returnValue((result or {}).get("verdict") != "BLOCK")


# ----------------------------------------------------------------------
# Risk sizing / max exposure (commit 5/8, plan items 6-7). Reuses
# autotrader.py's own proven pieces rather than a new sizing scheme:
# _get_account_balance (shared cache - see config.py's comment on why),
# _normalize_volume (broker min/max/step volume rounding, exact-match
# symbol resolution). Only the risk-percent-per-trade and max-open-
# positions LIMITS are VWAP-specific config, independently tunable from
# autotrader's own (see CLAUDE.md's documented MVP compromise: the two
# systems don't coordinate combined account exposure).
# ----------------------------------------------------------------------


def _compute_entry_volume(*, balance: float, limit_price: float, stop_price: float, pair: str) -> int | None:
    """Pure sizing math (given an already-fetched balance) plus the one
    piece of I/O-adjacent work (_normalize_volume resolves the symbol to
    read its min/max/step volume) - same risk = balance * risk% formula
    autotrader.py's own _prepare_and_check_risk uses, just against the
    LIMIT entry's stop distance instead of an ATR-derived one."""
    if not isinstance(balance, (int, float)) or balance <= 0:
        return None

    sl_distance = abs(limit_price - stop_price)
    if sl_distance <= 0:
        return None

    risk_amount = balance * (VWAP_EXECUTOR_MAX_RISK_PERCENT_PER_TRADE / 100.0)
    raw_units = risk_amount / sl_distance
    return autotrader._normalize_volume(pair, raw_units)


def _get_account_balance() -> float | None:
    return autotrader._get_account_balance()


def _max_open_positions_reached() -> bool:
    return db.count_open_vwap_trades(VWAP_EXECUTOR_ACCOUNT_MODE) >= VWAP_EXECUTOR_MAX_OPEN_POSITIONS


# ----------------------------------------------------------------------
# Kill switch (commit 6/8, plan items 8-9) - persisted via db (not a
# module global), no auto-resume, mirrors autotrader.py's own daily-loss
# kill switch shape exactly, PLUS a consecutive-losses dimension
# autotrader.py doesn't have at all - that's Binomo's pattern
# (MAX_CONSECUTIVE_LOSSES), reused here per the plan's explicit
# instruction. Both conditions share the same trip/clear mechanism and
# the same `since` fix (2026-08-14/08-15) that keeps a cleared switch
# from immediately re-tripping on the same pre-clear numbers.
# ----------------------------------------------------------------------


def is_active() -> bool:
    if not VWAP_EXECUTOR_ENABLED:
        return False
    state = db.get_vwap_executor_runtime_state()
    if not state.get("database_available", True):
        raise BoundedIOTimeout("Runtime state could not be loaded from database")
    return state["runtime_enabled"] and not state["kill_switch_tripped"]


_database_reads = BoundedIO(reactor, timeout=10.0)


def _db_read(function, *args, **kwargs):
    return _database_reads.call(function, *args, **kwargs)


def _is_read_only() -> bool:
    """VWAP_EXECUTOR_READ_ONLY (static, from .env at process start) OR the
    DB-persisted runtime flag /vwap_executor_readonly toggles - either
    source asking for read-only is honored, one-way-safety (same
    principle as is_active() never letting a runtime toggle override
    VWAP_EXECUTOR_ENABLED=false upward): a runtime command can always ADD
    the read-only restriction, never remove one the static config set."""
    if VWAP_EXECUTOR_READ_ONLY:
        return True
    return db.get_vwap_executor_runtime_state()["read_only"]


def _check_kill_switch_conditions(balance: float, account_mode: str) -> str | None:
    """Pure decision (given an already-fetched balance and the DB reads
    it needs) - returns a human-readable trip reason if either limit is
    breached, else None. Checked before every new entry, mirroring
    autotrader.py's _prepare_and_check_risk's own inline check."""
    state = db.get_vwap_executor_runtime_state()
    cleared_at = state.get("kill_switch_cleared_at")

    daily_pnl = db.get_daily_vwap_pnl(account_mode, since=cleared_at)
    max_daily_loss = balance * (VWAP_EXECUTOR_MAX_DAILY_LOSS_PERCENT / 100.0)
    if daily_pnl <= -max_daily_loss:
        return (
            f"daily pnl {daily_pnl:.2f} breached limit -{max_daily_loss:.2f} "
            f"({VWAP_EXECUTOR_MAX_DAILY_LOSS_PERCENT:.2f}% of balance)"
        )

    consecutive_losses = db.get_consecutive_vwap_losses(account_mode, since=cleared_at)
    if consecutive_losses >= VWAP_EXECUTOR_MAX_CONSECUTIVE_LOSSES:
        return f"{consecutive_losses} consecutive losses (limit {VWAP_EXECUTOR_MAX_CONSECUTIVE_LOSSES})"

    return None


def _trip_kill_switch(reason: str) -> None:
    if not db.trip_vwap_executor_kill_switch(reason):
        return

    logger.critical("VWAP EXECUTOR KILL SWITCH: %s", reason)
    _notify_admin_async(
        "🛑 <b>VWAP EXECUTOR KILL SWITCH</b>\n"
        f"{reason}\n"
        "Виконавця ЗУПИНЕНО і не відновиться сам.\n"
        "Перевір рахунок вручну, тоді /vwap_executor_on, щоб відновити."
    )


# ----------------------------------------------------------------------
# Position sizing / entry scope helpers (commit 7/8)
# ----------------------------------------------------------------------

# Matches vwap_long_only_backtest.py/vwap_6mo_verification.py's own
# bars_remaining_in_session<=48 filter EXACTLY - the validated backtest
# never simulated an entry outside the session's last 4 hours, so live
# entries outside that window would be trading a scenario the backtest
# never actually tested.
MAX_BARS_REMAINING_FOR_ENTRY = 48


def _bars_remaining_ok(now_ts: int, session_end_ts: int) -> bool:
    bars_remaining = (session_end_ts - now_ts) // M5_PERIOD_SECONDS
    return 0 <= bars_remaining <= MAX_BARS_REMAINING_FOR_ENTRY


def _compute_stop_price(*, limit_price: float, vwap: float, band_level: float, stop_sigma: float) -> float:
    """std implied by the live band itself (band_level = vwap - 2*std, by
    construction of compute_causal_vwap_bands's Z_BAND=2.0), NOT a
    separately re-derived value - stop_price = limit_price - stop_sigma*std,
    same shape as the validated backtest's stop_price = effective_entry -
    stop_mult*sigma_at_event."""
    std = (vwap - band_level) / 2.0
    return limit_price - stop_sigma * std


# ----------------------------------------------------------------------
# Dead man's switch (commit 7/8, extended for unattended autostart) -
# infra-audit item #1's same principle, a SEPARATE implementation: this
# process is invisible to /api/health/deep (it's a local, non-cloud
# process, like binomo_executor.py), AND runs on its own OS thread rather
# than anything scheduled through the Twisted reactor - if the reactor
# itself hangs (a bug inside a yield that never resolves, the exact
# failure mode this whole project has hit before with cTrader/Twisted
# code), anything scheduled via the reactor's own LoopingCall would hang
# right along with it and could never alert. A plain threading.Thread
# keeps running regardless.
#
# HEARTBEAT_PATH (added for unattended Task Scheduler autostart, per the
# user's explicit "власника не буде поруч тиждень" scenario): the
# in-process alert above only reaches Telegram - useless if nobody's
# there to act on it for hours. run_vwap_executor.ps1 (the supervisor
# wrapper Task Scheduler launches) is a SEPARATE OS process with no
# access to this process's memory, so it can only detect a hang by
# reading a FILE this process writes on its own heartbeat, then force-
# kill and restart. Written on every _mark_poll_completed call - the
# exact same moment the in-process alert's own staleness clock resets.
# ----------------------------------------------------------------------

HEARTBEAT_PATH = "logs/vwap_executor_heartbeat.txt"

_last_poll_completed_ts: float = 0.0
_dead_mans_switch_alerted = False


def _write_heartbeat_file(ts: float) -> None:
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_PATH), exist_ok=True)
        with open(HEARTBEAT_PATH, "w", encoding="utf-8") as f:
            f.write(str(ts))
    except Exception:
        logger.warning("VWAP executor: failed to write heartbeat file", exc_info=True)


def _mark_poll_completed() -> None:
    global _last_poll_completed_ts, _dead_mans_switch_alerted
    _last_poll_completed_ts = time_module.time()
    _dead_mans_switch_alerted = False
    _write_heartbeat_file(_last_poll_completed_ts)


def _is_poll_cycle_stale(now: float, last_poll_completed_ts: float, threshold_seconds: float) -> bool:
    if last_poll_completed_ts <= 0:
        return False  # not started yet, nothing to alert about
    return (now - last_poll_completed_ts) >= threshold_seconds


def _dead_mans_switch_tick(now: float) -> bool:
    """Check one watchdog tick; scheduled weekend silence applies here too."""
    global _dead_mans_switch_alerted, _last_poll_completed_ts
    if _in_weekend_closure(datetime.fromtimestamp(now, timezone.utc)):
        # Keep the in-memory baseline fresh, so reopening gets a full grace
        # period. Do not write a heartbeat: only the poll loop proves progress.
        _last_poll_completed_ts = now
        _dead_mans_switch_alerted = False
        return False
    if _dead_mans_switch_alerted:
        return False
    if not _is_poll_cycle_stale(now, _last_poll_completed_ts, VWAP_EXECUTOR_STALE_POLL_ALERT_SECONDS):
        return False

    _dead_mans_switch_alerted = True
    age = now - _last_poll_completed_ts
    logger.critical("VWAP executor: poll cycle stale for %.0fs", age)
    try:
        from notifier import notify_admin

        notify_admin(
            f"🛑 VWAP executor: цикл опитування не завершувався {age:.0f}с "
            f"(поріг {VWAP_EXECUTOR_STALE_POLL_ALERT_SECONDS:.0f}с) - процес міг зависнути.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("VWAP executor: dead man's switch alert failed")
    return True


def _dead_mans_switch_loop() -> None:  # pragma: no cover - tick tested separately
    while True:
        time_module.sleep(15.0)
        _dead_mans_switch_tick(time_module.time())


# ----------------------------------------------------------------------
# Main poll loop (commit 7/8) - ties entry (2,4,5,6), exit (3), and
# monitoring together. Per-symbol per-poll: fetch+filter bars (imported,
# unchanged from vwap_shadow_logger.py), compute the live VWAP bands
# (imported, unchanged from vwap_mean_reversion_event_study.py), then
# either evaluate an existing OPEN trade for exit or evaluate a fresh
# entry - never both in the same poll, and never more than one
# resting/open trade per (symbol, session) at all
# (db.find_open_vwap_trade_for_session enforces that).
# ----------------------------------------------------------------------


@defer.inlineCallbacks
def _maybe_exit(client, account_id: int, trade: dict, now_ts: int, session_end_ts: int, df, current_vwap: float):
    low = float(df["Low"].iloc[-1])
    high = float(df["High"].iloc[-1])
    reason = _decide_exit_reason(now_ts, session_end_ts, low, high, current_vwap)
    if reason is None:
        return

    expected_price = current_vwap if reason == EXIT_VWAP_TOUCH else float(df["Close"].iloc[-1])

    if (yield _db_read(_is_read_only)):
        logger.info(
            "VWAP [READ-ONLY]: would close #%s %s (%s) at ~%.5f",
            trade["id"], trade["symbol"], reason, expected_price,
        )
        return

    db.mark_vwap_trade_closing(trade["id"], exit_reason=reason, expected_exit_price=expected_price)

    symbol_details = _resolve_symbol_details(app_state.symbol_cache, trade["symbol"])
    if symbol_details is None:
        logger.error("VWAP: cannot resolve symbol for close #%s %s", trade["id"], trade["symbol"])
        return

    try:
        yield _place_market_close_with_retry(
            trade_id=trade["id"], client=client, account_id=account_id,
            symbol_id=symbol_details.symbolId, position_id=int(trade["broker_position_id"]),
            volume=trade["filled_volume"] or trade["volume"],
        )
    except Exception:
        logger.exception("VWAP: failed to submit close order for #%s %s", trade["id"], trade["symbol"])
        _notify_admin_async(f"❌ VWAP-угода #{trade['id']} {trade['symbol']}: не вдалося закрити позицію!")


@defer.inlineCallbacks
def _maybe_enter(client, account_id: int, symbol: str, session_id: str, now_ts: int, session_end_ts: int, df, current_vwap: float, band_level: float):
    if not (yield _db_read(is_active)):
        return
    if not _bars_remaining_ok(now_ts, session_end_ts):
        return

    low = float(df["Low"].iloc[-1])
    if low > band_level:
        return  # -2sigma not touched this poll

    allowed = yield _news_allows_entry(symbol)
    if not allowed:
        return

    # BUG FIX (2026-08-25): _get_account_balance() (autotrader.py) calls
    # blockingCallFromThread(reactor, ...) internally, which is only safe
    # from a NON-reactor thread - it blocks the calling thread waiting for
    # the reactor to run the given function. Called directly here (this
    # inlineCallbacks generator resumes on the reactor thread after the
    # `yield` above), it self-deadlocks the entire reactor: the reactor
    # blocks waiting on itself, so nothing else in the whole process runs
    # either - hit live 2026-08-25, twice, right after this exact line,
    # with total silence (no more log lines of any kind) until the external
    # supervisor force-killed the hung process. Dispatching through the
    # thread pool - same pattern autotrader.py's own callers use - gives
    # blockingCallFromThread a real non-reactor thread to block from.
    balance = yield deferToThreadPool(reactor, _blocking_pool(), _get_account_balance)
    if balance is None:
        return

    kill_reason = yield _db_read(_check_kill_switch_conditions, balance, VWAP_EXECUTOR_ACCOUNT_MODE)
    if kill_reason:
        _trip_kill_switch(kill_reason)
        return

    if (yield _db_read(_max_open_positions_reached)):
        return

    symbol_details = _resolve_symbol_details(app_state.symbol_cache, symbol)
    if symbol_details is None:
        return

    limit_price = band_level
    stop_price = _compute_stop_price(
        limit_price=limit_price, vwap=current_vwap, band_level=band_level, stop_sigma=VWAP_EXECUTOR_STOP_SIGMA,
    )
    volume = _compute_entry_volume(balance=balance, limit_price=limit_price, stop_price=stop_price, pair=symbol)
    if not volume:
        return

    if (yield _db_read(_is_read_only)):
        submitted = _paper_intention(client,symbol,session_id,session_end_ts,df,limit_price,stop_price,volume,current_vwap)
        if submitted:
            logger.info(
                "VWAP [READ-ONLY]: paper intention queued %s LIMIT=%.5f SL=%.5f volume=%s",
                symbol, limit_price, stop_price, volume,
            )
        return

    trade_id = db.create_vwap_trade(
        symbol=symbol, session_id=session_id, volume=volume,
        limit_price=limit_price, stop_price=stop_price, account_mode=VWAP_EXECUTOR_ACCOUNT_MODE,
    )
    if trade_id is None:
        return

    try:
        yield _place_limit_entry_with_retry(
            trade_id=trade_id, client=client, account_id=account_id, symbol_id=symbol_details.symbolId,
            limit_price=limit_price, stop_price=stop_price, volume=volume,
            expiration_ts_ms=session_end_ts * 1000,
        )
    except Exception:
        logger.exception("VWAP: failed to submit entry order for #%s %s", trade_id, symbol)
        db.mark_vwap_trade_error(trade_id, "order submission failed after all retries")
        _notify_admin_async(f"❌ VWAP-угода #{trade_id} {symbol}: не вдалося виставити ордер!")


@defer.inlineCallbacks
def _emergency_stop_all(client, account_id: int):
    """Cancels every resting entry order and closes every open position
    this process knows about - plan item 13 ("миттєва зупинка: закрити
    всі позиції + скасувати всі ордери"). The /vwap_executor_off Telegram
    command (cloud process) only flips the shared runtime_enabled DB flag
    - same binomo_off/autotrade_off pattern, since the cloud process holds
    no cTrader client for THIS purpose. This LOCAL process is what
    actually acts on that flag, checked at the top of every poll cycle
    regardless of session window (a stop request must act immediately,
    not wait for the next session)."""
    if (yield _db_read(_is_read_only)):
        if _paper_bridge is not None:
            _paper_bridge.halt()
        logger.info("VWAP [READ-ONLY]: emergency stop requested; no broker orders sent")
        return
    trades = yield _db_read(db.get_open_and_pending_vwap_trades, VWAP_EXECUTOR_ACCOUNT_MODE)
    if not trades:
        return

    logger.warning("VWAP executor: emergency stop - %d trade(s) to cancel/close", len(trades))
    for trade in trades:
        if trade["status"] == "pending" and trade["broker_order_id"]:
            yield _cancel_order(client, account_id, int(trade["broker_order_id"]))
            db.mark_vwap_trade_error(trade["id"], "cancelled_by_emergency_stop")
        elif trade["status"] == "open" and trade["broker_position_id"]:
            symbol_details = _resolve_symbol_details(app_state.symbol_cache, trade["symbol"])
            if symbol_details is None:
                logger.error("VWAP: emergency stop cannot resolve symbol for #%s %s", trade["id"], trade["symbol"])
                continue

            db.mark_vwap_trade_closing(trade["id"], exit_reason="manual", expected_exit_price=trade.get("entry_price") or 0.0)
            try:
                yield _place_market_close_with_retry(
                    trade_id=trade["id"], client=client, account_id=account_id,
                    symbol_id=symbol_details.symbolId, position_id=int(trade["broker_position_id"]),
                    volume=trade["filled_volume"] or trade["volume"],
                )
            except Exception:
                logger.exception("VWAP: emergency close failed for #%s %s", trade["id"], trade["symbol"])


# WEEKEND HARD CLOSURE (2026-09-06, user request, live finding): the
# per-cycle weekend gate below (2026-09-05 fix) stops it from ever touching
# cTrader off-session, but it still called is_active() - a DB read - every
# single cycle even off-session, to keep the emergency-stop path
# responsive. That DB read is NOT actually free of the network: it hit a
# real, separate problem the very next night (2026-09-05/06) - intermittent
# Supabase/Postgres connection aborts ("SSL SYSCALL error: Software caused
# connection abort") - and stalled poll cycles 90-620s, 17 CRITICAL alerts
# overnight, for a market that cannot possibly be open regardless of
# whether the DB is healthy.
#
# This is a second, coarser gate on top of that one: during the confirmed-
# closed stretch from Friday session end to shortly before Monday's
# session start, skip EVERYTHING - no DB read, no cTrader, not even the
# emergency-stop check - not just "no cTrader". The trade-off (an admin
# /vwap_executor_off or a kill-switch trip during this window would not be
# acted on until the window ends) is accepted deliberately: the session-end
# hard time-exit already closes every trade before Friday close, so there
# is nothing a demo-only executor could legitimately have open here to act
# on, and the window itself is only meant to run unattended over a weekend
# where you're not watching /vwap_executor_status anyway.
#
# Sunday resume time is intentionally earlier than Monday's actual 08:00
# UTC session start (matches vwap_shadow_logger.py's own documented "forex
# reopens Sunday ~22:00 UTC" - one hour of margin) so the narrower
# per-cycle weekend gate (DB-only, no cTrader) has a chance to notice and
# report any real problem before Monday trading actually needs to work,
# rather than the very first poll of the week doubling as the first
# problem discovery.
_WEEKEND_CLOSURE_START_WEEKDAY = 4  # Friday (Monday=0 .. Sunday=6)
_WEEKEND_CLOSURE_START_HOUR_UTC = 22
_WEEKEND_CLOSURE_END_WEEKDAY = 6  # Sunday
_WEEKEND_CLOSURE_END_HOUR_UTC = 21


def _in_weekend_closure(now: datetime) -> bool:
    weekday, hour = now.weekday(), now.hour

    if weekday == _WEEKEND_CLOSURE_START_WEEKDAY and hour >= _WEEKEND_CLOSURE_START_HOUR_UTC:
        return True
    if _WEEKEND_CLOSURE_START_WEEKDAY < weekday < _WEEKEND_CLOSURE_END_WEEKDAY:
        return True  # Saturday, and any other day strictly between (never happens Mon-Fri, kept general)
    if weekday == _WEEKEND_CLOSURE_END_WEEKDAY and hour < _WEEKEND_CLOSURE_END_HOUR_UTC:
        return True
    return False


@defer.inlineCallbacks
def _poll_all_symbols():
    try:
        yield _poll_all_symbols_inner()
    except BoundedIOTimeout as error:
        logger.warning("VWAP: database unavailable; skipping cycle: %s", error)
        # Do not fake a successful heartbeat. A permanently blocked daemon
        # needs the external supervisor to replace the process.
    except Exception:
        logger.exception("VWAP: poll cycle failed; loop will retry")


@defer.inlineCallbacks
def _poll_all_symbols_inner():
    now = datetime.now(timezone.utc)

    if _in_weekend_closure(now):
        if app_state.client is not None:
            logger.info(
                "VWAP executor: вихідні (повне закриття Пт %02d:00 UTC - Нд %02d:00 UTC) - "
                "зупиняю з'єднання з cTrader.",
                _WEEKEND_CLOSURE_START_HOUR_UTC, _WEEKEND_CLOSURE_END_HOUR_UTC,
            )
            try:
                ctrader.stop_ctrader_client()
            except Exception:
                logger.exception("VWAP executor: не вдалося акуратно зупинити cTrader-клієнт на вихідні")
            app_state.client = None
        _mark_poll_completed()
        return

    window = _current_session_window_utc(now)

    if window is None:
        # BUG FIX (2026-09-06, live finding): this used to unconditionally
        # yield _wait_for_live_client() BEFORE ever checking the session
        # window, so every single poll cycle - including all weekend and
        # overnight ones - required a live cTrader connection and would sit
        # blocked (up to 120s) trying to get one. Harmless on a normal
        # weekday (the connection is already up), but on a real weekend,
        # when cTrader's demo backend itself was flaky (CANT_ROUTE_REQUEST /
        # "Trading account is not authorized"), this turned into a
        # reconnect storm that stalled poll cycles past the supervisor's
        # stale threshold - 32 forced restarts in one Saturday
        # (2026-09-05), for a market that can't possibly be open at all.
        #
        # Checking the window FIRST and going straight to
        # _mark_poll_completed() when nothing is open means the
        # overwhelmingly common case (weekend, nothing to manage) never
        # touches cTrader at all. The one thing that still legitimately
        # needs to act immediately regardless of session window - an
        # emergency stop (kill switch trip or admin /vwap_executor_off, see
        # _emergency_stop_all's own docstring) - is preserved by checking
        # get_open_and_pending_vwap_trades first: a pure DB read, so it
        # costs nothing when (as is virtually always the case off-session,
        # since the hard time-exit already closes everything by session
        # end) there is nothing open to close.
        if not (yield _db_read(is_active)):
            if _paper_bridge is not None:
                _paper_bridge.halt()
            trades = yield _db_read(db.get_open_and_pending_vwap_trades, VWAP_EXECUTOR_ACCOUNT_MODE)
            if trades:
                ready = yield _wait_for_live_client()
                if ready:
                    client = app_state.client
                    account_id = getattr(getattr(client, "_client", None), "account_id", None)
                    yield _emergency_stop_all(client, account_id)
        elif app_state.client is not None:
            # Nothing to do and no session can reopen until the next
            # weekday - stop holding/reconnecting a cTrader session that
            # can only flap against a possibly degraded weekend backend.
            logger.info(
                "VWAP executor: сесія закрита (поза торговими годинами) - "
                "зупиняю з'єднання з cTrader до наступної сесії."
            )
            try:
                ctrader.stop_ctrader_client()
            except Exception:
                logger.exception("VWAP executor: не вдалося акуратно зупинити cTrader-клієнт на вихідні")
            app_state.client = None

        # Still marked "completed" even off-session (nights/weekends) -
        # the dead man's switch tracks whether the poll LOOP is alive,
        # not whether a session happens to be open; without this, it
        # would falsely fire every single night once the gap since the
        # last in-session poll exceeds VWAP_EXECUTOR_STALE_POLL_ALERT_
        # SECONDS (90s default).
        _mark_poll_completed()
        return

    if app_state.client is None:
        # Coming back from a weekend/off-hours stop (above) - reconnect now
        # that a session is actually about to use it. Mirrors main()'s own
        # _start() wiring exactly (same event handler attached).
        logger.info("VWAP executor: сесія відкривається - піднімаю з'єднання з cTrader.")
        client = ctrader.start_ctrader_client()
        if client is None:
            _mark_poll_completed()
            return
        client.on("execution_event", handle_execution_event)

    ready = yield _wait_for_live_client(max_wait_seconds=30.0)
    if not ready:
        logger.warning("VWAP executor: cTrader client not ready, skipping poll cycle")
        _mark_poll_completed()  # Loop returned safely; this is NOT quote-feed health.
        return

    client = app_state.client
    account_id = getattr(getattr(client, "_client", None), "account_id", None)

    if not (yield _db_read(is_active)):
        yield _emergency_stop_all(client, account_id)
        _mark_poll_completed()
        return

    session_start, session_end = window
    session_id = session_start.strftime("%Y-%m-%d")
    session_end_ts = int(session_end.timestamp())
    from_ts = int(session_start.timestamp())
    to_ts = int(now.timestamp())

    cycle_started = time_module.monotonic()
    consecutive_fetch_failures = 0
    for symbol in SYMBOLS:
        if time_module.monotonic() - cycle_started >= 60.0:
            logger.warning("VWAP: data scan budget exhausted; remaining symbols skipped")
            break
        df = yield _fetch_session_bars(symbol, from_ts, to_ts)
        if df is None or df.empty:
            consecutive_fetch_failures += 1
            if consecutive_fetch_failures >= 3:
                logger.warning("VWAP: three consecutive data failures; ending degraded cycle")
                break
            continue
        consecutive_fetch_failures = 0

        df = _drop_incomplete_trailing_bars(df, to_ts)
        df, _dropped = _filter_anomalous_bars(df, symbol)
        if df.empty:
            continue

        vwap, upper, lower = compute_causal_vwap_bands(
            df["Close"].to_numpy(dtype=float), df["Volume"].to_numpy(dtype=float),
        )
        if len(vwap) == 0 or vwap[-1] != vwap[-1]:
            continue

        if _paper_bridge is not None:
            _paper_bridge.attach(client,_paper_spot_event,is_current=lambda:app_state.client is client)
            _paper_bridge.target(symbol,ts=time_module.time(),value=float(vwap[-1]),
                                 asof=float(df['Timestamp'].iloc[-1])+M5_PERIOD_SECONDS)

        existing = yield _db_read(db.find_open_vwap_trade_for_session, symbol, session_id, VWAP_EXECUTOR_ACCOUNT_MODE)

        if existing is not None and existing["status"] == "open":
            yield _maybe_exit(client, account_id, existing, to_ts, session_end_ts, df, float(vwap[-1]))
        elif existing is None:
            yield _maybe_enter(client, account_id, symbol, session_id, to_ts, session_end_ts, df, float(vwap[-1]), float(lower[-1]))
        # existing["status"] == "pending": resting limit order, nothing to
        # do here - it fills or expires on its own (execution events).

    _mark_poll_completed()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="Крок 3.1: VWAP LONG-only executor (real orders, gated by VWAP_EXECUTOR_ENABLED).")
    parser.add_argument("--poll-seconds", type=float, default=None)
    args = parser.parse_args()
    poll_seconds = args.poll_seconds or VWAP_EXECUTOR_POLL_SECONDS

    if not VWAP_EXECUTOR_ENABLED:
        print("VWAP_EXECUTOR_ENABLED=false у конфігурації. Нічого не запущено.")
        return

    print(f"VWAP executor запущено. Режим рахунку: {VWAP_EXECUTOR_ACCOUNT_MODE}. "
          f"Read-only: {VWAP_EXECUTOR_READ_ONLY}. Опитування кожні {poll_seconds:.0f}с.")

    print("VWAP watchdog: weekend silence enabled.", flush=True)
    print("VWAP reliability: bounded database reads and broker recovery v2.", flush=True)
    print("VWAP paper: durable quote journal v1 (READ-ONLY branch only).", flush=True)
    if VWAP_EXECUTOR_READ_ONLY:
        _get_paper_bridge()
    threading.Thread(target=_dead_mans_switch_loop, daemon=True).start()

    def _start():
        # BUG FIX (2026-09-06): used to unconditionally connect to cTrader
        # right here, before the first poll cycle even ran - on a boot
        # during a confirmed-closed weekend, that's a connection with
        # nothing to do, immediately torn down again by the very first
        # poll cycle's own weekend gate (see _poll_all_symbols). Harmless
        # (self-correcting within one poll interval) but pointless.
        # _poll_all_symbols already connects on its own the moment
        # app_state.client is None and a session window is actually open -
        # same wiring (execution_event handler included) - so just start
        # the loop and let the first (now=True) cycle decide.
        lc = task.LoopingCall(_poll_all_symbols)
        lc.start(poll_seconds, now=True)

    reactor.callWhenRunning(_start)
    reactor.run()


if __name__ == "__main__":
    main()
