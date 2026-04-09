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
_BOOTSTRAP_GRACE_SECONDS = 180

_PRICE_SSE_THROTTLE_SECONDS = 0.5

_SYMBOL_ALIASES = {
    "US100": ["USTEC", "NAS100", "US100", "US100USD", "USTECH"],
    "US30": ["US30", "DJ30", "DJI30", "WALLSTREET"],
    "SPX500": ["US500", "SPX500", "SP500", "US500USD"],
    "GER40": ["GER40", "DE40", "DAX40", "DE30"],
    "DE30": ["DE30", "GER40", "DE40", "DAX40"],
    "UK100": ["UK100", "FTSE100"],
    "JP225": ["JP225", "JPN225", "NI225"],
    "AUS200": ["AUS200", "AU200"],
}

_reconnect_attempt = 0
_reconnect_scheduled = False
_reconnect_call = None

_stale_check_call = None
_connection_ready_ts = 0.0
_last_any_spot_ts = 0.0
_last_resubscribe_ts = 0.0
_subscriptions_started_ts = 0.0

_subscribed_symbols = set()
_last_price_sse_ts = {}

_stale_all_confirmations = 0
_empty_price_confirmations = 0


def _normalize_pair(pair: str) -> str:
    return pair.replace("/", "").upper().strip()


def _canonical_symbol_key(pair: str) -> str:
    return "".join(ch for ch in _normalize_pair(pair) if ch.isalnum())


def _cancel_reconnect() -> None:
    global _reconnect_call, _reconnect_scheduled

    if _reconnect_call and _reconnect_call.active():
        try:
            _reconnect_call.cancel()
            logger.info("Скасовано запланований reconnect.")
        except Exception:
            logger.exception("Не вдалося скасувати reconnect call")

    _reconnect_call = None
    _reconnect_scheduled = False


def _cancel_stale_check() -> None:
    global _stale_check_call

    if _stale_check_call and _stale_check_call.active():
        try:
            _stale_check_call.cancel()
        except Exception:
            logger.exception("Не вдалося скасувати stale check")
    _stale_check_call = None


def _schedule_stale_check() -> None:
    global _stale_check_call

    if _stale_check_call and _stale_check_call.active():
        return

    _stale_check_call = reactor.callLater(_STALE_CHECK_INTERVAL, _check_stale_prices)


def _reset_runtime_state() -> None:
    global _connection_ready_ts
    global _last_any_spot_ts
    global _last_resubscribe_ts
    global _subscriptions_started_ts
    global _subscribed_symbols
    global _last_price_sse_ts
    global _stale_all_confirmations
    global _empty_price_confirmations

    _connection_ready_ts = 0.0
    _last_any_spot_ts = 0.0
    _last_resubscribe_ts = 0.0
    _subscriptions_started_ts = 0.0

    _subscribed_symbols = set()
    _last_price_sse_ts = {}

    _stale_all_confirmations = 0
    _empty_price_confirmations = 0

    app_state.live_prices.clear()


def _reconnect_attempt_reset() -> None:
    global _reconnect_attempt
    _reconnect_attempt = 0


def _find_in_cache(pair: str):
    details = app_state.get_symbol_details(pair)
    if details:
        return details

    norm = _normalize_pair(pair)
    canon = _canonical_symbol_key(pair)

    for alias in _SYMBOL_ALIASES.get(norm, []):
        alias_details = app_state.get_symbol_details(alias)
        if alias_details:
            logger.info(f"Alias-матч символу '{norm}' -> '{alias}'")
            return alias_details

    for key, value in app_state.symbol_cache.items():
        if not isinstance(key, str):
            continue
        if _canonical_symbol_key(key) == canon:
            return value

    candidates = []
    for key, value in app_state.symbol_cache.items():
        if not isinstance(key, str):
            continue
        ck = _canonical_symbol_key(key)
        if ck.startswith(canon) or canon.startswith(ck):
            candidates.append((key, value))

    if candidates:
        chosen_key, chosen_value = candidates[0]
        logger.info(f"Fallback-матч символу '{norm}' -> '{chosen_key}'")
        return chosen_value

    return None


