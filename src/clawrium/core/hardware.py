"""Hardware capability detection via ansible-runner.

This module provides functions to detect host hardware capabilities including
architecture, CPU, memory, disk, and GPU via Ansible fact gathering.
"""

import ansible_runner
import tempfile
import json
from pathlib import Path


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


def parse_gpu_output(lspci_output: str) -> dict:
    """Parse lspci VGA output to detect GPU presence and vendor.

    Args:
        lspci_output: Output from 'lspci | grep -i vga' command

    Returns:
        Dict with 'present' bool and 'vendor' string or None
    """
    if not lspci_output or not lspci_output.strip():
        return {"present": False, "vendor": None}

    output_lower = lspci_output.lower()

    if "nvidia" in output_lower:
        return {"present": True, "vendor": "nvidia"}
    elif "amd" in output_lower or "[ati]" in output_lower or "ati " in output_lower:
        return {"present": True, "vendor": "amd"}
    elif "intel" in output_lower:
        return {"present": True, "vendor": "intel"}
    else:
        # GPU present but unknown vendor
        return {"present": True, "vendor": "unknown"}


def gather_hardware(
    hostname: str, user: str = "xclm", port: int = 22, ssh_key: str | None = None
) -> dict:
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
        Hardware dict with architecture, cores, memory, mounts, gpu

    Raises:
        RuntimeError: If fact gathering fails
    """
    with tempfile.TemporaryDirectory() as tmpdir:
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

        if ssh_key:
            inventory["all"]["hosts"][hostname]["ansible_ssh_private_key_file"] = (
                ssh_key
            )

        inv_path = Path(tmpdir) / "inventory"
        inv_path.mkdir()
        (inv_path / "hosts.json").write_text(json.dumps(inventory))

        # Gather standard facts (30s timeout to prevent indefinite blocking)
        result = ansible_runner.run(
            private_data_dir=tmpdir,
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
        gpu_result = ansible_runner.run(
            private_data_dir=tmpdir,
            host_pattern=hostname,
            module="shell",
            module_args="lspci | grep -i vga || true",
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

        return hardware
