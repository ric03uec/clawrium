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
from clawrium.core.web_ui import ResolvedUI, resolve as resolve_web_ui


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
        from clawrium.core.web_ui_tunnel import TunnelError
        from clawrium.core.web_ui_tunnel import ensure as ensure_tunnel

        try:
            # owned=False: tunnel subprocess outlives CLI — no atexit cleanup.
            local_port = ensure_tunnel(name, owned=False)
        except TunnelError as exc:
            emit_error(
                f"tunnel setup failed for agent {name!r}: {exc}",
                hint=(
                    "check SSH config with 'clawctl host describe <host>'; "
                    "use --print-url to get the URL for manual SSH forwarding"
                ),
            )
        url = f"http://127.0.0.1:{local_port}"

    # For ethos agents, append the web token as a query param so the dashboard
    # frontend can authenticate its requests to ethos serve.
    claw_type = _claw_record.get("type", "")
    if claw_type == "ethos":
        agent_name = _claw_record.get("agent_name") or name
        if needs_tunnel:
            web_token = _read_ethos_web_token(resolved, agent_name)
        else:
            try:
                import builtins
                with builtins.open(f"/home/{agent_name}/.ethos/web-token") as _f:
                    web_token = _f.read().strip()
            except Exception:
                web_token = ""
        if web_token:
            from urllib.parse import quote
            url = f"{url}/auth/exchange?t={quote(web_token, safe='')}"

    if print_url:
        typer.echo(url)
        return

    stream_action(resource=f"agent/{name}", message=f"opening {url}")
    if not webbrowser.open(url):
        typer.echo(f"Could not open browser. URL: {url}", err=True)
        typer.echo(
            "Hint:  re-run with --print-url to get the URL for manual use.",
            err=True,
        )


def _ssh_run(resolved: ResolvedUI, remote_cmd: str, timeout: int = 10) -> str:
    """Run a single command on the remote host via SSH. Returns stdout stripped, or ''."""
    import subprocess

    ssh = resolved.ssh_config or {}
    user = ssh.get("user")
    if not user:
        return ""
    cmd = ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes"]
    port = ssh.get("port")
    if isinstance(port, int):
        cmd += ["-p", str(port)]
    identity = ssh.get("identity_file")
    if isinstance(identity, str):
        cmd += ["-i", identity]
    cmd += [f"{user}@{resolved.host}", remote_cmd]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _read_ethos_web_token(resolved: ResolvedUI, agent_name: str) -> str:
    """Read the ethos web-token from the remote host.

    Reads directly from the agent user's home directory to avoid picking up
    stale web-token files from other users on the same host.
    """
    return _ssh_run(
        resolved,
        f"sudo cat /home/{agent_name}/.ethos/web-token 2>/dev/null",
    )
