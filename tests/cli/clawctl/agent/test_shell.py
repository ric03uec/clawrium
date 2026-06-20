"""Tests for `clawctl agent shell`.

Mocks `cli.clawctl.agent.shell.run_agent_shell` (the CLI's import seam)
to keep the suite hermetic. Per the plan, every CLI bullet uses
exact-args assertions (`assert_called_once_with(...)`) — weaker
`.assert_called()` shapes would pass even if the timeout was silently
zeroed in the CLI layer.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import shell as shell_module

runner = CliRunner()


@pytest.fixture
def mock_run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace `run_agent_shell` with a MagicMock returning ("","",0)."""
    m = MagicMock(return_value=("", "", 0))
    monkeypatch.setattr(shell_module, "run_agent_shell", m)
    return m


# ----- C1: no command provided ---------------------------------------


def test_C1_no_command_provided(fleet_dir, stdin_not_tty, mock_run):
    result = runner.invoke(app, ["agent", "shell", "wise-hypatia"])
    assert result.exit_code == 2
    assert "no command provided" in result.output
    mock_run.assert_not_called()


# ----- C2: basic passthrough -----------------------------------------


def test_C2_basic_passthrough_exact_kwargs(fleet_dir, stdin_not_tty, mock_run):
    result = runner.invoke(
        app, ["agent", "shell", "wise-hypatia", "--", "ls", "-la"]
    )
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once_with(
        hostname="10.0.0.1",
        agent_name="wise-hypatia",
        cmd_argv=["ls", "-la"],
        timeout=120,
    )


# ----- C3: --timeout 600 (raw passthrough) ---------------------------


def test_C3_timeout_600_exact_kwarg(fleet_dir, stdin_not_tty, mock_run):
    result = runner.invoke(
        app,
        ["agent", "shell", "wise-hypatia", "--timeout", "600", "--", "make", "test"],
    )
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once_with(
        hostname="10.0.0.1",
        agent_name="wise-hypatia",
        cmd_argv=["make", "test"],
        timeout=600,
    )


# ----- C4: --timeout 0 — CLI passes raw value through ---------------


def test_C4_timeout_zero_is_not_clamped_at_cli(fleet_dir, stdin_not_tty, mock_run):
    """Clamping lives in core, NOT CLI. CLI passes 0 through unmodified."""
    result = runner.invoke(
        app,
        ["agent", "shell", "wise-hypatia", "--timeout", "0", "--", "x"],
    )
    assert result.exit_code == 0, result.output
    _args, kwargs = mock_run.call_args
    assert kwargs["timeout"] == 0


# ----- C5: --timeout 9999 — CLI passes raw value through ------------


def test_C5_timeout_9999_is_not_clamped_at_cli(fleet_dir, stdin_not_tty, mock_run):
    result = runner.invoke(
        app,
        ["agent", "shell", "wise-hypatia", "--timeout", "9999", "--", "x"],
    )
    assert result.exit_code == 0, result.output
    _args, kwargs = mock_run.call_args
    assert kwargs["timeout"] == 9999


# ----- C6: --timeout -1 rejected by Typer callback ------------------


def test_C6_negative_timeout_rejected_before_core(fleet_dir, stdin_not_tty, mock_run):
    result = runner.invoke(
        app,
        ["agent", "shell", "wise-hypatia", "--timeout", "-1", "--", "x"],
    )
    assert result.exit_code == 2
    assert "--timeout must be >= 0" in result.output
    mock_run.assert_not_called()


# ----- C7: stdout passthrough sanitization -------------------------


def test_C7_stdout_passthrough_via_sanitize(
    fleet_dir, stdin_not_tty, mock_run, monkeypatch
):
    mock_run.return_value = ("hello\n", "", 0)
    sanitize_spy = MagicMock(side_effect=lambda s: s)
    monkeypatch.setattr(shell_module, "sanitize_passthrough", sanitize_spy)
    result = runner.invoke(
        app, ["agent", "shell", "wise-hypatia", "--", "x"]
    )
    assert result.exit_code == 0, result.output
    assert "hello" in result.output
    sanitize_spy.assert_called_once_with("hello\n")


# ----- C8: stderr passthrough + nonzero exit -----------------------


def test_C8_stderr_passthrough_and_nonzero_exit(fleet_dir, stdin_not_tty, mock_run):
    mock_run.return_value = ("", "oops\n", 1)
    result = runner.invoke(
        app, ["agent", "shell", "wise-hypatia", "--", "x"]
    )
    assert result.exit_code == 1
    assert "oops" in result.output


# ----- C9: exit-code propagation: success --------------------------


def test_C9_exit_code_zero(fleet_dir, stdin_not_tty, mock_run):
    mock_run.return_value = ("", "", 0)
    result = runner.invoke(
        app, ["agent", "shell", "wise-hypatia", "--", "x"]
    )
    assert result.exit_code == 0


# ----- C10: exit-code 124 timeout friendly message -----------------


def test_C10_exit_code_124_timeout_message(fleet_dir, stdin_not_tty, mock_run):
    mock_run.return_value = ("", "remote command timed out after 5s\n", 124)
    result = runner.invoke(
        app,
        ["agent", "shell", "wise-hypatia", "--timeout", "5", "--", "sleep", "30"],
    )
    assert result.exit_code == 124
    assert "timed out after 5s" in result.output


