"""`clawctl agent upgrade <name>` — forward-only upgrade to manifest max.

Bumps an installed agent to the highest manifest version compatible with
its host hardware. No version pinning, no downgrade path: the manifest is
the contract. Issue #592.

Version comparison (#754): for openclaw agents the live on-host version is
probed via SSH and compared against the manifest max, NOT the
`hosts.json` snapshot. This closes the false-no-op trap in which the
snapshot says the agent is at max but the per-agent binary on the host is
actually older (manual rollback, half-completed prior upgrade, manually
edited snapshot). For non-openclaw agents the snapshot is still trusted
until parity lands.

Pre-flight (hard fail on any rejection):

1. Resolve agent + host from `hosts.json`.
2. Compute `target = latest_supported_version(agent_type, host_hardware)`.
3. **Live version probe** (openclaw): SSH into host, run `openclaw --version`.
   Compare live version against manifest max.
4. **No-op** if live (or snapshot for non-openclaw) >= target. Exit 0;
   `run_installation` not called. Snapshot is NOT auto-corrected.
5. **Drift check**: refuse if any rendered file differs from on-host state.
   `--skip-drift-check` bypasses (hidden escape hatch).
6. Confirmation prompt unless `--yes` or `-o json`.

Execute:

- `run_installation(claw_name=<type>, hostname=..., name=..., force=True)`.
  Matched-entry resolution inside it picks `target` automatically because
  the manifest's max is the new version.
- `hosts.json.agents.<name>.version` updates at the existing write site
  (`core/install.py:562`).
- The canonical lifecycle drives restart + re-pair (per AGENTS.md
  §"Gateway Token Lifecycle (zeroclaw)").
"""

from __future__ import annotations

import json

import typer
from packaging.version import InvalidVersion, Version

from clawrium.cli.clawctl._common import OutputFormat, confirm_destructive
from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action


def _parse(v: str) -> Version:
    try:
        return Version(v)
    except InvalidVersion:
        return Version("0.0.0")


_RENDERERS = {
    "hermes": "render_hermes",
    "zeroclaw": "render_zeroclaw",
    "openclaw": "render_openclaw",
}

# Agent types whose gateway requires a bearer-token re-pair on lifecycle
# operations (AGENTS.md §"Gateway Token Lifecycle (zeroclaw)"). The
# upgrade path force-reinstalls the binary, restarts the unit, and the
# daemon mints a fresh bearer — `hosts.json.gateway.auth` must be
# rewritten atomically or remote `clawctl agent chat` sessions will get
# a clean 401. ATX B2 (issue #592): drive the rotation by calling
# `lifecycle.restart_agent` after the install playbook returns; that
# helper already emits the `gateway_token_rotated` event.
_PAIRING_AGENT_TYPES = {"zeroclaw"}


def _drift_files(host: dict, agent_name: str, agent_type: str) -> list[str]:
    """Return the list of file paths that differ between rendered and host.

    Raises on render/SSH errors so the caller can surface a clean failure.
    """
    from clawrium.core import render as _render_mod
    from clawrium.core.render import build_render_inputs
    from clawrium.core.render_diff import diff_files

    renderer_name = _RENDERERS.get(agent_type)
    if renderer_name is None:
        raise RuntimeError(f"no renderer for agent type {agent_type!r}")
    renderer = getattr(_render_mod, renderer_name)

    inputs = build_render_inputs(agent_name)
    rendered = renderer(inputs)
    results = diff_files(
        host=host, agent_name=agent_name, rendered_files=rendered.files
    )
    return [d.path for d in results if d.unified_diff]


def _get_live_openclaw_version(host: dict, agent_name: str) -> str | None:
    """Probe the live openclaw version on the host via SSH.

    Returns the version string (e.g. "2026.6.8") or None if the probe
    fails (binary missing, SSH error, unparseable output).
    """
    import paramiko

    from clawrium.core.keys import get_host_private_key
    from clawrium.core.lifecycle_canonical import _get_host_openclaw_version

    key_id = host.get("key_id") or host.get("hostname") or ""
    private_key = get_host_private_key(key_id)
    if not private_key:
        return None

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    try:
        client.connect(
            hostname=host.get("hostname", ""),
            port=int(host.get("port", 22)),
            username=host.get("user", "xclm"),
            key_filename=str(private_key),
            timeout=10,
        )
        os_family = host.get("os_family", "linux")
        version_tuple, _stderr = _get_host_openclaw_version(
            client, agent_name, os_family=os_family
        )
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass

    if version_tuple is None:
        return None
    return ".".join(str(p) for p in version_tuple)


