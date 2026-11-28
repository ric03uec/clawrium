"""Command-discovery regression tests for the #1071 removal set.

These lock in exactly which top-level `clawctl` and `clawctl agent`
verbs are registered after the removal of chat / memory / exec /
audit / secret (per-agent) and apply / diff / audit / doctor (top-
level). They complement the per-verb help-text tests and catch
accidental re-registration of a removed command.
"""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app


runner = CliRunner()


# Top-level clawctl verbs that must be present post-#1071.
RETAINED_ROOT_COMMANDS = {
    "version",
    "completion",
    "tui",
    "delete",  # `clawctl delete -f` declarative-fleet teardown
    "service",
    "server",
    "host",
    "agent",
    "provider",
    "channel",
    "integration",
}

# Top-level clawctl groups / verbs removed by #1071.
REMOVED_ROOT_COMMANDS = {
    "apply",
    "diff",
    "audit",
    "doctor",
}

# Per-agent verbs that must be present post-#1071.
RETAINED_AGENT_COMMANDS = {
    "create",
    "get",
    "describe",
    "delete",
    "edit",
    "configure",
    "start",
    "stop",
    "status",
    "restart",
    "sync",
    "upgrade",
    "doctor",
    "logs",
    "open",
    "port-forward",
    "shell",
    "provider",
    "channel",
    "integration",
    "registry",
}

# Per-agent verbs removed by #1071.
REMOVED_AGENT_COMMANDS = {
    "chat",
    "memory",
    "exec",
    "audit",
    "secret",
}


def _normalize_help(text: str) -> str:
    return " ".join(text.split())


def test_clawctl_root_help_lists_retained_commands_and_omits_removed():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    normalized = _normalize_help(result.output)
    for cmd in RETAINED_ROOT_COMMANDS:
        assert f" {cmd} " in f" {normalized} ", (
            f"root command '{cmd}' should be registered"
        )
    for cmd in REMOVED_ROOT_COMMANDS:
        assert f" {cmd} " not in f" {normalized} ", (
            f"root command '{cmd}' must not be re-registered after #1071"
        )


def test_clawctl_agent_help_lists_retained_verbs_and_omits_removed():
    result = runner.invoke(app, ["agent", "--help"])
    assert result.exit_code == 0
    normalized = _normalize_help(result.output)
    for verb in RETAINED_AGENT_COMMANDS:
        assert f" {verb} " in f" {normalized} ", (
            f"agent verb '{verb}' should be registered"
        )
    for verb in REMOVED_AGENT_COMMANDS:
        assert f" {verb} " not in f" {normalized} ", (
            f"agent verb '{verb}' must not be re-registered after #1071"
        )


def test_removed_root_commands_are_unknown():
    for cmd in REMOVED_ROOT_COMMANDS:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code != 0, (
            f"'clawctl {cmd}' should be unknown after #1071"
        )
        assert "No such command" in result.output, (
            f"'clawctl {cmd}' did not surface a No-such-command error: {result.output!r}"
        )


def test_removed_agent_verbs_are_unknown():
    for verb in REMOVED_AGENT_COMMANDS:
        result = runner.invoke(app, ["agent", verb, "--help"])
        assert result.exit_code != 0, (
            f"'clawctl agent {verb}' should be unknown after #1071"
        )
        assert "No such command" in result.output, (
            f"'clawctl agent {verb}' did not surface a No-such-command error: "
            f"{result.output!r}"
        )
