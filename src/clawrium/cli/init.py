"""Init command for Clawrium."""

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from clawrium.cli.output._sanitize import sanitize_passthrough
from clawrium.core.config import init_config_dir
from clawrium.core.deps import check_all_dependencies

__all__ = ["init"]

console = Console()


def _safe_terminal_value(value: str) -> str:
    """Remove terminal controls before treating untrusted text as Rich markup."""
    return escape(sanitize_passthrough(value))


def init() -> None:
    """Initialize Clawrium configuration directory and check dependencies.

    Creates the configuration directory at ~/.config/clawrium/
    (or XDG_CONFIG_HOME/clawrium/ if set) and verifies that all
    required dependencies are available.

    Exits with code 1 if any dependency is missing.
    """
    # Create config directory
    try:
        config_dir = init_config_dir()
    except OSError:
        console.print("[red]Unable to initialize the Clawrium config directory.[/red]")
        console.print(
            "[yellow]Use a private, real XDG_CONFIG_HOME directory owned by the invoking user.[/yellow]"
        )
        raise typer.Exit(code=1) from None
    console.print("[green]Clawrium initialized![/green]")
    console.print(f"Config directory: {_safe_terminal_value(str(config_dir))}")
    console.print()

    # Check dependencies
    deps = check_all_dependencies()

    table = Table(title="Dependency Status")
    table.add_column("Dependency", style="cyan")
    table.add_column("Status")
    table.add_column("Version/Path")
    table.add_column("Action Required")

    all_found = True
    for dep in deps:
        if dep.found:
            status = "[green]OK[/green]"
        else:
            status = "[red]MISSING[/red]"
            all_found = False

        version_or_path = dep.version or dep.path or "-"
        action = dep.install_hint if not dep.found else "-"
        table.add_row(
            _safe_terminal_value(dep.name),
            status,
            _safe_terminal_value(version_or_path),
            _safe_terminal_value(action),
        )

    console.print(table)

    if not all_found:
        console.print()
        console.print(
            "[yellow]Some dependencies are missing. Please install them before continuing.[/yellow]"
        )
        raise typer.Exit(code=1)
