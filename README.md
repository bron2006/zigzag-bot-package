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

`data/binomo_asset_map.json` та більшість селекторів у `SELECTORS`
(`binomo_executor.py`) звірені 2026-08-09 напряму з живим терміналом Binomo
(тільки читання DOM, жодних кліків на суму/угоду). Лишились відомі
прогалини, задокументовані в докстрінгу модуля:

- `asset_price_display` не існує — ціну Binomo малює лише у `<canvas>`,
  без жодного доступного DOM/SVG-тексту, тому `--correlation-check` поки
  не може читати ціну з боку Binomo (Binomo-сторона логується як
  `unknown`, доки це не вирішено інакше, напр. через перехоплення
  WebSocket).
- `login_email_input`/`login_password_input`/`login_submit_button` —
  все ще неперевірені (сторінку логіну не вдалось оглянути, бо акаунт
  вже залогінений). Впливає лише на необов'язковий автозаповнення при
  `--login`; при помилці воно й так безпечно просить заповнити вручну.
- Клікер часу експірації (`_set_expiry_time`) підбирає потрібний час
  через кнопки +/- (поле readonly, це не dropdown з готовими варіантами)
  і сам вираховує потрібну кількість кліків — але сам клік по цих кнопках
  жодного разу не тестувався наживо (лишався в режимі читання). Перш ніж
  довіряти `--run`, перевір це на одній ручній demo-угоді.
- `trade_history_row` — розмітка самого рядка історії угод не перевірена
  (на акаунті ще не було жодної угоди під час звірки), лишився
  scoped `:has-text()`-фолбек всередині перевіреного контейнера.

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
