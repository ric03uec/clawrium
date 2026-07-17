"""`clawctl agent doctor <name>` — F4 of parent #555.

Lists every declared attachment, every secret status, and every
rendered field for one agent. Local-only: never touches the host. The
output is a deterministic, machine-comparable snapshot of what
`build_render_inputs` would assemble *right now* from clawctl's own
stores (providers.json + channels.json + integrations.json +
secrets.json + hosts.json).

Two outputs:

- table (default): human-readable sections (Attachments, Resolved
  inputs, Rendered files).
- json (`-o json`): the same data as a single object, suitable for
  diffing against `tests/fixtures/audit_2026_05_29.json` per #555 F4.

A failing `build_render_inputs` (the on-purpose loud failure mode of
parent #555) is rendered as `status: broken` plus the exact lookup
error so the operator can fix the attach/secret/registry record. The
declared-attachment list is shown either way so the operator can see
the gap between what the agent record claims and what clawctl can
resolve.
"""

from __future__ import annotations

import hashlib

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl.agent._shared import safe_resolve_agent
from clawrium.cli.output import dump_json, dump_yaml, emit_error
from clawrium.cli.output._sanitize import sanitize
from clawrium.core.render import (
    AgentConfigError,
    RenderedFiles,
    RenderInputs,
    build_render_inputs,
    render_ethos,  # noqa: F401 — re-exported for test monkeypatching.
    render_hermes,  # noqa: F401 — re-exported for test monkeypatching.
    render_openclaw,  # noqa: F401 — re-exported for test monkeypatching.
    render_zeroclaw,  # noqa: F401 — re-exported for test monkeypatching.
)


# Map agent type → attribute name on THIS module. Looking up via
# `globals()[name]` (rather than capturing the function reference at
# import time) lets `monkeypatch.setattr(doctor_mod, "render_X", ...)`
# work without callers having to know about the dispatch table.
_RENDERER_NAMES = {
    "ethos": "render_ethos",
    "hermes": "render_hermes",
    "zeroclaw": "render_zeroclaw",
    "openclaw": "render_openclaw",
}


def _s(value: object) -> str:
    return sanitize(str(value))


def _present(value: str) -> str:
    return "present" if value else "missing"


def _safe_endpoint(value: str) -> str:
    """Redact an endpoint that embeds URL credentials.

    ATX iter-1 W1: enterprise / corporate-proxy providers commonly
    point at endpoints like `https://user:key@llm-proxy.corp/v1`.
    Doctor's whole purpose is producing output that's safe to paste
    into a bug report, so a URL-embedded credential must be masked
    even though it's technically a "config" field.

    ATX iter-2 B7: bare-token userinfo (no `:` before `@`, e.g.
    `https://sk-token@host/v1`) is also a credential — the whole
    userinfo segment is the token. Mask it too.
    """
    if not value:
        return ""
    import re

    # `user:password@` form → preserve the user, mask the password.
    masked = re.sub(
        r"^(\w+://)([^/@:]+):([^/@]+)@",
        r"\1\2:***@",
        value,
    )
    if masked != value:
        return masked
    # `token@` form (no colon in userinfo) → mask the whole userinfo.
    # `[^/@:]+` excludes `:` so we don't accidentally re-match the
    # `user:password@` form whose colon happens to follow a non-mask
    # branch (handled above already, but explicit is cheaper than
    # debugging an ordering bug later).
    return re.sub(
        r"^(\w+://)([^/@:]+)@",
        r"\1***@",
        value,
    )


def _render_for(inputs: RenderInputs) -> RenderedFiles | None:
    """Dispatch to the per-agent-type renderer; return None on unknown type."""
    name = _RENDERER_NAMES.get(inputs.agent_type)
    if name is None:
        return None
    return globals()[name](inputs)


def _attachments_block(claw_record: dict) -> dict:
    """Extract declared attachment lists from the agent record.

    These are what clawctl *thinks* is attached. The resolved block
    below shows what could actually be hydrated. A divergence between
    the two is exactly the silent-wipe class of bugs #555 was filed
    against.
    """
    return {
        "providers": list(claw_record.get("providers") or []),
        "channels": list(claw_record.get("channels") or []),
        "integrations": list(claw_record.get("integrations") or []),
        "skills": list(claw_record.get("skills") or []),
    }


