"""Skills catalog API routes.

Read-only browse of the in-repo skills catalog, mirroring the Phase 1
CLI surface (``clawctl skill registry get`` / ``clawctl skill registry describe``). Backed by
``clawrium.core.skills``; this module never writes to disk and never
mutates agent state. Per-agent install/remove lives under
``/api/agents/{agent}/skills`` and is a later phase.

Status mapping for ``SkillError`` subclasses:

- ``MissingSourcePrefix``, ``ExternalSourceBlocked``, ``InvalidSkillRef``
  → 422 (request shape is malformed; the user can fix it by retyping)
- ``SkillNotFound`` → 404 (well-formed ref, no such skill in the catalog)
- ``SchemaValidationError`` → 422 (catalog file present but invalid; the
  detail string names the offending field so the catalog author can fix
  it; not surfaced as 500 because catalog files are user-authored)
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path as FastAPIPath

from clawrium.core.skills import (
    SOURCES,
    SUPPORTED_CLAWS_BY_DEFAULT,
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingSourcePrefix,
    ReadOnlySource,
    SchemaValidationError,
    SkillError,
    SkillNameConflict,
    SkillNameImmutable,
    SkillNotFound,
    SkillRef,
    list_skills,
    load_skill,
    parse_skill_ref,
    validate_skill,
)
from clawrium.core.skills_local import (
    create_local_skill,
    delete_local_skill,
    update_local_skill,
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
        "source": ref.source,
        "name": ref.name,
        "description": None,
        "version": None,
        "degraded": False,
    }
    try:
        skill = load_skill(ref)
    except (SkillError, OSError) as error:
        # `degraded=True` distinguishes a failed-to-load row from a
        # legitimately undescribed skill — the GUI renders a warning
        # icon on the card so operators can tell broken catalog
        # entries from new stubs.
        logger.warning("skipping summary for %s: %s", ref, error)
        summary["degraded"] = True
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
        body = body.encode("utf-8")[:_BODY_MAX_BYTES].decode("utf-8", errors="ignore")
        body += "\n\n... [truncated by GUI — fetch via `clawctl skill registry describe` for full]\n"

    return {
        "ref": str(skill.ref),
        "source": skill.ref.source,
        "name": skill.ref.name,
        "metadata": metadata,
        "body": body,
        "supported_on": dict(SUPPORTED_CLAWS_BY_DEFAULT),
    }


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
                "Run `clawctl skill registry get` to see available skills."
            ),
        )
    if isinstance(
        error,
        (
            MissingSourcePrefix,
            ExternalSourceBlocked,
            InvalidSkillRef,
            SkillNameImmutable,
        ),
    ):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, SkillNameConflict):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ReadOnlySource):
        return HTTPException(status_code=403, detail=str(error))
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
    """Unified catalog listing.

    Response shape::

        {
          "sources": ["vetted", "local"],
          "supported_on": {"hermes": true, "openclaw": false, "zeroclaw": false},
          "skills": [<summary>, ...],   # flat union, sorted by source then name
        }

    Each summary carries ``source`` and ``supported_on`` so the frontend
    can render a single flat list with per-card badges (no tabs).
    """

    def _build() -> dict[str, Any]:
        try:
            refs = list_skills()
        except (SkillError, OSError) as error:
            logger.warning("skills catalog unavailable: %s", error)
            return {
                "sources": list(SOURCES),
                "supported_on": dict(SUPPORTED_CLAWS_BY_DEFAULT),
                "skills": [],
                "error": "catalog unavailable",
            }
        summaries = [_summarize(ref) for ref in refs]
        # Inject the support table into every card so the frontend
        # doesn't need to make a separate request for it.
        for s in summaries:
            s["supported_on"] = dict(SUPPORTED_CLAWS_BY_DEFAULT)
        return {
            "sources": list(SOURCES),
            "supported_on": dict(SUPPORTED_CLAWS_BY_DEFAULT),
            "skills": summaries,
        }

    return await asyncio.to_thread(_build)


@router.get("/{source}/{name}")
async def get_skill_route(
    source: str = FastAPIPath(..., max_length=64),
    name: str = FastAPIPath(..., max_length=128),
) -> dict[str, Any]:
    """Detail view for a single ``<source>/<name>`` skill."""
    raw_ref = f"{source}/{name}"

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
            raise HTTPException(status_code=500, detail="Internal error.") from error

    # `HTTPException` propagates through FastAPI automatically; no wrap
    # needed. A bare `await` here keeps the call path clean and lets a
    # truly unhandled exception 500 visibly rather than silently swallow.
    return await asyncio.to_thread(_resolve)


# --- Local-source CRUD ---


def _coerce_frontmatter(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Pull (frontmatter, body) out of a JSON request body.

    Accepted shape::

        {
          "name": "...",
          "description": "...",
          "version": "...",          # optional
          "author": "...",           # optional
          "license": "...",          # optional
          "tags": [...],             # optional
          "platforms": [...],        # optional
          "body": "markdown body",   # optional
        }

    Unknown keys are ignored. Validation happens via schema after the
    file is staged on disk in ``skills_local``.
    """
    if not isinstance(payload, dict):
        raise SchemaValidationError("Request body must be a JSON object.")
    body = payload.get("body", "")
    if not isinstance(body, str):
        raise SchemaValidationError("`body` must be a string.")
    fm: dict[str, Any] = {}
    for key in (
        "name",
        "description",
        "version",
        "license",
        "author",
        "tags",
        "platforms",
        "prerequisites",
        "metadata",
    ):
        if key in payload and payload[key] is not None:
            fm[key] = payload[key]
    return fm, body


