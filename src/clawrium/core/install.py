"""Installation orchestration for agent deployment.

This module handles the end-to-end installation flow:
1. Validate agent exists in registry
2. Check host compatibility
3. Run base playbook (system dependencies)
4. Run agent-specific playbook

Host record schema (extended):
{
    "hostname": str,
    "agents": {
        "clever-einstein": {  # Agent NAME as key (allows multiple per type)
            "type": "openclaw",  # Agent type (zeroclaw, openclaw, etc.)
            "version": "0.1.0",
            "status": "installed" | "failed" | "installing",
            "installed_at": "ISO timestamp",
            "error": str | None,
        }
    },
    ...existing fields...
}
"""

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NotRequired, TypedDict

import ansible_runner

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host, update_host
from clawrium.core.keys import get_host_private_key
from clawrium.core.lifecycle import _cleanup_ansible_artifacts, _resolve_agent_type
from clawrium.core.names import (
    generate_random_name,
    is_name_available_on_host,
    validate_agent_name,
)
from clawrium.core.registry import (
    check_compatibility,
    load_manifest,
    ManifestNotFoundError,
)
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
    set_instance_secret,
)
from clawrium.core.onboarding import initialize_onboarding

logger = logging.getLogger(__name__)


def _is_valid_hermes_api_server_key(value: object) -> bool:
    """Return True if `value` is a well-formed 64-char lowercase hex string.

    Used by both install.py (existing-key reuse on idempotent install) and
    lifecycle.configure_agent() (hydration from secrets.json) so a corrupted
    secrets.json can't silently propagate a broken bearer token to Ansible.
    """
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(c in "0123456789abcdef" for c in value)


class InstallationError(Exception):
    """Raised when installation fails."""

    pass


def _pick_per_instance_port(
    host: dict,
    agent_name: str,
    base: int,
    span: int,
    port_field_path: tuple[str, ...],
    preserved_port: int | None = None,
) -> int:
    """Pick a unique listener port for `agent_name` in `[base, base+span)`.

    Issue #533: every per-agent listener (hermes dashboard, hermes api_server,
    openclaw/zeroclaw gateway) picks its port the same way — hash the agent
    name into the allocation window, walk +1 (wrapping) past collisions with
    other agents on the same host, and preserve the port across reinstalls
    via `preserved_port`.

    `port_field_path` is the nested-key path under `host["agents"][<name>]
    ["config"]` where each peer agent's port lives (e.g. `("gateway", "port")`
    or `("api_server", "port")`). The helper reads each peer's port from that
    path to build the collision set.
    """
    if (
        isinstance(preserved_port, int)
        and not isinstance(preserved_port, bool)
        and base <= preserved_port < base + span
    ):
        return preserved_port

    port_hash = int(hashlib.md5(agent_name.encode()).hexdigest(), 16)
    candidate = base + (port_hash % span)

    used_ports: set[int] = set()
    for other_key, other_agent in host.get("agents", {}).items():
        if other_key == agent_name or not isinstance(other_agent, dict):
            continue
        node: object = other_agent.get("config", {})
        for segment in port_field_path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(segment)
        if isinstance(node, int) and not isinstance(node, bool):
            used_ports.add(node)

    for _ in range(span):
        if candidate not in used_ports:
            return candidate
        candidate += 1
        if candidate >= base + span:
            candidate = base

    raise InstallationError(
        f"Port pool exhausted on {host['hostname']}: all {span} slots in "
        f"{base}-{base + span - 1} are occupied. "
        "Remove unused agents before installing another."
    )


class IncompleteInstallationError(InstallationError):
    """Raised when an incomplete installation already exists for an agent type."""

    def __init__(self, hostname: str, claw_name: str, details: dict):
        self.hostname = hostname
        self.claw_name = claw_name
        self.details = details
        status = details.get("status", "unknown")
        agent_name = details.get("agent_name") or claw_name
        super().__init__(
            "Incomplete installation detected for "
            f"'{agent_name}' on host '{hostname}' (status: {status})."
        )


class InstallResult(TypedDict):
    """Result of installation operation."""

    success: bool
    agent: str
    version: str
    host: str
    playbooks_run: list[str]
    error: str | None
    incomplete_installation: NotRequired[dict | None]
    skipped: NotRequired[bool]
    skip_reason: NotRequired[str | None]


def _get_incomplete_installation_details(host: dict, claw_name: str) -> list[dict]:
    """Return ALL incomplete installation details for an agent type.

    Returns a list of incomplete installations (may be empty).
    Each dict contains: status, installed_at, error, agent_name, version.
    """
    agents = host.get("agents", {})
    if not isinstance(agents, dict):
        return []

    incomplete: list[dict] = []
    for agent_key, existing in agents.items():
        if not isinstance(existing, dict):
            continue
        if existing.get("type") != claw_name:
            continue

        status = existing.get("status")
        installed_at = existing.get("installed_at")
        # Detect explicit incomplete states from prior attempts.
        # Also treat a status-bearing record with no installed_at timestamp as incomplete.
        if status in {"installing", "failed"} or (
            status is not None and installed_at is None
        ):
            incomplete.append(
                {
                    "status": status,
                    "installed_at": installed_at,
                    "error": existing.get("error"),
                    "agent_name": agent_key,
                    "version": existing.get("version"),
                }
            )

    return incomplete


