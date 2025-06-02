#Dockerfile
FROM python:3.11-slim

# Set environment variables to improve security and performance
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONFAULTHANDLER=1

# Install system dependencies and reate a non-root user
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    # FFmpeg for video processing
    ffmpeg \
    # Cleanup to reduce image size
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash -u 1000 appuser

# Set working directory
WORKDIR /app

# Copy requirements and set proper permissions
COPY --chown=appuser:appuser requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser entrypoint.sh ./
# COPY --chown=appuser:appuser newrelic.ini ./

RUN chmod +x ./entrypoint.sh

# Switch to non-root user
USER appuser

# Expose port and define command
EXPOSE 41295

# Use entrypoint for more flexible command execution
ENTRYPOINT ["./entrypoint.sh"]
# CMD ["main.py"]

# #Dockerfile
# FROM python:3.11-alpine

# # Set environment variables to improve security and performance
# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     PIP_NO_CACHE_DIR=1 \
#     PIP_DISABLE_PIP_VERSION_CHECK=1 \
#     PYTHONFAULTHANDLER=1

# # Install system dependencies and create a non-root user
# RUN apk update && \
#     # Install runtime dependencies
#     apk add --no-cache \
#     ffmpeg \
#     bash \
#     shadow \
#     librdkafka \
#     && \
#     # Install build dependencies temporarily
#     apk add --no-cache --virtual .build-deps \
#     gcc \
#     g++ \
#     musl-dev \
#     linux-headers \
#     libffi-dev \
#     openssl-dev \
#     librdkafka-dev \
#     && adduser -D -s /bin/bash -u 1000 appuser

# # Set working directory
# WORKDIR /app

# # Copy requirements and set proper permissions
# COPY --chown=appuser:appuser requirements.txt .

# # Install dependencies and remove build deps
# RUN pip install --no-cache-dir -r requirements.txt && \
#     apk del .build-deps

# # Copy application code
# COPY --chown=appuser:appuser src/ ./src/
# COPY --chown=appuser:appuser main.py .

# # Switch to non-root user
# USER appuser

# # Expose port and define command
# EXPOSE 41295

# # Use entrypoint for more flexible command execution
# ENTRYPOINT ["./entrypoint.sh"]