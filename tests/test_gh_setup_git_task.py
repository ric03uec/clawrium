"""Structural tests for the `gh auth setup-git` task (#649).

Zeroclaw ships this task at `configure.yaml:223`. Without it, raw
`git push` over HTTPS from an agent shell fails with "could not read
Username for 'https://github.com'" — even though `gh auth login` has
put a valid token in gh's config — because git uses credential helpers,
not env vars. `gh auth setup-git` writes the credential.helper entry to
`~/.gitconfig`.

These tests enforce that the same task exists on zeroclaw (reference),
hermes, and openclaw (Linux + openclaw macOS), sits inside the
`GitHub CLI authentication block`, and is gated so it is a no-op on
agents without a `github` integration.
"""

from importlib.resources import files

import pytest
import yaml


SETUP_GIT_TASK_NAME = "Configure git credential helper via gh auth setup-git"
AUTH_LOGIN_TASK_NAME = "Authenticate gh CLI for each github integration"
GITCONFIG_TASK_NAME = "Render ~/.gitconfig for each git integration"
GITCONFIG_DEST_LINUX = "/home/{{ agent_name }}/.gitconfig"
GITCONFIG_DEST_MACOS = "/Users/{{ agent_name }}/.gitconfig"

# Canonical Jinja for the github-integration guard: every playbook MUST use
# the exact same filter chain so a partial / mistyped guard is caught.
GITHUB_INTEGRATION_WHEN = (
    "integrations | dict2items | selectattr('value.type', 'equalto', 'github') "
    "| list | length > 0"
)


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


def _normalize_when_expr(expr: str) -> str:
    """Collapse whitespace so multi-line YAML `when:` clauses compare cleanly."""
    return " ".join(expr.split())


# (claw, playbook filename, gitconfig dest, expected argv[0], expected gh probe expr)
#
# expected_gh_guard is the exact substring that MUST appear in the setup-git
# task's `when:` clauses:
#   - Linux uses `which gh` which sets rc=0 on success => guard on rc.
#   - macOS uses `which gh || true` (rc always 0) => guard on stdout length.
# Swapping these is semantically wrong and this test catches that.
PLAYBOOK_MATRIX = [
    ("zeroclaw", "configure.yaml", GITCONFIG_DEST_LINUX, "gh", "gh_check.rc == 0"),
    ("hermes", "configure.yaml", GITCONFIG_DEST_LINUX, "gh", "gh_check.rc == 0"),
    ("openclaw", "configure.yaml", GITCONFIG_DEST_LINUX, "{{ gh_check.stdout | trim }}", "gh_check.rc == 0"),
    ("openclaw", "configure_macos.yaml", GITCONFIG_DEST_MACOS, "{{ gh_check.stdout | trim }}", "(gh_check.stdout | trim) | length > 0"),
]


@pytest.fixture(params=PLAYBOOK_MATRIX, ids=lambda p: f"{p[0]}/{p[1]}")
def playbook(request):
    claw, filename, gitconfig_dest, expected_argv0, expected_gh_guard = request.param
    tasks = _load_playbook(claw, filename)
    return claw, filename, gitconfig_dest, expected_argv0, expected_gh_guard, tasks


def test_setup_git_task_present(playbook):
    claw, filename, _, _, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    assert task is not None, (
        f"{claw}/{filename} is missing the `{SETUP_GIT_TASK_NAME}` task. "
        f"Without it, raw `git push` over HTTPS fails from an agent shell "
        f"even after `gh auth login` succeeds (#649)."
    )


def test_setup_git_task_runs_as_agent_user(playbook):
    claw, filename, _, _, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    assert task.get("become") is True, f"{claw}/{filename}: must `become: yes`"
    assert task.get("become_user") == "{{ agent_name }}", (
        f"{claw}/{filename}: must `become_user: {{{{ agent_name }}}}` — "
        f"credential.helper is written to the agent user's ~/.gitconfig"
    )


def test_setup_git_task_is_idempotent(playbook):
    claw, filename, _, _, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    assert task.get("changed_when") is False, (
        f"{claw}/{filename}: `changed_when: false` — setup-git is idempotent, "
        f"re-running configure should report `ok`, not `changed`"
    )


