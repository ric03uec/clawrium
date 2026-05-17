"""Skills catalog loader for clawrium-managed registries.

Single chokepoint for resolving and validating skill references. The only
install source recognized by `clm` is the in-repo `skills/` catalog —
shipped inside the wheel as `clawrium/_skills/` (see `pyproject.toml`
`force-include`) and present at the repo root for development.

Reference grammar: `<registry>/<name>` where `<registry>` is one of
{`clawrium`, `openclaw`, `hermes`, `zeroclaw`} and `<name>` matches
`^[a-z0-9][a-z0-9_-]*$`. Bare names, URLs, and arbitrary paths are
rejected at `parse_skill_ref` with stable error classes.

Phase 1 surface: `parse_skill_ref`, `load_skill`, `validate_skill`,
`list_skills`. Per-agent install (state file, apply playbooks) is Phases
2–3; this module avoids any agent-mutation concerns.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

logger = logging.getLogger(__name__)


REGISTRIES: tuple[str, ...] = ("clawrium", "openclaw", "hermes", "zeroclaw")
"""Allowed registries. Order is preserved for `clm skill list` output."""

NATIVE_REGISTRIES: frozenset[str] = frozenset({"openclaw", "hermes", "zeroclaw"})
"""Registries whose skills validate against the native (claw-specific) schema."""

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
"""Slug pattern for `<name>` in `<registry>/<name>` and for directory names."""

_EXTERNAL_PREFIXES = (
    "http://",
    "https://",
    "git+",
    "git@",
    "ssh://",
    "ftp://",
    "file://",
)
"""Schemes blocked at `parse_skill_ref`."""


class SkillError(Exception):
    """Base class for catalog-loader errors."""


class MissingRegistryPrefix(SkillError):
    """Raised when a skill ref omits the `<registry>/` prefix."""


class InvalidSkillRef(SkillError):
    """Raised when a skill ref is otherwise malformed (bad chars, empty, etc.)."""


class ExternalSourceBlocked(SkillError):
    """Raised when a skill ref looks like a URL or arbitrary path."""


class SkillNotFound(SkillError):
    """Raised when `<registry>/<name>` is not present in the catalog."""


class SchemaValidationError(SkillError):
    """Raised when a skill's frontmatter/meta fails its registry's schema."""


class IncompatibleSkillRegistry(SkillError):
    """Raised when a skill is requested on an agent type it can't run on.

    - `<claw>/<name>`: only installable on agents whose type matches the
      registry exactly. Cross-claw native installs are a hard error,
      not a warning — the SKILL.md is in a per-claw native format.
    - `clawrium/<name>`: installable on any agent type whose entry in
      the skill's `_meta.yaml.compatibility` map is truthy. A
      `compatibility: {hermes: false}` flag fails closed.
    """


@dataclass(frozen=True)
class SkillRef:
    """Parsed `<registry>/<name>` pair."""

    registry: str
    name: str

    def __str__(self) -> str:
        return f"{self.registry}/{self.name}"


@dataclass(frozen=True)
class Skill:
    """Loaded skill: parsed metadata + raw SKILL.md body.

    For `clawrium/*` skills, `metadata` is the parsed `_meta.yaml`. For
    native `<claw>/*` skills, `metadata` is the SKILL.md frontmatter.
    """

    ref: SkillRef
    path: Path
    metadata: dict[str, Any]
    body: str
    skill_md_frontmatter: dict[str, Any] = field(default_factory=dict)


def _catalog_root() -> Path:
    """Locate the on-disk root of the `skills/` catalog.

    Order of resolution:

    1. Bundled inside the installed wheel as `clawrium/_skills/` (see
       `pyproject.toml` `force-include`).
    2. Repo root, as a sibling of `src/clawrium/` (development checkout).

    The first existing path wins. We return a `Path` rather than a
    `Traversable` so callers can do path arithmetic and `is_dir()` checks
    without juggling two filesystem-ish APIs.
    """
    bundled = Path(__file__).resolve().parent.parent / "_skills"
    if bundled.is_dir():
        return bundled

    # Repo-root fallback: clawrium-issue-380/skills/, with this file at
    # clawrium-issue-380/src/clawrium/core/skills.py — four parents up.
    repo_root = Path(__file__).resolve().parents[3]
    dev = repo_root / "skills"
    if dev.is_dir():
        return dev

    raise SkillNotFound(
        "skills catalog not found (looked for bundled "
        f"{bundled} and dev {dev}). "
        "Reinstall with: `uv tool install --force clawrium`."
    )


def parse_skill_ref(raw: str) -> SkillRef:
    """Parse `<registry>/<name>` into a `SkillRef`.

    Rejects, in this precedence order:

    - Empty or whitespace-only refs -> `InvalidSkillRef`.
    - URLs / git+ / ssh:// / absolute paths -> `ExternalSourceBlocked`.
    - Bare names (no `/`) -> `MissingRegistryPrefix` with a hint listing
      every existing `<registry>/<name>` match for that name so the user
      gets a copy-pasteable correction.
    - Two-part refs with an unknown registry or a malformed name ->
      `InvalidSkillRef`.

    The hint cost in the bare-name branch is intentional: catalog reads
    are cheap (`is_dir()` per registry), and a clear "did you mean
    `clawrium/tdd`?" message is the dominant ergonomic win over a flat
    error.
    """
    if raw is None or not isinstance(raw, str):
        raise InvalidSkillRef(
            "Skill reference must be a non-empty string of the form "
            "`<registry>/<name>` (e.g. `clawrium/tdd`)."
        )

    candidate = raw.strip()
    if not candidate:
        raise InvalidSkillRef(
            "Skill reference is empty. Expected `<registry>/<name>` "
            "(e.g. `clawrium/tdd`)."
        )

    lowered = candidate.lower()
    if any(lowered.startswith(prefix) for prefix in _EXTERNAL_PREFIXES):
        raise ExternalSourceBlocked(
            f"External skill sources are not allowed: {candidate!r}. "
            "Skills must be referenced as `<registry>/<name>` from the "
            "in-repo catalog (e.g. `clawrium/tdd`)."
        )

    if candidate.startswith("/") or candidate.startswith("~"):
        raise ExternalSourceBlocked(
            f"Path-style skill sources are not allowed: {candidate!r}. "
            "Skills must be referenced as `<registry>/<name>` from the "
            "in-repo catalog (e.g. `clawrium/tdd`)."
        )

    if "/" not in candidate:
        hint = _bare_name_hint(candidate)
        raise MissingRegistryPrefix(
            f"Skill reference {candidate!r} is missing a registry prefix. "
            "Use `<registry>/<name>` (e.g. `clawrium/tdd`)."
            + (f" Did you mean: {hint}?" if hint else "")
        )

    parts = candidate.split("/")
    if len(parts) != 2:
        raise InvalidSkillRef(
            f"Skill reference {candidate!r} must have exactly one `/` "
            "separator. Use `<registry>/<name>` (e.g. `clawrium/tdd`)."
        )

    registry, name = parts
    if registry not in REGISTRIES:
        raise InvalidSkillRef(
            f"Unknown registry {registry!r} in {candidate!r}. "
            f"Allowed: {', '.join(REGISTRIES)}."
        )
    if not _NAME_RE.match(name):
        raise InvalidSkillRef(
            f"Invalid skill name {name!r} in {candidate!r}. "
            "Names must match ^[a-z0-9][a-z0-9_-]*$."
        )

    return SkillRef(registry=registry, name=name)


def _bare_name_hint(name: str) -> str:
    """Return a comma-separated list of `<registry>/<name>` matches.

    Used in `MissingRegistryPrefix`. Best-effort: catalog access failures
    are swallowed so a missing catalog never masks the underlying user
    error.
    """
    if not _NAME_RE.match(name):
        return ""
    try:
        root = _catalog_root()
    except SkillNotFound:
        return ""

    matches: list[str] = []
    for registry in REGISTRIES:
        if (root / registry / name).is_dir():
            matches.append(f"`{registry}/{name}`")
    return ", ".join(matches)


def list_skills(registry: str | None = None) -> list[SkillRef]:
    """Enumerate skills in the catalog.

    `registry=None` returns refs from every registry, sorted by registry
    (per `REGISTRIES` order) and then by name. `registry=<name>` filters
    to a single registry; an unknown registry raises `InvalidSkillRef`.
    """
    if registry is not None and registry not in REGISTRIES:
        raise InvalidSkillRef(
            f"Unknown registry {registry!r}. Allowed: {', '.join(REGISTRIES)}."
        )

    root = _catalog_root()
    registries: Iterable[str] = (registry,) if registry else REGISTRIES

    refs: list[SkillRef] = []
    for reg in registries:
        reg_dir = root / reg
        if not reg_dir.is_dir():
            continue
        names: list[str] = []
        for entry in reg_dir.iterdir():
            if not entry.is_dir():
                continue
            if not _NAME_RE.match(entry.name):
                continue
            if not _has_skill_files(entry, reg):
                continue
            names.append(entry.name)
        for name in sorted(names):
            refs.append(SkillRef(registry=reg, name=name))
    return refs


def _has_skill_files(skill_dir: Path, registry: str) -> bool:
    """Return True if `skill_dir` looks like a real skill, not a placeholder.

    For `clawrium/*` we require both `_meta.yaml` and `SKILL.md` (the
    latter is the canonical content materialized to each claw). For
    native registries we require `SKILL.md` only.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return False
    if registry == "clawrium":
        meta = skill_dir / "_meta.yaml"
        return meta.is_file()
    return True


