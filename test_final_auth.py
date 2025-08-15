import os
import sys
from dotenv import load_dotenv

try:
    from twisted.internet import reactor
    from ctrader_open_api import Client, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq,
        ProtoOAApplicationAuthRes,
        ProtoOAErrorRes
    )
except ImportError as e:
    print(f"ПОМИЛКА: Не вдалося імпортувати залежності: {e}")
    sys.exit(1)


load_dotenv()
CLIENT_ID = os.getenv("CT_CLIENT_ID")
CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")

print("--- Фінальний тест авторизації через Deferred Callbacks ---")

if not CLIENT_ID or not CLIENT_SECRET:
    print("ПОМИЛКА: CT_CLIENT_ID або CT_CLIENT_SECRET не встановлені.")
    if 'reactor' in locals() and reactor.running:
        reactor.stop()
    sys.exit(1)

def on_response(response):
    # Цей колбек тепер обробляє і успіх, і помилку від API
    if response.payloadType == ProtoOAApplicationAuthRes.payload_type:
        print("\n==========================================")
        print("✅ ТЕСТ УСПІШНИЙ! Авторизація додатку пройдена!")
        print("✅ Ваші Client ID та Secret - ПРАВИЛЬНІ.")
        print("==========================================")
    elif response.payloadType == ProtoOAErrorRes.payload_type:
        err = ProtoOAErrorRes()
        err.ParseFromString(response.payload)
        print("\n==========================================")
        print("❌ СЕРВЕР ПОВЕРНУВ ПОМИЛКУ!")
        print(f"❌ Код: {err.errorCode}")
        print(f"❌ Опис: {err.description}")
        print("==========================================")
    else:
        print(f"ℹ️  Отримано несподівану відповідь (payloadType={response.payloadType})")
    
    if reactor.running:
        reactor.stop()

def on_deferred_error(error_failure):
    # Цей колбек обробляє помилки на рівні Twisted (наприклад, збій з'єднання)
    error_message = error_failure.getErrorMessage()
    print(f"\n==========================================")
    print(f"❌ ТЕСТ ПРОВАЛЕНО! (Помилка Twisted)")
    print(f"❌ Причина: {error_message}")
    print("==========================================")
    if reactor.running:
        reactor.stop()

def main():
    protocol = TcpProtocol()
    client = Client("demo.ctraderapi.com", 5035, protocol)

    def send_auth():
        print("Відправляю ProtoOAApplicationAuthReq...")
        req = ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET)
        deferred = client.send(req)
        # Підписуємося на результат: on_response для успішної передачі, on_deferred_error для збою
        deferred.addCallbacks(on_response, on_deferred_error)
        reactor.callLater(20, timeout)

    def timeout():
        if reactor.running:
            print("\n==========================================")
            print("❌ ТЕСТ ПРОВАЛЕНО!")
            print("❌ Причина: Таймаут. Сервер не відповів на запит.")
            print("==========================================")
            reactor.stop()

    reactor.callWhenRunning(send_auth)
    print("Запуск реактора Twisted...")
    reactor.run()
    print("Реактор завершив роботу.")

if __name__ == "__main__":
    main()