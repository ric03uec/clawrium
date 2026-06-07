"""Agent-specific API routes for memory, chat, and logs.

Supplements fleet.py (which handles fleet overview + lifecycle). These
endpoints power the Agent Detail page's tabs: Configuration is served
from the existing fleet detail endpoint, Chat via a streaming proxy,
Memory via Ansible-dispatched file operations, and Logs via journal reads.
"""

import asyncio
import json
import logging
import re
import shlex

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from clawrium.core.keys import get_host_private_key
from clawrium.gui.routes._common import resolve_agent as _resolve_agent
from clawrium.core.memory import (
    MemoryOpError,
    claw_supports_memory,
    get_memory_info,
    read_memory_file,
    write_memory_file,
)
from clawrium.core.registry import (
    ManifestNotFoundError,
    ManifestParseError,
    load_manifest,
)
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
    set_instance_secret,
)
from clawrium.core.skills import (
    SOURCES,
    ClawNotSupported,
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingSourcePrefix,
    SchemaValidationError,
    SkillError,
    SkillNotFound,
    check_claw_supported,
    list_skills,
    load_skill,
    parse_skill_ref,
)
from clawrium.core.skills_apply import (
    AgentNotFoundError,
    SkillApplyError,
    SkillApplyNotSupported,
    apply_state,
)
from clawrium.core.skills_state import (
    add_skill,
    read_state,
    remove_skill,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])


# --- Memory endpoints ---


@router.get("/{agent_key}/memory")
async def list_memory_files(agent_key: str):
    """List memory files for an agent."""
    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    host_record, agent_type, agent_record = resolved
    agent_name = agent_record.get("agent_name") or agent_key

    if not claw_supports_memory(agent_type):
        return {"supported": False, "files": [], "workspace_path": ""}

    hostname = host_record.get("hostname", "")
    info = await asyncio.to_thread(get_memory_info, hostname, agent_name)
    if info is None:
        return {
            "supported": True,
            "files": [],
            "workspace_path": "",
            "error": "unreachable",
        }

    return {
        "supported": True,
        "workspace_path": info["workspace_path"],
        "files": info["files"],
    }


@router.get("/{agent_key}/memory/{filename:path}")
async def get_memory_file(agent_key: str, filename: str):
    """Read a memory file's content."""
    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    host_record, agent_type, agent_record = resolved
    agent_name = agent_record.get("agent_name") or agent_key
    hostname = host_record.get("hostname", "")

    try:
        content = await asyncio.to_thread(
            read_memory_file, hostname, agent_name, filename
        )
    except MemoryOpError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if content is None:
        raise HTTPException(
            status_code=404, detail=f"File '{filename}' not found or unreachable"
        )

    return {"filename": filename, "content": content}


class MemoryWriteRequest(BaseModel):
    content: str


@router.put("/{agent_key}/memory/{filename:path}")
async def update_memory_file(agent_key: str, filename: str, body: MemoryWriteRequest):
    """Write content to a memory file."""
    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    host_record, agent_type, agent_record = resolved
    agent_name = agent_record.get("agent_name") or agent_key
    hostname = host_record.get("hostname", "")

    try:
        success, error = await asyncio.to_thread(
            write_memory_file, hostname, agent_name, filename, body.content
        )
    except MemoryOpError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(status_code=500, detail=error or "Write failed")

    return {"success": True, "filename": filename}


# --- Chat endpoint (streaming proxy) ---


class ChatRequest(BaseModel):
    message: str
    session: str = "main"


@router.post("/{agent_key}/chat")
async def chat_send(agent_key: str, body: ChatRequest):
    """Send a chat message and stream the response via SSE.

    Proxies to the agent's chat backend (OpenAI HTTP or WebSocket).
    Returns a streaming response with Server-Sent Events.
    """
    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    host_record, agent_type, agent_record = resolved

    # Determine chat type from manifest
    try:
        manifest = await asyncio.to_thread(load_manifest, agent_type)
    except (ManifestNotFoundError, ManifestParseError):
        raise HTTPException(
            status_code=400, detail=f"Cannot load manifest for '{agent_type}'"
        )

    features = manifest.get("features") or {}
    chat_config = features.get("chat") if isinstance(features, dict) else None
    if not isinstance(chat_config, dict):
        raise HTTPException(
            status_code=400, detail=f"Chat not supported for '{agent_type}'"
        )

    chat_type = chat_config.get("type")

    if chat_type == "openai":
        return await _chat_hermes(
            host_record, agent_type, agent_record, agent_key, body
        )
    elif chat_type == "websocket":
        return await _chat_openclaw(host_record, agent_type, agent_record, body)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown chat type: {chat_type}")


