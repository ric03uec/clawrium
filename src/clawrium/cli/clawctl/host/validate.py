"""`clawctl host validate <hostname>` — fleet-visibility health probe.

Phase 3 of #11 (issue #945). Aggregates `nemoclaw status <sandbox>`
for every openclaw agent on the target host and reports:

- exit 0 when every openclaw sandbox reports healthy;
- exit 1 when any sandbox is unhealthy or unreachable;
- exit 0 with a "no openclaw agents" note when the host has none
  (a host with only hermes/zeroclaw agents is trivially valid).

Read-only: dispatches the `nemoclaw_status` playbook per agent via
the shared `_run_lifecycle_playbook` seam so the sandbox_name
extravar plumbing lands on the same code path as sync/remove.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl.host._shared import safe_get_host
from clawrium.cli.output import dump_json, dump_yaml, render_table
from clawrium.cli.output._sanitize import sanitize


def validate(
    hostname: str = typer.Argument(..., help="Host name or alias."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(
        False, "--no-headers", help="Skip the header row (table mode only)."
    ),
) -> None:
    """Validate openclaw sandbox health on a host."""
    host = safe_get_host(hostname)
    rows = _probe_openclaw_agents(host)

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        raise typer.Exit(code=_exit_code(rows))
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        raise typer.Exit(code=_exit_code(rows))

    if not rows:
        typer.echo(f"host {sanitize(hostname)!r}: no openclaw agents to validate")
        raise typer.Exit(code=0)

    headers = ["AGENT", "SANDBOX", "STATUS", "DETAIL"]
    body = [
        [
            sanitize(str(r["agent"])),
            sanitize(str(r["sandbox"])),
            sanitize(str(r["status"])),
            sanitize(str(r["detail"] or "")),
        ]
        for r in rows
    ]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)
    raise typer.Exit(code=_exit_code(rows))


def _exit_code(rows: list[dict]) -> int:
    return 0 if all(r["status"] == "healthy" for r in rows) else 1


def _probe_openclaw_agents(host: dict) -> list[dict]:
    """Dispatch nemoclaw_status per openclaw agent and collect rows.

    Non-openclaw agents are skipped silently — a host mixing hermes +
    openclaw only surfaces the openclaw rows. Runs are sequential:
    parallelism here would require overlapping ansible-runner invocations
    on the same host, which is a documented anti-pattern
    (`_run_lifecycle_playbook` acquires no cross-invocation lock).
    """
    from clawrium.core.lifecycle import _run_lifecycle_playbook

    rows: list[dict] = []
    agents = host.get("agents", {}) or {}
    for agent_key, record in agents.items():
        if not isinstance(record, dict):
            continue
        if (record.get("type") or agent_key) != "openclaw":
            continue

        config = record.get("config") or {}
        sandbox_name = config.get("sandbox_name") if isinstance(config, dict) else None
        agent_display = record.get("agent_name") or agent_key

        if not isinstance(sandbox_name, str) or not sandbox_name:
            rows.append(
                {
                    "agent": agent_display,
                    "sandbox": "",
                    "status": "legacy",
                    "detail": ("no sandbox_name in hosts.json — remove + re-create"),
                }
            )
            continue

        try:
            success, err = _run_lifecycle_playbook(
                agent_type="openclaw",
                agent_name=agent_key,
                hostname=host["hostname"],
                operation="nemoclaw_status",
                host=host,
                timeout=60,
            )
        except Exception as exc:  # pragma: no cover — defensive boundary
            rows.append(
                {
                    "agent": agent_display,
                    "sandbox": sandbox_name,
                    "status": "error",
                    "detail": f"probe failed: {exc}",
                }
            )
            continue

        rows.append(
            {
                "agent": agent_display,
                "sandbox": sandbox_name,
                "status": "healthy" if success else "unhealthy",
                "detail": None if success else (err or "unknown error"),
            }
        )

    return rows
