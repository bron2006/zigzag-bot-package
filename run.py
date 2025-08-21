import os
import sys
from klein import Klein
from twisted.internet import reactor
from twisted.web.server import Site
from twisted.python import log  # <-- 1. Імпортуємо логгер Twisted
from spotware_connect import SpotwareConnect

app = Klein()
# Логування тепер глобальне, тому окремий logger не потрібен

@app.route("/")
def index(request):
    log.msg("Web root requested.")  # <-- 2. Використовуємо log.msg
    return b"Hello, cTrader bot is running!"

def on_ctrader_ready():
    log.msg("cTrader Client готовий. Запитую символи...")
    d = ctrader_client.get_all_symbols()
    d.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(response):
    symbols = response.symbol
    log.msg(f"Завантажено {len(symbols)} символів.")
    # Тут буде подальша логіка...

def on_symbols_error(failure):
    log.err(failure)  # <-- 3. Використовуємо log.err для помилок
    log.msg(f"Не вдалося завантажити символи: {failure.getErrorMessage()}")

def start_services():
    # 4. Запускаємо спостерігача логів, щоб вони виводились у консоль
    log.startLogging(sys.stdout)
    
    try:
        web_port = int(os.environ.get("PORT", 8080))
        site = Site(app.resource())
        reactor.listenTCP(web_port, site, interface='0.0.0.0')
        log.msg(f"Веб-сервер запущено на порту {web_port}")
        
        # Ініціалізуємо клієнт після запуску логування
        global ctrader_client
        ctrader_client = SpotwareConnect()
        
        ctrader_client.on("ready", on_ctrader_ready)
        ctrader_client.start()

        log.msg("Запуск головного циклу reactor...")
        reactor.run()
    except Exception as e:
        log.err(e) # Використовуємо log.err для виводу помилок
        if reactor.running:
            reactor.stop()

if __name__ == "__main__":
    start_services()