@router.get("/{agent_key}/chat/info")
async def chat_info(agent_key: str):
    """Get chat capability info for an agent."""
    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    _, agent_type, _ = resolved

    try:
        manifest = await asyncio.to_thread(load_manifest, agent_type)
    except (ManifestNotFoundError, ManifestParseError):
        return {"supported": False, "type": None}

    features = manifest.get("features") or {}
    chat_config = features.get("chat") if isinstance(features, dict) else None
    if not isinstance(chat_config, dict):
        return {"supported": False, "type": None}

    return {"supported": True, "type": chat_config.get("type")}


# --- Logs endpoint ---


@router.get("/{agent_key}/logs")
async def get_agent_logs(
    agent_key: str,
    lines: int = Query(100, ge=1, le=5000),
):
    """Fetch recent logs for an agent via journalctl over SSH.

    Returns structured log entries. Falls back to empty if unreachable.
    """
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


# --- Skills endpoints ---


def _skill_error_status(error: SkillError) -> int:
    """Map a ``SkillError`` subclass to an HTTP status code.

    ``SkillApplyError`` is the only "remote failed" class; everything else
    is a client-side input or catalog problem and maps to 422/404. ATX
    review wanted explicit failure isolation: a broken playbook run
    surfaces as 502 (upstream/host failed) so the GUI doesn't mistake
    "your input is bad" for "the host is down".
    """
    if isinstance(error, AgentNotFoundError):
        return 404
    if isinstance(error, SkillNotFound):
        return 404
    if isinstance(error, SkillApplyError):
        return 502
    if isinstance(error, SkillApplyNotSupported):
        return 422
    if isinstance(
        error,
        (
            MissingSourcePrefix,
            ExternalSourceBlocked,
            InvalidSkillRef,
            ClawNotSupported,
            SchemaValidationError,
        ),
    ):
        return 422
    # Defensive: a future SkillError subclass surfaces as 500 with a
    # bounded message so it isn't silently treated as a client error.
    return 500


# SkillApplyError messages from core.skills_apply embed absolute paths
# (log_dir, playbook_path) and remote stderr — useful for the CLI's local
# error surface but not safe to ship in an HTTP body that a browser or
# upstream proxy may cache/log. ATX-1 B1: replace the detail string with
# a generic message for SkillApplyError; the full text is logged for
# operator debugging only.
_SKILL_APPLY_GENERIC_DETAIL = (
    "Skills apply failed on host. Check server logs for details."
)


def _skill_error_detail(error: SkillError) -> str:
    """Detail string to ship in the HTTPException body.

    All ``SkillError`` subclasses except ``SkillApplyError`` are
    user-actionable input/catalog problems — the message itself is the
    fix hint, so we surface it verbatim. ``SkillApplyError`` is the only
    class that can carry filesystem paths or remote stderr; that one is
    redacted to a fixed string and the original message goes to the
    server log.
    """
    if isinstance(error, SkillApplyError):
        logger.warning("skills apply failed: %s", error)
        return _SKILL_APPLY_GENERIC_DETAIL
    return str(error)


def _is_compatible_for_agent_type(reg: str, name: str, agent_type: str) -> bool:
    """Decide if a catalog skill is installable on a given claw type.

    ATX-1 W2: delegate to ``check_agent_compatibility`` instead of
    reimplementing the rule. Any future tweak to the compatibility
    semantics (e.g. how missing keys are treated) now applies to both
    the CLI and GUI from one place.

    Short-circuits (no I/O) for two cases that cannot ever be
    compatible:
      - Unknown source registry → false.
      - Native registry whose name doesn't match the claw → false (a
        native skill can never run on another claw).

    Everything else — `clawrium/*` and `<claw>/*` matching the claw —
    falls through to ``load_skill`` + ``check_agent_compatibility``.
    The picker scan is therefore O(n) ``load_skill`` calls bounded by
    the catalog size for compatible registries; a follow-up could
    cache loaded skills per request if catalogs grow large (ATX-2 W4
    flagged the cost but the present picker scans <10 skills, so the
    cache is deferred).

    Loader failures swallow to false so a single bad catalog row
    cannot widen the install picker on the user's screen.
    """
    if reg not in SOURCES:
        return False
    try:
        check_claw_supported(agent_type)
        load_skill(parse_skill_ref(f"{reg}/{name}"))
    except SkillError:
        return False
    return True


