"""Dependency detection for Clawrium."""

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass

__all__ = [
    "DependencyStatus",
    "check_python",
    "check_ansible",
    "check_ansible_runner",
    "check_all_dependencies",
]


@dataclass
class DependencyStatus:
    """Status of a dependency check.

    Attributes:
        name: Human-readable dependency name.
        found: Whether the dependency is available.
        version: Version string if found, None otherwise.
        path: Path to binary/module if found, None otherwise.
        install_hint: Instructions for installing if missing.
    """

    name: str
    found: bool
    version: str | None
    path: str | None
    install_hint: str


def check_python() -> DependencyStatus:
    """Check Python availability and version.

    Returns:
        DependencyStatus for Python (always found since we're running in it).
    """
    version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    return DependencyStatus(
        name="python",
        found=True,
        version=version,
        path=sys.executable,
        install_hint="",
    )


def check_ansible() -> DependencyStatus:
    """Check if Ansible is installed and get its version.

    Returns:
        DependencyStatus for Ansible.
    """
    path = shutil.which("ansible")
    if not path:
        return DependencyStatus(
            name="ansible",
            found=False,
            version=None,
            path=None,
            install_hint="Install via: pipx install ansible (recommended) or sudo apt install ansible",
        )

    # Get version
    try:
        result = subprocess.run(
            ["ansible", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # First line is like: "ansible [core 2.15.0]"
        version = result.stdout.split("\n")[0] if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        version = None

    return DependencyStatus(
        name="ansible",
        found=True,
        version=version,
        path=path,
        install_hint="",
    )


def check_ansible_runner() -> DependencyStatus:
    """Check if ansible-runner Python package is available.

    Returns:
        DependencyStatus for ansible-runner.
    """
    spec = importlib.util.find_spec("ansible_runner")
    if spec is None:
        return DependencyStatus(
            name="ansible-runner",
            found=False,
            version=None,
            path=None,
            install_hint="Install via: uv add ansible-runner (or pip install ansible-runner)",
        )

    # Get version if available
    try:
        import ansible_runner

        version = getattr(ansible_runner, "__version__", None)
        path = str(spec.origin) if spec.origin else None
    except ImportError:
        version = None
        path = None

    return DependencyStatus(
        name="ansible-runner",
        found=True,
        version=version,
        path=path,
        install_hint="",
    )


def check_all_dependencies() -> list[DependencyStatus]:
    """Check all required dependencies.

    Returns:
        List of DependencyStatus for python, ansible, and ansible-runner.
    """
    return [
        check_python(),
        check_ansible(),
        check_ansible_runner(),
    ]
