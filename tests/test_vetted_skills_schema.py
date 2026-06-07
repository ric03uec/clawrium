"""Schema validation for every shipped `skills/vetted/<name>/SKILL.md`.

The Phase 2 loader contract is `skills/_schema/agent-skill.schema.json`.
We exercise that contract directly here so a future SKILL.md edit that
silently drops `description`, breaks the `name` slug, or otherwise
violates the schema fails CI with a per-skill diagnostic rather than
surfacing at runtime as a loader crash.

Parametrized over the on-disk vetted catalog so adding a new skill
under `skills/vetted/` automatically pulls it into coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent
_VETTED_DIR = _REPO_ROOT / "skills" / "vetted"
_SCHEMA_PATH = _REPO_ROOT / "skills" / "_schema" / "agent-skill.schema.json"


def _vetted_skill_paths() -> list[Path]:
    return sorted(_VETTED_DIR.glob("*/SKILL.md"))


def _split_frontmatter(text: str) -> dict:
    """Pull YAML frontmatter out of a SKILL.md body.

    Mirrors the loader's expectation: file MUST start with `---`, a YAML
    block, then `---`, then the markdown body. Anything else fails the
    test loudly.
    """
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md does not start with a YAML frontmatter block")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("SKILL.md frontmatter is not terminated by a `---` line")
    return yaml.safe_load(text[4:end]) or {}


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


@pytest.mark.parametrize(
    "skill_path",
    _vetted_skill_paths(),
    ids=[p.parent.name for p in _vetted_skill_paths()],
)
def test_vetted_skill_frontmatter_validates(skill_path: Path, schema: dict) -> None:
    frontmatter = _split_frontmatter(skill_path.read_text())
    jsonschema.validate(instance=frontmatter, schema=schema)


@pytest.mark.parametrize(
    "skill_path",
    _vetted_skill_paths(),
    ids=[p.parent.name for p in _vetted_skill_paths()],
)
def test_vetted_skill_name_matches_directory(skill_path: Path) -> None:
    frontmatter = _split_frontmatter(skill_path.read_text())
    assert frontmatter.get("name") == skill_path.parent.name, (
        f"frontmatter.name={frontmatter.get('name')!r} must equal "
        f"directory name {skill_path.parent.name!r}"
    )


def test_vetted_catalog_is_not_empty() -> None:
    """Guard against an accidental wipe: if we ever end up with zero
    vetted skills, the parametrized validation tests above degrade to
    a no-op and pass vacuously. This test fails loudly instead."""
    assert _vetted_skill_paths(), "no skills/vetted/<name>/SKILL.md files found"
