"""YAML-parse invariants on `src/clawrium/platform/shell/shell.yaml`.

Pure static inspection — no ansible-runner invocation. Catches
regressions where a future edit silently drops `no_log`, swaps to
`shell:`, or removes the `/usr/bin/timeout` wrapper.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


_PLAYBOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "clawrium"
    / "platform"
    / "shell"
    / "shell.yaml"
)


@pytest.fixture(scope="module")
def play() -> dict:
    text = _PLAYBOOK_PATH.read_text()
    docs = list(yaml.safe_load_all(text))
    # File is a single play.
    play_doc = docs[0]
    assert isinstance(play_doc, list)
    return play_doc[0]


def _task_by_name_prefix(play: dict, prefix: str) -> dict:
    for task in play["tasks"]:
        if task.get("name", "").startswith(prefix):
            return task
    raise AssertionError(f"No task with name starting {prefix!r}")


def test_P1_no_log_true_on_command_task(play):
    task = _task_by_name_prefix(play, "Run command")
    assert task["no_log"] is True


def test_P2_become_user_is_agent_name_template(play):
    task = _task_by_name_prefix(play, "Run command")
    assert task["become"] is True
    assert task["become_user"] == "{{ agent_name }}"


def test_P3_timeout_binary_is_argv0(play):
    task = _task_by_name_prefix(play, "Run command")
    argv = task["ansible.builtin.command"]["argv"]
    assert argv[0] == "/usr/bin/timeout"


def test_P4_bash_lc_is_inner_shell_no_interactive(play):
    """Inner shell is `bash -lc` (login, NOT interactive). The Python
    caller prepends an explicit `[ -f ~/.bashrc ] && . ~/.bashrc;` to
    the decoded command so PATH shims still load, without the
    `-i` side effects (history pollution, job-control stderr noise,
    `~/.bash_logout` trap — #761 iter-3 W1)."""
    task = _task_by_name_prefix(play, "Run command")
    argv = task["ansible.builtin.command"]["argv"]
    for i in range(len(argv) - 1):
        if argv[i] == "/bin/bash" and argv[i + 1] == "-lc":
            return
    raise AssertionError(f"argv missing '/bin/bash -lc' sequence: {argv!r}")


def test_iter3_W3_cmd_b64_validation_task_present(play):
    """A defined-and-non-empty guard on `cmd_b64` must run before the
    no-log command task (#761 iter-3 W3)."""
    for task in play["tasks"]:
        if "ansible.builtin.fail" not in task:
            continue
        when = task.get("when")
        when_str = " ".join(when) if isinstance(when, list) else (when or "")
        if "cmd_b64" in when_str and "not defined" in when_str:
            return
    raise AssertionError("No `cmd_b64 is not defined` guard task found")


def test_iter3_B2_shell_timeout_validation_task_present(play):
    """A positive-integer guard on `shell_timeout` must precede the
    command task so a missing/zero value cannot silently degrade into
    `timeout(1)`'s "no kill window" mode (#761 iter-3 B2)."""
    for task in play["tasks"]:
        if "ansible.builtin.fail" not in task:
            continue
        when = task.get("when")
        when_str = " ".join(when) if isinstance(when, list) else (when or "")
        if "shell_timeout" in when_str:
            return
    raise AssertionError("No `shell_timeout` guard task found")


def test_P5_agent_name_regex_validation_task_present(play):
    # A task using ansible.builtin.fail whose `when` references the
    # agent_name regex match.
    for task in play["tasks"]:
        if "ansible.builtin.fail" not in task:
            continue
        when = task.get("when")
        when_str = " ".join(when) if isinstance(when, list) else (when or "")
        if "agent_name is not match" in when_str:
            return
    raise AssertionError("No agent_name regex-validation fail task found")


def test_P6_failed_when_and_changed_when_false(play):
    task = _task_by_name_prefix(play, "Run command")
    assert task["failed_when"] is False
    assert task["changed_when"] is False


# ----- W8: kill-after-5 and SHELL_*= prefix cross-layer contracts ---


def test_W8_kill_after_5_present(play):
    """Removing --kill-after=5 would leave SIGTERM-ignoring processes
    unreapable. Lock the contract here so a future edit can't drop it."""
    task = _task_by_name_prefix(play, "Run command")
    argv = task["ansible.builtin.command"]["argv"]
    assert "--kill-after=5" in argv


def test_W8_emit_prefix_contracts(play):
    """The three debug tasks emit SHELL_STDOUT=/SHELL_STDERR=/SHELL_RC=.
    Core's parser hard-codes these prefixes; flipping any of them
    silently breaks the round-trip."""
    expected_prefixes = {
        "SHELL_STDOUT=": False,
        "SHELL_STDERR=": False,
        "SHELL_RC=": False,
    }
    for task in play["tasks"]:
        if "ansible.builtin.debug" not in task:
            continue
        msg = task["ansible.builtin.debug"].get("msg", "")
        for prefix in expected_prefixes:
            if msg.startswith(prefix):
                expected_prefixes[prefix] = True
    missing = [p for p, hit in expected_prefixes.items() if not hit]
    assert not missing, f"Missing emit prefixes: {missing}"
