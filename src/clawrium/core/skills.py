"""Unified skills catalog: vetted (in-repo) + local (user-owned).

Reference grammar: ``<source>/<name>`` where ``source ∈ {vetted, local}``
and ``<name>`` matches ``^[a-z0-9][a-z0-9_-]*$``. Bare names, URLs, and
arbitrary paths are rejected at ``parse_skill_ref``.

The catalog is the union of two on-disk roots:

- **vetted/**: shipped inside the wheel as ``clawrium/_skills/vetted/`` and
  present at the repo root for development. Read-only at runtime.
- **local/**: ``~/.config/clawrium/skills/<name>/``. Created and edited via
  ``clm skill add|edit|remove`` or the GUI.

Skill names are globally unique across both sources — a ``vetted/tdd`` and
``local/tdd`` collision raises ``SkillNameConflict`` at load time.

Each skill is a single ``SKILL.md`` file with YAML frontmatter following
the agentskills.io standard. Required fields: ``name``, ``description``.

Per-claw support is hardcoded in ``SUPPORTED_CLAWS_BY_DEFAULT``. Skills
attach only to agents whose claw type is True in that table. Openclaw and
zeroclaw are off in v1 and will be flipped on in follow-up issues once
their materializers + e2e tests are re-validated.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from clawrium.core.config import get_config_dir

logger = logging.getLogger(__name__)


SOURCES: tuple[str, ...] = ("vetted", "local")
"""Allowed skill sources. Order is preserved for catalog listings."""

SUPPORTED_CLAWS_BY_DEFAULT: dict[str, bool] = {
    "hermes": True,
    "openclaw": False,
    "zeroclaw": False,
}
"""Per-claw support table. Skills attach only where True. Edit gated via PR review."""

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_EXTERNAL_PREFIXES = (
    "http://",
    "https://",
    "git+",
    "git@",
    "ssh://",
    "ftp://",
    "file://",
)


class SkillError(Exception):
    """Base class for catalog-loader errors."""


class MissingSourcePrefix(SkillError):
    """Raised when a skill ref omits the ``<source>/`` prefix."""


class InvalidSkillRef(SkillError):
    """Raised when a skill ref is malformed (bad chars, unknown source, etc.)."""


class ExternalSourceBlocked(SkillError):
    """Raised when a skill ref looks like a URL or arbitrary path."""


class SkillNotFound(SkillError):
    """Raised when ``<source>/<name>`` is not present in the catalog."""


class SchemaValidationError(SkillError):
    """Raised when a skill's frontmatter fails the agentskills schema."""


class SkillNameConflict(SkillError):
    """Raised when the same name appears under both vetted/ and local/."""


class SkillNameImmutable(SkillError):
    """Raised when an edit tries to change the ``name`` field of a skill."""


class ReadOnlySource(SkillError):
    """Raised when a write operation targets a ``vetted/*`` ref."""


class ClawNotSupported(SkillError):
    """Raised when a skill is attached to a claw whose support flag is False."""


@dataclass(frozen=True)
class SkillRef:
    """Parsed ``<source>/<name>`` pair."""

    source: str
    name: str

    def __str__(self) -> str:
        return f"{self.source}/{self.name}"


@dataclass(frozen=True)
class Skill:
    """Loaded skill: parsed frontmatter + raw SKILL.md body."""

    ref: SkillRef
    path: Path
    metadata: dict[str, Any]
    body: str


def _vetted_catalog_root() -> Path | None:
    """Locate the on-disk root of the bundled vetted/ catalog.

    Order:
      1. Bundled inside installed wheel as ``clawrium/_skills/vetted/``.
      2. Repo root ``skills/vetted/`` (dev checkout).

    Returns None if neither exists — used by ``list_skills`` which is
    expected to keep working with only a local catalog present.
    """
    bundled = Path(__file__).resolve().parent.parent / "_skills" / "vetted"
    if bundled.is_dir():
        return bundled
    repo_root = Path(__file__).resolve().parents[3]
    dev = repo_root / "skills" / "vetted"
    if dev.is_dir():
        return dev
    return None


def _local_catalog_root() -> Path:
    """Return the user-owned local skills directory.

    Does not create the directory — callers that write should mkdir.
    """
    return get_config_dir() / "skills"


def _source_root(source: str) -> Path | None:
    if source == "vetted":
        return _vetted_catalog_root()
    if source == "local":
        root = _local_catalog_root()
        return root if root.is_dir() else None
    return None


