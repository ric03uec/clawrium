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
canonical pipeline NOW re-pairs the zeroclaw gateway bearer on every
sync invocation with `restart=True` (issue #437, restored in PR #568
ATX round 3). The phase is emitted as a `repair` event rather than a
numbered phase line so the user-visible sequence stays at 4 steps.

Flags:
- `--timeout 120` — 2-minute default; advisory (canonical pipeline
  does not honor a timeout parameter today).
- `--workspace-only` — workspace overlay only, no canonical render/restart.
- `--no-restart` — canonical render + workspace overlay, no restart.
- `--workspace` — removed (issue #760); exits 2 with a hint.
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


_PHASES = (
    "validating local state",
    "pushing config (provider, skills, channels, env)",
    "restarting unit",
    "verifying health",
)


_RENDERERS = {
    # #924 (ATX B1): ethos renders through render_ethos on every path
    # (doctor, configure, sync, and this --dry-run --diff table).
    "ethos": "render_ethos",
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
    workspace_only: bool = typer.Option(
        False,
        "--workspace-only",
        help=(
            "Push workspace overlay only. "
            "Skips canonical render, restart, verify. "
            "Mutually exclusive with --diff and --no-restart. "
            "Supported for zeroclaw — the gateway bearer is re-paired "
            "after the overlay push so hosts.json.gateway.auth stays in "
            "sync with the daemon."
        ),
    ),
    no_restart: bool = typer.Option(
        False,
        "--no-restart",
        help=(
            "Canonical render + workspace overlay; skip restart and verify. "
            "Supported for zeroclaw — the gateway bearer is re-paired "
            "even when restart is skipped, since any externally-driven "
            "daemon restart invalidates the on-disk bearer."
        ),
    ),
    workspace_deprecated: bool = typer.Option(
        False,
        "--workspace",
        hidden=True,
        help=(
            "[REMOVED] Use --no-restart for canonical+overlay-no-restart, "
            "or --workspace-only for overlay-only."
        ),
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
    """Flush local control-plane state and workspace overlay to the agent."""
    # Issue #760 W6 iter-2 / W2 iter-3: `--workspace` is a HARD ERROR,
    # not a deprecation alias. The flag prints both candidate
    # replacements and exits 2 immediately. Routed through emit_error
    # so JSON mode produces zero stdout bytes and one parseable error
    # object on stderr (U32).
    if workspace_deprecated:
        emit_error(
            "the --workspace flag was removed. "
            "Use --no-restart for canonical+overlay-no-restart, "
            "or --workspace-only for overlay-only.",
            exit_code=2,
        )
        return

    # Issue #760 §1.3 mutex rejection: --workspace-only --diff is
    # ambiguous (workspace-only pushes a fresh overlay; diff is
    # rendered-vs-host for the canonical pipeline). Reject explicitly
    # (I7).
    if workspace_only and diff:
        emit_error(
            "--workspace-only and --diff are mutually exclusive. "
            "Use --workspace-only --dry-run for a non-mutating overlay "
            "preview.",
            exit_code=2,
        )
        return

    # ATX iter-1 B1: `--workspace-only` already implies skip-restart;
    # passing `--no-restart` alongside is ambiguous (no-restart preserves
    # the canonical render phase, workspace-only skips it). Reject
    # explicitly rather than silently collapse to workspace-only.
    if workspace_only and no_restart:
        emit_error(
            "--workspace-only and --no-restart are mutually exclusive. "
            "--workspace-only already skips restart and verify; use it "
            "alone for overlay-only behavior, or use --no-restart for "
            "canonical+overlay-no-restart.",
            exit_code=2,
        )
        return

    # Phase 1 of #760 gated `--workspace-only` / `--no-restart` away
    # from zeroclaw because the bearer-rotation invariant was not yet
    # wired into either path. Phase 2 (#768) now invokes
    # `_zeroclaw_repair_after_start` unconditionally in
    # `lifecycle_canonical.sync_agent_canonical` for both flags, so the
    # gate is dropped. The resolver call below is retained because
    # downstream code (NDJSON emit, agent_key lookup) still relies on
    # it, and ATX iter-3 W6 (hoisted above the old gate) keeps the
    # single-lookup contract intact.
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
    # underlying call runs — if the canonical pipeline fails, terminals
    # would show "complete" lines followed by an error. Pre-emit as
    # `queued` so NDJSON consumers can distinguish from the post-call
    # `complete` summary. Bundle 5 will refactor `sync_agent_canonical`
    # to emit per-phase events directly, removing pre-emission.
    phase_keys = ("validate", "push", "restart", "verify")
    for key, label in zip(phase_keys, _PHASES):
        if key == "validate" and skip_validate:
            continue
        if key == "restart" and (no_restart or workspace_only):
            continue
        if key in ("validate", "push") and workspace_only:
            # `--workspace-only` short-circuits before canonical render.
            continue
        if key == "verify" and (no_restart or workspace_only):
            continue
        # ATX iter-1 W3: in dry-run mode every phase short-circuits
        # before the canonical pipeline runs (the early return at the
        # dry_run branch below). Emit `skipped (dry-run)` for ALL phases —
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
        AgentInstallMissingError,
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
            return
        # AGENTS.md §"Gateway Token Lifecycle (zeroclaw)" requires a
        # yellow notice on `configure` / `sync` / `restart` whenever the
        # zeroclaw bearer rotates. The legacy path emits this via
        # `_print_configure_warnings` in `cli/agent.py:122-152`; mirror
        # that here for the canonical sync path so remote chat sessions
        # learn they must reconnect.
        if stage == "gateway_token_rotated":
            import json as _json

            from rich.console import Console
            from rich.markup import escape as rich_escape

            from clawrium.cli.output._sanitize import sanitize

            console = Console()

            agent_label: str | None = None
            try:
                payload = _json.loads(message)
                if isinstance(payload, dict):
                    raw_key = payload.get("agent_key")
                    if isinstance(raw_key, str) and raw_key:
                        agent_label = raw_key
            except (_json.JSONDecodeError, TypeError):
                pass
            if agent_label:
                # `agent_label` originates from JSON-parsed daemon output;
                # iter-2 cli-ux W1 + W2: route through `sanitize` (strict —
                # strips bidi + zero-width + C0/C1 controls + ANSI escapes;
                # agent_key is a single-line token with no legitimate
                # whitespace to preserve) BEFORE `rich_escape` (markup-only).
                # Closes the same vector W3 patched in the
                # `gateway_auth_stale` handler below.
                console.print(
                    f"  [yellow]Gateway token rotated for "
                    f"{rich_escape(sanitize(agent_label))}. "
                    f"Active chat sessions on other machines will need to "
                    f"reconnect.[/yellow]"
                )
            else:
                console.print(
                    "  [yellow]Gateway token rotated. Active chat sessions "
                    "on other machines will need to reconnect.[/yellow]"
                )
            return
        if stage == "gateway_auth_stale":
            # Issue #760 Phase 2 (#768) W11 iter-3 stale-bearer banner.
            # `lifecycle_canonical.sync_agent_canonical` emits this
            # event right before raising when zeroclaw's re-pair fails:
            # the daemon will enforce a bearer the on-disk
            # `hosts.json.gateway.auth` no longer matches. The error
            # itself surfaces via the CanonicalSyncError path; this
            # banner gives the operator a head-start on the diagnosis
            # before that error lands. The `detail` field is the raw
            # `repair_err` string from the pair playbook — operator
            # debuggability hint per recommendation in iter-1
            # lifecycle-core review (we surface it explicitly so the
            # operator doesn't have to scrape NDJSON).
            import json as _json
            import sys as _sys

            from rich.console import Console
            from rich.markup import escape as rich_escape

            from clawrium.cli.output._sanitize import sanitize

            stderr_console = Console(stderr=True)

            agent_label = None
            detail_text = ""
            try:
                payload = _json.loads(message)
                if isinstance(payload, dict):
                    raw_key = payload.get("agent_key")
                    if isinstance(raw_key, str) and raw_key:
                        agent_label = raw_key
                    raw_detail = payload.get("detail")
                    if isinstance(raw_detail, str):
                        detail_text = raw_detail
            except (_json.JSONDecodeError, TypeError):
                pass

            # iter-1 cli-ux W3 + iter-2 cli-ux W2: both `agent_label`
            # (operator-chosen agent name) and `detail_text` (raw
            # `repair_err` from the pair playbook / ansible-runner) are
            # operator-controlled, single-line tokens. `sanitize` is
            # the strict primitive — strips bidi + zero-width + C0/C1
            # controls + ANSI escape sequences. Use it (not
            # `sanitize_passthrough`, which only strips bidi) so a
            # hostile `\x1b[2J` or U+202E in the daemon's 401 echo
            # can't manipulate the terminal. `rich_escape` second to
            # block Rich's `[...]` markup metacharacters.
            if agent_label:
                label_text = sanitize(agent_label)
                label = rich_escape(label_text)
                # iter-2 cli-ux S1: the recovery hint embeds the agent
                # name in a `clawctl agent restart <name>` snippet. With
                # a valid label the snippet is copy-pasteable; on the
                # malformed-payload fallback we drop the name parameter
                # entirely so the operator does not paste an
                # unrunnable two-positional command.
                restart_cmd = f"clawctl agent restart {label}"
                doctor_cmd = f"clawctl agent doctor {label}"
            else:
                label = "zeroclaw agent"
                restart_cmd = "clawctl agent restart <agent-name>"
                doctor_cmd = "clawctl agent doctor <agent-name>"
            stderr_console.print(
                f"  [yellow]WARN: Gateway bearer for {label} is now stale "
                f"on disk: the daemon is running but "
                f"`hosts.json.gateway.auth` may not match the bearer it "
                f"will enforce. Run `{restart_cmd}` first; if that "
                f"fails, `{doctor_cmd}` for diagnosis.[/yellow]"
            )
            if detail_text:
                stderr_console.print(
                    f"    [dim]repair detail: "
                    f"{rich_escape(sanitize(detail_text))}"
                    f"[/dim]"
                )
            _sys.stderr.flush()
            return
        stream_action(resource=resource, message=f"{stage}: {message}")

    try:
        canonical_result = sync_agent_canonical(
            on_host_name,
            force=False,
            restart=not (no_restart or workspace_only),
            verify=not (no_restart or workspace_only),
            push_workspace=True,
            workspace_only=workspace_only,
            dry_run=dry_run,
            on_event=canonical_event,
        )
    except SecretRemovalRefused as exc:
        emit_error(str(exc))
        return
    except AgentInstallMissingError as exc:
        # #811: dedicated branch so the message reads cleanly. The
        # exception body already starts with "refusing to sync…";
        # routing it through the generic `sync failed: {exc}`
        # handler below would double-frame it as
        # "sync failed: refusing to sync…" (iter-5 W2).
        emit_error(str(exc))
        return
    except (AgentConfigError, CanonicalSyncError, RemoteReadError) as exc:
        # Issue #760 S-cli-ux: workspace-phase failures from
        # `sync_agent_canonical` come up as CanonicalSyncError with a
        # "workspace overlay push failed" prefix. The exception flow
        # is unchanged — `emit_error` already calls `sys.exit(1)` /
        # raises `typer.Exit(code=1)` internally — but the integration
        # test pins this contract so a future refactor cannot silently
        # downgrade workspace failures to a non-zero-but-non-1 code.
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
