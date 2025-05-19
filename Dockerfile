#Dockerfile
FROM python:3.11-slim

# Set environment variables to improve security and performance
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONFAULTHANDLER=1

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    # FFmpeg for video processing
    ffmpeg \
    # Cleanup to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -s /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy requirements and set proper permissions
COPY --chown=appuser:appuser requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser main.py .

# Switch to non-root user
USER appuser

# Expose port and define command
EXPOSE 41295

# Use entrypoint for more flexible command execution
ENTRYPOINT ["python3"]
CMD ["main.py"]
