# --- Етап 1: Будівництво ---
# Використовуємо стабільний образ Debian Bullseye, де є потрібні нам бібліотеки
FROM python:3.11-bullseye as builder

# Встановлюємо TA-Lib з репозиторію Debian. Це найнадійніший спосіб.
# libta-lib-dev містить файли, потрібні для компіляції Python-пакету.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libta-lib-dev \
    && rm -rf /var/lib/apt/lists/*

# Встановлюємо залежності Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Етап 2: Основний образ ---
FROM python:3.11-bullseye

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Kyiv

# Встановлюємо тільки рантайм-бібліотеку TA-Lib (libta-lib0) та tzdata для часової зони
RUN apt-get update && apt-get install -y --no-install-recommends \
    libta-lib0 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*
    
# Налаштовуємо часову зону
RUN ln -fs /usr/share/zoneinfo/Europe/Kyiv /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Копіюємо встановлені залежності Python з етапу builder
COPY --from=builder /install /usr/local
    
# Копіюємо код проєкту
COPY . /app
WORKDIR /app

# Документуємо порт, на якому працює застосунок
EXPOSE 8080

# Правильна команда для запуску веб-сервера gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "bot:app"]