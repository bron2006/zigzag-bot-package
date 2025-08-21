# Використовуємо офіційний образ Python
FROM python:3.9-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Встановлюємо git, необхідний для клонування репозиторію
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей та встановлюємо їх
# Це прискорює білд, оскільки залежності перевстановлюються тільки якщо requirements.txt змінився
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Спочатку копіюємо всі файли проекту
COPY . .

# --- Крок регенерації Protobuf (тепер виконується ПІСЛЯ копіювання) ---
# Клонуємо офіційний репозиторій з .proto файлами
RUN git clone https://github.com/spotware/openapi-proto-messages.git /tmp/proto-messages

# Створюємо директорію для скомпільованих файлів, якщо її немає
# (Хоча після COPY вона вже має існувати, це для надійності)
RUN mkdir -p /app/ctrader_open_api/messages

# Компілюємо .proto файли, перезаписуючи існуючі старі файли в проекті
RUN python -m grpc_tools.protoc \
    -I=/tmp/proto-messages/ \
    --python_out=/app/ctrader_open_api/messages \
    /tmp/proto-messages/*.proto

# Створюємо порожній __init__.py, щоб директорія розглядалась як Python-пакет
RUN touch /app/ctrader_open_api/messages/__init__.py

# Видаляємо тимчасовий репозиторій, щоб зменшити розмір образу
RUN rm -rf /tmp/proto-messages
# --- Кінець кроку регенерації ---

# Вказуємо команду для запуску програми
CMD ["python", "run.py"]