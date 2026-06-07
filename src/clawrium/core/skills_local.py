"""Create/update/delete operations on the user-owned local skills catalog.

Local skills live at ``~/.config/clawrium/skills/<name>/SKILL.md``. They
follow the same agentskills.io frontmatter schema as vetted skills and
share the global-name-uniqueness rule (a local name that already exists
under ``vetted/`` is a ``SkillNameConflict``).

All writes are atomic: content is staged to a sibling ``.tmp`` file in
the same directory and renamed into place. Concurrent readers never see
a half-written ``SKILL.md``.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from clawrium.core.skills import (
    ReadOnlySource,
    SkillNameConflict,
    SkillNameImmutable,
    SkillNotFound,
    SkillRef,
    _local_catalog_root,
    _NAME_RE,
    _vetted_catalog_root,
    load_skill,
    parse_skill_ref,
    validate_skill,
)
from clawrium.core.skills import Skill as _Skill  # noqa: F401

logger = logging.getLogger(__name__)


__all__ = [
    "create_local_skill",
    "update_local_skill",
    "delete_local_skill",
]


def _ensure_local_root() -> Path:
    root = _local_catalog_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError as error:
        logger.debug("Could not chmod %s: %s", root, error)
    return root


def _require_local_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        from clawrium.core.skills import InvalidSkillRef

        raise InvalidSkillRef(
            f"Invalid skill name {name!r}. Names must match ^[a-z0-9][a-z0-9_-]*$."
        )


def _check_name_globally_unique(name: str, *, allow_existing_local: bool) -> None:
    """Raise ``SkillNameConflict`` if ``name`` collides across sources.

    ``allow_existing_local`` is True for the update path (the target
    must exist) and False for create (must not exist anywhere).
    """
    vetted_root = _vetted_catalog_root()
    if vetted_root is not None and (vetted_root / name).is_dir():
        raise SkillNameConflict(
            f"Skill name {name!r} is already taken by `vetted/{name}`. "
            "Choose a different name."
        )
    local_root = _local_catalog_root()
    local_skill = local_root / name / "SKILL.md"
    if local_skill.is_file() and not allow_existing_local:
        raise SkillNameConflict(
            f"Skill `local/{name}` already exists. Use `clm skill edit` to update it."
        )


def _render_skill_md(frontmatter: dict[str, Any], body: str) -> str:
    yaml_block = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{yaml_block}\n---\n\n{body.lstrip()}"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(prefix=".SKILL.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def create_local_skill(
    name: str, frontmatter: dict[str, Any], body: str
) -> SkillRef:
    """Create a new local skill. Returns its SkillRef.

    Validates the frontmatter against the agentskills schema before
    writing. Fails closed on global name conflict.
    """
    _require_local_name(name)
    _check_name_globally_unique(name, allow_existing_local=False)

    # Force `name` in frontmatter to match the slug.
    fm = dict(frontmatter)
    fm["name"] = name

    ref = SkillRef(source="local", name=name)
    _ensure_local_root()
    skill_dir = _local_catalog_root() / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    try:
        skill_dir.chmod(0o700)
    except OSError:
        pass

    skill_md = skill_dir / "SKILL.md"
    _atomic_write(skill_md, _render_skill_md(fm, body))

    # Reload + validate so a bad frontmatter shape is rejected loudly.
    loaded = load_skill(ref)
    try:
        validate_skill(loaded)
    except Exception:
        # Roll back the create.
        try:
            skill_md.unlink()
            skill_dir.rmdir()
        except OSError:
            pass
        raise
    return ref


def update_local_skill(
    name: str, frontmatter: dict[str, Any], body: str
) -> SkillRef:
    """Replace contents of an existing local skill. ``name`` is immutable."""
    _require_local_name(name)

    local_skill = _local_catalog_root() / name / "SKILL.md"
    if not local_skill.is_file():
        # Check if the user is trying to edit a vetted skill.
        vetted_root = _vetted_catalog_root()
        if vetted_root and (vetted_root / name / "SKILL.md").is_file():
            raise ReadOnlySource(
                f"Cannot edit `vetted/{name}`: vetted skills are read-only. "
                "Submit a PR to change them."
            )
        raise SkillNotFound(f"Local skill `local/{name}` not found.")

    fm = dict(frontmatter)
    if "name" in fm and fm["name"] != name:
        raise SkillNameImmutable(
            f"Cannot change skill name from {name!r} to {fm['name']!r}. "
            "Names are immutable — delete and re-create instead."
        )
    fm["name"] = name

    ref = SkillRef(source="local", name=name)
    # Snapshot prior content for rollback on validation failure.
    prior = local_skill.read_text()
    _atomic_write(local_skill, _render_skill_md(fm, body))
    try:
        loaded = load_skill(ref)
        validate_skill(loaded)
    except Exception:
        _atomic_write(local_skill, prior)
        raise
    return ref


def delete_local_skill(name: str) -> bool:
    """Delete a local skill. Returns True if it existed and was removed."""
    _require_local_name(name)
    skill_dir = _local_catalog_root() / name
    skill_md = skill_dir / "SKILL.md"

    vetted_root = _vetted_catalog_root()
    if vetted_root and (vetted_root / name / "SKILL.md").is_file() and not skill_md.is_file():
        raise ReadOnlySource(
            f"Cannot delete `vetted/{name}`: vetted skills are read-only."
        )
    if not skill_md.is_file():
        return False
    try:
        skill_md.unlink()
    except OSError:
        pass
    # Best-effort cleanup of the directory if now empty.
    try:
        if skill_dir.is_dir() and not any(skill_dir.iterdir()):
            skill_dir.rmdir()
    except OSError:
        pass
    return True


def delete_skill_by_ref(ref: SkillRef | str) -> bool:
    """Delete a skill referenced as ``<source>/<name>``. Raises ReadOnlySource on vetted."""
    parsed = parse_skill_ref(ref) if isinstance(ref, str) else ref
    if parsed.source == "vetted":
        raise ReadOnlySource(
            f"Cannot delete `{parsed}`: vetted skills are read-only."
        )
    return delete_local_skill(parsed.name)