def _list_available_for_agent_type(agent_type: str) -> list[dict[str, object]]:
    """Return catalog skills installable on ``agent_type``, summarized.

    Used to populate the install picker on the agent-detail Skills tab.
    """
    try:
        refs = list_skills()
    except SkillError as error:
        logger.warning("skills catalog unavailable: %s", error)
        return []
    available: list[dict[str, object]] = []
    for ref in refs:
        if not _is_compatible_for_agent_type(ref.source, ref.name, agent_type):
            continue
        description: str | None = None
        version: str | None = None
        try:
            skill = load_skill(ref)
        except SkillError:
            # Bad catalog row — surface the ref so the user still sees
            # something in the picker, but null out the optional fields.
            pass
        else:
            raw_desc = skill.metadata.get("description")
            if isinstance(raw_desc, str) and raw_desc.strip():
                description = " ".join(raw_desc.split())
            raw_ver = skill.metadata.get("version")
            if raw_ver is not None:
                version = str(raw_ver)
        available.append(
            {
                "ref": str(ref),
                "source": ref.source,
                "name": ref.name,
                "description": description,
                "version": version,
            }
        )
    return available


@router.get("/{agent_key}/skills")
async def list_agent_skills(agent_key: str):
    """List installed skills + available-to-install skills for an agent.

    Returns:

    ```
    {
      "agent_name": "tdd-hermes",
      "agent_type": "hermes",
      "installed": [{"ref": "clawrium/tdd", ...}, ...],
      "available": [{"ref": "clawrium/tdd", ...}, ...]
    }
    ```

    ``installed`` is the local desired-state file's view — the same view
    ``clawctl agent skill get`` shows. The agent-detail Skills tab merges
    these in the UI, so the response keeps them separate to keep the
    payload close to the underlying data.
    """
    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    _host_record, agent_type, agent_record = resolved
    agent_name = agent_record.get("agent_name") or agent_key

    def _build() -> dict[str, object]:
        try:
            installed_refs = read_state(agent_name)
        except SkillError as error:
            logger.warning("skills state unreadable for %s: %s", agent_name, error)
            installed_refs = []
        installed: list[dict[str, object]] = []
        for raw_ref in installed_refs:
            try:
                ref = parse_skill_ref(raw_ref)
            except SkillError:
                # State file has an entry that no longer validates — show
                # the bare ref so the user can remove it.
                installed.append(
                    {
                        "ref": raw_ref,
                        "source": None,
                        "name": None,
                        "description": None,
                        "version": None,
                    }
                )
                continue
            description: str | None = None
            version: str | None = None
            try:
                skill = load_skill(ref)
            except SkillError:
                pass
            else:
                raw_desc = skill.metadata.get("description")
                if isinstance(raw_desc, str) and raw_desc.strip():
                    description = " ".join(raw_desc.split())
                raw_ver = skill.metadata.get("version")
                if raw_ver is not None:
                    version = str(raw_ver)
            installed.append(
                {
                    "ref": str(ref),
                    "source": ref.source,
                    "name": ref.name,
                    "description": description,
                    "version": version,
                }
            )
        available = _list_available_for_agent_type(agent_type)
        return {
            "agent_name": agent_name,
            "agent_type": agent_type,
            "installed": installed,
            "available": available,
        }

    return await asyncio.to_thread(_build)