def upgrade(
    name: str = typer.Argument(..., help="Agent name."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt."
    ),
    skip_drift_check: bool = typer.Option(
        False,
        "--skip-drift-check",
        help="Bypass the drift pre-flight gate.",
        hidden=True,
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table or json)."
    ),
) -> None:
    """Upgrade an installed agent to the manifest's max supported version."""
    from clawrium.core.install import InstallationError, run_installation
    from clawrium.core.registry import latest_supported_version

    host, agent_type, claw_record = safe_resolve_agent(name)
    agent_key = resolve_agent_key(host, name)
    agent_type = claw_record.get("type", agent_type)

    installed = str(claw_record.get("version") or "")
    if not installed:
        emit_error(
            f"agent {name!r} has no installed version recorded",
            hint="clawctl agent describe " + name,
        )

    # ATX B3 (issue #592): `core/install.py:set_installing()` stamps the
    # target version into `hosts.json` BEFORE Ansible runs. A failed
    # playbook leaves `version=<new_target>` with `status="failed"`. If
    # we naively trust the version field, a retry would compare
    # installed==target and exit as a no-op, permanently trapping the
    # operator. Treat any non-installed status as "version is unreliable
    # for the no-op decision" and let `run_installation(force=True)`
    # drive the retry. The fix-forward is to call install regardless.
    install_status = str(claw_record.get("status") or "").lower()
    failed_retry = install_status == "failed"

    hardware = host.get("hardware") or {}
    target = latest_supported_version(agent_type, hardware)
    if target is None:
        emit_error(
            f"no platform entry in {agent_type!r} manifest matches host hardware",
            hint="check the host's os/os_version/arch facts",
        )

    use_json = output is OutputFormat.json
    resource = f"agent/{name}"
    hostname = host.get("hostname", "")
    on_host_name = claw_record.get("agent_name") or agent_key

    # #754: for openclaw, probe the live version on the host instead of
    # trusting the snapshot in hosts.json. This closes the false-no-op
    # trap in which snapshot says max but the per-agent binary is older.
    if agent_type == "openclaw" and not failed_retry:
        live_version_str = _get_live_openclaw_version(host, on_host_name)
        if live_version_str is not None:
            live_v = _parse(live_version_str)
            target_v = _parse(target)
            if live_v >= target_v:
                msg = f"already at latest ({live_version_str})"
                if use_json:
                    typer.echo(
                        json.dumps(
                            {
                                "agent": name,
                                "from_version": live_version_str,
                                "to_version": live_version_str,
                                "status": "no-op",
                            }
                        )
                    )
                else:
                    stream_action(resource=resource, message=msg)
                return
            # Live version is below target — proceed with upgrade.
            # Use live_version_str for the "from_version" display.
            installed = live_version_str

    installed_v = _parse(installed)
    target_v = _parse(target)

    if target_v == installed_v and not failed_retry:
        msg = f"already at latest ({installed})"
        if use_json:
            typer.echo(
                json.dumps(
                    {
                        "agent": name,
                        "from_version": installed,
                        "to_version": installed,
                        "status": "no-op",
                    }
                )
            )
        else:
            stream_action(resource=resource, message=msg)
        return

    if target_v < installed_v and not failed_retry:
        emit_error(
            f"refusing downgrade: installed {installed} > manifest max {target}",
            hint="manifest entries may have been removed; restore them or reinstall",
        )

    if not skip_drift_check:
        # Pre-init so `changed` is bound even if `emit_error` were ever
        # to become non-NoReturn (it raises typer.Exit today, but the
        # invariant should not be implicit). ATX iter-2 S1.
        changed: list[str] = []
        try:
            changed = _drift_files(host, on_host_name, agent_type)
        except Exception as exc:
            emit_error(
                f"drift check failed: {type(exc).__name__}: {exc}",
                hint="re-run with --skip-drift-check to bypass",
            )
        if changed:
            stream_action(
                resource=resource,
                message=(
                    f"drift detected ({len(changed)} file(s) differ from rendered "
                    f"state); refusing upgrade"
                ),
            )
            for path in changed:
                stream_action(resource=resource, message=f"  drift: {path}")
            emit_error(
                "host state has drifted from rendered config",
                hint="run `clawctl agent sync` first, or pass --skip-drift-check",
            )

    if not use_json:
        confirm_destructive(
            prompt=f"Upgrade {name} from {installed} to {target}?",
            yes=yes,
        )

    if failed_retry and not use_json:
        stream_action(
            resource=resource,
            message="retrying upgrade after previous failed install (status=failed)",
        )

    try:
        result = run_installation(
            claw_name=agent_type,
            hostname=hostname,
            name=on_host_name,
            force=True,
        )
    except InstallationError as exc:
        emit_error(f"upgrade failed: {exc}")
        return

    from clawrium.core.workspace_sync import push_workspace_phase

    def _emit_workspace(stage: str, payload: dict) -> None:
        if not use_json:
            stream_action(resource=resource, message=f"{stage}: {json.dumps(payload)}")

    workspace_hint = "run `clawctl agent sync` after fixing the local workspace overlay"
    if agent_type in _PAIRING_AGENT_TYPES:
        workspace_hint += (
            f"; {agent_type} bearer state may also be stale until you run "
            "`clawctl agent sync` or `clawctl agent restart`"
        )

    try:
        ws_result = push_workspace_phase(
            host=host,
            agent_type=agent_type,
            agent_name=on_host_name,
            on_event=_emit_workspace if not use_json else None,
        )
    except Exception as exc:
        emit_error(
            f"upgrade installed but workspace restore crashed: {exc}",
            hint=workspace_hint,
        )
    workspace_error = (
        (ws_result.error or "unknown workspace error")
        if not ws_result.success
        else None
    )
    if workspace_error:
        emit_error(
            f"upgrade installed but workspace restore failed: {workspace_error}",
            hint=workspace_hint,
        )

    # ATX B2 (issue #592): zeroclaw's install playbook does NOT pair
    # (see `core/install.py:1069`); the bearer token lives in the
    # configure path. After a forced reinstall the daemon mints a new
    # bearer and `hosts.json.gateway.auth` falls out of sync. Route
    # through `lifecycle.restart_agent`, which rotates the bearer and
    # emits a `gateway_token_rotated` event per AGENTS.md §"Gateway
    # Token Lifecycle".
    if agent_type in _PAIRING_AGENT_TYPES:
        from clawrium.core.lifecycle import LifecycleError, restart_agent

        def _emit_lifecycle(stage: str, message: str) -> None:
            if not use_json:
                stream_action(resource=resource, message=f"{stage}: {message}")

        # ATX iter-2 W1 (issue #592): `restart_agent` signals failure
        # through *both* a raised LifecycleError (host/onboarding pre-
        # flight) and a `{"success": False, "error": str}` return on
        # the stop-fail / repair-fail branches (lifecycle.py:914-926
        # and :781-795). Without checking the return dict, a failed
        # re-pair silently falls through to the "upgraded" success
        # output — exactly the silent-stale-bearer trap AGENTS.md
        # §"Gateway Token Lifecycle" calls out.
        try:
            restart_result = restart_agent(
                hostname=hostname,
                claw_name=agent_type,
                agent_name=on_host_name,
                on_event=_emit_lifecycle if not use_json else None,
            )
        except LifecycleError as exc:
            emit_error(
                f"upgrade installed but post-install restart failed: {exc}",
                hint="run `clawctl agent restart` to rotate the gateway token",
            )
        if not restart_result.get("success"):
            emit_error(
                "upgrade installed but post-install restart failed: "
                f"{restart_result.get('error') or 'unknown lifecycle error'}",
                hint="run `clawctl agent restart` to rotate the gateway token",
            )

    if use_json:
        typer.echo(
            json.dumps(
                {
                    "agent": name,
                    "from_version": installed,
                    "to_version": result.get("version") or target,
                    "status": "upgraded",
                }
            )
        )
    else:
        to_version = result.get("version") or target
        stream_action(
            resource=resource,
            message=f"upgraded {installed} → {to_version}",
        )
