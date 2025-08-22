# main.py
import os
import json
import logging
import sqlite3
from typing import Dict, Any, List, Optional

from klein import Klein
from twisted.internet import reactor, defer
from twisted.web.server import Site
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from spotware_connect import SpotwareConnect
import state
from config import TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret, DB_NAME
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

# Необов'язковий модуль аналізу: якщо є — використаємо, якщо ні — повернемо просту відповідь
try:
    import analysis  # очікується функція get_signal(client, pair) -> Deferred -> dict
    HAS_ANALYSIS = True
except Exception:
    HAS_ANALYSIS = False

# MTA mock (асинхронний)
try:
    from mta_analysis import get_mta_signal
except Exception:
    def get_mta_signal(client, pair: str):
        d = defer.Deferred()
        reactor.callLater(0.05, lambda: d.callback([
            {"tf": "15min", "signal": "NEUTRAL"},
            {"tf": "1h", "signal": "NEUTRAL"},
            {"tf": "4h", "signal": "NEUTRAL"},
            {"tf": "1day", "signal": "NEUTRAL"},
        ]))
        return d

# DB helpers
def fetch_signal_history(pair: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT timestamp, pair, price, bull_percentage
                FROM signal_history
                WHERE pair = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (pair, limit),
            )
            for ts, pr, price, bull in c.fetchall():
                rows.append({
                    "timestamp": ts,
                    "pair": pr,
                    "price": price,
                    "bull_percentage": bull,
                    "signal_type": "BUY" if (bull or 0) >= 50 else "SELL",
                })
    except Exception as e:
        logger.error(f"DB fetch history error: {e}")
    return rows

def upsert_watchlist(user_id: str, pair: str, is_add: bool) -> bool:
    try:
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS user_watchlist (user_id TEXT, pair TEXT, PRIMARY KEY(user_id, pair))")
            if is_add:
                c.execute("INSERT OR IGNORE INTO user_watchlist (user_id, pair) VALUES (?,?)", (user_id, pair))
            else:
                c.execute("DELETE FROM user_watchlist WHERE user_id=? AND pair=?", (user_id, pair))
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"DB watchlist error: {e}")
        return False

def get_watchlist(user_id: str) -> List[str]:
    try:
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS user_watchlist (user_id TEXT, pair TEXT, PRIMARY KEY(user_id, pair))")
            c.execute("SELECT pair FROM user_watchlist WHERE user_id=?", (user_id,))
            return [r[0] for r in c.fetchall()]
    except Exception as e:
        logger.error(f"DB get_watchlist error: {e}")
        return []

# ------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Klein()

WEB_DIR = os.path.join(os.getcwd(), "webapp")
INDEX_PATH = os.path.join(WEB_DIR, "index.html")
CSS_PATH = os.path.join(WEB_DIR, "style.css")
JS_PATH = os.path.join(WEB_DIR, "script.js")

def _read_file_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Static file read error ({path}): {e}")
        return None

def _ok_json(request, payload: Dict[str, Any]):
    request.setHeader(b"content-type", b"application/json; charset=utf-8")
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

def _bad_json(request, msg: str, status: int = 400):
    request.setResponseCode(status)
    request.setHeader(b"content-type", b"application/json; charset=utf-8")
    return json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")

def _get_user_id_from_initdata(init_data: str) -> str:
    # Для простоти: якщо є initData — використовуємо як user_id, інакше "anon"
    return init_data or "anon"

# --------------------- STATIC ROUTES -------------------------------

@app.route("/")
def index(request):
    request.setHeader(b"content-type", b"text/html; charset=utf-8")
    data = _read_file_bytes(INDEX_PATH)
    if not data:
        return "Помилка завантаження сторінки.".encode("utf-8")
    return data

@app.route("/style.css")
def style(request):
    request.setHeader(b"content-type", b"text/css; charset=utf-8")
    data = _read_file_bytes(CSS_PATH)
    if not data:
        return "/* Не знайдено style.css */".encode("utf-8")
    return data

@app.route("/script.js")
def script(request):
    request.setHeader(b"content-type", b"application/javascript; charset=utf-8")
    data = _read_file_bytes(JS_PATH)
    if not data:
        return "// Не знайдено script.js".encode("utf-8")
    return data

# ---------------------- API ROUTES --------------------------------

