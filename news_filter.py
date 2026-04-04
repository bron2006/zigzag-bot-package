import os
import google.generativeai as genai

# Використовуємо ключ, який ти вже зберіг у Fly Secrets
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

def get_latest_news_sentiment(pair: str):
    """Gemini аналізує фон для пари."""
    try:
        prompt = f"Ти аналітик. Оціни фон для {pair}. Якщо є критичний негатив - пиши BLOCK, якщо все ок - пиши GO. Тільки одне слово."
        response = model.generate_content(prompt)
        verdict = response.text.strip().upper()
        return verdict if verdict in ['GO', 'BLOCK'] else 'GO'
    except:
        return "GO"