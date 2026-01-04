FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp
RUN pip install --no-cache-dir yt-dlp

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App code
WORKDIR /app
COPY . /app

# Expose (Render ignores but ok)
EXPOSE 10000

# Start
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000", "--workers", "1", "--timeout-keep-alive", "75"]
