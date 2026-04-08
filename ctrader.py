# ctrader.py
import logging
import time
from typing import Optional

from twisted.internet import reactor

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

_PRICE_SSE_THROTTLE_SECONDS = 0.5

_SYMBOL_ALIASES = {
    "US100": ["USTEC", "NAS100", "US100", "US100USD", "USTECH"],
    "US30": ["US30", "DJ30", "DJI30", "WALLSTREET"],
    "SPX500": ["US500", "SPX500", "SP500", "US500USD"],
    "GER40": ["GER40", "DE40", "DAX40"],
    "UK100": ["UK100", "FTSE100"],
    "JP225": ["JP225", "JPN225", "NI225"],
    "AUS200": ["AUS200", "AU200"],
}

_reconnect_attempt: int = 0
_reconnect_scheduled: bool = False
_reconnect_call = None

_subscribed_symbols: set[str] = set()
_stale_check_call = None
_last_price_sse_ts: dict[str, float] = {}


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
    now = time.time()

    payload = {
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "ts": now,
    }

    app_state.update_live_price(pair_norm, payload)

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


def _find_in_cache(pair: str):
    details = app_state.get_symbol_details(pair)
    if details:
        return details

    norm = _normalize_pair(pair)
    canon = _canonical_symbol_key(pair)

    # 1. alias-map
    for alias in _SYMBOL_ALIASES.get(norm, []):
        alias_details = app_state.get_symbol_details(alias)
        if alias_details:
            logger.info(f"Alias-матч символу '{norm}' -> '{alias}'")
            return alias_details

    # 2. canonical exact match
    for key, value in app_state.symbol_cache.items():
        if not isinstance(key, str):
            continue
        if _canonical_symbol_key(key) == canon:
            return value

    # 3. soft contains match
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
        available = list(app_state.symbol_cache.keys())[:20]
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
    global _reconnect_scheduled, _reconnect_attempt, _reconnect_call

    if _reconnect_scheduled:
        logger.debug("Reconnect вже заплановано, пропускаємо.")
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


def _do_reconnect(scheduled_attempt: Optional[int] = None) -> None:
    global _reconnect_scheduled, _subscribed_symbols, _last_price_sse_ts, _reconnect_call

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
    _subscribed_symbols = set()
    _last_price_sse_ts = {}

    if old_client:
        try:
            setattr(old_client, "_intentional_shutdown", True)
            old_client.stop()
        except Exception:
            logger.exception("Не вдалося зупинити старий cTrader client")

    try:
        start_ctrader_client()
    except Exception:
        logger.exception("Виняток під час reconnect, плануємо наступну спробу...")
        _schedule_reconnect()


def _on_ctrader_disconnected(client: SpotwareConnect, reason: str) -> None:
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


def _reconnect_attempt_reset() -> None:
    global _reconnect_attempt
    _reconnect_attempt = 0


def _on_symbols_loaded(raw) -> None:
    res = ProtoOASymbolsListRes()
    res.ParseFromString(raw.payload)

    app_state.clear_symbol_state()

    for s in res.symbol:
        app_state.symbol_cache[s.symbolName] = s
        app_state.symbol_id_map[s.symbolId] = s.symbolName
        app_state.client.symbol_map[s.symbolName] = s.symbolId

        norm = _normalize_pair(s.symbolName)
        canon = _canonical_symbol_key(s.symbolName)

        if norm not in app_state.symbol_cache:
            app_state.symbol_cache[norm] = s

        if canon and canon not in app_state.symbol_cache:
            app_state.symbol_cache[canon] = s

        if len(norm) >= 6:
            slash = f"{norm[:3]}/{norm[3:]}"
            if slash not in app_state.symbol_cache:
                app_state.symbol_cache[slash] = s

    app_state.all_symbol_names = sorted(
        {k for k in app_state.symbol_cache.keys() if isinstance(k, str)}
    )
    app_state.mark_symbols_loaded(True)

    logger.info(f"Символи завантажено: {len(res.symbol)}")
    sample = list(app_state.symbol_cache.keys())[:20]
    logger.info(f"Приклади назв символів у кеші: {sample}")

    start_price_subscriptions()


def on_ctrader_ready() -> None:
    logger.info("cTrader авторизований і готовий.")
    _cancel_reconnect()
    _reconnect_attempt_reset()

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

    _cancel_reconnect()

    old_client = app_state.client
    if old_client:
        try:
            setattr(old_client, "_intentional_shutdown", True)
            old_client.stop()
        except Exception:
            logger.exception("Не вдалося зупинити попередній cTrader client")

    client = SpotwareConnect(client_id, client_secret)
    setattr(client, "_intentional_shutdown", False)

    app_state.client = client
    app_state.mark_symbols_loaded(False)

    client.on("ready", on_ctrader_ready)
    client.on("spot_event", _on_spot_event)
    client.on("error", lambda reason, c=client: _on_ctrader_disconnected(c, str(reason)))

    reactor.callWhenRunning(client.start)