def parse_skill_ref(raw: str) -> SkillRef:
    """Parse ``<source>/<name>`` into a ``SkillRef``."""
    if raw is None or not isinstance(raw, str):
        raise InvalidSkillRef(
            "Skill reference must be a non-empty string of the form "
            "`<source>/<name>` (e.g. `vetted/tdd`)."
        )

    candidate = raw.strip()
    if not candidate:
        raise InvalidSkillRef(
            "Skill reference is empty. Expected `<source>/<name>` "
            "(e.g. `vetted/tdd`)."
        )

    lowered = candidate.lower()
    if any(lowered.startswith(prefix) for prefix in _EXTERNAL_PREFIXES):
        raise ExternalSourceBlocked(
            f"External skill sources are not allowed: {candidate!r}. "
            "Skills must be referenced as `<source>/<name>`."
        )

    if candidate.startswith("/") or candidate.startswith("~"):
        raise ExternalSourceBlocked(
            f"Path-style skill sources are not allowed: {candidate!r}. "
            "Skills must be referenced as `<source>/<name>`."
        )

    if "/" not in candidate:
        hint = _bare_name_hint(candidate)
        raise MissingSourcePrefix(
            f"Skill reference {candidate!r} is missing a source prefix. "
            "Use `<source>/<name>` (e.g. `vetted/tdd`)."
            + (f" Did you mean: {hint}?" if hint else "")
        )

    parts = candidate.split("/")
    if len(parts) != 2:
        raise InvalidSkillRef(
            f"Skill reference {candidate!r} must have exactly one `/` "
            "separator. Use `<source>/<name>`."
        )

    source, name = parts
    if source not in SOURCES:
        raise InvalidSkillRef(
            f"Unknown source {source!r} in {candidate!r}. "
            f"Allowed: {', '.join(SOURCES)}."
        )
    if not _NAME_RE.match(name):
        raise InvalidSkillRef(
            f"Invalid skill name {name!r} in {candidate!r}. "
            "Names must match ^[a-z0-9][a-z0-9_-]*$."
        )

    return SkillRef(source=source, name=name)


def _bare_name_hint(name: str) -> str:
    if not _NAME_RE.match(name):
        return ""
    matches: list[str] = []
    for source in SOURCES:
        root = _source_root(source)
        if root and (root / name).is_dir():
            matches.append(f"`{source}/{name}`")
    return ", ".join(matches)


def list_skills(source: str | None = None) -> list[SkillRef]:
    """Enumerate skills in the catalog.

    ``source=None`` returns the union of both sources, with global name
    uniqueness enforced. If a name appears under both, ``SkillNameConflict``
    is raised — the catalog is in an invalid state until the user resolves it.
    """
    if source is not None and source not in SOURCES:
        raise InvalidSkillRef(
            f"Unknown source {source!r}. Allowed: {', '.join(SOURCES)}."
        )

    sources: Iterable[str] = (source,) if source else SOURCES
    seen: dict[str, str] = {}
    refs: list[SkillRef] = []
    for src in sources:
        root = _source_root(src)
        if root is None:
            continue
        names: list[str] = []
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            if not _NAME_RE.match(entry.name):
                continue
            if not (entry / "SKILL.md").is_file():
                continue
            names.append(entry.name)
        for name in sorted(names):
            if source is None and name in seen:
                raise SkillNameConflict(
                    f"Skill name {name!r} exists in both {seen[name]!r} "
                    f"and {src!r}. Names must be globally unique — remove "
                    "or rename one of them."
                )
            seen[name] = src
            refs.append(SkillRef(source=src, name=name))
    return refs


def find_skill_by_name(name: str) -> SkillRef | None:
    """Return the ``SkillRef`` for ``name`` across both sources, or None.

    Raises ``SkillNameConflict`` if the name appears in both.
    """
    if not _NAME_RE.match(name):
        return None
    matches: list[SkillRef] = []
    for src in SOURCES:
        root = _source_root(src)
        if root and (root / name / "SKILL.md").is_file():
            matches.append(SkillRef(source=src, name=name))
    if len(matches) > 1:
        sources = ", ".join(repr(m.source) for m in matches)
        raise SkillNameConflict(
            f"Skill name {name!r} exists in multiple sources: {sources}. "
            "Names must be globally unique."
        )
    return matches[0] if matches else None


def load_skill(ref: SkillRef | str) -> Skill:
    """Load a skill from the catalog."""
    if isinstance(ref, str):
        ref = parse_skill_ref(ref)

    root = _source_root(ref.source)
    if root is None:
        raise SkillNotFound(
            f"Skill {ref} not found: {ref.source!r} catalog is unavailable."
        )

    skill_dir = root / ref.name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillNotFound(
            f"Skill {ref} not found. Run `clm skill list` to see available skills."
        )

    body, frontmatter = _split_frontmatter(skill_md.read_text())
    return Skill(ref=ref, path=skill_dir, metadata=frontmatter, body=body)


def validate_skill(skill: Skill) -> None:
    """Validate ``skill.metadata`` against the agentskills schema.

    Also enforces that ``metadata.name`` equals the directory slug.
    """
    schema = _load_schema()
    _validate_against_schema(skill.metadata, schema, ref=skill.ref)
    if skill.metadata.get("name") != skill.ref.name:
        raise SchemaValidationError(
            f"Skill {skill.ref}: frontmatter `name` "
            f"({skill.metadata.get('name')!r}) must equal directory "
            f"name ({skill.ref.name!r})."
        )


