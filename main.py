# -*- coding: utf-8 -*-
import os
import json
import logging
from typing import Any, Dict, Optional

from klein import Klein
from twisted.internet import reactor
from twisted.internet.defer import maybeDeferred
from twisted.web.static import File

import state
import config
import analysis
import telegram_ui
import spotware_connect
import db

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("main")

app = Klein()

# --- Утиліти ---
def normalize_pair_input(pair: str) -> Dict[str, str]:
    """Приймає 'eurusd' або 'EUR/USD' або 'eur/usd' і повертає:
       {'norm': 'EURUSD', 'display': 'EUR/USD'}"""
    if not pair:
        return {"norm": "", "display": ""}
    p = pair.replace("\\", "").replace(" ", "").upper()
    if "/" in p:
        parts = p.split("/")
        if len(parts) >= 2:
            norm = (parts[0] + parts[1])[:6]
            display = f"{parts[0]}/{parts[1]}"
            return {"norm": norm, "display": display}
    # fallback: assume contiguous like EURUSD
    p = p.replace("/", "")
    if len(p) >= 6:
        display = f"{p[:3]}/{p[3:6]}"
    else:
        display = p
    return {"norm": p, "display": display}

def json_response(request, payload: Dict[str, Any], status: int = 200):
    request.setHeader(b"Content-Type", b"application/json; charset=utf-8")
    request.setResponseCode(status)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

def _get_arg(request, name: str) -> Optional[str]:
    raw = request.args.get(name.encode("utf-8"))
    if not raw:
        return None
    return raw[0].decode("utf-8")

def _get_json_body(request) -> Dict[str, Any]:
    try:
        body = request.content.read()
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}

# --- Health ---
@app.route("/health")
def health(request):
    data = {
        "ok": True,
        "telegram_initialized": bool(getattr(state, "updater", None)),
        "ctrader_connected": bool(getattr(state, "client", None) and getattr(state.client, "isConnected", False)),
        "symbols_cached": len(getattr(state, "symbol_cache", {}))
    }
    return json_response(request, data, 200)

# --- Ranked pairs (webapp expects "EUR/USD") ---
@app.route("/api/get_ranked_pairs", methods=["GET"])
def api_get_ranked_pairs(request):
    try:
        pairs = []
        cache = getattr(state, "symbol_cache", None)
        if cache and isinstance(cache, dict) and cache:
            for key in cache.keys():
                k = str(key).upper().replace(" ", "")
                if "/" in k:
                    pairs.append(k)
                else:
                    if len(k) >= 6:
                        pairs.append(f"{k[:3]}/{k[3:6]}")
                    else:
                        pairs.append(k)
        if not pairs:
            # fallback to config sessions (format them to EUR/USD)
            sessions = getattr(config, "FOREX_SESSIONS", {})
            for sess_pairs in sessions.values():
                for p in sess_pairs:
                    pnorm = normalize_pair_input(p)["display"]
                    pairs.append(pnorm)
        pairs = sorted(dict.fromkeys(pairs))  # unique, ordered by first appearance
        return json_response(request, {"ok": True, "pairs": pairs}, 200)
    except Exception as e:
        log.exception("get_ranked_pairs failed")
        return json_response(request, {"ok": False, "error": str(e)}, 500)

