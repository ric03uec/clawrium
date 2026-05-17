"""Materialize a per-agent skill desired-state onto a remote host.

`apply_state(agent_name)` is the single entry point both the CLI
(`clm agent skill install/remove`) and (eventually) the GUI call into. It
is intentionally a tight orchestrator:

  1. Resolve `agent_name` → (host record, agent_type) via `core.hosts`.
  2. Read the desired-state file via `core.skills_state.read_state`.
  3. For each ref, load + validate the skill and check compatibility
     against the resolved `agent_type`. Failure aborts before any
     remote I/O happens (no partial-apply states).
  4. Materialize each skill's SKILL.md into a process-owned staging
     directory inside the clawrium config tree.
  5. Dispatch to the per-claw `skills_apply.yaml` playbook with the
     staging dir + list of desired names as extravars. The playbook is
     responsible for atomic writes, pruning bounded to the
     clawrium-owned subtree on the host, and idempotency.
  6. Clean up the staging dir in a `finally` block.

Phase 2 only wires up hermes. Other claw types raise
`SkillApplyNotSupported` — surfaced as a clear CLI message rather than a
traceback. Phases 3+ extend the dispatch table.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_agent_by_name
from clawrium.core.keys import get_host_private_key
from clawrium.core.skills import (
    NATIVE_REGISTRIES,
    Skill,
    SkillError,
    check_agent_compatibility,
    load_skill,
    materialize_for_claw,
    parse_skill_ref,
    validate_skill,
)
from clawrium.core.skills_state import read_state

logger = logging.getLogger(__name__)

__all__ = [
    "ApplyResult",
    "SkillApplyError",
    "SkillApplyNotSupported",
    "AgentNotFoundError",
    "apply_state",
]


class SkillApplyError(SkillError):
    """Raised when apply_state could not complete on the host.

    Covers ansible-runner failures, SSH errors, and playbook task
    failures. The error message is the user-facing summary; richer
    detail is in the per-run log directory under
    `${XDG_CONFIG_HOME}/clawrium/logs/`.
    """


class SkillApplyNotSupported(SkillError):
    """Raised when the resolved agent type has no skills_apply playbook
    wired yet. Phase 2 wires hermes only; openclaw + zeroclaw raise this
    so the CLI surfaces a clear "not yet supported" message instead of
    silently no-op'ing or breaking on a missing playbook path."""


class AgentNotFoundError(SkillError):
    """Raised when `agent_name` does not resolve to an installed agent."""


# Map of agent_type → per-claw skills_apply playbook name. Phase 2 only
# wires hermes; later phases add the other two entries. Centralizing the
# dispatch table here avoids scattering claw-type literals through the
# CLI layer.
_APPLY_PLAYBOOK_BY_CLAW: dict[str, str] = {
    "hermes": "skills_apply.yaml",
}

