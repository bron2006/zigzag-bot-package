# price_streamer.py
import logging
import json
import time

from twisted.internet import reactor
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASubscribeSpotsReq, ProtoOASpotEvent
)
from redis_client import get_redis, set_tick

logger = logging.getLogger("price_streamer")
logger.setLevel(logging.INFO)


class PriceStreamer:
    def __init__(self, client, symbol_cache, pairs):
        """
        client        — cTrader OpenAPI клієнт
        symbol_cache  — кеш з описами символів
        pairs         — список торгових пар (['EURUSD', 'BTCUSD'] ...)
        """
        self.client = client
        self.symbol_cache = symbol_cache
        self.pairs = pairs

    def start(self):
        """
        Запускає підписку на всі необхідні пари
        """
        for norm_pair in self.pairs:
            symbol_details = self.symbol_cache.get(norm_pair)
            if not symbol_details:
                logger.warning(f"❌ Пара {norm_pair} не знайдена в кеші, пропускаю.")
                continue

            sub_req = ProtoOASubscribeSpotsReq(
                ctidTraderAccountId=self.client._client.account_id,
                symbolId=symbol_details.symbolId
            )

            d = self.client.send(sub_req, timeout=30)
            d.addCallbacks(
                lambda _: logger.info(f"✅ Підписався на {norm_pair}"),
                lambda f, p=norm_pair: logger.error(f"Не вдалося підписатися на {p}: {f}")
            )

        # слухаємо всі спот події
        self.client.add_listener(ProtoOASpotEvent, self._on_spot_event)

    def _on_spot_event(self, message):
        """
        Обробка тикових даних
        """
        try:
            event = ProtoOASpotEvent()
            event.ParseFromString(message.payload)

            if not event.bid and not event.ask:
                return

            norm_pair = None
            for k, v in self.symbol_cache.items():
                if v.symbolId == event.symbolId:
                    norm_pair = k
                    break
            if not norm_pair:
                return

            bid = event.bid[0].price / 10**5 if event.bid else None
            ask = event.ask[0].price / 10**5 if event.ask else None
            mid = None
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2

            tick_data = {
                "pair": norm_pair,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "ts_ms": int(time.time() * 1000)
            }

            # збереження в Redis
            try:
                r = get_redis()
                r.set(f"tick:{norm_pair}", json.dumps(tick_data))
                r.expire(f"tick:{norm_pair}", 60)  # 1 хв TTL
            except Exception as e:
                logger.exception(f"Помилка запису тіка {norm_pair} в Redis: {e}")

            logger.debug(f"Tick {norm_pair}: {tick_data}")

        except Exception as e:
            logger.exception(f"Помилка обробки spot event: {e}")


def run_price_streamer(client, symbol_cache, pairs):
    """
    Функція для запуску PriceStreamer
    """
    streamer = PriceStreamer(client, symbol_cache, pairs)
    streamer.start()
    reactor.run()
