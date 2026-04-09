# ctrader.py
import logging
import time
from twisted.internet import reactor

import config
import scanner
from config import STOCK_TICKERS, get_ct_client_id, get_ct_client_secret
from spotware_connect import SpotwareConnect
from state import app_state
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASymbolsListRes,
    ProtoOASubscribeSpotsReq,
    ProtoOASpotEvent,
)

logger = logging.getLogger("ctrader")

_RECONNECT_BASE_DELAY = 5
_RECONNECT_MAX_DELAY = 120
_RECONNECT_MAX_TRIES = 10

_STALE_THRESHOLD = 300
_STALE_CHECK_INTERVAL = 60
_BOOTSTRAP_GRACE_SECONDS = 180

_reconnect_attempt = 0
_reconnect_scheduled = False
_reconnect_call = None

_stale_check_call = None
_connection_ready_ts = 0.0
_last_any_spot_ts = 0.0
_last_resubscribe_ts = 0.0
_subscribed_symbols = set()

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


def _normalize_pair(pair: str) -> str:
    return pair.replace("/", "").upper().strip()


def _canonical_symbol_key(pair: str) -> str:
    return "".join(ch for ch in _normalize_pair(pair) if ch.isalnum())


def _resolve_price_divisor(symbol_name: str) -> float:
    upper = _normalize_pair(symbol_name)

    index_aliases = {
        "US100", "USTEC", "NAS100",
        "US30", "DJ30", "DJI30",
        "US500", "SPX500", "SP500",
        "DE30", "DE40", "GER40", "DAX40",
        "UK100", "FTSE100",
        "JP225", "JPN225", "NI225",
        "AUS200", "AU200",
    }

    if upper in index_aliases:
        return 10.0

    if upper.startswith("XAU") or upper.startswith("XAG"):
        return 100.0

    if upper.startswith("BTC") or upper.startswith("ETH") or upper.startswith("LTC") or upper.startswith("XRP") or upper.startswith("ADA") or upper.startswith("BCH"):
        return 100.0

    return 100000.0


def _cancel_reconnect():
    global _reconnect_call, _reconnect_scheduled

    if _reconnect_call and _reconnect_call.active():
        try:
            _reconnect_call.cancel()
            logger.info("Скасовано запланований reconnect.")
        except Exception:
            logger.exception("Не вдалося скасувати reconnect call")

    _reconnect_call = None
    _reconnect_scheduled = False


def _cancel_stale_check():
    global _stale_check_call

    if _stale_check_call and _stale_check_call.active():
        try:
            _stale_check_call.cancel()
        except Exception:
            logger.exception("Не вдалося скасувати stale check")
    _stale_check_call = None


def _schedule_stale_check():
    global _stale_check_call

    if _stale_check_call and _stale_check_call.active():
        return

    _stale_check_call = reactor.callLater(_STALE_CHECK_INTERVAL, _check_stale_prices)


def _reset_runtime_state():
    global _connection_ready_ts, _last_any_spot_ts, _last_resubscribe_ts, _subscribed_symbols

    _connection_ready_ts = 0.0
    _last_any_spot_ts = 0.0
    _last_resubscribe_ts = 0.0
    _subscribed_symbols = set()

    app_state.live_prices.clear()


def _reconnect_attempt_reset():
    global _reconnect_attempt
    _reconnect_attempt = 0


def _find_in_cache(pair: str):
    norm = _normalize_pair(pair)

    # 1. Прямий збіг
    direct = app_state.symbol_cache.get(norm)
    if direct:
        return direct

    # 2. Alias map
    for alias in _SYMBOL_ALIASES.get(norm, []):
        alias_norm = _normalize_pair(alias)
        alias_direct = app_state.symbol_cache.get(alias_norm)
        if alias_direct:
            logger.info(f"Alias-матч символу '{norm}' -> '{alias_norm}'")
            return alias_direct

    # 3. Canonical fallback
    canon = _canonical_symbol_key(norm)
    for key, value in app_state.symbol_cache.items():
        if _canonical_symbol_key(key) == canon:
            return value

    return None


