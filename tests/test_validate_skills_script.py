"""Tests for `scripts/validate_skills.py` — the CI catalog validator.

Expresses the contract for the new flat catalog (single `vetted/` source,
single `agent-skill.schema.json`) directly by building fixture catalogs
in `tmp_path` and running the validator against them. The real `skills/`
tree is exercised by the integration check at the bottom.

Each fixture is the smallest possible catalog that still triggers the
exact failure we care about. We assert on:

- A non-empty failure list (the validator reports the issue).
- The specific failure message substring (so a future regression that
  silently swallows the check fails this test, not just refactors).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


# scripts/validate_skills.py is not a package — import it via importlib
# so we can call validate_catalog() directly. The CI workflow exercises
# the `__main__` path separately via `python scripts/validate_skills.py`.
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "validate_skills.py"
_spec = importlib.util.spec_from_file_location("validate_skills", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
validate_skills_mod = importlib.util.module_from_spec(_spec)
sys.modules["validate_skills"] = validate_skills_mod
_spec.loader.exec_module(validate_skills_mod)

validate_catalog = validate_skills_mod.validate_catalog
ValidationFailure = validate_skills_mod.ValidationFailure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_schema(root: Path) -> None:
    """Copy the real `_schema/agent-skill.schema.json` into a fixture
    catalog. The schema lives next to the core loader; the fixture's
    copy is never read by the validator (which resolves against the
    real schema via `_load_schema()`), but a well-formed catalog still
    has a `_schema/` directory so `_validate_top_level` is happy."""
    real_schema = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "_schema"
        / "agent-skill.schema.json"
    )
    schema_dir = root / "_schema"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "agent-skill.schema.json").write_text(real_schema.read_text())


def _empty_vetted(root: Path) -> None:
    (root / "vetted").mkdir(parents=True, exist_ok=True)


def _build_fixture(root: Path) -> None:
    _write_schema(root)
    _empty_vetted(root)


def _has_failure(
    failures: list, path_part: str, message_part: str
) -> bool:
    return any(
        path_part in str(failure.path) and message_part in failure.message
        for failure in failures
    )


_VALID_SKILL_MD = dedent(
    """\
    ---
    name: tdd
    description: A test skill.
    ---

    # TDD

    Body content.
    """
)


def _write_valid_skill(root: Path, name: str = "tdd") -> Path:
    skill_dir = root / "vetted" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(_VALID_SKILL_MD.replace("name: tdd", f"name: {name}"))
    return skill_dir


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_valid_catalog_passes(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    _write_valid_skill(tmp_path)
    assert validate_catalog(tmp_path) == []


def test_empty_catalog_passes(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    assert validate_catalog(tmp_path) == []


def test_catalog_without_vetted_source_passes(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    # No vetted/ at all — legitimate during early development.
    assert validate_catalog(tmp_path) == []


# ---------------------------------------------------------------------------
# Slug / path-traversal rejections
# ---------------------------------------------------------------------------


def test_bad_dirname_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "vetted" / "Bad-Name").mkdir(parents=True)
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "Bad-Name", "slug rule")


def test_dirname_with_dot_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "vetted" / ".hidden").mkdir(parents=True)
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, ".hidden", "slug rule")


def test_symlink_inside_skill_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    skill_dir = _write_valid_skill(tmp_path)
    target = tmp_path / "outside.txt"
    target.write_text("outside")
    link = skill_dir / "link.md"
    os.symlink(target, link)
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "link.md", "symlinks are not allowed")


def test_source_level_symlink_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / "vetted" / "linked-skill"
    os.symlink(target, link)
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "linked-skill", "symlinks are not allowed")


def test_catalog_root_symlink_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / "weird"
    os.symlink(target, link)
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "weird", "symlinks are not allowed")


# ---------------------------------------------------------------------------
# Unexpected entries
# ---------------------------------------------------------------------------


def test_unexpected_top_level_directory_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "stranger").mkdir()
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "stranger", "unexpected top-level directory")


def test_unexpected_file_at_catalog_root_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "weird.txt").write_text("hi")
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "weird.txt", "unexpected file at skills/ root")


def test_unexpected_file_at_vetted_root_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "vetted" / "weird.txt").write_text("hi")
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "weird.txt", "unexpected file at vetted/ root")


def test_readme_at_vetted_root_allowed(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "vetted" / "README.md").write_text("# vetted")
    assert validate_catalog(tmp_path) == []


def test_readme_at_catalog_root_allowed(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "README.md").write_text("# skills")
    assert validate_catalog(tmp_path) == []


# ---------------------------------------------------------------------------
# Per-skill validation
# ---------------------------------------------------------------------------


def test_missing_skill_md_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "vetted" / "tdd").mkdir(parents=True)
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "tdd", "missing required SKILL.md")


def test_missing_frontmatter_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    skill_dir = tmp_path / "vetted" / "tdd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("just a body, no frontmatter.\n")
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "SKILL.md", "frontmatter")


def test_frontmatter_name_mismatch_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    skill_dir = tmp_path / "vetted" / "tdd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        dedent(
            """\
            ---
            name: other
            description: Mismatched name.
            ---

            Body.
            """
        )
    )
    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "SKILL.md", "must equal directory name")


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    skill_dir = tmp_path / "vetted" / "tdd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        dedent(
            """\
            ---
            name: tdd
            ---

            Body.
            """
        )
    )
    failures = validate_catalog(tmp_path)
    # Missing `description`.
    assert any(
        "tdd" in str(failure.path) for failure in failures
    ), failures


def test_invalid_yaml_frontmatter_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    skill_dir = tmp_path / "vetted" / "tdd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: : not valid yaml\n---\n\nBody.\n"
    )
    failures = validate_catalog(tmp_path)
    assert any("tdd" in str(failure.path) for failure in failures)


def test_frontmatter_as_list_rejected(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    skill_dir = tmp_path / "vetted" / "tdd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n- not\n- a\n- mapping\n---\n\nBody.\n"
    )
    failures = validate_catalog(tmp_path)
    assert any("tdd" in str(failure.path) for failure in failures)


# ---------------------------------------------------------------------------
# main() exit codes
# ---------------------------------------------------------------------------


def _run_script(catalog_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), str(catalog_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_main_exit_0_on_valid_catalog(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    _write_valid_skill(tmp_path)
    result = _run_script(tmp_path)
    assert result.returncode == 0, result.stderr


def test_main_exit_1_on_invalid_catalog(tmp_path: Path) -> None:
    _build_fixture(tmp_path)
    (tmp_path / "vetted" / "Bad-Name").mkdir(parents=True)
    result = _run_script(tmp_path)
    assert result.returncode == 1
    assert "Bad-Name" in result.stderr


def test_main_exit_2_on_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = _run_script(missing)
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_main_uses_default_catalog_root_for_real_repo() -> None:
    """No-arg invocation should resolve to the real repo `skills/` and
    pass — guards against the validator picking up a wrong default."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
        cwd=_SCRIPT_PATH.parent.parent,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Integration with the real in-repo catalog
# ---------------------------------------------------------------------------


def test_real_in_repo_catalog_validates() -> None:
    """The shipped `skills/` directory MUST validate. If this fails, a
    contributor pushed a broken skill — fix it before merging."""
    real_root = _SCRIPT_PATH.parent.parent / "skills"
    failures = validate_catalog(real_root)
    assert failures == [], [f.render(real_root) for f in failures]
