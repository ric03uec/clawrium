"""`clawctl agent sync <name>` — drift-to-zero flush (plan §9).

The redefined sync emits one streaming line per phase (plan §6.10):

    1. validating local state
    2. pushing config (provider, skills, channels, env)
    3. restarting unit
    4. re-pairing gateway
    5. verifying health
    + final `synced (drift=0, took Xs)`

Implementation note: `core/lifecycle.py:sync_agent` already does the
heavy lifting (validate + configure-with-restart-via-notify + re-pair
per issue #437). For #508 we wrap it and translate its internal
`on_event(stage, message)` callbacks into the plan-§6.10 five-line
canonical sequence. The full mid-step decomposition (separate "push",
"restart", "re-pair", "verify" core APIs) is out of scope for #508
and tracked as a follow-up.

Flags:
- `--timeout 120` — 2-minute default; passed through to the underlying
  call (currently advisory: core/lifecycle does not honor a timeout
  parameter today, captured as a Callout).
- `--workspace` — workspace files only, no restart.
- `--dry-run` — validate + show intent, no push.
- `--diff` — (F8, parent #555) host-vs-rendered unified diff per file.
  Implies `--dry-run`. Reads on-host files via SSH so you can verify
  what `sync` is about to overwrite *before* it runs.
- `--skip-validate` — bypass step 1.
- `-o json` — NDJSON per phase instead of text lines.
"""

from __future__ import annotations

import time

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import (
    NDJSONStreamer,
    emit_error,
    stream_action,
)
from clawrium.core.lifecycle import LifecycleError, sync_agent
from clawrium.core.playbook_resolver import resolve_lifecycle_backend


_PHASES = (
    "validating local state",
    "pushing config (provider, skills, channels, env)",
    "restarting unit",
    "re-pairing gateway",
    "verifying health",
)


_RENDERERS = {
    "hermes": "render_hermes",
    "zeroclaw": "render_zeroclaw",
    "openclaw": "render_openclaw",
}


def _emit_diff(
    *,
    host: dict,
    agent_name: str,
    agent_type: str,
    resource: str,
    use_json: bool,
    streamer,
) -> None:
    """Render the host-vs-rendered diff for `--dry-run --diff`.

    Failures are reported as a single error line (not raised) so the
    dry-run path stays non-throwing — an operator running this to
    verify before a real sync should never have the diagnostic crash
    the session.
    """
    # Deferred imports keep `clawctl agent sync` import-cheap when the
    # diff path is not exercised (the common case).
    from clawrium.core import render as _render_mod
    from clawrium.core.render import AgentConfigError, build_render_inputs
    from clawrium.core.render_diff import diff_files

    renderer_name = _RENDERERS.get(agent_type)
    if renderer_name is None:
        _emit_diff_error(
            f"no renderer for agent type {agent_type!r}",
            resource=resource,
            use_json=use_json,
            streamer=streamer,
        )
        return
    renderer = getattr(_render_mod, renderer_name)

    try:
        inputs = build_render_inputs(agent_name)
        rendered = renderer(inputs)
    except AgentConfigError as exc:
        _emit_diff_error(
            f"cannot render: {exc}",
            resource=resource,
            use_json=use_json,
            streamer=streamer,
        )
        return

    try:
        results = diff_files(
            host=host, agent_name=agent_name, rendered_files=rendered.files
        )
    except Exception as exc:  # paramiko / key lookup / SSH errors
        _emit_diff_error(
            f"diff read failed: {exc}",
            resource=resource,
            use_json=use_json,
            streamer=streamer,
        )
        return

    if use_json and streamer is not None:
        for d in results:
            streamer.emit(
                resource=resource,
                phase="diff",
                state="result",
                path=d.path,
                remote_path=d.remote_path,
                remote_present=d.remote_present,
                changed=bool(d.unified_diff),
                diff=d.unified_diff,
            )
        return

    # Text mode: print a human-readable header + unified diff per file.
    for d in results:
        if not d.unified_diff:
            stream_action(
                resource=resource,
                message=f"diff {d.path}: no changes",
            )
            continue
        marker = "would create" if not d.remote_present else "would change"
        stream_action(
            resource=resource,
            message=f"diff {d.path}: {marker}",
        )
        # Emit the diff body verbatim. `stream_action` adds the
        # resource prefix and sanitization which would mangle a
        # multi-line patch; write directly instead.
        typer.echo(d.unified_diff, nl=False)


def _emit_diff_error(
    message: str, *, resource: str, use_json: bool, streamer
) -> None:
    if use_json and streamer is not None:
        streamer.emit(
            resource=resource,
            phase="diff",
            state="error",
            message=message,
        )
    else:
        stream_action(resource=resource, message=f"diff error: {message}")


