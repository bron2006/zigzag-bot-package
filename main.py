import logging
import os
import json
import queue
import threading
from urllib.parse import parse_qs, unquote
from klein import Klein
from twisted.internet import reactor, defer
from twisted.web.static import File
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

import state
from telegram_ui import start, menu, button_handler, reset_ui # Додано reset_ui
from spotware_connect import SpotwareClient
# ... (інші імпорти)

# ... (код без змін до init_telegram_bot)

def init_telegram_bot():
    state.updater = Updater(TOKEN, use_context=True)
    dispatcher = state.updater.dispatcher
    
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu))
    # --- НОВИЙ ОБРОБНИК: для відновлення меню ---
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, reset_ui))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))

    logger.info("✅ Обробники Telegram зареєстровані.")
    
    # ... (решта коду без змін до home)

@app.route("/")
def home(request):
    """--- ЗМІНА: Перенаправляє на WebApp для зручності ---"""
    app_name = get_fly_app_name()
    if app_name:
        webapp_url = f"https://{app_name}.fly.dev/webapp/index.html"
        request.redirect(webapp_url.encode('utf-8'))
        request.finish()
        return b"" # Повертаємо пустий байтовий рядок, оскільки Klein цього вимагає
    else:
        return b"WebApp URL is not configured."

@app.route('/webapp/', branch=True)
def webapp_static(request):
    # ... (код без змін)

# ... (решта коду без змін)