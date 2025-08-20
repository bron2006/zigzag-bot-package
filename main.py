# main.py

import logging
from twisted.internet import reactor
# FIX 1: Імпортуємо TcpProtocol безпосередньо з пакету, згідно з __init__.py
from ctrader_open_api import Client, Auth, Protobuf, TcpProtocol
# FIX 2: Імпортуємо функції для отримання конфігурації
from config import (
    get_ct_client_id, get_ct_client_secret, 
    get_ctrader_access_token, get_demo_account_id
)
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Глобальні змінні, отримані з функцій конфігурації ---
APP_CLIENT_ID = get_ct_client_id()
APP_CLIENT_SECRET = get_ct_client_secret()
ACCESS_TOKEN = get_ctrader_access_token()
ACCOUNT_ID = get_demo_account_id()
HOST = "demo.ctraderapi.com"
PORT = 5035

# --- Колбеки ---
def on_message_received(client, message):
    payload_type = message.payloadType
    logging.info(f"Message Received: {payload_type} ({Protobuf.ProtoOAPayloadType.Name(payload_type)})")

    if payload_type == Protobuf.ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
        logging.info("Application authorized successfully. Now authorizing account...")
        auth_req = ProtoOAAccountAuthReq(ctidTraderAccountId=ACCOUNT_ID, accessToken=ACCESS_TOKEN)
        deferred = client.send(auth_req)
        deferred.addErrback(on_error, "Account Auth")

    elif payload_type == Protobuf.ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
        logging.info("Account authorized successfully. Bot is ready.")

def on_connected(client):
    logging.info("Client connected to server. Authorizing application...")
    auth_req = ProtoOAApplicationAuthReq(clientId=APP_CLIENT_ID, clientSecret=APP_CLIENT_SECRET)
    deferred = client.send(auth_req)
    deferred.addErrback(on_error, "Application Auth")

def on_disconnected(client, reason):
    logging.warning(f"Client disconnected from server. Reason: {reason.getErrorMessage()}")
    if reactor.running:
        reactor.stop()

def on_error(failure, context="Unknown"):
    logging.error(f"An error occurred in '{context}': {failure.getErrorMessage()}")
    if reactor.running:
        reactor.stop()

def main():
    try:
        # Правильна ініціалізація згідно з наданими файлами
        client = Client(HOST, PORT, TcpProtocol)
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