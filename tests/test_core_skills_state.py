"""Tests for the per-agent skills desired-state store.

Covers the per-agent local skill desired-state store:
- state file path is XDG-respecting and namespaced by agent name
- read/write round-trips bare local skill names and rejects registry refs,
  URLs, paths, uppercase names, and malformed JSON
- add/remove are idempotent and report whether the call changed state
- atomic writes (no `.tmp` left behind on success; concurrent reader
  never sees an empty file)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawrium.core.skills import InvalidSkillRef
from clawrium.core import skills_state
from clawrium.core.skills_state import (
    add_skill,
    agent_skills_dir,
    read_state,
    remove_skill,
    state_file_path,
    write_state,
)


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point clawrium config at a tmp dir so tests never mutate ~/."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield


# ------------------------------- state_file_path ----------------------------


def test_state_file_path_uses_xdg(tmp_path: Path):
    path = state_file_path("hermes-tdd")
    assert path == tmp_path / "clawrium" / "agents" / "hermes-tdd" / "skills.json"


def test_agent_skills_dir_uses_xdg(tmp_path: Path):
    path = agent_skills_dir("hermes-tdd")
    assert path == tmp_path / "clawrium" / "agents" / "hermes-tdd" / "skills"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "Cap",  # uppercase
        "1agent",  # starts with digit
        "agent$name",  # special chars
        "x" * 33,  # too long
        "../escape",
    ],
)
def test_state_file_path_rejects_bad_agent_name(bad):
    with pytest.raises(InvalidSkillRef):
        state_file_path(bad)


def test_agent_skills_dir_rejects_bad_agent_name():
    with pytest.raises(InvalidSkillRef):
        agent_skills_dir("../escape")


# ------------------------------- read_state ---------------------------------


def test_read_state_missing_file_returns_empty():
    assert read_state("hermes-tdd") == []


def test_read_state_round_trips_after_write():
    write_state("hermes-tdd", ["tdd"])
    assert read_state("hermes-tdd") == ["tdd"]


def test_read_state_returns_sorted_deduped():
    write_state("hermes-tdd", ["zebra", "tdd", "tdd"])
    assert read_state("hermes-tdd") == ["tdd", "zebra"]


def test_read_state_malformed_json_raises():
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text("{not-json")
    with pytest.raises(InvalidSkillRef, match="not valid JSON"):
        read_state("hermes-tdd")


def test_read_state_non_object_root_raises():
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(["tdd"]))
    with pytest.raises(InvalidSkillRef, match="must be a JSON object"):
        read_state("hermes-tdd")


def test_read_state_skills_field_must_be_list_of_strings():
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"skills": [{"ref": "tdd"}]}))
    with pytest.raises(InvalidSkillRef, match="list of strings"):
        read_state("hermes-tdd")


def test_read_state_revalidates_persisted_entries():
    """Hand-edited file with an invalid ref must surface as an error
    on read, not silently propagate to apply_state."""
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"skills": ["http://evil.example/skill"]}))
    with pytest.raises(InvalidSkillRef, match="Invalid skill name"):
        read_state("hermes-tdd")


def test_read_state_rejects_legacy_registry_ref_with_remediation():
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"skills": ["clawrium/tdd"]}))
    with pytest.raises(InvalidSkillRef, match="--from-template"):
        read_state("hermes-tdd")


# ------------------------------- write_state --------------------------------


def test_write_state_creates_parent_dir(tmp_path: Path):
    write_state("hermes-tdd", ["tdd"])
    parent = tmp_path / "clawrium" / "agents" / "hermes-tdd"
    assert parent.is_dir()


def test_write_state_persists_canonical_form():
    canonical = write_state("hermes-tdd", ["zebra", "tdd", "tdd"])
    raw = json.loads(state_file_path("hermes-tdd").read_text())
    assert canonical == ["tdd", "zebra"]
    assert raw == {"skills": ["tdd", "zebra"]}


def test_write_state_accepts_bare_name_in_payload():
    assert write_state("hermes-tdd", ["tdd"]) == ["tdd"]


def test_write_state_rejects_registry_ref_in_payload():
    with pytest.raises(InvalidSkillRef, match="--from-template"):
        write_state("hermes-tdd", ["clawrium/tdd"])


def test_write_state_rejects_url_in_payload():
    with pytest.raises(InvalidSkillRef):
        write_state("hermes-tdd", ["https://example.com/skill.tgz"])


@pytest.mark.parametrize("bad", ["", "UPPER", "bad name", "../escape", "tdd/extra"])
def test_write_state_rejects_invalid_local_names(bad: str):
    with pytest.raises(InvalidSkillRef):
        write_state("hermes-tdd", [bad])


def test_write_state_leaves_no_tmp_files_on_success(tmp_path: Path):
    write_state("hermes-tdd", ["tdd"])
    parent = tmp_path / "clawrium" / "agents" / "hermes-tdd"
    leftovers = [p for p in parent.iterdir() if p.name.startswith(".skills.")]
    assert leftovers == []


def test_write_state_atomic_against_failure(monkeypatch, tmp_path: Path):
    """If os.replace raises, the tempfile should be unlinked so we
    don't leave half-written staging files lying around."""
    real_replace = skills_state.os.replace

    def boom(_src, _dst):  # type: ignore[no-untyped-def]
        raise OSError("simulated rename failure")

    monkeypatch.setattr(skills_state.os, "replace", boom)
    with pytest.raises(OSError):
        write_state("hermes-tdd", ["tdd"])
    monkeypatch.setattr(skills_state.os, "replace", real_replace)

    parent = tmp_path / "clawrium" / "agents" / "hermes-tdd"
    if parent.is_dir():
        leftovers = [p for p in parent.iterdir() if p.name.startswith(".skills.")]
        assert leftovers == []


