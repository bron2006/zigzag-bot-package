# Dockerfile

FROM python:3.11-slim
WORKDIR /app

# Копіюємо всі файли проекту
COPY . .

# Встановлюємо залежності
RUN pip install --no-cache-dir -r requirements.txt

# FIX: Вказуємо правильний файл для запуску
CMD ["python", "run.py"]