def _on_spot_event(event: ProtoOASpotEvent) -> None:
    global _last_any_spot_ts
    global _stale_all_confirmations
    global _empty_price_confirmations

    try:
        if not (event.HasField("bid") or event.HasField("ask")):
            return

        symbol_name = app_state.symbol_id_map.get(event.symbolId)
        if not symbol_name:
            return

        details = app_state.get_symbol_details(symbol_name)
        if not details:
            return

        divisor = resolve_price_divisor(details)

        bid = event.bid / divisor if event.HasField("bid") else None
        ask = event.ask / divisor if event.HasField("ask") else None
        mid = (bid + ask) / 2.0 if (bid is not None and ask is not None) else bid or ask

        pair_norm = _normalize_pair(symbol_name)
        now = time.time()

        _last_any_spot_ts = now
        _stale_all_confirmations = 0
        _empty_price_confirmations = 0

        app_state.update_live_price(
            pair_norm,
            {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "ts": now,
            },
        )

        last_push = _last_price_sse_ts.get(pair_norm, 0.0)
        if (now - last_push) >= _PRICE_SSE_THROTTLE_SECONDS:
            _last_price_sse_ts[pair_norm] = now
            app_state.publish_price_sse(
                {
                    "type": "price",
                    "pair": pair_norm,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "ts": now,
                }
            )

    except Exception:
        logger.exception("Error processing spot event")


def start_price_subscriptions(force_resubscribe: bool = False):
    global _subscriptions_started_ts

    if config.APP_MODE == "light":
        logger.info("APP_MODE is 'light'. Skipping automatic price subscriptions.")
        return

    if not app_state.SYMBOLS_LOADED:
        logger.warning("start_price_subscriptions: символи ще не завантажені, відкладаємо на 5s")
        reactor.callLater(5, start_price_subscriptions, force_resubscribe)
        return

    if not app_state.client or not getattr(app_state.client._client, "account_id", None):
        logger.warning("start_price_subscriptions: client не готовий, відкладаємо на 5s")
        reactor.callLater(5, start_price_subscriptions, force_resubscribe)
        return

    logger.info("Starting price subscriptions for all scannable assets...")

    assets_to_subscribe = scanner._collect_assets_to_scan()
    assets_to_subscribe.extend(STOCK_TICKERS)
    assets_to_subscribe = sorted(list(set(_normalize_pair(p) for p in assets_to_subscribe)))

    if not force_resubscribe:
        assets_to_subscribe = [p for p in assets_to_subscribe if p not in _subscribed_symbols]
    else:
        logger.info("Force resubscribe enabled — перепідписуємо всі активи.")

    _subscriptions_started_ts = time.time()

    if not assets_to_subscribe:
        logger.info("start_price_subscriptions: всі активи вже підписані.")
        return

    logger.info(
        f"start_price_subscriptions: підписуємо {len(assets_to_subscribe)} активів "
        f"(вже підписано: {len(_subscribed_symbols)})"
    )

    for i, pair in enumerate(assets_to_subscribe):
        reactor.callLater(i * 0.2, _subscribe_one_pair, pair)


def _subscribe_one_pair(pair_norm: str):
    try:
        symbol_details = _find_in_cache(pair_norm)
        if not symbol_details:
            sample = list(app_state.symbol_cache.keys())[:20]
            logger.warning(
                f"Символ '{pair_norm}' не знайдено в кеші. "
                f"Приклади доступних: {sample}"
            )
            return

        req = ProtoOASubscribeSpotsReq(
            ctidTraderAccountId=app_state.client._client.account_id,
            symbolId=[symbol_details.symbolId],
        )

        d = app_state.client.send(req, timeout=20)
        d.addCallbacks(
            lambda _, p=pair_norm: logger.info(f"✅ Subscribed to price stream for {p}"),
            lambda err, p=pair_norm: logger.error(
                f"❌ Failed to subscribe to {p}: "
                f"{err.getErrorMessage() if hasattr(err, 'getErrorMessage') else err}"
            ),
        )

        _subscribed_symbols.add(pair_norm)

    except Exception:
        logger.exception(f"Error during subscription for {pair_norm}")


