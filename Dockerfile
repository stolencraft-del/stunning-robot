FROM python:3.11-slim

# Install system dependencies including bash
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ffmpeg aria2 build-essential libffi-dev bash && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip3 install --no-cache-dir -U pip

# Copy requirements
COPY requirements.txt /requirements.txt
RUN pip3 install --no-cache-dir -r /requirements.txt

# Set working directory
WORKDIR /app

# Copy entire project into container
COPY . /app

# Make start.sh executable
RUN chmod +x /app/start.sh

# Run start script
CMD ["bash", "/app/start.sh"]