@app.route("/api/get_pairs")
def api_get_pairs(request):
    request.setHeader(b"content-type", b"application/json; charset=utf-8")

    # user watchlist (через initData)
    init_data = request.args.get(b"initData", [b""])[0].decode("utf-8", "ignore")
    user_id = _get_user_id_from_initdata(init_data)
    watchlist = get_watchlist(user_id)

    crypto: List[str] = []
    forex_sessions: Dict[str, List[str]] = {"London": [], "NewYork": [], "Tokyo": [], "Sydney": []}
    stocks: List[str] = []

    # symbols завантажуються в on_symbols_loaded()
    symbols = list(state.symbol_cache.keys()) if getattr(state, "symbol_cache", None) else []

    for s in symbols:
        # crypto: USDT
        if s.endswith("USDT"):
            crypto.append(s)
            continue
        # forex: 6-символьні пари (EURUSD, GBPJPY тощо)
        if len(s) == 6 and s.isalpha():
            # Проста розкладка по "сесіях" (для UI-заголовків)
            if s.endswith(("USD", "EUR", "GBP")):
                forex_sessions["London"].append(s)
            elif s.endswith(("USD", "CAD")):
                forex_sessions["NewYork"].append(s)
            elif s.endswith(("JPY", "AUD", "NZD")):
                forex_sessions["Tokyo"].append(s)
            else:
                forex_sessions["Sydney"].append(s)
            continue
        # умовно в stocks усе інше (якщо є)
        if s not in crypto:
            stocks.append(s)

    payload = {
        "watchlist": watchlist,
        "crypto": sorted(list(set(crypto))),
        "forex": {k: sorted(list(set(v))) for k, v in forex_sessions.items()},
        "stocks": sorted(list(set(stocks))),
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

@app.route("/api/get_mta")
def api_get_mta(request):
    pair = request.args.get(b"pair", [b""])[0].decode("utf-8", "ignore")
    if not pair:
        return _bad_json(request, "pair is required")
    d = get_mta_signal(state.client, pair)

    def _ok(mta):
        return _ok_json(request, mta)

    def _err(f):
        logger.error(f"MTA error: {f}")
        return _bad_json(request, "MTA error", status=500)

    return d.addCallbacks(_ok, _err)

@app.route("/api/signal")
def api_signal(request):
    pair = request.args.get(b"pair", [b""])[0].decode("utf-8", "ignore")
    if not pair:
        return _bad_json(request, "pair is required")

    if HAS_ANALYSIS:
        d = analysis.get_signal(state.client, pair)

        def _ok(sig: Dict[str, Any]):
            # запис у історію (без user_id)
            try:
                import db
                db.add_signal_to_history({
                    "user_id": None,
                    "pair": sig.get("pair", pair),
                    "price": sig.get("price"),
                    "bull_percentage": sig.get("bull_percentage"),
                })
            except Exception as e:
                logger.error(f"History insert error: {e}")
            return _ok_json(request, sig)

        def _err(f):
            logger.error(f"Signal error: {f}")
            return _bad_json(request, "Signal error", status=500)

        return d.addCallbacks(_ok, _err)
    else:
        # fallback проста відповідь
        mock = {
            "pair": pair,
            "price": 0.0,
            "bull_percentage": 50,
            "bear_percentage": 50,
            "support": None,
            "resistance": None,
            "reasons": ["Аналізатор недоступний, повернуто заглушку."],
            "history": None,
        }
        return _ok_json(request, mock)

@app.route("/api/signal_history")
def api_signal_history(request):
    pair = request.args.get(b"pair", [b""])[0].decode("utf-8", "ignore")
    if not pair:
        return _bad_json(request, "pair is required")
    rows = fetch_signal_history(pair, limit=100)
    return _ok_json(request, rows)

@app.route("/api/toggle_watchlist")
def api_toggle_watchlist(request):
    pair = request.args.get(b"pair", [b""])[0].decode("utf-8", "ignore")
    init_data = request.args.get(b"initData", [b""])[0].decode("utf-8", "ignore")
    if not pair:
        return _bad_json(request, "pair is required")

    user_id = _get_user_id_from_initdata(init_data)
    current = set(get_watchlist(user_id))
    is_add = pair not in current
    ok = upsert_watchlist(user_id, pair, is_add)
    if not ok:
        return _bad_json(request, "failed to update watchlist", status=500)
    return _ok_json(request, {"success": True, "added": is_add})

# -------------------- CTRADER + TELEGRAM ---------------------------

def on_ctrader_ready():
    logger.info("cTrader client is ready. Loading symbols...")
    deferred = state.client.get_all_symbols()
    deferred.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        # Зберігаємо як EURUSD без слеша
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.SYMBOLS_LOADED = True
        logger.info(f"✅ Successfully loaded {len(state.symbol_cache)} light symbols.")
    except Exception as e:
        logger.error(f"Symbol processing error: {e}", exc_info=True)

def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")

def setup_and_run():
    logger.info("Initializing components...")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found!")
        return

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.updater = updater
    state.client = client

    # Telegram handlers (як у тебе було)
    try:
        import telegram_ui
        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start", telegram_ui.start))
        dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
        dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
    except Exception as e:
        logger.warning(f"Telegram UI not loaded: {e}")

    updater.start_polling()
    logger.info("Telegram bot started.")

    client.on("ready", on_ctrader_ready)
    client.start()
    logger.info("cTrader client started.")

# --- HTTP сервер на 0.0.0.0:8080 ---
site = Site(app.resource())
reactor.listenTCP(8080, site, interface="0.0.0.0")

reactor.callWhenRunning(setup_and_run)
logger = logging.getLogger("main")
logger.info("Application setup complete. Reactor will run.")