def _install_or_remove(
    agent_key: str,
    registry: str,
    skill: str,
    *,
    action: str,
) -> dict[str, object]:
    """Shared body for POST/DELETE; runs synchronously inside a thread.

    Resolves the agent, mutates desired state, then unconditionally calls
    ``apply_state`` — same drift-recovery contract the CLI uses. Returns
    a payload with the post-apply installed skills so the frontend can
    update its cache without an extra round-trip.
    """
    resolved = _resolve_agent(agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    _host_record, _agent_type, agent_record = resolved
    agent_name = agent_record.get("agent_name") or agent_key

    raw_ref = f"{registry}/{skill}"
    try:
        # add_skill / remove_skill both call parse_skill_ref as their
        # first operation, so a malformed ref short-circuits with 422
        # before any state mutation. (W4: dropped the redundant pre-call
        # that ATX flagged as dead code.)
        if action == "install":
            _new_state, changed = add_skill(agent_name, raw_ref)
        else:
            _new_state, changed = remove_skill(agent_name, raw_ref)
        result = apply_state(agent_name)
    except SkillError as error:
        raise HTTPException(
            status_code=_skill_error_status(error),
            detail=_skill_error_detail(error),
        ) from error

    return {
        "success": True,
        "agent_name": agent_name,
        "ref": raw_ref,
        "changed": changed,
        "installed": list(result.applied_skills),
    }


@router.post("/{agent_key}/skills/{registry}/{skill}")
async def install_agent_skill(agent_key: str, registry: str, skill: str):
    """Install ``<registry>/<skill>`` on ``agent_key``.

    Idempotent: re-installing an already-installed skill is a no-op
    state mutation, but the apply playbook still runs to reconcile any
    on-host drift (matches the CLI semantics).
    """
    return await asyncio.to_thread(
        _install_or_remove, agent_key, registry, skill, action="install"
    )


@router.delete("/{agent_key}/skills/{registry}/{skill}")
async def remove_agent_skill(agent_key: str, registry: str, skill: str):
    """Remove ``<registry>/<skill>`` from ``agent_key``.

    Idempotent: removing a skill that wasn't in desired state still
    runs the apply playbook so any orphan on-host directory is pruned
    (matches the CLI semantics).
    """
    return await asyncio.to_thread(
        _install_or_remove, agent_key, registry, skill, action="remove"
    )


# --- Internal helpers ---


async def _chat_hermes(
    host_record: dict,
    agent_type: str,
    agent_record: dict,
    agent_key: str,
    body: ChatRequest,
):
    """Proxy chat to hermes via OpenAI-compatible HTTP with SSE streaming."""
    from clawrium.core.chat import SecretStr
    from clawrium.core.chat_hermes import HermesOpenAIBackend

    config = agent_record.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="Agent config missing")

    api_server = config.get("api_server")
    if not isinstance(api_server, dict):
        raise HTTPException(status_code=500, detail="api_server config missing")

    port = api_server.get("port")
    hostname = host_record.get("hostname", "")
    agent_name = agent_record.get("agent_name") or agent_key

    host_key = host_record.get("key_id") or hostname
    instance_key = get_instance_key(host_key, agent_type, agent_name)
    secret_entry = get_instance_secrets(instance_key).get("HERMES_API_SERVER_KEY")
    raw_token = secret_entry.get("value") if secret_entry else None

    if not raw_token:
        raise HTTPException(status_code=500, detail="API key not found in secrets")

    base_url = f"http://{hostname}:{port}/v1"
    backend = HermesOpenAIBackend(
        base_url=base_url,
        auth_token=SecretStr(raw_token),
        timeout_seconds=120.0,
    )

    async def generate():
        try:
            await backend.connect()
            chunks: list[str] = []

            def on_delta(delta: str) -> None:
                chunks.append(delta)

            response_text = await backend.send_message(
                message=body.message,
                session_key=body.session,
                on_delta=on_delta,
            )

            # Send the complete response as SSE
            yield f"data: {json.dumps({'type': 'content', 'text': response_text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception:
            logger.exception("Chat proxy failed")
            yield (
                "data: "
                + json.dumps({"type": "error", "message": _CHAT_GENERIC_ERROR})
                + "\n\n"
            )
        finally:
            await backend.close()

    return StreamingResponse(generate(), media_type="text/event-stream")


_OPENCLAW_AUTH_SECRET = "OPENCLAW_GATEWAY_AUTH"
_OPENCLAW_PRIVKEY_SECRET = "OPENCLAW_DEVICE_PRIVATE_KEY"


