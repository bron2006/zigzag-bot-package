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

# Правильна команда для запуску веб-сервера gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "bot:app"]