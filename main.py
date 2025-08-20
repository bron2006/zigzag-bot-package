import os
import logging
import asyncio
from dotenv import load_dotenv
from threading import Thread, Event
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, Updater

from ctrader_open_api.ctrader_open_api_client import CTraderOpenAPIClient
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoMessage
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from queue import Queue, Empty

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

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
        self._loop = asyncio.new_event_loop()
        self._client = CTraderOpenAPIClient(API_HOST, API_PORT, self._on_message, loop=self._loop)
        self._token = token
        self.ctidTraderAccountId = None
        self._is_ready = Event()
        self._result_queue = Queue()

    def start_in_thread(self):
        thread = Thread(target=self.run_event_loop, daemon=True)
        thread.start()

    def run_event_loop(self):
        asyncio.set_event_loop(self._loop)
        self._client.start()
        self._loop.run_forever()

    async def _on_message(self, message: ProtoMessage):
        if message.payloadType == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Application authenticated")
            request = ProtoOAGetAccountListByAccessTokenReq()
            request.accessToken = self._token
            await self._client.send(request)

        elif message.payloadType == ProtoOAPayloadType.PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES:
            accounts = message.payload.ctidTraderAccount
            if accounts:
                self.ctidTraderAccountId = accounts[0].ctidTraderAccountId
                logger.info(f"Account ID set: {self.ctidTraderAccountId}")
                self._is_ready.set()
            else:
                logger.error("No accounts found for this access token.")

        elif message.payloadType == ProtoOAPayloadType.PROTO_OA_GET_TRENDBARS_RES:
            logger.info("Received trendbars")
            trendbars = message.payload.trendbar
            
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
                df.set_index('timestamp', inplace=True)
                df.ta.zigzag(inplace=True)
                zigzag_col = next((col for col in df.columns if 'ZIGZAG' in col), None)

                if zigzag_col:
                    pivots = df[df[zigzag_col].notna() & (df[zigzag_col] != 0)]
                    if len(pivots) >= 2:
                        last_pivot_value = pivots[zigzag_col].iloc[-1]
                        signal = 'BUY' if last_pivot_value == -1 else 'SELL'
                    else:
                        signal = "NEUTRAL"
                else:
                    signal = "ERROR: ZigZag indicator not calculated"
            else:
                signal = "NO DATA"
            
            result = (signal, datetime.now(ZoneInfo("Europe/Kyiv")).strftime('%Y-%m-%d %H:%M:%S'))
            self._result_queue.put(result)

    def _send_async_request(self, request):
        asyncio.run_coroutine_threadsafe(self._client.send(request), self._loop)

    def authenticate_app(self):
        request = ProtoOAApplicationAuthReq()
        request.clientId = CLIENT_ID
        request.clientSecret = CLIENT_SECRET
        self._send_async_request(request)

    def get_analysis_for_symbol(self, symbol_id, period, from_timestamp, to_timestamp):
        self._is_ready.wait(timeout=15) # Wait for client to be ready
        if not self._is_ready.is_set():
            return ("TIMEOUT (Client not ready)", "N/A")

        # Clear the queue before making a new request
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except Empty:
                continue

        request = ProtoOAGetTrendbarsReq()
        request.ctidTraderAccountId = self.ctidTraderAccountId
        request.symbolId = symbol_id
        request.period = period
        request.fromTimestamp = from_timestamp
        request.toTimestamp = to_timestamp
        
        self._send_async_request(request)
        
        try:
            # Wait for the result from the queue
            return self._result_queue.get(timeout=20)
        except Empty:
            return ("TIMEOUT (No response)", "N/A")

# --- Telegram Bot Handlers ---
clients = {} 
symbol_map = {
    "EURUSD": 1, "GBPUSD": 2, "USDJPY": 3, "AUDUSD": 5, "USDCAD": 6, 
    "NZDUSD": 7, "EURJPY": 9, "GBPJPY": 10, "EURGBP": 11, "XAUUSD": 22
}

def get_main_keyboard():
    buttons = [
        [InlineKeyboardButton(text=symbol, callback_data=symbol) for symbol in list(symbol_map.keys())[i:i+3]]
        for i in range(0, len(symbol_map), 3)
    ]
    return InlineKeyboardMarkup(buttons)

def get_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="back_to_main")]])

def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if len(context.args) == 0:
        update.message.reply_text("Please provide an access token. Usage: /start YOUR_TOKEN")
        return

    token = context.args[0]
    
    client = C_Trader_API(token=token)
    clients[user_id] = client
    client.start_in_thread()
    client.authenticate_app()
    
    update.message.reply_text("Welcome! Select a symbol to analyze:", reply_markup=get_main_keyboard())

def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    client = clients.get(user_id)

    if not client:
        query.edit_message_text(text="Client not initialized. Please use /start.")
        return

    if query.data == "back_to_main":
        query.edit_message_text(text="Select a symbol to analyze:", reply_markup=get_main_keyboard())
        return

    symbol_name = query.data
    symbol_id = symbol_map.get(symbol_name)

    if symbol_id:
        query.edit_message_text(text=f"Analyzing {symbol_name}, please wait...")
        
        to_timestamp = int(datetime.now().timestamp() * 1000)
        from_timestamp = int((datetime.now() - timedelta(days=90)).timestamp() * 1000)
        
        try:
            signal, timestamp = client.get_analysis_for_symbol(symbol_id, ProtoOATrendbarPeriod.H1, from_timestamp, to_timestamp)
            response_text = f"Analysis for {symbol_name}:\nSignal: {signal}\nLast Updated: {timestamp}"
        except Exception as e:
            logger.error(f"Error getting analysis: {e}")
            response_text = f"An error occurred: {e}"
        
        query.edit_message_text(text=response_text, reply_markup=get_back_keyboard())
    else:
        query.edit_message_text(text="Unknown symbol.", reply_markup=get_back_keyboard())

def main():
    updater = Updater(BOT_TOKEN)
    dispatcher = updater.dispatcher
    
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(button_callback))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()