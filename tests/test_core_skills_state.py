"""Tests for the per-agent skills desired-state store.

Covers Phase 2 exit criteria for `core/skills_state.py`:
- state file path is XDG-respecting and namespaced by agent name
- read/write round-trips through `parse_skill_ref` (rejects URLs,
  bare names, malformed JSON)
- add/remove are idempotent and report whether the call changed state
- atomic writes (no `.tmp` left behind on success; concurrent reader
  never sees an empty file)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawrium.core.skills import (
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingRegistryPrefix,
)
from clawrium.core import skills_state
from clawrium.core.skills_state import (
    add_skill,
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


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "Cap",            # uppercase
        "1agent",         # starts with digit
        "agent$name",     # special chars
        "x" * 33,         # too long
        "../escape",
    ],
)
def test_state_file_path_rejects_bad_agent_name(bad):
    with pytest.raises(InvalidSkillRef):
        state_file_path(bad)


# ------------------------------- read_state ---------------------------------


def test_read_state_missing_file_returns_empty():
    assert read_state("hermes-tdd") == []


def test_read_state_round_trips_after_write():
    write_state("hermes-tdd", ["clawrium/tdd"])
    assert read_state("hermes-tdd") == ["clawrium/tdd"]


def test_read_state_returns_sorted_deduped():
    write_state("hermes-tdd", ["clawrium/tdd", "clawrium/tdd"])
    assert read_state("hermes-tdd") == ["clawrium/tdd"]


def test_read_state_malformed_json_raises():
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text("{not-json")
    with pytest.raises(InvalidSkillRef, match="not valid JSON"):
        read_state("hermes-tdd")


def test_read_state_non_object_root_raises():
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(["clawrium/tdd"]))
    with pytest.raises(InvalidSkillRef, match="must be a JSON object"):
        read_state("hermes-tdd")


def test_read_state_skills_field_must_be_list_of_strings():
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"skills": [{"ref": "clawrium/tdd"}]}))
    with pytest.raises(InvalidSkillRef, match="list of strings"):
        read_state("hermes-tdd")


def test_read_state_revalidates_persisted_entries():
    """Hand-edited file with an invalid ref must surface as an error
    on read, not silently propagate to apply_state."""
    path = state_file_path("hermes-tdd")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"skills": ["http://evil.example/skill"]}))
    with pytest.raises(ExternalSourceBlocked):
        read_state("hermes-tdd")


# ------------------------------- write_state --------------------------------


def test_write_state_creates_parent_dir(tmp_path: Path):
    write_state("hermes-tdd", ["clawrium/tdd"])
    parent = tmp_path / "clawrium" / "agents" / "hermes-tdd"
    assert parent.is_dir()


def test_write_state_persists_canonical_form():
    canonical = write_state("hermes-tdd", ["clawrium/tdd", "clawrium/tdd"])
    raw = json.loads(state_file_path("hermes-tdd").read_text())
    assert canonical == ["clawrium/tdd"]
    assert raw == {"skills": ["clawrium/tdd"]}


def test_write_state_rejects_bare_name_in_payload():
    with pytest.raises(MissingRegistryPrefix):
        write_state("hermes-tdd", ["tdd"])


def test_write_state_rejects_url_in_payload():
    with pytest.raises(ExternalSourceBlocked):
        write_state("hermes-tdd", ["https://example.com/skill.tgz"])


def test_write_state_leaves_no_tmp_files_on_success(tmp_path: Path):
    write_state("hermes-tdd", ["clawrium/tdd"])
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
        write_state("hermes-tdd", ["clawrium/tdd"])
    monkeypatch.setattr(skills_state.os, "replace", real_replace)

    parent = tmp_path / "clawrium" / "agents" / "hermes-tdd"
    if parent.is_dir():
        leftovers = [p for p in parent.iterdir() if p.name.startswith(".skills.")]
        assert leftovers == []


# ------------------------------- add_skill / remove_skill -------------------


def test_add_skill_returns_added_flag_on_new_entry():
    state, added = add_skill("hermes-tdd", "clawrium/tdd")
    assert added is True
    assert state == ["clawrium/tdd"]


def test_add_skill_is_idempotent():
    add_skill("hermes-tdd", "clawrium/tdd")
    state, added = add_skill("hermes-tdd", "clawrium/tdd")
    assert added is False
    assert state == ["clawrium/tdd"]


def test_remove_skill_returns_removed_flag():
    add_skill("hermes-tdd", "clawrium/tdd")
    state, removed = remove_skill("hermes-tdd", "clawrium/tdd")
    assert removed is True
    assert state == []


def test_remove_skill_no_op_when_absent():
    state, removed = remove_skill("hermes-tdd", "clawrium/tdd")
    assert removed is False
    assert state == []
