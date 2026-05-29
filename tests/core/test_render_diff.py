"""Direct unit coverage for `core/render_diff.py` (ATX iter-1 B3).

`tests/cli/clawctl/agent/test_sync_diff.py` covers the CLI integration;
this file pins the data-layer contracts: path construction across OS
families, the missing-SSH-key failure mode, empty-bundle behavior,
and multi-file iteration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawrium.core.render_diff import (
    FileDiff,
    RemoteReadError,
    diff_files,
    remote_path_for,
)


def test_remote_path_for_linux() -> None:
    assert remote_path_for("linux", "alice", ".hermes/.env") == "/home/alice/.hermes/.env"


def test_remote_path_for_darwin() -> None:
    assert remote_path_for("darwin", "alice", ".hermes/.env") == "/Users/alice/.hermes/.env"


def test_remote_path_for_defaults_to_linux_when_os_family_blank() -> None:
    assert remote_path_for("", "alice", ".hermes/.env") == "/home/alice/.hermes/.env"


def test_remote_path_for_strips_leading_slash_on_relative_input() -> None:
    """A registry-supplied path like `/relative/from/home` must not
    produce `/home/alice//relative/...` or escape the home root."""
    assert (
        remote_path_for("linux", "alice", "/sub/path/file")
        == "/home/alice/sub/path/file"
    )


def test_diff_files_missing_ssh_key_raises(monkeypatch) -> None:
    from clawrium.core import render_diff

    monkeypatch.setattr(render_diff, "get_host_private_key", lambda k: None)
    host = {"key_id": "10.0.0.1", "hostname": "10.0.0.1"}
    with pytest.raises(RuntimeError, match="no SSH key"):
        diff_files(host=host, agent_name="alice", rendered_files={".env": "x"})


def test_diff_files_empty_rendered_returns_empty(monkeypatch) -> None:
    from clawrium.core import render_diff

    monkeypatch.setattr(render_diff, "get_host_private_key", lambda k: Path("/dev/null"))
    out = diff_files(
        host={"key_id": "h", "hostname": "h"},
        agent_name="alice",
        rendered_files={},
    )
    assert out == []


def test_diff_files_two_file_bundle_iterates_both(monkeypatch) -> None:
    from clawrium.core import render_diff

    monkeypatch.setattr(render_diff, "get_host_private_key", lambda k: Path("/dev/null"))

    calls: list[str] = []

    def fake_reader(**kwargs):
        calls.append(kwargs["remote_path"])
        return True, "remote-body\n"

    out = diff_files(
        host={
            "key_id": "h",
            "hostname": "h",
            "os_family": "linux",
            "user": "xclm",
            "port": 22,
        },
        agent_name="alice",
        rendered_files={
            ".hermes/.env": "remote-body\n",  # identical → no diff
            ".hermes/config.yaml": "rendered\n",  # differs → diff
        },
        reader=fake_reader,
    )
    assert calls == [
        "/home/alice/.hermes/.env",
        "/home/alice/.hermes/config.yaml",
    ]
    assert len(out) == 2
    assert out[0].unified_diff == ""
    assert "rendered" in out[1].unified_diff


def test_diff_files_propagates_remote_read_error(monkeypatch) -> None:
    """ATX iter-1 B4: sudo-fail must not silently masquerade as missing."""
    from clawrium.core import render_diff

    monkeypatch.setattr(render_diff, "get_host_private_key", lambda k: Path("/dev/null"))

    def fake_reader(**kwargs):
        raise RemoteReadError("sudo -n unavailable on h")

    with pytest.raises(RemoteReadError, match="sudo"):
        diff_files(
            host={"key_id": "h", "hostname": "h"},
            agent_name="alice",
            rendered_files={".env": "x"},
            reader=fake_reader,
        )


class _FakeChannel:
    def __init__(self, exit_status: int) -> None:
        self._exit = exit_status

    def recv_exit_status(self) -> int:
        return self._exit


class _FakeStream:
    def __init__(self, body: bytes, exit_status: int) -> None:
        self._body = body
        self.channel = _FakeChannel(exit_status)

    def read(self) -> bytes:
        return self._body


class _FakeSSHClient:
    """Minimal paramiko stand-in for `read_remote_file` tests.

    Each test configures `_responses` as a list of `(stdout_body,
    stderr_body, exit_status)` triples returned in order by
    `exec_command`. Matches the production code's two-call probe.
    """

    def __init__(self, responses: list[tuple[bytes, bytes, int]]) -> None:
        self._responses = responses
        self._idx = 0
        self.connect_kwargs: dict | None = None

    def load_system_host_keys(self) -> None:
        pass

    def set_missing_host_key_policy(self, *_a, **_kw) -> None:
        pass

    def connect(self, **kwargs) -> None:
        self.connect_kwargs = kwargs

    def exec_command(self, cmd, timeout=None):
        body, err, code = self._responses[self._idx]
        self._idx += 1
        return None, _FakeStream(body, code), _FakeStream(err, code)

    def close(self) -> None:
        pass


def test_read_remote_file_missing_returns_false_empty(monkeypatch) -> None:
    """File absent: `test -e` exits 1 with no stderr → `(False, '')`."""
    from clawrium.core import render_diff

    fake = _FakeSSHClient(responses=[(b"", b"", 1)])
    monkeypatch.setattr(render_diff.paramiko, "SSHClient", lambda: fake)

    present, body = render_diff.read_remote_file(
        hostname="h",
        port=22,
        user="xclm",
        key_filename="/dev/null",
        remote_path="/home/x/.env",
    )
    assert present is False
    assert body == ""


def test_read_remote_file_password_sudo_raises(monkeypatch) -> None:
    """ATX iter-1 B4 — sudo password prompt surfaces as RemoteReadError."""
    from clawrium.core import render_diff

    stderr = b"sudo: a password is required\n"
    fake = _FakeSSHClient(responses=[(b"", stderr, 1)])
    monkeypatch.setattr(render_diff.paramiko, "SSHClient", lambda: fake)

    with pytest.raises(render_diff.RemoteReadError, match="sudo -n unavailable"):
        render_diff.read_remote_file(
            hostname="h",
            port=22,
            user="xclm",
            key_filename="/dev/null",
            remote_path="/home/x/.env",
        )


def test_read_remote_file_non_password_sudo_failure_raises(monkeypatch) -> None:
    """ATX iter-2 W14 — non-password sudo refusals (NOPASSWD missing,
    no-tty, locale-translated) must also raise, not silently return
    '(False, '')'. Anchoring on 'password' was the iter-1 gap."""
    from clawrium.core import render_diff

    stderr = b"Sorry, user xclm is not allowed to execute '/bin/cat /home/x/.env' as root\n"
    fake = _FakeSSHClient(responses=[(b"", stderr, 1)])
    monkeypatch.setattr(render_diff.paramiko, "SSHClient", lambda: fake)

    with pytest.raises(render_diff.RemoteReadError, match="not allowed"):
        render_diff.read_remote_file(
            hostname="h",
            port=22,
            user="xclm",
            key_filename="/dev/null",
            remote_path="/home/x/.env",
        )


def test_read_remote_file_present_returns_body(monkeypatch) -> None:
    """File present: probe exits 0 → second `cat` call returns body."""
    from clawrium.core import render_diff

    fake = _FakeSSHClient(
        responses=[
            (b"", b"", 0),  # test -e
            (b"hello\n", b"", 0),  # cat
        ]
    )
    monkeypatch.setattr(render_diff.paramiko, "SSHClient", lambda: fake)

    present, body = render_diff.read_remote_file(
        hostname="h",
        port=22,
        user="xclm",
        key_filename="/dev/null",
        remote_path="/home/x/.env",
    )
    assert present is True
    assert body == "hello\n"


def test_read_remote_file_cat_exit_nonzero_raises(monkeypatch) -> None:
    """`test -e` succeeds but `cat` fails (e.g. permission flip mid-read)."""
    from clawrium.core import render_diff

    fake = _FakeSSHClient(
        responses=[
            (b"", b"", 0),
            (b"", b"cat: permission denied\n", 13),
        ]
    )
    monkeypatch.setattr(render_diff.paramiko, "SSHClient", lambda: fake)

    with pytest.raises(render_diff.RemoteReadError, match="sudo cat"):
        render_diff.read_remote_file(
            hostname="h",
            port=22,
            user="xclm",
            key_filename="/dev/null",
            remote_path="/home/x/.env",
        )


def test_file_diff_repr_hides_secret_bodies() -> None:
    """ATX iter-1 W5: repr() must not leak plaintext secrets."""
    d = FileDiff(
        path=".env",
        remote_path="/home/x/.env",
        remote_present=True,
        remote_body="OPENROUTER_API_KEY=plain-secret",
        rendered_body="OPENROUTER_API_KEY=new-secret",
        unified_diff="-OPENROUTER_API_KEY=plain-secret\n+OPENROUTER_API_KEY=new-secret\n",
    )
    rep = repr(d)
    assert "plain-secret" not in rep
    assert "new-secret" not in rep
    # Non-secret structural fields must still appear.
    assert ".env" in rep
    assert "remote_present=True" in rep
