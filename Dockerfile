# Dockerfile
# Use the official Python image.
FROM python:3.11-slim

# Set the working directory in the container.
WORKDIR /app

# Set the PYTHONPATH environment variable.
# This explicitly tells Python to look for packages in /app/packages.
ENV PYTHONPATH=/app/packages

# Copy the requirements file.
COPY requirements.txt .

# Install dependencies into the local packages directory.
# The --target flag forces installation to a specific folder.
RUN pip install --no-cache-dir --target=/app/packages -r requirements.txt

# Copy the rest of the application code.
COPY . .

# Set the command to run the application.
CMD ["python", "main.py"]