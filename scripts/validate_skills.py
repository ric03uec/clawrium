#!/usr/bin/env python3
"""Catalog validator for the in-repo `skills/` tree.

Used by:

- `.github/workflows/skills-validate.yml` — runs on every PR that touches
  `skills/`, `scripts/validate_skills.py`, or the schema under
  `skills/_schema/`.
- Local contributors — `python scripts/validate_skills.py` before pushing.

What it checks (each failure is collected; the script exits non-zero with
a full report rather than bailing on the first error):

1. **Slug rules.** Every `skills/vetted/<name>/` directory name matches
   ``^[a-z0-9][a-z0-9_-]*$``. Anything else (incl. `..`, dotfiles, names
   with slashes after normalization) is rejected as a *path-traversal*
   guard. The only allowed top-level entries under `skills/` are the
   `vetted/` source directory, the `_schema/` directory, and a `README.md`.
2. **No symlinks.** Skills must be plain files / dirs under `skills/`.
   A symlink pointing outside the tree is a covert path-traversal vector
   even when its name passes the slug rule.
3. **Required files.** Each `vetted/<name>/` needs a `SKILL.md`. Missing
   files are a hard failure (vs. the loader's "silently skip" behavior,
   which is the right default at runtime but not in CI).
4. **Single schema.** Every `vetted/<name>/SKILL.md` frontmatter validates
   against `_schema/agent-skill.schema.json`. Dispatches via
   :func:`clawrium.core.skills._validate_against_schema`.
5. **Slug invariant.** Frontmatter `name` MUST equal directory name —
   the loader uses the directory name as the canonical slug, and a
   mismatch would let a renamed skill silently fail to resolve.

The script keeps a tight dependency surface: only the in-repo
`clawrium.core.skills` module + `pyyaml` + `jsonschema` (both already
required by the package itself). It does not import the CLI or the GUI.

Exit codes
----------

- ``0`` — every skill in every source validates.
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

from clawrium.core.skills import (
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


# Name of the single source directory the catalog validator walks. The
# `local/` source lives in `${XDG_CONFIG_HOME:-~/.config}/clawrium/skills`
# and is never validated by this script — it's user-owned content, not
# in-repo content.
_VETTED_SOURCE = "vetted"


class _InternalValidationError(Exception):
    """Raised when validation cannot start because the catalog's own
    schema file is missing or malformed.

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
    directory, schema file, or source root). `message` is the
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


def _safe_load_schema() -> dict:
    """Wrap `_load_schema` so any schema-side failure surfaces as an
    `_InternalValidationError` (exit code 2) instead of leaking through
    as `SchemaValidationError` (exit 1, contributor-fixable) or as a
    raw `OSError` (Python's default exit 1).
    """
    try:
        return _load_schema()
    except (SchemaValidationError, OSError) as error:
        raise _InternalValidationError(
            f"agent-skill schema could not be loaded: {error}"
        ) from error


def _is_within(path: Path, root: Path) -> bool:
    """Return True if `path` resolves to a location inside `root`."""
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
        if not _is_within(entry, root):
            failures.append(
                ValidationFailure(
                    path=entry,
                    message="path resolves outside the skills catalog root",
                )
            )
    return failures


def _validate_vetted_skill(
    skill_dir: Path, ref: SkillRef
) -> list[ValidationFailure]:
    """Validate a single `skills/vetted/<name>/` skill.

    Requires `SKILL.md` whose frontmatter parses, validates against the
    single `agent-skill.schema.json`, and whose `name` field equals the
    directory name.
    """
    failures: list[ValidationFailure] = []
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        failures.append(
            ValidationFailure(skill_dir, "missing required SKILL.md")
        )
        return failures

    try:
        body, frontmatter = _split_frontmatter(skill_md.read_text())
    except SchemaValidationError as error:
        failures.append(ValidationFailure(skill_md, str(error)))
        return failures
    if not frontmatter:
        failures.append(
            ValidationFailure(
                skill_md, "SKILL.md must start with a YAML frontmatter block"
            )
        )
        return failures

    schema = _safe_load_schema()
    try:
        _validate_against_schema(frontmatter, schema, ref=ref)
    except SchemaValidationError as error:
        failures.append(ValidationFailure(skill_md, str(error)))

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


def _validate_vetted_source(
    source_root: Path, catalog_root: Path
) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    if not source_root.is_dir():
        # An empty vetted/ source is legitimate during early development —
        # the source dir may be absent until the first skill lands.
        return failures

    for entry in sorted(source_root.iterdir()):
        # Symlink check MUST come first: `Path.is_file()` follows
        # symlinks, so a `README.md -> /etc/passwd` link would slip past
        # the `is_file()` branch and `continue` before this guard ever
        # ran.
        if entry.is_symlink():
            failures.append(
                ValidationFailure(
                    entry, "source-level symlinks are not allowed"
                )
            )
            continue
        if entry.is_file():
            # README.md or similar source-level docs are allowed; any
            # other top-level file is suspicious enough to flag.
            if entry.name not in {"README.md", ".gitkeep"}:
                failures.append(
                    ValidationFailure(
                        entry,
                        (
                            "unexpected file at vetted/ root; skills live in "
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

        ref = SkillRef(source=_VETTED_SOURCE, name=entry.name)
        failures.extend(_check_no_symlinks(entry, catalog_root))
        failures.extend(_validate_vetted_skill(entry, ref))

    return failures


def _validate_top_level(catalog_root: Path) -> list[ValidationFailure]:
    """Flag top-level entries under `skills/` that aren't the vetted/
    source, the schema directory, or an allowlisted docs file."""
    failures: list[ValidationFailure] = []
    allowed_files = {"README.md"}
    allowed_dirs = {_VETTED_SOURCE, "_schema"}
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
                            "is allowed alongside the source directories"
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

    Note on schema resolution: the JSON schema lives with the
    ``clawrium.core.skills`` module (installed via the package, or at
    the repo root for development). The validator does NOT honour a
    custom ``_schema/`` directory under ``catalog_root`` — it always
    resolves against the schema the core loader resolves against. In
    practice this is what you want: every catalog the validator sees
    should agree with the loader's schema, and CI runs against the
    same checkout so the two roots are the same tree.
    """
    # Schema is cached at module level by the core loader. Tests that
    # validate multiple fixture catalogs in the same process need a
    # clean slate; production CI only runs once so the cost is moot.
    clear_schema_cache()

    failures: list[ValidationFailure] = []
    failures.extend(_validate_top_level(catalog_root))
    failures.extend(
        _validate_vetted_source(catalog_root / _VETTED_SOURCE, catalog_root)
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
        print(f"error: internal validation failure: {error}", file=sys.stderr)
        print(
            "hint: check that skills/_schema/ is intact and readable; "
            "reinstall the package (`uv sync` or `uv tool install --force "
            "clawrium`) if the schema file is missing or corrupt.",
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
    print(
        f"FAILED — {len(failures)} error(s). Fix the above, then "
        "re-run: python scripts/validate_skills.py",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
