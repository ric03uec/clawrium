"""Dispatch native agent CLI commands to a remote host via Ansible.

`run_agent_exec(hostname, agent_name, claw_type, cmd_argv)` invokes the
per-type `exec.yaml` playbook against the host that owns the agent.
The playbook runs the agent's native CLI binary (path baked into the
playbook for each claw type), captures stdout/stderr/rc, and emits them
as three base64-tagged debug events (`EXEC_STDOUT=`, `EXEC_STDERR=`,
`EXEC_RC=`). This module parses those events and returns
`(stdout, stderr, rc)`.

Failure modes:
    - Unknown claw type → AgentExecError (caller turns into exit 2).
    - SSH/setup failure → ("", error_msg, 255).
    - Remote command nonzero rc → that rc is propagated.

There is no live streaming in v1: ansible's `command` module returns
output at task completion. The CLI layer writes the captured output
to the local terminal once the playbook finishes.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import ansible_runner

from clawrium.core import keys as core_keys
from clawrium.core.config import get_config_dir

logger = logging.getLogger(__name__)

__all__ = ["AgentExecError", "SUPPORTED_CLAW_TYPES", "run_agent_exec"]

SUPPORTED_CLAW_TYPES: frozenset[str] = frozenset({"hermes", "zeroclaw", "openclaw"})

_REGISTRY_DIR = Path(__file__).parent.parent / "platform" / "registry"

# Cap on remote execution time. Picked to be long enough for slow agent
# subcommands (e.g. an openclaw config dump) but short enough that a
# hung remote can't pin the local CLI indefinitely.
_DEFAULT_TIMEOUT = 120

# Same shape playbooks enforce server-side; the Python-side check is
# defense-in-depth so non-CLI callers (or a future playbook edit that
# drops the regex task) cannot smuggle an arbitrary string into Ansible
# extravars (ATX iter-1 W3).
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# `log_dir` directory-name component must contain only filename-safe
# characters. A tampered hosts.json alias of `../tmp/evil` would otherwise
# escape the logs root (ATX iter-1 W4).
_LOG_DIR_SAFE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class AgentExecError(Exception):
    """Raised for caller-recoverable errors before invoking ansible_runner."""


def _playbook_path(claw_type: str) -> Path:
    return _REGISTRY_DIR / claw_type / "playbooks" / "exec.yaml"


def _logs_dir() -> Path:
    d = get_config_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_artifacts(log_dir: Path) -> None:
    for sub in ("artifacts", "env", "inventory"):
        target = log_dir / sub
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as e:
                logger.warning("Failed to clean up %s: %s", target, e)
    # Drop the now-empty per-run directory (ATX iter-1 W8).
    try:
        log_dir.rmdir()
    except OSError:
        pass


def _build_inventory(host: dict, ssh_key: Path, extra_vars: dict) -> dict:
    return {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": extra_vars,
        }
    }


def _parse_events(result) -> tuple[str, str, int | None]:
    """Walk runner events and extract EXEC_STDOUT/EXEC_STDERR/EXEC_RC."""
    stdout = ""
    stderr = ""
    rc: int | None = None
    for event in result.events:
        if event.get("event") != "runner_on_ok":
            continue
        msg = event.get("event_data", {}).get("res", {}).get("msg")
        if not isinstance(msg, str):
            continue
        if msg.startswith("EXEC_STDOUT="):
            try:
                stdout = base64.b64decode(msg[len("EXEC_STDOUT=") :]).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, TypeError):
                stdout = ""
        elif msg.startswith("EXEC_STDERR="):
            try:
                stderr = base64.b64decode(msg[len("EXEC_STDERR=") :]).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, TypeError):
                stderr = ""
        elif msg.startswith("EXEC_RC="):
            try:
                rc = int(msg[len("EXEC_RC=") :])
            except ValueError:
                rc = None
    return stdout, stderr, rc


def _extract_failure_message(result, default: str) -> str:
    for event in result.events:
        if event.get("event") == "runner_on_unreachable":
            res = event.get("event_data", {}).get("res", {})
            msg = res.get("msg") or "host unreachable"
            return f"Host unreachable: {msg}"
    for event in result.events:
        if event.get("event") == "runner_on_failed":
            res = event.get("event_data", {}).get("res", {})
            if "msg" in res:
                return res["msg"]
            if "stderr" in res:
                return res["stderr"]
    return default


def run_agent_exec(
    hostname: str,
    agent_name: str,
    claw_type: str,
    cmd_argv: list[str],
    timeout: int = _DEFAULT_TIMEOUT,
) -> tuple[str, str, int]:
    """Run `cmd_argv` against the agent's native CLI on its host.

    Returns (stdout, stderr, rc). Setup failures return rc=255 with the
    error message on stderr.
    """
    if claw_type not in SUPPORTED_CLAW_TYPES:
        raise AgentExecError(
            f"agent type '{claw_type}' does not support exec "
            f"(supported: {', '.join(sorted(SUPPORTED_CLAW_TYPES))})"
        )
    if not isinstance(cmd_argv, list) or not cmd_argv:
        raise AgentExecError("cmd_argv must be a non-empty list")
    if not _AGENT_NAME_RE.match(agent_name):
        raise AgentExecError(f"invalid agent_name: {agent_name!r}")

    playbook = _playbook_path(claw_type)
    if not playbook.exists():
        return "", f"Playbook not found: {playbook}", 255

    from clawrium.core.hosts import get_host

    host = get_host(hostname)
    if not host:
        return "", f"host '{hostname}' not found", 255

    key_id = host.get("key_id") or host["hostname"]
    ssh_key = core_keys.get_host_private_key(key_id)
    if not ssh_key:
        return (
            "",
            f"SSH key for host '{key_id}' not found. "
            f"Run 'clawctl host init {host['hostname']}' to provision it.",
            255,
        )

    extra_vars = {"agent_name": agent_name, "cmd_argv": cmd_argv}

    try:
        inventory = _build_inventory(host, ssh_key, extra_vars)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        raw_display = host.get("alias") or host.get("key_id") or host["hostname"]
        # Defense-in-depth: drop anything that's not filename-safe before
        # interpolating into the directory name (ATX iter-1 W4).
        host_display = (
            raw_display if _LOG_DIR_SAFE_RE.match(raw_display or "") else "host"
        )
        # Collision suffix: timestamp resolution is 1s; two concurrent
        # calls would otherwise share private_data_dir and `rmtree`
        # nukes both (ATX iter-1 W1).
        suffix = uuid.uuid4().hex[:8]
        log_dir = (
            _logs_dir() / f"exec-{claw_type}-{host_display}-{timestamp}-{suffix}"
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(log_dir, 0o700)
    except OSError as e:
        return "", f"Failed to set up runner workdir: {e}", 255

    try:
        result = ansible_runner.run(
            private_data_dir=str(log_dir),
            inventory=inventory,
            playbook=str(playbook),
            quiet=True,
            timeout=timeout,
        )
    except Exception as e:
        _cleanup_artifacts(log_dir)
        return "", f"ansible-runner error: {e}", 255

    try:
        if result.status == "timeout":
            return "", f"remote command timed out after {timeout}s", 255
        if result.status != "successful":
            err = _extract_failure_message(result, f"playbook {result.status}")
            return "", err, 255

        stdout, stderr, rc = _parse_events(result)
        if rc is None:
            return (
                stdout,
                stderr or "remote command did not report an exit code",
                255,
            )
        return stdout, stderr, rc
    finally:
        _cleanup_artifacts(log_dir)
