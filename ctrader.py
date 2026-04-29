# ctrader.py
import logging
import re
import time

from twisted.internet import reactor

from config import (
    COMMODITIES,
    CRYPTO_PAIRS,
    FOREX_SESSIONS,
    STOCK_TICKERS,
    broker_symbol_key,
    get_ct_client_id,
    get_ct_client_secret,
)
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

_reconnect_attempt = 0
_reconnect_scheduled = False
_SUBSCRIBE_BATCH_SIZE = 50
_SUBSCRIBE_BATCH_DELAY = 1.0
_PRICE_FRESH_SECONDS = 120
_PRICE_START_GRACE_SECONDS = 60
_PRICE_RECOVERY_COOLDOWN_SECONDS = 120
_PRICE_RESUBSCRIBE_ATTEMPTS_BEFORE_RECONNECT = 1

_symbols_loaded_at = 0.0
_last_subscription_request_ts = 0.0
_last_price_recovery_ts = 0.0
_price_recovery_attempts = 0
_last_spot_event_ts = 0.0


def _compact_symbol(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _display_symbol_name(symbol) -> str:
    return getattr(symbol, "symbolName", "") or str(getattr(symbol, "symbolId", "unknown"))


def _requested_pair_key(pair: str) -> str:
    return _compact_symbol(pair)


def _broker_pair_keys(pair: str) -> list[str]:
    requested = _requested_pair_key(pair)
    broker_key = broker_symbol_key(pair)
    keys = []

    for key in (requested, broker_key):
        if key and key not in keys:
            keys.append(key)

    return keys


def _symbol_cache_keys(symbol) -> set[str]:
    raw_name = _display_symbol_name(symbol)
    no_slash = raw_name.replace("/", "").upper().strip()
    compact = _compact_symbol(raw_name)
    return {key for key in (no_slash, compact) if key}


def _unique_symbols_from_cache() -> list:
    seen = set()
    symbols = []

    for symbol in app_state.symbol_cache.values():
        symbol_id = getattr(symbol, "symbolId", None)
        if symbol_id in seen:
            continue
        seen.add(symbol_id)
        symbols.append(symbol)

    return symbols


def _collect_configured_assets() -> list[str]:
    assets = []

    for pairs in FOREX_SESSIONS.values():
        assets.extend(pairs)

    assets.extend(CRYPTO_PAIRS)
    assets.extend(COMMODITIES)
    assets.extend(STOCK_TICKERS)


    seen = set()
    normalized = []

    for asset in assets:
        key = _requested_pair_key(asset)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)

    return normalized


def _resolve_broker_symbol(pair: str):
    requested_keys = _broker_pair_keys(pair)
    if not requested_keys:
        return None

    for key in requested_keys:
        exact = app_state.symbol_cache.get(key)
        if exact is not None:
            return exact

    candidates = []
    for symbol in _unique_symbols_from_cache():
        keys = _symbol_cache_keys(symbol)
        if any(requested in keys for requested in requested_keys):
            return symbol

        for key in keys:
            for requested in requested_keys:
                if key.startswith(requested):
                    candidates.append((len(key), _display_symbol_name(symbol), symbol))
                    break

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    return None


def start_ctrader_client():
    global _reconnect_scheduled

    _reconnect_scheduled = False

    try:
        client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        app_state.client = client

        client.on("ready", on_ctrader_ready)
        client.on("spot_event", _on_spot_event)
        client.on("error", _handle_error)

        client.start()
        logger.info("cTrader client started")
        return client

    except Exception:
        logger.exception("Failed to initialize cTrader client")
        notify_admin("cTrader client не стартував", alert_key="ctrader_start_failed")
        return None


def _handle_error(reason):
    logger.error("cTrader error handler: %s", reason)

    if reason in {"RATE_LIMIT_BLOCKED", "REQUEST_FREQUENCY_EXCEEDED"}:
        try:
            from scanner import pause_scanning_for_rate_limit

            pause_scanning_for_rate_limit(reason)
        except Exception:
            logger.exception("Failed to pause scanner after rate limit event")

    delay = 180 if reason in {"RATE_LIMIT_BLOCKED", "REQUEST_FREQUENCY_EXCEEDED"} else 30
    _schedule_reconnect(delay)


def _schedule_reconnect(delay):
    global _reconnect_scheduled, _reconnect_attempt

    if _reconnect_scheduled:
        return

    _reconnect_scheduled = True
    _reconnect_attempt += 1

    logger.warning("Reconnecting cTrader in %ss (attempt %s)", delay, _reconnect_attempt)
    reactor.callLater(delay, _do_reconnect)


