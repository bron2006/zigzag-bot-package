# Етап 1: Збірка образу ("Майстерня")
# --- ПОЧАТОК ЗМІН: Використовуємо повний, а не slim, образ Python ---
FROM python:3.11 as builder
# --- КІНЕЦЬ ЗМІН ---

# Встановлюємо системні залежності
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Завантажуємо та компілюємо TA-Lib з вихідного коду, що є найнадійнішим методом
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
# --- ПОЧАТОК ЗМІН: Також використовуємо повний образ для стабільності ---
FROM python:3.11
# --- КІНЕЦЬ ЗМІН ---

# Копіюємо скомпільовану бібліотеку TA-Lib з першого етапу
COPY --from-builder /usr/lib/libta_lib.so.0 /usr/lib/libta_lib.so.0
COPY --from-builder /usr/lib/libta_lib.so.0.0.0 /usr/lib/libta_lib.so.0.0.0
RUN ldconfig

# Додаємо шлях до встановлених бібліотек до системних змінних
ENV PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.11/site-packages"

WORKDIR /app

# Спочатку копіюємо код вашого додатка
COPY . .
# Потім копіюємо бібліотеки
COPY --from-builder /install /install

# Запускаємо додаток
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "bot:app"]