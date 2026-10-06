"""Lifecycle capabilities that differ by installed agent type.

Most Clawrium agent types expose a long-running gateway managed by systemd
or launchd. Claude Code and Pi are intentionally different: they are
installed, interactive CLIs and have no daemon to start, stop, restart,
inspect, or tunnel. Keep that distinction in one small, dependency-free module so every
entry point rejects daemon operations before opening SSH or invoking an
agent binary.
"""

from __future__ import annotations


_DAEMONLESS_AGENT_TYPES: frozenset[str] = frozenset({"claude", "pi"})


def has_daemon_lifecycle(agent_type: str) -> bool:
    """Whether ``agent_type`` owns a managed long-running daemon."""
    return agent_type not in _DAEMONLESS_AGENT_TYPES


def lifecycle_not_applicable_message(agent_type: str, operation: str) -> str:
    """Return the shared operator-facing error for a daemonless operation."""
    return (
        f"Agent type '{agent_type}' is an installed CLI and does not run a daemon; "
        f"`clawctl agent {operation}` is not applicable."
    )


def has_completed_install(agent_record: dict) -> bool:
    """Whether an agent record represents a completed installation.

    Statusless records predate lifecycle-state tracking and remain supported.
    Once a record has a status, require the success marker and timestamp so a
    failed or interrupted install is never surfaced as ready.
    """
    status = agent_record.get("status")
    if status is None:
        return True
    return status == "installed" and bool(agent_record.get("installed_at"))


def incomplete_install_message(agent_type: str, operation: str) -> str:
    """Return the shared error when an install-only agent is incomplete."""
    return (
        f"Agent type '{agent_type}' has an incomplete installation; "
        f"`clawctl agent {operation}` cannot run until installation completes."
    )
