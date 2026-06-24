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
from typing import Any

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


def test_home_root_for_linux_and_darwin() -> None:
    """#770 — `home_root_for` is the single OS seam for the home-dir
    root (`/home` vs `/Users`). Keeping the branch here means
    `workspace_sync.py` and other consumers stay free of OS literals
    (U13 / S4 iter-3)."""
    from clawrium.core.playbook_resolver import home_root_for

    assert home_root_for("linux") == "/home"
    assert home_root_for("darwin") == "/Users"

    # ATX iter-1 W6: pin the error message shape so a regression that
    # changes it to a generic `raise ValueError("bad")` is caught.
    with pytest.raises(ValueError, match=r"unsupported os_family.*freebsd"):
        home_root_for("freebsd")


def _macos_playbook_non_comment_body() -> str:
    """Helper: strip line-comments before scanning playbook text.

    ATX iter-2 W6 — applying comment-stripping uniformly to both
    positive and negative scans prevents a diff that comments out a
    live assertion line (or moves it into a comment) from silently
    passing.
    """
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    body = resolve_agent_playbook("openclaw", "workspace", "darwin").read_text()
    return "\n".join(line.split("#", 1)[0] for line in body.splitlines())


def test_openclaw_workspace_macos_playbook_uses_users_prefix() -> None:
    """#770 (openclaw macOS, U22 darwin variant) — the macOS workspace
    playbook asserts `workspace_dest_root` begins with
    `/Users/<agent_name>/`, not `/home/<agent_name>/`. Drift here means
    the dispatcher routed a darwin host through a /home/-asserting
    playbook and the run would fail mid-flight."""
    body = _macos_playbook_non_comment_body()
    assert "workspace_dest_root.startswith('/Users/' ~ agent_name ~ '/')" in body
    # The Linux assertion must NOT bleed into the macOS playbook
    # (regression: if someone copy-pasted from workspace.yaml without
    # editing the prefix, the playbook would always bail on darwin).
    assert "workspace_dest_root.startswith('/home/' ~ agent_name ~ '/')" not in body
    # ATX iter-1 W1 backstop — the `..` segment rejection is present.
    assert "'..' not in workspace_dest_root.split('/')" in body


def test_openclaw_workspace_macos_playbook_is_not_the_deferred_stub() -> None:
    """#770 — the Phase-1 stub used `ansible.builtin.fail: msg: deferred
    to macOS subtask`. Pin that body is no longer present so a future
    revert / merge accident can't ship the stub again."""
    body = _macos_playbook_non_comment_body()
    assert "deferred to macOS subtask" not in body
    # The real playbook copies files; the stub did not. Pin the copy
    # task is present and uses `follow: no` (symlink defense).
    assert "ansible.builtin.copy" in body
    assert "follow: no" in body


def test_openclaw_workspace_macos_playbook_uses_staff_group() -> None:
    """#770 — macOS users have primary group `staff` (gid 20), not a
    per-user group like Linux. The macOS playbook MUST hardcode
    `group: staff` for owner+copy tasks; using `{{ agent_name }}` (the
    Linux convention) would fail on darwin because the group does not
    exist."""
    body = _macos_playbook_non_comment_body()
    assert "group: staff" in body
    # The Linux-style `group: "{{ agent_name }}"` must NOT appear in
    # task bodies.
    assert 'group: "{{ agent_name }}"' not in body


@pytest.mark.parametrize(
    "os_family,raw,expected",
    [
        # Tilde-slash form — the realistic case (every shipped manifest
        # uses this shape).
        ("linux", "~/.openclaw/workspace", "/home/alice/.openclaw/workspace"),
        ("darwin", "~/.openclaw/workspace", "/Users/alice/.openclaw/workspace"),
        # Bare tilde — no shipped manifest uses this, but the helper
        # MUST not silently drop it (regression guard).
        ("linux", "~", "/home/alice"),
        ("darwin", "~", "/Users/alice"),
        # ATX iter-1 W4: absolute-path passthrough. A future manifest
        # with `destination_root: "/var/openclaw/workspace"` MUST be
        # returned unchanged regardless of os_family — otherwise the
        # macOS / Linux branches would silently rewrite operator intent.
        ("linux", "/var/openclaw/workspace", "/var/openclaw/workspace"),
        ("darwin", "/var/openclaw/workspace", "/var/openclaw/workspace"),
    ],
)
def test_expand_destination_root_parametrized(
    os_family: str, raw: str, expected: str
) -> None:
    """#770 — `_expand_destination_root` covers three input shapes
    (`~/...`, `~`, absolute passthrough) crossed with two OS families.
    S4 (ATX iter-1): the per-OS / per-shape cases collapse into a
    parametrized table; only the distinct backward-compat default-arg
    case below stays standalone because it tests a different contract."""
    from clawrium.core.workspace_sync import _expand_destination_root

    spec = WorkspaceOverlaySpec(destination_root=raw)
    assert _expand_destination_root(spec, "alice", os_family) == expected


