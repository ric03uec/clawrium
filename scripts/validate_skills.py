#!/usr/bin/env python3
"""Catalog validator for the in-repo `skills/` tree.

Used by:

- `.github/workflows/skills-validate.yml` — runs on every PR that touches
  `skills/`, `scripts/validate_skills.py`, or the schemas under
  `skills/_schema/`.
- Local contributors — `python scripts/validate_skills.py` before pushing.

What it checks (each failure is collected; the script exits non-zero with
a full report rather than bailing on the first error):

1. **Slug rules.** Every skill directory name matches
   ``^[a-z0-9][a-z0-9_-]*$``. Anything else (incl. `..`, dotfiles, names
   with slashes after normalization) is rejected as a *path-traversal*
   guard. The same rule applies to registry directories: only the four
   names in :data:`clawrium.core.skills.REGISTRIES` are allowed.
2. **No symlinks.** Skills must be plain files / dirs under `skills/`.
   A symlink pointing outside the tree is a covert path-traversal vector
   even when its name passes the slug rule.
3. **Required files.** `clawrium/<name>/` needs both `_meta.yaml` and
   `SKILL.md`. `<claw>/<name>/` needs `SKILL.md`. Missing files are a
   hard failure (vs. the loader's "silently skip" behavior, which is the
   right default at runtime but not in CI).
4. **Dual schema.** `clawrium/*` validates against
   `_schema/clawrium.schema.json`. `<claw>/*` validates against
   `_schema/native/<claw>.schema.json`. Dispatches via
   :func:`clawrium.core.skills.validate_skill`.
5. **Schema-mismatch fixtures rejected.** A clawrium-shaped layout
   placed under a native registry (e.g. `_meta.yaml` exists, or
   frontmatter has clawrium-only `compatibility` block) is rejected:
   the native registry's SKILL.md is the source of truth and the loader
   only reads `_meta.yaml` under `clawrium/`. Similarly, a clawrium
   skill whose `_meta.yaml.name` doesn't match the directory name is
   rejected (the source-dirname == registry-slug invariant from
   `.itx/364/02_PHASE0_FINDINGS.md`).

The script keeps a tight dependency surface: only the in-repo
`clawrium.core.skills` module + `pyyaml` + `jsonschema` (both already
required by the package itself). It does not import the CLI or the GUI.

Exit codes
----------

- ``0`` — every skill in every registry validates.
- ``1`` — at least one validation error. Full report goes to stderr.
- ``2`` — internal failure (e.g. catalog root missing, schema file
  unreadable) — surfaces as a CI failure, not a contributor-fixable
  one.

Usage
-----

::

    python scripts/validate_skills.py              # validates skills/ at repo root
    python scripts/validate_skills.py path/to/skills

The second form is used by the test suite to point the validator at a
fixture tree without monkey-patching `_catalog_root`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from clawrium.core.skills import (
    REGISTRIES,
    SchemaValidationError,
    SkillRef,
    clear_schema_cache,
)

# The four names below are intentionally underscored — they're private
# to `clawrium.core.skills` and don't appear in its `__all__`. We reuse
# them here as a cross-module contract so this script and the runtime
# loader stay in lockstep on parsing/schema semantics. Any rename in
# `skills.py` must touch this import block too.
from clawrium.core.skills import (  # noqa: PLC2701  (private import is deliberate)
    _NAME_RE,
    _load_schema,
    _split_frontmatter,
    _validate_against_schema,
)


# Clawrium-only frontmatter keys that must NOT appear in a native SKILL.md.
# Their presence under skills/<claw>/ signals a copy-paste from a clawrium
# skill — surface the mismatch loudly instead of letting the lenient
# native schema (additionalProperties: true) silently accept it.
_CLAWRIUM_ONLY_KEYS: frozenset[str] = frozenset({"compatibility", "native"})


class _InternalValidationError(Exception):
    """Raised when validation cannot start because the catalog's own
    schema files are missing or malformed.

    This is distinct from `SchemaValidationError`, which fires when a
    *skill* fails validation — those are contributor-fixable and surface
    as `ValidationFailure` entries with exit code 1. An
    `_InternalValidationError` means the validator itself can't do its
    job (corrupt repo state, partial install, schema file deleted) and
    surfaces as exit code 2 per the module-level contract.
    """


@dataclass
class ValidationFailure:
    """One catalog-level validation error.

    `path` is the on-disk location closest to the problem (a skill
    directory, schema file, or registry root). `message` is the
    contributor-facing diagnostic.
    """

    path: Path
    message: str

    def render(self, root: Path) -> str:
        try:
            rel = self.path.relative_to(root)
        except ValueError:
            rel = self.path
        return f"  - {rel}: {self.message}"


def _safe_load_schema(registry: str) -> dict:
    """Wrap `_load_schema` so any schema-side failure surfaces as an
    `_InternalValidationError` (exit code 2) instead of leaking through
    as `SchemaValidationError` (exit 1, contributor-fixable) or as a
    raw `OSError` (Python's default exit 1).

    Catches:
    - `SchemaValidationError`: missing file *or* corrupt JSON, raised
      explicitly by the core loader.
    - `OSError` and subclasses (`PermissionError`, `FileNotFoundError`):
      raceable between the loader's `is_file()` probe and the
      `read_text()` call, or surfaceable on partial installs / chroot
      mounts. Without this we'd exit 1 with an unhandled traceback.
    """
    try:
        return _load_schema(registry)
    except (SchemaValidationError, OSError) as error:
        raise _InternalValidationError(
            f"schema for registry {registry!r} could not be loaded: {error}"
        ) from error


def _is_within(path: Path, root: Path) -> bool:
    """Return True if `path` resolves to a location inside `root`.

    Both arguments are resolved to absolute paths first so symlinks
    pointing outside the catalog are caught even when the link itself
    lives inside it.
    """
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _check_no_symlinks(skill_dir: Path, root: Path) -> list[ValidationFailure]:
    """Walk `skill_dir` and flag any symlink — even one that resolves
    back inside `root`. Skills are a flat content directory; there's no
    legitimate reason for a symlink in this tree."""
    failures: list[ValidationFailure] = []
    for entry in skill_dir.rglob("*"):
        if entry.is_symlink():
            failures.append(
                ValidationFailure(
                    path=entry,
                    message=(
                        "symlinks are not allowed in the skills catalog "
                        "(path-traversal guard); resolve and inline the file"
                    ),
                )
            )
            continue
        # Defense-in-depth: a regular file whose resolved path escapes
        # the catalog should never happen (the symlink check above
        # already catches it), but check anyway so a future bug in the
        # symlink probe doesn't silently let an escape through.
        if not _is_within(entry, root):
            failures.append(
                ValidationFailure(
                    path=entry,
                    message="path resolves outside the skills catalog root",
                )
            )
    return failures


def _validate_clawrium_skill(
    skill_dir: Path, ref: SkillRef
) -> list[ValidationFailure]:
    """Validate a `clawrium/<name>/` skill.

    Requires `_meta.yaml` + `SKILL.md`. `_meta.yaml.name` MUST equal
    the directory name (Phase 0 finding: zeroclaw `skills install`/`remove`
    use the source dirname, so the slug and the meta name must agree).
    """
    failures: list[ValidationFailure] = []
    meta_path = skill_dir / "_meta.yaml"
    skill_md = skill_dir / "SKILL.md"

    if not meta_path.is_file():
        failures.append(
            ValidationFailure(skill_dir, "missing required _meta.yaml")
        )
    if not skill_md.is_file():
        failures.append(
            ValidationFailure(skill_dir, "missing required SKILL.md")
        )
    if failures:
        return failures

    try:
        metadata = yaml.safe_load(meta_path.read_text()) or {}
    except yaml.YAMLError as error:
        return [
            ValidationFailure(
                meta_path, f"_meta.yaml is not valid YAML: {error}"
            )
        ]
    if not isinstance(metadata, dict):
        return [
            ValidationFailure(
                meta_path,
                f"_meta.yaml must be a YAML mapping (got {type(metadata).__name__})",
            )
        ]

    schema = _safe_load_schema("clawrium")
    try:
        _validate_against_schema(metadata, schema, ref=ref)
    except SchemaValidationError as error:
        failures.append(ValidationFailure(meta_path, str(error)))

    if metadata.get("name") != ref.name:
        failures.append(
            ValidationFailure(
                meta_path,
                (
                    f"_meta.yaml `name` ({metadata.get('name')!r}) must equal "
                    f"directory name ({ref.name!r}) — the slug invariant from "
                    ".itx/364/02_PHASE0_FINDINGS.md"
                ),
            )
        )
    return failures


def _validate_native_skill(
    skill_dir: Path, ref: SkillRef
) -> list[ValidationFailure]:
    """Validate a `<claw>/<name>/` skill.

    Native skills are SKILL.md only — frontmatter validates against the
    claw-specific schema. A `_meta.yaml` in this directory is a
    schema-mismatch (copy-paste from a clawrium skill) and is rejected.
    Frontmatter keys reserved for the clawrium-normalized shape
    (``compatibility``, ``native``) are also rejected because the native
    schema is `additionalProperties: true` and would otherwise silently
    accept them.
    """
    failures: list[ValidationFailure] = []
    skill_md = skill_dir / "SKILL.md"

    if (skill_dir / "_meta.yaml").is_file():
        failures.append(
            ValidationFailure(
                skill_dir / "_meta.yaml",
                (
                    "_meta.yaml is only valid under skills/clawrium/ — a "
                    "native skill's frontmatter lives in SKILL.md itself"
                ),
            )
        )

    if not skill_md.is_file():
        failures.append(
            ValidationFailure(skill_dir, "missing required SKILL.md")
        )
        return failures

    try:
        body, frontmatter = _split_frontmatter(skill_md.read_text())
    except SchemaValidationError as error:
        # _split_frontmatter raises when YAML is invalid OR when the
        # frontmatter parses to a non-mapping (e.g. a list or scalar).
        # Catch here so a single broken contributor SKILL.md surfaces
        # as a normal failure entry, not an unhandled traceback in CI.
        failures.append(ValidationFailure(skill_md, str(error)))
        return failures
    if not frontmatter:
        failures.append(
            ValidationFailure(
                skill_md, "SKILL.md must start with a YAML frontmatter block"
            )
        )
        return failures

    schema = _safe_load_schema(ref.registry)
    try:
        _validate_against_schema(frontmatter, schema, ref=ref)
    except SchemaValidationError as error:
        failures.append(ValidationFailure(skill_md, str(error)))

    bad_keys = sorted(_CLAWRIUM_ONLY_KEYS & frontmatter.keys())
    if bad_keys:
        failures.append(
            ValidationFailure(
                skill_md,
                (
                    f"native SKILL.md frontmatter contains clawrium-only "
                    f"keys {bad_keys!r} — move the skill under "
                    f"skills/clawrium/ if you need them, or remove the keys"
                ),
            )
        )

    if frontmatter.get("name") != ref.name:
        failures.append(
            ValidationFailure(
                skill_md,
                (
                    f"SKILL.md frontmatter `name` ({frontmatter.get('name')!r}) "
                    f"must equal directory name ({ref.name!r})"
                ),
            )
        )
    return failures


def _validate_registry(
    registry: str, registry_root: Path, catalog_root: Path
) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    if not registry_root.is_dir():
        # README-only registries (e.g. an empty native namespace) are
        # legitimate during early adoption — the README is not a skill.
        return failures

    for entry in sorted(registry_root.iterdir()):
        # Symlink check MUST come first: `Path.is_file()` follows
        # symlinks, so a `README.md -> /etc/passwd` link would slip past
        # the `is_file()` branch and `continue` before this guard ever
        # ran. Mirrors the ordering in `_validate_unexpected_registries`.
        if entry.is_symlink():
            failures.append(
                ValidationFailure(
                    entry, "registry-level symlinks are not allowed"
                )
            )
            continue
        if entry.is_file():
            # README.md or similar registry-level docs are allowed; any
            # other top-level file is suspicious enough to flag.
            if entry.name not in {"README.md", ".gitkeep"}:
                failures.append(
                    ValidationFailure(
                        entry,
                        (
                            "unexpected file at registry root; skills live in "
                            "their own subdirectory"
                        ),
                    )
                )
            continue
        if not _NAME_RE.match(entry.name):
            failures.append(
                ValidationFailure(
                    entry,
                    (
                        f"directory name {entry.name!r} violates the slug rule "
                        "^[a-z0-9][a-z0-9_-]*$ (path-traversal guard)"
                    ),
                )
            )
            continue

        ref = SkillRef(registry=registry, name=entry.name)
        failures.extend(_check_no_symlinks(entry, catalog_root))
        if registry == "clawrium":
            failures.extend(_validate_clawrium_skill(entry, ref))
        else:
            failures.extend(_validate_native_skill(entry, ref))

    return failures


def _validate_unexpected_registries(
    catalog_root: Path,
) -> list[ValidationFailure]:
    """Flag top-level entries under `skills/` that aren't a known registry,
    a schema directory, or an allowlisted docs file."""
    failures: list[ValidationFailure] = []
    allowed_files = {"README.md"}
    allowed_dirs = set(REGISTRIES) | {"_schema"}
    for entry in sorted(catalog_root.iterdir()):
        if entry.is_symlink():
            failures.append(
                ValidationFailure(
                    entry, "catalog-root symlinks are not allowed"
                )
            )
            continue
        if entry.is_file():
            if entry.name not in allowed_files:
                failures.append(
                    ValidationFailure(
                        entry,
                        (
                            "unexpected file at skills/ root; only README.md "
                            "is allowed alongside the registries"
                        ),
                    )
                )
            continue
        if entry.name not in allowed_dirs:
            failures.append(
                ValidationFailure(
                    entry,
                    (
                        f"unexpected top-level directory {entry.name!r}; "
                        f"allowed: {', '.join(sorted(allowed_dirs))}"
                    ),
                )
            )
    return failures


def validate_catalog(catalog_root: Path) -> list[ValidationFailure]:
    """Run every validation rule on `catalog_root` and return the
    aggregated failure list. An empty list means the catalog is clean.

    Note on schema resolution: the JSON schemas live with the
    ``clawrium.core.skills`` module (installed via the package, or at
    the repo root for development). The validator does NOT honour a
    custom ``_schema/`` directory under ``catalog_root`` — it always
    resolves against the schemas the core loader resolves against. In
    practice this is what you want: every catalog the validator sees
    should agree with the loader's schemas, and CI runs against the
    same checkout so the two roots are the same tree. The fixture
    helper ``_write_schemas`` in the test suite re-creates the
    schemas under ``tmp_path`` only so the fixture *looks* like a
    well-formed catalog; the schema content is never read.
    """
    # Schemas are cached at module level by the core loader. Tests that
    # validate multiple fixture catalogs in the same process need a
    # clean slate; production CI only runs once so the cost is moot.
    clear_schema_cache()

    failures: list[ValidationFailure] = []
    failures.extend(_validate_unexpected_registries(catalog_root))
    for registry in REGISTRIES:
        registry_root = catalog_root / registry
        failures.extend(
            _validate_registry(registry, registry_root, catalog_root)
        )
    return failures


def _default_catalog_root() -> Path:
    """Resolve the in-repo skills/ tree. CI checks out the repo at root,
    so we walk up from this file: scripts/validate_skills.py -> repo
    root -> skills/."""
    return Path(__file__).resolve().parent.parent / "skills"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the in-repo skills/ catalog.",
    )
    parser.add_argument(
        "catalog_root",
        nargs="?",
        type=Path,
        default=None,
        help="Path to a skills/ directory (default: repo-root skills/).",
    )
    args = parser.parse_args(argv)

    root = (args.catalog_root or _default_catalog_root()).resolve()
    if not root.is_dir():
        print(
            f"error: catalog root not found: {root}\n"
            "hint: run `python scripts/validate_skills.py` with no args "
            "to auto-detect the repo-root skills/, or verify the path "
            "you passed.",
            file=sys.stderr,
        )
        return 2

    try:
        failures = validate_catalog(root)
    except _InternalValidationError as error:
        # The validator itself can't run (missing/corrupt schema, etc.).
        # Exit code 2 — matches the contract documented in the module
        # docstring and signals "not contributor-fixable" to CI.
        print(f"error: internal validation failure: {error}", file=sys.stderr)
        print(
            "hint: check that skills/_schema/ is intact and readable; "
            "reinstall the package (`uv sync` or `uv tool install --force "
            "clawrium`) if schema files are missing or corrupt.",
            file=sys.stderr,
        )
        return 2
    if not failures:
        print(f"ok: skills catalog at {root} validates")
        return 0

    print(
        f"error: {len(failures)} skill catalog validation "
        f"failure(s) under {root}:",
        file=sys.stderr,
    )
    for failure in failures:
        print(failure.render(root), file=sys.stderr)
    # Trailing summary mirrors the ok path so the last visible line in
    # a long CI log is actionable, not a bullet point that scrolls the
    # header off-screen. Pytest and ruff both do this.
    print(
        f"FAILED — {len(failures)} error(s). Fix the above, then "
        "re-run: python scripts/validate_skills.py",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