# --- Signal endpoint (accepts eurusd or eur/usd) ---
@app.route("/api/signal", methods=["GET", "POST"])
def api_signal(request):
    try:
        pair = _get_arg(request, "pair")
        if not pair:
            body = _get_json_body(request)
            pair = body.get("pair") or body.get("symbol")
        if not pair:
            return json_response(request, {"ok": False, "error": "pair parameter is required"}, 400)

        normalized = normalize_pair_input(pair)
        norm_pair = normalized["norm"]

        # user id parsing from initData if provided
        init_data = _get_arg(request, "initData")
        user_id = None
        if init_data:
            try:
                from urllib.parse import parse_qs, unquote
                params = parse_qs(unquote(init_data))
                user_raw = params.get('user', [None])[0]
                if user_raw:
                    user = json.loads(user_raw)
                    user_id = user.get('id')
            except Exception:
                user_id = None

        d = maybeDeferred(analysis.get_api_detailed_signal_data, getattr(state, "client", None), norm_pair, user_id)

        def cb_ok(res):
            if isinstance(res, dict) and res.get("error"):
                return json_response(request, {"ok": False, "error": res["error"]}, 200)
            res_out = {"ok": True, "pair": normalized["display"], "data": res}
            return json_response(request, res_out, 200)

        def cb_err(f):
            try:
                msg = f.getErrorMessage()
            except Exception:
                msg = str(f)
            log.error("api/signal error for %s: %s", norm_pair, msg)
            return json_response(request, {"ok": False, "error": msg}, 200)

        d.addCallback(cb_ok)
        d.addErrback(cb_err)
        return d
    except Exception as e:
        log.exception("api_signal unexpected")
        return json_response(request, {"ok": False, "error": str(e)}, 500)

# --- MTA endpoint ---
@app.route("/api/get_mta", methods=["GET", "POST"])
def api_get_mta(request):
    try:
        pair = _get_arg(request, "pair")
        if not pair:
            body = _get_json_body(request)
            pair = body.get("pair") or body.get("symbol")
        if not pair:
            return json_response(request, {"ok": False, "error": "pair parameter is required"}, 400)

        norm_pair = normalize_pair_input(pair)["norm"]
        d = maybeDeferred(analysis.get_mta_signal, getattr(state, "client", None), norm_pair)

        def cb_ok(res):
            return json_response(request, {"ok": True, "pair": pair, "mta": res}, 200)

        def cb_err(f):
            try:
                msg = f.getErrorMessage()
            except Exception:
                msg = str(f)
            log.error("api/get_mta error for %s: %s", norm_pair, msg)
            return json_response(request, {"ok": False, "error": msg}, 200)

        d.addCallback(cb_ok)
        d.addErrback(cb_err)
        return d
    except Exception as e:
        log.exception("api_get_mta unexpected")
        return json_response(request, {"ok": False, "error": str(e)}, 500)

# --- Static webapp route ---
@app.route("/webapp/", branch=True)
def webapp_static(request):
    return File("./webapp")

# --- Telegram webhook route ---
@app.route("/<token>", methods=["POST"])
def telegram_webhook(request, token: str):
    if not getattr(state, "updater", None) or token != getattr(state, "BOT_TOKEN", None):
        request.setResponseCode(404)
        return b"Not found"
    try:
        body = request.content.read()
        if not body:
            request.setResponseCode(400); return b"Empty"
        from telegram import Update as TgUpdate
        upd = TgUpdate.de_json(json.loads(body.decode("utf-8")), state.updater.bot)
        state.dispatcher.process_update(upd)
        request.setResponseCode(200); return b"OK"
    except Exception as e:
        log.exception("telegram_webhook failed")
        request.setResponseCode(500)
        return str(e).encode("utf-8")

# --- Init helpers ---
def init_services():
    try:
        db.init_db()
    except Exception:
        log.exception("DB init failed")
    # init telegram
    try:
        token = config.get_telegram_token()
        state.BOT_TOKEN = token
        from telegram.ext import Updater
        state.updater = Updater(token, use_context=True)
        state.dispatcher = state.updater.dispatcher
        telegram_ui.register_handlers(state.dispatcher)
        # do not force webhook here, rely on environment if set
        log.info("Telegram initialized")
    except Exception as e:
        log.error("Telegram init error: %s", e)
        state.updater = None
        state.dispatcher = None

    # init cTrader client (spotware_connect should set state.client and symbol_cache)
    try:
        spotware_connect.init_ctrader_client()
    except Exception:
        # try alternative start
        try:
            spotware_connect.start()
        except Exception:
            log.exception("ctrader init failed")

# --- run ---
if __name__ == "__main__":
    init_services()
    port = int(os.getenv("PORT", "8080"))
    app.run("0.0.0.0", port)
    reactor.run()
