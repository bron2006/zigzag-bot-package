# ZigZag Bot Package

Telegram-бот і Telegram Web App для аналізу ринкових даних через cTrader Open API.

## Можливості

- Аналіз Forex, криптовалют, індексів і сировини.
- Telegram Web App з пошуком активів, обраним списком, live-сигналами та live-цінами через SSE.
- ML-оцінка напрямку руху на базі RSI, ADX, ATR, EMA50 та EMA200.
- News-фільтр на основі економічного календаря, який блокує сигнали під час ризикових подій.
- Watchlist і історія сигналів через SQLAlchemy.
- Відстеження результату сигналів (binary-option style: вгору/вниз/флет за
  фіксований горизонт, без TP/SL) і win-rate (`/api/stats/signals`, `/winrate`,
  кнопка "Win-rate" у Web App).
- Опціональний автотрейдер поверх cTrader Open API — вимкнений за замовчуванням
  (`AUTOTRADE_ENABLED=false`), керується адмін-командами `/autotrade_status`,
  `/autotrade_on`, `/autotrade_off`. Перехід на реальний рахунок можливий
  лише через ручну зміну `AUTOTRADE_ACCOUNT_MODE` на Fly.io.
- Опціональний **локальний** виконавець бінарних опціонів на Binomo
  (`binomo_executor.py`, Playwright) — див. розділ нижче. Вимкнений за
  замовчуванням, ніколи не деплоїться на Fly.io.
- Деплой сигнальної частини на Fly.io через `fly.toml`.

## Архітектура: сигнали (хмара) vs виконання (два окремих шари)

- **Сигнали** — аналіз/скан ринку через cTrader Open API. Працює в хмарі
  (Fly.io) як частина основного застосунку (`app.py`, `analysis.py`,
  `scanner.py`). Це джерело істини для якості сигналу.
- **Виконання №1: cTrader** (`autotrader.py`) — прямі форекс-ордери на тому
  ж cTrader-акаунті. Живе в хмарному процесі, вимкнений за замовчуванням.
- **Виконання №2: Binomo** (`binomo_executor.py`) — бінарні опціони через
  браузерну автоматизацію. Завжди окремий **локальний** процес (не хмара),
  бо стабільна IP-адреса й "звичний" браузерний відбиток важливіші для
  уникнення анти-бот детекції, ніж зручність деплою. Отримує сигнали з
  хмарного `/api/signal-stream` через `ADMIN_ACCESS_TOKEN`.

Сигнальний код нічого не знає про Binomo; `binomo_executor.py` не дублює
логіку аналізу — лише споживає вже готові сигнали.

## Локальний запуск Binomo executor

```bash
pip install -r requirements.txt -r requirements-executor.txt
playwright install chromium

# 1. Один раз: вручну залогінься (капчу/2FA проходиш сам), сесія збережеться
python binomo_executor.py --login

# 2. Спочатку ОБОВ'ЯЗКОВО: перевір, чи узгоджуються фіди cTrader і Binomo,
#    без жодних реальних угод, лише лог у logs/binomo_correlation_check.csv
python binomo_executor.py --correlation-check

# 3. Тільки після кількох днів перевірки й свого явного рішення:
python binomo_executor.py --run
```

Перед `--run` заповни `data/binomo_asset_map.json` реальними назвами
активів з живого терміналу Binomo (файл із шаблоном позначений
`"verified": false` — селектори DOM у `binomo_executor.py` теж позначені
`VERIFY-SELECTOR` і потребують звірки з реальною сторінкою, залогінитись
у яку може тільки власник акаунту).

## Швидкий старт

1. Створи локальний `.env` на основі `.env.example`.
2. Заповни Telegram, cTrader та database змінні.
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
- `APP_MODE` - `full` завантажує ML-моделі, `light` запускає без них.
- `NEWS_CALENDAR_URL` - джерело економічного календаря для news-фільтра (не потребує API-ключа).
- `ADMIN_ACCESS_TOKEN` - потрібен і на Fly.io (щоб відкривати Web App поза Telegram), і в
  локальному `.env` для `binomo_executor.py` (щоб читати `/api/signal-stream` та `/api/live_price`
  з хмарного інстансу). Решта Binomo-змінних (`BINOMO_*`) документовані в `.env.example` і
  потрібні лише локально, не на Fly.io.

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
