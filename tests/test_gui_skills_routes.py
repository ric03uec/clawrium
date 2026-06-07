"""Tests for the unified skills GUI routes (#411).

Covers:
- ``GET /api/skills`` — flat list, source + supported_on on every card.
- ``GET /api/skills/{source}/{name}`` — detail, supported_on injected.
- ``POST /api/skills`` — create local-source skill.
- ``PUT /api/skills/local/{name}`` — update (name immutable).
- ``PUT /api/skills/vetted/{name}`` — read-only (403).
- ``DELETE /api/skills/local/{name}`` — delete.
- ``DELETE /api/skills/vetted/{name}`` — read-only (403).
- Error mapping: 404, 409, 422, 403.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from clawrium.core import skills as core_skills
from clawrium.gui.routes import skills as skills_route


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_local_catalog(tmp_path, monkeypatch):
    """Redirect the local skills root to a tmp dir for every test."""
    local_root = tmp_path / "local"
    local_root.mkdir()
    monkeypatch.setattr(core_skills, "_local_catalog_root", lambda: local_root)
    # skills_local imports the symbol at module load
    from clawrium.core import skills_local

    monkeypatch.setattr(skills_local, "_local_catalog_root", lambda: local_root)
    yield local_root


# ---------- GET /api/skills ----------------------------------------------------


def test_list_returns_flat_unified_list():
    result = _run(skills_route.list_skills_route())

    assert result["sources"] == list(core_skills.SOURCES)
    assert "skills" in result
    assert isinstance(result["skills"], list)
    assert result["supported_on"] == dict(core_skills.SUPPORTED_CLAWS_BY_DEFAULT)


def test_list_includes_vetted_tdd_summary():
    result = _run(skills_route.list_skills_route())

    refs = {entry["ref"] for entry in result["skills"]}
    assert "vetted/tdd" in refs

    tdd = next(e for e in result["skills"] if e["ref"] == "vetted/tdd")
    assert tdd["source"] == "vetted"
    assert tdd["name"] == "tdd"
    assert tdd["supported_on"]["hermes"] is True
    assert tdd["supported_on"]["openclaw"] is False
    assert tdd["description"]


def test_list_does_not_leak_skill_md_body():
    result = _run(skills_route.list_skills_route())
    for entry in result["skills"]:
        assert "body" not in entry
        assert "metadata" not in entry


# ---------- GET /api/skills/{source}/{name} -----------------------------------


def test_detail_returns_vetted_tdd_full_payload():
    result = _run(skills_route.get_skill_route(source="vetted", name="tdd"))
    assert result["ref"] == "vetted/tdd"
    assert result["source"] == "vetted"
    assert result["name"] == "tdd"
    assert result["body"]
    assert result["supported_on"]["hermes"] is True


def test_detail_unknown_skill_404():
    with pytest.raises(Exception) as exc:
        _run(skills_route.get_skill_route(source="vetted", name="no-such"))
    assert exc.value.status_code == 404


def test_detail_unknown_source_422():
    with pytest.raises(Exception) as exc:
        _run(skills_route.get_skill_route(source="bogus", name="tdd"))
    assert exc.value.status_code == 422


# ---------- POST /api/skills ---------------------------------------------------


def test_create_local_skill():
    payload = {
        "name": "my-skill",
        "description": "demo",
        "body": "# hi",
    }
    result = _run(skills_route.create_skill_route(payload=payload))
    assert result["ref"] == "local/my-skill"
    assert result["source"] == "local"


def test_create_rejects_missing_name():
    with pytest.raises(Exception) as exc:
        _run(skills_route.create_skill_route(payload={"description": "x", "body": ""}))
    assert exc.value.status_code == 422


def test_create_rejects_name_collision_with_vetted():
    with pytest.raises(Exception) as exc:
        _run(
            skills_route.create_skill_route(
                payload={"name": "tdd", "description": "collides", "body": ""}
            )
        )
    assert exc.value.status_code == 409


def test_create_then_duplicate_409():
    payload = {"name": "dupe", "description": "x", "body": "y"}
    _run(skills_route.create_skill_route(payload=payload))
    with pytest.raises(Exception) as exc:
        _run(skills_route.create_skill_route(payload=payload))
    assert exc.value.status_code == 409


# ---------- PUT /api/skills/local/{name} --------------------------------------


def test_update_local_skill():
    _run(
        skills_route.create_skill_route(
            payload={"name": "edme", "description": "v1", "body": ""}
        )
    )
    result = _run(
        skills_route.update_skill_route(
            name="edme",
            payload={"description": "v2", "body": "new body"},
        )
    )
    assert result["metadata"]["description"] == "v2"
    assert "new body" in result["body"]


def test_update_rejects_name_mutation():
    _run(
        skills_route.create_skill_route(
            payload={"name": "immut", "description": "x", "body": ""}
        )
    )
    with pytest.raises(Exception) as exc:
        _run(
            skills_route.update_skill_route(
                name="immut",
                payload={"name": "renamed", "description": "x", "body": ""},
            )
        )
    assert exc.value.status_code == 422


def test_update_vetted_403():
    with pytest.raises(Exception) as exc:
        _run(skills_route.update_vetted_skill_route(name="tdd"))
    assert exc.value.status_code == 403


# ---------- DELETE /api/skills/local/{name} -----------------------------------


def test_delete_local_skill(_isolated_local_catalog: Path):
    _run(
        skills_route.create_skill_route(
            payload={"name": "todelete", "description": "x", "body": ""}
        )
    )
    _run(skills_route.delete_skill_route(name="todelete"))
    assert not (_isolated_local_catalog / "todelete" / "SKILL.md").is_file()


def test_delete_vetted_403():
    with pytest.raises(Exception) as exc:
        _run(skills_route.delete_vetted_skill_route(name="tdd"))
    assert exc.value.status_code == 403
