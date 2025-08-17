# (замінити той же файл main.py у твому репо; виведено тільки оновлені/ключові частини для ясності -
# але у файловій системі покладай повний файл; якщо ти хочеш — я можу надіслати весь main.py знову)

# ... (верх main.py без змін)

def start_telegram_bot():
    token = get_telegram_token()
    if not token:
        logger.warning("TELEGRAM token не встановлено — Telegram бот не запущено.")
        return

    # створюємо asyncio loop у цьому потоці
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.info("Asyncio event loop створено у фоні для Telegram.")
    except Exception:
        logger.exception("Не вдалося створити asyncio loop для Telegram потоку.")
        return

    try:
        application = Application.builder().token(token).build()
        # register_handlers тепер синхронна функція (не coroutine)
        telegram_ui.register_handlers(application)
        logger.info("Запускаю Telegram бот (polling) у фоні...")
        # намагаємось запустити без додавання signal handlers (він падав у фон.потоці)
        try:
            application.run_polling(stop_signals=())
        except TypeError:
            # старіша версія PTB може не підтримувати stop_signals
            application.run_polling()
    except Exception:
        logger.exception("Помилка при запуску Telegram бота:")
