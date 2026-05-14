"""Hardening tests for the GUI logs endpoint helpers.

These tests guard the B7/B8 fixes: hostname/agent input validation, the `--`
SSH argv separator, and the constant generic error message. They run as pure
Python unit tests against the helpers — no FastAPI TestClient needed.
"""

import subprocess

import pytest

from clawrium.gui.routes.agents import (
    _LOGS_FETCH_GENERIC_ERROR,
    _LogsFetchError,
    _build_journalctl_ssh_cmd,
    _fetch_logs_via_ssh,
)


class TestBuildJournalctlCmd:
    def test_rejects_option_injection_hostname(self):
        with pytest.raises(_LogsFetchError) as exc:
            _build_journalctl_ssh_cmd(
                "-oProxyCommand=evil", "svc", 100, user_scope=True
            )
        assert str(exc.value) == _LOGS_FETCH_GENERIC_ERROR

    def test_rejects_empty_hostname(self):
        with pytest.raises(_LogsFetchError):
            _build_journalctl_ssh_cmd("", "svc", 100, user_scope=True)

    def test_rejects_hostname_with_shell_metachars(self):
        with pytest.raises(_LogsFetchError):
            _build_journalctl_ssh_cmd("box;rm -rf /", "svc", 100, user_scope=True)

    def test_includes_double_dash_separator_before_hostname(self):
        cmd = _build_journalctl_ssh_cmd("mybox", "svc", 50, user_scope=True)
        assert "--" in cmd
        # `--` must come immediately before the hostname so a future regression
        # in the hostname regex can't slip an SSH option through.
        dash_index = cmd.index("--")
        assert cmd[dash_index + 1] == "mybox"

    def test_includes_strict_host_key_checking_yes(self):
        cmd = _build_journalctl_ssh_cmd("mybox", "svc", 50, user_scope=True)
        assert "StrictHostKeyChecking=yes" in cmd

    def test_includes_batch_mode_yes(self):
        cmd = _build_journalctl_ssh_cmd("mybox", "svc", 50, user_scope=True)
        assert "BatchMode=yes" in cmd

    def test_service_name_is_shell_quoted_in_remote_command(self):
        cmd = _build_journalctl_ssh_cmd("mybox", "weird name", 50, user_scope=True)
        # Last arg is the remote command string; verify shlex.quote applied.
        remote = cmd[-1]
        assert "'weird name'" in remote


class TestFetchLogsViaSshValidation:
    def test_rejects_agent_type_with_control_char(self, monkeypatch):
        def boom(*a, **kw):
            raise AssertionError("subprocess.run must not be called")

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(_LogsFetchError) as exc:
            _fetch_logs_via_ssh("mybox", "openclaw\x00", "agent1", 50)
        assert str(exc.value) == _LOGS_FETCH_GENERIC_ERROR

    def test_rejects_agent_name_with_path_traversal(self, monkeypatch):
        def boom(*a, **kw):
            raise AssertionError("subprocess.run must not be called")

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(_LogsFetchError):
            _fetch_logs_via_ssh("mybox", "openclaw", "../../etc/passwd", 50)

    def test_rejects_uppercase_agent_name(self, monkeypatch):
        # Regex anchors at `^[a-z]` — uppercase first char must be rejected.
        def boom(*a, **kw):
            raise AssertionError("subprocess.run must not be called")

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(_LogsFetchError):
            _fetch_logs_via_ssh("mybox", "Openclaw", "agent1", 50)


class TestFetchLogsErrorMessageHidesDetails:
    def test_error_message_is_constant_not_stderr(self, monkeypatch):
        """B8: stderr containing a private-key path must never reach the caller."""

        class _Result:
            returncode = 1
            stdout = ""
            stderr = "ssh: connect to host failed; identity file /home/me/.ssh/id_rsa"

        def fake_run(*a, **kw):
            return _Result()

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(_LogsFetchError) as exc:
            _fetch_logs_via_ssh("mybox", "openclaw", "agent1", 50)

        msg = str(exc.value)
        assert msg == _LOGS_FETCH_GENERIC_ERROR
        assert "id_rsa" not in msg
        assert "/home/" not in msg

    def test_timeout_is_collapsed_to_generic(self, monkeypatch):
        def fake_run(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="ssh", timeout=15)

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(_LogsFetchError) as exc:
            _fetch_logs_via_ssh("mybox", "openclaw", "agent1", 50)

        assert str(exc.value) == _LOGS_FETCH_GENERIC_ERROR
