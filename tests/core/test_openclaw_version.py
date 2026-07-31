"""Unit tests for ``core/openclaw_version`` — the shared openclaw live-version resolver.

Extracted module for issue #754. Exercises the dispatcher and per-OS
implementations with mocked SSH clients so the resolver can be tested
without real SSH access.
"""

from __future__ import annotations

from io import BytesIO

import pytest

from clawrium.core.openclaw_version import (
    parse_semver_tuple,
    _run_openclaw_version_probe,
    get_host_openclaw_version,
)


# ─── Mock helpers ────────────────────────────────────────────────────────────

class _Chan:
    """Minimal paramiko Channel mock."""

    def __init__(self, exit_status: int = 0):
        self.exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self.exit_status


class _Stream:
    """Minimal paramiko stdout/stderr mock."""

    def __init__(self, content: str = "", exit_status: int = 0):
        self._content = content.encode()
        self.channel = _Chan(exit_status)

    def read(self) -> bytes:
        return self._content


class _FakeClient:
    """Fake paramiko.SSHClient that records commands and returns scripted output."""

    def __init__(
        self, version_output: str = "", exit_status: int = 0, stderr: str = ""
    ):
        self.commands: list[str] = []
        self._version_output = version_output
        self._exit_status = exit_status
        self._stderr = stderr

    def exec_command(self, cmd: str, **_kwargs):
        self.commands.append(cmd)
        return BytesIO(), _Stream(self._version_output, self._exit_status), _Stream(
            self._stderr, 0
        )

    def close(self):
        pass


# ─── parse_semver_tuple ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026.6.8", (2026, 6, 8)),
        ("openclaw 2026.6.8", (2026, 6, 8)),
        ("", None),
        ("openclaw (development build)", None),
        ("garbage", None),
    ],
)
def testparse_semver_tuple(raw: str, expected):
    assert parse_semver_tuple(raw) == expected


def testparse_semver_tuple_empty_string():
    """Empty string returns None (no crash)."""
    assert parse_semver_tuple("") is None


# ─── Dispatcher: Linux ──────────────────────────────────────────────────────

def test_dispatcher_linux():
    """Dispatcher selects linux when os_family is 'linux' or ''."""
    for raw_os_family in ("linux", "", "LINUX"):
        client = _FakeClient(version_output="2026.6.8")
        version, _ = get_host_openclaw_version(
            client, "test-agent", os_family=raw_os_family
        )
        assert version == (2026, 6, 8), f"Failed for os_family={raw_os_family!r}"
        assert len(client.commands) == 1
        assert "/home/" in client.commands[0]


# ─── Dispatcher: macOS ──────────────────────────────────────────────────────

def test_dispatcher_darwin():
    """Dispatcher selects macos when os_family is 'darwin'."""
    client = _FakeClient(version_output="2026.6.8")
    version, _ = get_host_openclaw_version(
        client, "test-agent", os_family="darwin"
    )
    assert version == (2026, 6, 8)
    assert len(client.commands) == 1
    assert "/Users/" in client.commands[0]


# ─── Error handling ──────────────────────────────────────────────────────────

def test_probe_returns_none_on_nonzero_exit():
    """When the binary exits non-zero, version is None."""
    client = _FakeClient(version_output="not found", exit_status=1)
    version, _ = get_host_openclaw_version(
        client, "test-agent", os_family="linux"
    )
    assert version is None


def test_probe_handles_unparseable_output():
    """When output doesn't contain X.Y.Z, version is None."""
    client = _FakeClient(version_output="openclaw (development build)")
    version, _ = get_host_openclaw_version(
        client, "test-agent", os_family="linux"
    )
    assert version is None


def test_run_probe_with_stderr():
    """stderr_tail captures trailing stderr output."""

    def _fake_exec(cmd, **kwargs):
        return BytesIO(), _Stream("2026.6.8", 0), _Stream("warning: slow\n", 0)

    client = _FakeClient()
    client.exec_command = _fake_exec
    version, stderr = _run_openclaw_version_probe(client, "fake-cmd", timeout=10)
    assert version == (2026, 6, 8)
    assert "warning" in stderr


def test_run_probe_nonzero_with_stderr():
    """Non-zero exit propagates stderr_tail to caller."""

    def _fake_exec(cmd, **kwargs):
        return BytesIO(), _Stream("", 1), _Stream("bash: not found\n", 0)

    client = _FakeClient()
    client.exec_command = _fake_exec
    version, stderr = _run_openclaw_version_probe(client, "fake-cmd", timeout=10)
    assert version is None
    assert "not found" in stderr