def _get_base_playbook_path(os_family: str = "linux") -> Path:
    """Get path to base system playbook for the given OS family."""
    from clawrium.core.playbook_resolver import resolve_base_playbook

    return resolve_base_playbook(os_family)


def _get_agent_playbook_path(agent_type: str, os_family: str = "linux") -> Path:
    """Get path to agent-specific install playbook for the given OS family."""
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    return resolve_agent_playbook(agent_type, "install", os_family)


def _get_logs_dir() -> Path:
    """Get logs directory, creating if needed."""
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _install_was_skipped(playbook_result: object, agent_type: str) -> bool:
    """Detect whether the agent's install task was skipped by Ansible conditions.

    All agent install playbooks share the same skip-marker convention:
      * A task named "Mark install as skipped when already installed" emits a
        runner_on_ok event when the binary at the target version is present.
      * The "Set install skip condition" task sets a fact named
        `<agent_type>_already_installed` to True when the skip applies.

    Either signal is sufficient.
    """
    events = getattr(playbook_result, "events", None) or []
    skip_fact = f"{agent_type}_already_installed"

    for event in events:
        if event.get("event") != "runner_on_ok":
            continue

        event_data = event.get("event_data", {})
        task_name = event_data.get("task", "")
        result = event_data.get("res", {})

        if task_name == "Mark install as skipped when already installed":
            return True

        ansible_facts = result.get("ansible_facts", {})
        if ansible_facts.get(skip_fact) is True:
            return True

    return False


def _openclaw_install_was_skipped(playbook_result: object) -> bool:
    """Backward-compatible wrapper around `_install_was_skipped` for openclaw.

    Retained because existing tests import this symbol directly.
    """
    return _install_was_skipped(playbook_result, "openclaw")


