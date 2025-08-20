# Dockerfile
# Use the official Python image.
FROM python:3.11-slim

# Add a cache-buster argument. Changing this value will invalidate the cache.
ARG CACHE_BUSTER=1

# Set the working directory in the container.
WORKDIR /app

# Set the PYTHONPATH environment variable to include a local packages directory.
ENV PYTHONPATH=/app/packages

# Copy the requirements file.
COPY requirements.txt .

# Install dependencies into the local packages directory.
RUN pip install --no-cache-dir --target=/app/packages -r requirements.txt

# Copy the rest of the application code.
COPY . .

# Set the command to run the application.
CMD ["python", "main.py"]