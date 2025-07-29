# Етап 1: Збірка образу ("Майстерня")
FROM python:3.11-slim as builder

# --- ПОЧАТОК ЗМІН: Встановлюємо TA-Lib з репозиторію Debian ---
# Встановлюємо системні залежності ТА саму бібліотеку TA-Lib (версію для розробки)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libta-lib-dev \
    && rm -rf /var/lib/apt/lists/*
# --- КІНЕЦЬ ЗМІН ---

WORKDIR /app
COPY requirements.txt .
# Тепер pip має гарантовано знайти бібліотеку, встановлену через apt
RUN pip install --no-cache-dir -r requirements.txt --prefix /install

# ---

# Етап 2: Робочий образ ("Виставковий зал")
FROM python:3.11-slim

# --- ПОЧАТОК ЗМІН: Встановлюємо тільки рантайм-бібліотеку TA-Lib ---
# Вона потрібна для запуску програми, але не для її компіляції
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libta-lib0 \
    && rm -rf /var/lib/apt/lists/*
# --- КІНЕЦЬ ЗМІН ---

# Додаємо шлях до встановлених бібліотек до системних змінних
ENV PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.11/site-packages"

WORKDIR /app

# Спочатку копіюємо код вашого додатка
COPY . .
# Потім копіюємо бібліотеки
COPY --from=builder /install /install

# Запускаємо додаток
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "bot:app"]