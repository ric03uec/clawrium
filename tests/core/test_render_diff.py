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
