import os
import logging
from google import genai

logger = logging.getLogger("news_filter")
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def get_latest_news_sentiment(pair: str):
    try:
        logger.info(f"🔍 Запит до Gemini для {pair}...")
        response = client.models.generate_content(
            model="gemini-flash-latest", 
            contents=f"Ти фінансовий аналітик. Оціни фон для {pair}. Якщо є критичний негатив - пиши BLOCK, якщо все ок - пиши GO. Тільки одне слово."
        )
        verdict = response.text.strip().upper()
        logger.info(f"🤖 Відповідь ШІ для {pair}: {verdict}")
        return "BLOCK" if "BLOCK" in verdict else "GO"
    except Exception as e:
        logger.error(f"❌ Помилка Gemini: {e}")
        return "GO"