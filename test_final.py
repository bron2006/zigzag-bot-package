import os
import sys
from dotenv import load_dotenv

try:
    from twisted.internet import reactor
    from ctrader_open_api import Client, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq, ProtoOAVersionReq, ProtoOAVersionRes
except ImportError as e:
    print(f"ПОМИЛКА: Не вдалося імпортувати залежності: {e}")
    sys.exit(1)

load_dotenv()
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")

print("--- Фінальний тест з Twisted Reactor ---")

if not CT_CLIENT_ID or not CT_CLIENT_SECRET:
    print("ПОМИЛКА: CT_CLIENT_ID або CT_CLIENT_SECRET не встановлені.")
    sys.exit(1)

def on_success(response):
    if response.payloadType == 2105: # ProtoOAVersionRes
        version_res = ProtoOAVersionRes()
        version_res.ParseFromString(response.payload)
        print("\n==========================================")
        print(f"✅ ТЕСТ УСПІШНИЙ! Зв'язок з API встановлено.")
        print(f"✅ Версія сервера cTrader: {version_res.version}")
        print("==========================================")
    else:
        print(f"✅ Отримано відповідь, але не на той запит (тип: {response.payloadType}). Авторизація, ймовірно, успішна.")
    
    if reactor.running:
        reactor.stop()

def on_error(error):
    error_message = getattr(error, 'getErrorMessage', lambda: str(error))()
    print(f"\n==========================================")
    print("❌ ТЕСТ ПРОВАЛЕНО!")
    print(f"❌ Причина: {error_message}")
    print("❌ Це на 99% означає, що ваші Client ID або Client Secret - НЕПРАВИЛЬНІ.")
    print("==========================================")
    if reactor.running:
        reactor.stop()

def send_requests(client):
    print("Відправка запиту на авторизацію додатку...")
    request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
    deferred = client.send(request)
    
    # Використовуємо callLater, щоб відправити наступний запит після невеликої паузи
    reactor.callLater(2, send_version_request, client)

def send_version_request(client):
    print("Відправка тестового запиту ProtoOAVersionReq...")
    request = ProtoOAVersionReq()
    deferred = client.send(request)
    deferred.addCallbacks(on_success, on_error)
    # Встановлюємо таймаут на випадок, якщо колбеки не спрацюють
    reactor.callLater(20, check_timeout)

def check_timeout():
    if reactor.running:
        print("\n==========================================")
        print("❌ ТЕСТ ПРОВАЛЕНО!")
        print("❌ Причина: Таймаут. Сервер не відповів на запит.")
        print("==========================================")
        reactor.stop()

def main():
    protocol = TcpProtocol()
    client = Client("demo.ctraderapi.com", 5035, protocol)
    # Запускаємо надсилання запитів, коли реактор буде готовий
    reactor.callWhenRunning(send_requests, client)
    
    print("Запуск реактора Twisted...")
    reactor.run()
    print("Реактор зупинено.")

if __name__ == "__main__":
    main()