def test_setup_git_task_gated_on_github_integration(playbook):
    """Verifies the exact canonical guard, not just substring presence."""
    claw, filename, _, _, expected_gh_guard, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    when_clause = task.get("when")
    assert isinstance(when_clause, list), (
        f"{claw}/{filename}: `when:` must be a list of clauses"
    )
    normalized = [_normalize_when_expr(c) for c in when_clause]

    # Exact github-integration selectattr guard: catches truncated or
    # malformed filter chains that a substring match would miss.
    assert GITHUB_INTEGRATION_WHEN in normalized, (
        f"{claw}/{filename}: setup-git must be gated on the exact github "
        f"integration filter:\n  expected: {GITHUB_INTEGRATION_WHEN!r}\n"
        f"  got: {normalized!r}"
    )

    # OS-appropriate gh probe guard: Linux uses rc, macOS uses stdout length.
    # Swapping these is a semantic bug (which gh vs. which gh || true).
    assert expected_gh_guard in normalized, (
        f"{claw}/{filename}: setup-git must guard on the OS-appropriate "
        f"gh probe form:\n  expected: {expected_gh_guard!r}\n"
        f"  got: {normalized!r}"
    )


def test_setup_git_task_invokes_gh_auth_setup_git(playbook):
    """Pin the exact argv[0] per playbook — no substring matching."""
    claw, filename, _, expected_argv0, _, tasks = playbook
    task = _find_task_in_tree(tasks, SETUP_GIT_TASK_NAME)
    cmd = task.get("ansible.builtin.command")
    assert isinstance(cmd, dict), f"{claw}/{filename}: must use ansible.builtin.command"
    argv = cmd.get("argv", [])
    assert argv == [expected_argv0, "auth", "setup-git"], (
        f"{claw}/{filename}: argv must be [{expected_argv0!r}, 'auth', 'setup-git']. "
        f"Got: {argv!r}"
    )


def test_setup_git_task_follows_gitconfig_render(playbook):
    """setup-git appends to ~/.gitconfig; the template render overwrites it.

    If ordering is reversed, the credential.helper line setup-git writes is
    silently dropped by the next configure run. This is the invariant called
    out in the zeroclaw comment block.

    Uses the same depth-first finder as setup-git so a future refactor that
    moves the render task into a block gives a correct error message.
    """
    claw, filename, _, _, _, tasks = playbook
    render_idx = _find_task_index(tasks, GITCONFIG_TASK_NAME)
    setup_idx = _find_task_index(tasks, SETUP_GIT_TASK_NAME)
    assert render_idx is not None, (
        f"{claw}/{filename}: `{GITCONFIG_TASK_NAME}` task not found"
    )
    assert setup_idx is not None, (
        f"{claw}/{filename}: `{SETUP_GIT_TASK_NAME}` task not found"
    )
    assert render_idx < setup_idx, (
        f"{claw}/{filename}: gitconfig render (idx {render_idx}) must precede "
        f"setup-git (idx {setup_idx}) — template overwrites, setup-git appends"
    )


def _find_index_in_tree(tasks, name):
    """Depth-first search that returns the *index* of `name` within its
    containing list, plus the list itself. Returns (None, None) if not found.

    Consistent with `_find_task_in_tree` — descends into `block:` lists so a
    future refactor that nests tasks one level deeper (e.g. into `rescue:`)
    still finds them and produces a real assertion, not a false pytest.fail.
    """
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        if task.get("name") == name:
            return i, tasks
        inner = task.get("block")
        if isinstance(inner, list):
            idx, container = _find_index_in_tree(inner, name)
            if idx is not None:
                return idx, container
    return None, None


def test_setup_git_task_follows_gh_auth_login(playbook):
    """setup-git relies on gh's stored token; it MUST run after `gh auth login`.

    Both live inside the same `GitHub CLI authentication block`. Requires
    them to share a container list AND the setup-git index to come after.
    """
    claw, filename, _, _, _, tasks = playbook
    login_idx, login_container = _find_index_in_tree(tasks, AUTH_LOGIN_TASK_NAME)
    setup_idx, setup_container = _find_index_in_tree(tasks, SETUP_GIT_TASK_NAME)
    assert login_idx is not None, (
        f"{claw}/{filename}: `{AUTH_LOGIN_TASK_NAME}` task missing"
    )
    assert setup_idx is not None, (
        f"{claw}/{filename}: `{SETUP_GIT_TASK_NAME}` task missing"
    )
    assert login_container is setup_container, (
        f"{claw}/{filename}: setup-git and gh auth login must share a "
        f"container (same block); found them in different lists"
    )
    assert login_idx < setup_idx, (
        f"{claw}/{filename}: setup-git (idx {setup_idx}) must run after "
        f"gh auth login (idx {login_idx}) within the auth block"
    )
