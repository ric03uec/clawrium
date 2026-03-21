"""Hardware capability detection via ansible-runner.

This module provides functions to detect host hardware capabilities including
architecture, CPU, memory, disk, and GPU via Ansible fact gathering.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import TypedDict

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


def extract_hardware_from_facts(facts: dict) -> dict:
    """Extract hardware capabilities from Ansible facts.

    Args:
        facts: Ansible fact dictionary from setup module

    Returns:
        Hardware dict with architecture, cores, memory, mounts
    """
    hardware = {
        "architecture": facts.get("ansible_architecture", "unknown"),
        "processor_cores": facts.get("ansible_processor_cores", 0),
        "processor_count": facts.get("ansible_processor_count", 0),
        "memtotal_mb": facts.get("ansible_memtotal_mb", 0),
        "mounts": [],
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

    # Allow keys in ~/.ssh or ~/.config/clawrium
    if not (
        str(key_path).startswith(str(ssh_dir))
        or str(key_path).startswith(str(config_dir))
    ):
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

        facts = result.get_fact_cache(hostname)
        if not facts:
            raise RuntimeError("No facts returned from host")

        # Extract hardware from facts
        hardware = extract_hardware_from_facts(facts)

        # GPU detection via lspci (use shell module for pipe support)
        # Include "3d controller" for compute GPUs (A100, H100, etc.)
        gpu_result = ansible_runner.run(
            private_data_dir=tmpdir,
            inventory=inventory,
            host_pattern=hostname,
            module="shell",
            module_args='lspci | grep -iE "vga|3d controller|display" || true',
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
