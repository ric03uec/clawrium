"""`clawctl agent chat <name>` — interactive chat session.

Delegates to the existing `cli/chat.py:chat` implementation. The
`--once` flag opts into single-shot mode: the delegated implementation
skips the REPL, sends the message, prints the reply, and exits. All
transport / auth / protocol errors surface as non-zero exit codes with
the same diagnostics the interactive path uses.
"""

from __future__ import annotations

from typing import Optional

import typer

from clawrium.cli.clawctl.agent._shared import safe_resolve_agent


def chat(
    name: str = typer.Argument(..., help="Agent name."),
    session: str = typer.Option("main", "--session", "-s", help="Gateway session key."),
    timeout: float = typer.Option(
        120.0, "--timeout", min=1.0, help="Response timeout (seconds)."
    ),
    idle_timeout: float = typer.Option(
        300.0, "--idle-timeout", min=0.0, help="Idle timeout (0 disables)."
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
    """Start an interactive chat with an agent."""
    safe_resolve_agent(name)  # validates existence
    from clawrium.cli.chat import chat as _legacy_chat

    _legacy_chat(
        agent_name=name,
        session=session,
        timeout=timeout,
        idle_timeout=idle_timeout,
        once=once,
    )
