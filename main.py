import os
import time
import logging
import requests
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# --- Налаштування логування ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Конфігурація ---
TOKEN = "8036106554:AAElZ3Xwh8615qB_uuKzOKqVpJoxz6kAR1o"
BASE_URL = "https://zigzag-bot-package.fly.dev/api"

# --- Кеш для валютних пар та сигналів ---
cache = {
    "ranked_pairs": None,
    "signals": {}
}

# --- Допоміжні функції для API ---
def fetch_ranked_pairs():
    try:
        resp = requests.get(f"{BASE_URL}/get_ranked_pairs", timeout=10)
        if resp.status_code == 200:
            cache["ranked_pairs"] = resp.json()
            return cache["ranked_pairs"]
        else:
            logger.warning("Помилка при fetch_ranked_pairs: %s", resp.text)
            return None
    except Exception as e:
        logger.error("Exception fetch_ranked_pairs: %s", e)
        return None

def fetch_signal(pair: str):
    try:
        resp = requests.get(f"{BASE_URL}/signal?pair={pair}", timeout=10)
        if resp.status_code == 200:
            cache["signals"][pair] = resp.json()
            return cache["signals"][pair]
        else:
            logger.warning("Помилка при fetch_signal: %s", resp.text)
            return None
    except Exception as e:
        logger.error("Exception fetch_signal: %s", e)
        return None

# --- Кнопки для меню ---
def build_keyboard():
    buttons = [
        [InlineKeyboardButton("Отримати рейтинг пар", callback_data="ranked_pairs")],
        [InlineKeyboardButton("Сигнал EUR/USD", callback_data="signal_EUR/USD")],
        [InlineKeyboardButton("Форсоване оновлення кешу", callback_data="force_cache")]
    ]
    return InlineKeyboardMarkup(buttons)

# --- Обробка команд Telegram ---
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привіт! Оберіть опцію:", 
        reply_markup=build_keyboard()
    )

def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data

    if data == "ranked_pairs":
        pairs = fetch_ranked_pairs()
        if pairs:
            text = "Рейтинг валютних пар:\n"
            for session, lst in pairs.get("forex", {}).items():
                text += f"\n{session}:\n"
                for p in lst:
                    text += f"- {p['ticker']} (active={p['active']})\n"
            query.edit_message_text(text=text)
        else:
            query.edit_message_text("Помилка при отриманні рейтингу пар.")
    
    elif data.startswith("signal_"):
        pair = data.split("_")[1]
        sig = fetch_signal(pair)
        if sig:
            query.edit_message_text(f"Сигнал для {pair}: {sig}")
        else:
            query.edit_message_text(f"Сигнал для {pair} недоступний.")
    
    elif data == "force_cache":
        # --- Крок 2: Форсоване оновлення кешу ---
        query.edit_message_text("Форсоване оновлення кешу...")
        Thread(target=force_cache_update, args=(query,)).start()

def force_cache_update(query):
    fetch_ranked_pairs()
    for session in cache["ranked_pairs"].get("forex", {}):
        for p in cache["ranked_pairs"]["forex"][session]:
            fetch_signal(p["ticker"])
    query.edit_message_text("Кеш оновлено успішно!")

# --- Запуск Telegram бота ---
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_callback))

    logger.info("Запускаю Telegram бота...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    # --- Попереднє завантаження кешу ---
    fetch_ranked_pairs()
    main()
