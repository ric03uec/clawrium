"""Tests for `scripts/validate_skills.py` — the CI catalog validator.

Phase 6 exit criterion: "CI rejects invalid-fixture PR; accepts
valid-fixture PR." These tests express that contract directly by
building fixture catalogs in `tmp_path` and running the validator
against them. The real `skills/` tree is exercised by the
`make test` integration check below.

Each fixture is the smallest possible catalog that still triggers the
exact failure we care about. We assert on:

- A non-empty failure list (the validator reports the issue).
- The specific failure message substring (so a future regression that
  silently swallows the check fails this test, not just refactors).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from textwrap import dedent

import pytest


# scripts/validate_skills.py is not a package — import it via importlib
# so we can call validate_catalog() directly. The CI workflow exercises
# the `__main__` path separately via `python scripts/validate_skills.py`.
_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "validate_skills.py"
)
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


def _write_schemas(root: Path) -> None:
    """Copy the real `_schema/` tree into a fixture catalog. Validator
    behavior depends on the actual schemas — re-defining them inline
    would let drift in the production schemas silently break this test
    suite."""
    real_schema = (
        Path(__file__).resolve().parent.parent / "skills" / "_schema"
    )
    schema_dir = root / "_schema"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "clawrium.schema.json").write_text(
        (real_schema / "clawrium.schema.json").read_text()
    )
    native_dir = schema_dir / "native"
    native_dir.mkdir(exist_ok=True)
    for claw in ("openclaw", "hermes", "zeroclaw"):
        (native_dir / f"{claw}.schema.json").write_text(
            (real_schema / "native" / f"{claw}.schema.json").read_text()
        )


def _empty_registries(root: Path) -> None:
    for reg in ("clawrium", "openclaw", "hermes", "zeroclaw"):
        (root / reg).mkdir(parents=True, exist_ok=True)


def _build_fixture(root: Path) -> None:
    _write_schemas(root)
    _empty_registries(root)


def _has_failure(
    failures: list[ValidationFailure], path_part: str, message_part: str
) -> bool:
    return any(
        path_part in str(failure.path) and message_part in failure.message
        for failure in failures
    )


_VALID_META = dedent(
    """\
    name: tdd
    description: A test skill.
    version: 0.1.0
    compatibility:
      openclaw: true
      hermes: true
      zeroclaw: true
    """
)
_VALID_SKILL_MD = dedent(
    """\
    ---
    name: tdd
    description: A test skill.
    ---

    # Body
    """
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_catalog_passes(tmp_path):
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "_meta.yaml").write_text(_VALID_META)
    (skill / "SKILL.md").write_text(_VALID_SKILL_MD)

    assert validate_catalog(tmp_path) == []


@pytest.mark.parametrize("registry", ["openclaw", "hermes", "zeroclaw"])
def test_native_skill_passes(tmp_path, registry):
    """The happy path for every native registry. Catches per-claw schema
    regressions (e.g. an accidental edit to zeroclaw.schema.json that
    leaves the other two unaffected)."""
    _build_fixture(tmp_path)
    skill = tmp_path / registry / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        dedent(
            f"""\
            ---
            name: demo
            description: A {registry}-native demo skill.
            ---

            # Body
            """
        )
    )

    assert validate_catalog(tmp_path) == []


def test_empty_catalog_passes(tmp_path):
    """skills/_schema/ but no registry directories should validate.
    Exercises the early-return in `_validate_registry` when a
    registry root doesn't exist on disk."""
    _write_schemas(tmp_path)
    assert validate_catalog(tmp_path) == []


# ---------------------------------------------------------------------------
# Path-traversal fixtures
# ---------------------------------------------------------------------------


