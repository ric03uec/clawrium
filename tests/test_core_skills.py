"""Tests for the skills catalog loader (parse / load / validate / list).

Covers the Phase 1 exit criteria from issue #380:
- `parse_skill_ref` raises the right error class for each bad input shape.
- `validate_skill` dispatches on registry and validates against the
  matching JSON schema (dual-schema dispatch).
- `load_skill` raises `SkillNotFound` for missing entries.
- `list_skills` enumerates the on-disk catalog and respects `--registry`.

Catalog tests use a temp directory monkey-patched in as `_catalog_root`
so they don't depend on the in-repo `skills/` tree state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawrium.core import skills
from clawrium.core.skills import (
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingRegistryPrefix,
    REGISTRIES,
    SchemaValidationError,
    SkillNotFound,
    SkillRef,
    list_skills,
    load_skill,
    parse_skill_ref,
    validate_skill,
)


# ----------------------------- parse_skill_ref ------------------------------


def test_parse_skill_ref_happy_path():
    ref = parse_skill_ref("clawrium/tdd")
    assert ref == SkillRef(registry="clawrium", name="tdd")
    assert str(ref) == "clawrium/tdd"


@pytest.fixture(autouse=True)
def _reset_schema_cache():
    """Schema cache is module-level. Tests that build a fake catalog
    in tmp_path poison the cache for whichever test runs next; clear
    it on every setup and teardown to keep tests independent.

    Uses the public `clear_schema_cache()` helper rather than poking at
    the private `_SCHEMA_CACHE` name — keeps the fixture working if the
    cache implementation ever changes (e.g. swaps to functools.lru_cache).
    """
    skills.clear_schema_cache()
    yield
    skills.clear_schema_cache()


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_parse_skill_ref_empty_rejected(raw):
    with pytest.raises(InvalidSkillRef, match="empty|non-empty"):
        parse_skill_ref(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "http://example.com/skill.tgz",
        "https://github.com/foo/bar",
        "git+https://github.com/foo/bar",
        "git@github.com:foo/bar",
        "ssh://host/path",
        "file:///etc/passwd",
    ],
)
def test_parse_skill_ref_blocks_urls(raw):
    with pytest.raises(ExternalSourceBlocked):
        parse_skill_ref(raw)


@pytest.mark.parametrize("raw", ["/abs/path", "~/relative", "/etc/passwd"])
def test_parse_skill_ref_blocks_paths(raw):
    with pytest.raises(ExternalSourceBlocked):
        parse_skill_ref(raw)


def test_parse_skill_ref_bare_name_raises_missing_prefix():
    with pytest.raises(MissingRegistryPrefix) as excinfo:
        parse_skill_ref("tdd")
    # The hint should reference the canonical clawrium/tdd if it exists
    # in the in-repo catalog. We don't assert on the hint here to keep
    # the test independent of the catalog state; presence is verified
    # in test_parse_skill_ref_bare_name_hints_existing_matches.
    assert "missing a registry prefix" in str(excinfo.value)


def test_parse_skill_ref_bare_name_hints_existing_matches():
    # Uses the real in-repo catalog: clawrium/tdd exists, so the hint
    # message should point to it as a copy-pasteable correction.
    with pytest.raises(MissingRegistryPrefix) as excinfo:
        parse_skill_ref("tdd")
    assert "clawrium/tdd" in str(excinfo.value)


def test_parse_skill_ref_rejects_unknown_registry():
    with pytest.raises(InvalidSkillRef, match="Unknown registry"):
        parse_skill_ref("nope/tdd")


@pytest.mark.parametrize(
    "raw",
    [
        "clawrium/TDD",  # uppercase
        "clawrium/-leading",
        "clawrium/_leading",
        "clawrium/has spaces",
        "clawrium/a/b",  # too many slashes
        "clawrium/",  # empty name
    ],
)
def test_parse_skill_ref_rejects_bad_names(raw):
    with pytest.raises(InvalidSkillRef):
        parse_skill_ref(raw)


def test_parse_skill_ref_non_string_input():
    with pytest.raises(InvalidSkillRef):
        parse_skill_ref(None)  # type: ignore[arg-type]


# ------------------------------ list_skills ---------------------------------


def test_list_skills_includes_tdd():
    refs = list_skills()
    # in-repo seed must include clawrium/tdd, validated end-to-end below.
    assert SkillRef("clawrium", "tdd") in refs


def test_list_skills_filter_to_clawrium():
    refs = list_skills(registry="clawrium")
    assert all(ref.registry == "clawrium" for ref in refs)
    assert SkillRef("clawrium", "tdd") in refs


def test_list_skills_unknown_registry_rejected():
    with pytest.raises(InvalidSkillRef, match="Unknown registry"):
        list_skills(registry="bogus")


def test_list_skills_empty_native_registries():
    # Phase 1 ships no native skills — placeholders only. Each native
    # registry should list cleanly as an empty result, not crash.
    for native in ("openclaw", "hermes", "zeroclaw"):
        refs = list_skills(registry=native)
        assert refs == [], f"{native} should be empty in Phase 1, got {refs}"


# ------------------------------ load_skill ----------------------------------


def test_load_skill_real_tdd():
    skill = load_skill("clawrium/tdd")
    assert skill.ref == SkillRef("clawrium", "tdd")
    assert skill.metadata.get("name") == "tdd"
    assert "Test-Driven Development" in skill.metadata.get("description", "")
    assert skill.body.strip().startswith("# TDD")


def test_load_skill_missing_raises_not_found():
    with pytest.raises(SkillNotFound):
        load_skill("clawrium/no-such-skill")


def test_load_skill_via_string_runs_parse_first():
    # A URL passed to load_skill should bubble ExternalSourceBlocked
    # from parse_skill_ref unchanged.
    with pytest.raises(ExternalSourceBlocked):
        load_skill("https://example.com/foo")


# ---------------------------- validate_skill --------------------------------


def test_validate_skill_real_tdd_passes():
    skill = load_skill("clawrium/tdd")
    validate_skill(skill)  # should not raise


def test_validate_skill_enforces_slug_invariant(monkeypatch, tmp_path):
    # Build a fake catalog where _meta.yaml's `name` disagrees with the
    # parent directory name. validate_skill must reject this — required
    # for downstream zeroclaw source-dirname semantics.
    _build_fake_clawrium_skill(tmp_path, dir_name="tdd", meta_name="wrong")
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    skill = load_skill("clawrium/tdd")
    with pytest.raises(SchemaValidationError, match="must equal directory name"):
        validate_skill(skill)


def test_validate_skill_dual_schema_dispatch_native(monkeypatch, tmp_path):
    # A native registry (e.g. hermes) should validate against the
    # native/hermes.schema.json, not the clawrium schema. We build a
    # hermes skill with frontmatter that satisfies hermes but would fail
    # the stricter clawrium schema (no `compatibility` block).
    _build_fake_native_skill(tmp_path, registry="hermes", name="sample")
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    skill = load_skill("hermes/sample")
    validate_skill(skill)  # uses native/hermes.schema.json — no compat block needed


def test_validate_skill_native_rejects_missing_required(monkeypatch, tmp_path):
    _build_fake_native_skill(
        tmp_path,
        registry="openclaw",
        name="broken",
        frontmatter={"description": "no name field"},
    )
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    skill = load_skill("openclaw/broken")
    with pytest.raises(SchemaValidationError, match="required"):
        validate_skill(skill)


def test_validate_skill_clawrium_rejects_missing_compatibility(
    monkeypatch, tmp_path
):
    # Clawrium schema declares `compatibility` as required; this is the
    # rejection-direction test that the affirmative tests above don't cover.
    # Without this, dropping `compatibility` from the schema's required
    # list would silently pass the test suite.
    skill_dir = tmp_path / "clawrium" / "incomplete"
    skill_dir.mkdir(parents=True)
    (skill_dir / "_meta.yaml").write_text(
        "name: incomplete\ndescription: missing compat\nversion: 0.1.0\n"
    )
    (skill_dir / "SKILL.md").write_text(
        "---\nname: incomplete\ndescription: missing compat\n---\n"
    )
    _copy_schemas(tmp_path)
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    skill = load_skill("clawrium/incomplete")
    with pytest.raises(SchemaValidationError, match="compatibility|required"):
        validate_skill(skill)


def test_validate_skill_zeroclaw_dispatch(monkeypatch, tmp_path):
    # Mirror of the hermes dispatch test — guarantees the zeroclaw branch
    # of the dual-schema dispatch is exercised at least once.
    _build_fake_native_skill(tmp_path, registry="zeroclaw", name="zsample")
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    skill = load_skill("zeroclaw/zsample")
    validate_skill(skill)  # native/zeroclaw.schema.json — no compat block needed


# ---------------------- _validate_against_schema sort key ------------------


def test_validate_against_schema_sort_key_handles_mixed_paths(monkeypatch):
    # The sort key in `_validate_against_schema` must tolerate
    # `absolute_path` deques whose components are a mix of `str` (object
    # keys) and `int` (array indices). The failure mode is a TypeError
    # raised by Python's sort during `int < str` comparison — which
    # only triggers when two errors share a common prefix but diverge
    # at the same depth with mixed types (e.g. `['items', 'foo']` vs
    # `['items', 0]`). We mock the validator to produce exactly that
    # pair so the regression actually exercises the int-vs-str compare.
    from collections import deque
    from unittest.mock import MagicMock, patch

    err_str = MagicMock()
    err_str.absolute_path = deque(["items", "foo"])
    err_str.message = "string-keyed branch"

    err_int = MagicMock()
    err_int.absolute_path = deque(["items", 0])
    err_int.message = "int-indexed branch"

    fake_validator = MagicMock()
    fake_validator.iter_errors.return_value = [err_str, err_int]

    # The validator is lazily imported inside `_validate_against_schema`
    # so the patch target is the source module, not `clawrium.core.skills`.
    with patch(
        "jsonschema.Draft202012Validator",
        return_value=fake_validator,
    ):
        with pytest.raises(SchemaValidationError) as excinfo:
            skills._validate_against_schema(
                data={"items": "ignored — Draft202012Validator is mocked"},
                schema={"$schema": "x", "title": "fake"},
                ref=SkillRef("clawrium", "anything"),
            )
    # Both branches must surface — confirms the sort completed and the
    # report was assembled, not short-circuited by TypeError.
    rendered = str(excinfo.value)
    assert "string-keyed branch" in rendered
    assert "int-indexed branch" in rendered


# ------------------------------ utilities -----------------------------------


def _build_fake_clawrium_skill(
    root: Path, dir_name: str = "tdd", meta_name: str = "tdd"
) -> None:
    """Create a minimal in-tmp_path clawrium catalog containing one skill."""
    skill_dir = root / "clawrium" / dir_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "_meta.yaml").write_text(
        "\n".join(
            [
                f"name: {meta_name}",
                "description: fake",
                "version: 0.1.0",
                "compatibility:",
                "  openclaw: true",
                "  hermes: true",
                "  zeroclaw: true",
            ]
        )
        + "\n"
    )
    (skill_dir / "SKILL.md").write_text("---\nname: tdd\ndescription: fake\n---\nbody")
    _copy_schemas(root)


def _build_fake_native_skill(
    root: Path,
    registry: str,
    name: str,
    frontmatter: dict | None = None,
) -> None:
    """Create a minimal native-registry skill under `root`."""
    assert registry in REGISTRIES and registry != "clawrium"
    skill_dir = root / registry / name
    skill_dir.mkdir(parents=True)
    frontmatter = (
        frontmatter
        if frontmatter is not None
        else {"name": name, "description": "fake native"}
    )
    lines = [f"{k}: {v}" for k, v in frontmatter.items()]
    (skill_dir / "SKILL.md").write_text(
        "---\n" + "\n".join(lines) + "\n---\nbody\n"
    )
    _copy_schemas(root)


def _copy_schemas(root: Path) -> None:
    """Materialize the real in-repo schemas under `root/_schema/` so
    validation in test scenarios runs against the same files CI uses."""
    src_schema_root = Path(skills.__file__).resolve().parents[3] / "skills" / "_schema"
    if not src_schema_root.is_dir():
        # Fallback for installed-only environments — should not happen
        # during development, but keep the failure mode loud.
        raise RuntimeError(f"Expected in-repo schemas at {src_schema_root}")
    dest_schema = root / "_schema"
    dest_schema.mkdir(exist_ok=True)
    (dest_schema / "clawrium.schema.json").write_text(
        (src_schema_root / "clawrium.schema.json").read_text()
    )
    native_dest = dest_schema / "native"
    native_dest.mkdir(exist_ok=True)
    for native in ("openclaw", "hermes", "zeroclaw"):
        (native_dest / f"{native}.schema.json").write_text(
            (src_schema_root / "native" / f"{native}.schema.json").read_text()
        )


def test_load_skill_rejects_malformed_meta_yaml(monkeypatch, tmp_path):
    """`load_skill` catches `yaml.YAMLError` and re-raises as
    `SchemaValidationError`. Without this test the YAMLError branch is
    0-coverage and a future refactor that drops the wrap would surface
    a raw stack trace to CLI / GUI callers instead of a fixable error."""
    skill_dir = tmp_path / "clawrium" / "tdd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "_meta.yaml").write_text("key: [unclosed\n")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: tdd\ndescription: fake\n---\nbody"
    )
    _copy_schemas(tmp_path)
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    with pytest.raises(SchemaValidationError, match="Failed to parse"):
        load_skill("clawrium/tdd")


def test_load_skill_rejects_non_mapping_meta_yaml(monkeypatch, tmp_path):
    """`_meta.yaml` that parses to a YAML list (or scalar) — the
    isinstance check sits next to the YAMLError handler and shares the
    same risk if dropped."""
    skill_dir = tmp_path / "clawrium" / "tdd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "_meta.yaml").write_text("- item1\n- item2\n")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: tdd\ndescription: fake\n---\nbody"
    )
    _copy_schemas(tmp_path)
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    with pytest.raises(SchemaValidationError, match="YAML mapping"):
        load_skill("clawrium/tdd")


def test_load_schema_missing_file_raises(monkeypatch, tmp_path):
    """`_load_schema` raises `SchemaValidationError` when the on-disk
    schema is absent. Catalog readers (e.g. the validate_skills.py CI
    script) rely on the *class* of the exception to map to exit code 2,
    so the contract needs a direct test."""
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)
    # No _schema/ at all → both clawrium and native lookups fail.
    with pytest.raises(SchemaValidationError, match="Schema file"):
        skills._load_schema("clawrium")
    with pytest.raises(SchemaValidationError, match="Schema file"):
        skills._load_schema("hermes")


def test_load_schema_corrupt_json_raises(monkeypatch, tmp_path):
    schema_dir = tmp_path / "_schema"
    schema_dir.mkdir()
    (schema_dir / "clawrium.schema.json").write_text("{not json")
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    with pytest.raises(SchemaValidationError, match="not valid JSON"):
        skills._load_schema("clawrium")


def test_clear_schema_cache_empties_cache(monkeypatch, tmp_path):
    """Round-trip: populate the cache via a real `_load_schema` call,
    then prove `clear_schema_cache()` actually empties it. Without this
    the autouse fixture pretends to do work without anyone verifying
    it does."""
    _copy_schemas(tmp_path)
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)
    skills.clear_schema_cache()
    assert skills._SCHEMA_CACHE == {}
    skills._load_schema("clawrium")
    assert "clawrium" in skills._SCHEMA_CACHE
    skills.clear_schema_cache()
    assert skills._SCHEMA_CACHE == {}


def test_real_schemas_are_valid_json():
    # Sanity check the schema files we ship aren't malformed — saves a
    # confusing failure mode where validate_skill raises SchemaValidationError
    # "schema is not valid JSON" instead of validating user data.
    src_schema_root = Path(skills.__file__).resolve().parents[3] / "skills" / "_schema"
    files = [
        src_schema_root / "clawrium.schema.json",
        src_schema_root / "native" / "openclaw.schema.json",
        src_schema_root / "native" / "hermes.schema.json",
        src_schema_root / "native" / "zeroclaw.schema.json",
    ]
    for path in files:
        assert path.is_file(), path
        data = json.loads(path.read_text())
        assert isinstance(data, dict)
        assert "$schema" in data
