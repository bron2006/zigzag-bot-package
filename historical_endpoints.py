"""Bounded same-broker historical endpoint audit. Never submits orders."""
import math
import time

_busy = False
_last_started = 0.0
AUTO_RECOVERY_ENABLED = True  # Live BCH/AAVE/LINK endpoint comparisons matched exactly.
_attempted = {}
ASOF_MAX_AGE_SECONDS = 60  # Fixed research rule, not tuned to win/loss results.


def select_asof(bids, asks, deadline, max_age=ASOF_MAX_AGE_SECONDS):
    """Last independently timestamped sides at expiry; never a future price."""
    sides = []
    for ticks in (bids, asks):
        eligible = [(ts, price) for ts, price in ticks
                    if deadline - max_age <= ts <= deadline
                    and math.isfinite(ts) and math.isfinite(price) and price > 0]
        if not eligible:
            return None
        # Decoded ticks are chronological; the last event wins timestamp ties.
        sides.append(max(enumerate(eligible), key=lambda item: (item[1][0], item[0]))[1])
    (bt, bid), (at, ask) = sides
    if ask < bid:
        return None
    return dict(ts=deadline, bid=bid, ask=ask, mid=(bid + ask) / 2,
                bid_ts=bt, ask_ts=at, max_age=max(deadline-bt, deadline-at))


def decode_ticks(ticks, has_more, start_ms, end_ms):
    # cTrader transmits newest first; BOTH time and price are signed deltas
    # after the first absolute tick. Reject truncation/invalid wire evidence.
    if has_more or len(ticks) > 10000:
        raise ValueError("historical_ticks_truncated")
    result = []
    ts = price = 0
    for i, tick in enumerate(ticks):
        delta_ts, delta_price = int(tick.timestamp), int(tick.tick)
        if i and delta_ts > 0:
            raise ValueError("historical_tick_order")
        ts = ts + delta_ts if i else delta_ts
        price = price + delta_price if i else delta_price
        if not start_ms <= ts <= end_ms or price <= 0:
            raise ValueError("historical_tick_bounds")
        result.append((ts / 1000, price / 100000))
    return list(reversed(result))


def select_endpoint(bids, asks, deadline):
    events = {}
    for side, ticks in (("bid", bids), ("ask", asks)):
        for ts, price in ticks:
            if not all(math.isfinite(v) for v in (ts, price)) or price <= 0:
                raise ValueError("invalid_historical_price")
            events.setdefault(ts, {})[side] = price
    sides = {}
    for ts, changes in sorted(events.items()):
        for side, price in changes.items():
            sides[side] = (ts, price)
        if not deadline <= ts <= deadline + 5 or len(sides) != 2:
            continue
        bt, bid = sides["bid"]
        at, ask = sides["ask"]
        if 0 <= ts - bt <= 5 and 0 <= ts - at <= 5 and ask >= bid:
            return dict(ts=ts, mid=(bid + ask) / 2, bid=bid, ask=ask,
                        bid_ts=bt, ask_ts=at)
    return None


def fetch_on_reactor(pair, deadline, policy='strict'):
    """Called only on reactor; finite requests, current authenticated client."""
    from twisted.internet import defer, reactor
    from twisted.internet.task import deferLater
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTickDataReq, ProtoOAGetTickDataRes
    from state import app_state
    import ctrader
    import analysis

    if policy not in {'strict', 'asof60', 'asof300'}:
        return defer.fail(ValueError('invalid_history_policy'))
    global _busy, _last_started
    if _busy or time.monotonic() - _last_started < 1:
        return defer.fail(ValueError("history_request_busy"))
    _busy = True
    _last_started = time.monotonic()

    @defer.inlineCallbacks
    def fetch():
        client = app_state.client
        account = getattr(getattr(client, "_client", None), "account_id", None)
        symbol = ctrader._resolve_broker_symbol_exact(pair)
        if not account or not getattr(client, "is_authorized", False) or symbol is None:
            raise ValueError("history_client_not_ready")
        if not math.isfinite(deadline) or not 15 <= time.time() - deadline <= 604800:
            raise ValueError("history_deadline_not_closed")
        asof_age = 300 if policy == 'asof300' else ASOF_MAX_AGE_SECONDS
        start, end = (math.floor((deadline - asof_age) * 1000), math.floor(deadline * 1000)) if policy.startswith('asof') else (math.floor((deadline - 5) * 1000), math.floor((deadline + 5) * 1000))
        decoded = []
        counts = []
        for side in (1, 2):  # ProtoOAQuoteType BID, ASK
            if app_state.client is not client:
                raise ValueError("history_transport_changed")
            req = ProtoOAGetTickDataReq(ctidTraderAccountId=account, symbolId=symbol.symbolId,
                                       type=side, fromTimestamp=start, toTimestamp=end)
            # Share the scanner's historical-data semaphore and pacing.
            message = yield analysis._send_market_data_request(client, req, response_timeout=5).addTimeout(6, reactor)
            expected = ProtoOAGetTickDataRes()
            if message.payloadType != expected.payloadType:
                raise ValueError("history_response_error")
            expected.ParseFromString(message.payload)
            if expected.ctidTraderAccountId != account:
                raise ValueError("history_account_mismatch")
            decoded.append(decode_ticks(expected.tickData, expected.hasMore, start, end))
            counts.append(len(expected.tickData))
            if side == 1:
                yield deferLater(reactor, 0.3, lambda: None)
        if app_state.client is not client:
            raise ValueError("history_transport_changed")
        endpoint = select_asof(*decoded, deadline, max_age=asof_age) if policy.startswith('asof') else select_endpoint(*decoded, deadline)
        source = 'cTrader_asof300_diagnostic_v1' if policy == 'asof300' else ('cTrader_asof60_shadow_v1' if policy == 'asof60' else 'cTrader_historical_ticks_v1')
        return dict(endpoint=endpoint, source=source, complete=True, symbol_id=symbol.symbolId,
                    from_ms=start, to_ms=end, counts=counts,
                    ranges=[dict(first=ticks[0][0], last=ticks[-1][0]) if ticks else None for ticks in decoded],
                    # Bounded evidence around the selected quote, not secret/account data.
                    sides={name: [dict(ts=t, price=p) for t, p in ticks if policy.startswith('asof') or (endpoint and
                                  endpoint["ts"] - 5 <= t <= endpoint["ts"])]
                           for name, ticks in zip(("bid", "ask"), decoded)})

    def finished(result):
        global _busy
        _busy = False
        return result

    return fetch().addTimeout(14, reactor).addBoth(finished)


