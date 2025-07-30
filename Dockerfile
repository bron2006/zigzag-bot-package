# Етап 1: Збірка образу ("Майстерня")
# --- ПОЧАТОК ЗМІН: Використовуємо більш стабільний образ ---
FROM python:3.11-bullseye as builder
# --- КІНЕЦЬ ЗМІН ---

# Встановлюємо системні залежності для компіляції TA-Lib
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Завантажуємо та компілюємо TA-Lib з вихідного коду
WORKDIR /tmp
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr && \
    make && \
    make install

# Встановлюємо Python залежності
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --prefix /install

# ---

# Етап 2: Робочий образ ("Виставковий зал")
# --- ПОЧАТОК ЗМІН: Використовуємо відповідний стабільний образ ---
FROM python:3.11-bullseye
# --- КІНЕЦЬ ЗМІН ---

# Копіюємо скомпільовану бібліотеку TA-Lib з першого етапу
COPY --from=builder /usr/lib/libta_lib.so.0 /usr/lib/libta_lib.so.0
COPY --from=builder /usr/lib/libta_lib.so.0.0.0 /usr/lib/libta_lib.so.0.0.0
RUN ldconfig

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