# api.py
import json
import logging
import os
import queue
import time
from functools import wraps

from flask import Response, jsonify, request, send_from_directory
from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from twisted.internet.threads import blockingCallFromThread
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
from twisted.web.wsgi import WSGIResource

import analysis as analysis_module
import ctrader
import db
from auth import get_user_id_from_init_data, is_valid_init_data
from config import (
    COMMODITIES,
    CRYPTO_PAIRS,
    FOREX_SESSIONS,
    STOCK_TICKERS,
    TRADING_HOURS,
    get_fly_app_name,
)
from state import app_state

logger = logging.getLogger("api")
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")


def _request_init_data() -> str | None:
    return request.values.get("initData")


def _protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = _request_init_data()
        if not is_valid_init_data(init_data):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


def _safe_json_dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def drain_sse_events() -> None:
    events = app_state.pop_pending_sse_events(limit=500)
    if not events:
        return

    for event in events:
        try:
            msg = f"data: {_safe_json_dumps(event)}\n\n"
            app_state.broadcast_sse_message(msg)
        except Exception:
            logger.exception("Не вдалося транслювати SSE event")


class SSEStreamResource(Resource):
    isLeaf = True

    def render_GET(self, request):
        init_data = self._get_query_arg(request, b"initData")
        if not is_valid_init_data(init_data):
            request.setResponseCode(401)
            request.setHeader(b"Content-Type", b"application/json; charset=utf-8")
            return b'{"success":false,"error":"Unauthorized"}'

        request.setHeader(b"Content-Type", b"text/event-stream; charset=utf-8")
        request.setHeader(b"Cache-Control", b"no-cache")
        request.setHeader(b"Connection", b"keep-alive")
        request.setHeader(b"X-Accel-Buffering", b"no")
        request.write(b": connected\n\n")

        listener_id, listener_queue = app_state.register_sse_listener(maxsize=200)
        flusher = LoopingCall(self._flush_queue, request, listener_queue)
        flusher.clock = reactor

        def _cleanup(_=None):
            try:
                if getattr(flusher, "running", False):
                    flusher.stop()
            except Exception:
                logger.exception("Помилка зупинки SSE flusher")
            app_state.unregister_sse_listener(listener_id)
            return None

        request.notifyFinish().addBoth(_cleanup)

        d = flusher.start(0.25, now=False)

        def _flusher_failed(failure):
            logger.warning(f"SSE flusher failure: {failure.getErrorMessage()}")
            _cleanup()

        d.addErrback(_flusher_failed)
        return NOT_DONE_YET

    @staticmethod
    def _get_query_arg(request, key: bytes) -> str | None:
        values = request.args.get(key, [])
        if not values:
            return None
        try:
            return values[0].decode("utf-8", errors="ignore")
        except Exception:
            return None

    @staticmethod
    def _flush_queue(request, listener_queue: queue.Queue) -> None:
        wrote_any = False

        for _ in range(100):
            try:
                message = listener_queue.get_nowait()
            except queue.Empty:
                break

            if isinstance(message, str):
                message = message.encode("utf-8")

            request.write(message)
            wrote_any = True

        if wrote_any:
            try:
                request.channel.transport.setTcpNoDelay(True)
            except Exception:
                pass


class HybridRootResource(Resource):
    isLeaf = True

    def __init__(self, wsgi_resource: WSGIResource, sse_resource: Resource):
        super().__init__()
        self._wsgi_resource = wsgi_resource
        self._sse_resource = sse_resource

    def render(self, request):
        path = request.path.rstrip(b"/") or b"/"
        if path == b"/api/signal-stream":
            return self._sse_resource.render(request)
        return self._wsgi_resource.render(request)


def build_root_resource(flask_app, reactor_obj, wsgi_pool):
    wsgi_resource = WSGIResource(reactor_obj, wsgi_pool, flask_app)
    sse_resource = SSEStreamResource()
    return HybridRootResource(wsgi_resource, sse_resource)


