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
import time
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from pydantic import BaseModel

from clawrium.core.chat_claude import ClaudeCodeChatBackend
from clawrium.core.chat_codex import CodexChatBackend
from clawrium.core.chat_pi import PiChatBackend
from clawrium.core.pi import PiProvisioningError, validate_pi_provider
from clawrium.core.providers.storage import get_provider
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

# A Claude Code process is created for every turn, but its upstream UUID has
# to survive the browser's separate POSTs. Keep one shared backend per
# browser-created conversation, never per agent alone: interleaved browser
# conversations must not reset each other's upstream history.
_CLAUDE_BROWSER_SESSION_TTL_SECONDS = 30 * 60
_CLAUDE_BROWSER_SESSION_MAX = 128
_CLAUDE_RESPONSE_TIMEOUT_SECONDS = 120.0
_CLAUDE_SESSION_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CLAUDE_MAX_PROMPT_CHARS = 100_000
# Codex uses the same finite-process and browser-session rules as Claude,
# but keeps a separate cache so a browser conversation can never cross agent
# types or native session protocols.
_CODEX_BROWSER_SESSION_TTL_SECONDS = 30 * 60
_CODEX_BROWSER_SESSION_MAX = 128
_CODEX_RESPONSE_TIMEOUT_SECONDS = 120.0
_CODEX_SESSION_KEY_RE = _CLAUDE_SESSION_KEY_RE
_CODEX_MAX_PROMPT_CHARS = 100_000
_PI_BROWSER_SESSIONS: dict[tuple[str, str], "_PiBrowserSession"] = {}
_PI_BROWSER_SESSION_GENERATION = 0


class _PiSessionCapacityError(Exception):
    """Raised when all bounded Pi browser sessions have active turns."""


@dataclass
class _ClaudeBrowserSession:
    backend: ClaudeCodeChatBackend
    lock: asyncio.Lock
    last_used: float


@dataclass
class _PiBrowserSession:
    backend: PiChatBackend
    identity: tuple[str, str, str, str, str, str, str]
    generation: int
    lock: asyncio.Lock
    last_used: float
    invalidated: bool = False


_CLAUDE_BROWSER_SESSIONS: dict[tuple[str, str], _ClaudeBrowserSession] = {}


@dataclass
class _CodexBrowserSession:
    backend: CodexChatBackend
    identity: tuple[str, str, str, str]
    generation: int
    lock: asyncio.Lock
    last_used: float
    invalidated: bool = False


_CODEX_BROWSER_SESSIONS: dict[tuple[str, str], _CodexBrowserSession] = {}
_CODEX_BROWSER_SESSION_GENERATION = 0


class _CodexSessionCapacityError(Exception):
    """Raised before streaming when every bounded browser session is active."""


def _invalidate_codex_browser_session(
    cache_key: tuple[str, str], session: _CodexBrowserSession
) -> None:
    session.invalidated = True
    if _CODEX_BROWSER_SESSIONS.get(cache_key) is session:
        _CODEX_BROWSER_SESSIONS.pop(cache_key)


def _codex_browser_session_is_current(
    cache_key: tuple[str, str], session: _CodexBrowserSession
) -> bool:
    current = _CODEX_BROWSER_SESSIONS.get(cache_key)
    return (
        not session.invalidated
        and current is session
        and current.generation == session.generation
    )


async def _codex_browser_session_matches_registry(
    agent_key: str, session: _CodexBrowserSession
) -> bool:
    """Fail closed if an in-flight turn outlives its installed agent identity."""
    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        return False
    host_record, agent_type, agent_record = resolved
    hostname = host_record.get("hostname")
    agent_name = agent_record.get("agent_name") or agent_record.get("name") or agent_key
    installed_at = agent_record.get("installed_at")
    return (
        agent_type == "codex"
        and agent_record.get("status") in (None, "installed")
        and (
            host_record.get("key_id") or hostname,
            hostname,
            agent_name,
            installed_at if isinstance(installed_at, str) else "",
        )
        == session.identity
    )


