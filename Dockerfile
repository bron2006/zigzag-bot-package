# Dockerfile
# Використовуємо повну, а не slim-версію, щоб мати більше системних інструментів
FROM python:3.11-bullseye

# Встановлюємо робочий каталог
WORKDIR /app

# Оновлюємо систему та встановлюємо необхідні інструменти (включно з git)
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    cargo \
    netcat-openbsd \
    git \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей
COPY requirements.txt .

# Агресивне очищення перед установкою
RUN pip uninstall -y ctrader_open_api ctrader-open-api || true

# --- КЛЮЧОВЕ ВИПРАВЛЕННЯ: Встановлюємо проблемну бібліотеку окремо і напряму з GitHub ---
RUN pip install "ctrader-open-api @ git+https://github.com/spotware/OpenApiPy.git"

# Встановлюємо решту залежностей
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту файлів проєкту
COPY . .

# Документуємо порт
EXPOSE 8080

# Оновлена команда запуску Gunicorn з файлом конфігурації
CMD ["gunicorn", "-c", "gunicorn.conf.py", "bot:app"]