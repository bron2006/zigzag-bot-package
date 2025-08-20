# Dockerfile
# Use the official Python image.
FROM python:3.11-slim

# Cache buster: 2025-08-20 20:52:00 EEST
WORKDIR /app

# Copy the requirements file into the container.
COPY requirements.txt .

# Install the dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container.
COPY . .

# Set the command to run the application.
CMD ["python", "main.py"]