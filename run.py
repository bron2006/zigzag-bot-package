# run.py
from twisted.internet import reactor
from main import app # Імпортуємо наш Klein-додаток з main.py

# --- КЛЮЧОВА ЗМІНА: ЗАПУСКАЄМО WEBSERVER ---
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)