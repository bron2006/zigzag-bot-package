# run.py
import os
import asyncio
import logging
import threading

# Імпорт після встановлення env/логів
from main import app, start_ctrader_client


def _start_ctrader_bg():
    """
    Запускає start_ctrader_client у бекґраунді.
    Працює і з sync, і з async реалізацією.
    """
    try:
        result = start_ctrader_client()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
    except Exception:
        logging.exception("start_ctrader_client failed")


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Стартуємо cTrader в окремому потоці, щоб не блокувати веб-сервер
    threading.Thread(target=_start_ctrader_bg, daemon=True).start()

    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
