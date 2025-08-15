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

def run_test(host, port, description):
    print(f"\n--- Тестування {description} ({host}:{port}) ---")
    
    if not CT_CLIENT_ID or not CT_CLIENT_SECRET:
        print("ПОМИЛКА: CT_CLIENT_ID або CT_CLIENT_SECRET не встановлені.")
        return

    protocol = TcpProtocol()
    client = Client(host, port, protocol)
    response_event = threading.Event()
    error_message = None
    success = False

    def on_success(response):
        nonlocal success
        success = True
        response_event.set()

    def on_error(error):
        nonlocal error_message
        error_message = error
        response_event.set()

    deferred = None
    try:
        time.sleep(2)
        print("Відправка запиту на авторизацію додатку...")
        request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
        deferred = client.send(request)
        deferred.addCallback(on_success)
        deferred.addErrback(on_error)

        if not response_event.wait(timeout=20):
            raise TimeoutError("Таймаут. Сервер не відповів.")

        if error_message:
            # Це може бути очікувана помилка, якщо ми отримали відповідь
            print(f"⚠️  Сервер відповів помилкою: {error_message}")
        elif success:
            print("✅  Сервер відповів успішно!")
        
    except Exception as e:
        print(f"❌  Критична помилка тесту: {e}")
    finally:
        if hasattr(client, "stop"):
            client.stop()

# --- Запускаємо тести ---
run_test("demo.ctraderapi.com", 5035, "ДЕМО-СЕРВЕРА")
run_test("live.ctraderapi.com", 5035, "БОЙОВОГО (LIVE) СЕРВЕРА")