def _get_codex_browser_session(
    *,
    agent_key: str,
    session_key: str,
    hostname: str,
    host_key: str,
    agent_name: str,
    installation_id: str,
) -> _CodexBrowserSession:
    now = time.monotonic()
    cache_key = (agent_key, session_key)
    identity = (host_key, hostname, agent_name, installation_id)
    cached = _CODEX_BROWSER_SESSIONS.get(cache_key)
    # Legacy records have no immutable install marker: never resume an old
    # native thread across a possible same-key reinstall.
    if cached is not None and not installation_id:
        _invalidate_codex_browser_session(cache_key, cached)
        cached = None
    if (
        cached is not None
        and cached.identity == identity
        and (
            cached.lock.locked()
            or now - cached.last_used <= _CODEX_BROWSER_SESSION_TTL_SECONDS
        )
    ):
        cached.last_used = now
        return cached
    if cached is not None:
        _invalidate_codex_browser_session(cache_key, cached)
    for key, value in tuple(_CODEX_BROWSER_SESSIONS.items()):
        if (
            not value.lock.locked()
            and now - value.last_used > _CODEX_BROWSER_SESSION_TTL_SECONDS
        ):
            _invalidate_codex_browser_session(key, value)
    while len(_CODEX_BROWSER_SESSIONS) >= _CODEX_BROWSER_SESSION_MAX:
        evictable = [
            (value.last_used, key)
            for key, value in _CODEX_BROWSER_SESSIONS.items()
            if not value.lock.locked()
        ]
        if not evictable:
            # Do not exceed the advertised bound under concurrent requests.
            # This is raised before StreamingResponse construction, so callers
            # receive a normal bounded HTTP failure rather than a late SSE frame.
            raise _CodexSessionCapacityError
        _, oldest_key = min(evictable)
        _invalidate_codex_browser_session(
            oldest_key, _CODEX_BROWSER_SESSIONS[oldest_key]
        )
    global _CODEX_BROWSER_SESSION_GENERATION
    _CODEX_BROWSER_SESSION_GENERATION += 1
    session = _CodexBrowserSession(
        backend=CodexChatBackend(
            hostname=hostname,
            agent_name=agent_name,
            timeout_seconds=_CODEX_RESPONSE_TIMEOUT_SECONDS,
        ),
        identity=identity,
        generation=_CODEX_BROWSER_SESSION_GENERATION,
        lock=asyncio.Lock(),
        last_used=now,
    )
    _CODEX_BROWSER_SESSIONS[cache_key] = session
    return session


def _get_claude_browser_session(
    *,
    agent_key: str,
    session_key: str,
    hostname: str,
    agent_name: str,
) -> _ClaudeBrowserSession:
    """Return the bounded, in-memory backend for one browser conversation.

    The backend deliberately owns only the UUID that Claude Code needs for
    ``--resume``. Credentials stay in the remote agent-owned artifacts and
    prompts never enter this cache or its keys.
    """
    now = time.monotonic()
    cache_key = (agent_key, session_key)
    cached = _CLAUDE_BROWSER_SESSIONS.get(cache_key)
    if cached is not None:
        cached.last_used = now
        return cached

    # Idle entries have no live remote connection: every completed, failed, or
    # cancelled turn closes its backend below. Do not evict a conversation that
    # currently owns its per-session lock.
    for key, value in tuple(_CLAUDE_BROWSER_SESSIONS.items()):
        if (
            not value.lock.locked()
            and now - value.last_used > _CLAUDE_BROWSER_SESSION_TTL_SECONDS
        ):
            _CLAUDE_BROWSER_SESSIONS.pop(key, None)

    while len(_CLAUDE_BROWSER_SESSIONS) >= _CLAUDE_BROWSER_SESSION_MAX:
        evictable = [
            (value.last_used, key)
            for key, value in _CLAUDE_BROWSER_SESSIONS.items()
            if not value.lock.locked()
        ]
        if not evictable:
            # Temporarily exceed the soft bound rather than replacing an
            # active conversation and corrupting its Claude resume state.
            break
        _, oldest_key = min(evictable)
        _CLAUDE_BROWSER_SESSIONS.pop(oldest_key, None)

    session = _ClaudeBrowserSession(
        backend=ClaudeCodeChatBackend(
            hostname=hostname,
            agent_name=agent_name,
            timeout_seconds=_CLAUDE_RESPONSE_TIMEOUT_SECONDS,
        ),
        lock=asyncio.Lock(),
        last_used=now,
    )
    _CLAUDE_BROWSER_SESSIONS[cache_key] = session
    return session


