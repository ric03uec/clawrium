"""Installation orchestration for claw deployment.

This module handles the end-to-end installation flow:
1. Validate claw exists in registry
2. Check host compatibility
3. Run base playbook (system dependencies)
4. Run claw-specific playbook

Host record schema (extended):
{
    "hostname": str,
    "claws": {
        "openclaw": {
            "version": "0.1.0",
            "status": "installed" | "failed" | "installing",
            "installed_at": "ISO timestamp",
            "error": str | None,
            "user": "opc-hostname"  # per D-07
        }
    },
    ...existing fields...
}
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

import ansible_runner

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host, update_host
from clawrium.core.keys import get_host_private_key
from clawrium.core.registry import (
    check_compatibility,
    load_manifest,
    ManifestNotFoundError,
)

logger = logging.getLogger(__name__)


class InstallationError(Exception):
    """Raised when installation fails."""
    pass


class InstallResult(TypedDict):
    """Result of installation operation."""
    success: bool
    claw: str
    version: str
    host: str
    playbooks_run: list[str]
    error: str | None


def _get_base_playbook_path() -> Path:
    """Get path to base system playbook."""
    # Base playbook is at project root/platform/playbooks/base.yaml
    # From src/clawrium/core/install.py: parent.parent.parent.parent gets to project root
    return Path(__file__).parent.parent.parent.parent / "platform" / "playbooks" / "base.yaml"


def _get_claw_playbook_path(claw_name: str) -> Path:
    """Get path to claw-specific install playbook."""
    return (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / claw_name
        / "playbooks"
        / "install.yaml"
    )


def _get_logs_dir() -> Path:
    """Get logs directory, creating if needed."""
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _get_claw_user(claw_name: str, host: dict) -> str:
    """Generate claw user name from host alias or key_id.

    Uses alias if available, otherwise key_id. Never uses IP address.
    Prefix depends on claw type (zc- for zeroclaw, opc- for openclaw, etc.)
    """
    # Claw prefixes
    prefixes = {
        "zeroclaw": "zc",
        "openclaw": "opc",
        "nemoclaw": "nc",
    }
    prefix = prefixes.get(claw_name, claw_name[:3])

    # Use alias first, then key_id (which should be set during host init)
    host_name = host.get("alias") or host.get("key_id") or host["hostname"]

    # Sanitize: only allow alphanumeric and hyphen, no dots
    sanitized = "".join(c if c.isalnum() or c == "-" else "-" for c in host_name)

    return f"{prefix}-{sanitized}"


def run_installation(
    claw_name: str,
    hostname: str,
    on_event: Callable[[str, str], None] | None = None,
) -> InstallResult:
    """Run full installation of a claw on a host.

    Args:
        claw_name: Name of claw to install (e.g., "openclaw")
        hostname: Hostname or alias of target host
        on_event: Optional callback for progress events (stage, message)

    Returns:
        InstallResult with success status and details

    Raises:
        InstallationError: If validation fails or playbook execution fails
    """
    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    # Step 1: Validate claw exists
    emit("validate", f"Checking {claw_name} manifest...")
    try:
        load_manifest(claw_name)  # Validates claw exists
    except ManifestNotFoundError as e:
        raise InstallationError(f"Claw '{claw_name}' not found in registry") from e

    # Step 2: Get host record
    emit("validate", f"Loading host {hostname}...")
    host = get_host(hostname)
    if not host:
        raise InstallationError(f"Host '{hostname}' not found. Run 'clm host add' first.")

    # Step 3: Check compatibility
    emit("validate", "Checking compatibility...")
    hardware = host.get("hardware", {})
    compat = check_compatibility(claw_name, hardware)

    if not compat["compatible"]:
        reasons = ", ".join(compat["reasons"])
        raise InstallationError(f"Host is incompatible: {reasons}")

    matched_version = compat["matched_entry"]["version"]
    emit("validate", f"Compatible with {claw_name} v{matched_version}")

    # Step 4: Generate claw user and set installing status
    claw_user = _get_claw_user(claw_name, host)

    def set_installing(h: dict) -> dict:
        if "claws" not in h:
            h["claws"] = {}
        h["claws"][claw_name] = {
            "version": matched_version,
            "status": "installing",
            "installed_at": None,
            "error": None,
            "user": claw_user
        }
        return h

    update_host(host["hostname"], set_installing)
    emit("validate", f"Installation state tracked (user: {claw_user})")

    # Step 5: Get SSH credentials
    key_id = host.get("key_id") or host["hostname"]
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        raise InstallationError(f"No SSH key found for host. Run 'clm host init {key_id}'.")

    # Step 6: Build inventory with extra vars for playbook
    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": {
                "claw_user": claw_user,
                "claw_version": f"v{matched_version}",
            }
        }
    }

    # Step 7: Setup persistent logs directory
    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = host.get("alias") or host.get("key_id") or host["hostname"]
    install_log_dir = logs_dir / f"install-{claw_name}-{host_display}-{timestamp}"
    install_log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(install_log_dir, 0o700)

    try:
        # Step 8: Run base playbook
        base_playbook = _get_base_playbook_path()
        if not base_playbook.exists():
            raise InstallationError(f"Base playbook not found: {base_playbook}")

        emit("base", "Installing system dependencies...")
        playbooks_run = []

        base_data_dir = install_log_dir / "base"
        base_data_dir.mkdir(exist_ok=True)

        result = ansible_runner.run(
            private_data_dir=str(base_data_dir),
            inventory=inventory,
            playbook=str(base_playbook),
            quiet=False,  # Show output
            timeout=300,  # 5 min timeout for base install
        )

        if result.status != "successful":
            raise InstallationError(
                f"Base playbook failed: {result.status}. "
                f"Check logs at {base_data_dir}/artifacts/"
            )
        playbooks_run.append(str(base_playbook))
        emit("base", "System dependencies installed")

        # Step 9: Run claw playbook
        claw_playbook = _get_claw_playbook_path(claw_name)
        if not claw_playbook.exists():
            raise InstallationError(f"Claw playbook not found: {claw_playbook}")

        emit("claw", f"Installing {claw_name}...")

        claw_data_dir = install_log_dir / "claw"
        claw_data_dir.mkdir(exist_ok=True)

        result = ansible_runner.run(
            private_data_dir=str(claw_data_dir),
            inventory=inventory,
            playbook=str(claw_playbook),
            quiet=False,  # Show output
            timeout=600,  # 10 min timeout for claw install
        )

        if result.status != "successful":
            raise InstallationError(
                f"Claw playbook failed: {result.status}. "
                f"Check logs at {claw_data_dir}/artifacts/"
            )
        playbooks_run.append(str(claw_playbook))
        emit("claw", f"{claw_name} installed successfully")

        # Step 10: Update host with success status
        def set_installed(h: dict) -> dict:
            if "claws" in h and claw_name in h["claws"]:
                h["claws"][claw_name]["status"] = "installed"
                h["claws"][claw_name]["installed_at"] = datetime.now(timezone.utc).isoformat()
            return h

        update_host(host["hostname"], set_installed)
        emit("complete", f"Installation complete. Logs at {install_log_dir}")

        return {
            "success": True,
            "claw": claw_name,
            "version": matched_version,
            "host": host["hostname"],
            "playbooks_run": playbooks_run,
            "error": None,
        }

    except Exception as e:
        # Step 11: Update host with failure status
        error_msg = str(e)

        def set_failed(h: dict) -> dict:
            if "claws" not in h:
                h["claws"] = {}
            if claw_name not in h["claws"]:
                h["claws"][claw_name] = {
                    "version": matched_version,
                    "user": claw_user
                }
            h["claws"][claw_name]["status"] = "failed"
            h["claws"][claw_name]["error"] = error_msg
            h["claws"][claw_name]["installed_at"] = datetime.now(timezone.utc).isoformat()
            return h

        update_host(host["hostname"], set_failed)
        emit("error", f"Installation failed. Logs at {install_log_dir}")

        # Re-raise the exception
        raise