def _do_reconnect():
    global _last_spot_event_ts

    if app_state.client:
        try:
            app_state.client.stop()
        except Exception:
            logger.exception("Failed to stop cTrader client before reconnect")

    app_state.clear_symbol_state()
    app_state.clear_live_prices()
    _last_spot_event_ts = 0.0
    start_ctrader_client()


def on_ctrader_ready():
    global _reconnect_attempt

    _reconnect_attempt = 0
    logger.info("cTrader account authorized. Loading symbols...")
    reactor.callLater(1.0, _request_symbols)


def _request_symbols():
    if not app_state.client:
        logger.warning("Cannot request symbols: app_state.client is empty")
        return

    logger.info("Запитую список символів cTrader...")
    d = app_state.client.get_all_symbols()
    if d is None:
        logger.error("Запит списку символів cTrader не повернув Deferred.")
        _schedule_reconnect(30)
        return

    d.addTimeout(30, reactor)
    d.addCallbacks(_on_symbols_loaded, _on_symbols_error)


def _on_symbols_error(failure):
    logger.error("Symbols error: %s", failure.getErrorMessage())
    _schedule_reconnect(30)
    return None


def _on_symbols_loaded(msg):
    global _symbols_loaded_at

    try:
        res = ProtoOASymbolsListRes()
        res.ParseFromString(msg.payload)

        symbol_cache = {}
        symbol_id_map = {}
        all_names = []

        for symbol in res.symbol:
            display_name = _display_symbol_name(symbol)
            keys = _symbol_cache_keys(symbol)

            for key in keys:
                symbol_cache[key] = symbol

            canonical = _compact_symbol(display_name)
            if canonical:
                symbol_id_map[symbol.symbolId] = canonical
                all_names.append(canonical)

        with app_state._state_lock:
            app_state.symbol_cache = symbol_cache
            app_state.symbol_id_map = symbol_id_map
            app_state.all_symbol_names = sorted(all_names)
            app_state.SYMBOLS_LOADED = True

        _symbols_loaded_at = time.time()

        logger.info(
            "Завантажено %s символів cTrader (%s ключів пошуку). Пари готові.",
            len(res.symbol),
            len(symbol_cache),
        )
        start_price_subscriptions()

    except Exception:
        logger.exception("Error parsing symbols")
        _schedule_reconnect(30)


