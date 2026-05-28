"""Tests for core/lifecycle_macos.py (issue #469, step 7).

Covers:
  - resolve_lifecycle_backend dispatch.
  - launchctl command shape per operation (assert on the exact strings
    sent to paramiko.exec_command).
  - "already loaded" and "not loaded" tolerance.

E2E (actually invoking launchctl on a Mac) is covered by step 11's
slow nightly suite.
"""

from io import StringIO

import pytest

from clawrium.core import lifecycle_macos
from clawrium.core.launchd import label_for, plist_path_for
from clawrium.core.playbook_resolver import resolve_lifecycle_backend


class _Chan:
    def __init__(self, exit_status: int = 0):
        self.exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self.exit_status


class _Out:
    def __init__(self, content: str = "", exit_status: int = 0):
        self._content = content.encode()
        self.channel = _Chan(exit_status)

    def read(self) -> bytes:
        return self._content


class _FakeClient:
    """Records every exec_command invocation; returns scripted responses."""

    def __init__(self, responses: list[tuple[int, str, str]] | None = None):
        self.commands: list[str] = []
        self._responses = list(responses or [])

    def exec_command(self, cmd):  # noqa: ANN001
        self.commands.append(cmd)
        if self._responses:
            rc, out, err = self._responses.pop(0)
        else:
            rc, out, err = 0, "", ""
        return StringIO(), _Out(out, rc), _Out(err, rc)

    # Methods needed by paramiko-compatible context use; lifecycle_macos
    # calls .close() in a finally block. SFTP is not exercised in these
    # tests (write_plist is tested separately in test_launchd).
    def close(self):
        pass

    def open_sftp(self):  # used only by install_service via write_plist
        raise RuntimeError("SFTP not exercised in this unit test")


def test_resolve_lifecycle_backend_linux():
    backend = resolve_lifecycle_backend("linux")
    assert backend.__name__ == "clawrium.core.lifecycle"


def test_resolve_lifecycle_backend_darwin():
    backend = resolve_lifecycle_backend("darwin")
    assert backend is lifecycle_macos


def test_resolve_lifecycle_backend_unknown_raises():
    with pytest.raises(ValueError, match="unsupported"):
        resolve_lifecycle_backend("windows")


def test_bootstrap_command_shape():
    client = _FakeClient(responses=[(0, "", "")])
    lifecycle_macos._bootstrap(client, "h1")
    assert client.commands == [
        f"sudo launchctl bootstrap system {plist_path_for('h1')}"
    ]


def test_bootout_command_shape():
    client = _FakeClient(responses=[(0, "", "")])
    lifecycle_macos._bootout(client, "h1")
    assert client.commands == [
        f"sudo launchctl bootout system/{label_for('h1')}"
    ]


def test_kickstart_command_shape_kill_false():
    client = _FakeClient(responses=[(0, "", "")])
    lifecycle_macos._kickstart(client, "h1", kill=False)
    assert client.commands == [
        f"sudo launchctl kickstart system/{label_for('h1')}"
    ]


def test_kickstart_command_shape_kill_true():
    client = _FakeClient(responses=[(0, "", "")])
    lifecycle_macos._kickstart(client, "h1", kill=True)
    assert client.commands == [
        f"sudo launchctl kickstart -k system/{label_for('h1')}"
    ]


def test_stop_tolerates_not_loaded(monkeypatch):
    """`launchctl bootout` against an absent unit must return success."""
    client = _FakeClient(
        responses=[(113, "", "Could not find service\n")]
    )
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda host: client)

    ok, err = lifecycle_macos.stop_agent_macos({"hostname": "x"}, "h1")
    assert ok is True
    assert err is None


def test_stop_reports_real_error():
    """Non-not-loaded errors must surface."""

    class _C(_FakeClient):
        pass

    client = _C(responses=[(2, "", "permission denied\n")])
    import clawrium.core.lifecycle_macos as lm

    original_ssh = lm._ssh
    lm._ssh = lambda host: client
    try:
        ok, err = lm.stop_agent_macos({"hostname": "x"}, "h1")
    finally:
        lm._ssh = original_ssh

    assert ok is False
    assert "permission denied" in (err or "")
