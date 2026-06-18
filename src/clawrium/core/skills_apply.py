"""Apply per-agent local skill desired-state onto a remote host.

`apply_state(agent_name)` is the single entry point both the CLI
(`clm agent skill install/remove`) and (eventually) the GUI call into. It
is intentionally a tight orchestrator:

  1. Resolve `agent_name` → (host record, agent_type) via `core.hosts`.
  2. Read the desired-state file via `core.skills_state.read_state`.
  3. For each bare local skill name, load the already-agent-native
     `SKILL.md` from the control plane and validate it against the
     resolved `agent_type`. Failure aborts before any remote I/O happens
     (no partial-apply states).
  4. Copy each local SKILL.md byte-for-byte into a process-owned staging
     directory inside the clawrium config tree.
  5. Dispatch to the per-claw `skills_apply.yaml` playbook with the
     staging dir + list of desired names as extravars. The playbook is
     responsible for atomic writes, pruning bounded to the
     clawrium-owned subtree on the host, and idempotency.
  6. Clean up the staging dir in a `finally` block.

All three native claw types are wired as of Phase 3 (#382). The
`_APPLY_PLAYBOOK_BY_CLAW` dispatch maps each `agent_type` to its
`skills_apply.yaml`; an `agent_type` outside `NATIVE_REGISTRIES` raises
`SkillApplyNotSupported` so the CLI surfaces a clear "unsupported claw
type" message rather than a missing-playbook traceback.
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

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_agent_by_name
from clawrium.core.keys import get_host_private_key
from clawrium.core.reset import _sanitize_for_path
from clawrium.core.skills import (
    NATIVE_REGISTRIES,
    Skill,
    SkillError,
    load_agent_skill,
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
    """Raised when the resolved agent type is outside the set of claws
    with a `skills_apply.yaml` playbook wired into the dispatch table.
    All three native claws (hermes/openclaw/zeroclaw) are wired as of
    Phase 3 (#382); this remains as a defensive guard for unknown
    agent types surfaced by future host records."""


class AgentNotFoundError(SkillError):
    """Raised when `agent_name` does not resolve to an installed agent."""


# Map of agent_type → per-claw skills_apply playbook name. All three
# native claws are wired as of Phase 3 (#382). Centralizing the dispatch
# table here avoids scattering claw-type literals through the CLI layer.
_APPLY_PLAYBOOK_BY_CLAW: dict[str, str] = {
    "hermes": "skills_apply.yaml",
    "openclaw": "skills_apply.yaml",
    "zeroclaw": "skills_apply.yaml",
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
        applied_skills: Sorted list of bare local skill names that now
            exist on the host (post-apply view).
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
            f"Invalid agent name {agent_name!r}. Must match ^[a-z][a-z0-9_-]{{0,31}}$."
        )

    try:
        resolved = get_agent_by_name(agent_name)
    except ValueError as error:
        # ambiguous name across hosts
        raise AgentNotFoundError(str(error)) from error
    if resolved is None:
        raise AgentNotFoundError(f"Agent {agent_name!r} not found. Run `clm agent ps`.")

    host, agent_type, _agent_record = resolved
    if agent_type not in NATIVE_REGISTRIES:
        raise SkillApplyNotSupported(
            f"Agent {agent_name!r} has unsupported claw type {agent_type!r}. "
            f"Supported: {', '.join(sorted(NATIVE_REGISTRIES))}."
        )
    playbook_name = _APPLY_PLAYBOOK_BY_CLAW.get(agent_type)
    if not playbook_name:
        # Operator-facing error text — no plan/phase jargon. Lists the
        # claw types that currently support skills so the user can
        # `clm agent ps | grep <supported>` for a target.
        supported = ", ".join(sorted(_APPLY_PLAYBOOK_BY_CLAW)) or "none"
        raise SkillApplyNotSupported(
            f"Skills install is not yet supported for {agent_type} agents. "
            f"Currently supported claw types: {supported}. "
            "Run `clm agent ps` to find a compatible agent."
        )

    # Validate everything in the desired state BEFORE touching the remote.
    # Desired state stores bare per-agent local skill names; the local
    # SKILL.md files are already materialized for this agent type.
    desired_names = read_state(agent_name)
    loaded: list[Skill] = []
    for name in desired_names:
        skill = load_agent_skill(agent_name, name, agent_type)
        loaded.append(skill)

    # Both staging and log-dir creation live inside the `try` so the
    # `finally` cleanup runs even when one of them raises mid-flight.
    # `_stage_skills` does `mkdtemp` then writes per-skill SKILL.md
    # files; `_make_log_dir` creates the log dir then does a
    # post-creation path-safety check that can raise. If either creator
    # raises after creating its dir, the only reference we have is the
    # return value — so we must capture it before any subsequent failure
    # point. Initialize to None so the `finally:` can None-guard cleanup.
    # (Original B-new1 hardening; consolidated with iter 3.)
    staging_dir: Path | None = None
    log_dir: Path | None = None
    try:
        staging_dir = _stage_skills(agent_name, agent_type, loaded)
        log_dir = _make_log_dir(agent_name, agent_type, host)
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
        # noise. May be None if `_stage_skills` raised before `mkdtemp`
        # returned. `_cleanup_runner_artifacts` is idempotent-safe so
        # we call it whenever `log_dir` was created.
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        if log_dir is not None:
            _cleanup_runner_artifacts(log_dir)

    # Both assignments inside the `try:` succeeded — we wouldn't reach
    # this line otherwise (an early raise would have propagated past
    # the `finally:` block). Asserting narrows `log_dir`'s type from
    # `Path | None` to `Path` for the ApplyResult construction below
    # AND documents the control-flow invariant for readers. (ATX
    # #382 iter 4 W-new9.)
    assert staging_dir is not None
    assert log_dir is not None
    return ApplyResult(
        agent_name=agent_name,
        agent_type=agent_type,
        hostname=host.get("hostname", "<unknown>"),
        applied_skills=[skill.ref.name for skill in loaded],
        # log_dir was assigned before _run_apply_playbook ran; on the
        # successful-return path it is always populated.
        log_dir=log_dir if log_dir is not None else Path(""),
    )


def _stage_skills(agent_name: str, agent_type: str, skills: list[Skill]) -> Path:
    """Copy every desired skill's local SKILL.md into a fresh staging dir.

    Layout::

        <staging>/<name>/SKILL.md   # for each skill (slug name)

    The staging dir lives under `${clawrium_config}/staging/skills/`
    with 0700 perms so other users on the control machine can't read
    staged frontmatter mid-apply. Each apply gets a unique sibling
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
    staging = Path(tempfile.mkdtemp(prefix=f"{agent_name}-{timestamp}-", dir=str(base)))

    # Wrap the per-skill write loop in try/except so a mid-loop failure
    # (disk full, permissions race) doesn't leak the partially-populated
    # tempdir into `${clawrium_config}/staging/skills/`. The caller's
    # `finally` cleanup uses the return value, so a raise-before-return
    # would otherwise leave the tempdir un-referenced and un-cleaned.
    # (ATX #382 iter 4 W-new6.)
    try:
        for skill in skills:
            skill_dir = staging / skill.ref.name
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_dir.chmod(0o700)
            skill_md_path = skill_dir / "SKILL.md"
            try:
                skill_md_path.write_bytes((skill.path / "SKILL.md").read_bytes())
            except OSError as error:
                raise SkillApplyError(
                    f"Failed to stage local skill {skill.ref.name!r}: {error}"
                ) from error
            os.chmod(skill_md_path, 0o600)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return staging


def _make_log_dir(agent_name: str, agent_type: str, host: dict) -> Path:
    """Create an ansible-runner private_data_dir for this apply run.

    Path components sourced from the host record are routed through
    `_sanitize_for_path` so a tampered hosts.json `alias` containing
    e.g. `../escape` cannot traverse outside the clawrium logs dir.
    The agent_name + agent_type fields are already regex-validated
    upstream, but we still sanitize for symmetry.

    Belt-and-suspenders: even after the allowlist sanitization, the
    resolved log_dir is asserted to stay inside logs_dir. Catches
    future regressions (e.g. if `_sanitize_for_path` is loosened)
    before they can reach `shutil.rmtree` in the cleanup step.
    """
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_host_display = host.get("alias") or host.get("hostname", "unknown")
    host_display = _sanitize_for_path(str(raw_host_display)) or "unknown"
    safe_agent_type = _sanitize_for_path(agent_type)
    log_dir = logs_dir / f"skills_apply-{safe_agent_type}-{host_display}-{timestamp}"
    # Belt-and-suspenders: even after the allowlist sanitization above,
    # assert the resolved log_dir stays inside logs_dir. Catches future
    # regressions (e.g. if `_sanitize_for_path` is loosened) before they
    # can reach shutil.rmtree. The user-facing error does NOT include
    # the computed path — leaking it would tell an attacker how their
    # traversal payload was reshaped (ATX #382 W2 / W13). Path lands at
    # DEBUG-level only.
    resolved = log_dir.resolve()
    if not str(resolved).startswith(str(logs_dir.resolve()) + os.sep):
        logger.debug(
            "Rejected log_dir outside logs root: computed=%s resolved=%s root=%s",
            log_dir,
            resolved,
            logs_dir.resolve(),
        )
        raise SkillApplyError(
            "Host alias or hostname contains unsafe characters that would "
            "escape the clawrium logs directory. Update the host alias: "
            "`clm host update <alias-or-address> --alias <safe-name>`, "
            "then retry."
        )
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
            f"Run `clawctl host create {hostname} --user xclm --alias <name>` "
            f"to register it (see docs/host-preparation.md for host setup)."
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
        raise SkillApplyError(f"ansible-runner failed to start: {error}") from error

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
    the absolute staging_dir path on this host); `env/` caches extravars.
    For `artifacts/` we preserve stdout/rc/status log files while removing
    the secret-bearing fact_cache/ subdirectory (same approach as
    lifecycle._cleanup_ansible_artifacts).
    """
    # Selectively clean artifacts — keep stdout/rc/status, remove fact_cache
    artifacts_dir = log_dir / "artifacts"
    if artifacts_dir.exists():
        for run_dir in artifacts_dir.iterdir():
            if not run_dir.is_dir():
                continue
            for sensitive_subdir in ("fact_cache",):
                target = run_dir / sensitive_subdir
                if target.exists():
                    try:
                        shutil.rmtree(target)
                    except OSError as error:
                        logger.debug("Could not clean %s: %s", target, error)

    for sub in ("env", "inventory"):
        target = log_dir / sub
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as error:
                logger.debug("Could not clean %s: %s", target, error)