# ----- C11: exit-code 127 command not found ------------------------


def test_C11_exit_code_127_not_found(fleet_dir, stdin_not_tty, mock_run):
    mock_run.return_value = (
        "",
        "/bin/bash: line 1: this-bin-does-not-exist: command not found\n",
        127,
    )
    result = runner.invoke(
        app,
        ["agent", "shell", "wise-hypatia", "--", "this-bin-does-not-exist"],
    )
    assert result.exit_code == 127


# ----- C12: agent not found ---------------------------------------


def test_C12_agent_not_found(fleet_dir, stdin_not_tty, mock_run):
    result = runner.invoke(
        app, ["agent", "shell", "does-not-exist", "--", "ls"]
    )
    assert result.exit_code != 0
    assert "does-not-exist" in result.output
    assert "not found" in result.output
    mock_run.assert_not_called()


# ----- C13: CLI-layer agent-name regex rejection ------------------


@pytest.mark.parametrize("bad_name", ["FOO", "agent name", "../etc", ""])
def test_C13_cli_layer_regex_rejection(
    fleet_dir, stdin_not_tty, mock_run, bad_name
):
    args = ["agent", "shell"]
    if bad_name:
        args += [bad_name, "--", "ls"]
    else:
        # Empty string: Typer treats it as the positional value.
        args += ["", "--", "ls"]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    mock_run.assert_not_called()


# ----- C14: --help shows the docstring ----------------------------


def test_C14_help_shows_non_interactive_notice(fleet_dir, mock_run):
    result = runner.invoke(app, ["agent", "shell", "--help"])
    assert result.exit_code == 0
    assert "NON-INTERACTIVE ONLY" in result.output
    assert "LINUX HOSTS ONLY" in result.output
    mock_run.assert_not_called()


# ----- W5: AgentShellError from core surfaces as exit 2 ------------


def test_W5_agent_shell_error_surfaces_exit_2(
    fleet_dir, stdin_not_tty, monkeypatch
):
    from clawrium.core.agent_shell import AgentShellError
    from clawrium.cli.clawctl.agent import shell as shell_module

    def boom(**kw):
        raise AgentShellError("boom from core")

    monkeypatch.setattr(shell_module, "run_agent_shell", boom)
    result = runner.invoke(
        app, ["agent", "shell", "wise-hypatia", "--", "x"]
    )
    assert result.exit_code == 2
    assert "boom from core" in result.output


# ----- W5b: claw_record.agent_name takes precedence over typed key --


def test_W5b_agent_name_precedence_record_over_typed_key(
    fleet_dir, stdin_not_tty, mock_run
):
    """If `claw_record.agent_name` differs from the typed key, the unix
    user passed to core must be the record's `agent_name` (the canonical
    on-host user). This is the exact class of bug that bit exec earlier.

    The fleet fixture seeds `agents["openclaw"] = {agent_name: "wise-hypatia"}`,
    so typing `wise-hypatia` resolves to the record, and `agent_name`
    passed to core must be `"wise-hypatia"` (the record), not
    `"openclaw"` (the dict key).
    """
    result = runner.invoke(
        app, ["agent", "shell", "wise-hypatia", "--", "x"]
    )
    assert result.exit_code == 0, result.output
    _args, kwargs = mock_run.call_args
    assert kwargs["agent_name"] == "wise-hypatia"


# ----- S5: agent_name regex identical between CLI and core ---------


def test_S5_agent_name_regex_drift_guard():
    from clawrium.cli.clawctl.agent.shell import _AGENT_NAME_RE as CLI_RE
    from clawrium.core.agent_shell import _AGENT_NAME_RE as CORE_RE

    assert CLI_RE.pattern == CORE_RE.pattern


# ----- iter3 W5: CLI denylist seam exits 2 before reaching core ----


def test_iter3_W5_cli_reserved_unix_name_seam(fleet_dir, stdin_not_tty, mock_run, monkeypatch):
    """A tampered hosts.json resolving `agent_name` to a system account
    (e.g. `daemon`) must be refused at the CLI seam — `run_agent_shell`
    is never called and the operator sees a clear exit-2 message."""
    from clawrium.cli.clawctl.agent import shell as shell_module

    def fake_resolve(_name):
        return (
            {"hostname": "10.0.0.1"},
            "openclaw",
            {"type": "openclaw", "agent_name": "daemon"},
        )

    monkeypatch.setattr(shell_module, "safe_resolve_agent", fake_resolve)
    result = runner.invoke(app, ["agent", "shell", "anyname", "--", "ls"])
    assert result.exit_code == 2
    assert "reserved system user" in result.output
    mock_run.assert_not_called()


# ----- iter3 W7: rc=255 routes through emit_error ------------------


def test_iter3_W7_rc_255_via_emit_error(fleet_dir, stdin_not_tty, mock_run):
    """Infrastructure failure (rc=255 with empty stdout) must surface
    with canonical `Error:`/`Hint:` framing, not a raw stderr dump
    that's indistinguishable from a remote command's own diagnostics.
    """
    mock_run.return_value = ("", "host 'foo' not found", 255)
    result = runner.invoke(
        app, ["agent", "shell", "wise-hypatia", "--", "ls"]
    )
    assert result.exit_code == 255
    assert "Error:" in result.output
    assert "host 'foo' not found" in result.output
