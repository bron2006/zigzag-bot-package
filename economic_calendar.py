# economic_calendar.py
import logging
import requests
from typing import Tuple, Optional
from datetime import datetime, timedelta, timezone

from config import get_finnhub_api_key

logger = logging.getLogger(__name__)

API_KEY = get_finnhub_api_key()
BASE_URL = "https://finnhub.io/api/v1/calendar/economic"

def check_for_imminent_news(pair: str) -> Tuple[bool, Optional[str]]:
    """
    Перевіряє наявність важливих новин для валют у парі через API Finnhub.
    """
    if not API_KEY:
        logger.warning("Finnhub API key is not configured. Skipping news check.")
        return False, None

    try:
        base_currency = pair[:3].upper()
        quote_currency = pair[3:].upper()
        
        # Визначаємо часовий проміжок для запиту (сьогодні)
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        # Робимо запит до API
        params = {'token': API_KEY, 'from': today, 'to': today}
        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status() # Перевіряємо наявність HTTP-помилок
        
        data = response.json()
        
        if not data or "economicCalendar" not in data:
            return False, None
            
        now = datetime.now(timezone.utc)
        imminent_window = now + timedelta(minutes=30) # Перевіряємо новини на 30 хв вперед

        for event in data["economicCalendar"]:
            event_time_utc = datetime.fromtimestamp(event['time'], tz=timezone.utc)

            # Перевіряємо, чи подія ще не відбулася і чи відбудеться скоро
            if now < event_time_utc < imminent_window:
                # Перевіряємо, чи подія стосується наших валют і чи вона важлива
                if event['impact'] == 'high' and event['currency'] in [base_currency, quote_currency]:
                    news_text = (
                        f"❗️УВАГА: СКОРО ВАЖЛИВІ НОВИНИ ({event['currency']})❗️\n"
                        f"Подія: {event['event']}"
                    )
                    logger.warning(f"High-impact news detected for {pair}: {event['event']}")
                    return True, news_text
        
        return False, None

    except requests.RequestException as e:
        logger.error(f"Помилка при запиті до Finnhub API: {e}")
        return False, None
    except Exception as e:
        logger.error(f"Помилка при обробці даних економічного календаря: {e}")
        return False, None