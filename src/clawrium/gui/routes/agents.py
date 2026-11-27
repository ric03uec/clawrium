"""Agent-specific API routes.

Narrow surface after #1071:

- `GET /api/agents/{agent_key}/logs` — fetch recent journalctl entries
  for a daemon agent over SSH.
- `_resolve_openclaw_credentials(instance_key, gateway)` — resolver
  used by `gui/routes/fleet.py` to surface the openclaw gateway
  bearer token on demand (openclaw dashboard WebSocket auth). The
  secrets-store seam is kept here so fleet.py does not have to
  depend on both routes files.

The previously-hosted `/chat*`, `/chat/info`, `/memory`,
`/memory/{file}`, and `/exec` endpoints were removed with the
underlying `core/chat*.py`, `core/memory.py`, and `core/agent_exec.py`
modules in #1071 phase 3a. Operators SSH to the agent host for
interactive sessions; `clawctl agent shell <name> -- <cmd>` still
wraps a one-shot command.
"""

import asyncio
import json
import logging
import re
import shlex

from fastapi import APIRouter, HTTPException, Query

from clawrium.core.keys import get_host_private_key
from clawrium.core.secrets import get_instance_secrets, set_instance_secret
from clawrium.gui.routes._common import resolve_agent as _resolve_agent


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])


_AGENT_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,252}$")
# Generic message returned to callers; full diagnostics go to the
# logger only so SSH key paths, remote stderr, etc. never leak into
# the HTTP body.
_LOGS_FETCH_GENERIC_ERROR = "Log fetch failed on remote host"

# Openclaw gateway credentials live under these fixed per-instance
# secret keys. Pre-#816 installs may still carry them inline under
# `gateway.auth` / `gateway.device.privateKey` in hosts.json; the
# resolver below migrates those into the secrets store on first read.
_OPENCLAW_AUTH_SECRET = "OPENCLAW_GATEWAY_AUTH"
_OPENCLAW_PRIVKEY_SECRET = "OPENCLAW_DEVICE_PRIVATE_KEY"


class _LogsFetchError(Exception):
    """SSH / journalctl failure — caller logs full detail, HTTP body is generic."""


@router.get("/{agent_key}/logs")
async def get_agent_logs(
    agent_key: str,
    lines: int = Query(100, ge=1, le=5000),
):
    """Fetch recent logs for an agent via journalctl over SSH."""
    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    host_record, agent_type, agent_record = resolved
    agent_name = agent_record.get("agent_name") or agent_key
    hostname = host_record.get("hostname", "")

    try:
        log_lines = await asyncio.to_thread(
            _fetch_logs_via_ssh, hostname, agent_type, agent_name, lines
        )
    except _LogsFetchError:
        # _fetch_logs_via_ssh always logs full detail before raising.
        raise HTTPException(status_code=503, detail=_LOGS_FETCH_GENERIC_ERROR)
    # Any other exception escapes as the default FastAPI 500 — a programmer
    # bug (KeyError/TypeError/...) shouldn't masquerade as "service unavailable".

    return {"logs": log_lines}


def _build_journalctl_ssh_cmd(
    hostname: str, service_name: str, lines: int, *, user_scope: bool
) -> list[str]:
    if not _HOSTNAME_RE.match(hostname or ""):
        raise _LogsFetchError(_LOGS_FETCH_GENERIC_ERROR)

    flag = "--user" if user_scope else ""
    remote = (
        f"journalctl {flag} -u {shlex.quote(service_name)} "
        f"-n {int(lines)} --no-pager -o json"
    )
    cmd: list[str] = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=5",
    ]
    key_path = get_host_private_key(hostname)
    if key_path is not None:
        cmd += ["-i", str(key_path)]
    # The `--` separator stops SSH from interpreting a future hostname like
    # `-oProxyCommand=...` as an option, even if validation regresses.
    cmd += ["--", hostname, remote]
    return cmd


