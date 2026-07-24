"""Structural tests for the `gh auth setup-git` task (#649).

Zeroclaw ships this task at `configure.yaml:223`. Without it, raw
`git push` over HTTPS from an agent shell fails with "could not read
Username for 'https://github.com'" — even though `gh auth login` has
put a valid token in gh's config — because git uses credential helpers,
not env vars. `gh auth setup-git` writes the credential.helper entry to
`~/.gitconfig`.

These tests enforce that the same task exists on hermes and openclaw
(Linux + openclaw macOS), sits inside the `GitHub CLI authentication
block`, and is gated so it is a no-op on agents without a `github`
integration.
"""

from importlib.resources import files

import pytest
import yaml


SETUP_GIT_TASK_NAME = "Configure git credential helper via gh auth setup-git"
AUTH_LOGIN_TASK_NAME = "Authenticate gh CLI for each github integration"
GITCONFIG_DEST_LINUX = "/home/{{ agent_name }}/.gitconfig"
GITCONFIG_DEST_MACOS = "/Users/{{ agent_name }}/.gitconfig"


def _load_playbook(claw: str, filename: str):
    pkg = files(f"clawrium.platform.registry.{claw}")
    data = yaml.safe_load((pkg / "playbooks" / filename).read_text())
    assert isinstance(data, list) and data, f"{claw}/{filename} must be a play list"
    return data[0]["tasks"]


def _find_task_in_tree(tasks, name):
    """Depth-first search for a task by `name`, descending into `block:` lists."""
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("name") == name:
            return task
        inner = task.get("block")
        if isinstance(inner, list):
            found = _find_task_in_tree(inner, name)
            if found is not None:
                return found
    return None


def _find_task_index(tasks, name):
    """Return the top-level index whose subtree contains `name`, or None."""
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        if task.get("name") == name:
            return i
        inner = task.get("block")
        if isinstance(inner, list) and _find_task_in_tree(inner, name) is not None:
            return i
    return None


# (claw, playbook filename, expected gitconfig dest)
PLAYBOOK_MATRIX = [
    ("hermes", "configure.yaml", GITCONFIG_DEST_LINUX),
    ("openclaw", "configure.yaml", GITCONFIG_DEST_LINUX),
    ("openclaw", "configure_macos.yaml", GITCONFIG_DEST_MACOS),
]


@pytest.fixture(params=PLAYBOOK_MATRIX, ids=lambda p: f"{p[0]}/{p[1]}")
def playbook(request):
    claw, filename, gitconfig_dest = request.param
    tasks = _load_playbook(claw, filename)
    return claw, filename, gitconfig_dest, tasks


def test_setup_git_task_present(playbook):
    claw, filename, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    assert task is not None, (
        f"{claw}/{filename} is missing the `{SETUP_GIT_TASK_NAME}` task. "
        f"Without it, raw `git push` over HTTPS fails from an agent shell "
        f"even after `gh auth login` succeeds (#649)."
    )


def test_setup_git_task_runs_as_agent_user(playbook):
    claw, filename, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    assert task.get("become") is True, f"{claw}/{filename}: must `become: yes`"
    assert task.get("become_user") == "{{ agent_name }}", (
        f"{claw}/{filename}: must `become_user: {{{{ agent_name }}}}` — "
        f"credential.helper is written to the agent user's ~/.gitconfig"
    )


def test_setup_git_task_is_idempotent(playbook):
    claw, filename, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    assert task.get("changed_when") is False, (
        f"{claw}/{filename}: `changed_when: false` — setup-git is idempotent, "
        f"re-running configure should report `ok`, not `changed`"
    )


