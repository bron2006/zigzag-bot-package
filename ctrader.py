# ctrader.py
import logging
import time
from twisted.internet import reactor
from state import app_state
import config
from config import STOCK_TICKERS, get_ct_client_id, get_ct_client_secret
from spotware_connect import SpotwareConnect
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASymbolsListRes, ProtoOASubscribeSpotsReq, ProtoOASpotEvent
)
import scanner
from price_utils import resolve_price_divisor
from errors import safe_twisted, SpotEventError
from notifier import notify_admin

logger = logging.getLogger("ctrader")

# ---------------------------------------------------------------------------
# Константи
# ---------------------------------------------------------------------------

_RECONNECT_BASE_DELAY = 5
_RECONNECT_MAX_DELAY  = 120
_RECONNECT_MAX_TRIES  = 10
_STALE_THRESHOLD      = 300
_STALE_CHECK_INTERVAL = 60

# ---------------------------------------------------------------------------
# Внутрішній стан
# ---------------------------------------------------------------------------

_reconnect_attempt   : int  = 0
_reconnect_scheduled : bool = False
_subscribed_symbols  : set  = set()


# ---------------------------------------------------------------------------
# Spot event handler
# ВИПРАВЛЕНО: підписка тепер на "spot_event" — саме такий івент
# емітує SpotwareConnect після нашого виправлення.
# ---------------------------------------------------------------------------

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

    details = app_state.symbol_cache.get(name)
    if not details:
        raise SpotEventError(
            f"Немає кешу для symbolId={event.symbolId}", symbol_id=event.symbolId
        )

    div = resolve_price_divisor(details)
    bid = event.bid / div if event.HasField("bid") else None
    ask = event.ask / div if event.HasField("ask") else None
    mid = (bid + ask) / 2.0 if bid and ask else None

    app_state.live_prices[name] = {
        "bid": bid, "ask": ask, "mid": mid, "ts": time.time()
    }


# ---------------------------------------------------------------------------
# Підписка на ціни
# ВИПРАВЛЕНО: пошук символу у кеші — пробуємо кілька варіантів назви
# (BTCUSD, BTC/USD, btcusd) щоб знайти незалежно від формату.
# ---------------------------------------------------------------------------

def _find_in_cache(pair: str):
    """
    Шукає символ у symbol_cache незалежно від формату назви.
    Пробує: BTCUSD → BTC/USD → btcusd → і навпаки.
    """
    pair_no_slash  = pair.replace("/", "")
    pair_with_slash = None
    # Спробуємо вставити "/" після 3 символів (EURUSD → EUR/USD)
    if len(pair_no_slash) >= 6:
        pair_with_slash = pair_no_slash[:3] + "/" + pair_no_slash[3:]

    for variant in [pair_no_slash, pair, pair_with_slash, pair.upper(), pair_no_slash.upper()]:
        if variant and variant in app_state.symbol_cache:
            return app_state.symbol_cache[variant]
    return None


def start_price_subscriptions() -> None:
    """
    Збирає всі активи з поточного стану сканерів і підписується
    лише на нові котирування. Безпечно викликати повторно.
    """
    global _subscribed_symbols

    if not app_state.SYMBOLS_LOADED:
        logger.warning("start_price_subscriptions: символи ще не завантажені, відкладаємо на 5s")
        try:
            reactor.callLater(5, start_price_subscriptions)
        except Exception:
            logger.exception("Не вдалося відкласти start_price_subscriptions")
        return

    if not app_state.client or not app_state.client._client.account_id:
        logger.warning("start_price_subscriptions: client не готовий, відкладаємо на 5s")
        try:
            reactor.callLater(5, start_price_subscriptions)
        except Exception:
            logger.exception("Не вдалося відкласти start_price_subscriptions")
        return

    try:
        scanner_assets = scanner._collect_assets_to_scan()
    except Exception:
        logger.exception("Не вдалося зібрати активи для підписки")
        scanner_assets = []

    all_assets = sorted(set(scanner_assets + STOCK_TICKERS))
    new_assets = [p for p in all_assets if p.replace("/", "") not in _subscribed_symbols]

    if not new_assets:
        logger.info("start_price_subscriptions: всі активи вже підписані.")
        return

    logger.info(
        f"start_price_subscriptions: підписуємо {len(new_assets)} нових активів "
        f"(вже підписано: {len(_subscribed_symbols)})"
    )

    for i, pair in enumerate(new_assets):
        def sub(p=pair):
            pair_norm = p.replace("/", "")
            details   = _find_in_cache(p)   # ← ВИПРАВЛЕНО: використовуємо розумний пошук
            if details:
                try:
                    req = ProtoOASubscribeSpotsReq(
                        ctidTraderAccountId=app_state.client._client.account_id,
                        symbolId=[details.symbolId]
                    )
                    app_state.client.send(req)
                    _subscribed_symbols.add(pair_norm)
                    logger.debug(f"Підписано: {pair_norm} (symbolId={details.symbolId})")
                except Exception:
                    logger.exception(f"Помилка підписки на {pair_norm}")
            else:
                # Логуємо доступні символи щоб допомогти відлагодженню
                available = [k for k in list(app_state.symbol_cache.keys())[:10]]
                logger.warning(
                    f"Символ '{pair_norm}' не знайдено в кеші. "
                    f"Приклади доступних: {available}"
                )
        try:
            reactor.callLater(i * 0.1, sub)
        except Exception:
            logger.exception(f"Не вдалося запланувати підписку для {pair}")


