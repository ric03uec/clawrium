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
    IncompatibleSkillRegistry,
    MissingRegistryPrefix,
    NATIVE_REGISTRIES,
    REGISTRIES,
    SchemaValidationError,
    Skill,
    SkillNotFound,
    SkillRef,
    list_agent_skills,
    list_skills,
    load_agent_skill,
    load_skill,
    materialize_skill_for_agent,
    parse_skill_ref,
    render_skill_md,
    validate_skill,
)
from clawrium.core.skills_state import agent_skills_dir


# ----------------------------- parse_skill_ref ------------------------------


def test_parse_skill_ref_happy_path():
    ref = parse_skill_ref("clawrium/tdd")
    assert ref == SkillRef(registry="clawrium", name="tdd")
    assert str(ref) == "clawrium/tdd"


@pytest.fixture(autouse=True)
def _reset_schema_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Schema cache is module-level. Tests that build a fake catalog
    in tmp_path poison the cache for whichever test runs next; clear
    it on every setup and teardown to keep tests independent.

    Uses the public `clear_schema_cache()` helper rather than poking at
    the private `_SCHEMA_CACHE` name — keeps the fixture working if the
    cache implementation ever changes (e.g. swaps to functools.lru_cache).
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    skills.clear_schema_cache()
    skills._CATALOG_OVERLAY_COLLISIONS_WARNED.clear()
    yield
    skills.clear_schema_cache()
    skills._CATALOG_OVERLAY_COLLISIONS_WARNED.clear()


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
    # `openclaw` and `zeroclaw` still ship as placeholder registries —
    # list_skills should list them as empty, not crash. `hermes` has
    # real skills (added in #403, #404) and is no longer Phase-1 empty.
    for native in ("openclaw", "zeroclaw"):
        refs = list_skills(registry=native)
        assert refs == [], f"{native} should be empty, got {refs}"


