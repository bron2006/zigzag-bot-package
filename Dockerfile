# Етап 1: Збірка образу ("Майстерня")
FROM python:3.11-slim as builder

# --- ПОЧАТОК ЗМІН: Встановлюємо TA-Lib ---
# Встановлюємо системні залежності
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Завантажуємо та компілюємо TA-Lib з вихідного коду
WORKDIR /tmp
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzvf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr && \
    make && \
    make install
# --- КІНЕЦЬ ЗМІН ---

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --prefix /install

# ---

# Етап 2: Робочий образ ("Виставковий зал")
FROM python:3.11-slim

# --- ПОЧАТОК ЗМІН: Копіюємо скомпільовану бібліотеку TA-Lib ---
COPY --from=builder /usr/lib/libta_lib.so.0 /usr/lib/libta_lib.so.0
COPY --from=builder /usr/lib/libta_lib.so.0.0.0 /usr/lib/libta_lib.so.0.0.0
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