"""Structural tests for the per-claw skills_apply.yaml playbooks.

These tests assert invariants that the safety + idempotency story for
`clm agent skill install/remove` depends on: file existence, presence of
the ownership boundary mechanism (hermes subdir / openclaw sentinel /
zeroclaw tracking file), and bounded pruning. They do NOT run ansible —
runtime behavior is exercised by `tests/test_core_skills_apply.py` with
a mocked `ansible_runner`, and end-to-end against real hosts in the
smoke transcripts captured under `.itx/<issue>/01_EXECUTION.md`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
REGISTRY_ROOT = PROJECT_ROOT / "src" / "clawrium" / "platform" / "registry"


def _load_playbook(claw: str) -> tuple[str, dict]:
    """Parse the playbook and return (raw_text, first_play_dict).

    An Ansible playbook file is a single YAML document whose top-level is
    a list of plays. We unwrap to the first play because both new
    playbooks declare exactly one.
    """
    path = REGISTRY_ROOT / claw / "playbooks" / "skills_apply.yaml"
    assert path.is_file(), f"{path} must exist"
    text = path.read_text()
    data = yaml.safe_load(text)
    assert isinstance(data, list), f"{path} top-level should be a list of plays"
    assert len(data) == 1, f"{path} should declare exactly one play"
    return text, data[0]


# ---------------------------- existence -------------------------------------


def test_openclaw_skills_apply_playbook_exists():
    _load_playbook("openclaw")


def test_zeroclaw_skills_apply_playbook_exists():
    _load_playbook("zeroclaw")


# ---------------------------- shared invariants -----------------------------


def _flatten_tasks(tasks: list[dict]) -> list[dict]:
    """Flatten a tasks list, descending into `block:` / `rescue:` /
    `always:` so structural assertions can reach tasks defined inside
    a block/always wrapper. Order is preserved: block body first, then
    rescue, then always — matching ansible's runtime contract for
    "before / on error / cleanup".
    """
    flat: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        # A block task can be a parent (no module key, only block/always)
        # or a regular task. If it has block/always, descend; either way
        # also include the wrapper so its `name:` shows up in ordering.
        if "block" in task or "always" in task or "rescue" in task:
            flat.append(task)
            for child in task.get("block", []) or []:
                flat.extend(_flatten_tasks([child]))
            for child in task.get("rescue", []) or []:
                flat.extend(_flatten_tasks([child]))
            for child in task.get("always", []) or []:
                flat.extend(_flatten_tasks([child]))
        else:
            flat.append(task)
    return flat


def _all_tasks(play: dict) -> list[dict]:
    return _flatten_tasks(play.get("tasks", []))


def _task_names(play: dict) -> list[str]:
    return [t.get("name", "") for t in _all_tasks(play)]


def test_openclaw_playbook_validates_inputs_before_touching_host():
    """Every input that influences a filesystem path on the host must be
    regex-validated by the playbook itself — defense-in-depth against a
    tampered extravar bypassing the Python-side validation."""
    _, play = _load_playbook("openclaw")
    names = _task_names(play)
    # Both checks must appear before any task that writes to skills_root.
    assert "Validate agent_name format" in names
    assert "Validate every desired skill name" in names
    # The validation tasks must come before file-mutation tasks.
    validate_idx = names.index("Validate every desired skill name")
    write_idx = names.index("Materialize SKILL.md for each desired skill")
    assert validate_idx < write_idx


def test_zeroclaw_playbook_validates_inputs_before_touching_host():
    _, play = _load_playbook("zeroclaw")
    names = _task_names(play)
    assert "Validate agent_name format" in names
    assert "Validate every desired skill name" in names
    validate_idx = names.index("Validate every desired skill name")
    install_idx = names.index(
        "Install each desired skill via native `zeroclaw skills install`"
    )
    assert validate_idx < install_idx


# ---------------------------- openclaw-specific -----------------------------


def test_openclaw_playbook_writes_clawrium_managed_sentinel():
    """Pruning safety: the playbook must drop a sentinel file inside
    each clawrium-managed skill dir so future prune passes can
    distinguish clawrium-owned dirs from user-authored ones under
    `~/.openclaw/skills/`."""
    text, play = _load_playbook("openclaw")
    assert "managed_marker: \".clawrium-managed\"" in text
    names = _task_names(play)
    assert "Mark each desired skill as clawrium-managed" in names


def test_openclaw_playbook_prunes_only_marked_dirs():
    """The prune set is the intersection of (on-host dirs that carry our
    sentinel) and (NOT in desired). Without the sentinel-filtering step,
    pruning would touch user-authored skills — verify the filter exists."""
    _, play = _load_playbook("openclaw")
    names = _task_names(play)
    assert "Detect clawrium-managed marker files" in names
    assert "Compute set of clawrium-managed skill dirnames on host" in names
    # The compute-prune task must reference clawrium_managed_dirs (the
    # filtered set), not the raw `existing_skill_dirs.files` list.
    compute_prune = next(
        t
        for t in play["tasks"]
        if t.get("name") == "Compute set of skill directories to prune"
    )
    set_fact = compute_prune["ansible.builtin.set_fact"]
    skills_to_prune = set_fact["skills_to_prune"]
    assert "clawrium_managed_dirs" in skills_to_prune


def test_openclaw_playbook_pruning_uses_depth_one_find():
    """The `find` enumeration that feeds the prune set must be bounded
    to top-level dirs. A recursive walk could enumerate (and ultimately
    delete) files inside a user-authored skill subdir."""
    _, play = _load_playbook("openclaw")
    find_task = next(
        t
        for t in play["tasks"]
        if t.get("name") == "List existing skill directories on host"
    )
    assert find_task["ansible.builtin.find"]["depth"] == 1


def test_openclaw_playbook_skills_root_is_canonical():
    text, _ = _load_playbook("openclaw")
    assert 'skills_root: "/home/{{ agent_name }}/.openclaw/skills"' in text


# ---------------------------- zeroclaw-specific -----------------------------


def test_zeroclaw_playbook_wraps_native_install_cli():
    """Zeroclaw's value-add is the security audit gate fronted by
    `zeroclaw skills install <path>`. The playbook MUST invoke this CLI
    (not raw file copies into `~/.zeroclaw/workspace/skills/`) so the
    audit runs on every install."""
    _, play = _load_playbook("zeroclaw")
    # The install task lives inside a block/always wrapper (ATX W3) —
    # walk the flattened list to find it.
    install_task = next(
        t
        for t in _all_tasks(play)
        if t.get("name")
        == "Install each desired skill via native `zeroclaw skills install`"
    )
    argv = install_task["ansible.builtin.command"]["argv"]
    # `argv` form prevents shell-injection through the slug; the slug
    # is also regex-validated upstream.
    assert argv[1] == "skills"
    assert argv[2] == "install"


def test_zeroclaw_playbook_removes_via_native_cli():
    _, play = _load_playbook("zeroclaw")
    remove_task = next(
        t
        for t in play["tasks"]
        if t.get("name")
        == "Uninstall clawrium-managed skills no longer in desired state"
    )
    argv = remove_task["ansible.builtin.command"]["argv"]
    assert argv[1] == "skills"
    assert argv[2] == "remove"


def test_zeroclaw_playbook_uses_workspace_skills_path():
    """Phase 0 confirmed the on-disk install path is
    `~/.zeroclaw/workspace/skills/` (workspace-scoped), not the
    plan's draft `~/.zeroclaw/skills/`. Regression guard against
    reverting to the wrong path."""
    text, _ = _load_playbook("zeroclaw")
    assert (
        'workspace_skills: "/home/{{ agent_name }}/.zeroclaw/workspace/skills"'
        in text
    )


def test_zeroclaw_playbook_tracking_file_outside_skills_dir():
    """The clawrium-managed-skills tracking file must NOT live under
    `~/.zeroclaw/workspace/skills/` — anything inside that subtree gets
    scanned by `zeroclaw skills install`'s audit gate, which could
    reject the unexpected file or surface false-positive findings."""
    text, _ = _load_playbook("zeroclaw")
    assert (
        'tracking_file: "/home/{{ agent_name }}/.zeroclaw/.clawrium-managed-skills"'
        in text
    )
    # The tracking file path must not be inside workspace/skills/.
    assert "/workspace/skills/.clawrium" not in text


def test_zeroclaw_playbook_prune_set_intersects_installed():
    """`zeroclaw skills remove <slug>` errors if the slug isn't
    currently installed. The prune set must intersect with the on-disk
    installed list so we never `remove` a slug that's already gone."""
    _, play = _load_playbook("zeroclaw")
    compute_prune = next(
        t
        for t in play["tasks"]
        if t.get("name")
        == "Compute prune set (tracked but not desired AND still installed)"
    )
    skills_to_prune = compute_prune["ansible.builtin.set_fact"]["skills_to_prune"]
    assert "intersect(installed_slugs)" in skills_to_prune
    assert "tracked_skill_names" in skills_to_prune
    assert "desired_skill_names" in skills_to_prune