def validate_asof(history, deadline):
    if history.get('source') != 'cTrader_asof60_shadow_v1' or history.get('complete') is not True:
        return False
    if history.get('from_ms') != math.floor((deadline-ASOF_MAX_AGE_SECONDS)*1000) or history.get('to_ms') != math.floor(deadline*1000):
        return False
    try:
        sides = history['sides']
        ticks = [[(x['ts'], x['price']) for x in sides[name]] for name in ('bid', 'ask')]
        if history.get('counts') != [len(side) for side in ticks]:
            return False
        for side in ticks:
            if len(side) > 10000 or any(not all(isinstance(v, (int, float)) and math.isfinite(v) for v in tick)
                                      or not history['from_ms']/1000 <= tick[0] <= history['to_ms']/1000 or tick[1] <= 0 for tick in side):
                return False
        return select_asof(*ticks, deadline) == history.get('endpoint')
    except (KeyError, TypeError, ValueError):
        return False


def validate_recovery(history, deadline):
    """Validate price/time/provenance before any short database write."""
    if history.get("source") != "cTrader_historical_ticks_v1" or history.get("complete") is not True:
        return False
    if history.get("from_ms") != math.floor((deadline - 5) * 1000) or history.get("to_ms") != math.floor((deadline + 5) * 1000):
        return False
    quote = history.get("endpoint")
    if not isinstance(quote, dict):
        return False
    values = [quote.get(k) for k in ("ts", "mid", "bid", "ask", "bid_ts", "ask_ts")]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return False
    ts, mid, bid, ask, bt, at = values
    if not (deadline <= ts <= deadline + 5 and ts <= time.time() and
            0 < bid <= ask and mid == (bid + ask) / 2 and 0 <= ts - bt <= 5 and 0 <= ts - at <= 5):
        return False
    try:
        sides = history["sides"]
        replay = select_endpoint([(x["ts"], x["price"]) for x in sides["bid"]],
                                 [(x["ts"], x["price"]) for x in sides["ask"]], deadline)
        return replay == quote
    except (KeyError, TypeError, ValueError):
        return False


def recover_missing_endpoints():
    """Worker thread only; two bounded requests per minute, no DB lock during IO."""
    if not AUTO_RECOVERY_ENABLED:
        return
    import db
    import logging
    from twisted.internet import reactor
    from twisted.internet.threads import blockingCallFromThread
    if not reactor.running:
        return
    count = 0
    now = time.monotonic()
    for identifier in db.get_recoverable_signal_ids():
        if now - _attempted.get(identifier, -1e10) < 3600:
            continue
        row = db.get_signal_endpoint_audit(identifier)
        if not row or row['evidence'].get('history_check') or row['evidence'].get('reason') not in {
                'no_valid_quote_in_5s_window', 'last_complete_quote_before_deadline', 'first_complete_quote_after_window'}:
            continue
        if not 15 <= time.time() - row['deadline'] <= 604800:
            continue
        _attempted[identifier] = now
        count += 1
        try:
            result = blockingCallFromThread(reactor, fetch_on_reactor, row['pair'], row['deadline'])
            recovered = bool(result.get('endpoint')) and db.recover_signal_endpoint(identifier, result)
            if not result.get('endpoint'):
                db.record_signal_history_check(identifier, result)
            logging.getLogger(__name__).info('ENDPOINT_RECOVERY: id=%s recovered=%s counts=%s',
                                             identifier, recovered, result.get('counts'))
        except Exception:
            _attempted[identifier] = now - 3540  # retry transient failure in one minute
            logging.getLogger(__name__).warning('ENDPOINT_RECOVERY: request failed id=%s', identifier)
        if count >= 2:
            break
    if len(_attempted) > 1000:
        for identifier in list(_attempted)[:500]:
            _attempted.pop(identifier, None)
    # Shared total budget: at most TWO broker-history probes per worker cycle.
    for identifier in db.get_asof_audit_ids(limit=max(0, 2-count)) if count < 2 else []:
        row = db.get_signal_endpoint_audit(identifier)
        if not row or not 15 <= time.time()-row['deadline'] <= 604800:
            continue
        try:
            result = blockingCallFromThread(reactor, fetch_on_reactor, row['pair'], row['deadline'], 'asof60')
            db.save_signal_asof_audit(identifier, result)
        except Exception:
            logging.getLogger(__name__).warning('ASOF_AUDIT: request failed id=%s', identifier)
