# Phase 1: Foundation Setup - Research

**Researched:** 2026-03-20
**Domain:** Python CLI development with Typer, uv packaging, dependency detection
**Confidence:** HIGH

## Summary

Phase 1 establishes the foundation for Clawrium: initializing the configuration directory at `~/.config/clawrium/` and providing clear dependency status to users. The tech stack is well-defined (Python + Typer + ansible-runner, packaged with uv), and the requirements are straightforward initialization tasks.

The primary challenges are: (1) structuring the project correctly for uv/Typer from the start, (2) implementing robust dependency detection that works across Ubuntu systems, and (3) providing actionable install instructions that respect the "no sudo" constraint (user must be prompted, not automated).

**Primary recommendation:** Use Typer with Rich for CLI output, structure with `src/` layout from day one, and implement dependency checking via `shutil.which()` with version parsing via subprocess. Create config directory using standard pathlib with XDG fallback support.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INIT-01 | User can initialize Clawrium config directory (`clm init`) | pathlib + XDG patterns, Typer command structure |
| INIT-02 | User sees dependency check (Python, Ansible) with install instructions | shutil.which() detection, subprocess version parsing, Rich formatted output |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typer | 0.24.1 | CLI framework | Official from FastAPI team, type-hint based, excellent DX |
| rich | 14.3.3 | Terminal formatting | Required by Typer for pretty output, industry standard |
| ansible-runner | 2.4.3 | Ansible execution | Official Ansible project library for embedding Ansible |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| xdg-base-dirs | 6.0.2 | XDG directory resolution | For ~/.config path resolution (optional, can use pathlib directly) |
| pytest | 8.x | Testing framework | All test files |
| pytest-cov | 6.x | Coverage reporting | CI/CD pipelines |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| typer | click | Typer is built on Click but adds type hints; prefer Typer for new projects |
| rich | plain print | No rich output; only use if terminal compatibility is paramount |
| xdg-base-dirs | pathlib only | Extra dependency vs manual XDG_CONFIG_HOME handling |

**Installation:**
```bash
uv add typer rich ansible-runner
uv add --dev pytest pytest-cov
```

**Version verification:** Versions verified against PyPI on 2026-03-20.

## Architecture Patterns

### Recommended Project Structure
```
clawrium/
├── pyproject.toml           # Project config, entry points, dependencies
├── uv.lock                   # Lockfile (auto-generated)
├── README.md
├── src/
│   └── clawrium/
│       ├── __init__.py       # Package init with version
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py       # Main Typer app, command groups
│       │   └── init.py       # `clm init` command
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py     # Config directory management
│       │   └── deps.py       # Dependency detection
│       └── utils/
│           ├── __init__.py
│           └── console.py    # Rich console helpers
└── tests/
    ├── __init__.py
    ├── conftest.py           # Shared fixtures
    ├── test_cli_init.py      # Test clm init command
    └── test_deps.py          # Test dependency detection
```

### Pattern 1: Typer Command Groups
**What:** Organize related commands under subcommands (e.g., `clm host add`, `clm host list`)
**When to use:** Phase 2+ when adding host management
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/subcommands/
import typer

app = typer.Typer()
host_app = typer.Typer()
app.add_typer(host_app, name="host")

@host_app.command("add")
def host_add(name: str):
    """Add a new host."""
    pass
```

### Pattern 2: Single-Command CLI (Phase 1)
**What:** Simple CLI with one or few top-level commands
**When to use:** Phase 1 with `clm init` as the primary command
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/first-steps/
import typer
from rich.console import Console

app = typer.Typer()
console = Console()

@app.command()
def init():
    """Initialize Clawrium configuration."""
    # Implementation here
    console.print("[green]Clawrium initialized![/green]")

if __name__ == "__main__":
    app()
```

### Pattern 3: Dependency Detection
**What:** Check if external tools (Python, Ansible) are available
**When to use:** `clm init` dependency verification
**Example:**
```python
# Source: https://docs.python.org/3/library/shutil.html
import shutil
import subprocess
from dataclasses import dataclass

@dataclass
class DependencyStatus:
    name: str
    found: bool
    version: str | None
    path: str | None
    install_hint: str

def check_ansible() -> DependencyStatus:
    path = shutil.which("ansible")
    if not path:
        return DependencyStatus(
            name="ansible",
            found=False,
            version=None,
            path=None,
            install_hint="Install via: pipx install ansible (recommended) or sudo apt install ansible"
        )

    result = subprocess.run(
        ["ansible", "--version"],
        capture_output=True,
        text=True
    )
    # Parse version from first line: "ansible [core 2.x.x]"
    version = result.stdout.split('\n')[0] if result.returncode == 0 else None

    return DependencyStatus(
        name="ansible",
        found=True,
        version=version,
        path=path,
        install_hint=""
    )
```