def sync(
    name: str = typer.Argument(..., help="Agent name."),
    workspace: bool = typer.Option(
        False, "--workspace", help="Workspace files only; no restart."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate + show intent; no push."
    ),
    diff: bool = typer.Option(
        False,
        "--diff",
        help=(
            "Show host-vs-rendered unified diff per file. Implies --dry-run. "
            "Reads on-host files via SSH; no host writes."
        ),
    ),
    timeout: int = typer.Option(
        120, "--timeout", min=1, help="Sync timeout in seconds (default 2 min)."
    ),
    skip_validate: bool = typer.Option(
        False, "--skip-validate", help="Bypass step 1 (validate)."
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table or json)."
    ),
) -> None:
    """Flush local control-plane state to the agent (drift-to-zero)."""
    # Bug #516: see configure.py for full rationale.
    host, _agent_type, claw_record = safe_resolve_agent(name)
    agent_key = resolve_agent_key(host, name)
    hostname = host["hostname"]
    agent_type = claw_record.get("type", _agent_type)

    # F8 (parent #555): `--diff` implies `--dry-run`. Promote here so
    # the phase-emission and short-circuit logic below sees the
    # effective intent without callers having to remember to pass both.
    if diff:
        dry_run = True

    resource = f"agent/{name}"
    use_json = output is OutputFormat.json
    streamer = NDJSONStreamer() if use_json else None

    def emit_phase(phase: str, state: str, **extra: object) -> None:
        if use_json and streamer is not None:
            streamer.emit(resource=resource, phase=phase, state=state, **extra)
        else:
            # ATX iter-2 W2: visual distinction in text mode — `queued`
            # uses an ellipsis suffix so a user watching `clawctl agent
            # sync` doesn't confuse "ready to run" with "complete".
            if state == "queued":
                label = f"{phase} ..."
            elif state == "complete":
                label = phase
            else:
                label = f"{phase} ({state})"
            stream_action(resource=resource, message=label)

    started = time.monotonic()

    # ATX iter-1 W3/W4: do NOT pre-mark phases as `complete` before the
    # underlying call runs — if `sync_agent` fails, terminals would show
    # 5 "complete" lines followed by an error. Pre-emit as `queued` so
    # NDJSON consumers can distinguish from the post-call `complete`
    # summary. Bundle 5 will refactor `core/lifecycle.sync_agent` to
    # emit per-phase events directly, removing the need for pre-emission.
    phase_keys = ("validate", "push", "restart", "repair", "verify")
    for key, label in zip(phase_keys, _PHASES):
        if key == "validate" and skip_validate:
            continue
        if key == "restart" and workspace:
            continue
        if dry_run and key in ("push", "restart", "repair", "verify"):
            emit_phase(label, "skipped (dry-run)")
            continue
        emit_phase(label, "queued")

    if dry_run:
        if diff:
            # The on-host POSIX user (and home dir) is the agent's
            # `agent_name`, not the host-record dict key. Legacy
            # installs key by type ("openclaw") while modern installs
            # key by name; the home dir is always `<name>`.
            on_host_name = claw_record.get("agent_name") or agent_key
            _emit_diff(
                host=host,
                agent_name=on_host_name,
                agent_type=agent_type,
                resource=resource,
                use_json=use_json,
                streamer=streamer,
            )
        if use_json and streamer is not None:
            streamer.emit(
                resource=resource,
                phase="sync",
                state="dry-run complete",
            )
        else:
            stream_action(
                resource=resource, message="dry-run complete; no changes pushed"
            )
        return

    # Underlying call. The plan-§6.10 streaming lines above are emitted
    # eagerly before the call to match the canonical layout; the real
    # work happens inside `sync_agent`. Bundle-5 cleanup will refactor
    # `core/lifecycle.py` to expose per-phase APIs so we don't have to
    # pre-emit phase lines.
    def on_event(stage: str, message: str) -> None:
        # Forward sub-events verbatim so anyone tailing `-o json` sees
        # the underlying ansible chatter too.
        if use_json and streamer is not None:
            streamer.emit(
                resource=resource,
                phase=stage,
                state="event",
                message=message,
            )
            return
        # ATX iter-5 W2-NEW carry-forward: surface warning-prefixed
        # sync events (state-write failures, registry incoherence) in
        # non-JSON mode so the operator sees them. stream_action's
        # sanitize() handles non-printable chars; rich is not involved
        # at this output path.
        if stage == "sync" and message.startswith("warning:"):
            stream_action(resource=resource, message=message)

    # ATX iter-2 S6/W7: pre-bind `result` so a non-LifecycleError that
    # escapes the try does not cause `UnboundLocalError` at the
    # `result.get('success')` check below. Combined with the queued →
    # complete NDJSON contract gap (tracked for bundle 5 in this same
    # file's docstring), this is the surface most likely to bite CI
    # consumers; documenting both here keeps the trail visible.
    result: dict = {}
    try:
        # OS-family dispatch (CLI layer). #469 step 1 invariant.
        os_family = host.get("os_family", "linux")
        if os_family == "linux":
            sync_fn = sync_agent
        else:
            sync_fn = resolve_lifecycle_backend(os_family).sync_agent
        result = sync_fn(
            hostname=hostname,
            claw_name=agent_type,
            agent_name=agent_key,
            workspace_only=workspace,
            on_event=on_event,
        )
    except LifecycleError as exc:
        emit_error(f"sync failed: {exc}")

    elapsed = int(time.monotonic() - started)
    if elapsed > timeout:
        stream_action(
            resource=resource,
            message=f"warning: sync took {elapsed}s (timeout {timeout}s)",
        )

    if not result.get("success"):
        emit_error(f"sync failed: {result.get('error') or 'unknown error'}")

    if use_json and streamer is not None:
        streamer.emit(
            resource=resource,
            phase="sync",
            state="complete",
            drift=0,
            took_seconds=elapsed,
        )
    else:
        stream_action(resource=resource, message=f"synced  (drift=0, took {elapsed}s)")
