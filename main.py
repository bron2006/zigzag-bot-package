import logging, json, queue, threading
from urllib.parse import parse_qs, unquote

from klein import Klein
from twisted.internet import reactor
from twisted.web.static import File
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

import state
from telegram_ui import start, menu, button_handler, reset_ui
from spotware_connect import SpotwareClient
from config import (
    get_telegram_token, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, CRYPTO_PAIRS_FULL, STOCKS_US_SYMBOLS
)
from db import init_db, get_watchlist, toggle_watch, get_signal_history
from analysis import get_api_detailed_signal_data
try:
    from mta_analysis import get_mta_signal
except Exception:
    # fallback, якщо все в analysis.py
    from analysis import get_mta_signal  # type: ignore

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("main")

app = Klein()
updates_queue = queue.Queue(maxsize=1000)

# ---------- HELPERS ----------
def _json(request, data: dict, code: int = 200):
    request.setResponseCode(code)
    request.setHeader('Content-Type', 'application/json')
    request.setHeader('Access-Control-Allow-Origin', '*')
    return json.dumps(data).encode()

def _parse_tg_init(init_data: str):
    try:
        params = parse_qs(unquote(init_data or ""))
        user_raw = params.get('user', [None])[0]
        return json.loads(user_raw) if user_raw else None
    except Exception:
        return None

# ---------- TELEGRAM ----------
def _dispatcher_worker():
    while True:
        try:
            update_data = updates_queue.get()
            if state.updater:
                upd = Update.de_json(update_data, state.updater.bot)
                state.updater.dispatcher.process_update(upd)
            updates_queue.task_done()
        except Exception as e:
            logger.exception(f"Помилка воркера диспетчера: {e}")

def init_telegram():
    token = get_telegram_token()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN відсутній — Telegram не буде запущено."); return
    try:
        state.updater = Updater(token, use_context=True)
    except Exception as e:
        logger.error(f"Telegram не запущено: {e}"); state.updater = None; return

    dp = state.updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, reset_ui))
    dp.add_handler(CallbackQueryHandler(button_handler))

    for _ in range(4):
        threading.Thread(target=_dispatcher_worker, daemon=True).start()

# ---------- cTrader ----------
def _on_symbols_loaded(symbols):
    # очікуємо: [{"symbolId": .., "symbolName": .., "digits": ..}, ...]
    for s in symbols:
        name = (s.get("symbolName") or "").replace("/", "").strip()
        if name:
            state.symbol_cache[name] = {"symbolId": s.get("symbolId"), "digits": s.get("digits", 5)}
    logger.info("✅ Завантажено символів: %s", len(state.symbol_cache))

def init_ctrader():
    client_id = get_ct_client_id()
    client_secret = get_ct_client_secret()
    state.client = SpotwareClient(client_id, client_secret)
    state.client.on("symbolsLoaded")(_on_symbols_loaded)
    state.client.on("error")(lambda e: logger.error(f"cTrader ERROR: {e}"))
    state.client.connect()

# ---------- API ----------
@app.route('/api/get_ranked_pairs', methods=['GET'])
def api_get_ranked_pairs(request):
    try:
        init_data = request.args.get(b'initData', [b''])[0].decode()
        user = _parse_tg_init(init_data)
        watch = get_watchlist(user['id']) if user and user.get('id') else []

        def mark(t):
            key = t.replace("/", "").strip()
            return {"ticker": t, "active": key in state.symbol_cache}

        data = {
            "watchlist": watch,
            "forex": {s: [mark(p) for p in pairs] for s, pairs in FOREX_SESSIONS.items()},
            "crypto": [mark(p) for p in CRYPTO_PAIRS_FULL],
            "stocks": [mark(p) for p in STOCKS_US_SYMBOLS],
        }
        return _json(request, data, 200)
    except Exception:
        logger.exception("/api/get_ranked_pairs")
        return _json(request, {"error": "Internal Server Error"}, 500)

@app.route('/api/toggle_watchlist', methods=['GET'])
def api_toggle_watchlist(request):
    try:
        init_data = request.args.get(b'initData', [b''])[0].decode()
        pair = request.args.get(b'pair', [b''])[0].decode()
        user = _parse_tg_init(init_data)
        if not (user and user.get('id') and pair):
            return _json(request, {"success": False, "error": "Invalid parameters"}, 400)
        toggle_watch(user['id'], pair)
        return _json(request, {"success": True}, 200)
    except Exception:
        logger.exception("/api/toggle_watchlist")
        return _json(request, {"success": False, "error": "Internal error"}, 500)

