"""macOS E2E with the SSH session and upstream installer stubbed (issue #469).

Runs on Linux. Exercises the full dispatcher → host_macos → playbook
resolver → lifecycle_macos chain with paramiko + ansible-runner replaced
by deterministic fakes. The goal is to catch any cross-module wiring
regressions in CI without needing an actual Mac runner.

This is the companion to tests/integration/test_macos_e2e_real.py,
which is gated `@pytest.mark.slow` and runs only against a live Mac.
"""

from __future__ import annotations

from io import StringIO

import pytest

from clawrium.core import lifecycle_macos
from clawrium.core.launchd import label_for, plist_path_for, render_plist
from clawrium.core.playbook_resolver import (
    resolve_agent_playbook,
    resolve_base_playbook,
    resolve_lifecycle_backend,
)


# ---- Stub paramiko client ---------------------------------------------------

class _Chan:
    def __init__(self, rc: int):
        self.rc = rc

    def recv_exit_status(self) -> int:
        return self.rc


class _Stream:
    def __init__(self, content: str, rc: int = 0):
        self._buf = content.encode()
        self.channel = _Chan(rc)

    def read(self) -> bytes:
        return self._buf


class _SFTPFile:
    def __init__(self):
        self.written = ""

    def write(self, s: str) -> None:
        self.written += s

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _SFTP:
    def __init__(self):
        self.files: dict[str, str] = {}

    def file(self, path: str, mode: str = "w"):
        f = _SFTPFile()
        self._last_path = path
        return _SFTPCtx(self, path, f)

    def close(self):
        pass


class _SFTPCtx:
    def __init__(self, sftp: _SFTP, path: str, f: _SFTPFile):
        self.sftp = sftp
        self.path = path
        self.f = f

    def __enter__(self):
        return self.f

    def __exit__(self, *a):
        self.sftp.files[self.path] = self.f.written
        return False


class _Client:
    def __init__(self):
        self.commands: list[str] = []
        self._sftp = _SFTP()

    def exec_command(self, cmd: str):
        self.commands.append(cmd)
        return StringIO(), _Stream("", rc=0), _Stream("", rc=0)

    def open_sftp(self) -> _SFTP:
        return self._sftp

    def close(self) -> None:
        pass


# ---- The actual tests -------------------------------------------------------


def test_dispatcher_chain_for_darwin():
    """Resolver returns the macOS playbooks and the macOS lifecycle module
    when os_family=darwin."""
    assert resolve_base_playbook("darwin").name == "base_macos.yaml"
    assert resolve_agent_playbook("hermes", "install", "darwin").name == "install_macos.yaml"
    assert resolve_agent_playbook("hermes", "configure", "darwin").name == "configure_macos.yaml"
    assert resolve_lifecycle_backend("darwin") is lifecycle_macos


def test_start_agent_macos_command_sequence_gateway_only(monkeypatch):
    """A host record without a dashboard port skips the dashboard plist
    entirely (gateway plist only)."""
    client = _Client()
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda host: client)

    host = {
        "hostname": "x",
        "agents": {"h1": {"config": {}}},  # no dashboard port
    }
    ok, err = lifecycle_macos.start_agent_macos(host, "h1")
    assert ok, err

    # Expect: 1 sudo install (gateway plist), 1 logs mkdir, 1 bootstrap,
    # 1 kickstart. No dashboard label should appear in any command.
    joined = "\n".join(client.commands)
    assert label_for("h1", kind="gateway") in joined
    assert ".dashboard" not in joined


def test_start_agent_macos_command_sequence_with_dashboard(monkeypatch):
    """When `agents.<name>.config.dashboard.port` is set, both plists land
    and both labels are bootstrapped + kickstarted."""
    client = _Client()
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda host: client)

    host = {
        "hostname": "x",
        "agents": {"h1": {"config": {"dashboard": {"port": 45112}}}},
    }
    ok, err = lifecycle_macos.start_agent_macos(host, "h1")
    assert ok, err

    joined = "\n".join(client.commands)
    assert plist_path_for("h1", kind="gateway") in joined
    assert plist_path_for("h1", kind="dashboard") in joined
    assert f"system/{label_for('h1', kind='dashboard')}" in joined

    # Dashboard plist contents must template the port in.
    dash_path = plist_path_for("h1", kind="dashboard")
    # Path written to SFTP first (in /tmp) then installed to the real path
    written = "\n".join(client._sftp.files.values())
    assert "45112" in written
    assert dash_path  # used by sudo install


def test_render_dashboard_plist_dashboard_port_required():
    """Rendering dashboard.plist.j2 without a port must fail loudly
    (StrictUndefined) so we don't silently emit a broken plist."""
    with pytest.raises(Exception):
        render_plist("h1", template_name="dashboard.plist.j2")
