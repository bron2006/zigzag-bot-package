# Dockerfile

# Використовуємо офіційний мінімалістичний образ Python
FROM python:3.11-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Копіюємо файл залежностей
COPY requirements.txt .

# Встановлюємо ВСІ бібліотеки глобально
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту коду додатку
COPY . .

# Команда для запуску додатку
CMD ["python", "main.py"]