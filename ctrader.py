# ctrader.py
import logging
import time
from typing import Optional

from twisted.internet import reactor

import config
import scanner
from config import STOCK_TICKERS, get_ct_client_id, get_ct_client_secret
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASpotEvent,
    ProtoOASubscribeSpotsReq,
    ProtoOASymbolsListRes,
)
from errors import SpotEventError, safe_twisted
from notifier import notify_admin
from price_utils import resolve_price_divisor
from spotware_connect import SpotwareConnect
from state import app_state

logger = logging.getLogger("ctrader")

_RECONNECT_BASE_DELAY = 5
_RECONNECT_MAX_DELAY = 120
_RECONNECT_MAX_TRIES = 10

_STALE_THRESHOLD = 300
_STALE_CHECK_INTERVAL = 60

_reconnect_attempt: int = 0
_reconnect_scheduled: bool = False
_subscribed_symbols: set[str] = set()
_stale_check_call = None


def _normalize_pair(pair: str) -> str:
    return pair.replace("/", "").upper()


@safe_twisted(
    "spot_event",
    threshold=10,
    window=60.0,
    on_threshold=lambda: _schedule_reconnect(),
)
def _on_spot_event(event: ProtoOASpotEvent) -> None:
    if not (event.HasField("bid") or event.HasField("ask")):
        return

    name = app_state.symbol_id_map.get(event.symbolId)
    if not name:
        return

    details = app_state.get_symbol_details(name)
    if not details:
        raise SpotEventError(
            f"Немає кешу для symbolId={event.symbolId}",
            symbol_id=event.symbolId,
        )

    div = resolve_price_divisor(details)
    bid = event.bid / div if event.HasField("bid") else None
    ask = event.ask / div if event.HasField("ask") else None
    mid = (bid + ask) / 2.0 if bid is not None and ask is not None else bid or ask

    pair_norm = _normalize_pair(name)
    payload = {
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "ts": time.time(),
    }

    app_state.update_live_price(pair_norm, payload)

    app_state.publish_sse(
        {
            "type": "price",
            "pair": pair_norm,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "ts": payload["ts"],
        }
    )


def _find_in_cache(pair: str):
    return app_state.get_symbol_details(pair)


def start_price_subscriptions() -> None:
    global _subscribed_symbols

    if not app_state.SYMBOLS_LOADED:
        logger.warning("start_price_subscriptions: символи ще не завантажені, відкладаємо на 5s")
        reactor.callLater(5, start_price_subscriptions)
        return

    if not app_state.client or not getattr(app_state.client._client, "account_id", None):
        logger.warning("start_price_subscriptions: client не готовий, відкладаємо на 5s")
        reactor.callLater(5, start_price_subscriptions)
        return

    try:
        scanner_assets = scanner._collect_assets_to_scan()
    except Exception:
        logger.exception("Не вдалося зібрати активи для підписки")
        scanner_assets = []

    all_assets = sorted({_normalize_pair(p) for p in (scanner_assets + STOCK_TICKERS)})
    new_assets = [p for p in all_assets if p not in _subscribed_symbols]

    if not new_assets:
        logger.info("start_price_subscriptions: всі активи вже підписані.")
        return

    logger.info(
        f"start_price_subscriptions: підписуємо {len(new_assets)} нових активів "
        f"(вже підписано: {len(_subscribed_symbols)})"
    )

    for i, pair in enumerate(new_assets):
        reactor.callLater(i * 0.1, _subscribe_one_asset, pair)


def _subscribe_one_asset(pair_norm: str) -> None:
    details = _find_in_cache(pair_norm)
    if not details:
        available = list(app_state.symbol_cache.keys())[:10]
        logger.warning(
            f"Символ '{pair_norm}' не знайдено в кеші. "
            f"Приклади доступних: {available}"
        )
        return

    try:
        req = ProtoOASubscribeSpotsReq(
            ctidTraderAccountId=app_state.client._client.account_id,
            symbolId=[details.symbolId],
        )
        app_state.client.send(req).addErrback(
            lambda failure, pair=pair_norm: logger.error(
                f"Помилка підписки на {pair}: {failure.getErrorMessage()}"
            )
        )
        _subscribed_symbols.add(pair_norm)
        logger.debug(f"Підписано: {pair_norm} (symbolId={details.symbolId})")
    except Exception:
        logger.exception(f"Помилка підписки на {pair_norm}")


def _schedule_reconnect() -> None:
    global _reconnect_scheduled, _reconnect_attempt

    if _reconnect_scheduled:
        logger.debug("Reconnect вже заплановано, пропускаємо.")
        return

    if _reconnect_attempt >= _RECONNECT_MAX_TRIES:
        msg = (
            f"🛑 cTrader: вичерпано {_RECONNECT_MAX_TRIES} спроб реконнекту. "
            "Потрібне ручне втручання."
        )
        logger.critical(msg)
        notify_admin(msg, alert_key="ctrader_reconnect_exhausted")
        return

    delay = min(_RECONNECT_BASE_DELAY * (2 ** _reconnect_attempt), _RECONNECT_MAX_DELAY)
    _reconnect_attempt += 1
    _reconnect_scheduled = True

    logger.warning(
        f"Reconnect через {delay}s (спроба {_reconnect_attempt}/{_RECONNECT_MAX_TRIES})"
    )
    reactor.callLater(delay, _do_reconnect)