def test_zeroclaw_playbook_audit_gate_runs_for_every_desired_skill():
    """Security contract (ATX #382 B2): `zeroclaw skills install` must
    fire for EVERY entry in `desired_skill_names`, with no
    `difference(installed_slugs)` filter that would skip already-present
    slugs. Skipping would bypass the native audit gate, defeating the
    whole reason the playbook wraps the CLI instead of doing raw file
    copies into `~/.zeroclaw/workspace/skills/`."""
    text, play = _load_playbook("zeroclaw")
    install_task = next(
        t
        for t in _all_tasks(play)
        if t.get("name")
        == "Install each desired skill via native `zeroclaw skills install`"
    )
    # The install task must loop over the FULL desired list, not a
    # filtered subset.
    assert install_task["loop"] == "{{ desired_skill_names }}"
    # Regression guard: the explicit anti-pattern that ATX B2 flagged.
    # If a future refactor reintroduces `difference(installed_slugs)`
    # in EXECUTABLE yaml (set_fact / when / loop), the test fails. We
    # strip line comments (`#...`) first so the explainer comments
    # documenting *why* we removed the filter don't false-positive.
    non_comment = "\n".join(
        line.split("#", 1)[0] for line in text.splitlines()
    )
    assert "difference(installed_slugs)" not in non_comment


