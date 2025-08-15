import os
import sys
from dotenv import load_dotenv
import time

try:
    from twisted.internet import reactor
    from ctrader_open_api import Client, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
except ImportError as e:
    print(f"ПОМИЛКА: Не вдалося імпортувати залежності: {e}")
    sys.exit(1)

load_dotenv()
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")

print("--- Найтиповіший тест: відправка запиту без обробки відповіді ---")

if not CT_CLIENT_ID or not CT_CLIENT_SECRET:
    print("ПОМИЛКА: CT_CLIENT_ID або CT_CLIENT_SECRET не встановлені.")
    sys.exit(1)

def main():
    def send_auth_request(client):
        print("Відправка запиту ProtoOAApplicationAuthReq...")
        request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
        client.send(request)
        print("Запит відправлено. Скрипт завершить роботу через 20 секунд.")
        # Зупиняємо реактор через 20 секунд, щоб побачити, чи було щось виведено в консоль
        reactor.callLater(20, reactor.stop)

    protocol = TcpProtocol()
    client = Client("demo.ctraderapi.com", 5035, protocol)
    
    # Запускаємо відправку запиту через 3 секунди після старту реактора
    reactor.callWhenRunning(lambda: reactor.callLater(3, send_auth_request, client))

    print("Запуск реактора Twisted...")
    reactor.run()
    print("Реактор зупинено. Перевірте, чи був вивід у консолі між запуском і зупинкою.")

if __name__ == "__main__":
    main()