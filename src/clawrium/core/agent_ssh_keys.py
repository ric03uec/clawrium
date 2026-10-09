"""Shared system-level provisioning for per-agent SSH identities.

The controller owns key generation.  Ansible is the only remote-write path;
the playbook receives paths, never private-key bytes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import ansible_runner

from clawrium.core.keys import ensure_agent_keypair, get_agent_private_key
from clawrium.core.playbook_resolver import resolve_agent_ssh_keys_playbook

logger = logging.getLogger(__name__)


class AgentSSHIdentityError(RuntimeError):
    """A safe agent SSH identity cannot be reconciled automatically."""


def _inventory(host: dict) -> dict:
    """Build the management connection inventory used by the key playbook."""
    from clawrium.core.keys import get_host_private_key

    key_id = host.get("key_id") or host.get("hostname") or ""
    management_key = get_host_private_key(key_id)
    if management_key is None:
        raise AgentSSHIdentityError(
            "host management SSH key is missing; re-register the host before syncing"
        )
    hostname = host.get("hostname")
    if not hostname:
        raise AgentSSHIdentityError("host record has no hostname")
    return {
        "all": {
            "hosts": {
                hostname: {
                    "ansible_host": hostname,
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(management_key),
                    "ansible_pipelining": True,
                }
            }
        }
    }


def ensure_agent_ssh_identity(
    host: dict,
    agent_name: str,
    *,
    private_data_dir: Path | None = None,
    inventory: dict | None = None,
) -> tuple[Path, Path]:
    """Ensure one controller-owned keypair is safely installed remotely.

    A read-only preflight happens before first local generation.  Thus an
    orphaned remote key makes the operation fail closed rather than silently
    replacing an identity the control machine no longer owns.
    """
    key_id = host.get("key_id") or host.get("hostname") or ""
    os_family = host.get("os_family", "linux")
    existing = get_agent_private_key(key_id, agent_name)
    playbook = resolve_agent_ssh_keys_playbook(os_family)
    data_dir = private_data_dir or (Path.home() / ".cache" / "clawrium-agent-ssh")
    data_dir.mkdir(parents=True, exist_ok=True)
    inventory = inventory or _inventory(host)

    def run(
        phase: str,
        private: Path | None = None,
        public: Path | None = None,
        controller_exists: bool | None = None,
    ):
        result = ansible_runner.run(
            private_data_dir=str(data_dir / phase),
            inventory=inventory,
            playbook=str(playbook),
            quiet=True,
            extravars={
                "agent_name": agent_name,
                "controller_pair_exists": (
                    existing is not None if controller_exists is None else controller_exists
                ),
                "controller_private_key_path": str(private or ""),
                "controller_public_key_path": str(public or ""),
                "agent_ssh_key_phase": phase,
            },
        )
        if result.status != "successful":
            raise AgentSSHIdentityError(
                "agent SSH identity preflight/provision failed; inspect the "
                "agent user's ~/.ssh/id_ed25519 files and recover conflicting "
                "state manually before retrying"
            )

    # Preflight is intentionally always run: an existing controller pair must
    # also reject a conflicting or symlinked remote identity.
    run("preflight")
    private, public = ensure_agent_keypair(key_id, agent_name)
    if not (os.access(private, os.R_OK) and os.access(public, os.R_OK)):
        raise AgentSSHIdentityError("controller agent SSH identity is not readable")
    run("provision", private, public, controller_exists=True)
    logger.info("Ensured SSH identity for agent %s on %s", agent_name, key_id)
    return private, public
