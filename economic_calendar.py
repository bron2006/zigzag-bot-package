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
    # Функцію вимкнено, оскільки вона вимагає платної підписки Finnhub
    return False, None

    # Весь код нижче більше не буде виконуватися
    if not API_KEY:
        logger.warning("Finnhub API key is not configured. Skipping news check.")
        return False, None

    try:
        base_currency = pair[:3].upper()
        
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        params = {'token': API_KEY, 'from': today, 'to': today}
        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if not data or "economicCalendar" not in data:
            return False, None
            
        now = datetime.now(timezone.utc)
        imminent_window = now + timedelta(minutes=30)

        for event in data["economicCalendar"]:
            event_time_utc = datetime.fromtimestamp(event['time'], tz=timezone.utc)

            if now < event_time_utc < imminent_window:
                if event['impact'] == 'high' and event['currency'] == base_currency:
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