# ZigZag Bot Package

Telegram-бот і Telegram Web App для аналізу ринкових даних через cTrader Open API.

## Можливості

- Аналіз Forex, криптовалют, індексів і сировини.
- Telegram Web App з пошуком активів, обраним списком, live-сигналами та live-цінами через SSE.
- ML-оцінка напрямку руху на базі RSI, ADX, ATR, EMA50 та EMA200.
- News-фільтр через OpenRouter, який може блокувати сигнали під час ризикових подій.
- Watchlist і історія сигналів через SQLAlchemy.
- Деплой на Fly.io через `fly.toml`.

## Швидкий старт

1. Створи локальний `.env` на основі `.env.example`.
2. Заповни Telegram, cTrader, database та OpenRouter змінні.
3. Запусти локально через Docker:

```bash
docker compose up --build
```

4. Відкрий health endpoint:

```text
http://localhost:8080/api/health
```

## Основні змінні середовища

- `TELEGRAM_BOT_TOKEN` - токен Telegram-бота.
- `CHAT_ID` - chat id адміністратора для сервісних повідомлень.
- `DATABASE_URL` - URL бази даних. Для Fly.io можна використовувати SQLite volume або Postgres.
- `CT_CLIENT_ID`, `CT_CLIENT_SECRET` - cTrader application credentials.
- `CTRADER_ACCESS_TOKEN`, `CTRADER_REFRESH_TOKEN`, `DEMO_ACCOUNT_ID` - cTrader account credentials.
- `OPENROUTER_API_KEY` - ключ для news-фільтра.
- `APP_MODE` - `full` завантажує ML-моделі, `light` запускає без них.

## Тести

У проєкті є unittest-тести для контракту аналізу та розрахунку features:

```bash
python -m unittest discover
```

## Деплой

```bash
fly deploy
```

Перед деплоєм переконайся, що secrets встановлені у Fly.io:

```bash
fly secrets list
```
