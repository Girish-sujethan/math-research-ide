# ── HEAVEN API server ──────────────────────────────────────────
FROM python:3.11-slim AS base

# System deps for sentence-transformers, scipy, etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git && \
    rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files first (layer cache)
COPY pyproject.toml uv.lock* ./

# Install production deps
RUN uv sync --no-dev --frozen || uv sync --no-dev

# Copy the rest of the application
COPY . .

# Run migrations then start server
# Using shell form so we can chain commands
CMD uv run alembic upgrade head && \
    uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
