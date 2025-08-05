# bot.py (тимчасова версія для верифікації)
from flask import Flask, send_from_directory

app = Flask(__name__)

@app.route('/')
def serve_index():
    """Подає головну сторінку-візитку."""
    return send_from_directory('landing_page', 'index.html')

@app.route('/privacy')
def serve_privacy():
    """Подає сторінку політики конфіденційності."""
    return send_from_directory('landing_page', 'privacy.html')

# Цей блок потрібен для локального тестування, gunicorn його ігнорує
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)