def test_path_traversal_via_bad_dirname_rejected(tmp_path):
    """A directory whose name fails the slug rule (incl. leading dots
    and dot-segments) is rejected before any file read. Even though
    Path() would never resolve `..` literally as a child entry, the
    same regex catches `evil-..` style attempts as well."""
    _build_fixture(tmp_path)
    # We can't literally create a directory named ".." (it resolves up),
    # but the slug rule catches the broader class of forbidden names:
    # dotfiles, dot-prefixed dirs, and anything not matching kebab-case.
    (tmp_path / "clawrium" / ".hidden").mkdir()

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures, ".hidden", "violates the slug rule"
    ), failures


def test_path_traversal_via_symlink_rejected(tmp_path):
    """A symlink inside a skill directory is rejected regardless of
    where it points. Skills are flat content; symlinks are not."""
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "_meta.yaml").write_text(_VALID_META)
    (skill / "SKILL.md").write_text(_VALID_SKILL_MD)

    # The symlink target itself is benign (/etc/hostname); the rule is
    # "no symlinks at all," so target choice is irrelevant to the test.
    evil = skill / "leak"
    evil.symlink_to("/etc/hostname")

    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "leak", "symlinks are not allowed"), failures


def test_unexpected_top_level_directory_rejected(tmp_path):
    """Anything at skills/ root that isn't `_schema`, a known registry,
    or README.md is rejected — keeps the catalog tree from accumulating
    drive-by directories."""
    _build_fixture(tmp_path)
    (tmp_path / "external").mkdir()

    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "external", "unexpected top-level"), failures


# ---------------------------------------------------------------------------
# Schema-mismatch fixtures
# ---------------------------------------------------------------------------


def test_meta_yaml_under_native_registry_rejected(tmp_path):
    """A `_meta.yaml` under skills/<claw>/ is the classic schema-mismatch
    signal — a clawrium-shaped skill mis-placed under a native registry.
    The validator surfaces this even if the SKILL.md frontmatter alone
    would have passed the lenient native schema."""
    _build_fixture(tmp_path)
    skill = tmp_path / "openclaw" / "demo"
    skill.mkdir()
    (skill / "_meta.yaml").write_text(_VALID_META)
    (skill / "SKILL.md").write_text(
        dedent(
            """\
            ---
            name: demo
            description: An openclaw demo with a stray _meta.yaml.
            ---

            # Body
            """
        )
    )

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures,
        "_meta.yaml",
        "only valid under skills/clawrium/",
    ), failures


def test_clawrium_keys_in_native_frontmatter_rejected(tmp_path):
    """Native schemas are `additionalProperties: true`. If we did NOT
    explicitly reject clawrium-only keys, a contributor could paste a
    clawrium frontmatter under skills/zeroclaw/ and have it silently
    pass — defeating the dual-schema guarantee."""
    _build_fixture(tmp_path)
    skill = tmp_path / "zeroclaw" / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        dedent(
            """\
            ---
            name: demo
            description: A zeroclaw skill with a stray compatibility block.
            compatibility:
              openclaw: true
              hermes: true
              zeroclaw: true
            ---

            # Body
            """
        )
    )

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures,
        "SKILL.md",
        "clawrium-only keys",
    ), failures


def test_clawrium_name_mismatch_rejected(tmp_path):
    """The source-dirname == registry-slug invariant (Phase 0 finding).
    Zeroclaw uses the source dirname for `remove`; if `_meta.yaml.name`
    drifts from the directory name, downstream uninstalls break."""
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "_meta.yaml").write_text(
        dedent(
            """\
            name: not-tdd
            description: Mismatched name.
            version: 0.1.0
            compatibility:
              openclaw: true
              hermes: true
              zeroclaw: true
            """
        )
    )
    (skill / "SKILL.md").write_text(_VALID_SKILL_MD)

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures,
        "_meta.yaml",
        "must equal directory name",
    ), failures


def test_native_skill_name_mismatch_rejected(tmp_path):
    _build_fixture(tmp_path)
    skill = tmp_path / "hermes" / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        dedent(
            """\
            ---
            name: wrong
            description: Mismatched name.
            ---

            # Body
            """
        )
    )

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures,
        "SKILL.md",
        "must equal directory name",
    ), failures


