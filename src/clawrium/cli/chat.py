"""Interactive chat command for installed agents.

Dispatch is driven by `features.chat.type` in the agent manifest:

- ``websocket`` → openclaw gateway over WebSocket (existing behavior).
- ``openai``    → hermes (and future agents) over OpenAI-compatible HTTP.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, TypedDict

import typer
from rich.console import Console
from rich.markup import escape as rich_escape

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatBackend,
    ChatConnectionError,
    ChatProtocolError,
    OpenClawChatClient,
    SecretStr,
)
from clawrium.core.chat_hermes import HermesOpenAIBackend
from clawrium.core.hosts import get_agent_by_name, HostsFileCorruptedError
from clawrium.core.registry import (
    ManifestNotFoundError,
    ManifestParseError,
    load_manifest,
)
from clawrium.core.secrets import get_instance_key, get_instance_secrets

console = Console()

__all__ = ["chat"]


class GatewayConfig(TypedDict, total=False):
    """Gateway connection settings from an installed agent record."""

    url: str
    auth: str
    device_id: str
    device_private_key: str


_SESSION_PATTERN = re.compile(r"^[a-zA-Z0-9_:.-]{1,255}$")


def chat(
    agent_name: str = typer.Argument(..., help="Installed agent name to chat with"),
    session: str = typer.Option(
        "main",
        "--session",
        "-s",
        help=(
            "Gateway session key for WebSocket-backed agents "
            "(for example: main, direct:<channel>, or thread-specific key). "
            "OpenAI-backed agents (e.g. hermes) accept the flag but ignore it "
            "in Phase 1 — server-side session routing is not wired through "
            "/v1/chat/completions yet."
        ),
    ),
    timeout: float = typer.Option(
        120.0,
        "--timeout",
        min=1.0,
        help="Seconds to wait for each assistant response before failing.",
    ),
    idle_timeout: float = typer.Option(
        300.0,
        "--idle-timeout",
        min=0.0,
        help="Seconds to wait for user input before auto-exit (0 disables).",
    ),
) -> None:
    """Start an interactive chat session with an installed agent."""
    _validate_session_key(session)

    try:
        resolved = get_agent_by_name(agent_name)
    except HostsFileCorruptedError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {rich_escape(str(exc))}")
        raise typer.Exit(code=1)

    if not resolved:
        console.print(f"[red]Error:[/red] Agent '{rich_escape(agent_name)}' not found")
        console.print("Run 'clm ps' to list installed agents.")
        raise typer.Exit(code=1)

    host_record, agent_type, agent_record = resolved

    try:
        chat_type = _resolve_chat_type(agent_type)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {rich_escape(str(exc))}")
        raise typer.Exit(code=1)

    display_host = (
        host_record.get("alias") or host_record.get("hostname") or "unknown-host"
    )
    # `canonical_name` is the Unix-level agent name used in secret instance
    # keys (host:type:name). Must NOT fall back to `agent_type` — that would
    # mint a wrong instance_key (e.g. host:hermes:hermes) and the bearer
    # lookup would silently miss the real entry.
    canonical_name = agent_record.get("agent_name") or agent_name
    # `display_agent` is for printing only; safe to fall back further.
    display_agent = (
        agent_record.get("agent_name")
        or agent_record.get("name")
        or agent_name
        or agent_type
    )

    try:
        if chat_type == "websocket":
            backend = _build_openclaw_backend(
                agent_record=agent_record,
                host_record=host_record,
                response_timeout_seconds=timeout,
            )
        elif chat_type == "openai":
            backend = _build_hermes_backend(
                agent_record=agent_record,
                host_record=host_record,
                agent_type=agent_type,
                agent_name=str(canonical_name),
                response_timeout_seconds=timeout,
            )
        else:
            console.print(
                f"[red]Error:[/red] Chat is not supported for agent type "
                f"'{rich_escape(agent_type)}'."
            )
            raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {rich_escape(str(exc))}")
        raise typer.Exit(code=1)

    console.print(
        f"[green]Connected target:[/green] {rich_escape(str(display_agent))} on {rich_escape(str(display_host))}"
    )
    console.print("Type /exit or press Ctrl+D to end the chat session.")

    try:
        asyncio.run(
            _chat_loop(
                backend=backend,
                session_key=session,
                response_timeout_seconds=timeout,
                idle_timeout_seconds=idle_timeout,
            )
        )
    except ChatAuthenticationError as exc:
        console.print(
            f"[red]Authentication failed:[/red] {rich_escape(_sanitize_exception_text(exc))}"
        )
        raise typer.Exit(code=1)
    except ChatConnectionError as exc:
        console.print(
            f"[red]Connection failed:[/red] {rich_escape(_sanitize_exception_text(exc))}"
        )
        console.print(
            "Verify the host is online and the recorded gateway URL/token are current (re-run configure/install if needed)."
        )
        raise typer.Exit(code=1)
    except ChatProtocolError as exc:
        console.print(
            f"[red]Protocol error:[/red] {rich_escape(_sanitize_exception_text(exc))}"
        )
        raise typer.Exit(code=1)


async def _chat_loop(
    backend: ChatBackend,
    session_key: str,
    response_timeout_seconds: float,
    idle_timeout_seconds: float,
) -> None:
    with console.status("Connecting to agent...", spinner="dots"):
        await backend.connect()

    try:
        while True:
            try:
                user_input = await _read_user_input("you> ", idle_timeout_seconds)
            except EOFError:
                console.print("\n[dim]Chat ended.[/dim]")
                break
            except KeyboardInterrupt:
                console.print("\n[dim]Interrupted.[/dim]")
                break
            except TimeoutError:
                console.print(
                    "\n[dim]No input received before idle timeout. Ending chat.[/dim]"
                )
                break

            message = user_input.strip()
            if not message:
                continue
            if message in {"/exit", "/quit"}:
                console.print("[dim]Bye.[/dim]")
                break

            shown_prefix = False

            def on_delta(delta: str) -> None:
                nonlocal shown_prefix
                if not shown_prefix:
                    console.print("agent> ", end="", markup=False, highlight=False)
                    shown_prefix = True
                console.print(delta, end="", markup=False, highlight=False)

            final_text = await backend.send_message(
                message=message,
                session_key=session_key,
                on_delta=on_delta,
                response_timeout_seconds=response_timeout_seconds,
            )
            if shown_prefix:
                console.print("")
            elif final_text:
                console.print(f"agent> {final_text}", markup=False, highlight=False)
            else:
                console.print("agent> [no response]", markup=False, highlight=False)
    finally:
        await backend.close()


async def _read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
    task = asyncio.create_task(asyncio.to_thread(input, prompt))
    try:
        if idle_timeout_seconds > 0:
            return await asyncio.wait_for(task, timeout=idle_timeout_seconds)
        return await task
    except TimeoutError:
        task.cancel()
        raise


def _resolve_chat_type(agent_type: str) -> str:
    """Read `features.chat.type` from the agent manifest.

    Raises ValueError when the manifest cannot be loaded or does not advertise
    chat support, so the caller can surface a friendly typer.Exit(1).
    """
    try:
        manifest = load_manifest(agent_type)
    except (ManifestNotFoundError, ManifestParseError) as exc:
        raise ValueError(
            f"Could not load manifest for agent type '{agent_type}': {exc}"
        ) from exc

    features = manifest.get("features") or {}
    chat = features.get("chat") if isinstance(features, dict) else None
    if not isinstance(chat, dict):
        raise ValueError(
            f"Chat is not supported for agent type '{agent_type}'."
        )
    chat_type = chat.get("type")
    if not isinstance(chat_type, str) or not chat_type:
        raise ValueError(
            f"Chat is not supported for agent type '{agent_type}'."
        )
    return chat_type


def _build_openclaw_backend(
    agent_record: dict[str, Any],
    host_record: dict[str, Any],
    response_timeout_seconds: float,
) -> ChatBackend:
    gateway = _extract_gateway_config(agent_record, host_record)
    return OpenClawChatClient(
        gateway_url=gateway["url"],
        auth_token=SecretStr(gateway["auth"]),
        device_id=gateway.get("device_id"),
        device_private_key=gateway.get("device_private_key"),
        timeout_seconds=response_timeout_seconds,
    )


def _build_hermes_backend(
    agent_record: dict[str, Any],
    host_record: dict[str, Any],
    agent_type: str,
    agent_name: str,
    response_timeout_seconds: float,
) -> ChatBackend:
    """Construct a HermesOpenAIBackend from the persisted hosts.json record.

    - URL: `http://{host_record.hostname}:{api_server.port}/v1` — mirrors
      openclaw's `_reconstruct_gateway_url`, which uses the host record's
      reachable address rather than `api_server.host` (that's the bind, not
      the dial target).
    - Bearer: `secrets.json[<instance_key>].HERMES_API_SERVER_KEY` — mirrors
      lifecycle.py:734-771.
    """
    config = agent_record.get("config")
    if not isinstance(config, dict):
        raise ValueError("Agent config missing. Re-run 'clm agent configure'.")
    api_server = config.get("api_server")
    if not isinstance(api_server, dict):
        raise ValueError(
            "Hermes api_server config missing. Re-run 'clm agent configure'."
        )

    port = api_server.get("port")
    if not isinstance(port, int) or port <= 0:
        raise ValueError(
            "Hermes api_server.port missing or invalid. Re-run 'clm agent configure'."
        )

    hostname = host_record.get("hostname")
    if not isinstance(hostname, str) or not hostname.strip():
        raise ValueError("Host primary address not found.")

    instance_key = get_instance_key(hostname, agent_type, agent_name)
    secret_entry = get_instance_secrets(instance_key).get("HERMES_API_SERVER_KEY")
    raw_token = secret_entry["value"] if secret_entry else None
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise ValueError(
            "HERMES_API_SERVER_KEY missing from secrets.json. "
            "Re-run 'clm agent install --type hermes ...' to generate one."
        )

    base_url = f"http://{hostname}:{port}/v1"
    return HermesOpenAIBackend(
        base_url=base_url,
        auth_token=SecretStr(raw_token),
        timeout_seconds=response_timeout_seconds,
    )


def _extract_gateway_config(
    agent_record: dict[str, Any], host_record: dict[str, Any]
) -> GatewayConfig:
    config = agent_record.get("config")
    if not isinstance(config, dict):
        raise ValueError("Agent config missing. Re-run agent configure/install.")

    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        raise ValueError("Gateway config missing. Re-run agent configure/install.")

    stored_url = gateway.get("url")
    if not isinstance(stored_url, str) or not stored_url.strip():
        raise ValueError(
            "Gateway URL is missing. Re-run install/configure to capture gateway URL."
        )

    auth_token = gateway.get("auth")
    if not isinstance(auth_token, str) or not auth_token.strip():
        raise ValueError(
            "Gateway auth token is missing. Re-run install/configure to refresh pairing token."
        )

    # Reconstruct gateway URL using current primary address from host record.
    # This ensures connectivity regardless of which network interface is used.
    gateway_url = _reconstruct_gateway_url(stored_url, gateway, host_record)

    result: GatewayConfig = {"url": gateway_url, "auth": auth_token}

    # Extract device credentials for operator.write scope
    device = gateway.get("device")
    if isinstance(device, dict):
        device_id = device.get("id")
        device_private_key = device.get("privateKey")
        if isinstance(device_id, str) and device_id.strip():
            result["device_id"] = device_id
        if isinstance(device_private_key, str) and device_private_key.strip():
            result["device_private_key"] = device_private_key

    return result


def _reconstruct_gateway_url(
    stored_url: str, gateway: dict[str, Any], host_record: dict[str, Any]
) -> str:
    """Reconstruct gateway URL using host's current primary address.

    The stored URL may contain an IP that's no longer reachable (e.g., LAN IP
    when connecting via Tailscale). This function rebuilds the URL using the
    host's current primary address while preserving the scheme and port.

    Args:
        stored_url: The originally stored gateway URL (e.g., ws://192.168.1.36:40317)
        gateway: Gateway config dict that may contain explicit port
        host_record: Host record containing current primary address in 'hostname'

    Returns:
        Reconstructed gateway URL using current primary address
    """
    from urllib.parse import urlparse

    parsed = urlparse(stored_url)
    scheme = parsed.scheme or "ws"

    # Get port from gateway config or parse from stored URL
    port = gateway.get("port")
    if not port and parsed.port:
        port = parsed.port

    if not port:
        raise ValueError(
            "Gateway port not found. Re-run install/configure to capture gateway config."
        )

    # Use current primary address from host record
    current_host = host_record.get("hostname")
    if not current_host:
        raise ValueError("Host primary address not found.")

    return f"{scheme}://{current_host}:{port}"


def _validate_session_key(session_key: str) -> None:
    if not _SESSION_PATTERN.fullmatch(session_key):
        raise typer.BadParameter(
            "Invalid session format. Use 1-255 chars: letters, numbers, _, :, ., -"
        )


def _sanitize_exception_text(exc: Exception, max_len: int = 500) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(exc))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(
        r"(?i)\b(token|auth|password)\b\s*[:=]\s*([^\s,;]+)",
        r"\1=***",
        cleaned,
    )
    return cleaned[:max_len]