def load_skill(ref: SkillRef | str) -> Skill:
    """Load a skill from the catalog.

    `ref` may be a pre-parsed `SkillRef` or a raw `<registry>/<name>`
    string (in which case it is passed through `parse_skill_ref`, so
    every error class from that function may surface here).
    """
    if isinstance(ref, str):
        ref = parse_skill_ref(ref)

    root = _catalog_root()
    skill_dir = root / ref.registry / ref.name
    if not skill_dir.is_dir():
        raise SkillNotFound(
            f"Skill {ref} not found. Run `clm skill list` to see available skills."
        )

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillNotFound(
            f"Skill {ref} is missing SKILL.md at {skill_md}."
        )
    body, frontmatter = _split_frontmatter(skill_md.read_text())

    if ref.registry == "clawrium":
        meta_path = skill_dir / "_meta.yaml"
        if not meta_path.is_file():
            raise SkillNotFound(
                f"Skill {ref} is missing _meta.yaml at {meta_path}."
            )
        try:
            metadata = yaml.safe_load(meta_path.read_text()) or {}
        except yaml.YAMLError as error:
            raise SchemaValidationError(
                f"Failed to parse {meta_path}: {error}"
            ) from error
        if not isinstance(metadata, dict):
            raise SchemaValidationError(
                f"{meta_path} must be a YAML mapping (got {type(metadata).__name__})."
            )
    else:
        metadata = dict(frontmatter)

    return Skill(
        ref=ref,
        path=skill_dir,
        metadata=metadata,
        body=body,
        skill_md_frontmatter=frontmatter,
    )


