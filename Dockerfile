# Keep Python 3.11 and application requirements unchanged, but use the
# maintained Debian 12 image instead of the failing Bullseye package mirror.
FROM python:3.11-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    build-essential \
    wget \
    unzip \
    git \
    curl \
    libssl-dev \
    libffi-dev \
    libgomp1 \
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

# Fail the build before publishing if local credentials/executors slipped into
# the context, or the pinned model/runtime cannot load on the new base image.
RUN DATABASE_URL=sqlite:///:memory: AUTOTRADE_ENABLED=false BINOMO_EXECUTOR_ENABLED=false \
    python -c "from pathlib import Path; forbidden=['.env','storage_state.json','binomo_executor.py','vwap_executor.py']; assert not [p for p in forbidden if Path(p).exists()], 'Local-only files in cloud image'; import analysis, api, scanner, ml_models; ml_models.load_models(); assert ml_models.LGBM_MODEL is not None and ml_models.SCALER is not None, 'Model load failed'; import numpy as np; result=ml_models.LGBM_MODEL.predict_proba(ml_models.SCALER.transform(np.zeros((1,5)))); assert result.shape == (1,2) and np.isfinite(result).all(), 'Model smoke test failed'; print('Cloud runtime/model smoke test passed')"

EXPOSE 8080

CMD ["python", "app.py"]
