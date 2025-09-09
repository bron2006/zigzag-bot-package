# Dockerfile
FROM python:3.11-bullseye
WORKDIR /app

# Встановлюємо системні залежності
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    unzip \
    git \
    curl \
    libssl-dev \
    libffi-dev \
    python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Встановлюємо системну бібліотеку TA-Lib
RUN wget 'http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz' && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# --- ПОЧАТОК ЗМІН: Використовуємо точну назву вашого файлу ---
COPY vendor/pandas_ta_openbb-0.4.22.tar.gz /app/vendor/
RUN pip install /app/vendor/pandas_ta_openbb-0.4.22.tar.gz
# --- КІНЕЦЬ ЗМІН ---

# Встановлюємо решту залежностей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8080

CMD ["python", "app.py"]