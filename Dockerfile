# Використовуємо офіційний образ Python
FROM python:3.9-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Встановлюємо git та sed
RUN apt-get update && apt-get install -y git sed && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей та встановлюємо їх
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Спочатку копіюємо всі файли проекту
COPY . .

# --- Крок регенерації Protobuf ---
# Клонуємо офіційний репозиторій з .proto файлами
RUN git clone https://github.com/spotware/openapi-proto-messages.git /tmp/proto-messages

# Створюємо директорію для скомпільованих файлів
RUN mkdir -p /app/ctrader_open_api/messages

# Компілюємо .proto файли, перезаписуючи існуючі
RUN python -m grpc_tools.protoc \
    -I=/tmp/proto-messages/ \
    --python_out=/app/ctrader_open_api/messages \
    /tmp/proto-messages/*.proto

# *** ВАЖЛИВИЙ КРОК: Виправляємо абсолютні імпорти на відносні у згенерованих файлах ***
RUN sed -i 's/^import \(.*_pb2\)/from . import \1/' /app/ctrader_open_api/messages/*_pb2.py

# Створюємо порожній __init__.py, щоб директорія розглядалась як Python-пакет
RUN touch /app/ctrader_open_api/messages/__init__.py

# Видаляємо тимчасовий репозиторій
RUN rm -rf /tmp/proto-messages
# --- Кінець кроку регенерації ---

# Вказуємо команду для запуску програми
CMD ["python", "run.py"]