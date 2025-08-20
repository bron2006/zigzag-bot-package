# Dockerfile

# Використовуємо офіційний мінімалістичний образ Python
FROM python:3.11-slim

# Встановлюємо системні залежності
RUN apt-get update && apt-get install -y git

# Встановлюємо робочу директорію
WORKDIR /app

# --- Крок 1: Встановлюємо проблемну бібліотеку ГЛОБАЛЬНО ---
COPY git_requirements.txt .
RUN pip install --no-cache-dir -r git_requirements.txt

# --- Крок 2: Встановлюємо решту бібліотек ЛОКАЛЬНО ---
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/app/packages -r requirements.txt

# Копіюємо решту коду додатку
COPY . .

# Вказуємо Python, де шукати локальні пакети
ENV PYTHONPATH=/app/packages

# Команда для запуску додатку
CMD ["python", "main.py"]