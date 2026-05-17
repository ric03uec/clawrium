"""Skills catalog API routes.

Read-only browse of the in-repo skills catalog, mirroring the Phase 1
CLI surface (``clm skill list`` / ``clm skill show``). Backed by
``clawrium.core.skills``; this module never writes to disk and never
mutates agent state. Per-agent install/remove lives under
``/api/agents/{agent}/skills`` and is a later phase.

Status mapping for ``SkillError`` subclasses:

- ``MissingRegistryPrefix``, ``ExternalSourceBlocked``, ``InvalidSkillRef``
  → 422 (request shape is malformed; the user can fix it by retyping)
- ``SkillNotFound`` → 404 (well-formed ref, no such skill in the catalog)
- ``SchemaValidationError`` → 422 (catalog file present but invalid; the
  detail string names the offending field so the catalog author can fix
  it; not surfaced as 500 because catalog files are user-authored)
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Path as FastAPIPath

from clawrium.core.skills import (
    NATIVE_REGISTRIES,
    REGISTRIES,
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingRegistryPrefix,
    SchemaValidationError,
    SkillError,
    SkillNotFound,
    SkillRef,
    list_skills,
    load_skill,
    parse_skill_ref,
    validate_skill,
)

# Keys lifted from a skill's raw _meta.yaml (or native SKILL.md
# frontmatter) into the GUI detail response. Anything outside this set —
# `native.*` materialization blocks, `prerequisites.env`, future
# free-form fields — is deliberately dropped so the HTTP body never
# becomes a backdoor exfil path for catalog-author-supplied data.
_DETAIL_METADATA_KEYS: tuple[str, ...] = (
    "name",
    "description",
    "version",
    "license",
    "author",
    "platforms",
)

# Cap SKILL.md body bytes sent to the browser. The CLI renders the raw
# file; the GUI shows a preview. 64 KiB is ~30 pages of markdown — well
# past anything a TDD-style skill should ship — but bounded against a
# future skill that bundles a long appendix.
_BODY_MAX_BYTES = 64 * 1024

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _summarize(ref: SkillRef) -> dict[str, Any]:
    """Card-shape summary for the catalog list endpoint.

    Per-skill loader failures degrade to a row with ``description: None``
    rather than blowing up the whole list — same UX rule the CLI uses in
    ``cli/skill.py::_short_description``. A single bad ``_meta.yaml``
    should not blank the GUI catalog tab.

    Catches OSError (e.g. permission glitch on _meta.yaml) in addition
    to SkillError so a flaky filesystem entry can't crash the whole
    /api/skills response. The full error is surfaced at WARNING — DEBUG
    is too quiet to spot when the catalog tab silently shows missing
    descriptions.
    """
    summary: dict[str, Any] = {
        "ref": str(ref),
        "registry": ref.registry,
        "name": ref.name,
        "description": None,
        "version": None,
    }
    try:
        skill = load_skill(ref)
    except (SkillError, OSError) as error:
        logger.warning("skipping summary for %s: %s", ref, error)
        return summary

    description = skill.metadata.get("description")
    if isinstance(description, str) and description.strip():
        summary["description"] = " ".join(description.split())

    version = skill.metadata.get("version")
    if version is not None:
        summary["version"] = str(version)

    return summary


def _detail(skill_ref: SkillRef) -> dict[str, Any]:
    """Full skill payload for the detail endpoint.

    Exposes a filtered metadata view, the SKILL.md body, and a derived
    ``compatibility`` map so the frontend doesn't need to know whether
    the source registry was ``clawrium`` (compatibility lives in
    ``_meta.yaml``) or a native claw (compatibility is implicit: only the
    claw whose registry name matches the ref).

    Metadata is **whitelisted** to ``_DETAIL_METADATA_KEYS`` — raw
    ``native.*`` materialization blocks and any future free-form fields
    in ``_meta.yaml`` never reach the wire. The GUI only renders the
    whitelisted fields, so anything else is dead weight with a live
    leak surface.
    """
    skill = load_skill(skill_ref)
    # Validate so malformed catalog files surface as 422 (caller maps the
    # exception). Without this, a missing required field in _meta.yaml
    # would return a partial-looking 200 to the GUI.
    validate_skill(skill)

    metadata = {
        key: skill.metadata[key]
        for key in _DETAIL_METADATA_KEYS
        if key in skill.metadata and skill.metadata[key] not in (None, "", [], {})
    }
    body = skill.body
    if len(body.encode("utf-8")) > _BODY_MAX_BYTES:
        # Byte-bounded truncation. The marker line is plain text so a
        # naive consumer (e.g. curl piped to less) sees something
        # obvious instead of a silently shortened document.
        body = body.encode("utf-8")[:_BODY_MAX_BYTES].decode(
            "utf-8", errors="ignore"
        )
        body += "\n\n... [truncated by GUI — fetch via `clm skill show` for full]\n"

    compatibility = _compatibility_map(skill_ref, skill.metadata)
    return {
        "ref": str(skill.ref),
        "registry": skill.ref.registry,
        "name": skill.ref.name,
        "metadata": metadata,
        "body": body,
        "compatibility": compatibility,
    }


def _compatibility_map(ref: SkillRef, metadata: dict[str, Any]) -> dict[str, bool]:
    """Return a uniform ``{claw: bool}`` shape for the frontend.

    For ``clawrium/*`` we read the ``_meta.yaml.compatibility`` map and
    coerce missing/non-bool entries to ``False`` (same fail-closed rule
    as ``check_agent_compatibility``).

    For ``<claw>/*`` we synthesize ``{<claw>: True, <other>: False}`` so
    the GUI doesn't have to special-case native skills.

    Claw list comes from ``NATIVE_REGISTRIES`` so any future claw
    (e.g. ``nemoclaw``) added to ``core.skills`` automatically appears
    in the compatibility map. ``sorted()`` for stable JSON ordering.
    """
    claws = sorted(NATIVE_REGISTRIES)
    if ref.registry == "clawrium":
        raw = metadata.get("compatibility") or {}
        if not isinstance(raw, dict):
            raw = {}
        return {claw: bool(raw.get(claw, False)) for claw in claws}
    return {claw: (claw == ref.registry) for claw in claws}


def _map_error(error: SkillError, ref_str: str) -> HTTPException:
    """Translate a ``SkillError`` into an HTTP exception with stable codes.

    Bodies are split between **safe-to-echo** errors (user-supplied refs
    like a bad registry name) and **path-bearing** errors (catalog
    validation messages that include absolute filesystem paths). The
    latter are logged server-side at WARNING and replaced with a
    generic message — clients shouldn't have to know about disk
    layout to debug a malformed `_meta.yaml`.
    """
    if isinstance(error, SkillNotFound):
        # `core/skills.py` raises SkillNotFound with the absolute path
        # of the missing SKILL.md / _meta.yaml when a skill directory
        # exists but is incomplete. That's useful for the CLI (one
        # operator, one machine) and a leak for the GUI (the body is
        # served to anything on localhost). Keep the verbose message
        # in the server log; ship a path-free body to the wire.
        logger.warning("skill not found %s: %s", ref_str, error)
        return HTTPException(
            status_code=404,
            detail=(
                f"Skill {ref_str!r} not found in catalog. "
                "Run `clm skill list` to see available skills."
            ),
        )
    if isinstance(
        error,
        (MissingRegistryPrefix, ExternalSourceBlocked, InvalidSkillRef),
    ):
        # User-supplied ref strings only — no filesystem paths leak here.
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, SchemaValidationError):
        # `str(error)` includes absolute paths to the offending file and
        # the full jsonschema validation trace. Keep that in the server
        # log; ship a stable generic message to the wire.
        logger.warning("catalog schema validation failed for %s: %s", ref_str, error)
        return HTTPException(
            status_code=422,
            detail=f"Catalog metadata for {ref_str!r} failed validation.",
        )
    # Defensive: a future SkillError subclass should not become a 500
    # whose body echoes a path or stack-encoded internal detail.
    logger.exception("unhandled SkillError for %s: %s", ref_str, error)
    return HTTPException(status_code=500, detail="Internal error.")


@router.get("")
async def list_skills_route() -> dict[str, Any]:
    """Catalog listing, grouped by registry.

    Response shape:

    ```
    {
      "registries": ["clawrium", "openclaw", "hermes", "zeroclaw"],
      "skills": {
        "clawrium": [<summary>, ...],
        "openclaw": [<summary>, ...],
        ...
      }
    }
    ```

    Empty registries appear as empty lists, not omitted keys — the GUI
    renders a tab per registry regardless. The ``registries`` echo lets
    the frontend hold tab order without re-importing the constant.
    """

    def _build() -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {
            registry: [] for registry in REGISTRIES
        }
        try:
            refs = list_skills()
        except (SkillError, OSError) as error:
            # Catch both SkillError (no catalog dir) and OSError
            # (permission glitch on the catalog tree). Either way the
            # GUI should render an empty catalog with all four tabs
            # rather than a hard 500 — the user can still navigate
            # away to fix the underlying filesystem issue.
            logger.warning("skills catalog unavailable: %s", error)
            return {"registries": list(REGISTRIES), "skills": grouped}
        for ref in refs:
            grouped[ref.registry].append(_summarize(ref))
        return {"registries": list(REGISTRIES), "skills": grouped}

    return await asyncio.to_thread(_build)


@router.get("/{registry}/{name}")
async def get_skill_route(
    registry: str = FastAPIPath(..., max_length=64),
    name: str = FastAPIPath(..., max_length=128),
) -> dict[str, Any]:
    """Detail view for a single ``<registry>/<name>`` skill.

    Path-param length caps are a framework-layer guard against absurdly
    long inputs that would otherwise reach `parse_skill_ref` and bloat
    error messages. Real refs are way under these caps.
    """
    raw_ref = f"{registry}/{name}"

    def _resolve() -> dict[str, Any]:
        try:
            ref = parse_skill_ref(raw_ref)
            return _detail(ref)
        except SkillError as error:
            raise _map_error(error, raw_ref) from error
        except OSError as error:
            # A filesystem permission or I/O glitch shouldn't reveal
            # the path layout in the 500 body. Log full server-side.
            logger.exception("filesystem error loading %s: %s", raw_ref, error)
            raise HTTPException(
                status_code=500, detail="Internal error."
            ) from error

    try:
        return await asyncio.to_thread(_resolve)
    except HTTPException:
        raise
