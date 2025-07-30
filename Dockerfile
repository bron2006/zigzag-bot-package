# --- Етап 1: Будівництво ---
# Використовуємо стабільний образ, де є всі інструменти для компіляції
FROM python:3.11-bullseye as builder

# Встановлюємо системні залежності, необхідні для компіляції TA-Lib
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Завантажуємо, компілюємо та встановлюємо TA-Lib з вихідного коду.
# Це єдиний надійний метод.
WORKDIR /tmp
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr && \
    make && \
    make install

# Встановлюємо залежності Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Етап 2: Основний образ ---
FROM python:3.11-bullseye

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Kyiv

# Копіюємо тільки скомпільовані файли бібліотеки з етапу "builder"
COPY --from=builder /usr/lib/libta_lib.so.0 /usr/lib/libta_lib.so.0
COPY --from=builder /usr/lib/libta_lib.so.0.0.0 /usr/lib/libta_lib.so.0.0.0
RUN ldconfig

# Встановлюємо tzdata для налаштування часової зони
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
RUN ln -fs /usr/share/zoneinfo/Europe/Kyiv /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Копіюємо встановлені залежності Python з етапу builder
COPY --from=builder /install /usr/local
    
# Копіюємо код проєкту
COPY . /app
WORKDIR /app

# Документуємо порт
EXPOSE 8080

# Правильна команда для запуску веб-сервера gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "bot:app"]