def _invalidate_pi_browser_session(
    cache_key: tuple[str, str], session: _PiBrowserSession
) -> None:
    """Retire one generation without closing a backend under an active turn."""
    session.invalidated = True
    if _PI_BROWSER_SESSIONS.get(cache_key) is session:
        _PI_BROWSER_SESSIONS.pop(cache_key)


def _pi_browser_session_is_current(
    cache_key: tuple[str, str], session: _PiBrowserSession
) -> bool:
    """Whether a turn still belongs to the currently resolved Pi identity."""
    current = _PI_BROWSER_SESSIONS.get(cache_key)
    return (
        not session.invalidated
        and current is session
        and current.generation == session.generation
    )


def _get_pi_browser_session(
    *,
    agent_key: str,
    session_key: str,
    hostname: str,
    agent_name: str,
    model: str,
    provider_name: str,
    installation_id: str,
    pi_provider: str = "openrouter",
    host_key: str = "",
) -> _PiBrowserSession:
    """Return a bounded Pi session, discarding stale agent identities."""
    now = time.monotonic()
    cache_key = (agent_key, session_key)
    identity = (
        host_key or hostname,
        hostname,
        agent_name,
        model,
        provider_name,
        installation_id,
        pi_provider,
    )
    cached = _PI_BROWSER_SESSIONS.get(cache_key)
    # Legacy records predate installed_at. They have no durable generation
    # marker, so retaining a browser session could route a same-key recreated
    # agent to its predecessor. Prefer a fresh finite Pi turn over continuity
    # until the record is migrated by a normal install.
    if not installation_id:
        if cached is not None:
            _invalidate_pi_browser_session(cache_key, cached)
        cached = None
    if (
        cached is not None
        and cached.identity == identity
        and (
            cached.lock.locked()
            or now - cached.last_used <= _CLAUDE_BROWSER_SESSION_TTL_SECONDS
        )
    ):
        cached.last_used = now
        return cached
    if cached is not None:
        # A replaced identity can have an active turn. It retains its own
        # backend until its finally block closes it, but loses authority to
        # start (or return) a turn after the replacement generation exists.
        _invalidate_pi_browser_session(cache_key, cached)

    for key, value in tuple(_PI_BROWSER_SESSIONS.items()):
        if (
            not value.lock.locked()
            and now - value.last_used > _CLAUDE_BROWSER_SESSION_TTL_SECONDS
        ):
            _invalidate_pi_browser_session(key, value)
    while len(_PI_BROWSER_SESSIONS) >= _CLAUDE_BROWSER_SESSION_MAX:
        evictable = [
            (value.last_used, key)
            for key, value in _PI_BROWSER_SESSIONS.items()
            if not value.lock.locked()
        ]
        if not evictable:
            raise _PiSessionCapacityError
        _, oldest_key = min(evictable)
        _invalidate_pi_browser_session(oldest_key, _PI_BROWSER_SESSIONS[oldest_key])

    global _PI_BROWSER_SESSION_GENERATION
    _PI_BROWSER_SESSION_GENERATION += 1
    session = _PiBrowserSession(
        backend=PiChatBackend(hostname, agent_name, model, provider=pi_provider),
        identity=identity,
        generation=_PI_BROWSER_SESSION_GENERATION,
        lock=asyncio.Lock(),
        last_used=now,
    )
    _PI_BROWSER_SESSIONS[cache_key] = session
    return session


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
    install_status = agent_record.get("status")
    if install_status is not None and install_status != "installed":
        raise HTTPException(status_code=409, detail="Agent is not installed")

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
    if chat_type == "websocket":
        return await _chat_openclaw(host_record, agent_type, agent_record, body)
    if chat_type == "claude":
        return await _chat_claude(host_record, agent_record, agent_key, body)
    if chat_type == "codex":
        return await _chat_codex(host_record, agent_record, agent_key, body)
    if chat_type == "pi":
        return await _chat_pi(host_record, agent_record, agent_key, body)
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


