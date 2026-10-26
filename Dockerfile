FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required for discord.py voice, ffmpeg, and opus
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first to take advantage of Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create runtime directories
RUN mkdir -p /app/data /app/assets /app/config

# Copy application source code
COPY assets/ /app/assets/
COPY config/ /app/config/
COPY core/ /app/core/
COPY services/ /app/services/
COPY main.py /app/

# Declare persistent data volume for SQLite database, temp files, and logs
VOLUME ["/app/data"]

# Run the Discord bot
CMD ["python", "main.py"]
