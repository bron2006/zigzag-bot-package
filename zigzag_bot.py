import os
import logging
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler, CallbackContext

# 🔐 Токен і секрет вебхука
TOKEN = os.environ.get("TOKEN")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

# 🛡️ Видаляємо 'bot' префікс, якщо є
if TOKEN and TOKEN.startswith("bot"):
    TOKEN = TOKEN[3:]

# 🤖 Ініціалізація бота
bot = Bot(token=TOKEN)

# 🌐 Flask сервер
app = Flask(__name__)

# ⚙️ Dispatcher для обробки команд
dispatcher = Dispatcher(bot=bot, update_queue=None, use_context=True)

# ✅ Команди бота
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Бот запущено!")

def stop(update: Update, context: CallbackContext):
    update.message.reply_text("Бот зупинено!")

# 📦 Реєстрація хендлерів
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("stop", stop))

# 🔒 Вебхук лише по секретному шляху
@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK", 200

# 🔧 Тестовий ендпоінт (не обов’язковий)
@app.route("/", methods=["GET"])
def index():
    return "ZigZag бот працює!"
