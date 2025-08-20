import asyncio
import os
from dotenv import load_dotenv
from ctrader_open_api.ctrader_open_api_client import CTraderOpenAPIClient
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoMessage
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from zigzag import zigzag
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart

# --- Environment and Configuration ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
API_HOST = "live.ctraderapi.com"
API_PORT = 5035

# --- CTrader API Client ---
class C_Trader_API:
    def __init__(self, token):
        self._client = CTraderOpenAPIClient(API_HOST, API_PORT, self._on_message)
        self._token = token
        self.ctidTraderAccountId = None
        self.analysis_results = {}
        self._is_ready = asyncio.Event()  # Подія для сигналізації про готовність

    def start(self):
        self._client.start()

    def stop(self):
        self._client.stop()

    async def _on_message(self, message: ProtoMessage):
        if message.payloadType == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            print("Application authenticated")
            request = ProtoOAGetAccountListByAccessTokenReq()
            request.accessToken = self._token
            await self._client.send(request)
        
        elif message.payloadType == ProtoOAPayloadType.PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES:
            accounts = message.payload.ctidTraderAccount
            if accounts:
                self.ctidTraderAccountId = accounts[0].ctidTraderAccountId
                print(f"Account ID set: {self.ctidTraderAccountId}")
                self._is_ready.set()  # Сигнал, що клієнт готовий до роботи
            else:
                print("No accounts found for this access token.")

        elif message.payloadType == ProtoOAPayloadType.PROTO_OA_GET_TRENDBARS_RES:
            print("Received trendbars")
            trendbars = message.payload.trendbar
            symbol_id = message.payload.symbolId
            
            df = pd.DataFrame([{
                'timestamp': bar.utcTimestampInMinutes,
                'open': bar.low + bar.deltaOpen,
                'high': bar.low + bar.deltaHigh,
                'low': bar.low,
                'close': bar.low + bar.deltaClose,
                'volume': bar.volume,
            } for bar in trendbars])
            
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='m')
                pivots = zigzag(df['open'], df['high'], df['low'], df['close'])
                last_pivots = pivots.tail(2)
                
                if len(last_pivots) >= 2:
                    last_pivot_type = last_pivots.iloc[-1]['type']
                    signal = 'BUY' if last_pivot_type == 'min' else 'SELL'
                else:
                    signal = "NEUTRAL"
            else:
                signal = "NO DATA"

            self.analysis_results[symbol_id] = (signal, datetime.now(ZoneInfo("Europe/Kyiv")).strftime('%Y-%m-%d %H:%M:%S'))

    def authenticate_app(self):
        request = ProtoOAApplicationAuthReq()
        request.clientId = CLIENT_ID
        request.clientSecret = CLIENT_SECRET
        asyncio.run_coroutine_threadsafe(self._client.send(request), self._client.loop)

    async def get_analysis_for_symbol(self, symbol_id, period, from_timestamp, to_timestamp):
        await self._is_ready.wait()  # 1. Чекаємо, доки клієнт буде повністю готовий

        # 2. Видаляємо старий результат, щоб завжди отримувати свіжі дані
        if symbol_id in self.analysis_results:
            del self.analysis_results[symbol_id]

        request = ProtoOAGetTrendbarsReq()
        request.ctidTraderAccountId = self.ctidTraderAccountId
        request.symbolId = symbol_id
        request.period = period
        request.fromTimestamp = from_timestamp
        request.toTimestamp = to_timestamp
        
        await self._client.send(request)
        
        # Чекаємо на результат
        while symbol_id not in self.analysis_results:
            await asyncio.sleep(0.1)
            
        return self.analysis_results[symbol_id]

# --- Telegram Bot ---
router = Router()
clients = {} 
symbol_map = {
    "EURUSD": 1, "GBPUSD": 2, "USDJPY": 3, "AUDUSD": 5, "USDCAD": 6, 
    "NZDUSD": 7, "EURJPY": 9, "GBPJPY": 10, "EURGBP": 11, "XAUUSD": 22
}

def create_main_keyboard():
    buttons = [
        [InlineKeyboardButton(text=symbol, callback_data=symbol) for symbol in list(symbol_map.keys())[i:i+3]]
        for i in range(0, len(symbol_map), 3)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def create_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="back_to_main")]])

@router.message(CommandStart())
async def start_handler(message: Message):
    token = message.text.split(' ')[1] if len(message.text.split(' ')) > 1 else None
    if not token:
        await message.answer("Please provide an access token with the /start command. Example: /start YOUR_TOKEN")
        return

    client = C_Trader_API(token=token)
    clients[message.from_user.id] = client
    client.start()
    client.authenticate_app()
    
    await message.answer("Welcome to the C-Trader Bot! Please select a symbol to analyze.", reply_markup=create_main_keyboard())

@router.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback_query: CallbackQuery):
    await callback_query.message.edit_text("Please select a symbol to analyze.", reply_markup=create_main_keyboard())

@router.callback_query()
async def button_callback(callback_query: CallbackQuery):
    client = clients.get(callback_query.from_user.id)
    if not client:
        await callback_query.answer("Client not initialized. Please use /start.", show_alert=True)
        return

    symbol_name = callback_query.data
    symbol_id = symbol_map.get(symbol_name)
    
    if symbol_id:
        try:
            await callback_query.answer("Analyzing, please wait...")

            to_timestamp = int(datetime.now().timestamp() * 1000)
            from_timestamp = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
            
            signal, timestamp = await client.get_analysis_for_symbol(
                symbol_id, 
                ProtoOATrendbarPeriod.H1, 
                from_timestamp, 
                to_timestamp
            )
            
            response_text = f"Analysis for {symbol_name}:\nSignal: {signal}\nLast Updated: {timestamp}"
            await callback_query.message.edit_text(response_text, reply_markup=create_back_keyboard())
        except Exception as e:
            print(f"Error during analysis: {e}")
            await callback_query.message.edit_text(f"An error occurred during analysis: {e}", reply_markup=create_back_keyboard())
    else:
        await callback_query.answer("Unknown symbol.", show_alert=True)

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped")