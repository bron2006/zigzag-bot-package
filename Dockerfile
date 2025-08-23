# Dockerfile
# Використовуємо повну версію python, оскільки slim не має потрібних інструментів для збірки
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

# Завантажуємо, компілюємо і встановлюємо TA-Lib
RUN wget 'http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz' && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Встановлюємо Python-залежності
COPY requirements.txt .
# --- ПОЧАТОК ЗМІН: Виправляємо додавання TA-Lib ---
# Використовуємо echo -e "\nTA-Lib", щоб гарантовано додати бібліотеку з нового рядка
RUN echo -e "\nTA-Lib" >> requirements.txt && \
    pip install --no-cache-dir -r requirements.txt
# --- КІНЕЦЬ ЗМІН ---

COPY . .
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "app:app"]e