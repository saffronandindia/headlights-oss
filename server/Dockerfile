# syntax=docker/dockerfile:1
# headlights-server — production image
#
# Multi-stage build:
#   builder  — installs Python deps into /install
#   runtime  — copies /install + source, runs as non-root

# ── Stage 1: builder ─────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools (needed for any C-extension deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifests first (layer cache)
COPY pyproject.toml ./
COPY headlights_server/__init__.py headlights_server/__init__.py

# Install into an isolated prefix so we can COPY it cleanly to the runtime stage
RUN pip install --no-cache-dir --prefix=/install ".[dev]" 2>/dev/null || \
    pip install --no-cache-dir --prefix=/install .

# ── Stage 2: runtime ─────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Create a non-root user
RUN useradd --create-home --shell /bin/bash headlights

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source
COPY --chown=headlights:headlights . .

# Data volume for the SQLite database
RUN mkdir -p /data && chown headlights:headlights /data
VOLUME ["/data"]

USER headlights

EXPOSE 8000

# Health check — uvicorn must be responsive before the container is marked healthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

ENV HEADLIGHTS_DATABASE_URL="sqlite:////data/headlights.db" \
    HEADLIGHTS_DEBUG="false" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1"

CMD ["uvicorn", "headlights_server.app:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info"]
