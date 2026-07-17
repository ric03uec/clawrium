"""`clawctl service` — system-level lifecycle ops.

Plan §4 / §5:

| Subcommand   | Status (this bundle) |
|--------------|----------------------|
| `init`       | Real — delegates to the same `init` implementation the legacy `clawctl init` used. |
| `start`      | Stub — prints `Not implemented: service start`, exits 0. |
| `stop`       | Stub — prints `Not implemented: service stop`, exits 0. |
| `snapshot`   | Stub — prints `Not implemented: service snapshot`, exits 0. |

`status` lands in a later issue (out of scope for #435 per the plan
table in §1). Stubs mirror today's `clawctl service snapshot` behavior — informative
message, zero exit code — so scripts can probe for availability without
crashing.
"""

import typer

from clawrium.cli.clawctl._stub import echo_not_implemented
from clawrium.cli.init import init as _init_impl

__all__ = ["service_app"]


service_app = typer.Typer(
    name="service",
    help="System-level lifecycle ops (init, start, stop, snapshot).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


@service_app.command("init")
def init() -> None:
    """Initialize Clawrium configuration and check dependencies."""
    _init_impl()


@service_app.command("start")
def start() -> None:
    """Start the Clawrium daemon (placeholder)."""
    # Delegate to the shared stub helper so the "Not implemented:"
    # wording stays in one place (#507 ATX iter-2 W2).
    echo_not_implemented("service", "start")


@service_app.command("stop")
def stop() -> None:
    """Stop the Clawrium daemon (placeholder)."""
    echo_not_implemented("service", "stop")


@service_app.command("snapshot")
def snapshot() -> None:
    """Snapshot fleet state (placeholder)."""
    echo_not_implemented("service", "snapshot")