def test_catalog_roots_returns_bundled_only(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    assert skills._catalog_roots() == [("bundled", tmp_path)]


def test_catalog_roots_returns_bundled_then_overlay(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    overlay = skills._overlay_root()
    bundled.mkdir()
    overlay.mkdir(parents=True)
    monkeypatch.setattr(skills, "_catalog_root", lambda: bundled)

    assert skills._catalog_roots() == [("bundled", bundled), ("overlay", overlay)]


def test_catalog_roots_returns_overlay_only(monkeypatch, tmp_path):
    overlay = skills._overlay_root()
    overlay.mkdir(parents=True)

    def missing_catalog():
        raise SkillNotFound("missing bundled catalog")

    monkeypatch.setattr(skills, "_catalog_root", missing_catalog)

    assert skills._catalog_roots() == [("overlay", overlay)]


def test_catalog_roots_raises_when_neither_root_exists(monkeypatch):
    def missing_catalog():
        raise SkillNotFound("missing bundled catalog")

    monkeypatch.setattr(skills, "_catalog_root", missing_catalog)

    with pytest.raises(SkillNotFound, match="missing bundled catalog"):
        skills._catalog_roots()


def test_public_list_skills_includes_overlay(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    overlay = skills._overlay_root()
    bundled.mkdir()
    _copy_schemas(bundled)
    _build_fake_native_skill(bundled, registry="hermes", name="bundled-skill")
    _build_fake_native_skill(overlay, registry="hermes", name="overlay-only")
    monkeypatch.setattr(skills, "_catalog_root", lambda: bundled)

    refs = list_skills(registry="hermes")
    assert SkillRef("hermes", "bundled-skill") in refs
    assert SkillRef("hermes", "overlay-only") in refs


def test_public_load_skill_uses_overlay(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    overlay = skills._overlay_root()
    bundled.mkdir()
    _copy_schemas(bundled)
    _build_fake_native_skill(bundled, registry="hermes", name="bundled-skill")
    _build_fake_native_skill(overlay, registry="hermes", name="overlay-only")
    monkeypatch.setattr(skills, "_catalog_root", lambda: bundled)

    assert load_skill("hermes/bundled-skill").ref == SkillRef(
        "hermes", "bundled-skill"
    )
    assert load_skill("hermes/overlay-only").path == overlay / "hermes" / "overlay-only"


def test_list_skills_includes_overlay_only(monkeypatch, tmp_path):
    overlay = skills._overlay_root()
    _build_fake_native_skill(overlay, registry="hermes", name="overlay-skill")

    def missing_catalog():
        raise SkillNotFound("missing bundled catalog")

    monkeypatch.setattr(skills, "_catalog_root", missing_catalog)

    assert skills._list_skills_from_roots(registry="hermes") == [
        SkillRef("hermes", "overlay-skill")
    ]


def test_list_skills_raises_when_no_catalog_roots(monkeypatch):
    def missing_catalog():
        raise SkillNotFound("missing bundled catalog")

    monkeypatch.setattr(skills, "_catalog_root", missing_catalog)

    with pytest.raises(SkillNotFound, match="missing bundled catalog"):
        skills._list_skills_from_roots()


def test_overlay_shadows_bundled_skill_once(monkeypatch, tmp_path, caplog):
    bundled = tmp_path / "bundled"
    overlay = skills._overlay_root()
    _build_fake_native_skill(
        bundled,
        registry="hermes",
        name="sample",
        frontmatter={"name": "sample", "description": "bundled"},
    )
    _build_fake_native_skill(
        overlay,
        registry="hermes",
        name="sample",
        frontmatter={"name": "sample", "description": "overlay"},
    )
    monkeypatch.setattr(skills, "_catalog_root", lambda: bundled)

    with caplog.at_level("WARNING"):
        assert skills._list_skills_from_roots(registry="hermes") == [
            SkillRef("hermes", "sample")
        ]
        assert skills._list_skills_from_roots(registry="hermes") == [
            SkillRef("hermes", "sample")
        ]

    warnings = [record for record in caplog.records if "shadows bundled" in record.message]
    assert len(warnings) == 1
    assert str(overlay / "hermes" / "sample") in warnings[0].message
    assert skills._find_catalog_skill_dir(SkillRef("hermes", "sample")) == (
        overlay / "hermes" / "sample"
    )


def test_list_skills_from_roots_empty_overlay_falls_back_to_bundled(
    monkeypatch, tmp_path
):
    bundled = tmp_path / "bundled"
    overlay = skills._overlay_root()
    _build_fake_native_skill(bundled, registry="hermes", name="sample")
    overlay.mkdir(parents=True)
    monkeypatch.setattr(skills, "_catalog_root", lambda: bundled)

    assert skills._list_skills_from_roots(registry="hermes") == [
        SkillRef("hermes", "sample")
    ]


def test_find_catalog_skill_dir_returns_bundled_when_no_overlay(monkeypatch, tmp_path):
    _build_fake_native_skill(tmp_path, registry="hermes", name="sample")
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    assert skills._find_catalog_skill_dir(SkillRef("hermes", "sample")) == (
        tmp_path / "hermes" / "sample"
    )


def test_find_catalog_skill_dir_returns_none_for_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    assert skills._find_catalog_skill_dir(SkillRef("hermes", "missing")) is None


def test_find_catalog_skill_dir_returns_overlay_when_bundled_absent(
    monkeypatch, tmp_path
):
    overlay = skills._overlay_root()
    _build_fake_native_skill(overlay, registry="hermes", name="sample")

    def missing_catalog():
        raise SkillNotFound("missing bundled catalog")

    monkeypatch.setattr(skills, "_catalog_root", missing_catalog)

    assert skills._find_catalog_skill_dir(SkillRef("hermes", "sample")) == (
        overlay / "hermes" / "sample"
    )


def test_find_catalog_skill_dir_ignores_stub_overlay(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    overlay = skills._overlay_root()
    _build_fake_native_skill(bundled, registry="hermes", name="sample")
    (overlay / "hermes" / "sample").mkdir(parents=True)
    monkeypatch.setattr(skills, "_catalog_root", lambda: bundled)

    assert skills._find_catalog_skill_dir(SkillRef("hermes", "sample")) == (
        bundled / "hermes" / "sample"
    )


def test_find_catalog_skill_dir_returns_none_when_no_roots(monkeypatch):
    def missing_catalog():
        raise SkillNotFound("missing bundled catalog")

    monkeypatch.setattr(skills, "_catalog_root", missing_catalog)

    assert skills._find_catalog_skill_dir(SkillRef("hermes", "sample")) is None


def test_find_catalog_skill_dir_returns_none_stub_overlay_no_bundled(monkeypatch):
    overlay = skills._overlay_root()
    (overlay / "hermes" / "sample").mkdir(parents=True)

    def missing_catalog():
        raise SkillNotFound("missing bundled catalog")

    monkeypatch.setattr(skills, "_catalog_root", missing_catalog)

    assert skills._find_catalog_skill_dir(SkillRef("hermes", "sample")) is None


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


def test_list_agent_skills_returns_sorted_valid_local_names():
    root = agent_skills_dir("hermes-tdd")
    _write_local_skill(root, "zeta")
    _write_local_skill(root, "alpha")
    (root / "bad name").mkdir()
    (root / "missing-md").mkdir()

    assert list_agent_skills("hermes-tdd") == ["alpha", "zeta"]


def test_list_agent_skills_missing_dir_returns_empty():
    assert list_agent_skills("hermes-tdd") == []


@pytest.mark.parametrize("agent", ["../escape", "Bad", ""])
def test_list_agent_skills_rejects_invalid_agent_name(agent):
    with pytest.raises(InvalidSkillRef):
        list_agent_skills(agent)


@pytest.mark.parametrize("agent_type", sorted(NATIVE_REGISTRIES))
def test_load_agent_skill_validates_native_shape(tmp_path, agent_type):
    root = agent_skills_dir(f"{agent_type}-tdd")
    _write_local_skill(root, "local")

    skill = load_agent_skill(f"{agent_type}-tdd", "local", agent_type)

    assert skill.ref == SkillRef(agent_type, "local")
    assert skill.metadata["name"] == "local"


@pytest.mark.parametrize(
    "name", ["bad name!", "clawrium/tdd", "", "../escape", "UPPER"]
)
def test_load_agent_skill_rejects_invalid_name(name):
    with pytest.raises(InvalidSkillRef):
        load_agent_skill("hermes-tdd", name, "hermes")


def test_load_agent_skill_missing_dir_raises_not_found():
    with pytest.raises(SkillNotFound, match="not found"):
        load_agent_skill("hermes-tdd", "local", "hermes")


def test_load_agent_skill_rejects_malformed_frontmatter(tmp_path):
    root = agent_skills_dir("hermes-tdd")
    skill_dir = root / "local"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: [unclosed\n---\nbody\n")

    with pytest.raises(SchemaValidationError, match="frontmatter"):
        load_agent_skill("hermes-tdd", "local", "hermes")


@pytest.mark.parametrize("agent_type", sorted(NATIVE_REGISTRIES))
def test_load_agent_skill_rejects_schema_invalid_frontmatter(tmp_path, agent_type):
    root = agent_skills_dir(f"{agent_type}-tdd")
    skill_dir = root / "local"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: local\n---\nbody\n")

    with pytest.raises(SchemaValidationError, match="required"):
        load_agent_skill(f"{agent_type}-tdd", "local", agent_type)


def test_load_agent_skill_rejects_unknown_agent_type():
    with pytest.raises(InvalidSkillRef, match="Unknown agent type"):
        load_agent_skill("hermes-tdd", "local", "not-a-claw")


# ---------------------------- validate_skill --------------------------------


def test_validate_skill_real_tdd_passes():
    skill = load_skill("clawrium/tdd")
    validate_skill(skill)  # should not raise


@pytest.mark.parametrize("agent_type", sorted(NATIVE_REGISTRIES))
def test_materialize_skill_for_agent_returns_valid_native_skill(agent_type):
    skill = load_skill("clawrium/tdd")

    native_skill = materialize_skill_for_agent(skill, agent_type)

    assert native_skill.ref == SkillRef(agent_type, "tdd")
    assert native_skill.path == Path("__materialized__")
    assert native_skill.path != skill.path
    assert native_skill.metadata["name"] == "tdd"
    assert native_skill.body.strip().startswith("# TDD")
    validate_skill(native_skill)


def test_materialize_skill_for_agent_rejects_unknown_agent_type():
    skill = load_skill("clawrium/tdd")

    with pytest.raises(IncompatibleSkillRegistry, match="Unknown agent type"):
        materialize_skill_for_agent(skill, "not-a-claw")


@pytest.mark.parametrize("agent_type", sorted(NATIVE_REGISTRIES))
def test_materialize_skill_for_agent_rejects_explicit_false_compatibility(
    monkeypatch, tmp_path, agent_type
):
    compatibility = {registry: True for registry in NATIVE_REGISTRIES}
    compatibility[agent_type] = False
    _build_fake_clawrium_skill(tmp_path, compatibility=compatibility)
    monkeypatch.setattr(skills, "_catalog_root", lambda: tmp_path)

    skill = load_skill("clawrium/tdd")
    with pytest.raises(IncompatibleSkillRegistry, match="not compatible"):
        materialize_skill_for_agent(skill, agent_type)


def test_render_skill_md_round_trips_frontmatter_and_body():
    skill = Skill(
        ref=SkillRef("hermes", "custom"),
        path=Path("__materialized__"),
        metadata={"name": "custom", "description": "Tést skill"},
        body="\n# Custom\n\nBody\n",
        skill_md_frontmatter={"name": "custom", "description": "Tést skill"},
    )

    rendered = render_skill_md(skill)
    body, frontmatter = skills._split_frontmatter(rendered)

    assert rendered.endswith("\n")
    assert "Tést skill" in rendered
    assert frontmatter == {"name": "custom", "description": "Tést skill"}
    assert body == "\n# Custom\n\nBody\n"


def test_render_skill_md_handles_empty_body():
    skill = Skill(
        ref=SkillRef("hermes", "empty"),
        path=Path("__materialized__"),
        metadata={"name": "empty", "description": "Empty"},
        body="",
        skill_md_frontmatter={"name": "empty", "description": "Empty"},
    )

    rendered = render_skill_md(skill)

    assert rendered == "---\nname: empty\ndescription: Empty\n---\n"


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


def test_validate_skill_clawrium_rejects_missing_compatibility(monkeypatch, tmp_path):
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
    root: Path,
    dir_name: str = "tdd",
    meta_name: str = "tdd",
    compatibility: dict[str, bool] | None = None,
) -> None:
    """Create a minimal in-tmp_path clawrium catalog containing one skill."""
    skill_dir = root / "clawrium" / dir_name
    skill_dir.mkdir(parents=True)
    compatibility = compatibility or {
        "openclaw": True,
        "hermes": True,
        "zeroclaw": True,
    }
    (skill_dir / "_meta.yaml").write_text(
        "\n".join(
            [
                f"name: {meta_name}",
                "description: fake",
                "version: 0.1.0",
                "compatibility:",
                f"  openclaw: {str(compatibility['openclaw']).lower()}",
                f"  hermes: {str(compatibility['hermes']).lower()}",
                f"  zeroclaw: {str(compatibility['zeroclaw']).lower()}",
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
    (skill_dir / "SKILL.md").write_text("---\n" + "\n".join(lines) + "\n---\nbody\n")
    _copy_schemas(root)


def _write_local_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: fake local\n---\nbody\n"
    )


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
    (skill_dir / "SKILL.md").write_text("---\nname: tdd\ndescription: fake\n---\nbody")
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
    (skill_dir / "SKILL.md").write_text("---\nname: tdd\ndescription: fake\n---\nbody")
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
