.PHONY: help install install-dev test test-cov lint format build clean upgrade lock setup-dev

help:
	@echo "Clawrium Development Commands"
	@echo ""
	@echo "  make install      Install dependencies"
	@echo "  make install-dev  Install with dev dependencies"
	@echo "  make setup-dev    Setup development workflow (first time)"
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

# Development workflow setup
setup-dev:
	@echo "=== Clawrium Development Setup ==="
	@echo ""
	@uv sync
	@echo ""
	@echo "Which editor do you use for AI-assisted development?"
	@echo "  1) OpenCode"
	@echo "  2) Claude Code"
	@echo "  3) Both"
	@echo ""
	@read -p "Enter choice [1-3]: " editor_choice; \
	case $$editor_choice in \
		1) $(MAKE) _setup-opencode ;; \
		2) $(MAKE) _setup-claude ;; \
		3) $(MAKE) _setup-opencode && $(MAKE) _setup-claude ;; \
		*) echo "Invalid choice. Run 'make setup-dev' again." && exit 1 ;; \
	esac
	@echo ""
	@echo "=== Setup Complete ==="
	@echo ""
	@echo "Spec Workflow ready! Available commands:"
	@echo ""
	@echo "  /clawrium:file-bug           - Create new bug report"
	@echo "  /clawrium:idea               - Capture raw thoughts (creates issue)"
	@echo "  /clawrium:write-spec <issue> - Create specification"
	@echo "  /clawrium:write-plan <issue> - Generate execution plan"
	@echo "  /clawrium:execute <issue>    - Execute plan tasks"
	@echo "  /clawrium:learn <issue>      - Document learnings"
	@echo ""
	@echo "Check .spec/status.md for current issues."
	@echo "Read .spec/CONTRIBUTING.md for full workflow guide."

_setup-opencode:
	@echo "Setting up OpenCode commands..."
	@mkdir -p .opencode/commands
	@for cmd in file-bug idea write-spec write-plan execute learn; do \
		cp .spec/commands/opencode/$$cmd.md .opencode/commands/clawrium:$$cmd.md 2>/dev/null || true; \
	done
	@echo "OpenCode commands installed in .opencode/commands/"

_setup-claude:
	@echo "Setting up Claude Code commands..."
	@mkdir -p .claude/commands
	@for cmd in file-bug idea write-spec write-plan execute learn; do \
		cp .spec/commands/claude/$$cmd.md .claude/commands/clawrium:$$cmd.md 2>/dev/null || true; \
	done
	@echo "Claude Code commands installed in .claude/commands/"