def test_setup_git_task_gated_on_github_integration(playbook):
    claw, filename, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    when_clause = task.get("when")
    assert isinstance(when_clause, list), (
        f"{claw}/{filename}: `when:` must be a list of clauses"
    )
    when_str = " ".join(when_clause)
    # Must guard on the `github`-integration selectattr — no github integration
    # attached => task is a no-op, so it does not touch gh on non-github agents.
    assert "selectattr" in when_str and "'github'" in when_str, (
        f"{claw}/{filename}: setup-git must be gated on presence of a "
        f"github integration via selectattr. Got: {when_clause!r}"
    )
    # Must also guard on gh being installed (rc == 0 on Linux, stdout|trim
    # length > 0 on macOS-shell probe).
    assert "gh_check" in when_str, (
        f"{claw}/{filename}: setup-git must be gated on the gh_check "
        f"probe result. Got: {when_clause!r}"
    )


def test_setup_git_task_invokes_gh_auth_setup_git(playbook):
    claw, filename, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    cmd = task.get("ansible.builtin.command")
    assert isinstance(cmd, dict), f"{claw}/{filename}: must use ansible.builtin.command"
    argv = cmd.get("argv", [])
    assert len(argv) == 3, f"{claw}/{filename}: argv must be [gh, auth, setup-git]. Got: {argv!r}"
    # argv[0] varies by file convention (bare `gh` on hermes; `gh_check.stdout`
    # on openclaw). Only require it references gh.
    assert "gh" in argv[0], f"{claw}/{filename}: argv[0] must invoke gh. Got: {argv[0]!r}"
    assert argv[1] == "auth", f"{claw}/{filename}: argv[1] must be 'auth'. Got: {argv[1]!r}"
    assert argv[2] == "setup-git", f"{claw}/{filename}: argv[2] must be 'setup-git'. Got: {argv[2]!r}"


def test_setup_git_task_follows_gitconfig_render(playbook):
    """setup-git appends to ~/.gitconfig; the template render overwrites it.

    If ordering is reversed, the credential.helper line setup-git writes is
    silently dropped by the next configure run. This is the invariant called
    out in the zeroclaw comment block.
    """
    claw, filename, gitconfig_dest, tasks = playbook
    setup_idx = _find_task_index(tasks, SETUP_GIT_TASK_NAME)
    # Find the gitconfig render task by dest.
    render_idx = None
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        block = task.get("ansible.builtin.template", {})
        if isinstance(block, dict) and block.get("dest") == gitconfig_dest:
            render_idx = i
            break
    assert render_idx is not None, f"{claw}/{filename}: gitconfig render task not found"
    assert setup_idx is not None, f"{claw}/{filename}: setup-git task not found"
    assert render_idx < setup_idx, (
        f"{claw}/{filename}: gitconfig render (idx {render_idx}) must precede "
        f"setup-git (idx {setup_idx}) — template overwrites, setup-git appends"
    )


def test_setup_git_task_follows_gh_auth_login(playbook):
    """setup-git relies on gh's stored token; it MUST run after `gh auth login`."""
    claw, filename, _, tasks = playbook
    login_task = _find_task_in_tree(tasks, AUTH_LOGIN_TASK_NAME)
    assert login_task is not None, (
        f"{claw}/{filename}: `{AUTH_LOGIN_TASK_NAME}` task missing"
    )
    # Both tasks live in the same GitHub CLI authentication block on all
    # three playbooks; find their positions within that block.
    def _find_in_block(block_list, name):
        for i, t in enumerate(block_list):
            if isinstance(t, dict) and t.get("name") == name:
                return i
        return None

    for task in tasks:
        inner = task.get("block") if isinstance(task, dict) else None
        if not isinstance(inner, list):
            continue
        login_i = _find_in_block(inner, AUTH_LOGIN_TASK_NAME)
        setup_i = _find_in_block(inner, SETUP_GIT_TASK_NAME)
        if login_i is not None and setup_i is not None:
            assert login_i < setup_i, (
                f"{claw}/{filename}: setup-git (idx {setup_i}) must run after "
                f"gh auth login (idx {login_i}) within the auth block"
            )
            return
    pytest.fail(
        f"{claw}/{filename}: could not find both auth-login and setup-git in "
        f"the same block:"
    )
