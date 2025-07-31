# Використовуємо легкий та стабільний slim-образ
FROM python:3.11-slim-bullseye

# Встановлюємо робочий каталог
WORKDIR /app

# Копіюємо файл залежностей та встановлюємо їх
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту файлів проєкту
COPY . .

# Документуємо порт
EXPOSE 8080

# --- ПОЧАТОК ЗМІН: Збільшуємо таймаут до 90 секунд ---
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "90", "bot:app"]
# --- КІНЕЦЬ ЗМІН ---