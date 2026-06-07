"""Tests for the per-agent skills desired-state store (#411)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawrium.core import skills_state as state
from clawrium.core.skills import InvalidSkillRef, SkillRef


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "get_config_dir", lambda: tmp_path)
    return tmp_path


def test_state_file_path(cfg_dir: Path):
    path = state.state_file_path("agent-1")
    assert path == cfg_dir / "agents" / "agent-1" / "skills.json"


def test_state_file_rejects_bad_agent_name(cfg_dir):
    with pytest.raises(InvalidSkillRef):
        state.state_file_path("../escape")


def test_read_missing_returns_empty(cfg_dir):
    assert state.read_state("foo") == []


def test_write_and_read_round_trip(cfg_dir):
    state.write_state("a1", ["vetted/tdd"])
    assert state.read_state("a1") == ["vetted/tdd"]


def test_write_canonicalizes(cfg_dir):
    state.write_state("a1", ["vetted/tdd", "vetted/tdd", "vetted/blog-author"])
    assert state.read_state("a1") == ["vetted/blog-author", "vetted/tdd"]


def test_write_rejects_url(cfg_dir):
    with pytest.raises(Exception):
        state.write_state("a1", ["http://evil/skill"])


def test_add_skill_returns_added_flag(cfg_dir):
    _, added = state.add_skill("a1", SkillRef("vetted", "tdd"))
    assert added is True
    _, added = state.add_skill("a1", SkillRef("vetted", "tdd"))
    assert added is False


def test_remove_skill_returns_removed_flag(cfg_dir):
    state.write_state("a1", ["vetted/tdd"])
    _, removed = state.remove_skill("a1", SkillRef("vetted", "tdd"))
    assert removed is True
    _, removed = state.remove_skill("a1", SkillRef("vetted", "tdd"))
    assert removed is False


# ---------- one-shot legacy migration -----------------------------------------


class TestMigration:
    def test_migrates_clawrium_to_vetted(self, cfg_dir):
        # Pre-create a state file with legacy refs.
        path = state.state_file_path("a1")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"skills": ["clawrium/tdd"]}))
        result = state.read_state("a1")
        assert result == ["vetted/tdd"]
        # Persisted back to disk.
        assert json.loads(path.read_text())["skills"] == ["vetted/tdd"]

    def test_migrates_hermes_to_vetted(self, cfg_dir):
        path = state.state_file_path("a1")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"skills": ["hermes/blog-author"]}))
        assert state.read_state("a1") == ["vetted/blog-author"]

    def test_drops_unknown_legacy_ref(self, cfg_dir):
        path = state.state_file_path("a1")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"skills": ["clawrium/no-such"]}))
        assert state.read_state("a1") == []

    def test_drops_unknown_prefix(self, cfg_dir):
        path = state.state_file_path("a1")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"skills": ["foobar/tdd"]}))
        assert state.read_state("a1") == []

    def test_keeps_already_valid_refs(self, cfg_dir):
        path = state.state_file_path("a1")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"skills": ["vetted/tdd"]}))
        assert state.read_state("a1") == ["vetted/tdd"]
