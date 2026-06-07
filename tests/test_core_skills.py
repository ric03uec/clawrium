"""Tests for the unified vetted+local skills catalog (#411)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawrium.core import skills as core_skills
from clawrium.core.skills import (
    ClawNotSupported,
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingSourcePrefix,
    SkillNameConflict,
    SkillNotFound,
    SkillRef,
    check_claw_supported,
    claws_support_map,
    find_skill_by_name,
    list_skills,
    load_skill,
    materialize_for_claw,
    parse_skill_ref,
    supported_claws,
    validate_skill,
)


@pytest.fixture
def local_root(tmp_path, monkeypatch):
    root = tmp_path / "local"
    root.mkdir()
    monkeypatch.setattr(core_skills, "_local_catalog_root", lambda: root)
    from clawrium.core import skills_local

    monkeypatch.setattr(skills_local, "_local_catalog_root", lambda: root)
    return root


def _write_skill(root: Path, name: str, description: str = "test") -> Path:
    d = root / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nversion: 0.1.0\n---\n\nbody\n"
    )
    return d


# ---------- parse_skill_ref ---------------------------------------------------


class TestParseSkillRef:
    def test_vetted_ref(self):
        ref = parse_skill_ref("vetted/tdd")
        assert ref.source == "vetted"
        assert ref.name == "tdd"
        assert str(ref) == "vetted/tdd"

    def test_local_ref(self):
        ref = parse_skill_ref("local/my-skill")
        assert ref.source == "local"
        assert ref.name == "my-skill"

    def test_bare_name_rejected(self):
        with pytest.raises(MissingSourcePrefix):
            parse_skill_ref("tdd")

    def test_unknown_source_rejected(self):
        with pytest.raises(InvalidSkillRef):
            parse_skill_ref("clawrium/tdd")

    def test_url_rejected(self):
        with pytest.raises(ExternalSourceBlocked):
            parse_skill_ref("https://example.com/tdd")

    def test_path_rejected(self):
        with pytest.raises(ExternalSourceBlocked):
            parse_skill_ref("/tmp/tdd")

    def test_empty_rejected(self):
        with pytest.raises(InvalidSkillRef):
            parse_skill_ref("")

    def test_too_many_parts_rejected(self):
        with pytest.raises(InvalidSkillRef):
            parse_skill_ref("vetted/foo/bar")

    def test_bad_name_rejected(self):
        with pytest.raises(InvalidSkillRef):
            parse_skill_ref("vetted/Bad Name")


# ---------- list_skills -------------------------------------------------------


class TestListSkills:
    def test_lists_vetted_skills(self):
        refs = list_skills(source="vetted")
        names = {r.name for r in refs}
        assert "tdd" in names

    def test_lists_local_skills(self, local_root):
        _write_skill(local_root, "alpha")
        refs = list_skills(source="local")
        assert [str(r) for r in refs] == ["local/alpha"]

    def test_union(self, local_root):
        _write_skill(local_root, "local-only")
        refs = list_skills()
        sources_seen = {r.source for r in refs}
        assert "vetted" in sources_seen
        assert "local" in sources_seen

    def test_name_conflict_raises(self, local_root):
        _write_skill(local_root, "tdd")  # collides with vetted/tdd
        with pytest.raises(SkillNameConflict):
            list_skills()

    def test_unknown_source_rejected(self):
        with pytest.raises(InvalidSkillRef):
            list_skills(source="bogus")


# ---------- find_skill_by_name ------------------------------------------------


class TestFindByName:
    def test_finds_vetted(self):
        assert find_skill_by_name("tdd") == SkillRef("vetted", "tdd")

    def test_returns_none_for_unknown(self):
        assert find_skill_by_name("no-such") is None

    def test_returns_none_for_invalid(self):
        assert find_skill_by_name("Bad Name") is None

    def test_raises_on_conflict(self, local_root):
        _write_skill(local_root, "tdd")
        with pytest.raises(SkillNameConflict):
            find_skill_by_name("tdd")


# ---------- load_skill / validate_skill ---------------------------------------


class TestLoadValidate:
    def test_load_vetted_tdd(self):
        skill = load_skill("vetted/tdd")
        assert skill.metadata.get("name") == "tdd"
        validate_skill(skill)

    def test_load_local(self, local_root):
        _write_skill(local_root, "foo")
        skill = load_skill("local/foo")
        assert skill.metadata["name"] == "foo"
        validate_skill(skill)

    def test_missing_skill_404(self):
        with pytest.raises(SkillNotFound):
            load_skill("vetted/no-such")


# ---------- per-claw support --------------------------------------------------


class TestClawSupport:
    def test_hermes_supported(self):
        check_claw_supported("hermes")

    def test_openclaw_not_supported(self):
        with pytest.raises(ClawNotSupported):
            check_claw_supported("openclaw")

    def test_zeroclaw_not_supported(self):
        with pytest.raises(ClawNotSupported):
            check_claw_supported("zeroclaw")

    def test_unknown_claw(self):
        with pytest.raises(ClawNotSupported):
            check_claw_supported("nemoclaw")

    def test_support_map_shape(self):
        m = claws_support_map()
        assert m["hermes"] is True
        assert m["openclaw"] is False
        assert m["zeroclaw"] is False

    def test_supported_claws_listing(self):
        assert supported_claws() == ["hermes"]


# ---------- materialize_for_claw ----------------------------------------------


class TestMaterialize:
    def test_hermes_passthrough(self):
        skill = load_skill("vetted/tdd")
        fm, body = materialize_for_claw(skill, "hermes")
        assert fm["name"] == "tdd"
        assert body == skill.body

    def test_strips_empty_values(self):
        skill = load_skill("vetted/tdd")
        skill_dict = dict(skill.metadata)
        skill_dict["empty_str"] = ""
        skill_dict["empty_list"] = []
        skill_dict["empty_dict"] = {}
        skill_dict["none_val"] = None
        from clawrium.core.skills import Skill

        skill2 = Skill(
            ref=skill.ref, path=skill.path, metadata=skill_dict, body=skill.body
        )
        fm, _ = materialize_for_claw(skill2, "hermes")
        assert "empty_str" not in fm
        assert "empty_list" not in fm
        assert "empty_dict" not in fm
        assert "none_val" not in fm

    def test_unsupported_claw(self):
        skill = load_skill("vetted/tdd")
        with pytest.raises(ClawNotSupported):
            materialize_for_claw(skill, "openclaw")


# ---------- skills_local CRUD -------------------------------------------------


class TestLocalCRUD:
    def test_create_local_skill(self, local_root):
        from clawrium.core.skills_local import create_local_skill

        ref = create_local_skill("my", {"description": "x"}, "body")
        assert str(ref) == "local/my"
        assert (local_root / "my" / "SKILL.md").is_file()

    def test_create_collides_with_vetted(self, local_root):
        from clawrium.core.skills_local import create_local_skill

        with pytest.raises(SkillNameConflict):
            create_local_skill("tdd", {"description": "x"}, "")

    def test_update_rejects_name_mutation(self, local_root):
        from clawrium.core.skills import SkillNameImmutable
        from clawrium.core.skills_local import (
            create_local_skill,
            update_local_skill,
        )

        create_local_skill("foo", {"description": "v1"}, "")
        with pytest.raises(SkillNameImmutable):
            update_local_skill("foo", {"name": "renamed", "description": "v2"}, "")

    def test_update_local(self, local_root):
        from clawrium.core.skills_local import (
            create_local_skill,
            update_local_skill,
        )

        create_local_skill("foo", {"description": "v1"}, "")
        update_local_skill("foo", {"description": "v2"}, "new body")
        skill = load_skill("local/foo")
        assert skill.metadata["description"] == "v2"
        assert "new body" in skill.body

    def test_delete_local(self, local_root):
        from clawrium.core.skills_local import (
            create_local_skill,
            delete_local_skill,
        )

        create_local_skill("delme", {"description": "x"}, "")
        assert delete_local_skill("delme") is True
        assert not (local_root / "delme").is_dir()

    def test_delete_vetted_blocked(self, local_root):
        from clawrium.core.skills import ReadOnlySource
        from clawrium.core.skills_local import delete_skill_by_ref

        with pytest.raises(ReadOnlySource):
            delete_skill_by_ref("vetted/tdd")

    def test_update_vetted_blocked(self, local_root):
        from clawrium.core.skills import ReadOnlySource
        from clawrium.core.skills_local import update_local_skill

        with pytest.raises(ReadOnlySource):
            update_local_skill("tdd", {"description": "x"}, "")
