import os
from dotenv import load_dotenv
from twisted.internet import reactor
from ctrader_open_api import Client, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes, ProtoOAErrorRes
)

load_dotenv()
CLIENT_ID = os.getenv("CT_CLIENT_ID")
CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")

print("--- Простейший тест на авторизацію через TCP API ---")

if not CLIENT_ID or not CLIENT_SECRET:
    print("ПОМИЛКА: CT_CLIENT_ID або CT_CLIENT_SECRET не встановлені.")
    reactor.stop()
    exit(1)

def on_response(message):
    if message.payloadType == ProtoOAApplicationAuthRes.payload_type:
        print("✅ Авторизація додатку пройдена успішно!")
    elif message.payloadType == ProtoOAErrorRes.payload_type:
        err = ProtoOAErrorRes()
        err.ParseFromString(message.payload)
        print(f"❌ Помилка від сервера: {err.errorCode} — {err.description}")
    else:
        print(f"ℹ Інша відповідь (payloadType={message.payloadType})")
    reactor.stop()

def main():
    protocol = TcpProtocol()
    client = Client("demo.ctraderapi.com", 5035, protocol)
    client.add_message_handler(lambda msg: on_response(msg))

    def send_auth():
        print("Відправляю ProtoOAApplicationAuthReq...")
        req = ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET)
        d = client.send(req)
        reactor.callLater(20, timeout)

    def timeout():
        print("⏱ Таймаут: відповідь не отримана.")
        reactor.stop()

    reactor.callWhenRunning(send_auth)
    print("Запуск реактора Twisted...")
    reactor.run()
    print("Реактор завершив роботу.")

if __name__ == "__main__":
    main()