# Same agent_name pattern enforced by every playbook + lifecycle.
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of `apply_state` for one agent.

    Attributes:
        agent_name: The instance name that was applied to.
        agent_type: The resolved claw type.
        hostname: The host the playbook ran against.
        applied_skills: Sorted list of `<registry>/<name>` refs that
            now exist on the host (post-apply view).
        log_dir: ansible-runner work directory; kept for the user to
            inspect on failure or for the smoke-test transcript.
    """

    agent_name: str
    agent_type: str
    hostname: str
    applied_skills: list[str]
    log_dir: Path


def apply_state(agent_name: str, *, timeout: int = 60) -> ApplyResult:
    """Reconcile the host with `agent_name`'s desired-state file.

    Raises:
        AgentNotFoundError: agent name does not resolve.
        SkillApplyNotSupported: agent's claw type has no playbook yet.
        SkillError + subclasses: skill load/validate/compatibility
            failures, evaluated before any remote I/O.
        SkillApplyError: SSH / ansible-runner / playbook failures.
    """
    if not isinstance(agent_name, str) or not _AGENT_NAME_RE.match(agent_name):
        raise AgentNotFoundError(
            f"Invalid agent name {agent_name!r}. Must match "
            "^[a-z][a-z0-9_-]{0,31}$."
        )

    try:
        resolved = get_agent_by_name(agent_name)
    except ValueError as error:
        # ambiguous name across hosts
        raise AgentNotFoundError(str(error)) from error
    if resolved is None:
        raise AgentNotFoundError(
            f"Agent {agent_name!r} not found. Run `clm agent ps`."
        )

    host, agent_type, _agent_record = resolved
    if agent_type not in NATIVE_REGISTRIES:
        raise SkillApplyNotSupported(
            f"Agent {agent_name!r} has unsupported claw type {agent_type!r}."
        )
    playbook_name = _APPLY_PLAYBOOK_BY_CLAW.get(agent_type)
    if not playbook_name:
        raise SkillApplyNotSupported(
            f"Skills apply for {agent_type!r} is not implemented yet "
            "(Phase 2 wires hermes; Phase 3 adds openclaw/zeroclaw)."
        )

    # Validate everything in the desired state BEFORE touching the
    # remote. A bad ref in the file should not produce a half-applied
    # host (e.g. some skills installed, then a validation error
    # aborts the run mid-loop).
    desired_refs = read_state(agent_name)
    loaded: list[Skill] = []
    for raw_ref in desired_refs:
        ref = parse_skill_ref(raw_ref)
        skill = load_skill(ref)
        validate_skill(skill)
        check_agent_compatibility(skill, agent_type)
        loaded.append(skill)

    staging_dir = _stage_skills(agent_name, agent_type, loaded)
    log_dir = _make_log_dir(agent_name, agent_type, host)

    try:
        _run_apply_playbook(
            host=host,
            agent_name=agent_name,
            agent_type=agent_type,
            playbook_name=playbook_name,
            staging_dir=staging_dir,
            desired_skill_names=[skill.ref.name for skill in loaded],
            log_dir=log_dir,
            timeout=timeout,
        )
    finally:
        # Staging dir is always cleaned up — it contains rendered
        # frontmatter only (no secrets) but lingering temp dirs are
        # noise.
        shutil.rmtree(staging_dir, ignore_errors=True)
        _cleanup_runner_artifacts(log_dir)

    return ApplyResult(
        agent_name=agent_name,
        agent_type=agent_type,
        hostname=host.get("hostname", "<unknown>"),
        applied_skills=[str(skill.ref) for skill in loaded],
        log_dir=log_dir,
    )


def _stage_skills(agent_name: str, agent_type: str, skills: list[Skill]) -> Path:
    """Render every desired skill's SKILL.md into a fresh staging dir.

    Layout::

        <staging>/<name>/SKILL.md   # for each skill (slug name)

    The staging dir lives under `${clawrium_config}/staging/skills/`
    with 0700 perms so other users on the control machine can't read
    rendered frontmatter mid-apply. Each apply gets a unique sibling
    (timestamp + agent name) so concurrent applies don't overwrite each
    other.
    """
    base = get_config_dir() / "staging" / "skills"
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        # Best-effort; the per-run tempdir inside still gets 0700 from
        # tempfile.mkdtemp.
        pass

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    staging = Path(
        tempfile.mkdtemp(prefix=f"{agent_name}-{timestamp}-", dir=str(base))
    )

    for skill in skills:
        frontmatter, body = materialize_for_claw(skill, agent_type)
        skill_dir = staging / skill.ref.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_dir.chmod(0o700)
        skill_md_path = skill_dir / "SKILL.md"
        skill_md_path.write_text(_render_skill_md(frontmatter, body))
        os.chmod(skill_md_path, 0o600)

    return staging


def _render_skill_md(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize a (frontmatter, body) pair into SKILL.md form.

    Uses block-style YAML (`default_flow_style=False`) and preserves
    insertion order via `sort_keys=False` so the materialized frontmatter
    reads `name`/`description` first — matches every claw's `skills list`
    UX (which keys off frontmatter order for the description column).
    """
    yaml_block = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{yaml_block}\n---\n\n{body.lstrip()}"