def _inputs_block(inputs: RenderInputs) -> dict:
    """Serialize the resolved RenderInputs into a JSON-safe dict.

    Secret values are NEVER emitted; only their presence is reported.
    Doctor is a diagnostic surface — leaking a bearer token into a
    JSON report (which operators commonly attach to bug reports)
    would be a regression in its own right.
    """
    provider = {
        "name": inputs.provider.name,
        "type": inputs.provider.type,
        "endpoint": _safe_endpoint(inputs.provider.endpoint),
        "default_model": inputs.provider.default_model,
        "region": inputs.provider.region,
        "api_key": _present(inputs.provider.api_key),
        "aws_access_key": _present(inputs.provider.aws_access_key),
        "aws_secret_key": _present(inputs.provider.aws_secret_key),
    }
    channels = [
        {
            "name": ch.name,
            "type": ch.type,
            "bot_token": _present(ch.bot_token),
            "app_token": _present(ch.app_token),
            "allowed_users": list(ch.allowed_users),
            "allowed_guilds": list(ch.allowed_guilds),
            "allowed_channels": list(ch.allowed_channels),
            "require_mention": ch.require_mention,
            "allow_all_users": ch.allow_all_users,
            "stream_mode": ch.stream_mode,
        }
        for ch in inputs.channels
    ]
    integrations = [
        {
            "name": it.name,
            "type": it.type,
            "credentials": [
                {"key": k, "value": _present(v)} for k, v in it.credentials
            ],
        }
        for it in inputs.integrations
    ]
    api_server = None
    if inputs.api_server is not None:
        api_server = {
            "host": inputs.api_server.host,
            "port": inputs.api_server.port,
            "key": _present(inputs.api_server.key),
        }
    gateway = None
    if inputs.gateway is not None:
        gateway = {
            "host": inputs.gateway.host,
            "port": inputs.gateway.port,
            "auth": _present(inputs.gateway.auth),
            "bind": inputs.gateway.bind,
            "allow_public_bind": inputs.gateway.allow_public_bind,
        }
        # W1 (#924): api_key / internal_port are ethos-only gateway
        # fields. Emitting them unconditionally would silently widen the
        # JSON schema for every zeroclaw/openclaw agent with a gateway
        # block (`"api_key": "missing"`, `"internal_port": 0`) — noise
        # for consumers parsing `-o json`.
        if inputs.agent_type == "ethos":
            gateway["api_key"] = _present(inputs.gateway.api_key)
            gateway["internal_port"] = inputs.gateway.internal_port
    return {
        "provider": provider,
        "channels": channels,
        "integrations": integrations,
        "api_server": api_server,
        "gateway": gateway,
    }


def _files_block(rendered: RenderedFiles) -> list[dict]:
    """Per-file digest + size for the rendered bundle.

    The sha256 prefix lets `tests/fixtures/audit_2026_05_29.json` pin
    byte-determinism without storing the full rendered content (which
    would make the fixture noisy on legitimate template edits).
    """
    out: list[dict] = []
    for path, body in rendered.files.items():
        raw = body.encode("utf-8")
        out.append(
            {
                "path": path,
                "bytes": len(raw),
                "lines": body.count("\n"),
                "sha256_prefix": hashlib.sha256(raw).hexdigest()[:16],
            }
        )
    return out


def _report(name: str, claw_record: dict) -> dict:
    """Build the full diagnostic report. Pure: no host access."""
    report: dict = {
        "name": name,
        "type": claw_record.get("type", ""),
        "status": "ok",
        "error": None,
        "declared": _attachments_block(claw_record),
        "inputs": None,
        "files": [],
    }
    try:
        inputs = build_render_inputs(name)
    except AgentConfigError as exc:
        report["status"] = "broken"
        report["error"] = str(exc)
        return report
    report["inputs"] = _inputs_block(inputs)
    # W5 (#924): the renderer itself can raise AgentConfigError (duplicate
    # channel type, gateway=None, unsupported provider). Doctor's contract
    # is a structured `status: broken` report + non-zero exit — never an
    # unhandled traceback.
    try:
        rendered = _render_for(inputs)
    except AgentConfigError as exc:
        report["status"] = "broken"
        report["error"] = str(exc)
        return report
    if rendered is None:
        report["status"] = "broken"
        report["error"] = (
            f"no renderer registered for agent type {inputs.agent_type!r}"
        )
        return report
    report["files"] = _files_block(rendered)
    return report


