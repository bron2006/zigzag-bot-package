# Dockerfile
# Use the official Python image.
# https://hub.docker.com/_/python
FROM python:3.11-slim

# Set the working directory in the container.
WORKDIR /app

# Install system-level build dependencies required for compiling Python packages with C extensions.
RUN apt-get update && apt-get install -y build-essential python3-dev

# Copy the requirements file into the container.
COPY requirements.txt .

# Install Python build dependencies separately BEFORE other packages.
RUN pip install numpy cython

# Install the rest of the dependencies.
# https://pip.pypa.io/en/stable/cli/pip_install/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container.
COPY . .

# Set the command to run the application.
CMD ["python", "main.py"]