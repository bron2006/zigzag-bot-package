# analysis.py
import logging
from twisted.internet.defer import Deferred
from twisted.internet import reactor
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    '1min': ProtoOATrendbarPeriod.M1, '5min': ProtoOATrendbarPeriod.M5,
    '15min': ProtoOATrendbarPeriod.M15, '1hour': ProtoOATrendbarPeriod.H1,
    '4hour': ProtoOATrendbarPeriod.H4, '1day': ProtoOATrendbarPeriod.D1
}

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)

    if not symbol_details:
        return Deferred.fail(Exception(f"Деталі для {norm_pair} не знайдено в кеші."))

    trendbar_period = PERIOD_MAP.get(period)
    if not trendbar_period:
        return Deferred.fail(Exception(f"Невідомий період: {period}"))
    
    # ДОДАНО ЛОГУВАННЯ
    logger.info(f"Знайдено деталі для {norm_pair}. ID символу: {symbol_details.symbolId}")

    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=trendbar_period,
        count=count
    )

    logger.info(f"Роблю запит на отримання {count} свічок для {norm_pair}...")
    deferred = client.send(request, timeout=15) # Зменшимо таймаут для швидшої реакції
    
    def on_success(message):
        response = ProtoOAGetTrendbarsRes()
        response.ParseFromString(message.payload)
        logger.info(f"✅ Отримано {len(response.trendbar)} свічок для {norm_pair}.")
        d.callback(response.trendbar)

    def on_error(failure):
        # failure.getErrorMessage() може не існувати, тому робимо перевірку
        error_text = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
        logger.error(f"❌ Помилка отримання свічок для {norm_pair}: {error_text}")
        d.errback(failure)
        
    deferred.addCallbacks(on_success, on_error)
    return d

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int) -> Deferred:
    d = Deferred()
    deferred_bars = get_market_data(client, symbol_cache, symbol, '15min', 100)

    def on_bars_received(bars):
        try:
            if not bars:
                raise Exception("Отримано порожній список свічок.")

            last_bar = bars[-1]
            price_close = last_bar.close / 100000.0
            price_open = last_bar.open / 100000.0
            price_low = last_bar.low / 100000.0
            price_high = last_bar.high / 100000.0
            
            verdict = "🟢 Рекомендовано Купувати" if price_close > price_open else "🔴 Рекомендовано Продавати"
            
            result = {
                "pair": symbol, "price": price_close, "verdict_text": verdict,
                "support": price_low, "resistance": price_high,
                "reasons": [f"Аналіз останньої свічки на періоді M15."]
            }
            d.callback(result)
        except Exception as e:
            logger.error(f"Помилка під час аналізу свічок для {symbol}: {e}")
            d.errback(e)

    def on_bars_error(failure):
        d.errback(failure)

    deferred_bars.addCallbacks(on_bars_received, on_bars_error)
    return d