def _make_log_dir(agent_name: str, agent_type: str, host: dict) -> Path:
    """Create an ansible-runner private_data_dir for this apply run."""
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = host.get("alias") or host.get("hostname", "unknown")
    log_dir = logs_dir / f"skills_apply-{agent_type}-{host_display}-{timestamp}"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(log_dir, 0o700)
    return log_dir


def _registry_playbook_dir(agent_type: str) -> Path:
    """Resolve the in-package playbook directory for ``agent_type``.

    Kept here rather than reusing memory's `_get_playbook_dir` so this
    module doesn't depend on `core.memory` (different concern). The
    layout is identical: `platform/registry/<claw>/playbooks/`.
    """
    return (
        Path(__file__).resolve().parent.parent
        / "platform"
        / "registry"
        / agent_type
        / "playbooks"
    )


def _run_apply_playbook(
    *,
    host: dict,
    agent_name: str,
    agent_type: str,
    playbook_name: str,
    staging_dir: Path,
    desired_skill_names: list[str],
    log_dir: Path,
    timeout: int,
) -> None:
    """Invoke ansible-runner with the skills_apply playbook.

    Lazy-imports `ansible_runner` so importing this module from CI/test
    contexts that mock the runner doesn't require ansible to be
    installed at import time.
    """
    playbook_path = _registry_playbook_dir(agent_type) / playbook_name
    if not playbook_path.is_file():
        raise SkillApplyError(f"Playbook not found: {playbook_path}")

    hostname = host.get("hostname")
    if not hostname:
        raise SkillApplyError("Host record is missing `hostname`.")

    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        raise SkillApplyError(
            f"SSH key for host {key_id!r} not found. "
            f"Run `clm host init {hostname}` to provision it."
        )

    inventory = {
        "all": {
            "hosts": {
                hostname: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": {
                "agent_name": agent_name,
                "agent_type": agent_type,
                "staging_dir": str(staging_dir),
                "desired_skill_names": list(desired_skill_names),
            },
        }
    }

    import ansible_runner

    try:
        result = ansible_runner.run(
            private_data_dir=str(log_dir),
            inventory=inventory,
            playbook=str(playbook_path),
            quiet=True,
            timeout=timeout,
        )
    except Exception as error:
        raise SkillApplyError(
            f"ansible-runner failed to start: {error}"
        ) from error

    if result.status == "timeout":
        raise SkillApplyError(
            f"Skills apply timed out after {timeout}s (log: {log_dir})."
        )

    if result.status != "successful":
        raise SkillApplyError(
            f"Skills apply failed (status={result.status}): "
            f"{_extract_failure_message(result)} (log: {log_dir})."
        )


def _extract_failure_message(result: Any) -> str:
    """Pull the most useful failure message out of an ansible-runner result.

    Prefers `runner_on_unreachable` over `runner_on_failed` so SSH /
    network failures present as "host unreachable" rather than a
    generic playbook status. Falls back to the status string if no
    event surfaces a message.
    """
    for event in getattr(result, "events", []) or []:
        if event.get("event") == "runner_on_unreachable":
            res = event.get("event_data", {}).get("res", {})
            msg = res.get("msg")
            return f"host unreachable: {msg}" if msg else "host unreachable"
    for event in getattr(result, "events", []) or []:
        if event.get("event") == "runner_on_failed":
            res = event.get("event_data", {}).get("res", {})
            if "msg" in res:
                return res["msg"]
            if "stderr" in res:
                return res["stderr"]
    return getattr(result, "status", "unknown")


def _cleanup_runner_artifacts(log_dir: Path) -> None:
    """Remove ansible-runner subdirectories that may cache inventory.

    `inventory/` includes the SSH key path and our extravars (including
    the absolute staging_dir path on this host); `env/` and `artifacts/`
    cache extravars + fact data. Same cleanup memory.py / lifecycle.py
    do — keep this module consistent so SSH key paths aren't left on
    disk after every apply.
    """
    for sub in ("artifacts", "env", "inventory"):
        target = log_dir / sub
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as error:
                logger.debug("Could not clean %s: %s", target, error)
