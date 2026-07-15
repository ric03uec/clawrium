"""Structured health diagnostics for deployed agents.

Runs five read-only checks in dependency order:

  SSH reachable → unit running → gateway reachable → token stored → onboarding complete

If a check fails, downstream checks that depend on it are skipped (marked
"skip") rather than reporting spurious failures.  This avoids the confusing
situation where a dead SSH connection produces three unrelated-looking errors.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Literal

from clawrium.core.keys import get_host_private_key
from clawrium.core.secrets import (
    InvalidInstanceKeyComponentError,
    SecretsFileCorruptedError,
    get_instance_key,
    get_instance_secrets,
)
from clawrium.core.ssh_connection import test_ssh_connection

logger = logging.getLogger(__name__)

__all__ = [
    "CheckResult",
    "run_doctor_checks",
]


@dataclass
class CheckResult:
    """Result of a single doctor health check."""

    name: str
    status: Literal["pass", "fail", "skip"]
    detail: str
    hint: str | None = None


def run_doctor_checks(
    agent_name: str,
    host_data: dict,
    agent_type: str,
    agent_record: dict,
) -> list[CheckResult]:
    """Run all doctor checks for an agent and return ordered results.

    Checks run in dependency order.  A failed check skips all checks that
    depend on it so operators see only the root cause rather than a cascade of
    consequent failures.

    Args:
        agent_name: Canonical agent instance name.
        host_data: Full host record from hosts.json.
        agent_type: Agent type string (e.g. "ethos", "hermes", "zeroclaw").
        agent_record: Per-agent record dict from host_data["agents"][agent_name].

    Returns:
        List of CheckResult in the order the checks ran.
    """
    results: list[CheckResult] = []

    hostname = host_data.get("hostname", "")
    port = host_data.get("port", 22)
    user = host_data.get("user", "xclm")
    key_id = host_data.get("key_id") or hostname

    # ── Check 1: SSH reachable ──────────────────────────────────────────────
    ssh_result = _check_ssh(hostname=hostname, port=port, user=user, key_id=key_id)
    results.append(ssh_result)
    if ssh_result.status != "pass":
        results += _skipped_checks(
            ["Unit running", "Gateway reachable", "Token stored", "Onboarding complete"]
        )
        return results

    # Resolve the SSH key path (confirmed present by check 1 succeeding).
    ssh_key = get_host_private_key(key_id)

    # ── Check 2: systemd unit running ──────────────────────────────────────
    unit_result = _check_unit(
        hostname=hostname,
        user=user,
        ssh_key=str(ssh_key),
        agent_type=agent_type,
        agent_name=agent_name,
    )
    results.append(unit_result)
    if unit_result.status != "pass":
        results += _skipped_checks(
            ["Gateway reachable", "Token stored", "Onboarding complete"]
        )
        return results

    # ── Check 3: Gateway port reachable ────────────────────────────────────
    config = agent_record.get("config", {})
    gateway_cfg = config.get("gateway", {})
    gateway_port = gateway_cfg.get("port") if isinstance(gateway_cfg, dict) else None

    gw_result = _check_gateway(
        hostname=hostname,
        user=user,
        ssh_key=str(ssh_key),
        gateway_port=gateway_port,
        agent_name=agent_name,
        agent_type=agent_type,
    )
    results.append(gw_result)
    if gw_result.status != "pass":
        results += _skipped_checks(["Token stored", "Onboarding complete"])
        return results

    # ── Check 4: Token stored in secrets ───────────────────────────────────
    token_result = _check_token(
        host_data=host_data,
        agent_type=agent_type,
        agent_name=agent_name,
    )
    results.append(token_result)

    # ── Check 5: Onboarding complete ───────────────────────────────────────
    onboard_result = _check_onboarding(agent_record=agent_record, agent_name=agent_name)
    results.append(onboard_result)

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Individual check implementations
# ──────────────────────────────────────────────────────────────────────────────


def _check_ssh(*, hostname: str, port: int, user: str, key_id: str) -> CheckResult:
    """Check 1: SSH connection reachable."""
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return CheckResult(
            name="SSH reachable",
            status="fail",
            detail=f"no SSH key found for host key_id={key_id!r}",
            hint="Run `clawctl host create` to re-register the host and generate keys.",
        )

    try:
        success, message = test_ssh_connection(
            hostname=hostname,
            port=port,
            user=user,
            key_filename=str(ssh_key),
        )
    except Exception as exc:  # pragma: no cover — unexpected transport errors
        return CheckResult(
            name="SSH reachable",
            status="fail",
            detail=f"unexpected error: {exc}",
            hint=f"Check network connectivity to {hostname}:{port}.",
        )

    if success:
        return CheckResult(
            name="SSH reachable",
            status="pass",
            detail=f"{hostname}:{port}, user={user}",
        )
    return CheckResult(
        name="SSH reachable",
        status="fail",
        detail=message,
        hint=(
            f"Verify that {hostname} is reachable on port {port} and "
            "that the host key has not changed."
        ),
    )


def _check_unit(
    *,
    hostname: str,
    user: str,
    ssh_key: str,
    agent_type: str,
    agent_name: str,
) -> CheckResult:
    """Check 2: systemd service unit is active."""
    unit_name = f"{agent_type}-{agent_name}.service"
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-i", ssh_key,
        f"{user}@{hostname}",
        f"systemctl is-active {unit_name}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        active_state = result.stdout.strip()
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="Unit running",
            status="fail",
            detail=f"{unit_name} — SSH command timed out",
            hint=f"Check `systemctl status {unit_name}` on {hostname}.",
        )
    except Exception as exc:
        return CheckResult(
            name="Unit running",
            status="fail",
            detail=f"{unit_name} — {exc}",
            hint=f"Check `systemctl status {unit_name}` on {hostname}.",
        )

    if active_state == "active":
        return CheckResult(
            name="Unit running",
            status="pass",
            detail=f"{unit_name} — active (running)",
        )
    return CheckResult(
        name="Unit running",
        status="fail",
        detail=f"{unit_name} — {active_state or 'inactive'}",
        hint=(
            f"Run `clawctl agent start {agent_name}` or check "
            f"`journalctl -u {unit_name}` on {hostname}."
        ),
    )


def _check_gateway(
    *,
    hostname: str,
    user: str,
    ssh_key: str,
    gateway_port: int | None,
    agent_name: str,
    agent_type: str,
) -> CheckResult:
    """Check 3: Gateway port is listening on the remote host."""
    if gateway_port is None:
        return CheckResult(
            name="Gateway reachable",
            status="fail",
            detail="gateway port not recorded in hosts.json",
            hint=f"Run `clawctl agent configure {agent_name}` to re-apply configuration.",
        )

    # Use `ss` to check if the port is bound; fall back to `netstat` if `ss` is absent.
    remote_cmd = (
        f"ss -tlnp 2>/dev/null | grep -q ':{gateway_port} ' "
        f"|| netstat -tlnp 2>/dev/null | grep -q ':{gateway_port} '"
        f"; [ $? -eq 0 ] && echo LISTENING || echo NOT_LISTENING"
    )
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-i", ssh_key,
        f"{user}@{hostname}",
        remote_cmd,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = result.stdout.strip()
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="Gateway reachable",
            status="fail",
            detail=f"port {gateway_port} — SSH command timed out",
            hint=f"Run `clawctl agent start {agent_name}` to restart the gateway.",
        )
    except Exception as exc:
        return CheckResult(
            name="Gateway reachable",
            status="fail",
            detail=f"port {gateway_port} — {exc}",
            hint=f"Run `clawctl agent start {agent_name}` to restart the gateway.",
        )

    unit_name = f"{agent_type}-{agent_name}.service"
    if output == "LISTENING":
        return CheckResult(
            name="Gateway reachable",
            status="pass",
            detail=f"port {gateway_port} is listening",
        )
    return CheckResult(
        name="Gateway reachable",
        status="fail",
        detail=f"connection refused on port {gateway_port}",
        hint=(
            f"Run `clawctl agent start {agent_name}` or check "
            f"`journalctl -u {unit_name}` on {hostname}."
        ),
    )


def _check_token(
    *,
    host_data: dict,
    agent_type: str,
    agent_name: str,
) -> CheckResult:
    """Check 4: API token present in local secrets store."""
    key_id = host_data.get("key_id") or host_data.get("hostname", "")

    try:
        instance_key = get_instance_key(key_id, agent_type, agent_name)
        secrets = get_instance_secrets(instance_key)
    except InvalidInstanceKeyComponentError as exc:
        return CheckResult(
            name="Token stored",
            status="fail",
            detail=f"invalid instance key: {exc}",
            hint=f"Run `clawctl agent configure {agent_name}` to reset credentials.",
        )
    except SecretsFileCorruptedError as exc:
        return CheckResult(
            name="Token stored",
            status="fail",
            detail=f"secrets store corrupted: {exc}",
            hint=(
                "Back up and remove ~/.config/clawrium/secrets.json, "
                "then re-run configure."
            ),
        )

    if not secrets:
        return CheckResult(
            name="Token stored",
            status="fail",
            detail="no secrets found for this agent",
            hint=(
                f"Run `clawctl agent configure {agent_name}` to supply "
                "provider credentials."
            ),
        )

    return CheckResult(
        name="Token stored",
        status="pass",
        detail=f"{len(secrets)} secret(s) stored",
    )


def _check_onboarding(*, agent_record: dict, agent_name: str) -> CheckResult:
    """Check 5: Onboarding is complete (state == 'ready')."""
    onboarding = agent_record.get("onboarding")
    if not isinstance(onboarding, dict):
        return CheckResult(
            name="Onboarding complete",
            status="fail",
            detail="state=pending (onboarding not started)",
            hint=f"Run `clawctl agent configure {agent_name}` to complete onboarding.",
        )

    state = onboarding.get("state") or "pending"
    if state == "ready":
        return CheckResult(
            name="Onboarding complete",
            status="pass",
            detail="state=ready",
        )
    return CheckResult(
        name="Onboarding complete",
        status="fail",
        detail=f"state={state}",
        hint=f"Run `clawctl agent configure {agent_name}` to complete onboarding.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _skipped_checks(names: list[str]) -> list[CheckResult]:
    """Return a list of skipped CheckResults for the given check names."""
    return [
        CheckResult(name=name, status="skip", detail="skipped (dependency failed)")
        for name in names
    ]
