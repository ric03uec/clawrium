"""Tests for NemoClaw delegation in the openclaw `start` playbook.

Phase 3 of #11 (#945) deletes the bare host-systemd lifecycle path: a
`clawctl agent start` for openclaw must call `nemoclaw start/status
<sandbox>` and must not rewrite or start an `openclaw-<name>.service`
unit.
"""

from pathlib import Path

import pytest
import yaml


START_PLAYBOOK = (
    Path(__file__).parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "openclaw"
    / "playbooks"
    / "start.yaml"
)


@pytest.fixture(scope="module")
def start_tasks() -> list[dict]:
    play = yaml.safe_load(START_PLAYBOOK.read_text())
    assert isinstance(play, list) and len(play) == 1, "start.yaml must be a single play"
    tasks = play[0].get("tasks", [])
    assert tasks, "start.yaml must declare tasks"
    return tasks


def _task_by_name(tasks: list[dict], name: str) -> dict | None:
    return next((t for t in tasks if t.get("name") == name), None)


def test_start_requires_sandbox_name(start_tasks: list[dict]) -> None:
    assert _task_by_name(start_tasks, "Assert sandbox_name extravar is provided")


def test_start_invokes_nemoclaw_start_then_status(start_tasks: list[dict]) -> None:
    start = _task_by_name(start_tasks, "Start NemoClaw sandbox {{ sandbox_name }}")
    status = _task_by_name(start_tasks, "Verify NemoClaw sandbox {{ sandbox_name }} status")
    assert start is not None
    assert status is not None
    assert start["ansible.builtin.command"]["argv"] == [
        "{{ nemoclaw_binary }}",
        "start",
        "{{ sandbox_name }}",
    ]
    assert status["ansible.builtin.command"]["argv"] == [
        "{{ nemoclaw_binary }}",
        "status",
        "{{ sandbox_name }}",
    ]
    assert start_tasks.index(start) < start_tasks.index(status)


def test_start_playbook_has_no_host_systemd_or_binary_discovery() -> None:
    content = START_PLAYBOOK.read_text()
    forbidden = (
        "ansible.builtin.systemd",
        "systemd:",
        "openclaw_runtime_binary",
        "Sync systemd service file",
        "Start openclaw service",
        "pgrep -u {{ agent_name }} openclaw",
        "ExecStart=",
    )
    for needle in forbidden:
        assert needle not in content
