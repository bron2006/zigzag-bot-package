# api.py
import json
import logging
import os
import queue
import time
from functools import wraps

from flask import Response, jsonify, request, send_from_directory
from twisted.internet import defer, reactor
from twisted.internet.task import LoopingCall
from twisted.internet.threads import blockingCallFromThread
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
from twisted.web.wsgi import WSGIResource

import analysis as analysis_module
import ctrader
import crypto_pay
import db
import ml_models
import news_filter
from auth import get_user_id_from_init_data, is_valid_init_data
from config import (
    COMMODITIES,
    CRYPTO_PAIRS,
    FOREX_SESSIONS,
    STOCK_TICKERS,
    SUBSCRIPTION_DAYS,
    get_fly_app_name,
)
from locales import localize_reason, localize_signal_payload, normalize_lang, session_label, t
from session_times import DEFAULT_TIMEZONE, normalize_timezone, session_time_label
from state import app_state

logger = logging.getLogger("api")
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")


def _request_init_data() -> str | None:
    return request.values.get("initData")


def _request_lang() -> str:
    init_data = _request_init_data()
    try:
        if init_data and is_valid_init_data(init_data):
            uid = get_user_id_from_init_data(init_data)
            saved_lang = db.get_user_language(uid) if uid else None
            if saved_lang:
                return normalize_lang(saved_lang)
    except Exception:
        logger.debug("Could not resolve saved user language", exc_info=True)

    return normalize_lang(
        request.values.get("lang")
        or request.headers.get("X-User-Language")
        or request.headers.get("Accept-Language")
    )


def _request_timezone() -> str:
    return normalize_timezone(
        request.values.get("timezone")
        or request.values.get("tz")
        or request.headers.get("X-User-Timezone")
    )


def _sync_user_timezone(uid: int | None) -> str:
    requested_tz = _request_timezone()
    if not uid:
        return requested_tz

    try:
        status = db.get_cached_user_status(uid, max_age_seconds=3600)
        current_tz = normalize_timezone((status or {}).get("timezone"))
        if requested_tz != current_tz:
            return db.set_user_timezone(uid, requested_tz)
        return current_tz
    except Exception:
        logger.debug("Could not sync user timezone", exc_info=True)
        return requested_tz or DEFAULT_TIMEZONE


def _protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        lang = _request_lang()
        init_data = _request_init_data()
        if not is_valid_init_data(init_data):
            return jsonify({"success": False, "error": t("unauthorized", lang)}), 401
        return f(*args, **kwargs)
    return decorated_function


def _safe_json_dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _pair_key(pair: str) -> str:
    return "".join(ch for ch in (pair or "").upper() if ch.isalnum())


def _collect_ui_pairs(watchlist: list[str]) -> list[str]:
    pairs = []

    for session_pairs in FOREX_SESSIONS.values():
        pairs.extend(session_pairs)

    pairs.extend(CRYPTO_PAIRS)
    pairs.extend(STOCK_TICKERS)
    pairs.extend(COMMODITIES)
    pairs.extend(watchlist or [])

    seen = set()
    result = []
    for pair in pairs:
        key = _pair_key(pair)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)

    return result


def _broker_pair_availability(watchlist: list[str]) -> tuple[list[str], list[str]]:
    if not app_state.SYMBOLS_LOADED:
        return [], []

    available = []
    unavailable = []

    for pair in _collect_ui_pairs(watchlist):
        if ctrader._resolve_broker_symbol(pair) is None:
            unavailable.append(pair)
        else:
            available.append(pair)

    return available, unavailable


def _unavailable_symbol_payload(pair: str, tf: str, lang: str = "en") -> dict:
    return {
        "success": False,
        "pair": _pair_key(pair) or pair,
        "timeframe": tf,
        "verdict_text": "ERROR",
        "score": 50,
        "price": None,
        "sentiment": "BLOCK",
        "reasons": [t("symbol_unavailable", lang)],
        "is_trade_allowed": False,
        "unavailable_symbol": True,
    }


