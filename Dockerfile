# Dockerfile

# --- Етап 1: "Будівельник" ---
# Створюємо тимчасове середовище для чистого встановлення бібліотек
FROM python:3.11-slim as builder

WORKDIR /app

# Встановлюємо залежності, необхідні для збірки
RUN pip install --upgrade pip

COPY requirements.txt .
# Встановлюємо всі бібліотеки в окрему папку
RUN pip wheel --no-cache-dir --wheel-dir=/app/wheels -r requirements.txt


# --- Етап 2: "Фінальний образ" ---
# Створюємо чистий образ, в який перенесемо все готове
FROM python:3.11-slim

WORKDIR /app

# Копіюємо вже скомпільовані та завантажені бібліотеки з "будівельника"
COPY --from=builder /app/wheels /wheels/
COPY requirements.txt .
# Встановлюємо бібліотеки з локальних файлів, а не з інтернету
RUN pip install --no-cache-dir --no-index --find-links=/wheels/ -r requirements.txt

# Копіюємо код нашого додатку
COPY . .

# Вказуємо команду для запуску
CMD ["python", "main.py"]