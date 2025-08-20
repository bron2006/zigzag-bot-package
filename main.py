# main.py

import logging
from twisted.internet import reactor
# Імпортуємо компоненти з нашої локальної папки ctrader_open_api
from ctrader_open_api.client import Client
from ctrader_open_api.protocol import TcpProtocol # Ймовірно, ви мали на увазі tcpProtocol.py
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq
from ctrader_open_api.protobuf import Protobuf
from ctrader_open_api.auth import Auth

from config import HOST, PORT, SSL, APP_CLIENT_ID, APP_CLIENT_SECRET, ACCESS_TOKEN, ACCOUNT_ID

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Глобальні змінні для колбеків ---
client_instance = None

def on_message_received(client, message):
    """
    Обробник для всіх вхідних повідомлень від сервера.
    """
    payload_type = message.payloadType
    logging.info(f"Message Received: {payload_type} ({Protobuf.ProtoOAPayloadType.Name(payload_type)})")

    # 1. Після успішної авторизації додатку, авторизуємо торговий рахунок
    if payload_type == Protobuf.ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
        logging.info("Application authorized successfully. Now authorizing account...")
        auth_req = ProtoOAAccountAuthReq(ctidTraderAccountId=ACCOUNT_ID, accessToken=ACCESS_TOKEN)
        deferred = client.send(auth_req)
        deferred.addErrback(on_error, "Account Auth")

    # 2. Після успішної авторизації рахунку, бот готовий до роботи
    elif payload_type == Protobuf.ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
        logging.info("Account authorized successfully. Bot is ready.")
        #
        # ТУТ ПОЧИНАЄТЬСЯ ОСНОВНА ЛОГІКА ВАШОГО БОТА
        #

def on_connected(client):
    """
    Викликається, коли з'єднання з сервером встановлено.
    """
    global client_instance
    client_instance = client
    logging.info("Client connected to server. Authorizing application...")
    auth_req = ProtoOAApplicationAuthReq(clientId=APP_CLIENT_ID, clientSecret=APP_CLIENT_SECRET)
    deferred = client.send(auth_req)
    deferred.addErrback(on_error, "Application Auth")


def on_disconnected(client, reason):
    """
    Викликається при роз'єднанні. Зупиняє роботу програми.
    """
    logging.warning(f"Client disconnected from server. Reason: {reason.getErrorMessage()}")
    if reactor.running:
        reactor.stop()

def on_error(failure, context="Unknown"):
    """
    Обробник помилок.
    """
    logging.error(f"An error occurred in '{context}': {failure.getErrorMessage()}")
    if reactor.running:
        reactor.stop()

def main():
    """
    Головна функція для запуску.
    """
    try:
        # Правильна ініціалізація, як того вимагає наданий вами код
        protocol = TcpProtocol
        client = Client(HOST, PORT, protocol)

        # Встановлюємо колбеки
        client.setConnectedCallback(on_connected)
        client.setDisconnectedCallback(on_disconnected)
        client.setMessageReceivedCallback(on_message_received)

    except Exception as e:
        logging.error(f"Failed to initialize client: {e}")
        exit()

    logging.info("Starting cTrader client...")
    client.startService()
    logging.info("Twisted Reactor is running. Press Ctrl+C to stop.")
    reactor.run()
    logging.info("Reactor stopped. Exiting.")

if __name__ == "__main__":
    main()