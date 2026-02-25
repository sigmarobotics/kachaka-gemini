# Multi-arch Dockerfile for Kachaka + Gemini Live API
# Supports: linux/amd64, linux/arm64

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY src/backend/requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/backend/ /app/
COPY src/frontend/ /app/frontend/

# Create data and report directories
RUN mkdir -p /app/data /app/data/report/images /app/data/report/video

# Expose port
EXPOSE 9000

# Environment variables
ENV ROBOT_IP=192.168.50.133:26400
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9000/api/state || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "warning"]