def start_price_subscriptions():
    global _last_subscription_request_ts

    if not app_state.SYMBOLS_LOADED:
        logger.info("Символи ще не завантажені. Підписку на ціни пропущено.")
        return

    assets = _collect_configured_assets()

    if not assets:
        logger.info("Немає активів для підписки на ціни.")
        return

    resolved = []
    missing = []

    for pair in assets:
        symbol = _resolve_broker_symbol(pair)
        if symbol is None:
            logger.warning("Не зміг підписатися на пару %s, бо її немає в списку брокера", pair)
            missing.append(pair)
            continue

        resolved.append((pair, symbol))

    if not resolved:
        logger.warning(
            "Не знайдено жодного символу брокера для %s налаштованих активів.",
            len(assets),
        )
        return

    with app_state._state_lock:
        for pair, symbol in resolved:
            app_state.symbol_cache[pair] = symbol
            app_state.symbol_id_map[symbol.symbolId] = pair

    logger.info(
        "Підписуюся на ціни: знайдено %s з %s активів, не знайдено %s.",
        len(resolved),
        len(assets),
        len(missing),
    )

    _last_subscription_request_ts = time.time()

    for i in range(0, len(resolved), _SUBSCRIBE_BATCH_SIZE):
        batch = resolved[i : i + _SUBSCRIBE_BATCH_SIZE]
        reactor.callLater(
            (i // _SUBSCRIBE_BATCH_SIZE) * _SUBSCRIBE_BATCH_DELAY,
            _subscribe_symbol_batch,
            batch,
        )


def _subscribe_symbol_batch(batch):
    if not app_state.client:
        logger.warning("cTrader client не готовий. Батч підписки пропущено.")
        return

    if not batch:
        return

    account_id = getattr(app_state.client._client, "account_id", None)
    if not account_id:
        logger.warning("Акаунт cTrader не готовий. Не можу підписатися на ціни.")
        return

    symbol_ids = []
    pairs = []

    for pair, symbol in batch:
        symbol_id = getattr(symbol, "symbolId", None)
        if symbol_id is None:
            logger.warning("Не зміг підписатися на пару %s, бо її немає в списку брокера", pair)
            continue

        symbol_ids.append(symbol_id)
        pairs.append(f"{pair}->{_display_symbol_name(symbol)}")

    if not symbol_ids:
        return

    try:
        req = ProtoOASubscribeSpotsReq(
            ctidTraderAccountId=account_id,
            symbolId=symbol_ids,
        )
        app_state.client.send(req, responseTimeoutInSeconds=10)
        logger.info("Підписка на ціни надіслана для %s символів: %s", len(symbol_ids), ", ".join(pairs))

    except Exception:
        logger.exception("Не вдалося надіслати батч підписки на ціни: %s", ", ".join(pairs))


def _price_stream_snapshot() -> dict:
    now = time.time()
    assets = _collect_configured_assets()
    prices = app_state.get_live_prices_snapshot()

    fresh = []
    stale = {}
    missing = []

    for pair in assets:
        price = prices.get(pair)
        if not price:
            missing.append(pair)
            continue

        age = max(0, int(now - price.get("ts", 0)))
        if age <= _PRICE_FRESH_SECONDS:
            fresh.append(pair)
        else:
            stale[pair] = age

    return {
        "configured": len(assets),
        "live": len(prices),
        "fresh": len(fresh),
        "missing": missing,
        "stale": stale,
        "last_spot_age": int(now - _last_spot_event_ts) if _last_spot_event_ts else None,
        "last_subscription_age": (
            int(now - _last_subscription_request_ts)
            if _last_subscription_request_ts
            else None
        ),
        "recovery_attempts": _price_recovery_attempts,
    }


def get_price_stream_status() -> dict:
    snapshot = _price_stream_snapshot()
    ok = bool(app_state.SYMBOLS_LOADED and snapshot["fresh"] > 0)

    if not app_state.SYMBOLS_LOADED:
        label = "символи ще не завантажені"
    elif snapshot["fresh"] > 0:
        label = f"є свіжі ціни: {snapshot['fresh']} з {snapshot['configured']}"
    elif snapshot["live"] > 0:
        label = "потік цін давно не оновлювався"
    else:
        label = "ціни ще не отримані"

    return {
        "ok": ok,
        "label": label,
        **snapshot,
    }


def monitor_price_stream_health():
    global _last_price_recovery_ts, _price_recovery_attempts

    if _reconnect_scheduled:
        return

    if not app_state.SYMBOLS_LOADED:
        return

    client = app_state.client
    account_id = getattr(getattr(client, "_client", None), "account_id", None)
    if not client or not account_id:
        return

    assets = _collect_configured_assets()
    if not assets:
        return

    now = time.time()
    snapshot = _price_stream_snapshot()
    last_start = max(_symbols_loaded_at, _last_subscription_request_ts)

    if snapshot["fresh"] > 0:
        if _price_recovery_attempts:
            logger.info("Потік цін відновився. Свіжих цін: %s.", snapshot["fresh"])
        _price_recovery_attempts = 0
        return

    if last_start and now - last_start < _PRICE_START_GRACE_SECONDS:
        return

    if now - _last_price_recovery_ts < _PRICE_RECOVERY_COOLDOWN_SECONDS:
        return

    _last_price_recovery_ts = now
    _price_recovery_attempts += 1

    logger.warning(
        "Контроль цін: немає свіжих цін. Активів=%s, live=%s, застарілих=%s, пропущених=%s, спроба=%s.",
        snapshot["configured"],
        snapshot["live"],
        len(snapshot["stale"]),
        len(snapshot["missing"]),
        _price_recovery_attempts,
    )

    if _price_recovery_attempts <= _PRICE_RESUBSCRIBE_ATTEMPTS_BEFORE_RECONNECT:
        logger.warning("Контроль цін: повторно надсилаю підписку на ціни.")
        start_price_subscriptions()
        return

    logger.warning("Контроль цін: повторна підписка не допомогла, перезапускаю cTrader.")
    _price_recovery_attempts = 0
    _schedule_reconnect(5)


def _value_from_event(event: ProtoOASpotEvent, field: str, divisor: float):
    if event.HasField(field):
        return getattr(event, field) / divisor
    return None


def _on_spot_event(event: ProtoOASpotEvent):
    global _last_spot_event_ts

    if not (event.HasField("bid") or event.HasField("ask")):
        return

    name = app_state.symbol_id_map.get(event.symbolId)
    if not name:
        return

    symbol = app_state.symbol_cache.get(name)
    if symbol is None:
        return

    try:
        divisor = resolve_price_divisor(symbol)
        bid = _value_from_event(event, "bid", divisor)
        ask = _value_from_event(event, "ask", divisor)

        if bid is not None and ask is not None:
            mid = (bid + ask) / 2
        else:
            mid = bid if bid is not None else ask

        ts = time.time()
        _last_spot_event_ts = ts
        payload = {
            "type": "price",
            "pair": name,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "ts": ts,
        }

        app_state.update_live_price(name, payload)
        app_state.publish_price_sse(payload)

    except Exception:
        logger.exception("Failed to process spot event for symbolId=%s", event.symbolId)