def _on_spot_event(event: ProtoOASpotEvent):
    global _last_any_spot_ts

    try:
        if not (event.HasField("bid") or event.HasField("ask")):
            return

        symbol_name = app_state.symbol_id_map.get(event.symbolId)
        if not symbol_name:
            return

        divisor = _resolve_price_divisor(symbol_name)

        bid = event.bid / divisor if event.HasField("bid") else None
        ask = event.ask / divisor if event.HasField("ask") else None
        mid = (bid + ask) / 2.0 if (bid is not None and ask is not None) else bid or ask

        _last_any_spot_ts = time.time()

        app_state.live_prices[symbol_name] = {
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "ts": _last_any_spot_ts,
        }

        # Якщо у state є новий метод для price SSE — використовуємо
        publish_price = getattr(app_state, "publish_price_sse", None)
        if callable(publish_price):
            publish_price({
                "type": "price",
                "pair": symbol_name,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "ts": _last_any_spot_ts,
            })

        logger.debug(f"Tick {symbol_name}: Mid Price = {mid}")

    except Exception:
        logger.exception("Error processing spot event")


def start_price_subscriptions(force_resubscribe: bool = False):
    global _subscribed_symbols

    if config.APP_MODE == "light":
        logger.info("APP_MODE is 'light'. Skipping automatic price subscriptions at startup.")
        return

    if not app_state.client or not getattr(app_state.client._client, "account_id", None):
        logger.warning("Client is not ready for subscriptions yet.")
        return

    logger.info("Starting price subscriptions for all scannable assets...")

    assets_to_subscribe = scanner._collect_assets_to_scan()
    assets_to_subscribe.extend(STOCK_TICKERS)
    assets_to_subscribe = sorted(list(set(_normalize_pair(p) for p in assets_to_subscribe)))

    if not force_resubscribe:
        assets_to_subscribe = [p for p in assets_to_subscribe if p not in _subscribed_symbols]
    else:
        logger.info("Force resubscribe enabled — перепідписуємо всі активи.")

    if not assets_to_subscribe:
        logger.info("start_price_subscriptions: всі активи вже підписані.")
        return

    logger.info(
        f"start_price_subscriptions: підписуємо {len(assets_to_subscribe)} активів "
        f"(вже підписано: {len(_subscribed_symbols)})"
    )

    for i, pair in enumerate(assets_to_subscribe):
        reactor.callLater(i * 0.2, _subscribe_pair, pair)


def _subscribe_pair(pair_norm: str):
    try:
        symbol_details = _find_in_cache(pair_norm)
        if not symbol_details:
            sample = list(app_state.symbol_cache.keys())[:20]
            logger.warning(f"Cannot subscribe to {pair_norm}: not found in symbol cache. Examples: {sample}")
            return

        req = ProtoOASubscribeSpotsReq(
            ctidTraderAccountId=app_state.client._client.account_id,
            symbolId=[symbol_details.symbolId]
        )

        d = app_state.client.send(req, timeout=20)
        d.addCallbacks(
            lambda _, p=pair_norm: logger.info(f"✅ Subscribed to price stream for {p}"),
            lambda err, p=pair_norm: logger.error(
                f"❌ Failed to subscribe to {p}: "
                f"{err.getErrorMessage() if hasattr(err, 'getErrorMessage') else err}"
            )
        )

        _subscribed_symbols.add(pair_norm)

    except Exception:
        logger.exception(f"Error during subscription schedule for {pair_norm}")


def _on_symbols_loaded(raw_message):
    global _connection_ready_ts

    try:
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)

        app_state.symbol_cache = {s.symbolName.replace("/", ""): s for s in res.symbol}
        app_state.symbol_id_map = {s.symbolId: s.symbolName.replace("/", "") for s in res.symbol}
        app_state.all_symbol_names = [s.symbolName for s in res.symbol]
        app_state.SYMBOLS_LOADED = True

        _connection_ready_ts = time.time()

        logger.info(f"Loaded {len(app_state.symbol_cache)} symbols from cTrader.")
        sample = list(app_state.symbol_cache.keys())[:20]
        logger.info(f"Приклади назв символів у кеші: {sample}")

        start_price_subscriptions()

    except Exception:
        logger.exception("on_symbols_loaded error")


