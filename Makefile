# Makefile for running, testing, and dockerizing the app

PY := python3
PIP := pip3
UVICORN := uvicorn

APP_MODULE := app.main:app
HOST ?= 0.0.0.0
PORT ?= 8000

.PHONY: help install run dev test fmt lint migrate revision docker-build docker-up docker-down docker-logs docker-shell

help:
	@echo "Common targets:"
	@echo "  install       Install Python dependencies from requirements.txt"
	@echo "  run           Run the API locally with Uvicorn (reload)"
	@echo "  dev           Same as run"
	@echo "  test          Run unit tests"
	@echo "  fmt           Format with black & isort"
	@echo "  lint          Typecheck with mypy"
	@echo "  migrate       Apply DB migrations (alembic upgrade head)"
	@echo "  revision m=.. Create a new alembic revision with message"
	@echo "  docker-build  Build the Docker image"
	@echo "  docker-up     Start app + Postgres with docker-compose"
	@echo "  docker-down   Stop and remove containers"
	@echo "  docker-logs   Tail app logs"
	@echo "  docker-shell  Open a shell in the running app container"

install:
	poetry install

server:
	poetry run $(UVICORN) $(APP_MODULE) --reload --host $(HOST) --port $(PORT)

test:
	pytest -q

fmt:
	black .
	isort .

lint:
	mypy . || true

migrate:
	poetry run alembic upgrade head

revision:
	@if [ -z "$(m)" ]; then echo "Usage: make revision m=\"message\""; exit 1; fi
	poetry run alembic revision --autogenerate -m "$(m)"

docker-build:
	docker build -t ai-knowledge-base:latest .

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down -v

docker-logs:
	docker compose logs -f api

docker-shell:
	docker compose exec api /bin/bash
