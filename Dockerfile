# Dockerfile

# Використовуємо офіційний мінімалістичний образ Python
FROM python:3.11-slim

# Встановлюємо системні залежності (git потрібен для requirements.txt)
RUN apt-get update && apt-get install -y git

# Встановлюємо робочу директорію
WORKDIR /app

# Копіюємо файл залежностей
COPY requirements.txt .

# --- FIX: Встановлюємо ВСІ бібліотеки глобально, без --target ---
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту коду додатку
COPY . .

# Команда для запуску додатку
CMD ["python", "main.py"]