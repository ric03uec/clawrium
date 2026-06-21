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
@pytest.mark.parametrize("agent_type", ["openclaw", "zeroclaw"])
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


@pytest.mark.parametrize("agent_type", ["openclaw", "zeroclaw"])
def test_workspace_playbook_uses_copy_with_follow_no(agent_type: str) -> None:
    """U23 — symlink defense at the playbook copy boundary."""
    body = _workspace_yaml_body(agent_type)
    assert "ansible.builtin.copy" in body
    # The copy task carries `follow: no`. Loose match — YAML whitespace
    # may vary.
    assert "follow: no" in body or "follow: false" in body.lower()


@pytest.mark.parametrize("agent_type", ["openclaw", "zeroclaw"])
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
    assert "become: yes" in body
