# Dockerfile
# Use the official Python image.
FROM python:3.11-slim

# Set the working directory in the container.
WORKDIR /app

# Set the PYTHONPATH environment variable to include a local packages directory.
# This ensures that Python can find the packages we install locally.
ENV PYTHONPATH=/app/packages

# Copy the requirements file.
COPY requirements.txt .

# Install dependencies into the local packages directory.
# The --target flag specifies the installation directory.
RUN pip install --no-cache-dir --target=/app/packages -r requirements.txt

# Copy the rest of the application code.
COPY . .

# Set the command to run the application.
CMD ["python", "main.py"]