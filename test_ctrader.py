import os
import threading
import time
from dotenv import load_dotenv

try:
    from ctrader_open_api import Client, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq,
        ProtoOAAccountAuthReq,
        ProtoOAVersionReq,
        ProtoOAVersionRes
    )
except ImportError:
    print("ПОМИЛКА: Не вдалося імпортувати 'ctrader_open_api'. Переконайтеся, що бібліотека встановлена.")
    exit()

# --- Завантажуємо змінні середовища ---
load_dotenv()
CT_CLIENT_ID = os.getenv("CT_CLIENT_ID")
CT_CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
CTRADER_ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
# Використовуємо DEMO_ACCOUNT_ID з конфігурації або стандартний
DEMO_ACCOUNT_ID = os.getenv("DEMO_ACCOUNT_ID", 9541520) 

print("--- Мінімальний тест підключення до cTrader ---")

# --- Перевірка наявності змінних ---
if not all([CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN]):
    print("ПОМИЛКА: Необхідні змінні середовища (CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN) не встановлені.")
    exit()

protocol = TcpProtocol()
client = Client("demo.ctraderapi.com", 5035, protocol)

# --- Глобальні змінні для результатів ---
response_event = threading.Event()
final_result = None
final_error = None

# --- Колбеки для об'єкта Deferred ---
def on_success(response):
    global final_result
    print(f"✅ Отримано успішну відповідь (тип: {response.payloadType})")
    final_result = response
    response_event.set()

def on_error(error):
    global final_error
    print(f"❌ Отримано помилку: {error}")
    final_error = error
    response_event.set()

try:
    print("Ініціалізація клієнта...")
    time.sleep(3) 

    print("Авторизація додатку...")
    auth_req = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
    client.send(auth_req)
    time.sleep(1) 

    print("Авторизація акаунту...")
    acc_auth_req = ProtoOAAccountAuthReq(ctidTraderAccountId=int(DEMO_ACCOUNT_ID), accessToken=CTRADER_ACCESS_TOKEN)
    client.send(acc_auth_req)
    time.sleep(1)

    print("Відправка тестового запиту ProtoOAVersionReq...")
    version_req = ProtoOAVersionReq()
    deferred = client.send(version_req)
    deferred.addCallback(on_success)
    deferred.addErrback(on_error)

    print("Очікування відповіді (до 20 секунд)...")
    if not response_event.wait(timeout=20):
        raise TimeoutError("Таймаут очікування відповіді.")

    if final_error:
        raise Exception(f"Тест провалено з помилкою від API: {final_error}")
    
    if final_result and final_result.payloadType == 2105: # 2105 = ProtoOAVersionRes
        version_res = ProtoOAVersionRes()
        version_res.ParseFromString(final_result.payload)
        print("\n==========================================")
        print(f"✅ ТЕСТ УСПІШНИЙ!")
        print(f"✅ Версія сервера cTrader: {version_res.version}")
        print("==========================================")
    else:
        raise Exception(f"Тест провалено. Отримано несподівану відповідь: {final_result}")

except Exception as e:
    print(f"\n==========================================")
    print(f"❌ ТЕСТ ПРОВАЛЕНО!")
    print(f"❌ Причина: {e}")
    print("==========================================")

finally:
    if hasattr(client, "stop"):
        print("Зупинка клієнта...")
        client.stop()