def check_claw_supported(claw: str) -> None:
    """Raise ``ClawNotSupported`` if the claw is not in the support table."""
    if claw not in SUPPORTED_CLAWS_BY_DEFAULT:
        raise ClawNotSupported(
            f"Unknown agent type {claw!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_CLAWS_BY_DEFAULT))}."
        )
    if not SUPPORTED_CLAWS_BY_DEFAULT[claw]:
        raise ClawNotSupported(
            f"Skills are not yet supported on {claw!r} agents. "
            "Currently supported: "
            f"{', '.join(c for c, ok in SUPPORTED_CLAWS_BY_DEFAULT.items() if ok)}."
        )


def materialize_for_claw(skill: Skill, claw: str) -> tuple[dict[str, Any], str]:
    """Return the (frontmatter, body) pair to write on a ``claw``-type agent.

    Gated on ``SUPPORTED_CLAWS_BY_DEFAULT[claw]``. The flat agentskills
    frontmatter is passed through verbatim — per-claw native dialects are
    handled by the apply playbooks today; this function is the single
    place to inject any future per-claw shape translation.
    """
    check_claw_supported(claw)
    # Strip None/empty values for a clean rendered file.
    frontmatter: dict[str, Any] = {}
    for key, value in skill.metadata.items():
        if value in (None, "", [], {}):
            continue
        frontmatter[key] = value
    return frontmatter, skill.body


def _split_frontmatter(text: str) -> tuple[str, dict[str, Any]]:
    """Split a SKILL.md into (body, frontmatter dict)."""
    if not text.startswith("---\n"):
        return text, {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return text, {}
    yaml_block = text[4:end]
    body = text[end + len("\n---\n") :]
    try:
        parsed = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as error:
        raise SchemaValidationError(
            f"SKILL.md frontmatter is not valid YAML: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise SchemaValidationError("SKILL.md frontmatter must be a YAML mapping.")
    return body, parsed


_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _load_schema() -> dict[str, Any]:
    cached = _SCHEMA_CACHE.get("agent-skill")
    if cached is not None:
        return cached

    # Schema is bundled next to the skills root.
    bundled = Path(__file__).resolve().parent.parent / "_skills" / "_schema" / "agent-skill.schema.json"
    if bundled.is_file():
        schema_path = bundled
    else:
        repo_root = Path(__file__).resolve().parents[3]
        schema_path = repo_root / "skills" / "_schema" / "agent-skill.schema.json"

    if not schema_path.is_file():
        raise SchemaValidationError(
            f"agent-skill schema file not found at {schema_path}."
        )
    try:
        schema = json.loads(schema_path.read_text())
    except json.JSONDecodeError as error:
        raise SchemaValidationError(
            f"Schema {schema_path} is not valid JSON: {error}"
        ) from error
    _SCHEMA_CACHE["agent-skill"] = schema
    return schema


def clear_schema_cache() -> None:
    _SCHEMA_CACHE.clear()


def _validate_against_schema(
    data: dict[str, Any], schema: dict[str, Any], ref: SkillRef
) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise SchemaValidationError(
            "jsonschema package is required for skill validation."
        ) from error

    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(data),
        key=lambda e: [str(p) for p in e.absolute_path],
    )
    if not errors:
        return
    messages = []
    for err in errors:
        location = ".".join(str(p) for p in err.absolute_path) or "<root>"
        messages.append(f"  - {location}: {err.message}")
    raise SchemaValidationError(
        f"Skill {ref} failed agent-skill validation:\n" + "\n".join(messages)
    )


def supported_claws() -> list[str]:
    """Return list of claws where skills support is on."""
    return [c for c, ok in SUPPORTED_CLAWS_BY_DEFAULT.items() if ok]


def claws_support_map() -> dict[str, bool]:
    """Return a copy of the support table for UI rendering."""
    return dict(SUPPORTED_CLAWS_BY_DEFAULT)


__all__ = [
    "SOURCES",
    "SUPPORTED_CLAWS_BY_DEFAULT",
    "Skill",
    "SkillRef",
    "SkillError",
    "MissingSourcePrefix",
    "InvalidSkillRef",
    "ExternalSourceBlocked",
    "SkillNotFound",
    "SchemaValidationError",
    "SkillNameConflict",
    "SkillNameImmutable",
    "ReadOnlySource",
    "ClawNotSupported",
    "parse_skill_ref",
    "list_skills",
    "load_skill",
    "validate_skill",
    "find_skill_by_name",
    "check_claw_supported",
    "materialize_for_claw",
    "supported_claws",
    "claws_support_map",
    "clear_schema_cache",
]