def _do_reconnect() -> None:
    global _reconnect_scheduled, _subscribed_symbols

    _reconnect_scheduled = False
    logger.info(f"Виконую reconnect #{_reconnect_attempt}...")

    _cancel_stale_check()

    old_client = app_state.client
    app_state.clear_symbol_state()
    _subscribed_symbols = set()

    if old_client:
        try:
            old_client.stop()
        except Exception:
            logger.exception("Не вдалося зупинити старий cTrader client")

    try:
        start_ctrader_client()
    except Exception:
        logger.exception("Виняток під час reconnect, плануємо наступну спробу...")
        _schedule_reconnect()


def _on_ctrader_disconnected(reason: str) -> None:
    msg = f"⚡ cTrader відключився: {reason}"
    logger.error(msg)
    notify_admin(msg, alert_key="ctrader_disconnected")
    app_state.mark_symbols_loaded(False)
    _schedule_reconnect()


def _check_stale_prices() -> None:
    _schedule_stale_check()

    if not app_state.SYMBOLS_LOADED:
        return

    prices = app_state.get_live_prices_snapshot()
    if not prices:
        if _subscribed_symbols:
            logger.warning(
                f"Є {len(_subscribed_symbols)} підписок але live_prices порожній — "
                "можливо з'єднання мертве"
            )
        return

    now = time.time()
    stale = [n for n, d in prices.items() if (now - d.get("ts", 0)) > _STALE_THRESHOLD]
    fresh_count = len(prices) - len(stale)
    logger.debug(f"Stale check: {fresh_count} свіжих, {len(stale)} застарілих")

    if stale and len(stale) == len(prices):
        msg = (
            f"⏰ cTrader: всі {len(prices)} цін застаріли (>{_STALE_THRESHOLD}s). "
            "Запускаю reconnect."
        )
        logger.error(msg)
        notify_admin(msg, alert_key="ctrader_all_stale")
        _schedule_reconnect()
    elif stale:
        logger.warning(f"Застарілі: {', '.join(stale[:10])}")


def _schedule_stale_check() -> None:
    global _stale_check_call

    if _stale_check_call and _stale_check_call.active():
        return

    _stale_check_call = reactor.callLater(_STALE_CHECK_INTERVAL, _check_stale_prices)


def _cancel_stale_check() -> None:
    global _stale_check_call

    if _stale_check_call and _stale_check_call.active():
        try:
            _stale_check_call.cancel()
        except Exception:
            logger.exception("Не вдалося скасувати stale check")
    _stale_check_call = None


def _on_symbols_loaded(raw) -> None:
    res = ProtoOASymbolsListRes()
    res.ParseFromString(raw.payload)

    app_state.clear_symbol_state()

    for s in res.symbol:
        app_state.symbol_cache[s.symbolName] = s
        app_state.symbol_id_map[s.symbolId] = s.symbolName
        app_state.client.symbol_map[s.symbolName] = s.symbolId

        norm = _normalize_pair(s.symbolName)
        if norm not in app_state.symbol_cache:
            app_state.symbol_cache[norm] = s

        if len(norm) >= 6:
            slash = f"{norm[:3]}/{norm[3:]}"
            if slash not in app_state.symbol_cache:
                app_state.symbol_cache[slash] = s

    app_state.all_symbol_names = sorted(
        {k for k in app_state.symbol_cache.keys() if isinstance(k, str)}
    )
    app_state.mark_symbols_loaded(True)

    logger.info(f"Символи завантажено: {len(res.symbol)}")
    sample = list(app_state.symbol_cache.keys())[:15]
    logger.info(f"Приклади назв символів у кеші: {sample}")

    start_price_subscriptions()


def on_ctrader_ready() -> None:
    global _reconnect_attempt

    logger.info("cTrader авторизований і готовий.")
    _reconnect_attempt = 0
    _cancel_stale_check()
    _schedule_stale_check()

    d = app_state.client.get_all_symbols()
    d.addCallback(_on_symbols_loaded)
    d.addErrback(
        lambda failure: logger.error(
            f"Не вдалося завантажити символи: {failure.getErrorMessage()}"
        )
    )


def start_ctrader_client() -> None:
    client_id = get_ct_client_id()
    client_secret = get_ct_client_secret()

    if not client_id or not client_secret:
        from errors import ConfigError
        raise ConfigError("CT_CLIENT_ID або CT_CLIENT_SECRET не налаштовані")

    old_client = app_state.client
    if old_client:
        try:
            old_client.stop()
        except Exception:
            logger.exception("Не вдалося зупинити попередній cTrader client")

    client = SpotwareConnect(client_id, client_secret)
    app_state.client = client

    client.on("ready", on_ctrader_ready)
    client.on("spot_event", _on_spot_event)
    client.on("error", lambda reason: _on_ctrader_disconnected(str(reason)))

    reactor.callWhenRunning(client.start)