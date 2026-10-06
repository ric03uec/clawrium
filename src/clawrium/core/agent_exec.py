"""Dispatch native agent CLI commands to a remote host via Ansible.

`run_agent_exec(hostname, agent_name, claw_type, cmd_argv)` invokes the
per-type `exec.yaml` playbook against the host that owns the agent.
The playbook runs the agent's native CLI binary (path baked into the
playbook for each claw type), captures stdout/stderr/rc, and returns them
through a type-specific transport. Pi encrypts its complete result to an
ephemeral controller public key before it enters an Ansible event; legacy
agent types emit base64-tagged debug events. This module parses the
transport and returns `(stdout, stderr, rc)`.

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
import binascii
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

import ansible_runner

from clawrium.core import keys as core_keys
from clawrium.core.config import get_config_dir
from clawrium.core.names import RESERVED_UNIX_NAMES
from clawrium.core.playbook_resolver import normalize_os_family, resolve_agent_playbook

logger = logging.getLogger(__name__)

__all__ = ["AgentExecError", "SUPPORTED_CLAW_TYPES", "run_agent_exec"]

SUPPORTED_CLAW_TYPES: frozenset[str] = frozenset(
    {"claude", "ethos", "hermes", "openclaw", "pi", "zeroclaw"}
)

_REGISTRY_DIR = Path(__file__).parent.parent / "platform" / "registry"

# Cap on remote execution time. Picked to be long enough for slow agent
# subcommands (e.g. an openclaw config dump) but short enough that a
# hung remote can't pin the local CLI indefinitely.
_DEFAULT_TIMEOUT = 120
# Claude's per-OS playbooks enforce this same bound around the native process.
# Leave time for their final redacted result event to get back to ansible-runner.
_CLAUDE_RUNNER_GRACE_SECONDS = 30

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


def _effective_timeout(timeout: object) -> int:
    """Clamp every exec caller to the documented finite command window."""
    try:
        requested = int(timeout)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT
    if requested <= 0:
        return _DEFAULT_TIMEOUT
    return min(requested, _DEFAULT_TIMEOUT)


def _claude_secret_values(agent_name: str) -> tuple[str, ...]:
    """Return locally stored Claude secret values solely for output redaction.

    Native exec deliberately activates credentials only on the host.  This
    narrow, best-effort read is never sent remotely or logged; it prevents a
    misbehaving Claude subcommand from reflecting a selected API key or fields
    from its native OAuth document back to the operator's terminal.
    """
    try:
        from clawrium.core.claude_credentials import get_active_claude_credential

        _, credential = get_active_claude_credential(agent_name)
    except Exception:
        # Version and other unauthenticated commands remain useful before a
        # credential is configured, and failure to load a redaction value must
        # not change their native exit semantics.
        return ()

    values = {credential}
    try:
        document = json.loads(credential)
    except (TypeError, json.JSONDecodeError):
        document = None

    def collect(value: object, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, child_key)
        elif isinstance(value, list):
            for child_value in value:
                collect(child_value, key)
        elif isinstance(value, str) and key in {
            "accessToken",
            "refreshToken",
            "trustedDeviceToken",
        }:
            values.add(value)

    collect(document)
    # A three-character value is not a plausible Claude credential and would
    # over-redact ordinary version/help text. Valid API/OAuth values are much
    # longer; preserve output usability while still failing safe for secrets.
    return tuple(
        sorted((value for value in values if len(value) >= 4), key=len, reverse=True)
    )


def _redact_claude_command_output(
    stdout: str, stderr: str, agent_name: str
) -> tuple[str, str]:
    """Remove the selected Claude credential from returned native output."""
    for secret in _claude_secret_values(agent_name):
        stdout = stdout.replace(secret, "[REDACTED]")
        stderr = stderr.replace(secret, "[REDACTED]")
    return stdout, stderr


def _playbook_path(claw_type: str, os_family: str = "linux") -> Path:
    return resolve_agent_playbook(claw_type, "exec", os_family)


def _logs_dir() -> Path:
    d = get_config_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_artifacts(log_dir: Path) -> None:
    for filename in ("pi-exec-private.pem",):
        try:
            (log_dir / filename).unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Failed to remove ephemeral exec key %s: %s", filename, e)
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


def _create_pi_exec_keypair(log_dir: Path) -> tuple[Path, str]:
    """Create a one-run CMS recipient certificate and private key.

    The self-signed recipient certificate is safe to include in Ansible
    extravars. The private half stays mode 0600 in the runner workdir and is
    removed by ``_cleanup_artifacts`` on every exit path.
    """
    openssl = shutil.which("openssl")
    if not openssl:
        raise OSError("openssl is required for secure Pi exec transport")
    private_key = log_dir / "pi-exec-private.pem"
    certificate = log_dir / "pi-exec-recipient.pem"
    try:
        subprocess.run(
            [
                openssl,
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(private_key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        private_key.chmod(0o600)
        subprocess.run(
            [
                openssl,
                "req",
                "-new",
                "-x509",
                "-key",
                str(private_key),
                "-subj",
                "/CN=clawrium-pi-exec",
                "-days",
                "1",
                "-out",
                str(certificate),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return private_key, certificate.read_text(encoding="ascii")
    except (OSError, subprocess.CalledProcessError) as e:
        private_key.unlink(missing_ok=True)
        certificate.unlink(missing_ok=True)
        raise OSError("failed to initialize secure Pi exec transport") from e
    finally:
        certificate.unlink(missing_ok=True)


def _parse_pi_secure_result(result, private_key: Path) -> tuple[str, str, int | None]:
    """Decrypt Pi's opaque result event without writing native output to disk."""
    encrypted_result: str | None = None
    for event in result.events:
        if event.get("event") != "runner_on_ok":
            continue
        msg = event.get("event_data", {}).get("res", {}).get("msg")
        if isinstance(msg, str) and msg.startswith("PI_EXEC_RESULT="):
            encrypted_result = msg[len("PI_EXEC_RESULT=") :]
    if not encrypted_result:
        return "", "", None

    openssl = shutil.which("openssl")
    if not openssl:
        return "", "", None
    try:
        encrypted = base64.b64decode(encrypted_result, validate=True)
        decrypted = subprocess.run(
            [
                openssl,
                "cms",
                "-decrypt",
                "-binary",
                "-inform",
                "DER",
                "-inkey",
                str(private_key),
            ],
            input=encrypted,
            capture_output=True,
            check=True,
        ).stdout
        payload = json.loads(decrypted.decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            raise ValueError("Pi exec result must be an object")
        stdout = payload.get("stdout", "")
        stderr = payload.get("stderr", "")
        rc = payload.get("rc")
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            raise ValueError("Pi exec result output must be text")
        if isinstance(rc, bool) or not isinstance(rc, int):
            raise ValueError("Pi exec result rc must be an integer")
        return stdout, stderr, rc
    except (
        ValueError,
        TypeError,
        binascii.Error,
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
    ):
        return "", "", None


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
        if msg.startswith("CLAUDE_EXEC_RESULT="):
            # Claude playbooks redact on the agent host before their only
            # result event is persisted. Its payload is a base64 JSON object,
            # distinct from the legacy three-event EXEC_* transport.
            try:
                payload = json.loads(
                    base64.b64decode(
                        msg[len("CLAUDE_EXEC_RESULT=") :], validate=True
                    ).decode("utf-8", errors="replace")
                )
                if not isinstance(payload, dict):
                    raise ValueError("Claude exec result must be an object")
                stdout_value = payload.get("stdout", "")
                stderr_value = payload.get("stderr", "")
                rc_value = payload.get("rc")
                if not isinstance(stdout_value, str) or not isinstance(
                    stderr_value, str
                ):
                    raise ValueError("Claude exec result output must be text")
                if isinstance(rc_value, bool) or not isinstance(rc_value, int):
                    raise ValueError("Claude exec result rc must be an integer")
                stdout = stdout_value
                stderr = stderr_value
                rc = rc_value
            except (
                ValueError,
                TypeError,
                binascii.Error,
                json.JSONDecodeError,
            ):
                stdout = ""
                stderr = ""
                rc = None
        elif msg.startswith("EXEC_STDOUT="):
            try:
                stdout = base64.b64decode(msg[len("EXEC_STDOUT=") :]).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, TypeError, binascii.Error):
                stdout = ""
        elif msg.startswith("EXEC_STDERR="):
            try:
                stderr = base64.b64decode(msg[len("EXEC_STDERR=") :]).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, TypeError, binascii.Error):
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
    if (
        not isinstance(cmd_argv, list)
        or not cmd_argv
        or any(
            not isinstance(item, str) or not item or "\x00" in item for item in cmd_argv
        )
    ):
        raise AgentExecError(
            "cmd_argv must be a non-empty list of non-empty strings without NUL bytes"
        )
    if not _AGENT_NAME_RE.fullmatch(agent_name):
        raise AgentExecError(f"invalid agent_name: {agent_name!r}")
    if agent_name in RESERVED_UNIX_NAMES:
        raise AgentExecError(
            f"refusing to run exec as reserved system user: {agent_name!r}"
        )

    effective_timeout = _effective_timeout(timeout)

    from clawrium.core.hosts import get_host

    host = get_host(hostname)
    if not host:
        return "", f"host '{hostname}' not found", 255

    os_family = normalize_os_family(host)
    try:
        playbook = _playbook_path(claw_type, os_family)
    except FileNotFoundError as e:
        return "", str(e), 255
    except ValueError as e:
        return "", f"os_family='{os_family}' is not supported by clawrium: {e}", 255

    key_id = host.get("key_id") or host["hostname"]
    ssh_key = core_keys.get_host_private_key(key_id)
    if not ssh_key:
        return (
            "",
            f"SSH key for host '{key_id}' not found. "
            f"Run 'clawctl host create {host['hostname']} --user xclm --alias <name>' "
            f"to register it (see docs/host-preparation.md for host setup).",
            255,
        )

    extra_vars = {"agent_name": agent_name, "cmd_argv": cmd_argv}
    if claw_type == "claude":
        # The remote wrapper owns the canonical kill path. Never pass
        # credential contents: OAuth is native file state and API-key mode is
        # sourced only from the private agent-home artifact on the host.
        extra_vars["claude_exec_timeout"] = effective_timeout

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
        log_dir = _logs_dir() / f"exec-{claw_type}-{host_display}-{timestamp}-{suffix}"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(log_dir, 0o700)
        except OSError:
            # Don't leave an orphaned dir on disk if chmod fails
            # (ATX iter-2 NW6).
            try:
                log_dir.rmdir()
            except OSError:
                pass
            raise
        pi_private_key: Path | None = None
        if claw_type == "pi":
            pi_private_key, extra_vars["pi_exec_recipient_certificate"] = (
                _create_pi_exec_keypair(log_dir)
            )
    except OSError as e:
        if "log_dir" in locals():
            _cleanup_artifacts(log_dir)
        return "", f"Failed to set up runner workdir: {e}", 255
    except BaseException:
        if "log_dir" in locals():
            _cleanup_artifacts(log_dir)
        raise

    try:
        result = ansible_runner.run(
            private_data_dir=str(log_dir),
            inventory=inventory,
            playbook=str(playbook),
            quiet=True,
            timeout=(
                effective_timeout + _CLAUDE_RUNNER_GRACE_SECONDS
                if claw_type == "claude"
                else effective_timeout
            ),
        )
    except Exception as e:
        _cleanup_artifacts(log_dir)
        stderr = f"ansible-runner error: {e}"
        if claw_type == "claude":
            _, stderr = _redact_claude_command_output("", stderr, agent_name)
        return "", stderr, 255
    except BaseException:
        # SIGINT/SystemExit can interrupt runner before the result-processing
        # finally below; never retain the ephemeral recipient key or artifacts.
        _cleanup_artifacts(log_dir)
        raise

    try:
        if result.status == "timeout":
            return "", f"remote command timed out after {effective_timeout}s", 255
        if result.status != "successful":
            err = _extract_failure_message(result, f"playbook {result.status}")
            if claw_type == "claude":
                _, err = _redact_claude_command_output("", err, agent_name)
            return "", err, 255

        if claw_type == "pi":
            # The private key exists only for this in-memory decrypt and is
            # wiped in the finally block below. Raw Pi output never reaches
            # Ansible's persistent event or artifact streams.
            assert pi_private_key is not None
            stdout, stderr, rc = _parse_pi_secure_result(result, pi_private_key)
        else:
            stdout, stderr, rc = _parse_events(result)
        if claw_type == "claude":
            stdout, stderr = _redact_claude_command_output(stdout, stderr, agent_name)
        if rc is None:
            return (
                stdout,
                stderr or "remote command did not report an exit code",
                255,
            )
        return stdout, stderr, rc
    finally:
        _cleanup_artifacts(log_dir)
