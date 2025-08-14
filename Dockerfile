# syntax=docker/dockerfile:1

FROM python:3.11-slim as base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Poetry
RUN pip install --upgrade pip && pip install poetry==1.8.3

# Configure poetry: create virtual env in project, cache dir
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VENV_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# Install Python dependencies
COPY pyproject.toml poetry.lock /app/
# Force poetry to create venv in project and install dependencies
RUN poetry config virtualenvs.in-project true && \
    poetry install --without dev && \
    ls -la /app/.venv/bin/ && \
    echo "Virtual environment created successfully"

# Copy source
COPY . /app

# Create directories used by the app
RUN mkdir -p /app/chroma_db /app/uploads /app/documents

EXPOSE 8000

# Default envs (override with docker-compose or -e)
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_URL=postgresql+asyncpg://user:password@db:5432/knowledge_base \
    CHROMA_PERSIST_DIRECTORY=/app/chroma_db

# Start server
CMD ["poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
