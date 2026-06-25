"""`clawctl agent describe <name>` — single-agent detail.

Plan §6.7 layout: Name / Kind / Type / Version / Host / Provider /
Status / Age / Installed + Config + Skills + Integrations + Channels
+ Onboarding sections.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl.agent._shared import agent_to_row, safe_resolve_agent
from clawrium.cli.output import dump_json, dump_yaml, format_age, format_status
from clawrium.cli.output._sanitize import sanitize


def _s(value: object) -> str:
    """Per-field sanitize (ATX iter-1 B1).

    Agent describe is the worst exposure surface — config/identity/skills
    fields are attacker-reachable via prior `configure` calls. Apply per
    interpolation site; never on the joined block (sanitize collapses
    `\\n` so a single call would compact the whole output to one line).
    """
    return sanitize(str(value))


def describe(
    name: str = typer.Argument(..., help="Agent name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (yaml/json or text)."
    ),
) -> None:
    """Describe a single agent."""
    host, agent_key, claw_record = safe_resolve_agent(name)
    row = agent_to_row(host, agent_key, claw_record)

    if output is OutputFormat.json:
        typer.echo(dump_json([row]), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml([row]), nl=False)
        return

    lines: list[str] = []
    lines.append(f"Name:       {_s(row['name'])}")
    lines.append("Kind:       agent")
    lines.append(f"Type:       {_s(row['type'])}")
    lines.append(f"Version:    {_s(row['version'] or '-')}")
    lines.append(f"Host:       {_s(row['host'])} ({_s(row['address'])})")
    lines.append(f"Provider:   {_s(row['provider'] or '-')}")
    lines.append(f"Status:     {format_status(_s(row['status']))}")
    lines.append(f"Age:        {format_age(int(row['age_seconds']))}")
    lines.append(f"Installed:  {_s(row['installed_at'] or '-')}")

    config = claw_record.get("config", {}) or {}
    lines.append("")
    lines.append("Config:")
    lines.append(f"  Port:    {_s(row['port'] or '-')}")
    identity = config.get("identity") or config.get("identity_file") or "-"
    lines.append(f"  Identity: {_s(identity)}")

    skills = (config.get("skills") or claw_record.get("skills") or []) or []
    lines.append("")
    lines.append(f"Skills ({len(skills)}):")
    for skill in skills:
        if isinstance(skill, dict):
            lines.append(f"  {_s(skill.get('name') or skill.get('ref', '?'))}")
        else:
            lines.append(f"  {_s(skill)}")

    integrations = config.get("integrations") or claw_record.get("integrations") or {}
    if isinstance(integrations, dict):
        integration_names = sorted(integrations.keys())
    else:
        integration_names = list(integrations)
    lines.append("")
    lines.append(f"Integrations ({len(integration_names)}):")
    for integration in integration_names:
        lines.append(f"  {_s(integration)}  (configured)")

    channels = (claw_record.get("channels") or []) or []
    lines.append("")
    if channels:
        lines.append(f"Channels ({len(channels)}):")
        for channel in channels:
            if isinstance(channel, dict):
                lines.append(f"  {_s(channel.get('name') or channel.get('type', '?'))}")
            else:
                lines.append(f"  {_s(channel)}")
    else:
        lines.append("Channels: none")

    onboarding = claw_record.get("onboarding", {}) or {}
    stages = onboarding.get("stages", {}) or {}
    lines.append("")
    lines.append("Onboarding:")
    for stage in ("providers", "identity", "channels", "validate"):
        info = stages.get(stage, {})
        if isinstance(info, dict):
            # Stage records are written by core/onboarding.py under the
            # key `status` ("complete" / "skipped" / "failed") — see
            # complete_stage (line 327) and initialize_onboarding
            # (lines 451-457). The `state` fallback is a read-compat
            # shim for handwritten or third-party records that use the
            # old key shape; covered by
            # `test_describe_stage_state_key_fallback`.
            #
            # Explicit `is not None` check (not `or`-chain) so a
            # handwritten record with `{"status": ""}` is treated as
            # "status key present but empty" → renders "pending"
            # rather than silently falling through to the state-key
            # shim. ATX iter-3 W-N-2.
            raw_status = info.get("status")
            if raw_status is None:
                raw_status = info.get("state")
            stage_state = raw_status or "pending"
            completed = info.get("completed_at", "")
        else:
            stage_state = str(info)
            completed = ""
        completed_part = f"   ({_s(completed)})" if completed else ""
        lines.append(f"  {stage:<10} {_s(stage_state)}{completed_part}")

    typer.echo("\n".join(lines))