async def _chat_claude(
    host_record: dict,
    agent_record: dict,
    agent_key: str,
    body: ChatRequest,
):
    """Run one finite Claude Code turn through the shared CLI backend.

    Each browser conversation supplies an opaque session key. The GUI keeps
    that key stable until its New chat action, while this route retains the
    corresponding backend UUID long enough for Claude's ``--resume`` path.
    No credential, prompt, stderr, or remote diagnostic is included in SSE
    errors or server logs.
    """
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="Chat message must not be blank")
    if len(body.message) > _CLAUDE_MAX_PROMPT_CHARS:
        raise HTTPException(status_code=422, detail="Chat message is too long")
    if not _CLAUDE_SESSION_KEY_RE.fullmatch(body.session):
        raise HTTPException(status_code=422, detail="Invalid chat session")

    hostname = host_record.get("hostname")
    agent_name = agent_record.get("agent_name") or agent_record.get("name") or agent_key
    if not isinstance(hostname, str) or not hostname.strip():
        raise HTTPException(status_code=500, detail=_CHAT_GENERIC_ERROR)
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise HTTPException(status_code=500, detail=_CHAT_GENERIC_ERROR)

    session = _get_claude_browser_session(
        agent_key=agent_key,
        session_key=body.session,
        hostname=hostname,
        agent_name=agent_name,
    )

    async def generate():
        try:
            # A malicious or stale browser client must not interleave two
            # turns for the same Claude UUID. Different browser sessions get
            # separate locks and separate backends.
            async with session.lock:
                try:
                    await session.backend.connect()
                    response_text = await session.backend.send_message(
                        message=body.message,
                        session_key=body.session,
                        response_timeout_seconds=_CLAUDE_RESPONSE_TIMEOUT_SECONDS,
                    )
                    events = [
                        "data: "
                        + json.dumps({"type": "content", "text": response_text})
                        + "\n\n",
                        "data: [DONE]\n\n",
                    ]
                except asyncio.CancelledError:
                    # The shared backend signals its runner, waits for prompt
                    # artifacts to be removed, then re-raises cancellation.
                    raise
                except Exception:
                    # Do not log exception details here: backend failures may
                    # carry SSH/Ansible context and must not expose prompts,
                    # credentials, or remote stderr through GUI logs or SSE.
                    events = [
                        "data: "
                        + json.dumps({"type": "error", "message": _CHAT_GENERIC_ERROR})
                        + "\n\n",
                        "data: [DONE]\n\n",
                    ]
                finally:
                    session.last_used = time.monotonic()
                    await session.backend.close()

                for event in events:
                    yield event
        except asyncio.CancelledError:
            raise

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _chat_codex(
    host_record: dict, agent_record: dict, agent_key: str, body: ChatRequest
):
    """Run a finite Codex JSONL turn through the shared CLI backend.

    Browser session keys select isolated native-thread backends. Credentials,
    prompts, stderr, and remote diagnostics never enter the SSE stream.
    """
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="Chat message must not be blank")
    if len(body.message) > _CODEX_MAX_PROMPT_CHARS:
        raise HTTPException(status_code=422, detail="Chat message is too long")
    if not _CODEX_SESSION_KEY_RE.fullmatch(body.session):
        raise HTTPException(status_code=422, detail="Invalid chat session")
    hostname = host_record.get("hostname")
    agent_name = agent_record.get("agent_name") or agent_record.get("name") or agent_key
    if not isinstance(hostname, str) or not hostname.strip():
        raise HTTPException(status_code=500, detail=_CHAT_GENERIC_ERROR)
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise HTTPException(status_code=500, detail=_CHAT_GENERIC_ERROR)
    try:
        session = _get_codex_browser_session(
            agent_key=agent_key,
            session_key=body.session,
            hostname=hostname,
            host_key=host_record.get("key_id") or hostname,
            agent_name=agent_name,
            installation_id=agent_record.get("installed_at")
            if isinstance(agent_record.get("installed_at"), str)
            else "",
        )
    except _CodexSessionCapacityError as exc:
        raise HTTPException(status_code=503, detail="Chat is busy; try again") from exc

    cache_key = (agent_key, body.session)
    async with session.lock:
        try:
            if not _codex_browser_session_is_current(
                cache_key, session
            ) or not await _codex_browser_session_matches_registry(agent_key, session):
                _invalidate_codex_browser_session(cache_key, session)
                raise HTTPException(status_code=409, detail="Codex agent identity changed")
            await session.backend.connect()
            response_text = await session.backend.send_message(
                message=body.message,
                session_key=body.session,
                response_timeout_seconds=_CODEX_RESPONSE_TIMEOUT_SECONDS,
            )
            if not _codex_browser_session_is_current(
                cache_key, session
            ) or not await _codex_browser_session_matches_registry(agent_key, session):
                _invalidate_codex_browser_session(cache_key, session)
                raise HTTPException(status_code=409, detail="Codex agent identity changed")
        except asyncio.CancelledError:
            raise
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=502, detail=_CHAT_GENERIC_ERROR) from None
        finally:
            session.last_used = time.monotonic()
            await session.backend.close()

    async def generate():
        yield "data: " + json.dumps({"type": "content", "text": response_text}) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _chat_pi(
    host_record: dict, agent_record: dict, agent_key: str, body: ChatRequest
):
    """Run a finite Pi turn while preserving the browser conversation UUID."""
    if not body.message.strip() or len(body.message) > _CLAUDE_MAX_PROMPT_CHARS:
        raise HTTPException(
            status_code=422, detail="Chat message must not be blank or too long"
        )
    if not _CLAUDE_SESSION_KEY_RE.fullmatch(body.session):
        raise HTTPException(status_code=422, detail="Invalid chat session")
    hostname = host_record.get("hostname")
    agent_name = agent_record.get("agent_name") or agent_key
    providers = agent_record.get("providers")
    if (
        not isinstance(hostname, str)
        or not isinstance(agent_name, str)
        or not isinstance(providers, list)
        or len(providers) != 1
        or not isinstance(providers[0], str)
    ):
        raise HTTPException(status_code=500, detail=_CHAT_GENERIC_ERROR)
    try:
        selection = validate_pi_provider(get_provider(providers[0]))
    except PiProvisioningError:
        raise HTTPException(status_code=500, detail=_CHAT_GENERIC_ERROR) from None
    try:
        session = _get_pi_browser_session(
            agent_key=agent_key,
            session_key=body.session,
            hostname=hostname,
            host_key=host_record.get("key_id") or hostname,
            agent_name=agent_name,
            model=selection.model,
            provider_name=providers[0],
            pi_provider=selection.provider,
            installation_id=agent_record.get("installed_at")
            if isinstance(agent_record.get("installed_at"), str)
            else "",
        )
    except _PiSessionCapacityError:
        raise HTTPException(status_code=503, detail=_CHAT_GENERIC_ERROR) from None

    # Pi print mode returns one finite response rather than incremental deltas.
    # Complete the bounded operation before creating an SSE response so backend
    # failures retain a meaningful non-2xx HTTP status.
    cache_key = (agent_key, body.session)
    async with session.lock:
        try:
            # A same-key reinstall/reassignment can replace the cache while a
            # prior request waits for this lock. Never let that queued request
            # connect to its predecessor after the new identity is current.
            if not _pi_browser_session_is_current(cache_key, session):
                raise HTTPException(status_code=409, detail="Pi agent identity changed")
            await session.backend.connect()
            text = await session.backend.send_message(
                body.message,
                body.session,
                response_timeout_seconds=_CLAUDE_RESPONSE_TIMEOUT_SECONDS,
            )
            # An in-flight old-host request cannot be interrupted safely, but
            # its completed response must not be served as the replacement.
            if not _pi_browser_session_is_current(cache_key, session):
                raise HTTPException(status_code=409, detail="Pi agent identity changed")
        except asyncio.CancelledError:
            raise
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=502, detail=_CHAT_GENERIC_ERROR) from None
        finally:
            session.last_used = time.monotonic()
            await session.backend.close()

    async def generate():
        yield "data: " + json.dumps({"type": "content", "text": text}) + "\n\n"
        yield "data: [DONE]\n\n"

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

    if not body.command:
        raise HTTPException(status_code=400, detail="command list must not be empty")

    resolved = await asyncio.to_thread(_resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    host_record, claw_type, agent_record = resolved
    hostname = host_record.get("hostname", "")
    agent_name = agent_record.get("agent_name") or agent_key

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
