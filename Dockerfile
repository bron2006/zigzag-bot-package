# Dockerfile
FROM python:3.11-bullseye
WORKDIR /app

# Встановлюємо системні залежності для збірки TA-Lib
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    unzip \
    git \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Завантажуємо, компілюємо і встановлюємо системну бібліотеку TA-Lib
RUN wget 'http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz' && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Встановлюємо Python-залежності з файлу
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Запускаємо додаток напряму через Python, оскільки він використовує вбудований сервер Twisted.
CMD ["python", "app.py"]