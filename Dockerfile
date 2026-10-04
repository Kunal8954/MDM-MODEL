# ==============================================================================
# SATGUARD Production Multi-Stage Backend Dockerfile
# Hardened, Non-Root, Minimal Attack Surface
# ==============================================================================

# Stage 1: Build & Dependency Wheel Cache
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Final Minimal Runtime Image
FROM python:3.12-slim-bookworm AS runner

# Create non-root system operator group and user
RUN groupadd -g 10001 satguard && \
    useradd -u 10001 -g satguard -s /bin/bash -m satguard

WORKDIR /app

# Install minimal runtime shared libraries (libpq for postgresql)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python wheels from builder
COPY --from=builder /root/.local /home/satguard/.local
ENV PATH=/home/satguard/.local/bin:$PATH

# Copy platform source and assets
COPY --chown=satguard:satguard satguard/ /app/satguard/
COPY --chown=satguard:satguard migrations/ /app/migrations/
COPY --chown=satguard:satguard data/ /app/data/

# Prepare storage directory owned by non-root user
RUN mkdir -p /app/storage/data /app/storage/cache && \
    chown -R satguard:satguard /app/storage

USER satguard

# Security: drop capabilities
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SATGUARD_ENV=production \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/live || exit 1

CMD ["uvicorn", "satguard.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