def register_routes(app):
    @app.route("/api/health")
    def health_check():
        try:
            prices = app_state.get_live_prices_snapshot()
            stale_count = sum(1 for d in prices.values() if time.time() - d.get("ts", 0) > 300)
            tg_status = "✅ АКТИВНИЙ" if app_state.updater else "❌ ВИМКНЕНО"
            listener_count = app_state.sse_listener_count()

            html = f"""
            <html><head><meta charset="UTF-8"><style>
                body {{ background:#0f0f0f; color:#e0e0e0; font-family:sans-serif; padding:20px; display:flex; justify-content:center; }}
                .card {{ background:#1a1a1a; border-radius:16px; padding:24px; border:1px solid #333; width:480px; }}
                h1 {{ color:#3390ec; border-bottom:1px solid #333; padding-bottom:10px; font-size:22px; }}
                .stat {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #252525; }}
                .val {{ font-weight:bold; color:#fff; }}
                .ok {{ color:#4caf50; }} .info {{ color:#3390ec; }} .err {{ color:#ef5350; }}
            </style></head>
            <body><div class="card">
                <h1>📊 Стан ZigZag</h1>
                <div class="stat"><span>cTrader:</span><span class="val {'ok' if app_state.SYMBOLS_LOADED else 'err'}">{'✅ OK' if app_state.SYMBOLS_LOADED else '❌ ERROR'}</span></div>
                <div class="stat"><span>Telegram Бот:</span><span class="val {'ok' if app_state.updater else 'err'}">{tg_status}</span></div>
                <div class="stat"><span>SSE клієнтів:</span><span class="val info">{listener_count}</span></div>
                <div class="stat"><span>Цін в ефірі:</span><span class="val">{len(prices)}</span></div>
                <div class="stat"><span>Застарілих:</span><span class="val">{stale_count}</span></div>
                <p style='text-align:center;color:#555;font-size:11px;margin-top:20px;'>Оновлено: {time.strftime('%H:%M:%S')}</p>
            </div></body></html>
            """
            return Response(html, mimetype="text/html")
        except Exception as e:
            logger.exception("Health endpoint failed")
            return f"Error: {str(e)}", 500

    @app.route("/api/get_pairs")
    @_protected_route
    def get_pairs():
        uid = get_user_id_from_init_data(_request_init_data())
        watchlist = db.get_watchlist(uid) if uid else []
        forex_data = [
            {
                "title": f"{k} {TRADING_HOURS.get(k, '')}".strip(),
                "pairs": v,
            }
            for k, v in FOREX_SESSIONS.items()
        ]
        return jsonify(
            {
                "forex": forex_data,
                "crypto": CRYPTO_PAIRS,
                "stocks": STOCK_TICKERS,
                "commodities": COMMODITIES,
                "watchlist": watchlist,
            }
        )

    @app.route("/api/scanner/toggle", methods=["GET", "POST"])
    @_protected_route
    def scanner_toggle():
        cat = request.values.get("category")
        if cat in app_state.SCANNER_STATE:
            app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
            reactor.callLater(0.5, ctrader.start_price_subscriptions)
        return jsonify(app_state.get_scanner_state_snapshot())

    @app.route("/api/signal")
    @_protected_route
    def api_signal():
        pair = request.args.get("pair", "").strip()
        tf = request.args.get("timeframe", "15m").strip()
        uid = get_user_id_from_init_data(_request_init_data())

        if not pair:
            return jsonify({"success": False, "error": "pair is required"}), 400

        try:
            result = blockingCallFromThread(
                reactor,
                _run_analysis_and_wait,
                pair,
                uid,
                tf,
            )
            return jsonify(result)
        except Exception as e:
            logger.exception("api_signal failed")
            return jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "pair": pair,
                    "timeframe": tf,
                }
            ), 500

    @app.route("/")
    def home():
        idx = os.path.join(WEBAPP_DIR, "index.html")
        if os.path.exists(idx):
            with open(idx, "r", encoding="utf-8") as f:
                content = f.read().replace(
                    "{{API_BASE_URL}}",
                    f"https://{get_fly_app_name()}.fly.dev" if get_fly_app_name() else "",
                )
                version = int(time.time())
                content = content.replace(".js", f".js?v={version}")
                content = content.replace(".css", f".css?v={version}")
                return Response(content, mimetype="text/html")
        return "Not found", 404

    @app.route("/<path:filename>")
    def static_files(filename):
        return send_from_directory(WEBAPP_DIR, filename)


def _run_analysis_and_wait(pair: str, uid: int | None, tf: str) -> dict:
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    d = analysis_module.get_api_detailed_signal_data(
        app_state.client,
        app_state.symbol_cache,
        pair.replace("/", ""),
        uid,
        tf,
    )

    def _store_result(result):
        try:
            result_queue.put_nowait(result)
        except queue.Full:
            pass
        return result

    d.addBoth(_store_result)

    try:
        result = result_queue.get(timeout=35)
    except queue.Empty:
        return {
            "pair": pair,
            "timeframe": tf,
            "verdict_text": "ERROR",
            "score": 50,
            "reasons": ["Час очікування аналізу вичерпано"],
        }

    if hasattr(result, "getErrorMessage"):
        return {
            "pair": pair,
            "timeframe": tf,
            "verdict_text": "ERROR",
            "score": 50,
            "reasons": [result.getErrorMessage()],
        }

    return result if isinstance(result, dict) else {
        "pair": pair,
        "timeframe": tf,
        "verdict_text": "ERROR",
        "score": 50,
        "reasons": ["Невідомий формат відповіді"],
    }