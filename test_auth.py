# test_auth.py
import os
import threading
import time
from dotenv import load_dotenv

try:
    from ctrader_open_api import Client, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
except ImportError:
    print("ПОМИЛКА: Не вдалося імпортувати 'ctrader_open_api'.")
    exit()

load_dotenv()
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")

print("--- Мінімальний тест АВТЕНТИФІКАЦІЇ ДОДАТКУ ---")

if not CT_CLIENT_ID or not CT_CLIENT_SECRET:
    print("ПОМИЛКА: CT_CLIENT_ID або CT_CLIENT_SECRET не встановлені.")
    exit()

protocol = TcpProtocol()
client = Client("demo.ctraderapi.com", 5035, protocol)

response_event = threading.Event()
error_message = None

def on_success(response):
    response_event.set()

def on_error(error):
    global error_message
    error_message = error
    response_event.set()

try:
    time.sleep(2)
    print("Відправка запиту на авторизацію додатку...")
    request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
    deferred = client.send(request)
    deferred.addCallback(on_success)
    deferred.addErrback(on_error)

    if not response_event.wait(timeout=20):
        raise TimeoutError("Таймаут. Сервер не відповів на запит авторизації.")

    if error_message:
        raise Exception(f"Помилка від API: {error_message}")
    
    print("\n==========================================")
    print("✅ ТЕСТ УСПІШНИЙ! Авторизація додатку пройдена.")
    print("✅ Це означає, що Client ID та Secret - правильні.")
    print("==========================================")

except Exception as e:
    print(f"\n==========================================")
    print("❌ ТЕСТ ПРОВАЛЕНО!")
    print(f"❌ Причина: {e}")
    print("❌ Це на 99% означає, що ваші Client ID або Client Secret - НЕПРАВИЛЬНІ.")
    print("==========================================")

finally:
    if hasattr(client, "stop"):
        client.stop()