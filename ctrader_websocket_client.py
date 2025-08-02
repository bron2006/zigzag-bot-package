# ctrader_websocket_client.py
import asyncio
import pandas as pd
from config import logger, CT_CLIENT_ID, CT_CLIENT_SECRET

# Імпорти з офіційного SDK
from openapi_client import Client
from openapi_client.messages import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOASubscribeLiveTrendbarReq,
    ProtoOATrendbarEvent,
    ProtoMessage,
    ProtoOAPayloadType,
    ProtoOATrendbarPeriod
)

SPOTWARE_HOST = "demo.ctraderapi.com"
SPOTWARE_PORT = 5035

async def _fetch_trendbars_async(access_token: str, account_id: int, symbol_id: int, timeframe: str) -> pd.DataFrame:
    """Асинхронна функція для отримання даних через WebSocket з використанням SDK."""
    
    future = asyncio.Future() # Створюємо "майбутній" об'єкт для очікування відповіді

    def on_message(message: ProtoMessage):
        """Ця функція буде обробляти всі вхідні повідомлення."""
        if message.payloadType == ProtoOAPayloadType.PROTO_OA_TRENDBAR_EVENT:
            event = ProtoOATrendbarEvent()
            event.ParseFromString(message.payload)
            logger.info(f"📥 WebSocket: Отримано {len(event.trendbar)} свічок для {symbol_id}.")
            
            # Конвертуємо дані в DataFrame
            bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                     'Open': bar.open / 100000.0, 'High': bar.high / 100000.0, 
                     'Low': bar.low / 100000.0, 'Close': bar.close / 100000.0, 
                     'Volume': bar.volume} for bar in event.trendbar]
            df = pd.DataFrame(bars)
            
            # Встановлюємо результат у future, щоб головна функція його отримала
            if not future.done():
                future.set_result(df)

    client = Client(SPOTWARE_HOST, SPOTWARE_PORT, use_ssl=True)
    client.set_listener(on_message)

    try:
        await client.connect()
        logger.info("✅ WebSocket: Підключення встановлено.")

        # Крок 1: Аутентифікація додатку
        app_auth_req = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
        await client.send(app_auth_req)
        logger.info("✅ WebSocket: Аутентифікація додатку пройдена.")

        # Крок 2: Авторизація рахунку
        acc_auth_req = ProtoOAAccountAuthReq(ctidTraderAccountId=account_id, accessToken=access_token)
        await client.send(acc_auth_req)
        logger.info(f"✅ WebSocket: Авторизація рахунку {account_id} пройдена.")

        # Крок 3: Підписка на свічки
        tf_map = {'15m': ProtoOATrendbarPeriod.M15, '1h': ProtoOATrendbarPeriod.H1, '4h': ProtoOATrendbarPeriod.H4, '1day': ProtoOATrendbarPeriod.D1}
        tf_enum = tf_map.get(timeframe, ProtoOATrendbarPeriod.H1)
        
        subscribe_req = ProtoOASubscribeLiveTrendbarReq(ctidTraderAccountId=account_id, symbolId=symbol_id, timeframe=tf_enum)
        await client.send(subscribe_req)
        logger.info(f"📤 WebSocket: Надіслано запит на підписку (symbolId={symbol_id}, timeframe={timeframe}).")

        # Крок 4: Очікуємо на дані
        # Чекаємо, доки on_message не отримає дані і не встановить результат у future
        result_df = await asyncio.wait_for(future, timeout=20)
        return result_df

    except Exception as e:
        logger.error(f"❌ Помилка WebSocket-клієнта: {e}", exc_info=True)
        return pd.DataFrame()
    finally:
        await client.disconnect()
        logger.info("🔌 WebSocket: З'єднання закрито.")


def fetch_trendbars_sync(access_token: str, account_id: int, symbol_id: int, timeframe: str) -> pd.DataFrame:
    """Синхронна 'обгортка' для виклику з основного коду бота."""
    logger.info("▶️ Запускаю синхронний запит на отримання даних через WebSocket...")
    return asyncio.run(_fetch_trendbars_async(access_token, account_id, symbol_id, timeframe))