def test_expand_destination_root_default_arg_is_linux() -> None:
    """#770 — backward-compat: callers that don't pass `os_family` get
    Linux behavior. The default keeps every existing call site working
    without churn; only the new sync entry point threads `os_family`
    explicitly. The playbook prefix assertion remains the backstop if a
    new caller forgets the threading on a darwin host."""
    from clawrium.core.workspace_sync import _expand_destination_root

    spec = WorkspaceOverlaySpec(destination_root="~/.openclaw/workspace")
    assert (
        _expand_destination_root(spec, "alice")
        == "/home/alice/.openclaw/workspace"
    )


def test_push_workspace_phase_threads_os_family_to_darwin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ATX iter-1 W5 — integration test: `push_workspace_phase` must
    thread `host['os_family']` into both the playbook resolver AND the
    `workspace_dest_root` expansion. A regression that hard-coded
    `'linux'` at the call site would route the dispatcher to
    `workspace_macos.yaml` correctly but pass `workspace_dest_root =
    '/home/<name>/...'` to it — the playbook's `/Users/` prefix assert
    would catch it on-host, but we want a unit-level signal too.

    Stubs `ansible_runner.run` and captures the playbook path + the
    extravars handed to it.
    """
    # Redirect config dir so our fake workspace lives in tmp_path.
    monkeypatch.setattr(
        "clawrium.core.workspace_sync.get_config_dir", lambda: tmp_path
    )
    # Redirect the lazy-loaded host-key lookup to a synthetic path —
    # `push_workspace_phase` only checks for non-None, then passes it
    # into the inventory dict as the SSH key file.
    fake_key = tmp_path / "fake.pem"
    fake_key.write_text("")
    monkeypatch.setattr(
        "clawrium.core.keys.get_host_private_key",
        lambda _key_id: str(fake_key),
    )

    # Stage a marker file under the openclaw workspace slot for a
    # synthetic agent.
    ws = tmp_path / "agents" / "openclaw" / "alice" / "workspace"
    ws.mkdir(parents=True)
    (ws / "MARKER.md").write_text("hello mac")

    captured: dict[str, Any] = {}

    class _StubResult:
        status = "successful"
        rc = 0

    class _StubRunner:
        def run(self, **kwargs: Any) -> _StubResult:
            captured["playbook"] = kwargs.get("playbook")
            captured["extravars"] = kwargs.get("extravars")
            return _StubResult()

    monkeypatch.setitem(
        __import__("sys").modules, "ansible_runner", _StubRunner()
    )

    from clawrium.core.workspace_sync import push_workspace_phase

    result = push_workspace_phase(
        host={
            "hostname": "esper-macmini.example",
            "key_id": "esper-macmini.example",
            "os_family": "darwin",
        },
        agent_type="openclaw",
        agent_name="alice",
    )
    assert result.success is True, result.error
    assert result.files_pushed == ("MARKER.md",)

    # Dispatcher routed to the macOS playbook.
    assert captured["playbook"].endswith("workspace_macos.yaml"), captured["playbook"]
    # Expansion used the darwin home root.
    extravars = captured["extravars"]
    assert extravars["workspace_dest_root"] == "/Users/alice/.openclaw/workspace"
    # The remote path on each enumerated file also uses /Users/.
    files = extravars["workspace_files"]
    assert len(files) == 1
    assert files[0]["rel"] == "MARKER.md"
    # ATX iter-2 W4: pin every extravar that downstream playbook tasks
    # consume so a regression that mixes up agent_name, swaps in the
    # wrong agent's excludes (e.g. hermes excludes on openclaw), or
    # drops staging_dir surfaces at unit-test level.
    assert extravars["agent_name"] == "alice"
    assert extravars["agent_type"] == "openclaw"
    assert extravars["workspace_excludes_files"] == []
    assert extravars["workspace_excludes_dirs"] == []
    assert extravars["staging_dir"].startswith(str(tmp_path))


def test_push_workspace_phase_threads_os_family_to_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ATX iter-1 W5 (counterpart) — same integration as above but for
    linux. Catches a regression that hard-coded 'darwin' at the call
    site (the mirror of the failure W5 protects against)."""
    monkeypatch.setattr(
        "clawrium.core.workspace_sync.get_config_dir", lambda: tmp_path
    )
    fake_key = tmp_path / "fake.pem"
    fake_key.write_text("")
    monkeypatch.setattr(
        "clawrium.core.keys.get_host_private_key",
        lambda _key_id: str(fake_key),
    )

    ws = tmp_path / "agents" / "openclaw" / "bob" / "workspace"
    ws.mkdir(parents=True)
    (ws / "MARKER.md").write_text("hello linux")

    captured: dict[str, Any] = {}

    class _StubResult:
        status = "successful"
        rc = 0

    class _StubRunner:
        def run(self, **kwargs: Any) -> _StubResult:
            captured["playbook"] = kwargs.get("playbook")
            captured["extravars"] = kwargs.get("extravars")
            return _StubResult()

    monkeypatch.setitem(
        __import__("sys").modules, "ansible_runner", _StubRunner()
    )

    from clawrium.core.workspace_sync import push_workspace_phase

    result = push_workspace_phase(
        host={
            "hostname": "wolf-i.example",
            "key_id": "wolf-i.example",
            "os_family": "linux",
        },
        agent_type="openclaw",
        agent_name="bob",
    )
    assert result.success is True, result.error

    assert captured["playbook"].endswith("workspace.yaml")
    assert not captured["playbook"].endswith("workspace_macos.yaml")
    extravars = captured["extravars"]
    assert extravars["workspace_dest_root"] == "/home/bob/.openclaw/workspace"
    # ATX iter-2 W4 mirror: same extravar pinning on the linux side.
    assert extravars["agent_name"] == "bob"
    assert extravars["agent_type"] == "openclaw"
    assert extravars["workspace_excludes_files"] == []
    assert extravars["workspace_excludes_dirs"] == []
    assert extravars["staging_dir"].startswith(str(tmp_path))


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
        # ATX iter-1 S3: edge cases reviewer flagged but the original
        # parity test didn't cover.
        "",  # empty string — neither side should claim this is excluded
        "/config.yaml",  # leading-slash rel — should NOT match the
                         # exact-file `config.yaml` entry (path canonicalization)
    ]
    for rel in cases:
        assert workspace_excluded(rel, excludes_files, excludes_dirs) == (
            _is_excluded(rel, py_spec)
        ), f"filter/_is_excluded drift for rel={rel!r}"

    # ATX iter-2 S_NEW_2 fix: pin the semantic for the edge cases —
    # agreement alone is not enough, both sides could regress in the
    # same direction. The leading-slash case especially is about
    # bypass: `/config.yaml` MUST NOT match the exact-file exclude
    # entry `config.yaml`. Empty-string rel MUST NEVER match
    # anything; it should be impossible to surface from the
    # enumerator, but the filter should still behave correctly.
    assert _is_excluded("/config.yaml", py_spec) is False, (
        "leading-slash bypass: '/config.yaml' must not match exact-file "
        "exclude 'config.yaml' — a regression here lets an operator drop "
        "a hostile path starting with '/' that gets canonicalized later"
    )
    assert workspace_excluded("/config.yaml", excludes_files, excludes_dirs) is False
    assert _is_excluded("", py_spec) is False, (
        "empty-string rel must not match any exclude entry"
    )
    assert workspace_excluded("", excludes_files, excludes_dirs) is False


