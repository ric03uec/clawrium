"""`clawctl agent open <name>` — open the agent's web UI in a browser.

Plan §"Specific Outcomes": only for agents whose manifest declares
`features.web_ui`. Delegates to `core/web_ui.py:resolve` and, for
remote hosts, opens an SSH tunnel via `core/web_ui_tunnel.py`.

The CLI spawns tunnels with ``owned=False`` so the SSH process outlives
the CLI invocation. The tunnel stays alive until the SSH connection
drops, the remote service stops, or the GUI idle-reaper cleans it up.
"""

from __future__ import annotations

import webbrowser

import typer

from clawrium.cli.clawctl._common import is_local_host
from clawrium.cli.clawctl.agent._shared import safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.web_ui import resolve as resolve_web_ui


def open(  # noqa: A001 — `open` matches plan §4 verb name
    name: str = typer.Argument(..., help="Agent name."),
    print_url: bool = typer.Option(
        False, "--print-url", help="Print the URL instead of launching a browser."
    ),
) -> None:
    """Open the agent's web UI in the default browser."""
    host, agent_key, _claw_record = safe_resolve_agent(name)

    # resolve_web_ui expects the user-facing instance name (the key in
    # hosts.json.agents), not the agent_type returned by get_agent_by_name.
    # Use `name` (the CLI argument) which is the instance name the user typed.
    resolved = resolve_web_ui(name)
    if resolved is None:
        emit_error(
            f"agent {name!r} has no web UI (manifest lacks features.web_ui)",
            hint="clawctl agent registry describe <type> to see supported features",
        )

    remote_port = resolved.remote_port  # type: ignore[union-attr]
    host_addr = resolved.host  # type: ignore[union-attr]

    needs_tunnel = not is_local_host(host_addr)

    if not needs_tunnel:
        url = f"http://127.0.0.1:{remote_port}"
    else:
        from clawrium.core.web_ui_tunnel import ensure as ensure_tunnel

        # owned=False: tunnel subprocess outlives CLI — no atexit cleanup.
        local_port = ensure_tunnel(name, owned=False)
        url = f"http://127.0.0.1:{local_port}"

    if print_url:
        typer.echo(url)
        return

    stream_action(resource=f"agent/{name}", message=f"opening {url}")
    webbrowser.open(url)
