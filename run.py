# run.py
import os
from twisted.internet import reactor
# Імпортуємо 'app' з main.py, де вся логіка вже налаштована
from main import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # app.run() - це стандартний спосіб запуску Klein, який коректно стартує Twisted reactor
    app.run(host="0.0.0.0", port=port)