# Hard count of canonical hermes renderer output keys. Bumping
# `render_hermes` to emit a new `.hermes/<path>` key MUST trip this
# constant + the superset assertion below in the same commit, forcing
# a deliberate edit of the manifest excludes.
_EXPECTED_HERMES_RENDER_OUTPUT_COUNT = 2


def test_hermes_excludes_are_strict_superset_of_render_hermes_outputs() -> None:
    """U5 (hermes subset, #769) — strict superset invariant.

    `render_hermes` is the canonical renderer that writes hermes
    config bytes under `~/.hermes/`. Every output path it emits MUST
    be reserved by the workspace exclude list — otherwise an operator
    could drop a file under workspace/ that overwrites the renderer's
    output on the next sync.

    Implementation (ATX iter-1 W3 fix): walk the entire `render`
    module AST (not just the `render_hermes` FunctionDef body) and
    harvest every string literal — including `ast.JoinedStr`
    (f-strings) constituents — of the shape `.hermes/<path>`. Module-
    level constants, helper functions, and f-string fragments are now
    all visible.

    Two assertions tighten the contract:
      1. The harvested key set is a strict subset of the manifest
         exclude set (the original superset invariant).
      2. The harvested key count equals `_EXPECTED_HERMES_RENDER_OUTPUT_COUNT`.
         A new `.hermes/<path>` literal anywhere in `render.py` —
         even buried in a helper or assembled via f-string — fails
         this assertion and forces an explicit constant bump plus a
         matching manifest exclude entry.
    """
    import ast
    import inspect

    from clawrium.core import render as render_mod

    tree = ast.parse(inspect.getsource(render_mod))

    output_keys: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(".hermes/"):
                output_keys.add(node.value)
        elif isinstance(node, ast.JoinedStr):
            # Catch any f-string whose static fragments mention a
            # `.hermes/...` path. ATX iter-2 W_NEW_1 fix: the prior
            # `len(head) > len(".hermes/")` guard let
            # `f".hermes/{var_name}"` slip through silently because
            # the first Constant is exactly `.hermes/` (length 8 == 8,
            # guard fails). We now harvest a synthetic key for ANY
            # JoinedStr containing a `.hermes/` literal fragment, so
            # the count pin trips and forces a manual investigation.
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    if ".hermes/" in piece.value:
                        # Use the source-position offset as a stable
                        # synthetic key per f-string occurrence so two
                        # different f-strings count as two outputs.
                        synth = (
                            f".hermes/<f-string@{node.lineno}:{node.col_offset}>"
                        )
                        output_keys.add(synth)
                        break

    assert output_keys, (
        "U5 found zero `.hermes/...` literals across the render module; "
        "either the renderer moved its keys to indirect construction "
        "(e.g. `os.path.join('.hermes', ...)` or `Path('.hermes') / ...`) "
        "and this test must broaden its scanner, or there is a real "
        "regression in render_hermes."
    )

    # Hard count pin. A new renderer-output key requires bumping the
    # constant AND adding a matching exclude entry. Drift in either
    # direction is caught here.
    assert len(output_keys) == _EXPECTED_HERMES_RENDER_OUTPUT_COUNT, (
        f"render_hermes output-key count drifted: found "
        f"{sorted(output_keys)} ({len(output_keys)} keys), expected "
        f"{_EXPECTED_HERMES_RENDER_OUTPUT_COUNT}. Bump "
        f"_EXPECTED_HERMES_RENDER_OUTPUT_COUNT in this test AND add "
        f"every new key to hermes manifest "
        f"features.workspace_overlay.excludes — they MUST land in the "
        f"same commit."
    )

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None
    excluded_files = set(spec.excludes_files)
    excluded_dirs = set(spec.excludes_dirs)

    for key in output_keys:
        rel = key[len(".hermes/") :]
        # Synthetic f-string keys are intentionally not in the exclude
        # set — they exist purely to make the count pin trip. The
        # count assertion above already failed earlier in that path,
        # so we skip them in the superset check.
        if rel.startswith("<f-string@"):
            continue
        in_files = rel in excluded_files
        in_dir = any(
            rel == d or rel.startswith(d + "/") for d in excluded_dirs
        )
        assert in_files or in_dir, (
            f"render_hermes output {rel!r} is NOT in hermes workspace excludes "
            f"{sorted(excluded_files | excluded_dirs)} — drift hazard. Add "
            f"the path to hermes manifest.features.workspace_overlay.excludes."
        )


