"""Structural tests for the per-claw gitconfig render task (#531).

Each claw's configure.yaml must:
- declare a `Render ~/.gitconfig for each git integration` task,
- gate it on `type == 'git'` via selectattr,
- run as the agent user (become_user: {{ agent_name }}),
- write to /home/<agent>/.gitconfig with mode 0644,
- pull the template from `{{ shared_template_path }}/gitconfig.j2`,
- precede the GitHub auth block so that `gh auth setup-git`'s
  credential.helper write (zeroclaw) is not wiped by the template
  overwrite, and so the position is consistent across claws.
"""

from importlib.resources import files

import pytest
import yaml


GITHUB_AUTH_NAMES = {
    "GitHub CLI authentication block",
}


@pytest.fixture(params=["zeroclaw", "hermes", "openclaw"])
def configure_tasks(request):
    pkg = files(f"clawrium.platform.registry.{request.param}")
    data = yaml.safe_load((pkg / "playbooks" / "configure.yaml").read_text())
    assert isinstance(data, list) and data, "configure.yaml must be a play list"
    tasks = data[0]["tasks"]
    return request.param, tasks


def _find_gitconfig_task(tasks):
    for task in tasks:
        if not isinstance(task, dict):
            continue
        block = task.get("ansible.builtin.template")
        if not isinstance(block, dict):
            continue
        dest = block.get("dest", "")
        if dest == "/home/{{ agent_name }}/.gitconfig":
            return task
    return None


def test_gitconfig_render_task_present(configure_tasks):
    claw, tasks = configure_tasks
    task = _find_gitconfig_task(tasks)
    assert task is not None, (
        f"{claw}/configure.yaml is missing the gitconfig render task"
    )


def test_gitconfig_render_task_uses_shared_template(configure_tasks):
    claw, tasks = configure_tasks
    task = _find_gitconfig_task(tasks)
    block = task["ansible.builtin.template"]
    assert block["src"] == "{{ shared_template_path }}/gitconfig.j2", (
        f"{claw}: gitconfig task must source the shared template"
    )


def test_gitconfig_render_task_file_attrs(configure_tasks):
    claw, tasks = configure_tasks
    task = _find_gitconfig_task(tasks)
    block = task["ansible.builtin.template"]
    assert block["owner"] == "{{ agent_name }}", f"{claw}: owner mismatch"
    assert block["group"] == "{{ agent_name }}", f"{claw}: group mismatch"
    assert block["mode"] == "0600", f"{claw}: mode mismatch (should be 0600 since `gh auth setup-git` later appends credential.helper)"


def test_gitconfig_render_task_runs_as_agent_user(configure_tasks):
    claw, tasks = configure_tasks
    task = _find_gitconfig_task(tasks)
    assert task.get("become") is True, (
        f"{claw}: gitconfig render task must `become: yes`"
    )
    assert task.get("become_user") == "{{ agent_name }}", (
        f"{claw}: gitconfig render task must `become_user: {{{{ agent_name }}}}`"
    )


def test_gitconfig_render_task_filters_on_type_git(configure_tasks):
    claw, tasks = configure_tasks
    task = _find_gitconfig_task(tasks)
    loop_expr = task.get("loop", "")
    assert "selectattr" in loop_expr and "'git'" in loop_expr, (
        f"{claw}: gitconfig render task must filter on type == 'git'. "
        f"Got: {loop_expr!r}"
    )


def test_gitconfig_render_task_guarded_on_integrations_defined(configure_tasks):
    """The render task must skip cleanly when no integrations are configured."""
    claw, tasks = configure_tasks
    task = _find_gitconfig_task(tasks)
    when_clause = task.get("when")
    # `when` may be a string or a list — normalize.
    when_str = (
        when_clause
        if isinstance(when_clause, str)
        else " ".join(when_clause)
        if isinstance(when_clause, list)
        else ""
    )
    assert "integrations is defined" in when_str, (
        f"{claw}: gitconfig render task must guard on `integrations is defined`"
    )


def test_gitconfig_render_task_precedes_github_auth_block(configure_tasks):
    """Render task must come before the GitHub CLI authentication block.

    Reason: ansible.builtin.template overwrites the destination file. If the
    template ran AFTER `gh auth setup-git` (zeroclaw), the credential.helper
    key that setup-git writes to ~/.gitconfig would be silently dropped.
    For hermes and openclaw the ordering is consistency / future-proofing.
    """
    claw, tasks = configure_tasks
    git_index = None
    auth_index = None
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        name = task.get("name", "")
        block = task.get("ansible.builtin.template", {})
        if (
            isinstance(block, dict)
            and block.get("dest") == "/home/{{ agent_name }}/.gitconfig"
        ):
            git_index = i
        if name in GITHUB_AUTH_NAMES:
            auth_index = i
    assert git_index is not None, f"{claw}: gitconfig render task missing"
    assert auth_index is not None, f"{claw}: github auth block missing"
    assert git_index < auth_index, (
        f"{claw}: gitconfig render task (idx {git_index}) must precede "
        f"the GitHub auth block (idx {auth_index})"
    )


def test_gitconfig_render_task_vars_map_all_five_fields(configure_tasks):
    """The vars.git dict must surface all five #531 fields with safe defaults."""
    claw, tasks = configure_tasks
    task = _find_gitconfig_task(tasks)
    git_vars = task.get("vars", {}).get("git", {})
    expected_keys = {
        "user_name",
        "user_email",
        "init_default_branch",
        "pull_rebase",
        "core_editor",
    }
    assert set(git_vars.keys()) == expected_keys, (
        f"{claw}: vars.git must declare exactly {expected_keys}, got {set(git_vars.keys())}"
    )
    # Optional fields carry safe defaults so an empty integration value
    # never lands as a blank line in the rendered file.
    assert "default('main')" in git_vars["init_default_branch"]
    assert "default('false')" in git_vars["pull_rebase"]
    assert "default('vim')" in git_vars["core_editor"]