def _diagnostics_payload() -> dict:
    now = time.time()
    prices = app_state.get_live_prices_snapshot()
    configured_pairs = _collect_ui_pairs([])
    stale_prices = {
        pair: int(now - data.get("ts", 0))
        for pair, data in prices.items()
        if now - data.get("ts", 0) > 60
    }
    missing_prices = sorted(set(configured_pairs) - set(prices.keys()))

    return {
        "ok": True,
        "updated_at": int(now),
        "ctrader": {
            "ok": bool(app_state.SYMBOLS_LOADED),
            "label": "символи завантажені" if app_state.SYMBOLS_LOADED else "символи не завантажені",
            "configured_pairs": len(configured_pairs),
            "prices_live": len(prices),
            "missing_prices": missing_prices,
            "stale_prices": stale_prices,
            "price_stream": ctrader.get_price_stream_status(),
        },
        "telegram": {
            "ok": bool(app_state.updater),
            "label": "працює" if app_state.updater else "вимкнено",
        },
        "ml": {
            "ok": bool(
                ml_models.SCALER is not None
                and ml_models.LGBM_MODEL is not None
                and hasattr(ml_models.SCALER, "transform")
                and hasattr(ml_models.LGBM_MODEL, "predict_proba")
            ),
            "label": "модель завантажена" if ml_models.SCALER is not None and ml_models.LGBM_MODEL is not None else "модель не завантажена",
        },
        "calendar": news_filter.get_cache_stats(),
        "database": db.check_database_status(),
        "sse": {
            "signal_clients": app_state.sse_listener_count("signal"),
            "price_clients": app_state.sse_listener_count("price"),
        },
    }


def _drain_channel(channel: str) -> None:
    events = app_state.pop_pending_sse_events(channel, limit=500)
    if not events:
        return

    for event in events:
        try:
            msg = f"data: {_safe_json_dumps(event)}\n\n"
            app_state.broadcast_sse_message(channel, msg)
        except Exception:
            logger.exception(f"Не вдалося транслювати SSE event каналу '{channel}'")


def drain_sse_events() -> None:
    _drain_channel("signal")
    _drain_channel("price")


class SSEStreamResource(Resource):
    isLeaf = True

    def __init__(self, channel: str):
        super().__init__()
        self.channel = channel

    def render_GET(self, request):
        init_data = self._get_query_arg(request, b"initData")
        lang = normalize_lang(self._get_query_arg(request, b"lang"))
        if not is_valid_init_data(init_data):
            request.setResponseCode(401)
            request.setHeader(b"Content-Type", b"application/json; charset=utf-8")
            return _safe_json_dumps({"success": False, "error": t("unauthorized", lang)}).encode("utf-8")

        request.setHeader(b"Content-Type", b"text/event-stream; charset=utf-8")
        request.setHeader(b"Cache-Control", b"no-cache")
        request.setHeader(b"Connection", b"keep-alive")
        request.setHeader(b"X-Accel-Buffering", b"no")
        request.write(b": connected\n\n")

        listener_id, listener_queue = app_state.register_sse_listener(self.channel, maxsize=200)
        flusher = LoopingCall(self._flush_queue, request, listener_queue)
        flusher.clock = reactor

        def _cleanup(_=None):
            try:
                if getattr(flusher, "running", False):
                    flusher.stop()
            except Exception:
                logger.exception("Помилка зупинки SSE flusher")
            app_state.unregister_sse_listener(self.channel, listener_id)
            return None

        request.notifyFinish().addBoth(_cleanup)

        d = flusher.start(0.25, now=False)

        def _flusher_failed(failure):
            logger.warning(
                f"SSE flusher failure [{self.channel}]: {failure.getErrorMessage()}"
            )
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
        for _ in range(100):
            try:
                message = listener_queue.get_nowait()
            except queue.Empty:
                break

            if isinstance(message, str):
                message = message.encode("utf-8")

            request.write(message)


class HybridRootResource(Resource):
    isLeaf = True

    def __init__(self, wsgi_resource: WSGIResource):
        super().__init__()
        self._wsgi_resource = wsgi_resource
        self._signal_resource = SSEStreamResource("signal")
        self._price_resource = SSEStreamResource("price")

    def render(self, request):
        path = request.path.rstrip(b"/") or b"/"

        if path == b"/api/signal-stream":
            return self._signal_resource.render(request)

        if path == b"/api/price-stream":
            return self._price_resource.render(request)

        return self._wsgi_resource.render(request)


def build_root_resource(flask_app, reactor_obj, wsgi_pool):
    wsgi_resource = WSGIResource(reactor_obj, wsgi_pool, flask_app)
    return HybridRootResource(wsgi_resource)


