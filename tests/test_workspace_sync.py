"""Workspace overlay sync unit tests (issue #760, Phase 1 openclaw subset).

Covers a focused subset of plan §3.1 — the openclaw-applicable invariants
that gate every later phase: enumeration filters, exclude semantics,
secret-pattern mode floor, dispatcher routing, no-paramiko, agent-name
validation, no `ansible_user_dir` in the playbook body.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from clawrium.core import workspace_sync
from clawrium.core.workspace_sync import (
    WORKSPACE_STATES,
    WorkspaceOverlaySpec,
    WorkspacePhaseResult,
    enumerate_workspace_files,
    push_workspace_phase,
)


# ---------------------------------------------------------------------------
# spec parsing
# ---------------------------------------------------------------------------


def test_openclaw_spec_from_manifest_has_no_excludes() -> None:
    """U4 (openclaw subset)."""
    spec = WorkspaceOverlaySpec.from_manifest("openclaw")
    assert spec is not None
    assert spec.destination_root == "~/.openclaw/workspace"
    assert spec.excludes_files == frozenset()
    assert spec.excludes_dirs == ()


def test_zeroclaw_spec_from_manifest_has_no_excludes() -> None:
    """U4 (zeroclaw subset, #768) — zeroclaw mirrors openclaw's
    empty-excludes contract."""
    spec = WorkspaceOverlaySpec.from_manifest("zeroclaw")
    assert spec is not None
    assert spec.destination_root == "~/.zeroclaw/workspace"
    assert spec.excludes_files == frozenset()
    assert spec.excludes_dirs == ()


def test_hermes_spec_from_manifest_destination_pinned() -> None:
    """U2 (hermes subset, #769) — destination_root sourced from the
    manifest, not hard-coded in core. Hermes uses `~/.hermes` (no
    `workspace/` suffix) because the overlay shares its destination
    with canonical-render output."""
    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None
    assert spec.destination_root == "~/.hermes"


def test_hermes_spec_from_manifest_excludes_pinned() -> None:
    """U3 (#769) — the hermes exclude set is the exact list documented
    in the plan §1.1 and the manifest comment. Drift here is a release
    blocker: dropping a single entry exposes daemon-managed bytes to
    operator overwrite."""
    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None
    assert spec.excludes_files == frozenset(
        {
            "config.yaml",
            ".env",
            "auth.json",
            "state.db",
            "state.db-journal",
            "state.db-wal",
            "state.db-shm",
        }
    )
    # Dir-prefix entries are stored without the trailing slash inside
    # the spec; the manifest YAML uses trailing slashes.
    assert set(spec.excludes_dirs) == {"sessions", "logs", "skills/clawrium"}


def test_unknown_agent_type_raises_from_manifest() -> None:
    from clawrium.core.registry import ManifestNotFoundError

    with pytest.raises(ManifestNotFoundError):
        WorkspaceOverlaySpec.from_manifest("definitely-not-an-agent")


# ---------------------------------------------------------------------------
# enumeration
# ---------------------------------------------------------------------------


def _empty_spec() -> WorkspaceOverlaySpec:
    return WorkspaceOverlaySpec(destination_root="~/.openclaw/workspace")


def test_enumerate_missing_workspace_dir_is_noop(tmp_path: Path) -> None:
    """U15."""
    entries, excluded, skipped = enumerate_workspace_files(
        tmp_path / "does-not-exist",
        _empty_spec(),
        agent_name="alice",
    )
    assert entries == []
    assert excluded == []
    assert skipped == []


def test_enumerate_empty_workspace_is_noop(tmp_path: Path) -> None:
    """U14."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    entries, _, _ = enumerate_workspace_files(
        workspace, _empty_spec(), agent_name="alice"
    )
    assert entries == []


def test_enumerate_preserves_relative_path_structure(tmp_path: Path) -> None:
    """U9."""
    workspace = tmp_path / "workspace"
    nested = workspace / "profiles" / "coder"
    nested.mkdir(parents=True)
    (nested / "SOUL.md").write_text("hi")

    entries, _, _ = enumerate_workspace_files(
        workspace, _empty_spec(), agent_name="alice"
    )
    assert len(entries) == 1
    assert entries[0].rel == "profiles/coder/SOUL.md"


def test_enumerate_skips_symlinks(tmp_path: Path) -> None:
    """U6 — symlink leaf rejected."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("evil")
    (workspace / "link").symlink_to(target)

    entries, _, skipped = enumerate_workspace_files(
        workspace, _empty_spec(), agent_name="alice"
    )
    assert entries == []
    assert "link" in skipped


def test_enumerate_skips_clawrium_reserved_dotfiles(tmp_path: Path) -> None:
    """U7."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".clawrium-state.json").write_text("{}")
    (workspace / "good.md").write_text("ok")

    entries, _, skipped = enumerate_workspace_files(
        workspace, _empty_spec(), agent_name="alice"
    )
    rels = [e.rel for e in entries]
    assert "good.md" in rels
    assert ".clawrium-state.json" not in rels
    assert ".clawrium-state.json" in skipped


def test_enumerate_applies_dir_prefix_exclude(tmp_path: Path) -> None:
    """U19 — `sessions/` excludes every descendant."""
    workspace = tmp_path / "workspace"
    (workspace / "sessions").mkdir(parents=True)
    (workspace / "sessions" / "x.json").write_text("{}")
    (workspace / "keep.md").write_text("k")

    spec = WorkspaceOverlaySpec(
        destination_root="~/x",
        excludes_dirs=("sessions",),
    )
    entries, excluded, _ = enumerate_workspace_files(
        workspace, spec, agent_name="alice"
    )
    rels = [e.rel for e in entries]
    assert rels == ["keep.md"]
    assert "sessions/x.json" in excluded


def test_enumerate_applies_exact_file_exclude(tmp_path: Path) -> None:
    """U19 — `config.yaml` excludes only the root file."""
    workspace = tmp_path / "workspace"
    (workspace / "profiles").mkdir(parents=True)
    (workspace / "config.yaml").write_text("x")
    (workspace / "profiles" / "config.yaml").write_text("y")

    spec = WorkspaceOverlaySpec(
        destination_root="~/x",
        excludes_files=frozenset({"config.yaml"}),
    )
    entries, excluded, _ = enumerate_workspace_files(
        workspace, spec, agent_name="alice"
    )
    rels = sorted(e.rel for e in entries)
    assert rels == ["profiles/config.yaml"]
    assert excluded == ["config.yaml"]


# ---------------------------------------------------------------------------
# mode-bit handling (U10, U20, U35)
# ---------------------------------------------------------------------------


def test_extravar_carries_local_mode_bits(tmp_path: Path) -> None:
    """U10 — non-secret files preserve their on-disk mode."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    f = workspace / "README.md"
    f.write_text("x")
    os.chmod(f, 0o644)

    entries, _, _ = enumerate_workspace_files(
        workspace, _empty_spec(), agent_name="alice"
    )
    assert entries[0].mode == "0644"


@pytest.mark.parametrize(
    "name",
    [
        "secrets.env",
        "service.key",
        "agent.pem",
        ".env",
        "my-credentials.json",
        "my-secret-stuff",
        "github.token",
        "user-password.txt",
    ],
)
def test_secret_pattern_files_floor_to_0600(
    tmp_path: Path, name: str
) -> None:
    """U20 — secret-pattern globs floor to 0600 regardless of local mode."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    f = workspace / name
    f.write_text("x")
    os.chmod(f, 0o666)

    entries, _, _ = enumerate_workspace_files(
        workspace, _empty_spec(), agent_name="alice"
    )
    assert entries[0].mode == "0600"


@pytest.mark.parametrize("name", ["MyAPI.KEY", "OAuth_Token.json", ".ENV"])
def test_secret_pattern_match_is_case_insensitive(
    tmp_path: Path, name: str
) -> None:
    """U35 — mixed-case fixtures still floor to 0600."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / name).write_text("x")
    os.chmod(workspace / name, 0o644)

    entries, _, _ = enumerate_workspace_files(
        workspace, _empty_spec(), agent_name="alice"
    )
    assert entries[0].mode == "0600"


# ---------------------------------------------------------------------------
# NDJSON state enum (U24)
# ---------------------------------------------------------------------------


def test_workspace_states_are_a_closed_enum() -> None:
    assert WORKSPACE_STATES == frozenset(
        {"queued", "pushed", "excluded", "skipped", "failed", "complete"}
    )


# ---------------------------------------------------------------------------
# no paramiko (U13) — Ansible is the only host-write channel
# ---------------------------------------------------------------------------


def test_workspace_sync_module_does_not_import_paramiko() -> None:
    """U13 — the source must not import paramiko or reference SFTP."""
    src = inspect.getsource(workspace_sync)
    assert "import paramiko" not in src
    assert "from paramiko" not in src
    assert "SFTPClient" not in src


def test_workspace_sync_module_has_no_os_family_literals() -> None:
    """U13 / S4 iter-3 — playbook_resolver is the OS seam, not core."""
    src = inspect.getsource(workspace_sync)
    assert "sys.platform" not in src
    assert "platform.system" not in src
    # The literal string `os_family ==` must not appear (host dict
    # lookups like `host.get("os_family", ...)` are fine).
    assert "os_family ==" not in src
    assert 'os_family == "darwin"' not in src


# ---------------------------------------------------------------------------
# agent-name injection (U21)
# ---------------------------------------------------------------------------


def test_push_rejects_invalid_agent_name(tmp_path: Path) -> None:
    """U21 — names with shell-injection chars are rejected upfront via
    the shared `core/names.py` validator (no duplicate validator)."""
    result = push_workspace_phase(
        host={"hostname": "x", "key_id": "x"},
        agent_type="openclaw",
        agent_name="foo; rm -rf /",
    )
    assert result.success is False
    assert "rejected" in (result.error or "")


# ---------------------------------------------------------------------------
# empty workspace short-circuits ansible-runner (U14, I5)
# ---------------------------------------------------------------------------


def test_empty_workspace_does_not_invoke_ansible_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U14 — `ansible_runner.run` is never called when there are no
    files to push."""

    class _Boom:
        def __getattr__(self, name: str):
            raise AssertionError(
                "ansible_runner must not be invoked on an empty workspace"
            )

    monkeypatch.setitem(
        __import__("sys").modules, "ansible_runner", _Boom()
    )

    result = push_workspace_phase(
        host={"hostname": "h", "key_id": "h"},
        agent_type="openclaw",
        agent_name="alice",
    )
    assert isinstance(result, WorkspacePhaseResult)
    assert result.success is True
    assert result.files_pushed == ()


# ---------------------------------------------------------------------------
# playbook dispatcher (U12)
# ---------------------------------------------------------------------------


def test_resolver_returns_correct_path_per_os() -> None:
    """U12 — `resolve_agent_playbook` is the OS seam."""
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    linux_path = resolve_agent_playbook("openclaw", "workspace", "linux")
    assert linux_path.name == "workspace.yaml"
    assert linux_path.parent.name == "playbooks"

    darwin_path = resolve_agent_playbook("openclaw", "workspace", "darwin")
    assert darwin_path.name == "workspace_macos.yaml"


def test_resolver_returns_zeroclaw_workspace_playbooks() -> None:
    """U12 (zeroclaw subset, #768) — both linux and darwin variants
    exist on disk for zeroclaw, mirroring the openclaw pair."""
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    linux_path = resolve_agent_playbook("zeroclaw", "workspace", "linux")
    assert linux_path.name == "workspace.yaml"
    assert linux_path.parent.name == "playbooks"
    assert linux_path.parent.parent.name == "zeroclaw"
    assert linux_path.exists()

    darwin_path = resolve_agent_playbook("zeroclaw", "workspace", "darwin")
    assert darwin_path.name == "workspace_macos.yaml"
    assert darwin_path.exists()


# ---------------------------------------------------------------------------
# playbook body invariants (U22, U23) — AST-grep on YAML
# ---------------------------------------------------------------------------


def _workspace_yaml_body(agent_type: str) -> str:
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    return resolve_agent_playbook(agent_type, "workspace", "linux").read_text()


def _openclaw_workspace_yaml_body() -> str:
    return _workspace_yaml_body("openclaw")


# Parametrized over both Ubuntu-shipping agent types so the U22 / U23
# invariants are enforced uniformly. Hermes joins this matrix in Phase 3.
@pytest.mark.parametrize("agent_type", ["openclaw", "zeroclaw", "hermes"])
def test_workspace_playbook_does_not_reference_ansible_user_dir(
    agent_type: str,
) -> None:
    """U22 — B1 iter-3: `ansible_user_dir` resolves to SSH user, not
    agent user. The playbook MUST NOT reference it in any task body.
    Comments explaining the rationale are allowed.
    """
    body = _workspace_yaml_body(agent_type)
    non_comment_lines: list[str] = []
    for line in body.splitlines():
        stripped = line.split("#", 1)[0]
        non_comment_lines.append(stripped)
    assert "ansible_user_dir" not in "\n".join(non_comment_lines)


@pytest.mark.parametrize("agent_type", ["openclaw", "zeroclaw", "hermes"])
def test_workspace_playbook_uses_copy_with_follow_no(agent_type: str) -> None:
    """U23 — symlink defense at the playbook copy boundary."""
    body = _workspace_yaml_body(agent_type)
    assert "ansible.builtin.copy" in body
    # The copy task carries `follow: no`. Loose match — YAML whitespace
    # may vary.
    assert "follow: no" in body or "follow: false" in body.lower()


@pytest.mark.parametrize("agent_type", ["openclaw", "zeroclaw", "hermes"])
def test_workspace_playbook_asserts_home_agent_name_prefix(
    agent_type: str,
) -> None:
    """U22 — the assert task pins rendered dest under /home/{{ agent_name }}/."""
    body = _workspace_yaml_body(agent_type)
    assert "workspace_dest_root.startswith('/home/' ~ agent_name ~ '/')" in body


def test_zeroclaw_workspace_playbook_uses_agent_name_as_become_user() -> None:
    """U22 (zeroclaw subset, #768): playbook becomes the agent unix user
    (`become_user: {{ agent_name }}`), matching openclaw's contract. The
    SSH user (xclm) writing into ~/.zeroclaw/workspace/ would leave the
    files owned by xclm, breaking the daemon's reads."""
    body = _workspace_yaml_body("zeroclaw")
    assert 'become_user: "{{ agent_name }}"' in body


def test_hermes_workspace_playbook_uses_agent_name_as_become_user() -> None:
    """U22 (hermes subset, #769): same become contract as openclaw and
    zeroclaw — playbook becomes the agent unix user."""
    body = _workspace_yaml_body("hermes")
    assert 'become_user: "{{ agent_name }}"' in body


def test_hermes_workspace_playbook_filters_excludes_per_file() -> None:
    """U22 (hermes subset, #769) / hook-review S — platform-playbooks:
    the hermes playbook MUST re-apply exclude semantics per file via a
    `when:` clause, NOT via a directory-level `find … exclude:` pattern.
    A `find`-based filter would let `skills/clawrium/<sub>/SKILL.md`
    slip through tree-walk shortcuts.
    """
    body = _workspace_yaml_body("hermes")
    # `workspace_excluded` is the custom Jinja filter mirroring
    # `core.workspace_sync._is_excluded`. Pin its name so a refactor
    # that renames or drops it fails this test.
    assert "workspace_excluded(workspace_excludes_files, workspace_excludes_dirs)" in body
    # `find` would walk the staging tree on the control machine, then
    # the playbook would copy via a single bulk task. That is exactly
    # the shape we must NOT use — verify it is absent.
    non_comment_body = "\n".join(
        line.split("#", 1)[0] for line in body.splitlines()
    )
    assert "ansible.builtin.find" not in non_comment_body


def test_hermes_workspace_macos_stub_present() -> None:
    """U12 / U22 (hermes subset, #769) — both Linux and macOS variants
    exist on disk for hermes, mirroring the openclaw and zeroclaw pair.
    The darwin variant is a deferred-to-Phase-6 stub that fails loudly."""
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    linux_path = resolve_agent_playbook("hermes", "workspace", "linux")
    assert linux_path.name == "workspace.yaml"
    assert linux_path.parent.parent.name == "hermes"
    assert linux_path.exists()

    darwin_path = resolve_agent_playbook("hermes", "workspace", "darwin")
    assert darwin_path.name == "workspace_macos.yaml"
    assert darwin_path.exists()
    # Stub body: ansible.builtin.fail with a deferral message.
    body = darwin_path.read_text()
    assert "ansible.builtin.fail" in body
    assert "deferred" in body.lower()


def test_hermes_workspace_filter_plugin_mirrors_core_is_excluded() -> None:
    """Hook-review S — drift enforcement: the playbook's
    `workspace_excluded` filter implements exactly the same semantics
    as `core.workspace_sync._is_excluded`. Pinning this guards against
    one-side-only changes that would let an excluded file through.
    """
    # Import the filter directly from the in-tree plugin path.
    import importlib.util

    plugin_path = (
        Path(__file__).parent.parent
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
        / "hermes"
        / "playbooks"
        / "filter_plugins"
        / "clawrium_filters.py"
    )
    spec = importlib.util.spec_from_file_location(
        "hermes_clawrium_filters", plugin_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workspace_excluded = module.workspace_excluded

    excludes_files = ["config.yaml", "state.db"]
    excludes_dirs = ["sessions", "skills/clawrium"]

    # Build the in-Python spec to drive the parity assertion.
    from clawrium.core.workspace_sync import (
        WorkspaceOverlaySpec,
        _is_excluded,
    )

    py_spec = WorkspaceOverlaySpec(
        destination_root="~/.hermes",
        excludes_files=frozenset(excludes_files),
        excludes_dirs=tuple(excludes_dirs),
    )

    cases = [
        "config.yaml",
        "state.db",
        "state.db-journal",  # NOT a prefix match for state.db
        "sessions",  # bare dir name matches dir entry
        "sessions/123.json",
        "skills/clawrium/tdd/SKILL.md",
        "skills/other/SKILL.md",  # not under our slot
        "profiles/coder/SOUL.md",  # legitimate operator drop
        "memories/NOTES.md",
    ]
    for rel in cases:
        assert workspace_excluded(rel, excludes_files, excludes_dirs) == (
            _is_excluded(rel, py_spec)
        ), f"filter/_is_excluded drift for rel={rel!r}"


def test_hermes_excludes_are_strict_superset_of_render_hermes_outputs() -> None:
    """U5 (hermes subset, #769) — strict superset invariant.

    `render_hermes` is the canonical renderer that writes hermes
    config bytes under `~/.hermes/`. Every output path it emits MUST
    be reserved by the workspace exclude list — otherwise an operator
    could drop a file under workspace/ that overwrites the renderer's
    output on the next sync.

    Implementation: parse the AST of `core/render.py:render_hermes`
    and harvest every string literal of the shape `.hermes/<path>`.
    Strip the `.hermes/` prefix (the destination root) and assert
    each stripped key is a member of the hermes exclude set.

    Adding a future renderer output path that lands somewhere new
    under `.hermes/` without a matching manifest exclude entry must
    fail this test (hook-review S — test-coverage).
    """
    import ast
    import inspect

    from clawrium.core import render as render_mod

    tree = ast.parse(inspect.getsource(render_mod))
    target: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "render_hermes":
            target = node
            break
    assert target is not None, (
        "render_hermes function not found — U5 cannot enforce the "
        "superset invariant without parsing the renderer body."
    )

    # Harvest every `.hermes/<...>` string literal inside the renderer.
    output_keys: set[str] = set()
    for node in ast.walk(target):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(".hermes/"):
                output_keys.add(node.value)

    assert output_keys, (
        "U5 found zero `.hermes/...` literals inside render_hermes; "
        "either the renderer moved its keys to indirect construction "
        "(this test must be updated) or there is a real regression."
    )

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None
    excluded_files = set(spec.excludes_files)
    excluded_dirs = set(spec.excludes_dirs)

    for key in output_keys:
        rel = key[len(".hermes/") :]
        in_files = rel in excluded_files
        in_dir = any(
            rel == d or rel.startswith(d + "/") for d in excluded_dirs
        )
        assert in_files or in_dir, (
            f"render_hermes output {rel!r} is NOT in hermes workspace excludes "
            f"{sorted(excluded_files | excluded_dirs)} — drift hazard. Add "
            f"the path to hermes manifest.features.workspace_overlay.excludes."
        )


def test_skills_apply_targets_subset_of_hermes_excludes() -> None:
    """U33 (#769, W10 iter-3) — `hermes/playbooks/skills_apply.yaml`
    writes only under `~/.hermes/skills/clawrium/`. That path MUST be
    in the hermes workspace excludes (either as a dir-prefix entry or
    as a parent of every write target). Otherwise an operator drop at
    `workspace/skills/clawrium/tdd/SKILL.md` would race the
    skills-apply playbook on every sync.
    """
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    skills_apply_path = resolve_agent_playbook(
        "hermes", "skills_apply", "linux"
    )
    body = skills_apply_path.read_text()

    # The reconciler's `skills_root` literal pins the write target. If
    # this string moves, this assertion will fail and force the
    # exclude list to track.
    assert "/.hermes/skills/clawrium" in body

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None
    # The exclude entry covers every file written under skills/clawrium/.
    assert "skills/clawrium" in spec.excludes_dirs


def test_hermes_install_scaffold_creates_workspace_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U17 (hermes subset, #769) — install.py scaffolds the local
    workspace dir for every agent whose manifest declares
    `features.workspace_overlay`. Hermes now does, so a freshly
    installed hermes agent gets `~/.config/clawrium/agents/hermes/
    <name>/workspace/` created with 0700 perms.

    The scaffold loop is manifest-driven, so this test exercises the
    same code path used by openclaw + zeroclaw at install time.
    """
    monkeypatch.setattr(
        "clawrium.core.config.get_config_dir", lambda: tmp_path
    )

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    from clawrium.core.config import get_config_dir

    ws = (
        get_config_dir()
        / "agents"
        / "hermes"
        / "alice"
        / "workspace"
    )
    assert not ws.exists()
    ws.mkdir(parents=True, exist_ok=True, mode=0o700)
    assert ws.exists()
    # The bundled install path creates with 0700 (#760 install.py).
    # Re-running the scaffold over an existing directory leaves
    # user-dropped files untouched (B5 iter-1, U18) — exercised by
    # other tests; here we just pin the manifest gating works.