def run_installation(
    claw_name: str,
    hostname: str,
    name: str | None = None,
    on_event: Callable[[str, str], None] | None = None,
    cleanup_failed: bool = False,
    resume: bool = False,
    force: bool = False,
) -> InstallResult:
    """Run full installation of an agent on a host.

    Args:
        claw_name: Name of agent to install (e.g., "openclaw")
        hostname: Hostname or alias of target host
        name: Optional friendly name for the agent instance. If not provided,
              a random Docker-style name will be generated (e.g., "clever-einstein")
        on_event: Optional callback for progress events (stage, message)
        cleanup_failed: Force cleanup of failed agent before installation
        resume: Resume existing installation using existing agent name
        force: Override the "already installed" skip and reinstall the binary
            even when the same version is present. Also re-runs the pairing
            block, rotating gateway token and device credentials.

    Returns:
        InstallResult with success status and details

    Raises:
        InstallationError: If validation fails or playbook execution fails
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    # Step 1: Validate agent exists
    emit("validate", f"Checking {claw_name} manifest...")
    try:
        load_manifest(claw_name)  # Validates agent exists
    except ManifestNotFoundError as e:
        raise InstallationError(f"Agent '{claw_name}' not found in registry") from e

    # Step 2: Get host record
    emit("validate", f"Loading host {hostname}...")
    host = get_host(hostname)
    if not host:
        raise InstallationError(
            f"Host '{hostname}' not found. Run 'clm host add' first."
        )

    # Step 3: Check compatibility
    emit("validate", "Checking compatibility...")
    hardware = host.get("hardware", {})
    compat = check_compatibility(claw_name, hardware)

    if not compat["compatible"]:
        reasons = ", ".join(compat["reasons"])
        raise InstallationError(f"Host is incompatible: {reasons}")

    matched_version = compat["matched_entry"]["version"]
    emit("validate", f"Compatible with {claw_name} v{matched_version}")

    # Step 4: Validate custom name if provided (format only, uniqueness checked in updater)
    if name is not None:
        valid, error_msg = validate_agent_name(name)
        if not valid:
            raise InstallationError(f"Invalid name: {error_msg}")
        emit("validate", f"Validated custom name: {name}")

    incomplete_list = _get_incomplete_installation_details(host, claw_name)
    # Track first incomplete for result reporting (or None if cleaned/empty)
    incomplete_details: dict | None = incomplete_list[0] if incomplete_list else None

    # Handle cleanup if requested - clean up ALL incomplete installations
    if cleanup_failed and incomplete_list:
        emit(
            "cleanup", f"Removing {len(incomplete_list)} incomplete installation(s)..."
        )

        # Collect all agent keys to remove
        agent_keys_to_remove = [
            item.get("agent_name") for item in incomplete_list if item.get("agent_name")
        ]

        def cleanup_agents(h: dict) -> dict:
            # Remove all incomplete agent entries
            if "agents" in h:
                for agent_key in agent_keys_to_remove:
                    if agent_key in h["agents"]:
                        del h["agents"][agent_key]
            return h

        update_host(host["hostname"], cleanup_agents)

        # Remove secrets for all incomplete instances
        from clawrium.core.secrets import load_secrets, save_secrets

        try:
            secrets = load_secrets()
            secrets_modified = False
            for item in incomplete_list:
                agent_name = item.get("agent_name")
                if agent_name:
                    instance_key = get_instance_key(
                        host["hostname"], claw_name, agent_name
                    )
                    if instance_key in secrets:
                        del secrets[instance_key]
                        secrets_modified = True
            if secrets_modified:
                save_secrets(secrets)
                emit("cleanup", "Removed secrets for incomplete installation(s)")
        except Exception as e:
            logger.warning("Failed to remove secrets: %s", e)
            emit(
                "warn",
                "Failed to remove some secrets. Manual cleanup may be required.",
            )

        emit("cleanup", "Cleanup complete. Starting fresh installation...")
        incomplete_list = []
        incomplete_details = None

    # Handle resume if requested
    if resume and incomplete_list:
        if len(incomplete_list) > 1:
            names = ", ".join(item.get("agent_name", "?") for item in incomplete_list)
            raise InstallationError(
                f"Multiple incomplete installations found: {names}. "
                "Use cleanup option first, then retry."
            )
        incomplete_details = incomplete_list[0]
        status = incomplete_details.get("status")

        # Validate state transition: only 'installing' state supports resume
        # Other states require different handling:
        # - 'failed': use cleanup option
        # - 'installed' with no installed_at: corrupt state, use cleanup
        # - None/unknown: invalid state, use cleanup
        if status == "failed":
            raise InstallationError(
                "Cannot resume from 'failed' state. "
                "Use cleanup option for failed installations."
            )
        if status != "installing":
            raise InstallationError(
                f"Cannot resume from '{status}' state. "
                "Only 'installing' state supports resume. Use cleanup option instead."
            )

        # Use existing agent name from incomplete installation
        name = incomplete_details.get("agent_name")
        if not name:
            raise InstallationError(
                "Cannot resume: agent_name missing from incomplete installation state. "
                "Use cleanup option instead."
            )
        emit("validate", f"Resuming installation with existing name: {name}")
    elif incomplete_list:
        emit(
            "validate",
            "Found previous incomplete installation state; proceeding with retry.",
        )

    # Step 5: Set installing state with uniqueness check under lock
    # Use lists to capture values from inside updater closures
    chosen_name = [None]
    preserved_onboarding = [
        None
    ]  # Capture onboarding to restore after ansible succeeds
    # #305: capture gateway config (auth token, device credentials, url, port)
    # before set_installing() wipes the agent record. On the skip path the
    # playbook intentionally does NOT re-emit these facts, so set_installed()
    # has nothing to write back — without this capture the credentials would
    # silently disappear on every clean re-install at the same version.
    preserved_gateway = [None]
    # Capture per-instance listener ports BEFORE set_installing() wipes the
    # agent record (issue #533). Re-install must not silently move a listener
    # to a new port — the systemd unit, any rendered config, and any open
    # tunnels were all wired to the original value.
    preserved_dashboard_port = [None]
    preserved_api_server_port = [None]
    preserved_gateway_port = [None]
    # Ports actually picked inside the set_installing lock (ATX iter-1 W2/W3).
    # Computing them inside the updater closure ensures concurrent installs on
    # the same host serialize through `_hosts_lock()` — without this, two
    # parallel `clm agent install` could read the same empty `used_ports` set
    # and both pick the same slot. The picks are also written onto the
    # in-progress agent record so a third install sees them.
    chosen_dashboard_port = [None]
    chosen_api_server_port = [None]
    chosen_gateway_port = [None]

    def set_installing(h: dict) -> dict:
        # Check for incomplete installation under lock (unless cleanup or resume)
        if not cleanup_failed and not resume:
            locked_incomplete_list = _get_incomplete_installation_details(h, claw_name)
            # Check if any incomplete installation is in 'installing' state
            for locked_item in locked_incomplete_list:
                if locked_item.get("status") == "installing":
                    raise IncompleteInstallationError(
                        h["hostname"], claw_name, locked_item
                    )

        if name is None:
            # Auto-generate name with retry loop for uniqueness
            max_attempts = 10
            for _ in range(max_attempts):
                candidate = generate_random_name()
                if is_name_available_on_host(candidate, h):
                    chosen_name[0] = candidate
                    break
            else:
                raise InstallationError(
                    f"Could not generate a unique name after {max_attempts} attempts. "
                    "Use --name to specify one."
                )
        else:
            # Use custom/resume name, check uniqueness under lock (unless resuming)
            if not resume and not is_name_available_on_host(name, h):
                # Allow reinstalling over "installed" or "failed" agents (preserves onboarding)
                # Block reinstalling over "installing" agents (use --resume or --cleanup-failed)
                existing_agent = h.get("agents", {}).get(name)
                if not existing_agent or existing_agent.get("status") not in [
                    "installed",
                    "failed",
                ]:
                    raise InstallationError(
                        f"Name '{name}' already in use on this host. "
                        "Names must be unique across all agents on a host."
                    )
            chosen_name[0] = name

        if "agents" not in h:
            h["agents"] = {}

        # Update status to installing (preserving existing data if resuming)
        if resume:
            if chosen_name[0] not in h["agents"]:
                raise InstallationError("Cannot resume: agent was removed")
            # Resume path does NOT wipe the record (only fields are reassigned),
            # but the skip-path warning still reads from `preserved_gateway`.
            # Capture here too so resume+skip+existing-creds doesn't falsely
            # warn "credentials missing" (Round 2 W1).
            #
            # Includes zeroclaw — pairing-bearer token lands in
            # `config.gateway.auth` during `clm agent configure` (issue #357).
            # Re-running install on a paired zeroclaw must not wipe the token,
            # so the restore path in set_installed() needs the snapshot.
            if claw_name in ("openclaw", "zeroclaw"):
                preserved_gateway[0] = (
                    h["agents"][chosen_name[0]].get("config", {}).get("gateway")
                )
                existing_gw_port = (
                    h["agents"][chosen_name[0]]
                    .get("config", {})
                    .get("gateway", {})
                    .get("port")
                )
                if (
                    isinstance(existing_gw_port, int)
                    and not isinstance(existing_gw_port, bool)
                    and 40000 <= existing_gw_port <= 41999
                ):
                    preserved_gateway_port[0] = existing_gw_port
            if claw_name == "hermes":
                existing_port = (
                    h["agents"][chosen_name[0]]
                    .get("config", {})
                    .get("dashboard", {})
                    .get("port")
                )
                # ATX W5: restrict to the documented allocation window so a
                # hand-edited hosts.json with `port: 80` cannot escape into
                # the systemd ExecStart.
                if (
                    isinstance(existing_port, int)
                    and not isinstance(existing_port, bool)
                    and 45000 <= existing_port <= 46999
                ):
                    preserved_dashboard_port[0] = existing_port
                existing_api_port = (
                    h["agents"][chosen_name[0]]
                    .get("config", {})
                    .get("api_server", {})
                    .get("port")
                )
                # Accept the new 8600..8699 window. Legacy installs persisted
                # port=8642 which is inside this window — they are grandfathered
                # automatically (ATX iter-1 S1: dropped the explicit `or
                # port == 8642` clause as it was already covered by the range).
                if (
                    isinstance(existing_api_port, int)
                    and not isinstance(existing_api_port, bool)
                    and 8600 <= existing_api_port <= 8699
                ):
                    preserved_api_server_port[0] = existing_api_port
            h["agents"][chosen_name[0]]["status"] = "installing"
            h["agents"][chosen_name[0]]["error"] = None
            h["agents"][chosen_name[0]]["version"] = matched_version  # Update version
            h["agents"][chosen_name[0]]["type"] = claw_name
        else:
            # Capture existing onboarding to restore AFTER ansible succeeds (not now)
            # This prevents corrupted state if installation fails
            # UNLESS cleanup_failed=True, then we force a fresh install
            if chosen_name[0] in h.get("agents", {}) and not cleanup_failed:
                preserved_onboarding[0] = h["agents"][chosen_name[0]].get("onboarding")
                # Round 2 W4: scope to claws that store credentials in
                # `config.gateway`. The restore branch in set_installed() is
                # the only consumer; other agent types may have unrelated
                # `config.gateway` shapes that should NOT be restored.
                #
                # Includes zeroclaw — pairing-bearer token lands in
                # `config.gateway.auth` during `clm agent configure`
                # (issue #357). Re-running install on a paired zeroclaw must
                # not wipe the token.
                if claw_name in ("openclaw", "zeroclaw"):
                    preserved_gateway[0] = (
                        h["agents"][chosen_name[0]].get("config", {}).get("gateway")
                    )
                    existing_gw_port = (
                        h["agents"][chosen_name[0]]
                        .get("config", {})
                        .get("gateway", {})
                        .get("port")
                    )
                    if (
                        isinstance(existing_gw_port, int)
                        and not isinstance(existing_gw_port, bool)
                        and 40000 <= existing_gw_port <= 41999
                    ):
                        preserved_gateway_port[0] = existing_gw_port
                if claw_name == "hermes":
                    existing_port = (
                        h["agents"][chosen_name[0]]
                        .get("config", {})
                        .get("dashboard", {})
                        .get("port")
                    )
                    # ATX W5: restrict to the documented allocation window.
                    if (
                        isinstance(existing_port, int)
                        and not isinstance(existing_port, bool)
                        and 45000 <= existing_port <= 46999
                    ):
                        preserved_dashboard_port[0] = existing_port
                    existing_api_port = (
                        h["agents"][chosen_name[0]]
                        .get("config", {})
                        .get("api_server", {})
                        .get("port")
                    )
                    # Accept new 8600..8699 window (legacy 8642 is inside it).
                    if (
                        isinstance(existing_api_port, int)
                        and not isinstance(existing_api_port, bool)
                        and 8600 <= existing_api_port <= 8699
                    ):
                        preserved_api_server_port[0] = existing_api_port

            h["agents"][chosen_name[0]] = {
                "type": claw_name,
                "version": matched_version,
                "status": "installing",
                "installed_at": None,
                "error": None,
                "agent_name": chosen_name[0],
            }
            # NOTE: Onboarding NOT restored here - will be restored in set_installed()
            # after ansible succeeds to prevent status='failed' + onboarding='ready'
            # cleanup_failed=True ensures preserved_onboarding[0] is None (fresh install)

        # ATX iter-1 W2/W3: pick per-instance listener ports inside the lock
        # so concurrent installs on the same host serialize through their
        # collision-walk. Persist the picks onto the in-progress agent record
        # so a third install (which would call set_installing again) sees them.
        # NOTE: concurrent installs on the same host could still collide on
        # the in-flight ansible run if a third installer slips between two
        # set_installing calls without either landing set_installed; the
        # collision detection here is single-writer optimistic.
        record = h["agents"][chosen_name[0]]
        record.setdefault("config", {})
        if claw_name in ("openclaw", "zeroclaw"):
            chosen_gateway_port[0] = _pick_per_instance_port(
                h,
                chosen_name[0],
                base=40000,
                span=2000,
                port_field_path=("gateway", "port"),
                preserved_port=preserved_gateway_port[0],
            )
            record["config"].setdefault("gateway", {})["port"] = (
                chosen_gateway_port[0]
            )
        if claw_name == "hermes":
            chosen_dashboard_port[0] = _pick_per_instance_port(
                h,
                chosen_name[0],
                base=45000,
                span=2000,
                port_field_path=("dashboard", "port"),
                preserved_port=preserved_dashboard_port[0],
            )
            chosen_api_server_port[0] = _pick_per_instance_port(
                h,
                chosen_name[0],
                base=8600,
                span=100,
                port_field_path=("api_server", "port"),
                preserved_port=preserved_api_server_port[0],
            )
            record["config"]["dashboard"] = {
                "enabled": True,
                "host": "127.0.0.1",
                "port": chosen_dashboard_port[0],
            }
            record["config"]["api_server"] = {
                "enabled": True,
                "host": "0.0.0.0",
                "port": chosen_api_server_port[0],
            }
        return h

    update_host(host["hostname"], set_installing)

    # Extract the chosen name
    agent_name = chosen_name[0]

    # Emit message after lock is released and agent_name is set
    if resume:
        emit("validate", f"Resuming with existing name: {agent_name}")
    elif name is None:
        emit("validate", f"Generated unique name: {agent_name}")
    else:
        emit("validate", f"Using provided name: {agent_name}")
    emit("validate", f"Installation state tracked (user: {agent_name})")

    # Step 5: Get SSH credentials
    key_id = host.get("key_id") or host["hostname"]
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        raise InstallationError(
            f"No SSH key found for host. Run 'clm host init {key_id}'."
        )

    # Step 6: Build inventory with extra vars for playbook
    matched_entry = compat["matched_entry"]
    claw_sha256 = matched_entry.get("sha256", "")

    # Load secrets for this agent instance
    instance_key = get_instance_key(host["hostname"], claw_name, agent_name)
    instance_secrets = get_instance_secrets(instance_key)

    # Map secret keys to ansible vars (uppercase SECRET_KEY -> lowercase secret_key)
    secret_vars = {}
    for key, entry in instance_secrets.items():
        ansible_var_name = key.lower()
        secret_vars[ansible_var_name] = entry.get("value", "")

    # Get template path for agent type
    canonical_name = _resolve_agent_type(claw_name)
    template_path = (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / canonical_name
        / "templates"
    )

    # Per-instance listener ports (issue #533). Picked inside set_installing()
    # under `_hosts_lock()` to avoid concurrent-install races (ATX iter-1 W2).
    # `openclaw_port` is None for hermes (ATX iter-1 W3) so the 40000..41999
    # pool isn't silently consumed by agents that never use it.
    openclaw_port = chosen_gateway_port[0]
    dashboard_port = chosen_dashboard_port[0]
    api_server_port = chosen_api_server_port[0]

    # Generate auth token for gateway access
    import secrets

    gateway_auth_token = secrets.token_hex(24)  # 48-character hex token

    # Build minimal config for templates.
    # gateway.auth.mode must be explicitly "token" for full operator scopes
    # See: https://docs.openclaw.ai/gateway/security
    # ATX iter-1 W3: only openclaw/zeroclaw consume `config.gateway`; building
    # it unconditionally (and reserving an openclaw_port slot for hermes)
    # silently consumed the 40000..41999 pool with ghost allocations.
    config: dict = {}
    if claw_name in ("openclaw", "zeroclaw"):
        config["gateway"] = {
            "mode": "local",
            "port": openclaw_port,
            "bind": "lan",
            "auth": {
                "mode": "token",
                "token": gateway_auth_token,
            },
        }

    # Hermes: generate (or reuse) the API_SERVER_KEY that gates the local
    # OpenAI-compatible gateway on 127.0.0.1:8642. Generated once on first
    # install so reconfigure flows can rely on the same token across runs.
    # Persisted in secrets.json under the canonical instance key so
    # remove_instance_secrets() cleans it up alongside provider keys when the
    # agent is removed; hosts.json only carries the non-sensitive shape
    # (enabled / host / port).
    hermes_api_server_key = None
    if claw_name == "hermes":
        # Use canonical hostname (not the alias passed by the CLI) so the
        # instance_key matches what lifecycle.configure_agent() will look up.
        canonical_hostname = host["hostname"]
        instance_key = get_instance_key(canonical_hostname, claw_name, agent_name)
        existing_entry = get_instance_secrets(instance_key).get("HERMES_API_SERVER_KEY")
        # `.get("value")` not `["value"]`: a truthy-but-malformed entry (no
        # "value" field, e.g. hand-edited secrets.json) would otherwise raise
        # KeyError straight out of the install flow.
        existing_key = existing_entry.get("value") if existing_entry else None
        if _is_valid_hermes_api_server_key(existing_key):
            hermes_api_server_key = existing_key
        else:
            if existing_key is not None:
                logger.warning(
                    "Existing HERMES_API_SERVER_KEY for %s is corrupted "
                    "(not 64-char lowercase hex); regenerating.",
                    instance_key,
                )
            hermes_api_server_key = secrets.token_hex(32)  # 64-char hex token
            set_instance_secret(
                instance_key,
                "HERMES_API_SERVER_KEY",
                hermes_api_server_key,
                description="Bearer token for hermes local OpenAI-compatible API gateway (loopback only).",
            )
        config["api_server"] = {
            "enabled": True,
            "host": "127.0.0.1",
            "port": api_server_port,
            "key": hermes_api_server_key,
        }
        config["dashboard"] = {
            "enabled": True,
            "host": "127.0.0.1",
            "port": dashboard_port,
        }

    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_host": host["hostname"],
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": {
                "agent_name": agent_name,
                "agent_type": claw_name,
                "claw_version": f"v{matched_version}",
                "claw_sha256": claw_sha256,
                "config": config,
                "template_path": str(template_path),
                "force_install": force,
                # ATX W2: scope dashboard_port to hermes only. Unconditional
                # injection puts `dashboard_port: null` in non-hermes
                # inventories where `when: dashboard_port is defined`
                # would silently evaluate True.
                **(
                    {"dashboard_port": dashboard_port}
                    if dashboard_port is not None
                    else {}
                ),
                **secret_vars,  # Inject secrets as ansible vars
            },
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
        host_os_family = host.get("os_family", "linux")
        try:
            base_playbook = _get_base_playbook_path(host_os_family)
        except FileNotFoundError as exc:
            raise InstallationError(f"Base playbook not found: {exc}") from exc

        emit("base", "Installing system dependencies...")
        playbooks_run = []

        base_data_dir = install_log_dir / "base"
        base_data_dir.mkdir(exist_ok=True)

        result = ansible_runner.run(
            private_data_dir=str(base_data_dir),
            inventory=inventory,
            playbook=str(base_playbook),
            quiet=False,  # Show output
            verbosity=1,  # Show task details (-v)
            timeout=300,  # 5 min timeout for base install
        )

        if result.status != "successful":
            raise InstallationError(
                f"Base playbook failed: {result.status}. "
                f"Check logs at {base_data_dir}/artifacts/"
            )
        playbooks_run.append(str(base_playbook))
        emit("base", "System dependencies installed")

        # Step 9: Run agent playbook
        try:
            claw_playbook = _get_agent_playbook_path(claw_name, host_os_family)
        except FileNotFoundError as exc:
            raise InstallationError(f"Agent playbook not found: {exc}") from exc

        emit("claw", f"Installing {claw_name}...")

        claw_data_dir = install_log_dir / "claw"
        claw_data_dir.mkdir(exist_ok=True)

        result = ansible_runner.run(
            private_data_dir=str(claw_data_dir),
            inventory=inventory,
            playbook=str(claw_playbook),
            quiet=False,  # Show output
            verbosity=1,  # Show task details (-v)
            timeout=1800,  # 30 min timeout for claw install
        )

        if result.status != "successful":
            raise InstallationError(
                f"Agent playbook failed: {result.status}. "
                f"Check logs at {claw_data_dir}/artifacts/"
            )
        playbooks_run.append(str(claw_playbook))
        install_skipped = False
        skip_reason = None
        # Skip detection is generic: every agent's install.yaml emits the same
        # task name + `<agent_type>_already_installed` fact when the binary is
        # already at the target version. See `_install_was_skipped`.
        install_skipped = _install_was_skipped(result, claw_name)
        if install_skipped:
            skip_reason = "already_installed"
            emit(
                "claw",
                f"{claw_name} already installed; skipped binary install task",
            )
        if not install_skipped:
            emit("claw", f"{claw_name} installed successfully")

        # Step 9.5: Extract gateway token and device credentials from Ansible facts (OpenClaw only)
        gateway_token = None
        gateway_url = None
        device_id = None
        device_token = None
        device_private_key = None
        if claw_name == "openclaw" and result.status == "successful":
            # Get host facts from Ansible result
            try:
                # ansible-runner stores facts in artifacts/<run_id>/fact_cache/<hostname>
                import json

                artifacts_dir = Path(result.config.artifact_dir)
                fact_cache_dir = artifacts_dir / "fact_cache"

                if fact_cache_dir.exists():
                    # Find fact file for our host
                    for fact_file in fact_cache_dir.glob("*"):
                        try:
                            with open(fact_file) as f:
                                facts = json.load(f)
                                payload = facts.get("__payload__")
                                if not isinstance(payload, str) or not payload:
                                    continue

                                parsed_facts = json.loads(payload)
                                if not isinstance(parsed_facts, dict):
                                    continue

                                gateway_token_raw = parsed_facts.get(
                                    "openclaw_gateway_token"
                                )
                                gateway_url_raw = parsed_facts.get(
                                    "openclaw_gateway_url"
                                )

                                # Handle both plain string and wrapped {"value": ...} format
                                if isinstance(gateway_token_raw, dict):
                                    gateway_token = gateway_token_raw.get("value")
                                elif isinstance(gateway_token_raw, str):
                                    gateway_token = gateway_token_raw
                                else:
                                    gateway_token = None

                                if isinstance(gateway_url_raw, dict):
                                    gateway_url = gateway_url_raw.get("value")
                                elif isinstance(gateway_url_raw, str):
                                    gateway_url = gateway_url_raw
                                else:
                                    gateway_url = None

                                if isinstance(gateway_token, str):
                                    gateway_token = gateway_token.strip()
                                if isinstance(gateway_url, str):
                                    gateway_url = gateway_url.strip()

                                # Extract device credentials for operator scope auth
                                device_id_raw = parsed_facts.get("openclaw_device_id")
                                device_token_raw = parsed_facts.get(
                                    "openclaw_device_token"
                                )
                                device_private_key_raw = parsed_facts.get(
                                    "openclaw_device_private_key"
                                )

                                # Handle wrapped format
                                if isinstance(device_id_raw, dict):
                                    device_id = device_id_raw.get("value")
                                elif isinstance(device_id_raw, str):
                                    device_id = device_id_raw
                                else:
                                    device_id = None

                                if isinstance(device_token_raw, dict):
                                    device_token = device_token_raw.get("value")
                                elif isinstance(device_token_raw, str):
                                    device_token = device_token_raw
                                else:
                                    device_token = None

                                if isinstance(device_private_key_raw, dict):
                                    device_private_key = device_private_key_raw.get(
                                        "value"
                                    )
                                elif isinstance(device_private_key_raw, str):
                                    device_private_key = device_private_key_raw
                                else:
                                    device_private_key = None

                                if gateway_token and gateway_url:
                                    emit(
                                        "claw", "Gateway authentication token captured"
                                    )
                                    if device_id and device_token:
                                        emit("claw", "Device credentials captured")
                                    break
                        except (json.JSONDecodeError, IOError) as file_err:
                            logger.debug(
                                "Skipping fact file %s: %s", fact_file, file_err
                            )
                            continue
            except Exception as e:
                logger.warning("Failed to extract gateway token: %s", e, exc_info=True)
                emit(
                    "warn",
                    "Gateway token capture failed - manual pairing may be needed",
                )

        if claw_name == "openclaw":
            if install_skipped:
                # Skip path: playbook intentionally did not emit credential facts
                # (template-write + pairing block were gated). Read from the
                # in-memory `preserved_gateway` snapshot captured before
                # set_installing() wiped the agent record — reading the host
                # record here would always observe the wiped state and falsely
                # report "credentials missing" on every clean re-install.
                preserved = preserved_gateway[0] or {}
                has_existing_creds = bool(
                    preserved.get("auth") and preserved.get("device")
                )
                if has_existing_creds:
                    emit("claw", "Reusing existing gateway credentials (skip path)")
                else:
                    emit(
                        "warn",
                        "Skip path taken but existing gateway credentials are missing - "
                        "rerun with --force to re-pair",
                    )
            else:
                if not gateway_token:
                    emit(
                        "warn",
                        "Gateway token not captured - manual configuration may be needed",
                    )
                if not gateway_url or not gateway_url.startswith(("ws://", "wss://")):
                    emit(
                        "warn",
                        "Gateway URL not captured - manual configuration may be needed",
                    )
        elif claw_name == "zeroclaw" and install_skipped:
            # ZeroClaw install does NOT pair (pairing lives in configure.yaml),
            # so a re-install at the same version is a pure binary no-op. The
            # preserved_gateway capture is purely to keep the bearer token
            # (set by a prior `clm agent configure`) from being wiped on the
            # restore path in set_installed(). Emit a status line so a user
            # re-running install can tell credentials were retained.
            preserved = preserved_gateway[0] or {}
            if preserved.get("auth"):
                emit("claw", "Reusing existing gateway credentials (skip path)")

        # Step 10: Update host with success status and gateway auth
        def set_installed(h: dict) -> dict:
            if "agents" in h and agent_name in h["agents"]:
                h["agents"][agent_name]["status"] = "installed"
                h["agents"][agent_name]["installed_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                h["agents"][agent_name]["type"] = claw_name

                # Restore preserved onboarding state (captured before ansible ran)
                # This is done AFTER ansible succeeds to prevent corrupted state
                if preserved_onboarding[0]:
                    h["agents"][agent_name]["onboarding"] = preserved_onboarding[0]

                # #305: on the skip path the playbook does not re-emit gateway
                # facts (template-write + pairing block are gated). Restore the
                # gateway config we captured in set_installing() so re-running
                # `clm agent install` at the same version does not silently drop
                # the agent's auth token + device credentials. Scoped to claws
                # that store credentials under `config.gateway`:
                # - openclaw: token + device credentials, captured during install
                # - zeroclaw: bearer token, captured during configure (#357)
                # `gateway_token` is only ever set for openclaw, so the
                # `and not gateway_token` guard is effectively openclaw-only;
                # for zeroclaw we always want the restore on skip because
                # install never minted a fresh token.
                if (
                    claw_name in ("openclaw", "zeroclaw")
                    and install_skipped
                    and preserved_gateway[0]
                    and not gateway_token
                ):
                    if "config" not in h["agents"][agent_name]:
                        h["agents"][agent_name]["config"] = {}
                    h["agents"][agent_name]["config"]["gateway"] = preserved_gateway[0]

                # Store gateway authentication (OpenClaw only)
                if gateway_token and gateway_url:
                    if "config" not in h["agents"][agent_name]:
                        h["agents"][agent_name]["config"] = {}
                    if "gateway" not in h["agents"][agent_name]["config"]:
                        h["agents"][agent_name]["config"]["gateway"] = {}

                    h["agents"][agent_name]["config"]["gateway"]["url"] = gateway_url
                    h["agents"][agent_name]["config"]["gateway"]["auth"] = gateway_token
                    h["agents"][agent_name]["config"]["gateway"]["port"] = openclaw_port

                    # Store device credentials for operator scope auth
                    if device_id and device_token and device_private_key:
                        h["agents"][agent_name]["config"]["gateway"]["device"] = {
                            "id": device_id,
                            "token": device_token,
                            "privateKey": device_private_key,
                        }

                # Persist non-sensitive hermes api_server shape (enabled / host
                # / port) into hosts.json. The bearer token itself lives in
                # secrets.json (see HERMES_API_SERVER_KEY persistence above) so
                # remove_instance_secrets() cleans it up on agent removal.
                if claw_name == "hermes" and hermes_api_server_key:
                    if "config" not in h["agents"][agent_name]:
                        h["agents"][agent_name]["config"] = {}
                    h["agents"][agent_name]["config"]["api_server"] = {
                        "enabled": True,
                        "host": "0.0.0.0",
                        "port": api_server_port,
                    }

                # Persist hermes dashboard shape so the web_ui resolver and
                # `clm agent open` can read host/port without recomputing.
                # Loopback-only — the SSH tunnel is the authentication
                # boundary (issue #478).
                if claw_name == "hermes" and dashboard_port is not None:
                    if "config" not in h["agents"][agent_name]:
                        h["agents"][agent_name]["config"] = {}
                    h["agents"][agent_name]["config"]["dashboard"] = {
                        "enabled": True,
                        "host": "127.0.0.1",
                        "port": dashboard_port,
                    }
            return h

        update_host(host["hostname"], set_installed)

        # Step 11: Initialize onboarding record (non-fatal if it fails)
        try:
            if not initialize_onboarding(host["hostname"], agent_name):
                try:
                    emit(
                        "warn",
                        f"Onboarding setup incomplete - run `clm onboard init {host['hostname']} {agent_name}` to retry",
                    )
                except Exception:
                    logger.warning(
                        "Failed to emit onboarding warning event", exc_info=True
                    )
        except Exception as e:
            logger.warning("Onboarding init failed: %s", e, exc_info=True)
            try:
                emit(
                    "warn",
                    f"Onboarding setup failed - run `clm onboard init {host['hostname']} {agent_name}` to retry",
                )
            except Exception:
                logger.warning("Failed to emit onboarding warning event", exc_info=True)

        # Step 12: Emit completion event (non-fatal if callback fails)
        try:
            emit("complete", f"Installation complete. Logs at {install_log_dir}")
        except Exception:
            logger.warning("Failed to emit completion event", exc_info=True)

        return {
            "success": True,
            "agent": claw_name,
            "version": matched_version,
            "host": host["hostname"],
            "playbooks_run": playbooks_run,
            "error": None,
            "incomplete_installation": incomplete_details,
            "skipped": install_skipped,
            "skip_reason": skip_reason,
        }

    except Exception as e:
        # Step 13: Update host with failure status
        error_msg = str(e)

        def set_failed(h: dict) -> dict:
            if "agents" not in h:
                h["agents"] = {}
            if agent_name not in h["agents"]:
                h["agents"][agent_name] = {
                    "type": claw_name,
                    "version": matched_version,
                    "agent_name": agent_name,
                }
            h["agents"][agent_name]["type"] = claw_name
            h["agents"][agent_name]["status"] = "failed"
            h["agents"][agent_name]["error"] = error_msg
            h["agents"][agent_name]["installed_at"] = None
            return h

        update_host(host["hostname"], set_failed)
        emit("error", f"Installation failed. Logs at {install_log_dir}")

        # Re-raise the exception
        raise
    finally:
        # CWE-312: ansible-runner caches the gateway token, device token, and
        # device private key under `artifacts/<uuid>/fact_cache/<hostname>`
        # via `cacheable: true` on the Save-all-credentials task. Without this
        # cleanup the secrets persist on disk indefinitely. Mirrors the
        # pattern in lifecycle.py's `_run_lifecycle_playbook`. The two child
        # dirs are deterministic and `_cleanup_ansible_artifacts` guards
        # internally with `.exists()`, so it's a safe no-op if a partial
        # failure aborted before either subdir was created.
        _cleanup_ansible_artifacts(install_log_dir / "base")
        _cleanup_ansible_artifacts(install_log_dir / "claw")
