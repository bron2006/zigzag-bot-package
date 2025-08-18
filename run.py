import os
from main import app  # Імпортуємо Klein app з нашого основного модуля

# Klein вимагає, щоб ресурс був визначений для запуску.
# app.run() використовує порт з оточення або 8080 за замовчуванням.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)