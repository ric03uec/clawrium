"""Interactive chat command for installed agents.

Dispatch is driven by `features.chat.type` in the agent manifest:

- ``websocket`` → openclaw gateway over WebSocket (existing behavior).
- ``openai``    → hermes (and future agents) over OpenAI-compatible HTTP.
- ``zeroclaw``  → ZeroClaw gateway over WebSocket with bearer-token auth
                  (tagged-JSON envelope; distinct from openclaw's frame
                  schema, so it gets a dedicated dispatch value).
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Any, Optional, TypedDict

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
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
from clawrium.core.chat_zeroclaw import (
    RECV_TIMEOUT_MSG_PREFIX as ZEROCLAW_RECV_TIMEOUT_MSG_PREFIX,
    ZeroClawChatBackend,
)
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


# Single-shot mode hard cap. `--once` skips the REPL and awaits ONE top-
# level completion, so a stuck agent must not hang the caller forever.
# The effective per-request timeout in once mode is min(--timeout,
# _ONCE_IDLE_TIMEOUT_SECONDS); the CLI --timeout still bounds slow but
# progressing turns. Kept as a module constant rather than a flag to
# keep the surface small — promotable in a follow-up if operators ask.
_ONCE_IDLE_TIMEOUT_SECONDS = 60.0

_SESSION_PATTERN = re.compile(r"^[a-zA-Z0-9_:.-]{1,255}$")

# C0/C1 control + Unicode bidi-formatting + zero-width + line/paragraph
# separators. Kept in sync with `_sanitize_exception_text` below and
# `chat_hermes._CONTROL_CHARS_RE`. Shared so the agent-label sanitizer
# (issue #455 ATX W2) and the exception sanitizer use identical
# coverage; drifting one would reintroduce the bypass.
_CONTROL_AND_BIDI_RE = re.compile(
    # Use explicit \uXXXX escapes (matching chat_hermes._CONTROL_CHARS_RE).
    # Literal bidi/zero-width codepoints in source are invisible to most
    # editors and easily corrupted by auto-formatters, BOM insertion, or
    # careless copy-paste — \uXXXX escapes are grep-able and survive
    # every editor.
    "["
    "\x00-\x1f\x7f-\x9f"
    "\u061c"  # ARABIC LETTER MARK (UAX#9 bidi format char)
    "\u200b-\u200f"  # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "\u2028-\u2029"  # LINE / PARAGRAPH SEPARATOR
    "\u202a-\u202e"  # LRE, RLE, PDF, LRO, RLO
    "\u2060"  # WORD JOINER
    "\u2066-\u2069"  # LRI, RLI, FSI, PDI
    "\ufeff"  # ZWNBSP / BOM
    "]"
)


def _sanitize_agent_label(label: str) -> str:
    """Strip control / bidi / zero-width chars from `label` so it is
    safe to render at terminal output sites.

    Replaces dangerous codepoints with a single space, then collapses
    runs of whitespace. Returns a literal `agent` fallback when the
    input collapses to empty so the prefix is never just `> `.
    """
    cleaned = _CONTROL_AND_BIDI_RE.sub(" ", label)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "agent"


def chat(
    agent_name: str = typer.Argument(..., help="Installed agent name to chat with"),
    session: str = typer.Option(
        "main",
        "--session",
        "-s",
        help=(
            "Gateway session key for WebSocket-backed agents "
            "(for example: main, direct:<channel>, or thread-specific key). "
            "OpenAI-backed agents (e.g. hermes) accept the flag but it has no "
            "effect — server-side session isolation is not yet supported."
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
    once: Optional[str] = typer.Option(
        None,
        "--once",
        help=(
            "Send one message, print the reply, and exit. Exit code 0 on "
            "success, non-zero on transport error."
        ),
    ),
) -> None:
    """Start an interactive chat session with an installed agent.

    REPL commands:
    - /exit or /quit: end the session
    - /reset: clear accumulated conversation history (no-op for WebSocket-backed
      agents where the gateway owns session state)
    """
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
        console.print("Run 'clawctl agent get' to list installed agents.")
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
        elif chat_type == "openai" and agent_type == "ethos":
            backend = _build_ethos_backend(
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
        elif chat_type == "zeroclaw":
            backend = _build_zeroclaw_backend(
                agent_record=agent_record,
                host_record=host_record,
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

    # Emit the `--session` no-op notice only after backend construction
    # succeeds so the user doesn't see a misleading "chat is about to start"
    # warning followed by a hard error. ATX Round 1 W7: zeroclaw too —
    # the ZeroClaw gateway owns session state and there is no separate
    # session-key concept on the wire.
    #
    # ATX Round 2 S5: distinct wording per backend — hermes/openai's
    # history is client-side in-memory; zeroclaw's session state lives
    # on the gateway daemon for the lifetime of the WebSocket. The old
    # generic "in-memory only" line was accurate for hermes but
    # misleading for zeroclaw.
    # Scripted callers (`--once`) get clean stdout containing only the
    # reply. The session-noop notices and interactive banners are
    # gated on interactive mode.
    if once is None:
        if chat_type == "openai" and session != "main":
            console.print(
                "[dim]`--session` is accepted but has no effect for this agent type "
                "— conversation history is in-memory only and will not be routed to "
                "a named session.[/dim]"
            )
        elif chat_type == "zeroclaw" and session != "main":
            console.print(
                "[dim]`--session` is accepted but has no effect for zeroclaw — the "
                "gateway daemon owns session state for the duration of this "
                "WebSocket connection.[/dim]"
            )

        console.print(
            f"[green]Connected target:[/green] {rich_escape(str(display_agent))} on {rich_escape(str(display_host))}"
        )
        if chat_type == "openai":
            console.print(
                "Type /exit or press Ctrl+D to end. Use /reset to clear conversation history."
            )
        else:
            console.print("Type /exit or press Ctrl+D to end the chat session.")

    attempted_reconnect = False
    while True:
        # Drop the module-level PromptSession between reconnect iterations.
        # Each `asyncio.run(_chat_loop(...))` is a fresh event loop; reusing
        # a PromptSession that was created during the previous loop's
        # `prompt_async` (and whose `Application`/`AsyncOutput` may still
        # hold fd refs / terminal state from that loop) risks anchoring the
        # second iteration to an already-closed loop. Forcing a fresh
        # session on each retry costs one extra object construction and
        # eliminates that whole class of cross-loop weirdness.
        _reset_prompt_session()
        try:
            asyncio.run(
                _chat_loop(
                    backend=backend,
                    session_key=session,
                    response_timeout_seconds=timeout,
                    idle_timeout_seconds=idle_timeout,
                    chat_type=chat_type,
                    agent_label=str(display_agent),
                    once=once,
                )
            )
            if attempted_reconnect:
                # ATX W7: only confirm success after the retry actually
                # succeeded (no further auth error during the inner loop).
                console.print("[dim]Gateway token rotated; reconnected.[/dim]")
            break
        except ChatAuthenticationError as exc:
            # Issue #437: zeroclaw lifecycle ops always rotate the bearer.
            # If a sync/restart/configure rotated the token in another
            # shell while this session was open, the in-memory bearer is
            # stale. Reload hosts.json once; if the on-disk bearer
            # differs, rebuild the backend with the fresh token and
            # resume. Identical bearer ⇒ genuine pairing failure, fall
            # through to the existing error path.
            if chat_type == "zeroclaw" and not attempted_reconnect:
                reloaded_backend = _try_reload_zeroclaw_bearer(
                    agent_name=agent_name,
                    current_bearer=_current_bearer_for_backend(backend),
                    response_timeout_seconds=timeout,
                )
                if reloaded_backend is not None:
                    backend = reloaded_backend
                    attempted_reconnect = True
                    # ATX W7: tentative — the second asyncio.run might
                    # also raise. Promote to the documented confirmation
                    # only after the retry actually breaks the loop.
                    console.print("[dim]Gateway token rotated — retrying...[/dim]")
                    continue
            console.print(
                f"[red]Authentication failed:[/red] {rich_escape(_sanitize_exception_text(exc))}"
            )
            if chat_type in ("openai", "zeroclaw"):
                console.print(
                    f"Token mismatch. Re-run 'clawctl agent configure {rich_escape(str(canonical_name))}'."
                )
            raise typer.Exit(code=1)
        except ChatConnectionError as exc:
            console.print(
                f"[red]Connection failed:[/red] {rich_escape(_sanitize_exception_text(exc))}"
            )
            if chat_type == "openai":
                # The backend uses two distinct ChatConnectionError messages:
                # - "Failed to reach hermes at <url>" for connect-refused / DNS
                # - "Timed out waiting for hermes response after Ns" for timeouts
                # A genuine timeout means the service is up but slow; the right
                # remediation is `--timeout`, not `systemctl`.
                if str(exc).startswith("Timed out"):
                    console.print(
                        f"Try a higher --timeout value (current: {timeout}s)."
                    )
                else:
                    svc = "ethos" if agent_type == "ethos" else "hermes"
                    console.print(
                        f"Check 'systemctl --user status {svc}-{rich_escape(str(canonical_name))}' on the agent host."
                    )
                    # Legacy install hint: persisted bind still on loopback means the
                    # opportunistic 127.0.0.1 → 0.0.0.0 migration in lifecycle hasn't
                    # run for this agent yet. Re-running configure flips it.
                    api_server = (
                        agent_record.get("config", {}).get("api_server")
                        if isinstance(agent_record.get("config"), dict)
                        else None
                    )
                    if (
                        isinstance(api_server, dict)
                        and api_server.get("host") == "127.0.0.1"
                    ):
                        console.print(
                            f"Legacy bind detected (127.0.0.1). "
                            f"Re-run 'clawctl agent configure {rich_escape(str(canonical_name))}' "
                            f"to bind a reachable interface."
                        )
            elif chat_type == "zeroclaw":
                # ATX Round 1 W6 / Round 2 W8: distinguish three connection
                # failure modes. `chat_zeroclaw.py` emits three word-stable
                # ChatConnectionError messages:
                #
                #   "Timed out connecting to ZeroClaw gateway at <url>"
                #       -> TCP handshake never completed; firewall / wrong
                #          port / host down. A higher --timeout won't help
                #          because the connect path doesn't honor request
                #          timeout. Route to a reachability hint.
                #
                #   "Timed out waiting for ZeroClaw response after Ns"
                #       -> Connection succeeded but the agent is slow.
                #          Route to the --timeout hint.
                #
                #   "Failed to reach ZeroClaw gateway at <url>: <reason>"
                #       -> Connect failed immediately (OSError). Same as
                #          connect-timeout: reachability hint.
                # ATX Round 3 W2: use the shared constant exported by the
                # zeroclaw backend so reworded exception messages can't
                # silently misroute the hint.
                msg = str(exc)
                if msg.startswith(ZEROCLAW_RECV_TIMEOUT_MSG_PREFIX):
                    console.print(
                        f"Try a higher --timeout value (current: {timeout}s)."
                    )
                else:
                    console.print(
                        f"Verify the agent host is reachable and re-run "
                        f"'clawctl agent configure {rich_escape(str(canonical_name))}' "
                        f"if the pairing token is stale."
                    )
            else:
                console.print(
                    "Verify the host is online and the recorded gateway URL/token are current (re-run configure/install if needed)."
                )
            raise typer.Exit(code=1)
        except ChatProtocolError as exc:
            console.print(
                f"[red]Protocol error:[/red] {rich_escape(_sanitize_exception_text(exc))}"
            )
            raise typer.Exit(code=1)


async def _chat_once(
    backend: ChatBackend,
    session_key: str,
    response_timeout_seconds: float,
    message: str,
) -> None:
    """Single-shot chat turn: connect, send one message, print reply, close.

    Exceptions (`ChatAuthenticationError`, `ChatConnectionError`,
    `ChatProtocolError`) propagate to the outer `chat()` handlers, which
    render a diagnostic and exit non-zero. Stdout stays clean — only the
    assembled reply is written via `console.print` — so scripted callers
    (`clawctl agent chat <name> --once "hi"`) can consume it directly.

    The per-request timeout is capped at `_ONCE_IDLE_TIMEOUT_SECONDS` so
    a stuck agent cannot hang the caller indefinitely even if the
    operator passed a large `--timeout`.
    """
    effective_timeout = min(response_timeout_seconds, _ONCE_IDLE_TIMEOUT_SECONDS)
    await backend.connect()
    try:
        # Stream nothing to stdout during the turn; we print the full
        # assembled reply after `send_message` returns. This keeps the
        # scripted-caller contract simple: one newline-terminated reply
        # on stdout, no partial writes interleaved with progress noise.
        final_text = await backend.send_message(
            message=message,
            session_key=session_key,
            on_delta=None,
            response_timeout_seconds=effective_timeout,
        )
    finally:
        await backend.close()

    if final_text:
        console.print(final_text, markup=False, highlight=False)
    else:
        console.print("[no response]", markup=False, highlight=False)


async def _chat_loop(
    backend: ChatBackend,
    session_key: str,
    response_timeout_seconds: float,
    idle_timeout_seconds: float,
    chat_type: str = "websocket",
    agent_label: str = "agent",
    once: Optional[str] = None,
) -> None:
    if once is not None:
        await _chat_once(
            backend=backend,
            session_key=session_key,
            response_timeout_seconds=response_timeout_seconds,
            message=once,
        )
        return

    with console.status("Connecting to agent...", spinner="dots"):
        await backend.connect()

    history_capable = chat_type == "openai"
    # Parity with `_sanitize_exception_text` (issue #455 ATX W2): strip
    # C0/C1 control bytes + bidi-formatting + zero-width + line/paragraph
    # separators from the agent label before it reaches the terminal.
    # Normal lifecycle validation (^[a-z][a-z0-9_-]{0,31}$) already
    # precludes these, but a hand-edited `hosts.json` could smuggle in a
    # bidi-spoofed label; this guarantees the styled prefix can never be
    # the injection site.
    agent_prefix_plain = f"{_sanitize_agent_label(agent_label)}> "

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
            if message == "/reset":
                if history_capable:
                    backend.clear_history()
                    console.print("[dim]Conversation history cleared.[/dim]")
                else:
                    console.print(
                        "[yellow]/reset is a no-op for this agent type "
                        "(the gateway owns session state).[/yellow]"
                    )
                continue

            shown_prefix = False
            status = console.status("Waiting for agent...", spinner="dots")
            status.start()
            status_stopped = False

            def _stop_status() -> None:
                nonlocal status_stopped
                if not status_stopped:
                    status.stop()
                    status_stopped = True

            def on_delta(delta: str) -> None:
                nonlocal shown_prefix
                _stop_status()
                if not shown_prefix:
                    # `style=` (not f-string markup) AND `markup=False`:
                    # `style=` alone does NOT disable Rich's markup parser
                    # (it's on by default), so an `agent_label` containing
                    # `[red]…[/red]` or `[link=…]…[/link]` would still be
                    # consumed by the parser even though the string is
                    # passed positionally. `markup=False` is what actually
                    # turns parsing off; `style=` then applies the color
                    # to the literal text.
                    console.print(
                        agent_prefix_plain,
                        end="",
                        style="bold green",
                        highlight=False,
                        markup=False,
                    )
                    shown_prefix = True
                console.print(delta, end="", markup=False, highlight=False)

            try:
                final_text = await backend.send_message(
                    message=message,
                    session_key=session_key,
                    on_delta=on_delta,
                    response_timeout_seconds=response_timeout_seconds,
                )
            except ChatProtocolError as exc:
                _stop_status()
                if shown_prefix:
                    console.print("")
                console.print(
                    f"[red]Protocol error:[/red] "
                    f"{rich_escape(_sanitize_exception_text(exc))}"
                )
                # ATX Round 2 W2 / Round 4 W-A: some protocol errors
                # (e.g. zeroclaw `approval_request`) tear down the
                # transport before re-raising. Continuing the REPL
                # after such an error would send the next message into
                # a stuck connection and produce a misleading "host
                # unreachable" error on the *next* user turn. Break
                # cleanly so the user sees the right remediation up
                # front.
                #
                # `backend.is_connected` is declared in the
                # `ChatBackend` Protocol; reading the attribute
                # directly (not via `getattr(..., True)`) makes a
                # missing-property regression an immediate
                # AttributeError instead of a silent always-True
                # fallback.
                if not backend.is_connected:
                    console.print(
                        "[dim]Chat session ended. Reconnect with "
                        "`clawctl agent chat <name>` to start a new session.[/dim]"
                    )
                    break
                console.print("[dim]Continuing chat session.[/dim]")
                continue
            finally:
                _stop_status()

            if shown_prefix:
                console.print("")
            elif final_text:
                console.print(
                    agent_prefix_plain,
                    end="",
                    style="bold green",
                    highlight=False,
                    markup=False,
                )
                console.print(final_text, markup=False, highlight=False)
            else:
                console.print(
                    agent_prefix_plain,
                    end="",
                    style="bold green",
                    highlight=False,
                    markup=False,
                )
                console.print("[no response]", markup=False, highlight=False)

            # Surface a user-visible notice when the backend silently trimmed
            # the conversation history to stay under MAX_HISTORY_TURNS. Only
            # backends with client-side history expose this attribute.
            dropped = getattr(backend, "last_send_dropped_turns", 0)
            if dropped:
                console.print(
                    f"[yellow]Note: dropped {dropped} oldest "
                    f"{'turn' if dropped == 1 else 'turns'} from history "
                    f"to stay under the conversation cap. "
                    f"Use /reset to start fresh.[/yellow]"
                )
    finally:
        await backend.close()


_PROMPT_SESSION: PromptSession[str] | None = None


def _get_prompt_session() -> PromptSession[str]:
    global _PROMPT_SESSION
    if _PROMPT_SESSION is None:
        _PROMPT_SESSION = PromptSession()
    return _PROMPT_SESSION


def _reset_prompt_session() -> None:
    """Drop the cached PromptSession so the next `_read_user_input` call
    constructs a fresh one. Called at the start of each `chat()`
    reconnect iteration; safe to call when no session has been created
    yet."""
    global _PROMPT_SESSION
    _PROMPT_SESSION = None


async def _read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
    # Non-TTY fallback: prompt_toolkit requires a real terminal and raises
    # if stdin is piped or otherwise not a TTY. Preserve the bare `input()`
    # behavior so scripted callers (`echo hi | clawctl agent chat ...`) still work.
    # `sys.stdin is None` covers detached embedders (Windows GUI hosts,
    # `subprocess.Popen(stdin=DEVNULL)`, sites that set `sys.stdin = None`):
    # without the explicit None check, `.isatty()` would raise
    # `AttributeError` before the fallback can take over.
    if sys.stdin is None or not sys.stdin.isatty():
        task = asyncio.create_task(asyncio.to_thread(input, prompt))
        try:
            if idle_timeout_seconds > 0:
                return await asyncio.wait_for(task, timeout=idle_timeout_seconds)
            return await task
        except TimeoutError:
            task.cancel()
            raise

    styled = FormattedText([("ansiblue bold", prompt)])
    session = _get_prompt_session()
    coro = session.prompt_async(styled)
    if idle_timeout_seconds > 0:
        return await asyncio.wait_for(coro, timeout=idle_timeout_seconds)
    return await coro


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
        raise ValueError(f"Chat is not supported for agent type '{agent_type}'.")
    chat_type = chat.get("type")
    if not isinstance(chat_type, str) or not chat_type:
        raise ValueError(f"Chat is not supported for agent type '{agent_type}'.")
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


def _current_bearer_for_backend(backend: ChatBackend) -> str | None:
    """Return the bearer the backend will send on its next request.

    Reads `_auth_token` (the SecretStr field both OpenClaw and ZeroClaw
    backends use). Returns None if the backend type doesn't expose one;
    callers treat None as "cannot compare" and skip the reconnect path.
    """
    auth = getattr(backend, "_auth_token", None)
    if auth is None:
        return None
    # SecretStr exposes get_secret_value()
    getter = getattr(auth, "get_secret_value", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return None


def _try_reload_zeroclaw_bearer(
    agent_name: str,
    current_bearer: str | None,
    response_timeout_seconds: float,
) -> ChatBackend | None:
    """Reload hosts.json for a zeroclaw agent and rebuild the backend if
    the on-disk bearer differs from `current_bearer`.

    Returns a fresh ChatBackend when reconnect should proceed, or None
    when the on-disk bearer matches (genuine pairing failure) or the
    reload itself failed (treat as "cannot transparently recover").
    """
    if current_bearer is None:
        return None
    try:
        resolved = get_agent_by_name(agent_name)
    except (HostsFileCorruptedError, ValueError):
        return None
    if not resolved:
        return None
    host_record, _agent_type, agent_record = resolved
    disk_bearer = (
        agent_record.get("config", {}).get("gateway", {}).get("auth")
        if isinstance(agent_record.get("config"), dict)
        else None
    )
    if not isinstance(disk_bearer, str) or not disk_bearer.strip():
        return None
    if disk_bearer == current_bearer:
        return None
    try:
        return _build_zeroclaw_backend(
            agent_record=agent_record,
            host_record=host_record,
            response_timeout_seconds=response_timeout_seconds,
        )
    except ValueError:
        return None


def _build_zeroclaw_backend(
    agent_record: dict[str, Any],
    host_record: dict[str, Any],
    response_timeout_seconds: float,
) -> ChatBackend:
    """Construct a ZeroClawChatBackend from the persisted hosts.json record.

    Reuses `_extract_gateway_config` for shape parity with openclaw — the
    bearer token and URL live under the same `config.gateway.{auth,url}`
    keys, written by `clawctl agent configure` (issue #357).

    The path-suffix `/ws/chat` is appended if the persisted URL was only
    the gateway origin. ZeroClaw's chat endpoint is `GET /ws/chat`; older
    persisted records (or hand-edited ones) may omit the path.

    The agent instance name is passed through as `agent_alias`. Since
    zeroclaw ≥0.8.2 the daemon requires `?agent=<alias>` on the
    handshake and a matching `[agents.<alias>]` sub-table in
    config.toml (both landed in #817). The canonical renderer emits
    the sub-table using the same instance name, so the two ends stay
    in lockstep.
    """
    gateway = _extract_gateway_config(agent_record, host_record)
    url = gateway["url"]
    # Idempotent suffix: append `/ws/chat` only when missing. ZeroClaw's
    # gateway rejects connections at the bare root path.
    if "/ws/chat" not in url:
        url = url.rstrip("/") + "/ws/chat"
    agent_alias = agent_record.get("agent_name") or agent_record.get("name")
    return ZeroClawChatBackend(
        gateway_url=url,
        auth_token=SecretStr(gateway["auth"]),
        timeout_seconds=response_timeout_seconds,
        agent_alias=str(agent_alias) if agent_alias else None,
    )


def _build_ethos_backend(
    agent_record: dict[str, Any],
    host_record: dict[str, Any],
    response_timeout_seconds: float,
) -> ChatBackend:
    """Construct an EthosOpenAIBackend from the persisted hosts.json record."""
    from clawrium.core.chat_ethos import EthosOpenAIBackend

    config = agent_record.get("config")
    if not isinstance(config, dict):
        raise ValueError("Agent config missing. Re-run 'clawctl agent configure'.")
    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        raise ValueError("Ethos gateway config missing. Re-run 'clawctl agent configure'.")

    hostname = host_record.get("hostname")
    if not isinstance(hostname, str) or not hostname.strip():
        raise ValueError("Host primary address not found.")

    # ethos web-api (port 3000) serves /v1/chat/completions + the dashboard.
    # Establish an SSH tunnel so the local clawctl process can reach it.
    from clawrium.core.web_ui_tunnel import TunnelError

    agent_key = agent_record.get("agent_name") or agent_record.get("name") or hostname
    try:
        from clawrium.core.web_ui_tunnel import ensure as ensure_tunnel
        local_port = ensure_tunnel(agent_key, owned=True)
    except TunnelError as exc:
        raise ValueError(f"Could not establish SSH tunnel to ethos serve: {exc}") from exc

    instance_key = get_instance_key(hostname, "ethos", agent_record.get("agent_name", ""))
    secrets = get_instance_secrets(instance_key)
    chat_entry = secrets.get("ETHOS_CHAT_TOKEN")
    auth_token = chat_entry.get("value", "") if isinstance(chat_entry, dict) else ""

    # config.chat_model selects the ethos persona (e.g. "engineer", "ethos-default").
    chat_model = config.get("chat_model") or "ethos-default"

    return EthosOpenAIBackend(
        base_url=f"http://127.0.0.1:{local_port}/v1",
        auth_token=auth_token,
        model=chat_model,
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
        raise ValueError("Agent config missing. Re-run 'clawctl agent configure'.")
    api_server = config.get("api_server")
    if not isinstance(api_server, dict):
        raise ValueError(
            "Hermes api_server config missing. Re-run 'clawctl agent configure'."
        )

    port = api_server.get("port")
    if not isinstance(port, int) or port <= 0:
        raise ValueError(
            "Hermes api_server.port missing or invalid. Re-run 'clawctl agent configure'."
        )

    hostname = host_record.get("hostname")
    if not isinstance(hostname, str) or not hostname.strip():
        raise ValueError("Host primary address not found.")

    # Key secrets by host_record["key_id"] (immutable, #448) — `hostname`
    # is the network dial target and may have mutated since install.
    host_key = host_record.get("key_id") or hostname
    instance_key = get_instance_key(host_key, agent_type, agent_name)
    secret_entry = get_instance_secrets(instance_key).get("HERMES_API_SERVER_KEY")
    # `.get("value")` not `["value"]`: a truthy-but-malformed entry (no
    # "value" field) would otherwise raise KeyError and escape the outer
    # `except ValueError` handler, dumping a traceback to the user.
    raw_token = secret_entry.get("value") if secret_entry else None
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise ValueError(
            "HERMES_API_SERVER_KEY missing from secrets.json. "
            f"Re-run 'clawctl agent create {agent_name} --type {agent_type} --host {hostname}' "
            "to regenerate the API key."
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
    # Strip C0/C1 control bytes AND Unicode bidi-formatting + zero-width
    # + line/paragraph-separator codepoints. Uses the shared
    # `_CONTROL_AND_BIDI_RE` so the coverage stays identical to
    # `_sanitize_agent_label` and `chat_hermes._CONTROL_CHARS_RE`.
    # Closes the W-A bypass where a remote-supplied error body can
    # embed RTLO/LRM/LINE-SEP/etc.
    cleaned = _CONTROL_AND_BIDI_RE.sub(" ", str(exc))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # First pass: redact `<scheme> <value>` header forms like
    # `Authorization: Bearer abc-123` and the shorthand `bearer abc-123`.
    # Without this pass, the generic regex below stops after consuming
    # `Bearer` as the "value" and leaves `abc-123` in the clear.
    cleaned = re.sub(
        r"(?i)\b(bearer|basic|digest)\s+([^\s,;]+)",
        r"\1 ***",
        cleaned,
    )
    # Second pass: match keywords that appear *anywhere* inside an identifier
    # (so e.g. `HERMES_API_SERVER_KEY` matches via `KEY`, `api_key` via
    # `key`, `BearerToken` via both `bearer` and `token`). The separator is
    # restricted to `:` or `=` here — a bare-space separator would false-
    # positive on prose like "no secrets here"; bearer/basic/digest header
    # forms with a space separator are handled by the first pass above.
    cleaned = re.sub(
        r"(?i)\b([A-Za-z0-9_]*(?:token|auth|password|key|bearer|secret|apikey|authorization)[A-Za-z0-9_]*)\s*[:=]\s*([^\s,;]+)",
        r"\1=***",
        cleaned,
    )
    # Bearer scheme uses a space separator and is not covered by the
    # token=/auth= pattern above. Mask the credential, keep the scheme word.
    cleaned = re.sub(r"(?i)\bbearer\s+(\S+)", "Bearer ***", cleaned)
    # api_key / api-key / apikey variants with = or : separator.
    cleaned = re.sub(
        r"(?i)\bapi[_-]?key\s*[:=]\s*([^\s,;]+)",
        "api_key=***",
        cleaned,
    )
    return cleaned[:max_len]
