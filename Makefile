# =============================================================================
# Combined targets
# =============================================================================

.PHONY: install
install: install-server install-ui ## Install all dependencies (server + UI)

.PHONY: check
check: check-server check-ui ## Run all quality checks (server + UI)

.PHONY: dev
dev: ## Run agent-runtime and UI dev server concurrently
	@echo "Starting agent-runtime and UI dev server..."
	@echo "Agent Runtime: http://localhost:8000"
	@echo "UI Dev Server: http://localhost:5173"
	@trap 'kill 0' EXIT; \
		$(MAKE) run-agent & \
		$(MAKE) dev-ui & \
		wait

# =============================================================================
# Server
# =============================================================================

.PHONY: install-server
install-server: ## Install Python virtual environment and pre-commit hooks
	@echo "Creating virtual environment using uv"
	@uv sync
	@uv run pre-commit install

.PHONY: check-server
check-server: ## Run server-side quality checks
	@echo "Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "Linting code: Running pre-commit (server hooks)"
	@SKIP=ui-lint,ui-fmt-check uv run pre-commit run -a
	@echo "Static type checking: Running pyright"
	@uv run pyright
	@echo "Checking for obsolete dependencies: Running deptry"
	@uv run deptry .

.PHONY: test
test: ## Run all tests (requires Docker for integration tests)
	@echo "Testing code: Running pytest"
	@uv run python -m pytest tests

.PHONY: test-unit
test-unit: ## Run unit tests only (no Docker required)
	@echo "Running unit tests"
	@uv run python -m pytest tests -m "not integration"

.PHONY: run-agent
run-agent: ## Run agent-runtime dev server with auto-reload
	@uv run netherbrain agent --reload

.PHONY: run-gateway
run-gateway: ## Run im-gateway
	@uv run netherbrain gateway

# =============================================================================
# UI
# =============================================================================

.PHONY: install-ui
install-ui: ## Install UI dependencies
	@echo "Installing UI dependencies"
	@cd ui && npm install

.PHONY: check-ui
check-ui: ## Run UI linting and formatting checks
	@echo "Linting UI"
	@cd ui && pnpm run lint
	@echo "Checking UI formatting"
	@cd ui && pnpm run fmt:check

.PHONY: fix-ui
fix-ui: ## Fix UI lint and formatting issues
	@cd ui && pnpm run lint:fix
	@cd ui && pnpm run fmt

.PHONY: dev-ui
dev-ui: ## Run UI dev server with hot-reload
	@cd ui && pnpm run dev

.PHONY: build-ui
build-ui: ## Build UI for production
	@echo "Building UI"
	@cd ui && pnpm run build

# =============================================================================
# Build & Release
# =============================================================================

.PHONY: build
build: clean-build build-ui ## Build wheel file (includes UI)
	@echo "Creating wheel file"
	@uvx --from build pyproject-build --installer uv

.PHONY: clean-build
clean-build: ## Clean build artifacts
	@echo "Removing build artifacts"
	@uv run python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"

.PHONY: publish
publish: ## Publish a release to PyPI
	@echo "Publishing."
	@uvx twine upload --repository-url https://upload.pypi.org/legacy/ dist/*

.PHONY: build-and-publish
build-and-publish: build publish ## Build and publish

# =============================================================================
# Database
# =============================================================================

.PHONY: db-upgrade
db-upgrade: ## Run database migrations to latest
	@uv run netherbrain db upgrade

.PHONY: db-downgrade
db-downgrade: ## Roll back database by one migration
	@uv run netherbrain db downgrade

.PHONY: db-current
db-current: ## Show current database revision
	@uv run netherbrain db current

.PHONY: db-history
db-history: ## Show migration history
	@uv run netherbrain db history

# =============================================================================
# Infrastructure
# =============================================================================

.PHONY: infra-up
infra-up: ## Start dev PostgreSQL and Redis
	@bash dev/dev-setup.sh up

.PHONY: infra-down
infra-down: ## Stop dev PostgreSQL and Redis (data preserved)
	@bash dev/dev-setup.sh down

.PHONY: infra-status
infra-status: ## Show dev infrastructure status
	@bash dev/dev-setup.sh status

.PHONY: infra-reset
infra-reset: ## Stop dev infrastructure and remove all data
	@bash dev/dev-setup.sh reset

# =============================================================================
# Help
# =============================================================================

.PHONY: help
help:
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.DEFAULT_GOAL := help
