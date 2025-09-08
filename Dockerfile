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
    curl && \
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

# --- ПОЧАТОК ЗМІН: Завантажуємо pandas-ta як ZIP-архів ---
RUN wget https://github.com/twopirllc/pandas-ta/archive/refs/heads/main.zip -O pandas-ta.zip && \
    unzip pandas-ta.zip && \
    pip install ./pandas-ta-main && \
    rm pandas-ta.zip && \
    rm -rf ./pandas-ta-main
# --- КІНЕЦЬ ЗМІН ---

# Встановлюємо Python-залежності з файлу
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8080

CMD ["python", "app.py"]