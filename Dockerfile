# Dockerfile

# Використовуємо офіційний мінімалістичний образ Python
FROM python:3.11-slim

# --- FIX: Встановлюємо git-клієнт ---
# Це необхідно для того, щоб pip міг завантажувати бібліотеки з GitHub
RUN apt-get update && apt-get install -y git

# Встановлюємо робочу директорію
WORKDIR /app

# Копіюємо файл залежностей і встановлюємо їх
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/app/packages -r requirements.txt

# Копіюємо решту коду додатку
COPY . .

# Вказуємо Python, де шукати встановлені пакети
ENV PYTHONPATH=/app/packages

# Команда для запуску додатку
CMD ["python", "main.py"]