def _on_symbols_error(failure):
    msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
    logger.error(f"Failed to load symbols: {msg}")
    app_state.SYMBOLS_LOADED = False


def _schedule_reconnect():
    global _reconnect_attempt, _reconnect_scheduled, _reconnect_call

    if _reconnect_scheduled:
        logger.debug("Reconnect already scheduled, skipping.")
        return

    if _reconnect_attempt >= _RECONNECT_MAX_TRIES:
        msg = f"🛑 cTrader: вичерпано {_RECONNECT_MAX_TRIES} спроб реконнекту. Потрібне ручне втручання."
        logger.critical(msg)
        notify_admin(msg, alert_key="ctrader_reconnect_exhausted")
        return

    delay = min(_RECONNECT_BASE_DELAY * (2 ** _reconnect_attempt), _RECONNECT_MAX_DELAY)
    _reconnect_attempt += 1
    _reconnect_scheduled = True

    logger.warning(f"Reconnect через {delay}s (спроба {_reconnect_attempt}/{_RECONNECT_MAX_TRIES})")
    _reconnect_call = reactor.callLater(delay, _do_reconnect)


def _do_reconnect():
    global _reconnect_scheduled, _reconnect_call

    _reconnect_call = None
    _reconnect_scheduled = False

    logger.info(f"Виконую reconnect #{_reconnect_attempt}...")

    old_client = app_state.client
    _cancel_stale_check()
    _reset_runtime_state()

    if old_client:
        try:
            setattr(old_client, "_intentional_shutdown", True)
            old_client.stop()
        except Exception:
            logger.exception("Не вдалося зупинити старий cTrader client")

    app_state.client = None
    app_state.SYMBOLS_LOADED = False

    start_ctrader_client()


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
    _schedule_reconnect()


def _check_stale_prices():
    global _last_resubscribe_ts

    _schedule_stale_check()

    if not app_state.SYMBOLS_LOADED:
        return

    now = time.time()
    prices = app_state.live_prices

    if _connection_ready_ts and (now - _connection_ready_ts) < _BOOTSTRAP_GRACE_SECONDS:
        logger.info(
            "Stale check: bootstrap grace active (%ss/%ss)",
            int(now - _connection_ready_ts),
            _BOOTSTRAP_GRACE_SECONDS,
        )
        return

    if not prices:
        logger.warning("Немає live_prices після grace period — пробую force resubscribe")
        if (now - _last_resubscribe_ts) > 90:
            _last_resubscribe_ts = now
            reactor.callLater(0, start_price_subscriptions, True)
        return

    stale = [n for n, d in prices.items() if (now - d.get("ts", 0)) > _STALE_THRESHOLD]
    fresh_count = len(prices) - len(stale)

    if fresh_count > 0:
        if stale:
            logger.warning(f"Застарілі: {', '.join(stale[:10])}")
        return

    if _last_any_spot_ts and (now - _last_any_spot_ts) < _STALE_THRESHOLD:
        logger.info("Spot events були нещодавно — reconnect по stale поки не роблю")
        return

    logger.warning("Усі ціни stale — пробую force resubscribe перед reconnect")
    if (now - _last_resubscribe_ts) > 90:
        _last_resubscribe_ts = now
        reactor.callLater(0, start_price_subscriptions, True)
        return

    logger.error(f"⏰ cTrader: всі {len(prices)} цін застаріли (>{_STALE_THRESHOLD}s). Запускаю reconnect.")
    _schedule_reconnect()


def on_ctrader_ready():
    logger.info("cTrader client ready — requesting symbol list")

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
        client.on("ready", on_ctrader_ready)
        client.on("spot_event", _on_spot_event)
        client.on("error", lambda reason, c=client: _on_ctrader_disconnected(c, str(reason)))

        reactor.callWhenRunning(client.start)
        logger.info("cTrader client scheduled to start")
    except Exception:
        logger.exception("Failed to initialize cTrader client")