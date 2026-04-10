"""Interactive chat command for OpenClaw agents."""

from __future__ import annotations

import asyncio
import re
from typing import Any, TypedDict

import typer
from rich.console import Console
from rich.markup import escape as rich_escape

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
    OpenClawChatClient,
    SecretStr,
)
from clawrium.core.hosts import get_agent_by_name, HostsFileCorruptedError

console = Console()

__all__ = ["chat"]


class GatewayConfig(TypedDict):
    """Gateway connection settings from an installed agent record."""

    url: str
    auth: str


_SESSION_PATTERN = re.compile(r"^[a-zA-Z0-9_:.-]{1,255}$")


def chat(
    agent_name: str = typer.Argument(..., help="Installed agent name to chat with"),
    session: str = typer.Option(
        "main",
        "--session",
        "-s",
        help="Gateway session key (for example: main, direct:<channel>, or thread-specific key)",
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
    if agent_type != "openclaw":
        console.print(
            f"[red]Error:[/red] Chat is currently supported for OpenClaw only (got {rich_escape(agent_type)})"
        )
        raise typer.Exit(code=1)

    try:
        gateway = _extract_gateway_config(agent_record)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {rich_escape(str(exc))}")
        raise typer.Exit(code=1)
    gateway_url = gateway["url"]
    auth_token = SecretStr(gateway["auth"])

    display_host = (
        host_record.get("alias") or host_record.get("hostname") or "unknown-host"
    )
    display_agent = (
        agent_record.get("agent_name")
        or agent_record.get("name")
        or agent_name
        or "openclaw"
    )

    console.print(
        f"[green]Connected target:[/green] {rich_escape(str(display_agent))} on {rich_escape(str(display_host))}"
    )
    console.print("Type /exit or press Ctrl+D to end the chat session.")

    try:
        asyncio.run(
            _chat_loop(
                gateway_url=str(gateway_url),
                auth_token=auth_token,
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
    gateway_url: str,
    auth_token: SecretStr,
    session_key: str,
    response_timeout_seconds: float,
    idle_timeout_seconds: float,
) -> None:
    client = OpenClawChatClient(gateway_url=gateway_url, auth_token=auth_token)
    with console.status("Connecting to gateway...", spinner="dots"):
        await client.connect()

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

            final_text = await client.send_message(
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
        await client.close()


async def _read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
    task = asyncio.create_task(asyncio.to_thread(input, prompt))
    try:
        if idle_timeout_seconds > 0:
            return await asyncio.wait_for(task, timeout=idle_timeout_seconds)
        return await task
    except TimeoutError:
        task.cancel()
        raise


def _extract_gateway_config(agent_record: dict[str, Any]) -> GatewayConfig:
    config = agent_record.get("config")
    if not isinstance(config, dict):
        raise ValueError("Agent config missing. Re-run agent configure/install.")

    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        raise ValueError("Gateway config missing. Re-run agent configure/install.")

    gateway_url = gateway.get("url")
    if not isinstance(gateway_url, str) or not gateway_url.strip():
        raise ValueError(
            "Gateway URL is missing. Re-run install/configure to capture gateway URL."
        )

    auth_token = gateway.get("auth")
    if not isinstance(auth_token, str) or not auth_token.strip():
        raise ValueError(
            "Gateway auth token is missing. Re-run install/configure to refresh pairing token."
        )

    return {"url": gateway_url, "auth": auth_token}


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
