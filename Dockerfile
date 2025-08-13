# Використовуємо повну, а не slim-версію, щоб мати більше системних інструментів
FROM python:3.11-bullseye

# Встановлюємо робочий каталог
WORKDIR /app

# Оновлюємо систему та встановлюємо всі необхідні інструменти для збірки
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    cargo \
    git \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей та встановлюємо їх
COPY requirements.txt .
# --- ВИПРАВЛЕНО КОМАНДУ ВСТАНОВЛЕННЯ ---
# Встановлюємо змінну середовища, щоб git не запитував пароль
RUN GIT_TERMINAL_PROMPT=0 pip install --no-cache-dir -r requirements.txt

# Копіюємо решту файлів проєкту
COPY . .
# Документуємо порт
EXPOSE 8080

# Оптимізована команда запуску Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "--worker-class", "gevent", "bot:app"]