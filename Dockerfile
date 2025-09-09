# Dockerfile
FROM python:3.11-bullseye
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential wget unzip git curl libssl-dev libffi-dev python3-dev && \
    rm -rf /var/lib/apt/lists/*

RUN wget 'http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz' && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && ./configure --prefix=/usr && make && make install && cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Встановлюємо pandas-ta-openbb з локальної копії
COPY vendor/ /app/vendor/
RUN pip install /app/vendor/pandas-ta-openbb-0.4.22

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8080
CMD ["python", "app.py"]