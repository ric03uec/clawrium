"""Tests for `clawctl agent memory get|describe|edit|delete`.

The underlying `clawrium.core.memory` API dispatches Ansible playbooks
against a real host — we monkey-patch those primitives so the tests
exercise the CLI plumbing in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import memory as memory_module

runner = CliRunner()


@pytest.fixture
def memory_stub(monkeypatch: pytest.MonkeyPatch):
    state: dict[str, str] = {"FOO.md": "hello"}

    def fake_supports(claw_type: str) -> bool:
        return True

    def fake_get_info(hostname, agent_name):
        return {
            "workspace_path": "/home/agent/work",
            "total_bytes": sum(len(v) for v in state.values()),
            "files": [
                {
                    "name": name,
                    "exists": True,
                    "size_bytes": len(content),
                    "relative_path": name,
                }
                for name, content in state.items()
            ],
        }

    def fake_read(hostname, agent_name, filename):
        return state.get(filename)

    def fake_write(hostname, agent_name, filename, content):
        state[filename] = content
        return True, None

    def fake_delete(hostname, agent_name, files):
        for f in files:
            state.pop(f, None)
        return True, None

    monkeypatch.setattr(memory_module, "claw_supports_memory", fake_supports)
    monkeypatch.setattr(memory_module, "get_memory_info", fake_get_info)
    monkeypatch.setattr(memory_module, "read_memory_file", fake_read)
    monkeypatch.setattr(memory_module, "write_memory_file", fake_write)
    monkeypatch.setattr(memory_module, "delete_memory_files", fake_delete)
    return state


def test_get_lists_files(fleet_dir, stdin_not_tty, memory_stub) -> None:
    result = runner.invoke(app, ["agent", "memory", "get", "--agent", "wise-hypatia"])
    assert result.exit_code == 0, result.output
    assert "FOO.md" in result.output


def test_get_with_file_prints_content(fleet_dir, stdin_not_tty, memory_stub) -> None:
    result = runner.invoke(
        app,
        ["agent", "memory", "get", "--agent", "wise-hypatia", "--file", "FOO.md"],
    )
    assert result.exit_code == 0
    assert "hello" in result.output


def test_describe_file_metadata(fleet_dir, stdin_not_tty, memory_stub) -> None:
    result = runner.invoke(
        app,
        ["agent", "memory", "describe", "FOO.md", "--agent", "wise-hypatia"],
    )
    assert result.exit_code == 0
    assert "FOO.md" in result.output


def test_edit_with_content_flag(fleet_dir, stdin_not_tty, memory_stub) -> None:
    result = runner.invoke(
        app,
        [
            "agent",
            "memory",
            "edit",
            "FOO.md",
            "--agent",
            "wise-hypatia",
            "--content",
            "new body",
        ],
    )
    assert result.exit_code == 0, result.output
    assert memory_stub["FOO.md"] == "new body"


def test_edit_with_from_file(
    fleet_dir, stdin_not_tty, memory_stub, tmp_path: Path
) -> None:
    src = tmp_path / "in.txt"
    src.write_text("loaded body")
    result = runner.invoke(
        app,
        [
            "agent",
            "memory",
            "edit",
            "FOO.md",
            "--agent",
            "wise-hypatia",
            "--from-file",
            str(src),
        ],
    )
    assert result.exit_code == 0
    assert memory_stub["FOO.md"] == "loaded body"


def test_edit_requires_content_or_from_file(
    fleet_dir, stdin_not_tty, memory_stub
) -> None:
    result = runner.invoke(
        app, ["agent", "memory", "edit", "FOO.md", "--agent", "wise-hypatia"]
    )
    assert result.exit_code != 0


def test_edit_rejects_both_sources(
    fleet_dir, stdin_not_tty, memory_stub, tmp_path: Path
) -> None:
    src = tmp_path / "in.txt"
    src.write_text("loaded body")
    result = runner.invoke(
        app,
        [
            "agent",
            "memory",
            "edit",
            "FOO.md",
            "--agent",
            "wise-hypatia",
            "--content",
            "x",
            "--from-file",
            str(src),
        ],
    )
    assert result.exit_code != 0


def test_delete_requires_yes(fleet_dir, stdin_not_tty, memory_stub) -> None:
    result = runner.invoke(
        app,
        ["agent", "memory", "delete", "FOO.md", "--agent", "wise-hypatia"],
    )
    assert result.exit_code != 0


def test_delete_with_yes(fleet_dir, stdin_not_tty, memory_stub) -> None:
    result = runner.invoke(
        app,
        [
            "agent",
            "memory",
            "delete",
            "FOO.md",
            "--agent",
            "wise-hypatia",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert "FOO.md" not in memory_stub
