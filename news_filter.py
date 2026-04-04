import os
from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def get_latest_news_sentiment(pair: str):
    try:
        response = client.models.generate_content(
            model="gemini-flash-latest", 
            contents=f"Ти фінансовий аналітик. Оціни фон для {pair}. Якщо є критичний негатив - пиши BLOCK, якщо все ок - пиши GO. Тільки одне слово."
        )
        verdict = response.text.strip().upper()
        return "BLOCK" if "BLOCK" in verdict else "GO"
    except Exception:
        return "GO"