def _render_table(report: dict) -> str:
    lines: list[str] = []
    lines.append(f"Name:    {_s(report['name'])}")
    lines.append(f"Type:    {_s(report['type'])}")
    status = report["status"]
    lines.append(f"Status:  {_s(status)}")
    if report.get("error"):
        lines.append(f"Error:   {_s(report['error'])}")

    declared = report["declared"]
    lines.append("")
    lines.append("Declared attachments:")
    lines.append(f"  providers:    {declared['providers'] or '-'}")
    lines.append(f"  channels:     {declared['channels'] or '-'}")
    lines.append(f"  integrations: {declared['integrations'] or '-'}")
    lines.append(f"  skills:       {declared['skills'] or '-'}")

    inputs = report.get("inputs")
    if inputs:
        provider = inputs["provider"]
        lines.append("")
        lines.append("Resolved provider:")
        lines.append(f"  name:           {_s(provider['name'])}")
        lines.append(f"  type:           {_s(provider['type'])}")
        if provider["default_model"]:
            lines.append(f"  default_model:  {_s(provider['default_model'])}")
        if provider["endpoint"]:
            lines.append(f"  endpoint:       {_s(provider['endpoint'])}")
        if provider["region"]:
            lines.append(f"  region:         {_s(provider['region'])}")
        lines.append(f"  api_key:        {provider['api_key']}")
        if provider["aws_access_key"] != "missing":
            lines.append(f"  aws_access_key: {provider['aws_access_key']}")
            lines.append(f"  aws_secret_key: {provider['aws_secret_key']}")

        lines.append("")
        if inputs["channels"]:
            lines.append(f"Resolved channels ({len(inputs['channels'])}):")
            for ch in inputs["channels"]:
                lines.append(
                    f"  {_s(ch['name'])}  type={_s(ch['type'])}  "
                    f"bot_token={ch['bot_token']}"
                    + (
                        f"  app_token={ch['app_token']}"
                        if ch["type"] == "slack"
                        else ""
                    )
                )
        else:
            lines.append("Resolved channels: none")

        lines.append("")
        if inputs["integrations"]:
            lines.append(f"Resolved integrations ({len(inputs['integrations'])}):")
            for it in inputs["integrations"]:
                creds = ", ".join(
                    f"{c['key']}={c['value']}" for c in it["credentials"]
                )
                lines.append(
                    f"  {_s(it['name'])}  type={_s(it['type'])}  {creds}"
                )
        else:
            lines.append("Resolved integrations: none")

        # W2 (#924): the gateway diagnostic block must be visible in the
        # default table output too, not only via `-o json` / `-o yaml` —
        # the api_key present/missing signal is the primary thing an
        # ethos operator runs doctor for.
        gw = inputs.get("gateway")
        if gw:
            lines.append("")
            lines.append("Resolved gateway:")
            lines.append(f"  host:           {_s(gw['host'])}")
            lines.append(f"  port:           {gw['port']}")
            lines.append(f"  auth:           {gw['auth']}")
            if gw["bind"]:
                lines.append(f"  bind:           {_s(gw['bind'])}")
            if "api_key" in gw:
                lines.append(f"  api_key:        {gw['api_key']}")
            if "internal_port" in gw:
                lines.append(f"  internal_port:  {gw['internal_port']}")

        files = report["files"]
        lines.append("")
        lines.append(f"Rendered files ({len(files)}):")
        for f in files:
            lines.append(
                f"  {_s(f['path'])}  bytes={f['bytes']}  "
                f"lines={f['lines']}  sha256={f['sha256_prefix']}"
            )
    return "\n".join(lines) + "\n"


def doctor(
    name: str = typer.Argument(..., help="Agent name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
) -> None:
    """Diagnose an agent's render bundle (declared vs resolved vs files).

    Reports BEFORE any clawctl operation would touch the host, so the
    operator can verify that `sync` / `configure` / `restart` are
    about to render a coherent bundle. Implements F4 of parent #555.
    """
    _host, _agent_key, claw_record = safe_resolve_agent(name)
    report = _report(name, claw_record)

    if output is OutputFormat.json:
        typer.echo(dump_json([report]), nl=False)
    elif output is OutputFormat.yaml:
        typer.echo(dump_yaml([report]), nl=False)
    else:
        typer.echo(_render_table(report), nl=False)

    if report["status"] != "ok":
        # Non-zero exit so CI / shell pipelines can gate on doctor.
        emit_error(
            f"agent {name!r} is not in a renderable state",
            hint="see status above; fix the failing lookup and re-run",
        )
