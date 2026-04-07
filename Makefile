.PHONY: help up down logs migrate seed test lint format check api-dev worker-dev web-dev clean score ingest export sync

DOCKER_COMPOSE = docker compose
API_DIR = apps/api
WEB_DIR = apps/web
WORKER_DIR = workers

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---- Infrastructure ----
up: ## Start all services (detached)
	$(DOCKER_COMPOSE) up -d
	@echo "API   → http://localhost:8000/docs"
	@echo "Web   → http://localhost:3000"
	@echo "Flower→ http://localhost:5555"

down: ## Stop all services
	$(DOCKER_COMPOSE) down

logs: ## Tail all service logs
	$(DOCKER_COMPOSE) logs -f

logs-api: ## Tail API logs
	$(DOCKER_COMPOSE) logs -f api

logs-worker: ## Tail worker logs
	$(DOCKER_COMPOSE) logs -f worker

# ---- Database ----
migrate: ## Run Alembic migrations
	cd $(API_DIR) && alembic upgrade head

migrate-down: ## Rollback last migration
	cd $(API_DIR) && alembic downgrade -1

migrate-new: ## Create new migration (usage: make migrate-new MSG="add foo table")
	cd $(API_DIR) && alembic revision --autogenerate -m "$(MSG)"

seed: ## Seed database with test data
	cd $(API_DIR) && python -m app.cli seed

# ---- Pipeline CLI ----
ingest: ## Run ingestion from local raw dir
	cd $(API_DIR) && python -m app.cli ingest --source-dir ../../data/raw/

build-views: ## Rebuild feature materialized views
	cd $(API_DIR) && python -m app.cli build-views

score: ## Run full scoring pass
	cd $(API_DIR) && python -m app.cli score-leads

export: ## Export top 50 leads to CSV
	cd $(API_DIR) && python -m app.cli export-daily-list --top-n 50 --out ../../data/processed/daily_top_50.csv

sync-hubspot: ## Sync top leads to HubSpot
	cd $(API_DIR) && python -m app.cli sync-hubspot --csv ../../data/processed/daily_top_50.csv

# ---- Development ----
api-dev: ## Run API locally (without Docker)
	cd $(API_DIR) && uvicorn app.main:app --reload --port 8000

worker-dev: ## Run Celery worker locally
	cd $(WORKER_DIR) && celery -A workers.celery_app worker --loglevel=debug --concurrency=2

web-dev: ## Run Next.js dev server locally
	cd $(WEB_DIR) && npm run dev

# ---- Testing & Quality ----
test: ## Run all tests
	cd $(API_DIR) && python -m pytest tests/ -v --tb=short
	cd $(WEB_DIR) && npm run test

test-api: ## Run API tests only
	cd $(API_DIR) && python -m pytest tests/ -v --tb=short -x

lint: ## Run all linters
	cd $(API_DIR) && ruff check . && mypy app/
	cd $(WEB_DIR) && npm run lint

format: ## Auto-format Python code
	cd $(API_DIR) && ruff format . && ruff check --fix .

check: lint test ## Full quality gate (lint + test)

# ---- Housekeeping ----
clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(WEB_DIR)/.next
	@echo "Clean done."

install-api: ## Install API dependencies
	cd $(API_DIR) && pip install -e ".[dev]"

install-web: ## Install web dependencies
	cd $(WEB_DIR) && npm install

install: install-api install-web ## Install all dependencies

# ---- Data directories ----
data-dirs: ## Create local data directories
	mkdir -p data/raw data/processed data/exports
	touch data/.gitkeep
