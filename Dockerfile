# Етап 1: Збірка образу ("Майстерня")
FROM python:3.11-slim as builder

# Встановлюємо системні залежності для компіляції
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Розбиваємо компіляцію на кроки
WORKDIR /tmp

# Крок 1: Завантаження
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz -O ta-lib-0.4.0-src.tar.gz

# Крок 2: Розпакування
RUN tar -xzvf ta-lib-0.4.0-src.tar.gz

# Крок 3: Конфігурація
WORKDIR /tmp/ta-lib
RUN ./configure --prefix=/usr

# --- ПОЧАТОК ЗМІН: Прибираємо паралельну збірку ---
# Крок 4: Компіляція (в один потік для стабільності)
RUN make
# --- КІНЕЦЬ ЗМІН ---

# Крок 5: Встановлення
RUN make install


# Встановлюємо Python залежності
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --prefix /install

# ---

# Етап 2: Робочий образ ("Виставковий зал")
FROM python:3.11-slim

# Копіюємо скомпільовану бібліотеку TA-Lib з першого етапу
COPY --from=builder /usr/lib/libta_lib.so.0 /usr/lib/libta_lib.so.0
COPY --from=builder /usr/lib/libta_lib.so.0.0.0 /usr/lib/libta_lib.so.0.0.0

# Оновлюємо кеш завантажувача, щоб система "знала" про нову бібліотеку
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