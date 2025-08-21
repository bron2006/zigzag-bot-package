# Використовуємо офіційний образ Python
FROM python:3.9-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Встановлюємо git, необхідний для клонування репозиторію
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей та встановлюємо їх
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Крок регенерації Protobuf ---
# Клонуємо офіційний репозиторій з .proto файлами
RUN git clone https://github.com/spotware/openapi-proto-messages.git /tmp/proto-messages

# Створюємо директорію для скомпільованих файлів, якщо її немає
RUN mkdir -p /app/ctrader_open_api/messages

# Компілюємо .proto файли в Python код
RUN python -m grpc_tools.protoc \
    -I=/tmp/proto-messages/ \
    --python_out=/app/ctrader_open_api/messages \
    /tmp/proto-messages/*.proto

# Створюємо порожній __init__.py, щоб директорія розглядалась як Python-пакет
RUN touch /app/ctrader_open_api/messages/__init__.py

# Видаляємо тимчасовий репозиторій, щоб зменшити розмір образу
RUN rm -rf /tmp/proto-messages
# --- Кінець кроку регенерації ---

# Копіюємо решту файлів проекту
COPY . .

# Вказуємо команду для запуску програми
CMD ["python", "run.py"]