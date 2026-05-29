.PHONY: help install test test-py test-ui test-cov lint lint-py lint-ui format build build-ui clean upgrade lock setup-dev

GUI_DIR := gui
GUI_OUT := $(GUI_DIR)/out
GUI_INSTALL_STAMP := $(GUI_DIR)/node_modules/.package-lock.json
FRONTEND_DEST := src/clawrium/gui/frontend

help:
	@echo "Clawrium Development Commands"
	@echo ""
	@echo "  make setup-dev    Setup development environment (first time)"
	@echo "  make install      Install production dependencies only"
	@echo "  make test         Run Python and JS tests"
	@echo "  make test-py      Run Python tests only"
	@echo "  make test-ui      Run GUI (vitest) tests only"
	@echo "  make test-cov     Run Python tests with coverage"
	@echo "  make lint         Run Python and JS linters"
	@echo "  make lint-py      Run Python linter only"
	@echo "  make lint-ui      Run GUI (next lint) only"
	@echo "  make format       Format code"
	@echo "  make build        Build Python package (includes GUI)"
	@echo "  make build-ui     Build the GUI frontend and stage it for clm gui"
	@echo "  make clean        Remove build artifacts"
	@echo "  make upgrade      Upgrade all dependencies"
	@echo "  make lock         Update lock file"

install:
	uv sync --no-dev

test: test-py test-ui

test-py:
	uv run pytest

test-ui: $(GUI_INSTALL_STAMP)
	cd $(GUI_DIR) && npm test

test-cov:
	uv run pytest --cov=src/clawrium --cov-report=term-missing

# Mac-touching test set. Runs only the new tests added by #469 (resolver,
# version matcher, hardware normalization, host_macos, launchd plist,
# lifecycle_macos, mocked Mac E2E). The rest of the suite pre-dates Mac
# support and assumes a Linux runtime — exercising it on macOS surfaces
# unrelated, pre-existing failures with no signal about the Mac change set.
test-macos:
	uv run pytest \
	  tests/core/test_playbook_resolver.py \
	  tests/core/test_hosts_os_family.py \
	  tests/core/test_version_matches.py \
	  tests/core/test_hardware_macos_normalization.py \
	  tests/core/test_launchd.py \
	  tests/core/test_lifecycle_macos.py \
	  tests/integration/test_macos_e2e_mocked.py \
	  tests/test_names.py::TestReservedUnixNames \
	  -v

lint: lint-py lint-ui

lint-py:
	uv run ruff check src tests

lint-ui: $(GUI_INSTALL_STAMP)
	cd $(GUI_DIR) && npm run lint

format:
	uv run ruff format src tests

build: build-ui
	uv build

$(GUI_INSTALL_STAMP): $(GUI_DIR)/package-lock.json $(GUI_DIR)/package.json
	@command -v npm >/dev/null 2>&1 || { echo "npm is required to build the GUI"; exit 1; }
	cd $(GUI_DIR) && npm ci
	@touch $@

build-ui: $(GUI_INSTALL_STAMP)
	cd $(GUI_DIR) && npm run build
	rm -rf $(FRONTEND_DEST)
	mkdir -p $(FRONTEND_DEST)
	cp -R $(GUI_OUT)/. $(FRONTEND_DEST)/
	@echo "GUI built and staged at $(FRONTEND_DEST)/"

clean:
	rm -rf dist build *.egg-info
	rm -rf .pytest_cache .coverage .ruff_cache
	rm -rf $(GUI_OUT) $(GUI_DIR)/.next $(FRONTEND_DEST)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

upgrade:
	uv lock --upgrade

lock:
	uv lock

# Development environment setup (first time)
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
