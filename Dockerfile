# Dockerfile

# Використовуємо офіційний мінімалістичний образ Python
FROM python:3.11-slim

# Встановлюємо системні залежності
RUN apt-get update && apt-get install -y git

# Встановлюємо робочу директорію
WORKDIR /app

# --- FIX: Найнадійніший спосіб встановлення бібліотеки ---
# Крок 1: Клонуємо офіційний репозиторій
RUN git clone https://github.com/spotware/OpenApiPy.git

# Крок 2: Встановлюємо бібліотеку з локального вихідного коду
RUN pip install --no-cache-dir ./OpenApiPy

# Крок 3: Встановлюємо решту залежностей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту коду додатку
COPY . .

# Команда для запуску додатку
CMD ["python", "main.py"]