def test_missing_required_field_rejected(tmp_path):
    """Schema-required keys (e.g. clawrium `compatibility`) must trip
    the dual-schema validator. This is the same code path that
    runtime `validate_skill` exercises — we just confirm it surfaces
    from the validator script too."""
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "_meta.yaml").write_text(
        dedent(
            """\
            name: tdd
            description: Missing compatibility.
            version: 0.1.0
            """
        )
    )
    (skill / "SKILL.md").write_text(_VALID_SKILL_MD)

    failures = validate_catalog(tmp_path)
    # Pin both path and message so a future refactor that mis-attributes
    # the failure to SKILL.md (or to some unrelated file that happens to
    # mention `compatibility`) still trips this test.
    assert _has_failure(failures, "_meta.yaml", "compatibility"), failures


def test_missing_skill_md_rejected(tmp_path):
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "_meta.yaml").write_text(_VALID_META)
    # Intentionally no SKILL.md.

    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "tdd", "missing required SKILL.md"), failures


def test_missing_meta_yaml_rejected(tmp_path):
    """Symmetric counterpart to test_missing_skill_md_rejected. Without
    this test, a refactor that drops the _meta.yaml guard in
    _validate_clawrium_skill would pass the full suite even though the
    catalog would silently accept SKILL.md-only clawrium skills."""
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "SKILL.md").write_text(_VALID_SKILL_MD)
    # Intentionally no _meta.yaml.

    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "tdd", "missing required _meta.yaml"), failures


def test_native_skill_missing_skill_md_rejected(tmp_path):
    """Native-registry counterpart to test_missing_skill_md_rejected.
    Covers the missing-SKILL.md branch in _validate_native_skill which
    the clawrium-path test does not exercise."""
    _build_fixture(tmp_path)
    skill = tmp_path / "openclaw" / "demo"
    skill.mkdir()
    # Intentionally no SKILL.md.

    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "demo", "missing required SKILL.md"), failures


def test_missing_frontmatter_in_native_rejected(tmp_path):
    _build_fixture(tmp_path)
    skill = tmp_path / "hermes" / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# No frontmatter\n")

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures, "SKILL.md", "YAML frontmatter block"
    ), failures


def test_native_frontmatter_as_list_rejected(tmp_path):
    """SKILL.md frontmatter that parses to a YAML list (or any non-
    mapping) used to crash the validator with an uncaught
    SchemaValidationError. The validator must surface this as a
    normal failure entry instead."""
    _build_fixture(tmp_path)
    skill = tmp_path / "hermes" / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        dedent(
            """\
            ---
            - item1
            - item2
            ---

            # Body
            """
        )
    )

    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "SKILL.md", "YAML mapping"), failures


def test_meta_yaml_invalid_yaml_rejected(tmp_path):
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "_meta.yaml").write_text("key: [unclosed")
    (skill / "SKILL.md").write_text(_VALID_SKILL_MD)

    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "_meta.yaml", "not valid YAML"), failures


def test_meta_yaml_non_dict_rejected(tmp_path):
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "_meta.yaml").write_text("- item1\n- item2\n")
    (skill / "SKILL.md").write_text(_VALID_SKILL_MD)

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures, "_meta.yaml", "must be a YAML mapping"
    ), failures


def test_registry_level_symlink_rejected(tmp_path):
    """A skill directory that is itself a symlink (not just a symlink
    *inside* a skill dir) is a separate path-traversal vector. The
    symlink check in _validate_registry must fire before the
    is_file()/is_dir() branches that would otherwise follow the link."""
    _build_fixture(tmp_path)
    target = tmp_path / "_real_skill"
    target.mkdir()
    evil = tmp_path / "clawrium" / "evil"
    evil.symlink_to(target)

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures, "evil", "registry-level symlinks are not allowed"
    ), failures


