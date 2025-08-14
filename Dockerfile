# Використовуємо повну, а не slim-версію, щоб мати більше системних інструментів
FROM python:3.11-bullseye

# Встановлюємо робочий каталог
WORKDIR /app

# Оновлюємо систему та встановлюємо необхідні інструменти
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    cargo \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей та .whl файл
COPY requirements.txt .
COPY ctrader_open_api-0.0.0-py3-none-any.whl .

# Агресивне очищення перед установкою
RUN pip uninstall -y ctrader_open_api ctrader-open-api || true

# Встановлюємо залежності
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту файлів проєкту
COPY . .
# Документуємо порт
EXPOSE 8080

# Оновлена команда запуску Gunicorn з файлом конфігурації
CMD ["gunicorn", "-c", "gunicorn.conf.py", "bot:app"]