@app.route('/api/signal', methods=['GET'])
def api_signal(request):
    pair = request.args.get(b'pair', [b''])[0].decode()
    if not pair:
        return _json(request, {"status": "error", "message": "pair is required"}, 400)
    if not state.client or not getattr(state.client, "isConnected", False):
        return _json(request, {"status": "error", "message": "cTrader not connected"}, 503)

    init_data = request.args.get(b'initData', [b''])[0].decode()
    user = _parse_tg_init(init_data) or {}
    user_id = user.get('id')

    d = get_api_detailed_signal_data(state.client, pair, user_id)

    def on_ok(res):
        try:
            if isinstance(res, dict) and res.get("error"):
                return _json(request, {"status": "error", "message": res["error"]}, 400)
            return _json(request, {"status": "success", "data": res}, 200)
        except Exception:
            logger.exception("format /api/signal")
            return _json(request, {"status": "error", "message": "internal"}, 500)

    def on_err(f):
        try:
            msg = f.getErrorMessage() if hasattr(f, 'getErrorMessage') else str(f)
            logger.error(f"/api/signal ERROR: {msg}")
        except Exception:
            logger.error("/api/signal ERROR")
        return _json(request, {"status": "error", "message": "internal"}, 500)

    return d.addCallbacks(on_ok, on_err)

@app.route('/api/get_mta', methods=['GET'])
def api_get_mta(request):
    pair = request.args.get(b'pair', [b''])[0].decode()
    if not pair:
        return _json(request, {"status": "error", "message": "pair is required"}, 400)
    if not state.client or not getattr(state.client, "isConnected", False):
        return _json(request, {"status": "error", "message": "cTrader not connected"}, 503)

    d = get_mta_signal(state.client, pair)

    def on_ok(res):
        try:
            if isinstance(res, dict) and res.get("error"):
                return _json(request, {"status": "error", "message": res["error"]}, 400)
            return _json(request, {"status": "success", "data": res}, 200)
        except Exception:
            logger.exception("format /api/get_mta")
            return _json(request, {"status": "error", "message": "internal"}, 500)

    def on_err(f):
        try:
            msg = f.getErrorMessage() if hasattr(f, 'getErrorMessage') else str(f)
            logger.error(f"/api/get_mta ERROR: {msg}")
        except Exception:
            logger.error("/api/get_mta ERROR")
        return _json(request, {"status": "error", "message": "internal"}, 500)

    return d.addCallbacks(on_ok, on_err)

@app.route('/api/signal_history', methods=['GET'])
def api_signal_history(request):
    init_data = request.args.get(b'initData', [b''])[0].decode()
    pair = request.args.get(b'pair', [b''])[0].decode()
    user = _parse_tg_init(init_data)
    if not (user and user.get('id') and pair):
        return _json(request, [], 400)
    hist = get_signal_history(user['id'], pair)
    return _json(request, hist, 200)

# ---------- WEBHOOK (опціонально, якщо користуєтесь) ----------
@app.route("/tg", methods=['POST'])
def tg_webhook(request):
    if not state.updater:
        request.setResponseCode(503); return b"telegram disabled"
    try:
        data = json.loads(request.content.read().decode())
        updates_queue.put_nowait(data)
        return b"OK"
    except queue.Full:
        request.setResponseCode(503); return b"busy"
    except Exception:
        request.setResponseCode(400); return b"bad request"

# ---------- СТАТИКА/HEALTH ----------
@app.route('/webapp/', branch=True)
def web_static(request):
    return File("./webapp")

@app.route('/health')
def health(request):
    return _json(request, {
        "telegram": bool(state.updater),
        "ctrader_connected": bool(getattr(state.client, "isConnected", False)),
        "symbols_cached": len(state.symbol_cache),
    }, 200)

@app.route('/')
def root(request):
    return b"OK"

# ---------- STARTUP ----------
init_db()
logger.info("✅ Базу даних ініціалізовано.")
init_telegram()
reactor.callWhenRunning(init_ctrader)