def _schedule_reconnect():
    global _reconnect_attempt, _reconnect_scheduled, _reconnect_call

    if _reconnect_scheduled:
        logger.debug("Reconnect already scheduled, skipping.")
        return

    if app_state.client and getattr(app_state.client, "is_authorized", False):
        logger.info("Клієнт уже авторизований — reconnect не плануємо.")
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
    scheduled_attempt = _reconnect_attempt + 1

    _reconnect_attempt += 1
    _reconnect_scheduled = True

    logger.warning(
        f"Reconnect через {delay}s (спроба {scheduled_attempt}/{_RECONNECT_MAX_TRIES})"
    )

    _reconnect_call = reactor.callLater(delay, _do_reconnect, scheduled_attempt)


def _do_reconnect(scheduled_attempt: Optional[int] = None):
    global _reconnect_scheduled, _reconnect_call

    _reconnect_call = None
    _reconnect_scheduled = False

    if app_state.client and getattr(app_state.client, "is_authorized", False):
        logger.info(
            "Пропускаю запланований reconnect #%s: клієнт уже авторизований.",
            scheduled_attempt,
        )
        _reconnect_attempt_reset()
        return

    logger.info(f"Виконую reconnect #{scheduled_attempt or _reconnect_attempt}...")

    _cancel_stale_check()

    old_client = app_state.client
    app_state.clear_symbol_state()
    _reset_runtime_state()

    if old_client:
        try:
            setattr(old_client, "_intentional_shutdown", True)
            old_client.stop()
        except Exception:
            logger.exception("Не вдалося зупинити старий cTrader client")

    app_state.client = None

    try:
        start_ctrader_client()
    except Exception:
        logger.exception("Reconnect failed, scheduling next attempt...")
        _schedule_reconnect()


def _on_ctrader_disconnected(client, reason: str):
    if client is not app_state.client:
        logger.info("Ігноруємо disconnect від неактуального cTrader client: %s", reason)
        return

    if getattr(client, "_intentional_shutdown", False):
        logger.info("Ігноруємо штатний disconnect після intentional shutdown: %s", reason)
        return

    msg = f"⚡ cTrader відключився: {reason}"
    logger.error(msg)
    notify_admin(msg, alert_key="ctrader_disconnected")
    app_state.mark_symbols_loaded(False)
    _schedule_reconnect()