### Pattern 4: Config Directory Initialization
**What:** Create ~/.config/clawrium/ following XDG specification
**When to use:** `clm init` command
**Example:**
```python
# Source: https://github.com/srstevenson/xdg-base-dirs + pathlib docs
from pathlib import Path
import os

def get_config_dir() -> Path:
    """Get Clawrium config directory, respecting XDG_CONFIG_HOME."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config and Path(xdg_config).is_absolute():
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"
    return base / "clawrium"

def init_config_dir() -> Path:
    """Create and return the config directory."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir
```

### Anti-Patterns to Avoid
- **Hard-coding ~/.config/clawrium/:** Always respect XDG_CONFIG_HOME environment variable
- **Running sudo automatically:** Never execute privileged commands; only show instructions
- **Monolithic CLI file:** Split into cli/, core/, utils/ from the start
- **Skipping type hints:** Typer relies on them; use everywhere

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CLI framework | argparse wrapper | Typer | Type hints, auto-completion, Rich integration |
| Terminal colors | ANSI escape codes | Rich | Cross-platform, consistent, many features |
| Ansible execution | subprocess calls | ansible-runner | Handles artifacts, events, async, edge cases |
| XDG paths | Path.home() + hardcoded | pathlib with XDG_CONFIG_HOME check | Respects user preferences |
| Version parsing | regex on --version | Structured parsing + dataclass | Testable, maintainable |

**Key insight:** The CLI and execution layers have mature, well-tested solutions. Focus implementation effort on Clawrium-specific logic like registry management and claw orchestration, not infrastructure.

## Common Pitfalls

