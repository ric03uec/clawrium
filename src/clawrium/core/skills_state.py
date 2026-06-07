"""Desired-state store for per-agent local skills.

Local desired state is the source of truth for which skills are installed
on each agent. Stored at::

    ${XDG_CONFIG_HOME:-~/.config}/clawrium/agents/<agent>/skills.json

The file is a JSON object with shape::

    {"skills": ["tdd", "my-custom-skill"]}

Entries are bare per-agent local skill names. Registry refs such as
``clawrium/tdd`` are template sources only at add time and are invalid in
desired state; re-add the skill from template to create the local native
copy. The list is sorted and deduped on every write so the on-disk shape
is canonical regardless of write order.

This module never touches a remote host. ``core/skills_apply.py::apply_state``
reads here, stages the already-agent-native local files as-is, calls the
per-claw ``skills_apply.yaml`` playbook, and lets the playbook do the I/O.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from clawrium.core.config import get_config_dir
from clawrium.core.skills import InvalidSkillRef, _NAME_RE

logger = logging.getLogger(__name__)

__all__ = [
    "agent_skills_dir",
    "state_file_path",
    "read_state",
    "write_state",
    "add_skill",
    "remove_skill",
    "cleanup_agent_state",
]


# Matches the agent_name validation used in lifecycle.py / playbooks.
# Keeping the pattern colocated here (vs. importing) avoids a cycle with
# lifecycle, which already imports the skills modules indirectly via the
# CLI tree.
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _validate_agent_name(agent_name: str) -> None:
    """Reject agent names that would let a caller escape the per-agent
    state directory. Same pattern enforced by every playbook on the
    project."""
    if not isinstance(agent_name, str) or not _AGENT_NAME_RE.match(agent_name):
        raise InvalidSkillRef(
            f"Invalid agent name {agent_name!r}. Must match ^[a-z][a-z0-9_-]{{0,31}}$."
        )


def _validate_skill_name(name: str) -> str:
    """Validate and return a bare per-agent skill name."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        if isinstance(name, str) and "/" in name:
            raise InvalidSkillRef(
                f"Invalid skill name {name!r}. skills.json now stores bare per-agent "
                "skill names only. Registry refs are template sources; re-add with "
                "`clawctl agent skill add <agent> --from-template <registry>/<name>`."
            )
        raise InvalidSkillRef(
            f"Invalid skill name {name!r}. Names must match ^[a-z0-9][a-z0-9_-]*$."
        )
    return name


def state_file_path(agent_name: str) -> Path:
    """Return the on-disk path for ``agent_name``'s skills state file.

    Does not touch the filesystem; pure path arithmetic so callers can
    decide whether to read, write, or check existence.
    """
    _validate_agent_name(agent_name)
    return get_config_dir() / "agents" / agent_name / "skills.json"


def agent_skills_dir(agent_name: str) -> Path:
    """Return the local directory containing ``agent_name``'s skill files.

    Contains already-agent-native ``SKILL.md`` files. ``skills.json`` only
    stores the bare directory names under this path.
    """
    _validate_agent_name(agent_name)
    return get_config_dir() / "agents" / agent_name / "skills"


