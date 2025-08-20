# main.py

import logging
from twisted.internet import reactor
# Імпортуємо тільки те, що дійсно існує в офіційній бібліотеці
from ctrader_open_api import Client, Auth, Protobuf
from config import HOST, PORT, SSL, APP_CLIENT_ID, APP_CLIENT_SECRET, ACCESS_TOKEN, ACCOUNT_ID

# FIX: Виправлено помилку форматування в налаштуваннях логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Створюємо екземпляр клієнта
try:
    # FIX: Видалено всі зайві аргументи. Це правильний виклик для офіційної бібліотеки.
    client = Client(HOST, PORT)
except Exception as e:
    logging.error(f"Failed to initialize client: {e}")
    exit()

def on_message_received(message):
    """
    Обробник для всіх вхідних повідомлень від сервера.
    """
    logging.info(f"Message Received: {message.payloadType} ({Protobuf.ProtoOAPayloadType.Name(message.payloadType)})")

    if message.payloadType == Protobuf.ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
        logging.info("Application authorized successfully. Now authorizing account...")
        deferred = client.send(Auth.authorize_token(ACCESS_TOKEN, ACCOUNT_ID))
        deferred.addErrback(on_error)

    elif message.payloadType == Protobuf.ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
        logging.info("Account authorized successfully. Bot is ready.")
        #
        # ТУТ ПОЧИНАЄТЬСЯ ОСНОВНА ЛОГІКА ВАШОГО БОТА
        #

def on_connected():
    """
    Викликається, коли з'єднання з сервером встановлено.
    """
    logging.info("Client connected to server. Authorizing application...")
    deferred = client.send(Auth.authorize_app(APP_CLIENT_ID, APP_CLIENT_SECRET))
    deferred.addErrback(on_error)

def on_disconnected():
    """
    Викликається при роз'єднанні. Зупиняє роботу програми.
    """
    logging.warning("Client disconnected from server.")
    if reactor.running:
        reactor.stop()

def on_error(failure):
    """
    Обробник помилок. Записує помилку в лог і зупиняє роботу.
    """
    logging.error(f"An error occurred: {failure.getErrorMessage()}")
    if client.is_running() and reactor.running:
         reactor.stop()

# Прив'язуємо наші функції безпосередньо до подій клієнта
client.events.on_connected(on_connected)
client.events.on_disconnected(on_disconnected)
client.events.on_message_received(on_message_received)
client.events.on_error(on_error)

def main():
    """
    Головна функція для запуску.
    """
    logging.info("Starting cTrader client...")
    client.start()
    logging.info("Twisted Reactor is running. Press Ctrl+C to stop.")
    reactor.run()
    logging.info("Reactor stopped. Exiting.")

if __name__ == "__main__":
    main()