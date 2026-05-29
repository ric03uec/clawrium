"""`clawctl agent sync <name>` — drift-to-zero flush (plan §9).

Routes through the F3 canonical pipeline (`sync_agent_canonical`) —
the only sync path since #560 dropped the `--canonical` opt-in flag.

Phase lines (plan §6.10, post-#560):

    1. validating local state
    2. pushing config (provider, skills, channels, env)
    3. restarting unit
    4. verifying health
    + final `synced (drift=0, took Xs)`

Note: the legacy 5-phase sequence included `re-pairing gateway`. The
canonical pipeline does not yet re-pair the zeroclaw gateway bearer;
that gap is tracked separately (see PR #566 Callouts).

Flags:
- `--timeout 120` — 2-minute default; advisory (canonical pipeline
  does not honor a timeout parameter today).
- `--workspace` — workspace files only, no restart.
- `--dry-run` — validate + show intent, no push.
- `--diff` — (F8, parent #555) host-vs-rendered unified diff per file.
  Implies `--dry-run`. Reads on-host files via SSH so you can verify
  what `sync` is about to overwrite *before* it runs.
- `--skip-validate` — bypass step 1.
- `--force` — allow writes that remove a host-side secret line.
  Required after `clawctl agent channel detach` or any other
  intentional secret-removal op; otherwise sync refuses with
  `SecretRemovalRefused`.
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


_PHASES = (
    "validating local state",
    "pushing config (provider, skills, channels, env)",
    "restarting unit",
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

    # ATX iter-1 W4: catch broadly. The diagnostic contract is
    # "diff cannot crash the dry-run" — any data-layer surprise
    # (KeyError on a misshapen provider record, AttributeError on an
    # unmapped channel type, JSONDecodeError from a corrupt store)
    # must reach the user as a `diff error:` line, not a stack
    # trace. AgentConfigError is the *expected* shape but we cannot
    # rely on every callee in the assembly chain to normalize to it.
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
    except Exception as exc:
        _emit_diff_error(
            f"cannot render: {type(exc).__name__}: {exc}",
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
        # ATX iter-1 B1: NEVER emit the unified diff body in NDJSON
        # mode. The diff text contains every secret line that differs
        # (`+OPENROUTER_API_KEY=...`, `+DISCORD_BOT_TOKEN=...`) and
        # NDJSON output is the format consumed by log aggregators, CI
        # logs, and monitoring sinks — surfaces that have no business
        # holding plaintext credentials. Text mode is the only path
        # that prints the patch; that is documented in
        # `docs/operations/sync.md`. The `contains_secret_values`
        # flag lets downstream consumers gate on this explicitly.
        for d in results:
            streamer.emit(
                resource=resource,
                phase="diff",
                state="result",
                path=d.path,
                remote_path=d.remote_path,
                remote_present=d.remote_present,
                changed=bool(d.unified_diff),
                contains_secret_values=bool(d.unified_diff),
                hint=(
                    "diff body suppressed in JSON mode; "
                    "re-run without -o json to see the patch"
                ),
            )
        return

    # Text mode: print a human-readable header + unified diff per file.
    from clawrium.cli.output._sanitize import sanitize_passthrough

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
        # ATX iter-1 B2: sanitize each line at the terminal output
        # boundary. The diff body originates from on-host file
        # contents which may contain bidi-override / zero-width /
        # control codepoints — exactly the class of bug #507
        # mandated guarding. `sanitize_passthrough` preserves
        # newlines / tabs (without which the unified-diff structure
        # would collapse) while stripping bidi + zero-width chars.
        # Line-by-line iteration preserves the per-line structure
        # that consumers rely on (e.g. paging the patch).
        for line in d.unified_diff.splitlines(keepends=True):
            typer.echo(sanitize_passthrough(line), nl=False)


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
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Allow writes that remove a host-side secret line. Required "
            "after `clawctl agent channel detach` or any other "
            "intentional secret-removal op; otherwise sync refuses."
        ),
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table or json)."
    ),
) -> None:
    """Flush local control-plane state to the agent (drift-to-zero)."""
    # Bug #516: see configure.py for full rationale.
    host, _agent_type, claw_record = safe_resolve_agent(name)
    agent_key = resolve_agent_key(host, name)
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
    phase_keys = ("validate", "push", "restart", "verify")
    for key, label in zip(phase_keys, _PHASES):
        if key == "validate" and skip_validate:
            continue
        if key == "restart" and workspace:
            continue
        # ATX iter-1 W3: in dry-run mode every phase short-circuits
        # before sync_agent runs (the early return at the dry_run
        # branch below). Emit `skipped (dry-run)` for ALL phases —
        # including `validate` — so NDJSON consumers don't see a
        # `queued` event that never resolves.
        if dry_run:
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

    # F3 (parent #555) canonical pipeline — the only sync path. Routes
    # through the pure render → diff → secret-removal-guard →
    # atomic-write → restart sequence. The legacy ansible extravar
    # path and the `--canonical` opt-in flag were dropped in #560.
    from clawrium.core.lifecycle_canonical import (
        CanonicalSyncError,
        SecretRemovalRefused,
        sync_agent_canonical,
    )
    from clawrium.core.render import AgentConfigError
    from clawrium.core.render_diff import RemoteReadError

    on_host_name = claw_record.get("agent_name") or agent_key

    def canonical_event(stage: str, message: str) -> None:
        if use_json and streamer is not None:
            streamer.emit(
                resource=resource, phase=stage, state="event", message=message
            )
        else:
            stream_action(resource=resource, message=f"{stage}: {message}")

    try:
        canonical_result = sync_agent_canonical(
            on_host_name,
            force=force,
            restart=not workspace,
            verify=not workspace,
            on_event=canonical_event,
        )
    except SecretRemovalRefused as exc:
        emit_error(str(exc))
        return
    except (AgentConfigError, CanonicalSyncError, RemoteReadError) as exc:
        emit_error(f"sync failed: {exc}")
        return

    elapsed = int(time.monotonic() - started)
    if elapsed > timeout:
        stream_action(
            resource=resource,
            message=f"warning: sync took {elapsed}s (timeout {timeout}s)",
        )

    if use_json and streamer is not None:
        streamer.emit(
            resource=resource,
            phase="sync",
            state="complete",
            drift=0,
            took_seconds=elapsed,
            files_written=list(canonical_result.files_written),
            files_unchanged=list(canonical_result.files_unchanged),
        )
    else:
        stream_action(
            resource=resource,
            message=(
                f"synced  (drift=0, took {elapsed}s, "
                f"{len(canonical_result.files_written)} written, "
                f"{len(canonical_result.files_unchanged)} unchanged)"
            ),
        )