def validate_skill(skill: Skill) -> None:
    """Validate `skill.metadata` against its registry's JSON schema.

    Dual-schema dispatch: `clawrium/*` validates against
    `_schema/clawrium.schema.json`; `<claw>/*` validates against
    `_schema/native/<claw>.schema.json`. The schema files are loaded
    relative to `_catalog_root()` so dev and bundled installs both
    resolve correctly.

    For `clawrium/*` we additionally enforce the slug invariant
    `metadata.name == ref.name` (the source-dirname == registry slug
    rule from `.itx/364/02_PHASE0_FINDINGS.md` — required so that
    zeroclaw `remove` keys line up with the registry slug downstream).
    """
    schema = _load_schema(skill.ref.registry)
    _validate_against_schema(skill.metadata, schema, ref=skill.ref)

    if skill.ref.registry == "clawrium":
        if skill.metadata.get("name") != skill.ref.name:
            raise SchemaValidationError(
                f"Skill {skill.ref}: _meta.yaml `name` field "
                f"({skill.metadata.get('name')!r}) must equal directory "
                f"name ({skill.ref.name!r})."
            )


def check_agent_compatibility(skill: Skill, agent_type: str) -> None:
    """Raise ``IncompatibleSkillRegistry`` if ``skill`` cannot run on
    ``agent_type``.

    Compatibility rules (locked in `.itx/364/00_PLAN.md`):

    - ``clawrium/<name>``: read the ``compatibility`` map in `_meta.yaml`.
      Default-true if the key is missing (a normalized skill is meant to
      run anywhere); explicit ``false`` fails closed. Unknown agent
      types fail closed too — better a clear error than a "silently
      installed and never invoked" surprise.
    - ``<claw>/<name>`` (native): must match ``agent_type`` exactly.
      Cross-claw native installs are a hard error because the SKILL.md
      is already in a per-claw frontmatter shape.
    """
    if agent_type not in NATIVE_REGISTRIES:
        raise IncompatibleSkillRegistry(
            f"Unknown agent type {agent_type!r}. "
            f"Supported: {', '.join(sorted(NATIVE_REGISTRIES))}."
        )

    if skill.ref.registry == "clawrium":
        compat = skill.metadata.get("compatibility") or {}
        if not isinstance(compat, dict):
            raise IncompatibleSkillRegistry(
                f"Skill {skill.ref}: `compatibility` must be a mapping, "
                f"got {type(compat).__name__}."
            )
        if not compat.get(agent_type, False):
            raise IncompatibleSkillRegistry(
                f"Skill {skill.ref} is not compatible with agent type "
                f"{agent_type!r} (compatibility flag is "
                f"{compat.get(agent_type)!r})."
            )
        return

    # Native registry: registry name == required agent type.
    if skill.ref.registry != agent_type:
        raise IncompatibleSkillRegistry(
            f"Skill {skill.ref} is a {skill.ref.registry!r}-native skill "
            f"and cannot be installed on a {agent_type!r} agent. "
            f"Use the corresponding {agent_type}/* skill instead."
        )


