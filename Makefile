# PostForge — common developer commands.
#
# Run `make` or `make help` to list everything below.
#
# There is no docker-compose.yml in this repo by design: the app ships as a
# single production image (frontend + backend combined, per
# docs/docker.md / the Bunny Magic Container architecture). The `up`/`down`/
# `logs`/etc. targets below wrap plain `docker build`/`docker run` against
# that one image, not `docker compose`.

# ---------------------------------------------------------------------------
# Configuration (override on the command line, e.g. `make HOST_PORT=3001 up`)
# ---------------------------------------------------------------------------

IMAGE_NAME     ?= postforge:local
CONTAINER_NAME ?= postforge
PLATFORM       ?= linux/amd64
HOST_PORT      ?= 3000
ENV_FILE       ?= .env.docker

FRONTEND_DIR := frontend
BACKEND_DIR  := backend
BACKEND_PY   := backend/.venv/bin/python

.DEFAULT_GOAL := help

.PHONY: help \
	build up down restart logs ps health shell rebuild prune \
	install install-frontend install-backend venv \
	dev dev-frontend dev-backend \
	test test-backend test-e2e \
	lint lint-frontend lint-backend typecheck format format-frontend format-backend \
	supabase-start supabase-stop supabase-migrate \
	clean

help: ## Show this help
	@echo "Usage: make <target> [VAR=value ...]"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Docker (single production image — see docs/docker.md)
# ---------------------------------------------------------------------------

build: ## Build the production container image
	docker build --platform $(PLATFORM) -t $(IMAGE_NAME) .

up: build ## Build (if needed) and start the container in the background
	@test -f $(ENV_FILE) || { \
		echo "Missing $(ENV_FILE) — see docs/docker.md 'Run Locally' for the required variables."; \
		exit 1; \
	}
	-docker rm -f $(CONTAINER_NAME) >/dev/null 2>&1
	docker run -d --name $(CONTAINER_NAME) --platform $(PLATFORM) \
		--env-file $(ENV_FILE) \
		-p $(HOST_PORT):3000 \
		$(IMAGE_NAME)
	@echo "Started: http://localhost:$(HOST_PORT)  (make logs / make health to check on it)"

down: ## Stop and remove the running container
	-docker stop $(CONTAINER_NAME)
	-docker rm $(CONTAINER_NAME)

restart: down up ## Restart the container

logs: ## Follow container logs
	docker logs -f $(CONTAINER_NAME)

ps: ## Show the container's status
	docker ps -a --filter name=$(CONTAINER_NAME)

health: ## Show the container's current health status
	docker inspect --format '{{.State.Health.Status}}' $(CONTAINER_NAME)

shell: ## Open a shell inside the running container
	docker exec -it $(CONTAINER_NAME) bash

rebuild: ## Rebuild the image from scratch (no layer cache), then restart
	docker build --no-cache --platform $(PLATFORM) -t $(IMAGE_NAME) .
	$(MAKE) restart

prune: down ## Stop the container and remove the built image
	-docker rmi $(IMAGE_NAME)

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

install: install-frontend install-backend ## Install all dependencies (frontend + backend)

install-frontend: ## npm install for the frontend
	cd $(FRONTEND_DIR) && npm install

install-backend: venv ## Create the backend venv and install dependencies

venv: ## Create the backend virtualenv (backend/.venv)
	python3 -m venv $(BACKEND_DIR)/.venv
	$(BACKEND_PY) -m pip install -r $(BACKEND_DIR)/requirements-dev.txt

# ---------------------------------------------------------------------------
# Local development servers
# ---------------------------------------------------------------------------

dev: ## Run backend (background) and frontend (foreground) dev servers together
	@trap 'kill %1 2>/dev/null' EXIT; \
	( cd $(BACKEND_DIR) && .venv/bin/python -m uvicorn app.main:app --reload --port 8000 ) & \
	cd $(FRONTEND_DIR) && npm run dev

dev-frontend: ## Run the frontend dev server only
	cd $(FRONTEND_DIR) && npm run dev

dev-backend: ## Run the backend dev server only (auto-reload)
	cd $(BACKEND_DIR) && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test: test-backend ## Run the default test suite (backend unit/contract/integration)

test-backend: ## Run backend tests (must run from repo root — imports are backend.app.*)
	$(BACKEND_PY) -m pytest backend/tests -q

test-e2e: ## Run frontend Playwright e2e tests (needs the app + Supabase already running)
	cd $(FRONTEND_DIR) && npx playwright test

# ---------------------------------------------------------------------------
# Lint / format / typecheck
# ---------------------------------------------------------------------------

lint: lint-frontend lint-backend ## Lint everything

lint-frontend: ## Lint the frontend (eslint, flat config)
	cd $(FRONTEND_DIR) && npm run lint

lint-backend: ## Lint the backend with ruff (requires `pip install ruff` in backend/.venv — not in requirements-dev.txt)
	$(BACKEND_PY) -m ruff check $(BACKEND_DIR)

typecheck: ## Type-check the frontend without emitting output
	cd $(FRONTEND_DIR) && npx tsc --noEmit

format: format-frontend format-backend ## Format everything

format-frontend: ## Format the frontend with prettier
	cd $(FRONTEND_DIR) && npx prettier --write .

format-backend: ## Format the backend with black (requires `pip install black` in backend/.venv — not in requirements-dev.txt)
	$(BACKEND_PY) -m black $(BACKEND_DIR)

# ---------------------------------------------------------------------------
# Supabase (local dev stack)
# ---------------------------------------------------------------------------

supabase-start: ## Start local Supabase (Postgres, Auth, Studio, Mailpit)
	supabase start

supabase-stop: ## Stop local Supabase
	supabase stop

supabase-migrate: ## Apply pending Supabase migrations
	supabase migration up

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove local build/test artifacts (not node_modules or the venv)
	rm -rf $(FRONTEND_DIR)/.next $(FRONTEND_DIR)/test-results $(FRONTEND_DIR)/playwright-report
	find $(BACKEND_DIR) -type d -name '__pycache__' -not -path '*/.venv/*' -prune -exec rm -rf {} +
	rm -rf $(BACKEND_DIR)/.pytest_cache