@defer.inlineCallbacks
def _call_analysis_in_reactor(pair: str, uid: int | None, tf: str, lang: str):
    d = analysis_module.get_api_detailed_signal_data(
        app_state.client,
        app_state.symbol_cache,
        pair.replace("/", ""),
        uid,
        tf,
        lang,
    )
    d.addTimeout(50, reactor)
    result = yield d
    return result


def register_routes(app):
    @app.route("/privacy")
    @app.route("/privacy.html")
    def privacy_policy():
        html = """
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>ZigZag Signals Privacy Policy</title>
            <style>
                body {
                    margin: 0;
                    background: #101214;
                    color: #eef2f6;
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                }
                main {
                    max-width: 860px;
                    margin: 0 auto;
                    padding: 42px 20px 56px;
                }
                h1, h2 {
                    color: #ffffff;
                    line-height: 1.25;
                }
                h1 {
                    font-size: 32px;
                    margin-bottom: 6px;
                }
                h2 {
                    font-size: 20px;
                    margin-top: 30px;
                    border-top: 1px solid #2c333a;
                    padding-top: 22px;
                }
                p, li {
                    color: #cbd5df;
                    font-size: 16px;
                }
                ul {
                    padding-left: 22px;
                }
                a {
                    color: #4aa3ff;
                }
                .muted {
                    color: #8b98a5;
                    font-size: 14px;
                }
                .notice {
                    background: #171c21;
                    border: 1px solid #2c333a;
                    border-radius: 8px;
                    padding: 16px 18px;
                    margin-top: 22px;
                }
            </style>
        </head>
        <body>
            <main>
                <h1>Privacy Policy</h1>
                <p class="muted">Last updated: April 20, 2026</p>

                <p>
                    This Privacy Policy explains how ZigZag Signals handles user data in the Telegram bot
                    and Web App available at zigzag-bot-package.fly.dev.
                </p>

                <h2>Data We Collect</h2>
                <p>We may process and store the following data:</p>
                <ul>
                    <li>Telegram user ID, language preference and timezone.</li>
                    <li>Favorites/watchlist selected by the user.</li>
                    <li>Subscription status, trial status and subscription expiration date.</li>
                    <li>Payment invoice identifiers and payment status received through Crypto Pay webhooks.</li>
                    <li>Basic technical logs required to keep the service stable and secure.</li>
                </ul>

                <h2>How We Use Data</h2>
                <p>We use this data to:</p>
                <ul>
                    <li>Provide access to the bot, Web App and trading signal features.</li>
                    <li>Save user preferences such as language, timezone and favorites.</li>
                    <li>Manage free trials, paid subscriptions and payment confirmations.</li>
                    <li>Detect errors, prevent abuse and improve service reliability.</li>
                </ul>

                <h2>Payments</h2>
                <p>
                    Payments are processed through Crypto Pay. We do not store private wallet keys,
                    bank card data or full payment credentials. We only store the information needed
                    to confirm that a payment was completed and to activate the subscription.
                </p>

                <h2>Third-Party Services</h2>
                <p>
                    The service may use Telegram, Crypto Pay, hosting providers and market data providers.
                    These services may process data according to their own privacy policies.
                </p>

                <h2>Data Retention</h2>
                <p>
                    We keep user data only as long as needed to provide the service, maintain subscription
                    records, prevent duplicate trial usage and comply with operational requirements.
                </p>

                <h2>Data Deletion</h2>
                <p>
                    Users may request deletion of their stored data by contacting the bot owner through Telegram.
                    Some payment or security records may be retained when necessary for fraud prevention,
                    dispute handling or legal compliance.
                </p>

                <h2>Trading Risk Notice</h2>
                <div class="notice">
                    <p>
                        ZigZag Signals provides analytical information only. It is not financial advice,
                        investment advice or a guarantee of profit. Trading financial instruments involves risk,
                        and users are responsible for their own decisions.
                    </p>
                </div>

                <h2>Changes</h2>
                <p>
                    We may update this Privacy Policy from time to time. The latest version will always be
                    available on this page.
                </p>

                <h2>Contact</h2>
                <p>
                    For privacy requests, contact the bot owner through the Telegram bot profile.
                </p>
            </main>
        </body>
        </html>
        """
        return Response(html, mimetype="text/html")

    @app.route("/api/health")
    def health_check():
        lang = _request_lang()
        try:
            prices = app_state.get_live_prices_snapshot()
            stale_count = sum(1 for d in prices.values() if time.time() - d.get("ts", 0) > 300)
            tg_status = f"✅ {t('active', lang)}" if app_state.updater else f"❌ {t('disabled', lang)}"

            html = f"""
            <html><head><meta charset="UTF-8"><style>
                body {{ background:#0f0f0f; color:#e0e0e0; font-family:sans-serif; padding:20px; display:flex; justify-content:center; }}
                .card {{ background:#1a1a1a; border-radius:16px; padding:24px; border:1px solid #333; width:520px; }}
                h1 {{ color:#3390ec; border-bottom:1px solid #333; padding-bottom:10px; font-size:22px; }}
                .stat {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #252525; }}
                .val {{ font-weight:bold; color:#fff; }}
                .ok {{ color:#4caf50; }} .info {{ color:#3390ec; }} .err {{ color:#ef5350; }}
            </style></head>
            <body><div class="card">
                <h1>{t('health_title', lang)}</h1>
                <div class="stat"><span>{t('quote_feed', lang)}:</span><span class="val {'ok' if app_state.SYMBOLS_LOADED else 'err'}">{'✅ ' + t('ready', lang) if app_state.SYMBOLS_LOADED else '❌ ' + t('error', lang)}</span></div>
                <div class="stat"><span>{t('telegram_bot', lang)}:</span><span class="val {'ok' if app_state.updater else 'err'}">{tg_status}</span></div>
                <div class="stat"><span>{t('sse_signal_clients', lang)}:</span><span class="val info">{app_state.sse_listener_count('signal')}</span></div>
                <div class="stat"><span>{t('sse_price_clients', lang)}:</span><span class="val info">{app_state.sse_listener_count('price')}</span></div>
                <div class="stat"><span>{t('live_prices', lang)}:</span><span class="val">{len(prices)}</span></div>
                <div class="stat"><span>{t('stale_prices', lang)}:</span><span class="val">{stale_count}</span></div>
                <p style='text-align:center;color:#555;font-size:11px;margin-top:20px;'>{t('updated', lang)}: {time.strftime('%H:%M:%S')}</p>
            </div></body></html>
            """
            return Response(html, mimetype="text/html")
        except Exception as e:
            logger.exception("Health endpoint failed")
            return f"{t('error', lang)}: {str(e)}", 500

    @app.route("/api/diagnostics")
    @_protected_route
    def diagnostics():
        lang = _request_lang()
        payload = _diagnostics_payload()
        for section in ("ctrader", "telegram", "ml"):
            item = payload.get(section)
            if isinstance(item, dict) and "label" in item:
                item["label"] = localize_reason(item["label"], lang)
        return jsonify(payload)

    @app.route("/api/get_pairs")
    @_protected_route
    def get_pairs():
        lang = _request_lang()
        uid = get_user_id_from_init_data(_request_init_data())
        user_timezone = _sync_user_timezone(uid)
        user_status = db.get_cached_user_status(uid, language_hint=lang) if uid else None
        raw_watchlist = db.get_watchlist(uid) if uid else []
        configured_pairs = set(_collect_ui_pairs([]))
        watchlist = [pair for pair in raw_watchlist if _pair_key(pair) in configured_pairs]
        available_pairs, unavailable_pairs = _broker_pair_availability(watchlist)
        forex_data = [
            {
                "title": f"{session_label(k, lang)} {session_time_label(k, user_timezone)}".strip(),
                "timezone": user_timezone,
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
                "symbols_loaded": app_state.SYMBOLS_LOADED,
                "available_pairs": available_pairs,
                "unavailable_pairs": unavailable_pairs,
                "language": lang,
                "timezone": user_timezone,
                "user": user_status,
            }
        )

    @app.route("/api/user/status", methods=["GET"])
    @_protected_route
    def user_status():
        lang = _request_lang()
        uid = get_user_id_from_init_data(_request_init_data())
        if not uid:
            return jsonify({"success": False, "error": t("user_not_resolved", lang)}), 400

        _sync_user_timezone(uid)
        status = db.get_cached_user_status(uid, language_hint=lang)
        return jsonify({"success": True, "user": status})

    @app.route("/api/subscription/status", methods=["GET"])
    @_protected_route
    def subscription_status():
        lang = _request_lang()
        uid = get_user_id_from_init_data(_request_init_data())
        if not uid:
            return jsonify({"success": False, "error": t("user_not_resolved", lang)}), 400

        _sync_user_timezone(uid)
        status = db.get_user_access_status(uid, language_hint=lang, notify_expired=False) or {}
        return jsonify(
            {
                "success": True,
                "plan_type": status.get("plan_type", "free"),
                "subscription_status": status.get("subscription_status", "free"),
                "trial_used": bool(status.get("trial_used")),
                "subscription_end_date": status.get("subscription_end_date"),
                "subscription_ends_at": status.get("subscription_ends_at"),
                "timezone": status.get("timezone", DEFAULT_TIMEZONE),
                "is_pro": bool(status.get("is_pro")),
                "is_admin": bool(status.get("is_admin")),
                "access_allowed": bool(status.get("access_allowed")),
                "has_active_subscription": bool(status.get("has_active_subscription")),
            }
        )

    @app.route("/api/trial/start", methods=["POST"])
    @_protected_route
    def trial_start():
        lang = _request_lang()
        uid = get_user_id_from_init_data(_request_init_data())
        if not uid:
            return jsonify({"success": False, "error": t("user_not_resolved", lang)}), 400

        status, activated = db.start_user_trial(uid, language=lang)
        if not activated and not bool((status or {}).get("access_allowed")):
            return jsonify(
                {
                    "success": False,
                    "error": t("trial_already_used", lang),
                    "payment_required": True,
                    "user": status,
                }
            ), 402

        return jsonify({"success": True, "activated": bool(activated), "user": status})

    @app.route("/api/payment/invoice", methods=["POST"])
    @_protected_route
    def payment_invoice():
        lang = _request_lang()
        uid = get_user_id_from_init_data(_request_init_data())
        if not uid:
            return jsonify({"success": False, "error": t("user_not_resolved", lang)}), 400

        try:
            invoice = crypto_pay.create_subscription_invoice(uid, language=lang)
        except Exception:
            logger.exception("Could not create Crypto Pay invoice for user_id=%s", uid)
            return jsonify({"success": False, "error": t("payment_invoice_error", lang)}), 500

        return jsonify(
            {
                "success": True,
                "invoice_url": invoice.get("invoice_url"),
                "invoice_id": invoice.get("invoice_id"),
                "amount": invoice.get("subscription_amount"),
                "asset": invoice.get("subscription_asset"),
                "days": invoice.get("subscription_days"),
            }
        )

    @app.route("/api/crypto_webhook", methods=["POST"])
    def crypto_webhook():
        raw_body = request.get_data() or b""
        signature = request.headers.get("crypto-pay-api-signature")
        if not crypto_pay.verify_webhook_signature(raw_body, signature):
            logger.warning("Crypto Pay webhook rejected: invalid signature")
            return jsonify({"ok": False, "error": "invalid_signature"}), 403

        update = request.get_json(silent=True) or {}
        if update.get("update_type") != "invoice_paid":
            return jsonify({"ok": True, "ignored": True})

        invoice = update.get("payload") or {}
        if not isinstance(invoice, dict) or invoice.get("status") != "paid":
            return jsonify({"ok": True, "ignored": True})

        payload = crypto_pay.parse_invoice_payload(invoice)
        try:
            uid = int(payload.get("user_id") or 0)
            days = int(payload.get("days") or SUBSCRIPTION_DAYS or 30)
        except (TypeError, ValueError):
            uid = 0
            days = int(SUBSCRIPTION_DAYS or 30)

        invoice_id = invoice.get("invoice_id")
        if not uid or not invoice_id:
            logger.warning("Crypto Pay webhook without user_id or invoice_id: %s", update)
            return jsonify({"ok": False, "error": "bad_payload"}), 400

        if not db.mark_payment_invoice_processed(invoice_id, uid):
            logger.info("Crypto Pay webhook duplicate ignored: invoice_id=%s user_id=%s", invoice_id, uid)
            return jsonify({"ok": True, "duplicate": True})

        status = db.activate_paid_subscription(uid, days=days)
        end_date = (status or {}).get("subscription_end_date")

        try:
            from notifier import notify_admin, send_signal

            notify_admin(f"💳 Оплата успішна\nuser_id: {uid}\ninvoice: {invoice_id}\nдоступ до: {end_date}")
            send_signal(uid, t("subscription_paid", "uk", date=(end_date or "∞")))
        except Exception:
            logger.debug("Could not send payment notifications", exc_info=True)

        return jsonify({"ok": True, "user_id": uid, "subscription_end_date": end_date})

    @app.route("/api/language", methods=["GET", "POST"])
    @_protected_route
    def language_settings():
        uid = get_user_id_from_init_data(_request_init_data())
        if not uid:
            return jsonify({"success": False, "error": t("user_not_resolved", _request_lang())}), 400

        requested_lang = request.values.get("language") or request.values.get("lang")
        if requested_lang:
            lang = db.set_user_language(uid, requested_lang)
        else:
            lang = _request_lang()

        timezone_name = _sync_user_timezone(uid)

        return jsonify({"success": True, "language": lang, "timezone": timezone_name})

    @app.route("/api/scanner/status", methods=["GET"])
    @_protected_route
    def scanner_status():
        return jsonify(app_state.get_scanner_state_snapshot())

    @app.route("/api/scanner/toggle", methods=["GET", "POST"])
    @_protected_route
    def scanner_toggle():
        cat = request.values.get("category")
        if cat in app_state.SCANNER_STATE:
            app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
            reactor.callLater(0.5, ctrader.start_price_subscriptions)
        return jsonify(app_state.get_scanner_state_snapshot())

    @app.route("/api/toggle_watchlist", methods=["GET", "POST"])
    @_protected_route
    def toggle_watchlist():
        lang = _request_lang()
        uid = get_user_id_from_init_data(_request_init_data())
        pair = (request.values.get("pair") or "").strip()

        if not uid:
            return jsonify({"success": False, "error": t("user_not_resolved", lang)}), 400

        if not pair:
            return jsonify({"success": False, "error": t("pair_required", lang)}), 400

        if _pair_key(pair) not in set(_collect_ui_pairs([])):
            return jsonify({"success": False, "error": t("pair_not_actual", lang)}), 400

        ok = db.toggle_watchlist(uid, pair.replace("/", "").upper())
        watchlist = db.get_watchlist(uid) if ok else []

        return jsonify(
            {
                "success": bool(ok),
                "watchlist": watchlist,
                "pair": pair.replace("/", "").upper(),
            }
        )

    @app.route("/api/signal")
    @_protected_route
    def api_signal():
        lang = _request_lang()
        pair = request.args.get("pair", "").strip()
        tf = request.args.get("timeframe", "15m").strip()
        uid = get_user_id_from_init_data(_request_init_data())

        if not pair:
            return jsonify({"success": False, "error": t("pair_required", lang)}), 400

        if not uid:
            return jsonify({"success": False, "error": t("user_not_resolved", lang)}), 400

        access, trial_started = db.ensure_trial_or_access(uid, language_hint=lang)
        if not access or not access.get("access_allowed"):
            return jsonify(
                {
                    "success": False,
                    "error": t("access_denied_subscription", lang),
                    "payment_required": True,
                    "user": access,
                    "pair": pair,
                    "timeframe": tf,
                    "verdict_text": "WAIT",
                    "score": 50,
                    "reasons": [t("access_denied_subscription", lang)],
                    "is_trade_allowed": False,
                }
            ), 402

        if app_state.SYMBOLS_LOADED and ctrader._resolve_broker_symbol(pair) is None:
            return jsonify(_unavailable_symbol_payload(pair, tf, lang))

        try:
            result = blockingCallFromThread(
                reactor,
                _call_analysis_in_reactor,
                pair,
                uid,
                tf,
                lang,
            )

            if not isinstance(result, dict):
                result = {
                    "pair": pair,
                    "timeframe": tf,
                    "verdict_text": "ERROR",
                    "score": 50,
                    "reasons": [t("bad_analysis_response", lang)],
                    "error": t("bad_analysis_response", lang),
                    "is_trade_allowed": False,
                }

            if trial_started:
                result["trial_started"] = True
                result["user"] = access

            return jsonify(localize_signal_payload(result, lang))

        except Exception as e:
            logger.exception("api_signal failed")

            msg = str(e)
            if msg in {"(45, 'Deferred')", "(50, 'Deferred')"} or "Deferred" in msg:
                msg = t("analysis_timeout", lang)
            elif "Timed out" in msg or "timeout" in msg.lower():
                msg = t("analysis_timeout", lang)
            else:
                msg = localize_reason(msg, lang)

            return jsonify(
                {
                    "success": False,
                    "error": msg,
                    "pair": pair,
                    "timeframe": tf,
                    "verdict_text": "ERROR",
                    "score": 50,
                    "reasons": [msg],
                    "is_trade_allowed": False,
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
        return t("not_found", _request_lang()), 404

    @app.route("/<path:filename>")
    def static_files(filename):
        return send_from_directory(WEBAPP_DIR, filename)
