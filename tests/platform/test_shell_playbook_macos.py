"""YAML-parse invariants on `src/clawrium/platform/shell/shell_macos.yaml`.

Pure static inspection — no ansible-runner invocation. Mirrors the
Linux invariants in `test_shell_playbook.py` for the macOS playbook so
a future edit cannot drop `no_log`, the SHELL_*= prefixes, the
`bash -lc` inner shell, or the gtimeout discovery / fallback branch.
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
    / "shell_macos.yaml"
)


@pytest.fixture(scope="module")
def play() -> dict:
    text = _PLAYBOOK_PATH.read_text()
    docs = list(yaml.safe_load_all(text))
    play_doc = docs[0]
    assert isinstance(play_doc, list)
    return play_doc[0]


def _tasks_by_name_prefix(play: dict, prefix: str) -> list[dict]:
    return [t for t in play["tasks"] if t.get("name", "").startswith(prefix)]


def _run_tasks(play: dict) -> list[dict]:
    tasks = _tasks_by_name_prefix(play, "Run command")
    assert len(tasks) == 2, (
        f"Expected exactly two `Run command ...` tasks (gtimeout / fallback), "
        f"got {len(tasks)}: {[t.get('name') for t in tasks]}"
    )
    return tasks


def test_P1_no_log_true_on_both_run_tasks(play):
    for task in _run_tasks(play):
        assert task["no_log"] is True, task.get("name")


def test_P2_become_user_is_agent_name_template(play):
    for task in _run_tasks(play):
        assert task["become"] is True, task.get("name")
        assert task["become_user"] == "{{ agent_name }}", task.get("name")


def test_P3_bash_lc_is_inner_shell_on_both_run_tasks(play):
    """Inner shell is `bash -lc` (login, NOT interactive) on both
    branches. The Python caller prepends `[ -f ~/.bash_profile ] && . ...;`
    + `[ -f ~/.bashrc ] && . ...;` so PATH shims still load."""
    for task in _run_tasks(play):
        argv = task["ansible.builtin.command"]["argv"]
        found = any(
            argv[i] == "/bin/bash" and argv[i + 1] == "-lc"
            for i in range(len(argv) - 1)
        )
        assert found, f"argv missing '/bin/bash -lc' sequence: {argv!r}"


def test_P4_gtimeout_branch_uses_resolved_gtimeout_as_argv0(play):
    """The gtimeout branch must use the discovered `resolved_gtimeout`
    path as argv[0] so the kill window is enforced server-side. The
    fallback branch starts directly with `/bin/bash` — the runner-level
    timeout is the kill backstop there."""
    run_tasks = _run_tasks(play)
    gtimeout_branch = [
        t
        for t in run_tasks
        if t["ansible.builtin.command"]["argv"][0] == "{{ resolved_gtimeout }}"
    ]
    fallback_branch = [
        t
        for t in run_tasks
        if t["ansible.builtin.command"]["argv"][0] == "/bin/bash"
    ]
    assert len(gtimeout_branch) == 1, (
        "Expected exactly one Run command task with resolved_gtimeout as argv0"
    )
    assert len(fallback_branch) == 1, (
        "Expected exactly one fallback Run command task starting with /bin/bash"
    )
    # gtimeout branch must include --kill-after=5 between argv[0] and argv[2].
    assert "--kill-after=5" in gtimeout_branch[0]["ansible.builtin.command"]["argv"]


def test_P4_run_tasks_gated_by_resolved_gtimeout_length(play):
    """The two Run command tasks must be mutually exclusive: gtimeout
    branch fires when `resolved_gtimeout` is non-empty, fallback fires
    when it is empty. Without the `when:` gating both tasks would run
    on every host (resolved_gtimeout=='' case), causing duplicate side
    effects and indeterminate SHELL_RC capture (W3 iter-1)."""
    run_tasks = _run_tasks(play)
    gtimeout_branch = next(
        t
        for t in run_tasks
        if t["ansible.builtin.command"]["argv"][0] == "{{ resolved_gtimeout }}"
    )
    fallback_branch = next(
        t
        for t in run_tasks
        if t["ansible.builtin.command"]["argv"][0] == "/bin/bash"
    )

    gtimeout_when = str(gtimeout_branch.get("when", ""))
    fallback_when = str(fallback_branch.get("when", ""))

    assert "resolved_gtimeout" in gtimeout_when
    assert "> 0" in gtimeout_when
    assert "resolved_gtimeout" in fallback_when
    assert "== 0" in fallback_when


def test_P5_merge_run_task_result_present_and_conditional(play):
    """The 'Merge run-task result' set_fact stitches the fallback
    register back to `shell_result` so the downstream emit tasks see
    one variable name. Its ternary must reference both registers AND
    the `resolved_gtimeout | length` predicate so the gating cannot
    drift undetected (W4 iter-1)."""
    merge_tasks = [
        t for t in play["tasks"] if "set_fact" in t.get("name", "").lower()
        or "merge" in t.get("name", "").lower()
    ]
    candidates = [
        t
        for t in merge_tasks
        if "ansible.builtin.set_fact" in t
        and "shell_result" in str(t["ansible.builtin.set_fact"])
    ]
    assert len(candidates) >= 1, (
        f"No `shell_result` merge set_fact task found. Tasks: "
        f"{[t.get('name') for t in play['tasks']]}"
    )
    merge = candidates[0]
    expr = str(merge["ansible.builtin.set_fact"])
    assert "shell_result_fallback" in expr
    assert "resolved_gtimeout" in expr
    assert "length" in expr


def test_P5_gtimeout_discovery_runs_as_agent_user(play):
    """Homebrew/MacPorts shims live on the agent user's $PATH (and
    `/opt/homebrew/bin` is readable to that user). Discovery must
    `become_user` the agent so the same shims are visible during the
    `which` lookup; otherwise a refactor would silently widen the
    kill window on every host (W5 iter-1)."""
    discovery = next(
        (t for t in play["tasks"] if t.get("name", "").startswith("Discover gtimeout")),
        None,
    )
    assert discovery is not None, (
        "No `Discover gtimeout` task found in shell_macos.yaml"
    )
    assert discovery["become"] is True
    assert discovery["become_user"] == "{{ agent_name }}"


def test_iter3_W3_cmd_b64_validation_task_present(play):
    for task in play["tasks"]:
        if "ansible.builtin.fail" not in task:
            continue
        when = task.get("when")
        when_str = " ".join(when) if isinstance(when, list) else (when or "")
        if "cmd_b64" in when_str and "not defined" in when_str:
            return
    raise AssertionError("No `cmd_b64 is not defined` guard task found")


def test_iter3_B2_shell_timeout_validation_task_present(play):
    for task in play["tasks"]:
        if "ansible.builtin.fail" not in task:
            continue
        when = task.get("when")
        when_str = " ".join(when) if isinstance(when, list) else (when or "")
        if "shell_timeout" in when_str:
            return
    raise AssertionError("No `shell_timeout` guard task found")


def test_P5_agent_name_regex_validation_task_present(play):
    for task in play["tasks"]:
        if "ansible.builtin.fail" not in task:
            continue
        when = task.get("when")
        when_str = " ".join(when) if isinstance(when, list) else (when or "")
        if "agent_name is not match" in when_str:
            return
    raise AssertionError("No agent_name regex-validation fail task found")


def test_P6_failed_when_and_changed_when_false_on_both_run_tasks(play):
    for task in _run_tasks(play):
        assert task["failed_when"] is False, task.get("name")
        assert task["changed_when"] is False, task.get("name")


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


def test_no_darwin_os_family_guard_in_when_clauses(play):
    """Dispatcher-only OS-fork: the macOS playbook must not branch on
    `ansible_os_family` itself — `core/playbook_resolver.py` is the
    routing source of truth. We inspect each task's `when:` clause
    rather than the raw text so explanatory comments can still mention
    the fact name."""
    for task in play["tasks"]:
        when = task.get("when")
        if when is None:
            continue
        clauses = when if isinstance(when, list) else [when]
        for clause in clauses:
            assert "ansible_os_family" not in str(clause), (
                f"task {task.get('name')!r} branches on ansible_os_family: {clause!r}"
            )
