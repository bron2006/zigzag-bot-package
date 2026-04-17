FROM python:3.11-bullseye

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

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

RUN wget 'http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz' && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

COPY vendor/pandas_ta_openbb-0.4.22.tar.gz /app/vendor/
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "app.py"]
