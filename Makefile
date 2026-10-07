.DEFAULT_GOAL := help
UV := uv run

.PHONY: help setup fmt lint typecheck arch test audit check dataset dataset-refresh clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

setup: ## Install dependencies and git hooks
	uv sync
	$(UV) pre-commit install

fmt: ## Auto-format and apply safe lint fixes
	$(UV) ruff format .
	$(UV) ruff check --fix .

lint: ## Lint and check formatting
	$(UV) ruff check .
	$(UV) ruff format --check .

typecheck: ## Static type checking (mypy --strict)
	$(UV) mypy

arch: ## Enforce architecture boundaries (import-linter)
	$(UV) lint-imports

test: ## Run tests with coverage gate
	$(UV) pytest --cov

audit: ## Scan the locked dependencies (hash-pinned) for known vulnerabilities
	uv export --locked --all-groups --no-emit-project --format requirements-txt --quiet \
		| $(UV) --with pip-audit pip-audit --requirement /dev/stdin --disable-pip --require-hashes

check: lint typecheck arch test ## Everything CI runs on every push

dataset: ## Build the BEIR corpus + dataset card from committed snapshots (offline)
	$(UV) masdar dataset --offline

dataset-refresh: ## Re-download source pages (10s crawl delay), then rebuild
	$(UV) masdar dataset --refresh

clean: ## Remove caches and build artifacts
	rm -rf .mypy_cache .ruff_cache .pytest_cache .hypothesis .import_linter_cache .coverage htmlcov dist
