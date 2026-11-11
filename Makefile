.PHONY: help up down logs logs-api logs-worker migrate migrate-down migrate-new seed ingest build-views score export sync-hubspot \
        api-dev worker-dev web-dev test test-api test-web lint format check mutation mutation-api mutation-web set-password clean install

DOCKER_COMPOSE = docker compose
API_DIR = apps/api
WEB_DIR = apps/web
ALEMBIC = uv run --package revops-api alembic -c $(API_DIR)/alembic.ini
CLI = uv run --package revops-api python -m app.cli

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---- Infrastructure ----
up: ## Start all services (detached)
	$(DOCKER_COMPOSE) up -d --build
	@echo "API   → http://localhost:8000/docs"
	@echo "Web   → http://localhost:3000"

down: ## Stop all services
	$(DOCKER_COMPOSE) down

logs: ## Tail all service logs
	$(DOCKER_COMPOSE) logs -f

logs-api: ## Tail API logs
	$(DOCKER_COMPOSE) logs -f api

logs-worker: ## Tail worker logs
	$(DOCKER_COMPOSE) logs -f worker

# ---- Database (needs DATABASE_URL, e.g. from .env) ----
migrate: ## Run Alembic migrations
	$(ALEMBIC) upgrade head

migrate-down: ## Roll back the last migration
	$(ALEMBIC) downgrade -1

migrate-new: ## Create a migration (usage: make migrate-new MSG="add foo table")
	$(ALEMBIC) revision --autogenerate -m "$(MSG)"

seed: ## Seed the database with synthetic data
	$(CLI) seed

set-password: ## Set a user's password (usage: make set-password EMAIL=someone@example.com)
	@test -n "$(EMAIL)" || (echo "usage: make set-password EMAIL=someone@example.com"; exit 1)
	$(CLI) set-password --email "$(EMAIL)"

# ---- Pipeline CLI ----
ingest: ## Ingest raw files from data/raw/
	$(CLI) ingest --source-dir data/raw/

build-views: ## Rebuild feature views
	$(CLI) build-views

score: ## Run a full scoring pass
	$(CLI) score-leads

export: ## Export the top 50 leads to CSV
	$(CLI) export-daily-list --top-n 50 --out data/processed/daily_top_50.csv

sync-hubspot: ## Push the exported leads to HubSpot
	$(CLI) sync-hubspot --csv data/processed/daily_top_50.csv

# ---- Development ----
api-dev: ## Run the API locally (without Docker)
	# From the repository root, as the Docker image runs it: `workers` (imported by the API to queue tasks) is found there, and `app` is the workspace install.
	uv run --package revops-api uvicorn app.main:app --reload --reload-dir $(API_DIR) --reload-dir workers --port 8000

worker-dev: ## Run a Celery worker locally
	uv run --package revops-workers celery -A workers.celery_app worker --loglevel=debug --concurrency=2

web-dev: ## Run the Next.js dev server locally
	cd $(WEB_DIR) && npm run dev

# ---- Testing & quality ----
install: ## Install everything (Python workspace + web)
	uv sync --all-packages --all-extras
	cd $(WEB_DIR) && npm ci

test: test-api test-web ## Run all tests

test-api: ## API and worker tests (a throwaway PostgreSQL is started if TEST_DATABASE_URL is not set)
	uv run --package revops-api pytest $(API_DIR)/tests -q

test-web: ## Web tests
	cd $(WEB_DIR) && npm test

lint: ## All linters and type checks
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy $(API_DIR)/app workers
	cd $(WEB_DIR) && npm run lint && npm run type-check

format: ## Format Python code
	uv run ruff format . && uv run ruff check --fix .

check: lint test ## Full quality gate

mutation: mutation-api mutation-web ## Mutation check of the security-critical code, API and web (slow: one test run per mutant)

mutation-api: ## Mutation check of the API's authentication, encryption, URL and signature code
	python3 $(API_DIR)/tests/mutation/mutate.py $(API_DIR)/tests/mutation/mutants.py -- uv run --package revops-api pytest $(API_DIR)/tests -x -q -p no:cacheprovider

mutation-web: ## Mutation check of the web app's session, proxy and helper code
	cd $(WEB_DIR) && python3 test/mutation/mutate.py test/mutation/mutants.py -- npx vitest run --bail 1

clean: ## Remove build artifacts and caches
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(WEB_DIR)/.next $(WEB_DIR)/coverage
	@echo "Clean done."
