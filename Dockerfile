FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose backend port
EXPOSE 8080

# Set environment variables with defaults
ENV HOME=/root
ENV PORT=8080
ENV NIM_KEY_REQUIRED=false

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run discovery and configuration on startup, then start the server
CMD python scripts/discover_machine.py && \
    python scripts/configure_from_discovery.py --no-overwrite && \
    python scripts/index_vault.py && \
    python main.py