def test_registry_root_symlink_to_file_rejected(tmp_path):
    """`Path.is_file()` follows symlinks. Before B2 was fixed, a
    `README.md -> /etc/passwd` symlink would slip past the
    `is_file()` branch and `continue` before the symlink check ever
    ran. Pin the ordering with an explicit test."""
    _build_fixture(tmp_path)
    target = tmp_path / "outside"
    target.write_text("decoy")
    evil = tmp_path / "clawrium" / "README.md"
    evil.symlink_to(target)

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures, "README.md", "registry-level symlinks are not allowed"
    ), failures


def test_catalog_root_symlink_rejected(tmp_path):
    _build_fixture(tmp_path)
    evil = tmp_path / "evil-link"
    evil.symlink_to("/etc")

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures, "evil-link", "catalog-root symlinks are not allowed"
    ), failures


def test_unexpected_file_at_registry_root_rejected(tmp_path):
    _build_fixture(tmp_path)
    (tmp_path / "clawrium" / "stray.txt").write_text("oops")

    failures = validate_catalog(tmp_path)
    assert _has_failure(
        failures, "stray.txt", "unexpected file at registry root"
    ), failures


def test_native_skill_schema_violation_rejected(tmp_path):
    """A native SKILL.md with a wrong-shape required field (description
    failing minLength) must surface a schema validation failure rather
    than slip past on the lenient `additionalProperties: true` schema."""
    _build_fixture(tmp_path)
    skill = tmp_path / "hermes" / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        dedent(
            """\
            ---
            name: demo
            description: ''
            ---

            # Body
            """
        )
    )

    failures = validate_catalog(tmp_path)
    assert _has_failure(failures, "SKILL.md", "description"), failures


# ---------------------------------------------------------------------------
# main() — exit-code contract (the CI entry point)
# ---------------------------------------------------------------------------


def test_main_exit_0_on_valid_catalog(tmp_path):
    _build_fixture(tmp_path)
    skill = tmp_path / "clawrium" / "tdd"
    skill.mkdir()
    (skill / "_meta.yaml").write_text(_VALID_META)
    (skill / "SKILL.md").write_text(_VALID_SKILL_MD)

    rc = validate_skills_mod.main([str(tmp_path)])
    assert rc == 0


def test_main_exit_1_on_invalid_catalog(tmp_path, capsys):
    _build_fixture(tmp_path)
    (tmp_path / "clawrium" / ".hidden").mkdir()

    rc = validate_skills_mod.main([str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    # Both the header and the trailing FAILED summary should reach
    # stderr so the last visible line in CI logs is actionable.
    assert "violation" in captured.err.lower() or "slug rule" in captured.err
    assert "FAILED" in captured.err


def test_main_exit_2_on_missing_root(tmp_path, capsys):
    rc = validate_skills_mod.main([str(tmp_path / "does-not-exist")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "catalog root not found" in captured.err


def test_main_uses_default_catalog_root_for_real_repo(monkeypatch, capsys):
    """`main` with no argv falls back to `_default_catalog_root()`, which
    encodes the assumption that the script lives at repo-root/scripts/.
    Run it against the actual repo to pin that assumption."""
    rc = validate_skills_mod.main([])
    captured = capsys.readouterr()
    assert rc == 0, captured.err


# ---------------------------------------------------------------------------
# Integration: the real catalog must always validate
# ---------------------------------------------------------------------------


def test_real_in_repo_catalog_validates():
    """The actual skills/ tree at repo root validates. This guards
    against schema regressions slipping past PR review — if a real
    skill is broken, this test fails before CI even runs the workflow."""
    real_root = Path(__file__).resolve().parent.parent / "skills"
    assert validate_catalog(real_root) == [], (
        "The in-repo skills/ catalog does not validate. "
        "Run `python scripts/validate_skills.py` for the full report."
    )