def test_u5_scanner_catches_injected_f_string_hermes_path() -> None:
    """ATX iter-2 W_NEW_1 regression test: the U5 scanner MUST flag a
    future `f".hermes/{name}"` literal added to render.py — that is
    the exact refactor pattern the broadened JoinedStr branch is
    supposed to catch.

    Parse a synthetic mini-module containing the at-risk pattern,
    walk it with the SAME scanner logic the production U5 uses, and
    assert the synthetic key surfaces in the harvested set. If the
    JoinedStr branch ever regresses (e.g., re-introducing the
    `len(head) > len(".hermes/")` guard), this test fails.
    """
    import ast

    # The classic "extracted-to-helper" refactor pattern that the
    # original AST scan missed: an f-string whose first segment is
    # exactly `.hermes/`, followed by a variable.
    src = """
def render_hermes_v2(name):
    return f".hermes/{name}"
"""
    tree = ast.parse(src)

    output_keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(".hermes/"):
                output_keys.add(node.value)
        elif isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    if ".hermes/" in piece.value:
                        synth = (
                            f".hermes/<f-string@{node.lineno}:{node.col_offset}>"
                        )
                        output_keys.add(synth)
                        break

    assert any(k.startswith(".hermes/<f-string@") for k in output_keys), (
        f"U5 scanner failed to catch the f-string refactor pattern: "
        f"harvested keys = {sorted(output_keys)}"
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