def materialize_for_claw(skill: Skill, claw: str) -> tuple[dict[str, Any], str]:
    """Return the (frontmatter, body) pair that should be written on a
    ``claw``-type agent for ``skill``.

    For a ``<claw>/<name>`` skill the SKILL.md already carries the
    correct native frontmatter — return it verbatim.

    For a ``clawrium/<name>`` skill we synthesize a native frontmatter
    by taking the union of:

      1. ``name``, ``description``, ``version``, ``license``, ``author``,
         ``platforms``, ``prerequisites`` from `_meta.yaml`
         (only fields that are present);
      2. ``native.<claw>`` overrides verbatim — currently used by
         ``clawrium/tdd`` to inject ``metadata.hermes.tags``.

    The function never writes to disk; the caller is responsible for
    serializing the frontmatter (YAML) and staging the file.
    """
    if claw not in NATIVE_REGISTRIES:
        raise IncompatibleSkillRegistry(
            f"Unknown claw {claw!r}. Supported: {', '.join(sorted(NATIVE_REGISTRIES))}."
        )

    if skill.ref.registry != "clawrium":
        # Native skill: SKILL.md frontmatter is already correct.
        return dict(skill.skill_md_frontmatter), skill.body

    meta = skill.metadata
    frontmatter: dict[str, Any] = {}
    # Keys lifted into native frontmatter from the normalized shape.
    # Order is the canonical "name/description first" UX hermes/openclaw
    # rely on for `skills list` rendering.
    for key in (
        "name",
        "description",
        "version",
        "license",
        "author",
        "platforms",
        "prerequisites",
    ):
        if key in meta and meta[key] not in (None, "", [], {}):
            frontmatter[key] = meta[key]

    native = meta.get("native") or {}
    if isinstance(native, dict):
        claw_overrides = native.get(claw) or {}
        if isinstance(claw_overrides, dict):
            # Verbatim merge. The _meta.yaml schema is the gate that
            # decides which keys are allowed under native.<claw>; we
            # don't second-guess it here.
            for key, value in claw_overrides.items():
                frontmatter[key] = value

    return frontmatter, skill.body


def _split_frontmatter(text: str) -> tuple[str, dict[str, Any]]:
    """Split a SKILL.md into (body, frontmatter dict).

    Frontmatter is the conventional `---\\n…\\n---\\n` block at the top
    of the file. Missing frontmatter returns an empty dict and the
    original text as the body — `validate_skill` decides whether that's
    fatal for the registry in question.
    """
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
        raise SchemaValidationError(
            "SKILL.md frontmatter must be a YAML mapping."
        )
    return body, parsed


def _load_schema(registry: str) -> dict[str, Any]:
    """Load the JSON schema for `registry`. Cached via `lru_cache`-free
    module-level dict — schemas don't change at runtime."""
    cached = _SCHEMA_CACHE.get(registry)
    if cached is not None:
        return cached

    root = _catalog_root() / "_schema"
    if registry == "clawrium":
        schema_path = root / "clawrium.schema.json"
    else:
        schema_path = root / "native" / f"{registry}.schema.json"

    if not schema_path.is_file():
        raise SchemaValidationError(
            f"Schema file for registry {registry!r} not found at {schema_path}."
        )
    try:
        schema = json.loads(schema_path.read_text())
    except json.JSONDecodeError as error:
        raise SchemaValidationError(
            f"Schema {schema_path} is not valid JSON: {error}"
        ) from error
    _SCHEMA_CACHE[registry] = schema
    return schema


_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _validate_against_schema(
    data: dict[str, Any], schema: dict[str, Any], ref: SkillRef
) -> None:
    """Run jsonschema validation, translating errors into `SchemaValidationError`.

    Lazy-imports `jsonschema` so this module imports cleanly even in
    environments where the dep hasn't been installed yet (e.g. tooling
    that imports our types but never calls the validator).
    """
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise SchemaValidationError(
            "jsonschema package is required for skill validation. "
            "Install it: `uv sync` (or `pip install jsonschema`)."
        ) from error

    validator = Draft202012Validator(schema)
    # Coerce path components to str before sorting — `absolute_path` may
    # contain a mix of dict keys (str) and array indices (int), and
    # `sorted()` raises TypeError on mixed-type comparisons. Stable
    # ordering is the only thing we need here, not lexical correctness.
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
        f"Skill {ref} failed {schema.get('title', 'schema')} validation:\n"
        + "\n".join(messages)
    )


__all__ = [
    "REGISTRIES",
    "NATIVE_REGISTRIES",
    "Skill",
    "SkillRef",
    "SkillError",
    "MissingRegistryPrefix",
    "InvalidSkillRef",
    "ExternalSourceBlocked",
    "SkillNotFound",
    "SchemaValidationError",
    "IncompatibleSkillRegistry",
    "parse_skill_ref",
    "list_skills",
    "load_skill",
    "validate_skill",
    "check_agent_compatibility",
    "materialize_for_claw",
]
