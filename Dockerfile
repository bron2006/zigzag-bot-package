# Dockerfile
FROM python:3.11-bullseye
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    unzip \
    git \
    curl && \
    rm -rf /var/lib/apt/lists/*

RUN wget 'http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz' && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

COPY requirements.txt .
RUN echo "TA-Lib" >> requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8080
# --- ПОЧАТОК ЗМІН: Додаємо --timeout 90 ---
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "90", "app:app"]
# --- КІНЕЦЬ ЗМІН ---