### Pitfall 1: Snake Case to Kebab Case in Typer
**What goes wrong:** Function `host_add` becomes CLI command `host-add`
**Why it happens:** Typer auto-converts underscores to dashes
**How to avoid:** Accept the conversion (it's CLI standard) or use `@app.command(name="host_add")` to override
**Warning signs:** Commands not found when using underscores

### Pitfall 2: Missing Build System for Entry Points
**What goes wrong:** `[project.scripts]` entry points don't work with `uv run`
**Why it happens:** Entry points require the package to be installed
**How to avoid:** Use `uv pip install -e .` for development, or use `uv run python -m clawrium.cli.main`
**Warning signs:** "command not found" after defining scripts

### Pitfall 3: Config Directory Race Conditions
**What goes wrong:** Multiple `clm` invocations try to create directory simultaneously
**Why it happens:** mkdir without exist_ok or locking
**How to avoid:** Always use `mkdir(parents=True, exist_ok=True)`
**Warning signs:** FileExistsError on first run

### Pitfall 4: ansible-runner Without Ansible Installed
**What goes wrong:** ansible-runner imports succeed but execution fails
**Why it happens:** ansible-runner is a Python wrapper; Ansible itself must be installed
**How to avoid:** Check for `ansible` binary BEFORE attempting ansible-runner operations
**Warning signs:** "ansible-playbook not found" errors at runtime

### Pitfall 5: External-Managed-Environment on Ubuntu
**What goes wrong:** pip install fails with "externally-managed-environment" error
**Why it happens:** Ubuntu 23.04+ protects system Python
**How to avoid:** Recommend pipx for Ansible installation in user instructions
**Warning signs:** Users report they can't follow install instructions

## Code Examples

### pyproject.toml for Clawrium
```toml
# Source: https://typer.tiangolo.com/tutorial/package/ + https://docs.astral.sh/uv/guides/projects/
[project]
name = "clawrium"
version = "0.1.0"
description = "CLI tool for managing AI assistant fleets"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "typer>=0.24.0",
    "rich>=14.0.0",
    "ansible-runner>=2.4.0",
]

[project.scripts]
clm = "clawrium.cli.main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/clawrium"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-cov>=6.0.0",
]
```

### Main CLI Entry Point
```python
# src/clawrium/cli/main.py
# Source: https://typer.tiangolo.com/tutorial/
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="clm",
    help="Clawrium - Manage your AI assistant fleet",
    no_args_is_help=True,
)
console = Console()

@app.command()
def init():
    """Initialize Clawrium and check dependencies."""
    from clawrium.core.config import init_config_dir
    from clawrium.core.deps import check_all_dependencies

    # Create config directory
    config_dir = init_config_dir()
    console.print(f"[green]Config directory:[/green] {config_dir}")

    # Check dependencies
    deps = check_all_dependencies()

    table = Table(title="Dependency Status")
    table.add_column("Dependency", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Version/Path")
    table.add_column("Action Required")

    for dep in deps:
        status = "[green]OK[/green]" if dep.found else "[red]MISSING[/red]"
        version = dep.version or dep.path or "-"
        action = dep.install_hint if not dep.found else "-"
        table.add_row(dep.name, status, version, action)

    console.print(table)

    if not all(dep.found for dep in deps):
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
```

### Testing the CLI
```python
# tests/test_cli_init.py
# Source: https://typer.tiangolo.com/tutorial/testing/
from typer.testing import CliRunner
from clawrium.cli.main import app

runner = CliRunner()

def test_init_creates_config_dir(tmp_path, monkeypatch):
    """Test that clm init creates the config directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    result = runner.invoke(app, ["init"])

    assert (tmp_path / "clawrium").exists()
    assert "Config directory:" in result.output

def test_init_shows_dependency_status():
    """Test that clm init shows dependency table."""
    result = runner.invoke(app, ["init"])

    assert "Dependency Status" in result.output
    assert "python" in result.output.lower() or "Python" in result.output
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pip install | uv (or pipx for tools) | 2024-2025 | 10-100x faster installs, better dependency resolution |
| argparse/click | Typer | 2020+ | Type hints, better DX, auto-completion |
| print() | Rich | 2020+ | Beautiful terminal output, cross-platform |
| ansible Python API | ansible-runner | 2019+ | Cleaner interface, artifact management |

**Deprecated/outdated:**
- **setup.py/setup.cfg:** Use pyproject.toml instead (PEP 517/518)
- **distutils:** Removed in Python 3.12+
- **requirements.txt as source of truth:** Use pyproject.toml + lockfile

## Open Questions

1. **Version constraints for dependencies**
   - What we know: Latest versions work; need minimum versions for stability
   - What's unclear: Exact minimum versions to support
   - Recommendation: Pin to major versions (e.g., `typer>=0.24.0`, `rich>=14.0.0`)

2. **Config file format inside ~/.config/clawrium/**
   - What we know: Directory will be created
   - What's unclear: What files go inside (config.toml? hosts.yaml?)
   - Recommendation: Defer to Phase 2; Phase 1 only creates the directory

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pyproject.toml `[tool.pytest.ini_options]` (Wave 0) |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest tests/ -v --cov=clawrium` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INIT-01 | Config directory created at expected path | unit | `uv run pytest tests/test_cli_init.py::test_init_creates_config_dir -x` | Wave 0 |
| INIT-01 | Respects XDG_CONFIG_HOME | unit | `uv run pytest tests/test_cli_init.py::test_init_respects_xdg -x` | Wave 0 |
| INIT-02 | Shows dependency status table | unit | `uv run pytest tests/test_cli_init.py::test_init_shows_dependency_status -x` | Wave 0 |
| INIT-02 | Detects missing Ansible | unit | `uv run pytest tests/test_deps.py::test_ansible_missing -x` | Wave 0 |
| INIT-02 | Shows install instructions for missing deps | unit | `uv run pytest tests/test_deps.py::test_install_hints -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/ -x -q`
- **Per wave merge:** `uv run pytest tests/ -v --cov=clawrium`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `pyproject.toml` — needs `[tool.pytest.ini_options]` section
- [ ] `tests/conftest.py` — shared fixtures for tmp config dirs
- [ ] `tests/test_cli_init.py` — covers INIT-01
- [ ] `tests/test_deps.py` — covers INIT-02
- [ ] Framework install: `uv add --dev pytest pytest-cov`

## Sources

### Primary (HIGH confidence)
- [PyPI typer](https://pypi.org/project/typer/) - Version 0.24.1, Feb 2026
- [PyPI ansible-runner](https://pypi.org/project/ansible-runner/) - Version 2.4.3, Mar 2026
- [PyPI rich](https://pypi.org/project/rich/) - Version 14.3.3, Feb 2026
- [Typer Official Docs](https://typer.tiangolo.com/) - CLI structure, testing, packaging
- [uv Official Docs](https://docs.astral.sh/uv/) - Project setup, pyproject.toml
- [ansible-runner Docs](https://ansible-runner.readthedocs.io/) - Python interface

### Secondary (MEDIUM confidence)
- [xdg-base-dirs GitHub](https://github.com/srstevenson/xdg-base-dirs) - XDG path resolution patterns
- [Python shutil.which docs](https://docs.python.org/3/library/shutil.html) - Executable detection

### Tertiary (LOW confidence)
- None - all claims verified against primary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all versions verified against PyPI on 2026-03-20
- Architecture: HIGH - patterns from official Typer documentation
- Pitfalls: HIGH - documented in official sources and community patterns

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (30 days - stable libraries)
