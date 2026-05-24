"""`clawctl version` and `clawctl completion` — meta verbs.

Plan §4 / §5:

- `clawctl version`           → prints `clawctl <version>` to stdout.
- `clawctl --version`         → same, handled in the root callback.
- `clawctl completion <shell>` → emits a Click-generated completion
  script for bash/zsh/fish. The user pipes the output into their shell
  rc file (`clawctl completion bash >> ~/.bashrc`).

Click's `shell_completion` module owns the script generation; we just
expose it as a Typer subcommand with a friendly enum of shells. Calling
`get_completion_class(shell)(...).source()` is the same path Click uses
internally for `_<APP>_COMPLETE=<shell>_source`.
"""

from enum import Enum

import click
import typer
from click import shell_completion

from clawrium import __version__

__all__ = ["Shell", "completion_cmd", "version_cmd"]


class Shell(str, Enum):
    """Supported shells for `clawctl completion`."""

    bash = "bash"
    zsh = "zsh"
    fish = "fish"


def version_cmd() -> None:
    """Show clawctl version and exit."""
    typer.echo(f"clawctl {__version__}")


def completion_cmd(
    shell: Shell = typer.Argument(
        ..., help="Shell to generate completion for (bash, zsh, or fish)."
    ),
) -> None:
    """Emit a shell-completion script for `clawctl`.

    Usage:
      clawctl completion bash >> ~/.bashrc
      clawctl completion zsh  >> ~/.zshrc
      clawctl completion fish >> ~/.config/fish/completions/clawctl.fish
    """
    complete_class = shell_completion.get_completion_class(shell.value)
    if complete_class is None:
        # Shouldn't be reachable — Enum constrains the input.
        typer.echo(f"Error: unsupported shell: {shell.value}", err=True)
        raise typer.Exit(code=1)

    ctx = click.get_current_context()
    root = ctx.find_root().command
    instance = complete_class(
        cli=root,
        ctx_args={},
        prog_name="clawctl",
        complete_var="_CLAWCTL_COMPLETE",
    )
    typer.echo(instance.source())