def test_zeroclaw_playbook_install_wrapped_in_block_always():
    """Failure-mode hygiene (ATX #382 W3): stage + install must run
    inside a `block:` with an `always:` cleanup so a rejected-by-audit
    install never leaves the rendered SKILL.md on disk at a predictable
    path. Mirrors the existing `configure.yaml` cleanup pattern."""
    _, play = _load_playbook("zeroclaw")
    # Find the wrapper block by its name. Wrapper has `block:` and
    # `always:` keys, no module key of its own.
    wrapper = next(
        t
        for t in play["tasks"]
        if "block" in t and "always" in t
    )
    block_names = [t.get("name", "") for t in wrapper["block"]]
    always_names = [t.get("name", "") for t in wrapper["always"]]
    assert (
        "Install each desired skill via native `zeroclaw skills install`"
        in block_names
    )
    assert "Clean up remote staging directory" in always_names


def test_zeroclaw_playbook_writes_tracking_file_last():
    """Failure-mode invariant: the tracking file is the ownership log
    that bounds future prune passes. It must be updated AFTER all
    install/remove operations succeed so a mid-apply failure leaves
    the previous tracked list intact (next apply reconverges)."""
    _, play = _load_playbook("zeroclaw")
    names = _task_names(play)
    tracking_idx = names.index("Update tracking file with current desired state")
    install_idx = names.index(
        "Install each desired skill via native `zeroclaw skills install`"
    )
    remove_idx = names.index(
        "Uninstall clawrium-managed skills no longer in desired state"
    )
    assert tracking_idx > install_idx
    assert tracking_idx > remove_idx


def test_zeroclaw_playbook_install_uses_argv_form_not_shell():
    """Defense-in-depth: every external command invocation must use
    `argv:` form, not a `cmd:` string. Even though the slug is regex-
    validated, passing arguments through a shell parser is an
    unnecessary risk surface."""
    _, play = _load_playbook("zeroclaw")
    # Walk the flattened task list so block/always-nested tasks are
    # included — the install task lives inside a `block:` wrapper.
    for task in _all_tasks(play):
        cmd = task.get("ansible.builtin.command")
        if cmd is None:
            continue
        # `cmd` may be a dict (with `argv` or `cmd`) or a plain string.
        # The string form is exactly what we want to ban.
        assert isinstance(cmd, dict), (
            f"task {task.get('name')!r} uses shell-style `command:` — "
            "must use argv form"
        )
        assert "argv" in cmd, (
            f"task {task.get('name')!r} must use `argv:` form, "
            "not `cmd:` string"
        )
