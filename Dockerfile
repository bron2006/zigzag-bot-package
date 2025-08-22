# Етап 1: Збірка образу ("Майстерня")
FROM python:3.11-slim as builder

# Встановлюємо системні інструменти для компіляції (якщо потрібні)
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --prefix /install

# ---

# Етап 2: Робочий образ ("Виставковий зал")
FROM python:3.11-slim

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