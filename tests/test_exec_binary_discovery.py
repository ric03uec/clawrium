"""Structural tests for the openclaw `exec` playbook binary discovery.

Mirrors the pattern in `test_start_binary_discovery.py`: parses the
playbook YAML and asserts task names, ordering, and `when:` conditions
that constitute the security gate. A future edit that deletes the
allowlist task or weakens its conditions fails here, even without
running ansible (ATX iter-2 NB1).
"""

from pathlib import Path

import pytest
import yaml


EXEC_PLAYBOOK = (
    Path(__file__).parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "openclaw"
    / "playbooks"
    / "exec.yaml"
)


@pytest.fixture(scope="module")
def exec_tasks() -> list[dict]:
    play = yaml.safe_load(EXEC_PLAYBOOK.read_text())
    assert isinstance(play, list) and len(play) == 1
    tasks = play[0].get("tasks", [])
    assert tasks
    return tasks


def _by_name(tasks: list[dict], name: str) -> dict | None:
    return next((t for t in tasks if t.get("name") == name), None)


def _idx(tasks: list[dict], name: str) -> int:
    return next(i for i, t in enumerate(tasks) if t.get("name") == name)


def test_allowlist_validation_task_present(exec_tasks: list[dict]) -> None:
    """The validate task gates the exec; deleting it must fail here."""
    validate = _by_name(exec_tasks, "Validate resolved binary path (allowlist)")
    assert validate is not None, "allowlist validation task removed"
    fail = validate.get("ansible.builtin.fail") or validate.get("fail")
    assert fail is not None, "validate must use ansible.builtin.fail"


def test_allowlist_rejects_dotdot_segments(exec_tasks: list[dict]) -> None:
    """ATX iter-2 NW1 / iter-3 NB2: paths with `..` segments must be
    rejected before the prefix allowlist runs. Each sub-pattern is
    asserted independently so a refactor that drops one branch fails
    here.
    """
    reject = _by_name(exec_tasks, "Reject `..` segments in resolved binary path")
    assert reject is not None
    when = reject["when"]
    assert "'/../' in resolved_binary" in when
    assert "endswith('/..')" in when
    assert "startswith('../')" in when


def test_allowlist_allowed_paths(exec_tasks: list[dict]) -> None:
    """The allowlist must accept: the per-agent path, /usr/local/bin/*,
    and /usr/bin/*.
    """
    validate = _by_name(exec_tasks, "Validate resolved binary path (allowlist)")
    when = validate["when"]
    assert "per_agent_binary" in when
    assert "/usr/local/bin/" in when
    assert "/usr/bin/" in when


def test_discovery_runs_as_agent_user(exec_tasks: list[dict]) -> None:
    """ATX iter-1 B3: `which` and `stat` must run as the agent user, not root."""
    for name in (
        "Stat per-agent openclaw binary (as agent user)",
        "Discover openclaw in PATH (as agent user)",
    ):
        task = _by_name(exec_tasks, name)
        assert task is not None, f"task missing: {name}"
        assert task.get("become_user") == "{{ agent_name }}"


def test_exec_runs_as_agent_user_with_no_log(exec_tasks: list[dict]) -> None:
    """The exec task itself must run as the agent user with no_log: true
    (ATX iter-1 W2 / B3).
    """
    run = _by_name(exec_tasks, "Run agent exec command")
    assert run is not None
    assert run.get("become_user") == "{{ agent_name }}"
    assert run.get("no_log") is True


def test_task_ordering(exec_tasks: list[dict]) -> None:
    """stat → which → resolve → normalize → validate → exec."""
    order = [
        "Validate agent_name (defense-in-depth)",
        "Stat per-agent openclaw binary (as agent user)",
        "Discover openclaw in PATH (as agent user)",
        "Resolve openclaw binary",
        "Fail if openclaw not found",
        "Reject `..` segments in resolved binary path",
        "Validate resolved binary path (allowlist)",
        "Ensure workspace directory exists",
        "Run agent exec command",
    ]
    indexes = [_idx(exec_tasks, n) for n in order]
    assert indexes == sorted(indexes), f"task order wrong: {indexes}"


@pytest.mark.parametrize("claw_type", ["hermes", "zeroclaw"])
def test_per_type_playbooks_use_no_log(claw_type: str) -> None:
    """ATX iter-1 W2 mirror: hermes + zeroclaw exec tasks also need no_log."""
    path = (
        EXEC_PLAYBOOK.parent.parent.parent
        / claw_type
        / "playbooks"
        / "exec.yaml"
    )
    play = yaml.safe_load(path.read_text())
    tasks = play[0]["tasks"]
    run = _by_name(tasks, "Run agent exec command")
    assert run is not None
    assert run.get("no_log") is True
    assert run.get("become_user") == "{{ agent_name }}"


@pytest.mark.parametrize("claw_type", ["openclaw", "hermes", "zeroclaw"])
def test_per_type_playbooks_validate_agent_name(claw_type: str) -> None:
    """ATX iter-3 NB3: every exec playbook must guard agent_name
    against shell-special / path-traversal characters, since
    `agent_name` is interpolated into paths and become_user. For
    hermes/zeroclaw this is the only injection guard (no realpath/
    discovery layer).
    """
    path = (
        EXEC_PLAYBOOK.parent.parent.parent
        / claw_type
        / "playbooks"
        / "exec.yaml"
    )
    play = yaml.safe_load(path.read_text())
    tasks = play[0]["tasks"]
    validate = _by_name(tasks, "Validate agent_name (defense-in-depth)")
    assert validate is not None, f"{claw_type}: agent_name validate task missing"
    fail = validate.get("ansible.builtin.fail") or validate.get("fail")
    assert fail is not None, f"{claw_type}: validate must use ansible.builtin.fail"
    when = validate["when"]
    when_str = " ".join(when) if isinstance(when, list) else str(when)
    assert "^[a-z][a-z0-9_-]{0,31}$" in when_str, (
        f"{claw_type}: agent_name regex missing or weakened"
    )
    # The validate task must run first (before any task that touches paths).
    assert tasks.index(validate) == 0, (
        f"{claw_type}: validate task must be first in tasks list"
    )
