FROM python:3.11-slim-bullseye
WORKDIR /app
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
# Змінюємо команду запуску на новий файл run.py
CMD ["python", "run.py"]