def _fetch_logs_via_ssh(
    hostname: str, agent_type: str, agent_name: str, lines: int
) -> list[dict]:
    """Fetch agent logs via SSH (journalctl for systemd units)."""
    import subprocess

    if not _AGENT_TOKEN_RE.match(agent_type or ""):
        logger.warning("Rejected agent_type=%r for log fetch", agent_type)
        raise _LogsFetchError(_LOGS_FETCH_GENERIC_ERROR)
    if not _AGENT_TOKEN_RE.match(agent_name or ""):
        logger.warning("Rejected agent_name=%r for log fetch", agent_name)
        raise _LogsFetchError(_LOGS_FETCH_GENERIC_ERROR)

    service_name = f"{agent_type}-{agent_name}"

    try:
        result = subprocess.run(
            _build_journalctl_ssh_cmd(hostname, service_name, lines, user_scope=True),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            fallback = subprocess.run(
                _build_journalctl_ssh_cmd(
                    hostname, service_name, lines, user_scope=False
                ),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if fallback.returncode != 0:
                logger.warning(
                    "journalctl failed for %s on %s (rc=%d): %s",
                    service_name,
                    hostname,
                    fallback.returncode,
                    (fallback.stderr or "").strip(),
                )
                raise _LogsFetchError(_LOGS_FETCH_GENERIC_ERROR)
            result = fallback
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("SSH log fetch errored for %s: %s", hostname, e)
        raise _LogsFetchError(_LOGS_FETCH_GENERIC_ERROR)

    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            entries.append(
                {
                    "timestamp": entry.get("__REALTIME_TIMESTAMP", ""),
                    "message": entry.get("MESSAGE", ""),
                    "priority": entry.get("PRIORITY", "6"),
                }
            )
        except json.JSONDecodeError:
            entries.append(
                {
                    "timestamp": "",
                    "message": line,
                    "priority": "6",
                }
            )

    return entries


def _resolve_openclaw_credentials(
    instance_key: str, gateway: dict
) -> tuple[str | None, str | None]:
    """Read openclaw gateway credentials from the secrets store.

    Falls back to the legacy hosts.json `gateway.auth` and
    `gateway.device.privateKey` values for pre-migration installs,
    copies them into the secrets store on first use, and logs a
    warning so operators notice. Returns ``(auth, private_key)``;
    either may be ``None`` if neither source has the value.

    Consumed by `gui/routes/fleet.py` to surface the gateway bearer
    on the **Show Connection Token** button and to authenticate the
    openclaw dashboard WebSocket handshake.

    **Trust model (pre-#1071, documented in AGENTS.md).** This
    helper is a pure secrets read. The *endpoint* that returns the
    bearer to a browser lives at
    `POST /api/fleet/agents/<name>/connection-token` in
    `gui/routes/fleet.py`; its auth boundary is the GUI server's
    loopback bind + the operator's SSH access to the host (per
    AGENTS.md: "anyone who can hit this URL can already read
    `hosts.json` directly on disk"). ATX phase-3a round B1 flagged
    this as a design concern — hardening the endpoint with
    per-operator sessions, CSRF, and scoped short-lived credentials
    is tracked as a follow-up and is intentionally out of #1071
    scope (removal / strip milestone).

    **Known residue (ATX phase-3a round W2).** The legacy fallback
    branches below copy `gateway.auth` / `gateway.device.privateKey`
    into the secrets store but leave the plaintext copies in
    `hosts.json`. Tightening to delete-after-migrate requires an
    atomic hosts.json mutation path and is deferred alongside B1
    into the same follow-up. This matches the pre-#1071 behaviour
    (#816 migration semantics) and is not a regression introduced
    by phase 3a.
    """
    secrets = get_instance_secrets(instance_key)

    auth_entry = secrets.get(_OPENCLAW_AUTH_SECRET)
    auth = auth_entry.get("value") if auth_entry else None

    pk_entry = secrets.get(_OPENCLAW_PRIVKEY_SECRET)
    private_key = pk_entry.get("value") if pk_entry else None

    legacy_auth = gateway.get("auth")
    legacy_pk = (gateway.get("device") or {}).get("privateKey")

    if not auth and legacy_auth:
        logger.warning(
            "Migrating %s from hosts.json into secrets store for %s",
            _OPENCLAW_AUTH_SECRET,
            instance_key,
        )
        set_instance_secret(
            instance_key,
            _OPENCLAW_AUTH_SECRET,
            legacy_auth,
            description="Auto-migrated from hosts.json",
        )
        auth = legacy_auth

    if not private_key and legacy_pk:
        logger.warning(
            "Migrating %s from hosts.json into secrets store for %s",
            _OPENCLAW_PRIVKEY_SECRET,
            instance_key,
        )
        set_instance_secret(
            instance_key,
            _OPENCLAW_PRIVKEY_SECRET,
            legacy_pk,
            description="Auto-migrated from hosts.json",
        )
        private_key = legacy_pk

    return auth, private_key
