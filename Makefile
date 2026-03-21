.PHONY: help install install-dev test test-cov lint format build clean upgrade lock

help:
	@echo "Clawrium Development Commands"
	@echo ""
	@echo "  make install      Install dependencies"
	@echo "  make install-dev  Install with dev dependencies"
	@echo "  make test         Run tests"
	@echo "  make test-cov     Run tests with coverage"
	@echo "  make lint         Run linter"
	@echo "  make format       Format code"
	@echo "  make build        Build package"
	@echo "  make clean        Remove build artifacts"
	@echo "  make upgrade      Upgrade all dependencies"
	@echo "  make lock         Update lock file"

install:
	uv sync --no-dev

install-dev:
	uv sync

test:
	uv run pytest

test-cov:
	uv run pytest --cov=src/clawrium --cov-report=term-missing

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

build:
	uv build

clean:
	rm -rf dist build *.egg-info
	rm -rf .pytest_cache .coverage .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

upgrade:
	uv lock --upgrade

lock:
	uv lock
