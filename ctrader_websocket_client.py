# ctrader_websocket_client.py
import asyncio
import websockets
import pandas as pd
import time
from config import logger, CT_CLIENT_ID, CT_CLIENT_SECRET

from openapi_client.protobuf.OpenApiCommonMessages_pb2 import ProtoMessage
from openapi_client.protobuf.OpenApiModelMessages_pb2 import ProtoOAPayloadType, ProtoOATrendbarPeriod
from openapi_client.protobuf.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOASubscribeLiveTrendbarReq,
    ProtoOASpotEvent,
    ProtoOASubscribeLiveTrendbarRes,
    ProtoOAErrorRes # <-- ДОДАНО: імпорт для розшифровки помилки
)

SPOTWARE_WS_URL = "wss://demo.ctraderapi.com:5035"

async def _fetch_trendbars_async(access_token: str, account_id: int, symbol_id: int, timeframe: str) -> pd.DataFrame:
    try:
        async with websockets.connect(SPOTWARE_WS_URL) as ws:
            app_auth_req = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_REQ, payload=app_auth_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            await ws.recv()
            logger.info("✅ WebSocket: Аутентифікація додатку пройдена.")

            acc_auth_req = ProtoOAAccountAuthReq(ctidTraderAccountId=account_id, accessToken=access_token)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_REQ, payload=acc_auth_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            await ws.recv()
            logger.info(f"✅ WebSocket: Авторизація рахунку {account_id} пройдена.")

            tf_map = {'m1': ProtoOATrendbarPeriod.M1, '15m': ProtoOATrendbarPeriod.M15, '1h': ProtoOATrendbarPeriod.H1, '4h': ProtoOATrendbarPeriod.H4, '1day': ProtoOATrendbarPeriod.D1}
            tf_enum = tf_map.get(timeframe)
            if not tf_enum:
                logger.error(f"Невідомий таймфрейм для WebSocket: {timeframe}")
                return pd.DataFrame()

            subscribe_req = ProtoOASubscribeLiveTrendbarReq(ctidTraderAccountId=account_id, symbolId=symbol_id, period=tf_enum)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_SUBSCRIBE_LIVE_TRENDBAR_REQ, payload=subscribe_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            logger.info(f"📤 WebSocket: Надіслано запит на підписку (symbolId={symbol_id}, timeframe={timeframe}).")

            start_time = time.time()
            while time.time() - start_time < 20:
                response_data = await ws.recv()
                response_wrapper = ProtoMessage()
                response_wrapper.ParseFromString(response_data)
                
                # --- ПОЧАТОК ЗМІН: Додаємо обробку повідомлення про помилку ---
                if response_wrapper.payloadType == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
                    error_res = ProtoOAErrorRes()
                    error_res.ParseFromString(response_wrapper.payload)
                    logger.error(f"❌ WebSocket: Сервер cTrader повернув помилку! Код: {error_res.errorCode}, Опис: {error_res.description}")
                    return pd.DataFrame() # Виходимо з помилкою
                # --- КІНЕЦЬ ЗМІН ---

                if response_wrapper.payloadType == ProtoOAPayloadType.PROTO_OA_SUBSCRIBE_LIVE_TRENDBAR_RES:
                    logger.info(f"✅ WebSocket: Підписка на {symbol_id} успішна. Очікуємо дані...")
                    continue

                if response_wrapper.payloadType == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
                    event = ProtoOASpotEvent()
                    event.ParseFromString(response_wrapper.payload)

                    if not event.trendbar:
                        logger.warning(f"⚠️ WebSocket: Отримано SpotEvent, але він не містить трендбарів для {symbol_id}.")
                        return pd.DataFrame()

                    logger.info(f"📥 WebSocket: Отримано {len(event.trendbar)} свічок для {symbol_id}.")
                    
                    bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                             'Open': (bar.low + bar.deltaOpen) / 100000.0, 'High': (bar.low + bar.deltaHigh) / 100000.0,
                             'Low': bar.low / 100000.0, 'Close': (bar.low + bar.deltaClose) / 100000.0,
                             'Volume': bar.volume} for bar in event.trendbar]
                    
                    return pd.DataFrame(bars)
                
                logger.info(f"ℹ️ WebSocket: Отримано проміжне повідомлення типу: {response_wrapper.payloadType}")
            
            logger.error("❌ WebSocket: Час очікування даних про свічки вичерпано.")
            return pd.DataFrame()

    except Exception as e:
        logger.error(f"❌ Помилка WebSocket-клієнта: {e}", exc_info=True)
        return pd.DataFrame()

def fetch_trendbars_sync(access_token: str, account_id: int, symbol_id: int, timeframe: str) -> pd.DataFrame:
    logger.info("▶️ Запускаю синхронний запит на отримання даних через WebSocket...")
    return asyncio.run(_fetch_trendbars_async(access_token, account_id, symbol_id, timeframe))