def _check_stale_prices():
    global _stale_all_confirmations
    global _empty_price_confirmations
    global _last_resubscribe_ts

    _schedule_stale_check()

    if not app_state.SYMBOLS_LOADED:
        return

    now = time.time()
    prices = app_state.get_live_prices_snapshot()

    if _connection_ready_ts and (now - _connection_ready_ts) < _BOOTSTRAP_GRACE_SECONDS:
        logger.info(
            "Stale check: bootstrap grace active (%ss/%ss)",
            int(now - _connection_ready_ts),
            _BOOTSTRAP_GRACE_SECONDS,
        )
        return

    if not prices:
        if _subscribed_symbols:
            _empty_price_confirmations += 1
            logger.warning(
                "live_prices порожній при %s підписках. Confirmation %s/4",
                len(_subscribed_symbols),
                _empty_price_confirmations,
            )

            if (now - _last_resubscribe_ts) > 90:
                _last_resubscribe_ts = now
                logger.warning("Пробую force resubscribe без reconnect")
                reactor.callLater(0, start_price_subscriptions, True)

            if _empty_price_confirmations >= 4:
                if _last_any_spot_ts and (now - _last_any_spot_ts) < _STALE_THRESHOLD:
                    logger.info("Spot events були недавно — reconnect скасовую")
                    _empty_price_confirmations = 0
                    return

                logger.error("Після кількох перевірок live_prices все ще порожній. Запускаю reconnect.")
                _empty_price_confirmations = 0
                _schedule_reconnect()
        return

    _empty_price_confirmations = 0

    stale = [n for n, d in prices.items() if (now - d.get("ts", 0)) > _STALE_THRESHOLD]
    fresh_count = len(prices) - len(stale)

    logger.debug(f"Stale check: {fresh_count} fresh, {len(stale)} stale")

    if fresh_count > 0:
        _stale_all_confirmations = 0
        if stale:
            logger.warning(f"Застарілі: {', '.join(stale[:10])}")
        return

    if _last_any_spot_ts and (now - _last_any_spot_ts) < _STALE_THRESHOLD:
        logger.info("Spot events були недавно — reconnect по stale поки не роблю")
        return

    _stale_all_confirmations += 1
    logger.warning(
        "Усі %s цін застарілі. Confirmation %s/4",
        len(prices),
        _stale_all_confirmations,
    )

    if (now - _last_resubscribe_ts) > 90:
        _last_resubscribe_ts = now
        logger.warning("Пробую force resubscribe перед reconnect")
        reactor.callLater(0, start_price_subscriptions, True)

    if _stale_all_confirmations >= 4:
        logger.error(
            f"⏰ cTrader: всі {len(prices)} цін застаріли (>{_STALE_THRESHOLD}s). Після кількох перевірок запускаю reconnect."
        )
        _stale_all_confirmations = 0
        _schedule_reconnect()


def _on_symbols_loaded(raw_message):
    global _connection_ready_ts

    try:
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)

        app_state.clear_symbol_state()

        for s in res.symbol:
            clean_name = s.symbolName.replace("/", "")
            app_state.symbol_cache[s.symbolName] = s
            app_state.symbol_cache[clean_name] = s
            app_state.symbol_id_map[s.symbolId] = clean_name

            canon = _canonical_symbol_key(s.symbolName)
            if canon and canon not in app_state.symbol_cache:
                app_state.symbol_cache[canon] = s

        app_state.all_symbol_names = [s.symbolName for s in res.symbol]
        app_state.mark_symbols_loaded(True)
        _connection_ready_ts = time.time()

        logger.info(f"Символи завантажено: {len(res.symbol)}")
        sample = list(app_state.symbol_cache.keys())[:20]
        logger.info(f"Приклади назв символів у кеші: {sample}")

        start_price_subscriptions()

    except Exception:
        logger.exception("on_symbols_loaded error")


def _on_symbols_error(failure):
    msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
    logger.error(f"Failed to load symbols: {msg}")
    app_state.mark_symbols_loaded(False)


def on_ctrader_ready():
    logger.info("cTrader авторизований і готовий.")

    _cancel_reconnect()
    _reconnect_attempt_reset()

    _cancel_stale_check()
    _schedule_stale_check()

    try:
        d = app_state.client.get_all_symbols()
        d.addCallbacks(_on_symbols_loaded, _on_symbols_error)
    except Exception:
        logger.exception("on_ctrader_ready error")


def start_ctrader_client():
    try:
        client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        setattr(client, "_intentional_shutdown", False)

        app_state.client = client
        app_state.mark_symbols_loaded(False)

        client.on("ready", on_ctrader_ready)
        client.on("spot_event", _on_spot_event)
        client.on("error", lambda reason, c=client: _on_ctrader_disconnected(c, str(reason)))

        reactor.callWhenRunning(client.start)
        logger.info("cTrader client scheduled to start")

    except Exception:
        logger.exception("Failed to initialize cTrader client")