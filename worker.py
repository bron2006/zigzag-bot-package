# worker.py
import logging, os, json, time, itertools
from twisted.internet import reactor, threads
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import LoopingCall
from twisted.web.server import Site, NOT_DONE_YET
from klein import Klein
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

import state, telegram_ui
from spotware_connect import SpotwareConnect
from config import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from analysis import get_api_detailed_signal_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("worker")

DATA_DIR = "/data"; os.makedirs(DATA_DIR, exist_ok=True)
SCANNER_STATE_FILE = os.path.join(DATA_DIR, "scanner_state.json")

def get_scanner_state():
    try:
        with open(SCANNER_STATE_FILE, 'r') as f: return json.load(f)
    except: return {"forex": False, "crypto": False, "metals": False}

def save_scanner_state(state_data):
    with open(SCANNER_STATE_FILE, 'w') as f: json.dump(state_data, f)

save_scanner_state(get_scanner_state())

internal_api = Klein()
sse_clients = []

def broadcast_sse_signal(signal_data):
    sse_data = f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n".encode('utf-8')
    for req in list(sse_clients): reactor.callFromThread(req.write, sse_data)

def send_sse_ping():
    ping_data = b": ping\n\n"
    for req in list(sse_clients):
        reactor.callFromThread(req.write, ping_data)

def scan_assets(asset_type, asset_list):
    if not get_scanner_state().get(asset_type, False): return
    logger.info(f"SCANNER ({asset_type.upper()}): Starting...")
    def on_analysis_done(result, pair_name):
        try:
            if result and not result.get("error"):
                score = result.get('bull_percentage', 50)
                if score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD):
                    broadcast_sse_signal(result)
                    # ... a.s.o.
        except Exception as e:
            logger.error(f"SCANNER Error in on_analysis_done: {e}", exc_info=True)
    @inlineCallbacks
    def process_all_pairs():
        for pair in asset_list:
            try:
                result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, pair.replace('/',''), 0, "5m")
                on_analysis_done(result, pair)
            except Exception as e:
                logger.error(f"Error analyzing {pair}: {e}")
    threads.deferToThread(process_all_pairs)

def on_ctrader_ready():
    logger.info("cTrader client ready. Loading symbols...")
    d = state.client.get_all_symbols()
    d.addCallbacks(on_symbols_loaded, lambda f: logger.error(f"Failed symbols load: {f}"))

def on_symbols_loaded(raw_message):
    symbols_response = ProtoOASymbolsListRes(); symbols_response.ParseFromString(raw_message.payload)
    state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
    logger.info(f"✅ Loaded {len(state.symbol_cache)} symbols.")
    all_forex = list(set(itertools.chain.from_iterable(FOREX_SESSIONS.values())))
    LoopingCall(scan_assets, "forex", all_forex).start(90)
    LoopingCall(scan_assets, "crypto", CRYPTO_PAIRS).start(60)
    LoopingCall(scan_assets, "metals", COMMODITIES).start(120)

@internal_api.route("/status")
def get_status(request): request.setHeader('Content-Type', 'application/json'); return json.dumps(get_scanner_state())
@internal_api.route("/get_pairs")
def get_pairs(request): request.setHeader('Content-Type', 'application/json'); return json.dumps({"forex_sessions": FOREX_SESSIONS, "crypto": CRYPTO_PAIRS, "commodities": COMMODITIES}, ensure_ascii=False)
@internal_api.route("/toggle_scanner", methods=['POST'])
def toggle_scanner(request):
    content = json.loads(request.content.read()); stype = content.get('type')
    state_data = get_scanner_state(); state_data[stype] = not state_data.get(stype, False); save_scanner_state(state_data)
    logger.info(f"Toggled '{stype}' to {state_data[stype]}"); request.setHeader('Content-Type', 'application/json')
    return json.dumps({"success": True, "newState": state_data})

@internal_api.route("/analyze")
@inlineCallbacks
def analyze(request):
    pair = request.args.get(b"pair")[0].decode('utf-8'); tf = request.args.get(b"timeframe")[0].decode('utf-8')
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, pair, 0, tf)
    return json.dumps(result, ensure_ascii=False)

@internal_api.route("/signal-stream")
def sse(request):
    request.setHeader(b'Content-Type', b'text/event-stream; charset=utf-8')
    sse_clients.append(request)
    request.notifyFinish().addBoth(lambda _: sse_clients.remove(request) if request in sse_clients else None)
    return NOT_DONE_YET

if __name__ == "__main__":
    site = Site(internal_api.resource())
    reactor.listenTCP(8081, site, interface="0.0.0.0")

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    state.updater = updater
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))

    # FIX: Запускаємо updater напряму, без reactor.callInThread
    updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Telegram bot started.")

    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.client = client
    client.on("ready", on_ctrader_ready)
    reactor.callWhenRunning(client.start)
    
    LoopingCall(send_sse_ping).start(20)
    
    logger.info("Worker process started successfully.")
    reactor.run()