def _resolve_openclaw_credentials(
    instance_key: str, gateway: dict
) -> tuple[str | None, str | None]:
    """Read openclaw chat credentials from the secrets store.

    Falls back to the legacy hosts.json `gateway.auth` and
    `gateway.device.privateKey` values for pre-migration installs, copies them
    into the secrets store on first use, and logs a warning so operators
    notice. Returns (auth, private_key); either may be None if neither source
    has the value.
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
            description="Auto-migrated from hosts.json (B5)",
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
            description="Auto-migrated from hosts.json (B5)",
        )
        private_key = legacy_pk

    return auth, private_key


async def _chat_openclaw(
    host_record: dict, agent_type: str, agent_record: dict, body: ChatRequest
):
    """Proxy chat to openclaw via WebSocket.

    Auth and device private key resolve through the encrypted secrets store
    (parallel to the hermes path). Existing installs that still carry the
    values in `hosts.json` are auto-migrated on first use — see
    `_resolve_openclaw_credentials` for details.
    """
    from clawrium.core.chat import OpenClawChatClient, SecretStr

    config = agent_record.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="Agent config missing")

    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        raise HTTPException(status_code=500, detail="Gateway config missing")

    url = gateway.get("url")
    if not url:
        raise HTTPException(status_code=500, detail="Gateway URL missing")

    hostname = host_record.get("hostname", "")
    agent_name = agent_record.get("agent_name") or agent_record.get("name") or ""
    host_key = host_record.get("key_id") or hostname
    instance_key = get_instance_key(host_key, agent_type, agent_name)
    auth, private_key = _resolve_openclaw_credentials(instance_key, gateway)

    if not auth:
        raise HTTPException(status_code=500, detail="Gateway auth not found in secrets")

    device = gateway.get("device") or {}
    backend = OpenClawChatClient(
        gateway_url=url,
        auth_token=SecretStr(auth),
        device_id=device.get("id"),
        device_private_key=private_key,
        timeout_seconds=120.0,
    )

    async def generate():
        try:
            await backend.connect()
            chunks: list[str] = []

            def on_delta(delta: str) -> None:
                chunks.append(delta)

            response_text = await backend.send_message(
                message=body.message,
                session_key=body.session,
                on_delta=on_delta,
            )

            yield f"data: {json.dumps({'type': 'content', 'text': response_text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception:
            logger.exception("Chat proxy failed")
            yield (
                "data: "
                + json.dumps({"type": "error", "message": _CHAT_GENERIC_ERROR})
                + "\n\n"
            )
        finally:
            await backend.close()

    return StreamingResponse(generate(), media_type="text/event-stream")


_AGENT_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,252}$")
# Generic messages returned to callers; full diagnostics go to the logger only
# so we never leak SSH key paths, gateway URLs with auth params, or remote
# stderr through the HTTP body or SSE error frames.
_LOGS_FETCH_GENERIC_ERROR = "Log fetch failed on remote host"
_CHAT_GENERIC_ERROR = "Chat request failed"


class _LogsFetchError(Exception):
    """Surface a SSH/journalctl failure to the caller for logging."""


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


# --- Agent exec endpoint ---


class ExecRequest(BaseModel):
    """Request body for agent exec."""

    command: list[str]
    timeout: int = 30


@router.post("/{agent_key}/exec")
async def agent_exec(agent_key: str, body: ExecRequest):
    """Run a command on the agent's host via its native CLI.

    Equivalent to `clawctl agent exec <name> -- <args...>`.
    Returns stdout, stderr, and return code.
    """
    from clawrium.core.agent_exec import run_agent_exec, AgentExecError

    agent = _resolve_agent(agent_key)
    hostname = agent["host"]
    agent_name = agent["agent_name"]
    claw_type = agent["agent_type"]

    if not body.command:
        raise HTTPException(status_code=400, detail="command list must not be empty")

    timeout = max(5, min(body.timeout, 120))

    try:
        stdout, stderr, rc = await asyncio.to_thread(
            run_agent_exec, hostname, agent_name, claw_type, body.command, timeout
        )
    except AgentExecError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("agent exec failed for %s", agent_key)
        raise HTTPException(
            status_code=500, detail="exec failed — check server logs"
        ) from e

    return {
        "stdout": stdout,
        "stderr": stderr,
        "return_code": rc,
    }