@router.post("", status_code=201)
async def create_skill_route(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create a new local-source skill."""

    def _resolve() -> dict[str, Any]:
        try:
            fm, body = _coerce_frontmatter(payload)
            name = fm.get("name")
            if not isinstance(name, str) or not name:
                raise SchemaValidationError("`name` is required.")
            ref = create_local_skill(name, fm, body)
            return _detail(ref)
        except SkillError as error:
            raise _map_error(error, f"local/{payload.get('name')!r}") from error

    return await asyncio.to_thread(_resolve)


@router.put("/local/{name}")
async def update_skill_route(
    name: str = FastAPIPath(..., max_length=128),
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Replace an existing local-source skill. ``name`` is immutable."""

    def _resolve() -> dict[str, Any]:
        try:
            fm, body = _coerce_frontmatter(payload)
            # If the caller sent `name`, it must match the URL slug.
            if "name" in fm and fm["name"] != name:
                raise SkillNameImmutable(
                    f"Cannot change skill name from {name!r} to {fm['name']!r}. "
                    "Names are immutable."
                )
            fm["name"] = name
            ref = update_local_skill(name, fm, body)
            return _detail(ref)
        except SkillError as error:
            raise _map_error(error, f"local/{name}") from error

    return await asyncio.to_thread(_resolve)


@router.put("/vetted/{name}")
async def update_vetted_skill_route(
    name: str = FastAPIPath(..., max_length=128),
) -> dict[str, Any]:
    """Reject updates to vetted/* — vetted is read-only."""
    raise HTTPException(
        status_code=403,
        detail=(
            f"Cannot edit `vetted/{name}`: vetted skills are read-only. "
            "Submit a PR to change them."
        ),
    )


@router.delete("/local/{name}", status_code=204)
async def delete_skill_route(
    name: str = FastAPIPath(..., max_length=128),
) -> None:
    """Delete a local-source skill."""

    def _resolve() -> None:
        try:
            delete_local_skill(name)
        except SkillError as error:
            raise _map_error(error, f"local/{name}") from error

    await asyncio.to_thread(_resolve)


@router.delete("/vetted/{name}", status_code=403)
async def delete_vetted_skill_route(
    name: str = FastAPIPath(..., max_length=128),
) -> None:
    """Reject deletes against vetted/* — vetted is read-only."""
    raise HTTPException(
        status_code=403,
        detail=(
            f"Cannot delete `vetted/{name}`: vetted skills are read-only."
        ),
    )
