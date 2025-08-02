# ctrader_websocket_client.py
import asyncio
import websockets
import pandas as pd
from config import logger, CT_CLIENT_ID, CT_CLIENT_SECRET

# --- ПОЧАТОК ЗМІН: Виправляємо фінальний імпорт ---
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage, ProtoOAPayloadType
# --- КІНЕЦЬ ЗМІН ---
from ctrader_open_api.messages.OpenApiCommonModelMessages_pb2 import ProtoOATrendbarPeriod
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOASubscribeLiveTrendbarReq,
    ProtoOATrendbarEvent
)

SPOTWARE_WS_URL = "wss://demo.ctraderapi.com:5035"

async def _fetch_trendbars_async(access_token: str, account_id: int, symbol_id: int, timeframe: str) -> pd.DataFrame:
    try:
        async with websockets.connect(SPOTWARE_WS_URL) as ws:
            # Крок 1: Аутентифікація додатку
            app_auth_req = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_REQ, payload=app_auth_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            await ws.recv()
            logger.info("✅ WebSocket: Аутентифікація додатку пройдена.")

            # Крок 2: Авторизація торгового рахунку
            acc_auth_req = ProtoOAAccountAuthReq(ctidTraderAccountId=account_id, accessToken=access_token)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_REQ, payload=acc_auth_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            await ws.recv()
            logger.info(f"✅ WebSocket: Авторизація рахунку {account_id} пройдена.")

            # Крок 3: Підписка на свічки
            tf_map = {'15m': ProtoOATrendbarPeriod.M15, '1h': ProtoOATrendbarPeriod.H1, '4h': ProtoOATrendbarPeriod.H4, '1day': ProtoOATrendbarPeriod.D1}
            tf_enum = tf_map.get(timeframe, ProtoOATrendbarPeriod.H1)
            
            subscribe_req = ProtoOASubscribeLiveTrendbarReq(ctidTraderAccountId=account_id, symbolId=symbol_id, timeframe=tf_enum)
            wrapper_msg = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_SUBSCRIBE_LIVE_TRENDBAR_REQ, payload=subscribe_req.SerializeToString())
            await ws.send(wrapper_msg.SerializeToString())
            logger.info(f"📤 WebSocket: Надіслано запит на підписку (symbolId={symbol_id}, timeframe={timeframe}).")

            # Крок 4: Отримання даних
            response_data = await asyncio.wait_for(ws.recv(), timeout=15)
            
            response_wrapper = ProtoMessage()
            response_wrapper.ParseFromString(response_data)

            if response_wrapper.payloadType == ProtoOAPayloadType.PROTO_OA_TRENDBAR_EVENT:
                event = ProtoOATrendbarEvent()
                event.ParseFromString(response_wrapper.payload)
                
                logger.info(f"📥 WebSocket: Отримано {len(event.trendbar)} свічок для {symbol_id}.")
                
                bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                         'Open': bar.open / 100000.0, 'High': bar.high / 100000.0, 
                         'Low': bar.low / 100000.0, 'Close': bar.close / 100000.0, 
                         'Volume': bar.volume}
                        for bar in event.trendbar]
                return pd.DataFrame(bars)
            else:
                logger.warning(f"⚠️ WebSocket: Отримано неочікуваний тип повідомлення: {response_wrapper.payloadType}")
                return pd.DataFrame()

    except Exception as e:
        logger.error(f"❌ Помилка WebSocket-клієнта: {e}", exc_info=True)
        return pd.DataFrame()

def fetch_trendbars_sync(access_token: str, account_id: int, symbol_id: int, timeframe: str) -> pd.DataFrame:
    logger.info("▶️ Запускаю синхронний запит на отримання даних через WebSocket...")
    return asyncio.run(_fetch_trendbars_async(access_token, account_id, symbol_id, timeframe))