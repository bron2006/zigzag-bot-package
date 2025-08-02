# Dockerfile
FROM python:3.11-slim-bullseye

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- ПОЧАТОК ЗМІН: Копіюємо папку SDK в образ ---
COPY openapi_client/ openapi_client/
# --- КІНЕЦЬ ЗМІН ---

COPY . .
EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "90", "bot:app"]