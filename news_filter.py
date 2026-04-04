import os
import logging
from google import genai
from google.genai import types

logger = logging.getLogger("news_filter")
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def get_latest_news_sentiment(pair: str):
    try:
        logger.info(f"🔍 Бліц-аналіз {pair}...")
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=f"Context: {pair}. Verdict (GO or BLOCK only).",
            config=types.GenerateContentConfig(
                max_output_tokens=5,
                temperature=0
            )
        )
        verdict = response.text.strip().upper()
        logger.info(f"🤖 ШІ: {verdict}")
        return "BLOCK" if "BLOCK" in verdict else "GO"
    except Exception as e:
        logger.error(f"❌ Помилка: {e}")
        return "GO"