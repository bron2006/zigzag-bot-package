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
RUN wget 'http-equiv="Content-Type" content="text/html; charset=utf-8"'http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz' && \
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

# --- ПОЧАТОК ЗМІН: Діагностика на етапі збірки ---
# Ця команда покаже вміст файлу в логах збірки (видно під час fly deploy)
RUN echo "--- Content of assets.json at BUILD time: ---" && cat assets.json && echo "--- End of build-time content ---"
# --- КІНЕЦЬ ЗМІН ---

EXPOSE 8080

# --- ПОЧАТОК ЗМІН: Діагностика на етапі запуску ---
# Ця команда покаже вміст файлу в логах додатку (видно через fly logs) перед запуском Python
CMD ["sh", "-c", "echo '--- Content of assets.json at RUN time: ---' && cat assets.json && echo '--- End of run-time content ---' && python app.py"]
# --- КІНЕЦЬ ЗМІН ---