"""Hardware capability detection via ansible-runner.

This module provides functions to detect host hardware capabilities including
architecture, CPU, memory, disk, and GPU via Ansible fact gathering.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import NotRequired, TypedDict

import ansible_runner

logger = logging.getLogger(__name__)


class GpuInfo(TypedDict):
    """GPU detection result."""

    present: bool | None  # None means detection failed
    vendor: str | None
    error: str | None


class HardwareInfo(TypedDict):
    """Hardware capability information from remote host."""

    architecture: str
    processor_cores: int
    processor_count: int
    memtotal_mb: int
    mounts: list[dict]
    gpu: GpuInfo
    os: str  # lowercase distribution name (e.g., "ubuntu", "debian")
    os_version: str  # distribution version (e.g., "24.04", "12")
    # Optional and absent on older hosts.json records that pre-date these
    # fields; typed as NotRequired so reading legacy dicts still type-checks.
    product_name: NotRequired[str | None]  # ansible_product_name (e.g., "DGX Spark")
    system_vendor: NotRequired[str | None]  # ansible_system_vendor, lowercase


def extract_hardware_from_facts(facts: dict) -> dict:
    """Extract hardware capabilities from Ansible facts.

    Args:
        facts: Ansible fact dictionary from setup module

    Returns:
        Hardware dict with architecture, cores, memory, mounts, os, os_version
    """
    product_name_raw = facts.get("ansible_product_name")
    product_name = (
        product_name_raw.strip() if isinstance(product_name_raw, str) else None
    )
    if product_name == "":
        product_name = None

    system_vendor_raw = facts.get("ansible_system_vendor")
    if isinstance(system_vendor_raw, str):
        system_vendor: str | None = system_vendor_raw.strip().lower() or None
    else:
        system_vendor = None

    hardware = {
        "architecture": facts.get("ansible_architecture", "unknown"),
        "processor_cores": facts.get("ansible_processor_cores", 0),
        "processor_count": facts.get("ansible_processor_count", 0),
        "memtotal_mb": facts.get("ansible_memtotal_mb", 0),
        "mounts": [],
        "os": (facts.get("ansible_distribution") or "unknown").lower(),
        "os_version": str(facts.get("ansible_distribution_version", "unknown")),
        "product_name": product_name,
        "system_vendor": system_vendor,
    }

    # Extract mount information (only relevant fields)
    for mount in facts.get("ansible_mounts", []):
        hardware["mounts"].append(
            {
                "mount": mount.get("mount", ""),
                "size_total": mount.get("size_total", 0),
                "size_available": mount.get("size_available", 0),
            }
        )

    return hardware


def parse_gpu_output(lspci_output: str) -> GpuInfo:
    """Parse lspci output to detect GPU presence and vendor.

    Args:
        lspci_output: Output from 'lspci | grep -iE "vga|3d controller|display"' command

    Returns:
        GpuInfo dict with 'present' bool, 'vendor' string, and 'error' if any
    """
    if not lspci_output or not lspci_output.strip():
        return {"present": False, "vendor": None, "error": None}

    # Check for lspci not installed sentinel
    if "__NO_LSPCI__" in lspci_output:
        return {"present": None, "vendor": None, "error": "lspci not installed"}

    output_lower = lspci_output.lower()

    if "nvidia" in output_lower:
        return {"present": True, "vendor": "nvidia", "error": None}
    elif "amd" in output_lower or "[ati]" in output_lower or "ati " in output_lower:
        return {"present": True, "vendor": "amd", "error": None}
    elif "intel" in output_lower:
        return {"present": True, "vendor": "intel", "error": None}
    else:
        # GPU present but unknown vendor
        return {"present": True, "vendor": "unknown", "error": None}


def _validate_ssh_key(ssh_key: str) -> Path:
    """Validate SSH key path is safe and has correct permissions.

    Args:
        ssh_key: Path to SSH private key

    Returns:
        Resolved Path object

    Raises:
        ValueError: If path is outside allowed directory or has insecure permissions
    """
    key_path = Path(ssh_key).resolve()
    ssh_dir = Path.home() / ".ssh"
    config_dir = Path.home() / ".config" / "clawrium"

    # Allow keys in ~/.ssh or ~/.config/clawrium (use is_relative_to for path boundary safety)
    if not (key_path.is_relative_to(ssh_dir) or key_path.is_relative_to(config_dir)):
        raise ValueError(
            f"SSH key path {ssh_key} is outside allowed directories (~/.ssh or ~/.config/clawrium)"
        )

    if not key_path.exists():
        raise ValueError(f"SSH key {ssh_key} does not exist")

    # Check permissions (should be 0600 or 0400)
    key_stat = os.stat(key_path)
    if key_stat.st_mode & 0o077:
        raise ValueError(
            f"SSH key {ssh_key} has insecure permissions; expected 0600 or 0400"
        )

    return key_path


def gather_hardware(
    hostname: str, user: str = "xclm", port: int = 22, ssh_key: str | None = None
) -> HardwareInfo:
    """Gather hardware capabilities from remote host.

    Uses ansible-runner to:
    1. Run setup module for standard facts (CPU, memory, disk)
    2. Run lspci command for GPU detection

    Args:
        hostname: Remote host IP or hostname
        user: SSH username (default: xclm)
        port: SSH port (default: 22)
        ssh_key: Optional path to SSH private key

    Returns:
        HardwareInfo dict with architecture, cores, memory, mounts, gpu

    Raises:
        RuntimeError: If fact gathering fails
        ValueError: If ssh_key path is invalid or insecure
    """
    # Validate SSH key if provided
    validated_key: str | None = None
    if ssh_key:
        validated_key = str(_validate_ssh_key(ssh_key))

    with tempfile.TemporaryDirectory() as tmpdir:
        # Set secure permissions on temp directory
        os.chmod(tmpdir, 0o700)
        # Create inventory
        inventory = {
            "all": {
                "hosts": {
                    hostname: {
                        "ansible_user": user,
                        "ansible_port": port,
                    }
                }
            }
        }

        if validated_key:
            inventory["all"]["hosts"][hostname]["ansible_ssh_private_key_file"] = (
                validated_key
            )

        # Gather standard facts (30s timeout to prevent indefinite blocking)
        result = ansible_runner.run(
            private_data_dir=tmpdir,
            inventory=inventory,
            host_pattern=hostname,
            module="setup",
            quiet=True,
            timeout=30,
        )

        if result.status == "timeout":
            raise RuntimeError("Fact gathering timed out after 30 seconds")
        if result.status != "successful":
            raise RuntimeError(f"Fact gathering failed: {result.status}")

        # Extract facts from runner events (more reliable than get_fact_cache with in-memory inventory)
        facts = None
        for event in result.events:
            if event.get("event") == "runner_on_ok":
                res = event.get("event_data", {}).get("res", {})
                ansible_facts = res.get("ansible_facts")
                if ansible_facts:
                    facts = ansible_facts
                    break

        if not facts:
            raise RuntimeError("No facts returned from host")

        # Extract hardware from facts
        hardware = extract_hardware_from_facts(facts)

        # GPU detection via lspci (use shell module for pipe support)
        # Include "3d controller" for compute GPUs (A100, H100, etc.)
        # Distinguish between "lspci not installed" and "no GPU found"
        gpu_cmd = (
            "if command -v lspci >/dev/null 2>&1; then "
            'lspci | grep -iE "vga|3d controller|display" || true; '
            'else echo "__NO_LSPCI__"; fi'
        )
        gpu_result = ansible_runner.run(
            private_data_dir=tmpdir,
            inventory=inventory,
            host_pattern=hostname,
            module="shell",
            module_args=gpu_cmd,
            quiet=True,
            timeout=15,
        )

        # Parse GPU output from events
        gpu_output = ""
        if gpu_result.status == "successful":
            for event in gpu_result.events:
                if event.get("event") == "runner_on_ok":
                    gpu_output = (
                        event.get("event_data", {}).get("res", {}).get("stdout", "")
                    )
                    break
            hardware["gpu"] = parse_gpu_output(gpu_output)
        else:
            # GPU detection failed - log and encode in return value
            logger.warning("GPU detection failed: %s", gpu_result.status)
            hardware["gpu"] = {
                "present": None,
                "vendor": None,
                "error": f"GPU detection failed: {gpu_result.status}",
            }

        return hardware
