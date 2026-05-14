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

    instance_key = get_instance_key(hostname, agent_type, agent_name)
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
    instance_key = get_instance_key(hostname, agent_type, agent_name)
    auth, private_key = _resolve_openclaw_credentials(instance_key, gateway)

    if not auth:
        raise HTTPException(
            status_code=500, detail="Gateway auth not found in secrets"
        )

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