# ---------------------------------------------------------------------------
# Reconnect з exponential backoff
# ---------------------------------------------------------------------------

def _schedule_reconnect() -> None:
    global _reconnect_scheduled, _reconnect_attempt

    if _reconnect_scheduled:
        logger.debug("Reconnect вже заплановано, пропускаємо.")
        return

    if _reconnect_attempt >= _RECONNECT_MAX_TRIES:
        msg = f"🛑 cTrader: вичерпано {_RECONNECT_MAX_TRIES} спроб реконнекту. Потрібне ручне втручання."
        logger.critical(msg)
        notify_admin(msg, alert_key="ctrader_reconnect_exhausted")
        return

    delay = min(_RECONNECT_BASE_DELAY * (2 ** _reconnect_attempt), _RECONNECT_MAX_DELAY)
    _reconnect_attempt  += 1
    _reconnect_scheduled = True
    logger.warning(f"Reconnect через {delay}s (спроба {_reconnect_attempt}/{_RECONNECT_MAX_TRIES})")

    try:
        reactor.callLater(delay, _do_reconnect)
    except Exception:
        logger.exception("Не вдалося запланувати reconnect")
        _reconnect_scheduled = False


def _do_reconnect() -> None:
    global _reconnect_scheduled, _subscribed_symbols

    _reconnect_scheduled = False
    logger.info(f"Виконую reconnect #{_reconnect_attempt}...")

    app_state.SYMBOLS_LOADED = False
    app_state.symbol_cache.clear()
    app_state.symbol_id_map.clear()
    _subscribed_symbols = set()

    try:
        start_ctrader_client()
    except Exception:
        logger.exception("Виняток під час reconnect, плануємо наступну спробу...")
        _schedule_reconnect()


def _on_ctrader_disconnected(reason: str) -> None:
    msg = f"⚡ cTrader відключився: {reason}"
    logger.error(msg)
    notify_admin(msg, alert_key="ctrader_disconnected")
    app_state.SYMBOLS_LOADED = False
    _schedule_reconnect()


# ---------------------------------------------------------------------------
# Перевірка застарілих цін
# ---------------------------------------------------------------------------

def _check_stale_prices() -> None:
    if not app_state.SYMBOLS_LOADED:
        _schedule_stale_check()
        return

    prices = app_state.live_prices
    if not prices:
        if _subscribed_symbols:
            logger.warning(
                f"Є {len(_subscribed_symbols)} підписок але live_prices порожній — "
                "можливо з'єднання мертве"
            )
        _schedule_stale_check()
        return

    now         = time.time()
    stale       = [n for n, d in prices.items() if (now - d.get("ts", 0)) > _STALE_THRESHOLD]
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

    _schedule_stale_check()


def _schedule_stale_check() -> None:
    try:
        reactor.callLater(_STALE_CHECK_INTERVAL, _check_stale_prices)
    except Exception:
        logger.exception("Не вдалося запланувати перевірку stale цін")


# ---------------------------------------------------------------------------
# Callbacks від SpotwareConnect
# ---------------------------------------------------------------------------

def _on_symbols_loaded(raw) -> None:
    res = ProtoOASymbolsListRes()
    res.ParseFromString(raw.payload)
    for s in res.symbol:
        app_state.symbol_cache[s.symbolName] = s
        app_state.symbol_id_map[s.symbolId]  = s.symbolName
    app_state.SYMBOLS_LOADED = True
    logger.info(f"Символи завантажено: {len(app_state.symbol_cache)}")

    # Логуємо кілька прикладів щоб бачити формат назв у кеші
    sample = list(app_state.symbol_cache.keys())[:15]
    logger.info(f"Приклади назв символів у кеші: {sample}")

    start_price_subscriptions()


def on_ctrader_ready() -> None:
    global _reconnect_attempt
    logger.info("cTrader авторизований і готовий.")
    _reconnect_attempt = 0
    reactor.callLater(_STALE_CHECK_INTERVAL, _check_stale_prices)
    app_state.client.get_all_symbols().addCallback(_on_symbols_loaded)


# ---------------------------------------------------------------------------
# Точка входу
# ---------------------------------------------------------------------------

def start_ctrader_client() -> None:
    client_id     = get_ct_client_id()
    client_secret = get_ct_client_secret()

    if not client_id or not client_secret:
        from errors import ConfigError
        raise ConfigError("CTRADER_CLIENT_ID або CTRADER_CLIENT_SECRET не налаштовані")

    client = SpotwareConnect(client_id, client_secret)
    app_state.client = client
    client.on("ready",      on_ctrader_ready)
    client.on("spot_event", _on_spot_event)   # ← тепер це працює після виправлення emit
    client.on("error",      lambda reason: _on_ctrader_disconnected(str(reason)))
    reactor.callWhenRunning(client.start)