def read_state(agent_name: str) -> list[str]:
    """Return the sorted list of bare skill names in ``agent_name``'s state.

    Missing file → empty list (the "no skills installed" state). A
    malformed file raises ``InvalidSkillRef`` so callers don't silently
    overwrite user data.
    """
    path = state_file_path(agent_name)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise InvalidSkillRef(
            f"Skills state file {path} is not valid JSON: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise InvalidSkillRef(f"Skills state file {path} must be a JSON object.")
    skills = raw.get("skills", [])
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise InvalidSkillRef(
            f"Skills state file {path}: `skills` must be a list of strings."
        )
    validated: list[str] = []
    for entry in skills:
        validated.append(_validate_skill_name(entry))
    return sorted(set(validated))


def write_state(agent_name: str, refs: list[str]) -> list[str]:
    """Persist bare skill names as ``agent_name``'s desired state.

    Each entry is validated through ``_validate_skill_name`` (so registry
    refs, URLs, paths, uppercase names, spaces, and traversal forms raise
    a stable error class instead of corrupting the file) and the final
    list is sorted + deduped. Returns the canonicalized list that was
    written, so callers can compare against the prior state.

    Writes are atomic: content is staged to a sibling ``.tmp`` file and
    renamed into place so a concurrent reader (or a crash mid-write)
    never observes a half-written file.
    """
    canonical: set[str] = set()
    for entry in refs:
        canonical.add(_validate_skill_name(entry))
    sorted_refs = sorted(canonical)

    path = state_file_path(agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 0o700 on the per-agent directory: state may grow to include
    # provider-specific hints in later phases; lock the directory down
    # now rather than retrofit.
    try:
        path.parent.chmod(0o700)
    except OSError as error:
        # Non-fatal: chmod can fail on exotic filesystems (e.g. shared
        # volumes mounted no-perm). The atomic write below still runs.
        logger.debug("Could not chmod %s: %s", path.parent, error)

    payload = json.dumps({"skills": sorted_refs}, indent=2, sort_keys=True) + "\n"

    # tempfile.NamedTemporaryFile in the target directory gives us same-FS
    # rename semantics. delete=False is required so the file survives
    # close() for the os.replace().
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".skills.", suffix=".tmp", dir=path.parent
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup if the rename never happened.
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

    return sorted_refs


def add_skill(agent_name: str, name: str) -> tuple[list[str], bool]:
    """Add bare ``name`` to ``agent_name``'s state. Returns (new_state, added).

    ``added`` is True if the ref was not previously present; False on
    no-op. This lets callers report "already installed, applying anyway"
    accurately while still re-running the apply playbook (idempotency +
    drift recovery).
    """
    parsed = _validate_skill_name(name)
    current = read_state(agent_name)
    already_present = parsed in current
    if already_present:
        return current, False
    new_state = sorted({*current, parsed})
    return write_state(agent_name, new_state), True


def remove_skill(agent_name: str, name: str) -> tuple[list[str], bool]:
    """Remove bare ``name`` from ``agent_name``'s state.

    Returns (new_state, removed).

    ``removed`` is True if the ref was previously present; False on
    no-op. Callers should treat a no-op as user-visible but not an
    error — removing an absent skill is idempotent.
    """
    parsed = _validate_skill_name(name)
    current = read_state(agent_name)
    if parsed not in current:
        return current, False
    new_state = [s for s in current if s != parsed]
    return write_state(agent_name, new_state), True


def cleanup_agent_state(agent_name: str) -> bool:
    """Remove the entire state directory for ``agent_name``.

    Called during agent removal to ensure no orphan state survives.
    Returns True if the directory existed and was removed, False otherwise.

    Raises ``ValueError`` if the resolved path escapes the config directory
    (defense-in-depth against ``XDG_CONFIG_HOME`` manipulation).
    """
    _validate_agent_name(agent_name)
    path = state_file_path(agent_name).parent  # agents/<name>/

    # Confinement check: ensure the resolved path stays inside the config
    # directory. Every other file-destructive path in the codebase already
    # runs this guard (keys.py, reset.py, cli/agent.py).
    config_dir = get_config_dir()
    try:
        resolved_path = path.resolve()
        resolved_config = config_dir.resolve()
    except OSError as e:
        raise ValueError(f"Invalid agent state path for {agent_name!r}: {e}") from e

    if not resolved_path.is_relative_to(resolved_config):
        raise ValueError(
            f"Agent state path {path} escapes config directory {config_dir}"
        )

    # Check symlink BEFORE exists() — a broken symlink has exists() == False
    # but is_symlink() == True. If we check exists() first, we'd return False
    # and leave the broken symlink as orphan state (the exact bug #400 pattern).
    if path.is_symlink():
        # Defense-in-depth: refuse to follow symlinks with rmtree.
        raise ValueError(f"Agent state path {path} is a symlink, refusing to remove")

    if not path.exists():
        return False

    # Do NOT use ignore_errors=True — the lifecycle.py except block is
    # the soft-failure boundary; ignoring errors here would silently
    # leave orphan directories (the exact bug #400 was filed for) and
    # disable Python 3.8+'s built-in symlink guard.
    shutil.rmtree(path)
    return True
