.DEFAULT_GOAL := help
.PHONY: help install fmt fmt-check lint typecheck arch test test-unit cov verify spec clean

UV ?= uv
RUN := $(UV) run

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Sync the virtualenv with all dependency groups
	$(UV) sync --all-groups

fmt: ## Apply formatting and safe lint fixes
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

fmt-check: ## Fail if formatting is not applied
	$(RUN) ruff format --check .

lint: ## Lint without fixing
	$(RUN) ruff check .

typecheck: ## Type-check in strict mode
	$(RUN) mypy src tests

arch: ## Enforce the layer graph only
	$(RUN) pytest tests/architecture -q

test: ## Run the full test suite
	$(RUN) pytest -q

test-unit: ## Run unit tests only
	$(RUN) pytest tests/unit -q

cov: ## Run tests with a coverage report
	$(RUN) pytest --cov=krep --cov-report=term-missing -q

verify: fmt-check lint typecheck test ## The gate. Must pass before any work is called done.
	@printf '\n\033[32mverify passed\033[0m\n'

spec: ## Scaffold docs for new work: make spec name=<slug> [level=2] [title="..."]
ifndef name
	$(error usage: make spec name=<slug> [level=2] [title="Human Title"])
endif
	@./scripts/spec_init.sh $(name) --level $(or $(level),2) $(if $(title),--title "$(title)",)

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage dist build
	find . -name '__pycache__' -type d -prune -not -path './*/.venv/*' -exec rm -rf {} +
