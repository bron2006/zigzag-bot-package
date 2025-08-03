# ctrader_websocket_client.py
import asyncio
import websockets
import pandas as pd
from config import logger, CT_CLIENT_ID, CT_CLIENT_SECRET

# Імпорти з правильної, нової директорії
from openapi_client.protobuf.OpenApiCommonMessages_pb2 import ProtoMessage
from openapi_client.protobuf.OpenApiModelMessages_pb2 import (
    ProtoOAPayloadType,
    ProtoOATrendbarPeriod
)
# --- ПОЧАТОК ЗМІН: Виправлено імпорти та логіку обробки повідомлень ---
from openapi_client.protobuf.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOASubscribeLiveTrendbarReq,
    ProtoOASpotEvent,
    ProtoOASubscribeLiveTrendbarRes
)
# --- КІНЕЦЬ ЗМІН ---

SPOTWARE_WS_URL = "wss://demo.ctraderapi.com:5035"

async def _fetch_trendbars_async(access_token: str, account_id: int, symbol_id: int, timeframe: str) -> pd.DataFrame:
    try:
        async with websockets.connect(SPOTWARE_WS_URL) as ws:
            # Крок 1: Аутентифікація додатку
            app_auth_req = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_REQ, payload=app_auth_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            await ws.recv() # Очікуємо відповідь-підтвердження
            logger.info("✅ WebSocket: Аутентифікація додатку пройдена.")

            # Крок 2: Авторизація торгового рахунку
            acc_auth_req = ProtoOAAccountAuthReq(ctidTraderAccountId=account_id, accessToken=access_token)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_REQ, payload=acc_auth_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            await ws.recv() # Очікуємо відповідь-підтвердження
            logger.info(f"✅ WebSocket: Авторизація рахунку {account_id} пройдена.")

            # Крок 3: Підписка на свічки
            tf_map = {'15m': ProtoOATrendbarPeriod.M15, '1h': ProtoOATrendbarPeriod.H1, '4h': ProtoOATrendbarPeriod.H4, '1day': ProtoOATrendbarPeriod.D1}
            tf_enum = tf_map.get(timeframe, ProtoOATrendbarPeriod.H1)

            subscribe_req = ProtoOASubscribeLiveTrendbarReq(ctidTraderAccountId=account_id, symbolId=symbol_id, period=tf_enum)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_SUBSCRIBE_LIVE_TRENDBAR_REQ, payload=subscribe_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            logger.info(f"📤 WebSocket: Надіслано запит на підписку (symbolId={symbol_id}, timeframe={timeframe}).")

            # --- ПОЧАТОК ЗМІН: Правильна обробка відповідей ---
            # Крок 4: Очікування підтвердження підписки
            response_data = await asyncio.wait_for(ws.recv(), timeout=15)
            response_wrapper = ProtoMessage()
            response_wrapper.ParseFromString(response_data)

            if response_wrapper.payloadType != ProtoOAPayloadType.PROTO_OA_SUBSCRIBE_LIVE_TRENDBAR_RES:
                logger.error(f"❌ WebSocket: Не вдалося підписатися. Отримано тип: {response_wrapper.payloadType}")
                return pd.DataFrame()
            
            logger.info(f"✅ WebSocket: Підписка на {symbol_id} успішна.")

            # Крок 5: Отримання даних про свічки (вони надходять у події ProtoOASpotEvent)
            data_event_data = await asyncio.wait_for(ws.recv(), timeout=15)
            data_wrapper = ProtoMessage()
            data_wrapper.ParseFromString(data_event_data)

            if data_wrapper.payloadType == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
                event = ProtoOASpotEvent()
                event.ParseFromString(data_wrapper.payload)

                if not event.trendbar:
                    logger.warning(f"⚠️ WebSocket: Отримано SpotEvent, але він не містить трендбарів для {symbol_id}.")
                    return pd.DataFrame()

                logger.info(f"📥 WebSocket: Отримано {len(event.trendbar)} свічок для {symbol_id}.")
                
                # Правильний розрахунок цін на основі нової структури
                bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                         'Open': (bar.low + bar.deltaOpen) / 100000.0,
                         'High': (bar.low + bar.deltaHigh) / 100000.0,
                         'Low': bar.low / 100000.0,
                         'Close': (bar.low + bar.deltaClose) / 100000.0,
                         'Volume': bar.volume}
                        for bar in event.trendbar]
                return pd.DataFrame(bars)
            else:
                logger.warning(f"⚠️ WebSocket: Отримано неочікуваний тип повідомлення з даними: {data_wrapper.payloadType}")
                return pd.DataFrame()
            # --- КІНЕЦЬ ЗМІН ---

    except Exception as e:
        logger.error(f"❌ Помилка WebSocket-клієнта: {e}", exc_info=True)
        return pd.DataFrame()

def fetch_trendbars_sync(access_token: str, account_id: int, symbol_id: int, timeframe: str) -> pd.DataFrame:
    logger.info("▶️ Запускаю синхронний запит на отримання даних через WebSocket...")
    return asyncio.run(_fetch_trendbars_async(access_token, account_id, symbol_id, timeframe))