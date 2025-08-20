# main.py

import logging
from twisted.internet import reactor
# Імпортуємо всі необхідні компоненти для стабільної версії
from ctrader_open_api import Client, Auth, Protobuf
from ctrader_open_api.protocol import OpenApiProtocol
from config import HOST, PORT, SSL, APP_CLIENT_ID, APP_CLIENT_SECRET, ACCESS_TOKEN, ACCOUNT_ID

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    # Правильна ініціалізація, як того вимагає бібліотека
    protocol = OpenApiProtocol()
    client = Client(HOST, PORT, protocol)
except Exception as e:
    logging.error(f"Failed to initialize client: {e}")
    exit()

def on_message_received(message):
    logging.info(f"Message Received: {message.payloadType} ({Protobuf.ProtoOAPayloadType.Name(message.payloadType)})")
    if message.payloadType == Protobuf.ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
        logging.info("Application authorized successfully. Now authorizing account...")
        client.send(Auth.authorize_token(ACCESS_TOKEN, ACCOUNT_ID)).addErrback(on_error)
    elif message.payloadType == Protobuf.ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
        logging.info("Account authorized successfully. Bot is ready.")

def on_connected():
    logging.info("Client connected to server. Authorizing application...")
    client.send(Auth.authorize_app(APP_CLIENT_ID, APP_CLIENT_SECRET)).addErrback(on_error)

def on_disconnected():
    logging.warning("Client disconnected from server.")
    if reactor.running:
        reactor.stop()

def on_error(failure):
    logging.error(f"An error occurred: {failure.getErrorMessage()}")
    if client.is_running() and reactor.running:
         reactor.stop()

# Події тепер прив'язуються до об'єкта protocol, як того вимагає структура бібліотеки
protocol.events.on_connected(on_connected)
protocol.events.on_disconnected(on_disconnected)
protocol.events.on_message_received(on_message_received)
protocol.events.on_error(on_error)

def main():
    logging.info("Starting cTrader client...")
    client.start()
    logging.info("Twisted Reactor is running. Press Ctrl+C to stop.")
    reactor.run()
    logging.info("Reactor stopped. Exiting.")

if __name__ == "__main__":
    main()