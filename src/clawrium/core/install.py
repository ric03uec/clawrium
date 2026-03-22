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
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

import ansible_runner

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

    # Step 1: Load manifest (validates claw exists)
    emit("validate", f"Checking {claw_name} manifest...")
    try:
        manifest = load_manifest(claw_name)
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

    # Step 4: Set installing status
    def set_installing(h: dict) -> dict:
        if "claws" not in h:
            h["claws"] = {}
        # Simple hostname extraction: use first part before first dot
        hostname_short = h["hostname"].split('.')[0]
        h["claws"][claw_name] = {
            "version": matched_version,
            "status": "installing",
            "installed_at": None,
            "error": None,
            "user": f"opc-{hostname_short}"
        }
        return h

    update_host(host["hostname"], set_installing)
    emit("validate", "Installation state tracked")

    # Step 5: Get SSH credentials
    key_id = host.get("key_id") or host["hostname"]
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        raise InstallationError(f"No SSH key found for host. Run 'clm host init {key_id}'.")

    # Step 6: Build inventory
    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            }
        }
    }

    try:
        # Step 7: Run base playbook
        base_playbook = _get_base_playbook_path()
        if not base_playbook.exists():
            raise InstallationError(f"Base playbook not found: {base_playbook}")

        emit("base", "Installing system dependencies...")
        playbooks_run = []

        with tempfile.TemporaryDirectory() as tmpdir:
            os.chmod(tmpdir, 0o700)

            result = ansible_runner.run(
                private_data_dir=tmpdir,
                inventory=inventory,
                playbook=str(base_playbook),
                quiet=True,
                timeout=300,  # 5 min timeout for base install
            )

            if result.status != "successful":
                raise InstallationError(
                    f"Base playbook failed: {result.status}. "
                    f"Check logs at {tmpdir}/artifacts/"
                )
            playbooks_run.append(str(base_playbook))
            emit("base", "System dependencies installed")

        # Step 8: Run claw playbook
        claw_playbook = _get_claw_playbook_path(claw_name)
        if not claw_playbook.exists():
            raise InstallationError(f"Claw playbook not found: {claw_playbook}")

        emit("claw", f"Installing {claw_name}...")

        with tempfile.TemporaryDirectory() as tmpdir:
            os.chmod(tmpdir, 0o700)

            result = ansible_runner.run(
                private_data_dir=tmpdir,
                inventory=inventory,
                playbook=str(claw_playbook),
                quiet=True,
                timeout=600,  # 10 min timeout for claw install
            )

            if result.status != "successful":
                raise InstallationError(
                    f"Claw playbook failed: {result.status}. "
                    f"Check logs at {tmpdir}/artifacts/"
                )
            playbooks_run.append(str(claw_playbook))
            emit("claw", f"{claw_name} installed successfully")

        # Step 9: Update host with success status
        def set_installed(h: dict) -> dict:
            if "claws" in h and claw_name in h["claws"]:
                h["claws"][claw_name]["status"] = "installed"
                h["claws"][claw_name]["installed_at"] = datetime.now(timezone.utc).isoformat()
            return h

        update_host(host["hostname"], set_installed)
        emit("complete", "Installation state updated")

        return {
            "success": True,
            "claw": claw_name,
            "version": matched_version,
            "host": host["hostname"],
            "playbooks_run": playbooks_run,
            "error": None,
        }

    except Exception as e:
        # Step 10: Update host with failure status
        def set_failed(h: dict) -> dict:
            if "claws" not in h:
                h["claws"] = {}
            if claw_name not in h["claws"]:
                hostname_short = h["hostname"].split('.')[0]
                h["claws"][claw_name] = {
                    "version": matched_version,
                    "user": f"opc-{hostname_short}"
                }
            h["claws"][claw_name]["status"] = "failed"
            h["claws"][claw_name]["error"] = str(e)
            h["claws"][claw_name]["installed_at"] = datetime.now(timezone.utc).isoformat()
            return h

        update_host(host["hostname"], set_failed)
        emit("error", f"Installation failed, state updated: {e}")

        # Re-raise the exception
        raise
