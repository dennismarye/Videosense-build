# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

# Install FFmpeg and create non-root user
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash -u 1000 appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser main_local.py ./
COPY --chown=appuser:appuser entrypoint.sh ./

RUN chmod +x ./entrypoint.sh

LABEL org.opencontainers.image.title="circo-video-sense" \
      org.opencontainers.image.version="1.2.0"

USER appuser
EXPOSE 41295

ENTRYPOINT ["./entrypoint.sh"]