# ------------------------------- add_skill / remove_skill -------------------


def test_add_skill_returns_added_flag_on_new_entry():
    state, added = add_skill("hermes-tdd", "tdd")
    assert added is True
    assert state == ["tdd"]


def test_add_skill_is_idempotent():
    add_skill("hermes-tdd", "tdd")
    state, added = add_skill("hermes-tdd", "tdd")
    assert added is False
    assert state == ["tdd"]


def test_add_skill_rejects_registry_ref():
    with pytest.raises(InvalidSkillRef, match="--from-template"):
        add_skill("hermes-tdd", "clawrium/tdd")


def test_remove_skill_returns_removed_flag():
    add_skill("hermes-tdd", "tdd")
    state, removed = remove_skill("hermes-tdd", "tdd")
    assert removed is True
    assert state == []


def test_remove_skill_no_op_when_absent():
    state, removed = remove_skill("hermes-tdd", "tdd")
    assert removed is False
    assert state == []


# ------------------------------- cleanup_agent_state ------------------------


class TestCleanupAgentState:
    """Tests for cleanup_agent_state — the per-agent state directory removal."""

    def test_removes_existing_state_directory(self, tmp_path: Path):
        from clawrium.core.skills_state import cleanup_agent_state

        # Pre-seed a state directory
        write_state("hermes-tdd", ["tdd"])
        agent_dir = tmp_path / "clawrium" / "agents" / "hermes-tdd"
        assert agent_dir.is_dir()

        result = cleanup_agent_state("hermes-tdd")
        assert result is True
        assert not agent_dir.exists()

    def test_returns_false_when_directory_absent(self):
        from clawrium.core.skills_state import cleanup_agent_state

        result = cleanup_agent_state("hermes-tdd")
        assert result is False

    def test_rejects_invalid_agent_name(self):
        from clawrium.core.skills_state import cleanup_agent_state

        with pytest.raises(InvalidSkillRef):
            cleanup_agent_state("../escape")

    def test_rejects_path_escaping_config_dir(self, tmp_path: Path, monkeypatch):
        """If the resolved agent state path escapes the config directory,
        cleanup_agent_state must refuse. Simulated by having state_file_path
        return a path outside the config dir."""
        from clawrium.core.skills_state import cleanup_agent_state

        agent_dir = tmp_path / "clawrium" / "agents" / "hermes-tdd"
        agent_dir.mkdir(parents=True)

        # Make state_file_path return a path that resolves outside
        # get_config_dir by patching it to return /tmp/evil/...
        outside_path = Path("/tmp/evil/clawrium/agents/hermes-tdd/skills.json")
        monkeypatch.setattr(
            "clawrium.core.skills_state.state_file_path",
            lambda name: outside_path,
        )
        with pytest.raises(ValueError, match="escapes config directory"):
            cleanup_agent_state("hermes-tdd")

    def test_rmtree_error_propagates(self, tmp_path: Path, monkeypatch):
        """If shutil.rmtree raises, the exception must propagate so the
        lifecycle.py except block can catch it."""
        from clawrium.core import skills_state
        from clawrium.core.skills_state import cleanup_agent_state

        write_state("hermes-tdd", ["tdd"])

        def boom(_path):
            raise OSError("permission denied")

        monkeypatch.setattr(skills_state.shutil, "rmtree", boom)
        with pytest.raises(OSError, match="permission denied"):
            cleanup_agent_state("hermes-tdd")

    def test_idempotent_on_already_removed_directory(self, tmp_path: Path):
        from clawrium.core.skills_state import cleanup_agent_state

        write_state("hermes-tdd", ["tdd"])
        agent_dir = tmp_path / "clawrium" / "agents" / "hermes-tdd"

        assert cleanup_agent_state("hermes-tdd") is True
        assert not agent_dir.exists()
        # Second call — directory already gone
        assert cleanup_agent_state("hermes-tdd") is False

    def test_rejects_broken_symlink_as_state_dir(self, tmp_path: Path):
        """A broken symlink at the agent state dir path must be rejected,
        not silently skipped. exists() returns False for broken symlinks,
        so checking exists() before is_symlink() would leave the orphan."""
        from clawrium.core.skills_state import cleanup_agent_state

        agent_dir = tmp_path / "clawrium" / "agents" / "hermes-tdd"
        agent_dir.mkdir(parents=True)

        # Replace the directory with a broken symlink pointing to a
        # non-existent target WITHIN the config tree (so the confinement
        # check passes but the symlink guard still fires)
        agent_dir.rmdir()
        broken_target = tmp_path / "clawrium" / "agents" / ".nonexistent"
        agent_dir.symlink_to(broken_target)

        # Verify our test setup: exists() is False but is_symlink() is True
        assert not agent_dir.exists()
        assert agent_dir.is_symlink()

        with pytest.raises(ValueError, match="is a symlink"):
            cleanup_agent_state("hermes-tdd")

        # Symlink should still exist (not removed)
        assert agent_dir.is_symlink()
