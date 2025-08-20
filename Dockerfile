# Dockerfile
# Use the official Python image.
# https://hub.docker.com/_/python
FROM python:3.11-slim

# Set the working directory in the container.
WORKDIR /app

# Copy the requirements file into the container.
COPY requirements.txt .

# Install numpy separately BEFORE other packages to ensure it's available for dependencies that need it for compilation.
RUN pip install numpy

# Install the rest of the dependencies.
# https://pip.pypa.io/en/stable/cli/pip_install/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container.
COPY . .

# Set the command to run the application.
CMD ["python", "main.py"]