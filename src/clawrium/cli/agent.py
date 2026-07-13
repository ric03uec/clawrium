"""Agent management commands for Clawrium.

This is the primary interface for managing AI assistants.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.panel import Panel

from clawrium.cli.agent_skill import agent_skill_app
from clawrium.cli.install import install as install_command
from clawrium.cli.output._sanitize import sanitize_passthrough
from clawrium.cli.status import status as status_command
from clawrium.core.config import get_config_dir
from clawrium.core.hosts import (
    get_host,
    load_hosts,
    HostsFileCorruptedError,
    read_gateway_auth,
    set_gateway_auth,
)
from clawrium.core.onboarding import (
    OnboardingState,
    StageStatus,
    get_onboarding_state,
    transition_state,
    complete_stage,
    initialize_onboarding,
    can_skip_stage,
    InvalidTransitionError,
    OnboardingNotFoundError,
    AgentNotFoundError,
)

__all__ = ["agent_app"]

console = Console()
err_console = Console(stderr=True)

VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")

STAGE_TO_CURRENT_STATE = {
    "providers": OnboardingState.PROVIDERS,
    "identity": OnboardingState.IDENTITY,
    "channels": OnboardingState.CHANNELS,
    "validate": OnboardingState.VALIDATE,
}

STAGE_TO_NEXT_STATE = {
    "providers": OnboardingState.IDENTITY,
    "identity": OnboardingState.CHANNELS,
    "channels": OnboardingState.VALIDATE,
    "validate": OnboardingState.READY,
}

STATE_RESUME_IDX = {
    "pending": 0,
    "providers": 0,
    "identity": 1,
    "channels": 2,
    "validate": 3,
    "ready": 4,
}

agent_app = typer.Typer(
    name="agent",
    help="Manage AI agents in your fleet",
    no_args_is_help=True,
    rich_markup_mode=None,
)


@agent_app.command()
def install(
    claw: Optional[str] = typer.Option(
        None, "--type", "-t", help="Agent type to install"
    ),
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Target host"),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Agent name for the instance (max 32 chars, alphanumeric/hyphens/underscores)",
    ),
    cleanup_failed: bool = typer.Option(
        False,
        "--cleanup-failed",
        help="Remove incomplete or failed installation of this agent type before retrying",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force reinstall even if the same version is already installed",
    ),
) -> None:
    """Install an agent on a host."""
    install_command(
        claw=claw,
        host=host,
        name=name,
        cleanup_failed=cleanup_failed,
        yes=yes,
        force=force,
    )


@agent_app.command()
def ps(
    host: Optional[str] = typer.Option(
        None, "--host", "-H", help="Filter to specific host"
    ),
) -> None:
    """Show status of agents across hosts."""
    status_command(host=host)


def _print_configure_warnings(stage: str, message: str) -> None:
    """on_event callback for configure_agent that surfaces WARNING-prefixed
    messages and structured lifecycle events to the terminal so silent
    lifecycle gaps (e.g. an integration with an unknown type, or an
    operator-visible token rotation) become visible during `clm agent
    configure`/`sync`/`restart`."""
    if stage == "gateway_token_rotated":
        # Issue #437: structured rotation event. Payload is JSON with
        # agent_key + old/new token prefixes + reason. Decode best-effort
        # — a malformed payload still surfaces, just without the agent
        # name.
        agent_label: str | None = None
        try:
            payload = json.loads(message)
            if isinstance(payload, dict):
                raw_key = payload.get("agent_key")
                if isinstance(raw_key, str) and raw_key:
                    agent_label = raw_key
        except (json.JSONDecodeError, TypeError):
            pass
        if agent_label:
            console.print(
                f"  [yellow]Gateway token rotated for "
                f"{rich_escape(agent_label)}. Active chat sessions on "
                f"other machines will need to reconnect.[/yellow]"
            )
        else:
            console.print(
                "  [yellow]Gateway token rotated. Active chat sessions on "
                "other machines will need to reconnect.[/yellow]"
            )
        return

    if message.startswith("WARNING:"):
        # Escape `message` before embedding in a Rich markup span — the
        # lifecycle warning interpolates `integration_type` from
        # integrations.json, which may be hand-edited and contain Rich
        # tokens like `[bold]`. Without escape Rich would either garble the
        # output or raise MarkupError mid-configure.
        console.print(f"  [yellow]{rich_escape(message)}[/yellow]")


def _validate_name_component(name: str, component_type: str) -> None:
    """Validate a name component against safe character set.

    Args:
        name: Name to validate
        component_type: Type description for error message

    Raises:
        typer.Exit: If name contains invalid characters
    """
    if not VALID_NAME_PATTERN.match(name):
        console.print(
            f"[red]Error:[/red] Invalid {component_type} '{rich_escape(name)}'"
        )
        console.print(
            f"{component_type.capitalize()} must contain only letters, numbers, dots, underscores, and hyphens"
        )
        raise typer.Exit(code=1)


class AgentNameResolutionError(Exception):
    """Raised when an agent name cannot be resolved."""


class AmbiguousAgentNameError(AgentNameResolutionError):
    """Raised when an agent name matches more than one instance."""


def _resolve_agent_instance(agent_name: str) -> tuple[str, dict, str, dict, str]:
    """Resolve an installed agent by canonical instance name.

    Args:
        agent_name: Generated or user-provided instance name

    Returns:
        Tuple of (hostname, host_data, claw_type, claw_record, canonical_name)

    Raises:
        AgentNameResolutionError: If no matching instance exists
        AmbiguousAgentNameError: If multiple instances share the same name
        HostsFileCorruptedError: If hosts.json is corrupted
    """
    _validate_name_component(agent_name, "agent name")

    matches: list[tuple[str, dict, str, dict, str]] = []
    for host_data in load_hosts():
        hostname = host_data.get("hostname")
        if not hostname:
            continue

        for agent_key, claw_record in host_data.get("agents", {}).items():
            # Agent name can be the dict key, or explicit agent_name/name field
            canonical_name = (
                claw_record.get("agent_name") or claw_record.get("name") or agent_key
            )
            claw_type = claw_record.get("type") or agent_key
            if canonical_name == agent_name:
                matches.append(
                    (hostname, host_data, claw_type, claw_record, canonical_name)
                )

    if not matches:
        raise AgentNameResolutionError(
            f"Agent '{agent_name}' not found. Use 'clm agent ps' to list installed agents."
        )

    if len(matches) > 1:
        formatted = ", ".join(
            f"{name} ({claw_type} on {h.get('alias') or h.get('hostname')})"
            for _, h, claw_type, _, name in matches
        )
        raise AmbiguousAgentNameError(
            f"Agent name '{agent_name}' is ambiguous: {formatted}. "
            "Use unique instance names per host."
        )

    return matches[0]


def _stage_header(
    stage_name: str, stage_num: int, total_stages: int, description: str
) -> None:
    """Display stage header."""
    console.print()
    console.print("═" * 51)
    console.print(f" Stage {stage_num}/{total_stages}: {stage_name.upper()}")
    console.print(f" {description}")
    console.print("═" * 51)
    console.print()


def _stage_complete(stage_name: str) -> None:
    """Display stage completion."""
    console.print(f"\n[green]Stage {stage_name.upper()} complete.[/green]")


def _atomic_write_file(path: str, content: str, mode: int = 0o600) -> None:
    """Write file atomically with temp file and rename.

    Args:
        path: Target file path
        content: Content to write
        mode: File permissions (default 0o600)
    """
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _sync_provider_config(
    host: str,
    claw_type: str,
    provider: dict,
    installed_name: str | None = None,
) -> None:
    """Sync provider configuration to remote agent via Ansible.

    This replaces direct SSH config writes with proper Ansible-based configuration
    management. All configuration is stored in hosts.json and applied via playbooks.

    Args:
        host: Host alias
        claw_type: Claw type (zeroclaw, openclaw, etc.)
        provider: Provider dict with name, type, endpoint, model, etc.

    Raises:
        RuntimeError: If configuration sync fails
    """
    import hashlib
    from clawrium.core.lifecycle import configure_agent

    host_data = get_host(host)
    if not host_data:
        raise RuntimeError(f"Host '{host}' not found")

    agents = host_data.get("agents", {})
    if installed_name is None:
        if isinstance(agents, dict) and claw_type in agents:
            installed_name = claw_type
        else:
            matches = [
                key
                for key, record in agents.items()
                if isinstance(record, dict)
                and (record.get("agent_name") or record.get("name"))
            ]
            if len(matches) == 1:
                installed_name = matches[0]

    claw_record = host_data.get("agents", {}).get(installed_name or "")
    if not claw_record:
        raise RuntimeError(f"Agent '{installed_name}' not installed on '{host}'")

    # Calculate or preserve gateway port
    existing_config = claw_record.get("config", {})
    existing_gateway = existing_config.get("gateway", {})

    if existing_gateway.get("port"):
        # Preserve existing port
        gateway_port = existing_gateway["port"]
    else:
        # Calculate port on first configuration (same logic as install playbook)
        port_hash = int(hashlib.md5(installed_name.encode()).hexdigest(), 16)
        gateway_port = 40000 + (port_hash % 2000)

    # Build gateway config based on agent type, preserving existing fields
    if claw_type == "zeroclaw":
        gateway_config = {
            "host": existing_gateway.get("host", "0.0.0.0"),
            "port": gateway_port,
            "allow_public_bind": existing_gateway.get("allow_public_bind", True),
        }
    elif claw_type == "openclaw":
        gateway_config = {
            "bind": existing_gateway.get("bind", "lan"),
            "port": gateway_port,
        }
    else:
        # Default gateway config
        gateway_config = {
            "host": existing_gateway.get("host", "0.0.0.0"),
            "port": gateway_port,
        }

    # Preserve url and auth if they exist
    if "url" in existing_gateway:
        gateway_config["url"] = existing_gateway["url"]
    if "auth" in existing_gateway:
        # #820: route copy-through of the bearer through the read/write
        # helpers so a legacy dict shape on disk normalizes to the bare
        # string at the boundary.
        set_gateway_auth(gateway_config, read_gateway_auth(existing_gateway))

    # Build provider config
    provider_config = {
        "name": provider.get("name", ""),
        "type": provider.get("type", "ollama"),
        "endpoint": provider.get("endpoint", ""),
        "default_model": provider.get("default_model", ""),
    }
    # Pass through optional ollama config fields
    if provider.get("context_window"):
        provider_config["context_window"] = provider["context_window"]
    if provider.get("max_tokens"):
        provider_config["max_tokens"] = provider["max_tokens"]

    # Build complete config data
    config_data = {"gateway": gateway_config, "provider": provider_config}

    # Preserve existing api_server block (Hermes loopback gateway auth).
    # configure_agent re-hydrates this from hosts.json too, but carrying it
    # through here keeps the persisted record consistent across rotations.
    if "api_server" in existing_config:
        config_data["api_server"] = existing_config["api_server"]

    # Call configure_agent to apply configuration via Ansible. The on_event
    # callback surfaces lifecycle WARNINGs (e.g. an integration with an unknown
    # type) so they don't get swallowed into logger.info.
    success, error = configure_agent(
        host,
        claw_type,
        config_data,
        agent_name=installed_name,
        on_event=_print_configure_warnings,
    )

    if not success:
        raise RuntimeError(f"Failed to configure {claw_type}: {error}")


def _run_providers_stage(
    host: str,
    claw_type: str,
    yes: bool,
    installed_name: str | None = None,
) -> bool:
    """Run the PROVIDERS onboarding stage.

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts

    Returns:
        True if stage completed successfully
    """
    from clawrium.core.providers import (
        get_provider_api_key,
        get_provider_aws_credentials,
        load_providers,
        ProvidersFileCorruptedError,
    )

    try:
        providers = load_providers()
    except ProvidersFileCorruptedError as e:
        console.print(f"[red]Error:[/red] Providers file corrupted: {e}")
        return False
    except FileNotFoundError:
        providers = []

    if not providers:
        console.print("[yellow]No providers configured.[/yellow]")
        console.print("Run 'clm provider add' to add an inference provider first.")
        return False

    console.print("[bold]Available providers:[/bold]")
    for i, provider in enumerate(providers, 1):
        name = provider.get("name", "?")
        ptype = provider.get("type", "?")
        model = provider.get("default_model", "-")
        # Determine credential status based on provider type
        if ptype == "ollama":
            # Ollama providers don't require credentials
            key_status = "✓"
        elif ptype == "bedrock":
            # Bedrock uses AWS credentials, not API key
            access_key, secret_key = get_provider_aws_credentials(name)
            key_status = "✓" if (access_key and secret_key) else "✗"
        else:
            # Cloud providers use API key
            key_status = "✓" if get_provider_api_key(name) else "✗"
        console.print(
            f"  {i}. {rich_escape(name)} ({rich_escape(ptype)}, {rich_escape(model)}) {key_status}"
        )

    console.print()
    if yes:
        choice = 1
    else:
        choice = typer.prompt("Select provider", type=int, default=1)

    if choice < 1 or choice > len(providers):
        console.print("[red]Invalid selection[/red]")
        return False

    selected = providers[choice - 1]
    provider_name = selected.get("name")

    # B3: Sync provider config to remote agent BEFORE completing the stage
    console.print("\nSyncing config to agent... ", end="")
    try:
        _sync_provider_config(host, claw_type, selected, installed_name)
        console.print("[green]✓[/green]")
    except Exception as e:
        console.print(f"[red]✗[/red] {rich_escape(str(e))}")
        agent_name = installed_name or claw_type
        console.print(
            f"[red]Error:[/red] Failed to apply provider configuration. "
            f"Run 'clm agent configure {rich_escape(agent_name)} --stage providers' to retry."
        )
        return False

    # Check if providers stage is already complete - if so, skip complete_stage()
    # This allows re-running the stage to update config without state machine errors
    from clawrium.core.onboarding import _get_claw_record, update_stage_metadata

    agent_name = installed_name or claw_type
    claw_record = _get_claw_record(host, agent_name)
    stages = claw_record.get("onboarding", {}).get("stages", {}) if claw_record else {}
    providers_status = stages.get("providers", {}).get("status")

    if providers_status == "complete":
        # Stage already complete (re-configure path). Patch provider_id so the
        # validate stage reads the *current* selection instead of the original
        # provider — complete_stage would raise InvalidTransitionError from a
        # later state, so we update metadata in place.
        try:
            update_stage_metadata(
                host, agent_name, "providers", {"provider_id": provider_name}
            )
        except Exception as e:
            console.print(
                f"[red]✗[/red] Failed to update provider metadata: "
                f"{rich_escape(str(e))}"
            )
            return False
        console.print("[green]✓[/green] Provider configuration updated")
        return True

    # Only complete stage after successful config sync
    console.print("Saving provider selection... ", end="")
    try:
        complete_stage(
            host,
            agent_name,
            "providers",
            StageStatus.COMPLETE,
            {"provider_id": provider_name},
        )
        console.print("[green]✓[/green]")
        return True
    except Exception as e:
        console.print(f"[red]✗[/red] {rich_escape(str(e))}")
        return False


def _run_identity_stage(
    host: str,
    claw_type: str,
    yes: bool,
    installed_name: str | None = None,
    identity_files: list[Path] | None = None,
) -> bool:
    """Run the IDENTITY onboarding stage.

    Creates local identity files and syncs them to the remote workspace.

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts
        installed_name: Agent instance name
        identity_files: Optional list of identity files to import

    Returns:
        True if stage completed successfully
    """
    from clawrium.core.lifecycle import configure_agent
    import shutil

    agent_name = installed_name or claw_type
    config_dir = get_config_dir()
    identity_dir = config_dir / "agents" / claw_type / agent_name / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)

    # If files provided via --file, copy them to identity directory
    if identity_files:
        console.print("[1/3] Import identity files")
        for src_file in identity_files:
            dest_file = identity_dir / src_file.name
            try:
                shutil.copy2(src_file, dest_file)
                console.print(f"  [green]✓[/green] Imported {src_file.name}")
            except Exception as e:
                console.print(
                    f"[red]Error:[/red] Failed to copy {src_file.name}: {rich_escape(str(e))}"
                )
                return False

        # Check if SOUL.md was provided, if not create default
        soul_path = identity_dir / "SOUL.md"
        if not soul_path.exists():
            console.print("  [dim]SOUL.md not provided, creating default...[/dim]")
            try:
                _atomic_write_file(
                    str(soul_path),
                    f"# {agent_name.upper()} Personality\n\nYou are a helpful coding assistant focused on reliability and code quality.\n",
                )
                console.print("  [green]✓[/green] Created default SOUL.md")
            except Exception as e:
                console.print(
                    f"[red]Error:[/red] Failed to write SOUL.md: {rich_escape(str(e))}"
                )
                return False
    else:
        # Interactive mode - prompt for personality
        console.print("[1/3] Create personality file (SOUL.md)")

        if yes:
            personality = "You are a helpful coding assistant focused on reliability and code quality."
        else:
            console.print(
                "  Describe your agent's personality (max 2000 chars, press Enter for default):"
            )
            personality = typer.prompt(
                "> ",
                default="You are a helpful coding assistant focused on reliability and code quality.",
            )

        if len(personality) > 2000:
            console.print(
                "[red]Error:[/red] Personality description exceeds 2000 character limit"
            )
            return False

        soul_path = identity_dir / "SOUL.md"

        try:
            _atomic_write_file(
                str(soul_path),
                f"# {agent_name.upper()} Personality\n\n{personality}\n",
            )
            console.print(f"  [green]✓[/green] Created {soul_path}")
        except Exception as e:
            console.print(
                f"[red]Error:[/red] Failed to write SOUL.md: {rich_escape(str(e))}"
            )
            return False

    console.print("\n[2/3] Create identity files")
    console.print("  [green]✓[/green] Using default identity configuration")

    soul_path = identity_dir / "SOUL.md"

    # Sync identity files to remote workspace
    console.print("\n[3/3] Sync identity files to remote workspace")

    # Get existing config to pass to configure_agent
    host_data = get_host(host)
    if not host_data:
        console.print(f"[red]Error:[/red] Host '{host}' not found")
        return False

    claw_record = host_data.get("agents", {}).get(agent_name, {})
    existing_config = claw_record.get("config", {})

    # If no config exists yet (before providers stage), use minimal config
    if not existing_config:
        existing_config = {"gateway": {}, "provider": {}}

    # Validate soul_path is within config directory (prevent path traversal)
    try:
        if not soul_path.resolve().is_relative_to(config_dir):
            console.print(f"[red]Error:[/red] Invalid soul_path: {soul_path}")
            return False
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid soul_path: {soul_path}")
        return False

    # Trigger workspace sync with identity files
    identity_vars = {
        "soul_path": str(soul_path),
        "sync_workspace": True,
    }

    console.print("  Syncing to remote... ", end="")
    try:
        success, error = configure_agent(
            host,
            claw_type,
            existing_config,
            agent_name=agent_name,
            extra_vars={"identity_files": identity_vars},
            on_event=_print_configure_warnings,
        )
        if success:
            console.print("[green]✓[/green]")
        else:
            console.print("[red]✗[/red]")
            console.print(f"  [yellow]Warning:[/yellow] Workspace sync failed: {error}")
            console.print(
                "  [dim]Identity files saved locally. Sync later with 'clm agent sync'[/dim]"
            )
            # Don't fail the stage - local files are saved
    except Exception as e:
        console.print("[red]✗[/red]")
        console.print(
            f"  [yellow]Warning:[/yellow] Workspace sync failed: {rich_escape(str(e))}"
        )
        console.print(
            "  [dim]Identity files saved locally. Sync later with 'clm agent sync'[/dim]"
        )
        # Don't fail the stage - local files are saved

    # Only call complete_stage if we're actually in the identity state
    # Re-runs from other states should not attempt to complete the stage
    onboarding = claw_record.get("onboarding", {})
    current_state = onboarding.get("state", "pending")

    if current_state == "identity":
        try:
            complete_stage(host, agent_name, "identity", StageStatus.COMPLETE)
        except Exception as e:
            console.print(
                f"[red]Error:[/red] Failed to save identity stage: {rich_escape(str(e))}"
            )
            return False

    return True


def _run_channels_stage(
    host: str,
    claw_type: str,
    yes: bool,
    installed_name: str | None = None,
) -> bool:  # type: ignore[return-value]
    """Run the CHANNELS onboarding stage.

    This wizard is deprecated. Always emits a deprecation message and
    exits with code 2, directing the operator at the modern
    `clawctl channel` surface.

    Args:
        host: Host alias
        claw_type: Agent type (determines which channel types are listed)
        yes: Unused (skip-confirmation flag from legacy wizard)
        installed_name: Agent name for display in the deprecation message
    """
    # Channel-type hint must mirror `_hydrate_channels_from_canonical`
    # in `core/lifecycle.py` (`if resolved_type in ("hermes", "zeroclaw",
    # "ethos"):`). Only those three types pull channels from the
    # canonical store on configure; openclaw and nemoclaw have no
    # canonical channel hydration today, so directing their operators
    # at `clawctl channel attach` would silently no-op on sync
    # (ATX #794 iter-4 W1). zeroclaw has no native Slack channel
    # (#422), so only discord is listed there.
    _channel_types_by_agent = {
        "hermes": "discord, slack",
        "ethos": "discord, slack",
        "zeroclaw": "discord",
    }
    channel_examples = _channel_types_by_agent.get(claw_type)
    safe_agent_name = sanitize_passthrough(
        installed_name or "<agent-name>"
    )
    if channel_examples is None:
        # openclaw / nemoclaw / unknown — no canonical hydration path.
        console.print(
            "[yellow]This wizard is deprecated.[/yellow] "
            f"`{claw_type}` does not currently support attaching "
            "channels via the canonical store. Channel configuration "
            "for this agent type is tracked as a follow-up under #790."
        )
    else:
        console.print(
            "[yellow]This wizard is deprecated.[/yellow] "
            "Channel state is now managed via `channels.json`.\n"
            "Use the modern surface instead "
            f"(supported types: {channel_examples}):\n"
            "  clawctl channel registry create <channel-name> "
            "--type <type> --token <bot-token>  "
            "(stores token in secrets.json)\n"
            "  clawctl agent channel attach <channel-name> --agent "
            f"{safe_agent_name}\n"
            f"  clawctl agent sync {safe_agent_name}"
        )
    raise typer.Exit(code=2)


def _run_validate_stage(
    host: str,
    claw_type: str,
    yes: bool,
    installed_name: str | None = None,
    skip_health: bool = False,
) -> bool:
    """Run the VALIDATE onboarding stage.

    Step ordering and per-claw-type coverage:

    Always (every claw type):
      1. validate_agent_installation — agent record exists in hosts.json
         for `host` / `installed_name or claw_type`.
      2. validate_provider_config + validate_provider_api_key — onboarding
         persisted a provider_id and the provider has credentials (or is
         a no-key provider).
      3. verify_provider_connectivity — provider URL/endpoint is reachable
         and answers in a way the connectivity check accepts.

    Claw-specific (added between provider and gateway/health, when present):
      - openclaw: validate_openclaw_gateway probes the openclaw gateway
        health endpoint over the configured transport.
      - hermes:   validate_hermes_health probes `hermes --version`, the
        agent's `.env` presence, and `GET /health`.

    SOUL.md control-machine check (`validate_soul_md`) is only run for
    openclaw — both hermes and zeroclaw manage their identity / workspace
    files on the agent host (their `identity` onboarding stage `auto_skip`s).
    Running the SOUL.md check on those claw types would always fail because
    `~/.config/clawrium/agents/<claw>/SOUL.md` is never written.

    For zeroclaw specifically this means three local checks total: install
    record, provider config + API key, provider connectivity. There is no
    separate gateway/health step here — the configure playbook owns the
    `GET /health/providers` probe.

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts
        installed_name: Optional agent name override; defaults to claw_type
        skip_health: When True, skip the openclaw / hermes gateway / health
                     check (no-op for zeroclaw)

    Returns:
        True if stage completed successfully
    """
    from clawrium.core.validation import (
        validate_soul_md,
        validate_provider_config,
        validate_provider_api_key,
        verify_provider_connectivity,
        validate_agent_installation,
        validate_openclaw_gateway,
        validate_hermes_health,
    )

    all_errors = []
    all_warnings = []

    # Hermes and ZeroClaw both manage their identity / workspace files on
    # the agent host, not under ~/.config/clawrium/agents/<claw>/. Their
    # onboarding `identity` stage `auto_skip`s, so the control-machine
    # SOUL.md the legacy check looks for is never written. Skipping the
    # check for both keeps the validate stage from blocking onboarding
    # transitions to READY for these agents. (ATX Round 3 B_new2:
    # zeroclaw was previously omitted from this list, which left
    # `_run_validate_stage` permanently failing for it.)
    skip_soul_check = claw_type in ("hermes", "zeroclaw")

    total_checks = 5
    if skip_soul_check:
        total_checks -= 1
    if claw_type not in ("openclaw", "hermes"):
        # Generic claws (zeroclaw, future agents) have no gateway/health step.
        total_checks -= 1

    step_idx = 0

    step_idx += 1
    console.print(f"[{step_idx}/{total_checks}] Validating agent installation...")
    agent_name = installed_name or claw_type
    install_result = validate_agent_installation(host, agent_name)
    if install_result.passed:
        console.print("  [green]✓[/green] Agent installed")
    else:
        console.print("  [red]✗[/red] Agent installation check failed")
        for error in install_result.errors:
            console.print(f"    [red]Error:[/red] {rich_escape(error)}")
        all_errors.extend(install_result.errors)

    if not skip_soul_check:
        step_idx += 1
        console.print(
            f"[{step_idx}/{total_checks}] Validating personality file (SOUL.md)..."
        )
        soul_result = validate_soul_md(claw_type)
        if soul_result.passed:
            console.print("  [green]✓[/green] SOUL.md exists and readable")
            for warning in soul_result.warnings:
                console.print(f"    [yellow]Warning:[/yellow] {rich_escape(warning)}")
                all_warnings.append(warning)
        else:
            console.print("  [red]✗[/red] SOUL.md validation failed")
            for error in soul_result.errors:
                console.print(f"    [red]Error:[/red] {rich_escape(error)}")
            all_errors.extend(soul_result.errors)

    step_idx += 1
    console.print(f"[{step_idx}/{total_checks}] Validating provider configuration...")
    provider_result = validate_provider_config(host, agent_name)
    if provider_result.passed:
        provider_id = provider_result.details.get("provider_id", "unknown")
        provider_type = provider_result.details.get("provider_type", "unknown")
        console.print(
            f"  [green]✓[/green] Provider: {rich_escape(provider_id)} ({rich_escape(provider_type)})"
        )

        console.print("  Checking API key...")
        key_result = validate_provider_api_key(provider_id)
        if key_result.passed:
            if key_result.details.get("key_configured") or key_result.details.get(
                "uses_cloud_auth"
            ):
                console.print("  [green]✓[/green] API credentials configured")
            else:
                console.print(
                    "  [green]✓[/green] Provider configured (no API key needed)"
                )
        else:
            console.print("  [red]✗[/red] API key validation failed")
            for error in key_result.errors:
                console.print(f"    [red]Error:[/red] {rich_escape(error)}")
            all_errors.extend(key_result.errors)
    else:
        console.print("  [red]✗[/red] Provider configuration missing")
        for error in provider_result.errors:
            console.print(f"    [red]Error:[/red] {rich_escape(error)}")
        all_errors.extend(provider_result.errors)

    step_idx += 1
    console.print(f"[{step_idx}/{total_checks}] Testing provider connectivity...")
    if provider_result.passed:
        provider_id = provider_result.details.get("provider_id")
        conn_result = verify_provider_connectivity(provider_id)
        if conn_result.passed:
            if conn_result.details.get("skipped"):
                console.print(
                    "  [yellow]⚠[/yellow] Provider connectivity check skipped"
                )
            else:
                console.print("  [green]✓[/green] Provider connectivity OK")
            for warning in conn_result.warnings:
                console.print(f"    [yellow]Warning:[/yellow] {rich_escape(warning)}")
                all_warnings.append(warning)
        else:
            console.print("  [red]✗[/red] Provider connectivity test failed")
            for error in conn_result.errors:
                console.print(f"    [red]Error:[/red] {rich_escape(error)}")
            all_errors.extend(conn_result.errors)
    else:
        console.print("  [dim]Skipped (no provider configured)[/dim]")

    gateway_status = "not_applicable"
    gateway_reason = ""
    gateway_details: dict = {}
    hermes_health_status = "not_applicable"
    hermes_health_reason = ""
    hermes_health_details: dict = {}

    if claw_type == "openclaw":
        step_idx += 1
        console.print(
            f"[{step_idx}/{total_checks}] Verifying OpenClaw gateway health..."
        )
        if skip_health:
            gateway_status = "skipped"
            gateway_reason = "skipped via --skip-health"
            console.print("  [yellow]⚠[/yellow] Skipped (--skip-health)")
        elif all_errors:
            gateway_status = "skipped"
            gateway_reason = "skipped due to earlier validation errors"
            console.print("  [dim]Skipped due to previous validation errors[/dim]")
        else:
            conn_result = validate_openclaw_gateway(host, agent_name)
            gateway_details = conn_result.details
            if conn_result.passed:
                gateway_status = "passed"
                endpoint = conn_result.details.get("gateway_url")
                if endpoint:
                    console.print(
                        f"  [green]✓[/green] Gateway reachable: {rich_escape(str(endpoint))}"
                    )
                else:
                    console.print("  [green]✓[/green] Gateway connectivity OK")
            else:
                gateway_status = "failed"
                console.print("  [red]✗[/red] Gateway health check failed")
                for error in conn_result.errors:
                    console.print(f"    [red]Error:[/red] {rich_escape(error)}")
                all_errors.extend(conn_result.errors)
    elif claw_type == "hermes":
        # hermes runs three checks on the agent host (binary + .env +
        # loopback /health). The api_server platform binds to 127.0.0.1:8642
        # on the agent host, so the probe runs there via Ansible rather than
        # from the clm machine.
        step_idx += 1
        console.print(
            f"[{step_idx}/{total_checks}] Verifying hermes health on agent host..."
        )
        if skip_health:
            hermes_health_status = "skipped"
            hermes_health_reason = "skipped via --skip-health"
            console.print("  [yellow]⚠[/yellow] Skipped (--skip-health)")
        elif all_errors:
            hermes_health_status = "skipped"
            hermes_health_reason = "skipped due to earlier validation errors"
            console.print("  [dim]Skipped due to previous validation errors[/dim]")
        else:
            hermes_result = validate_hermes_health(host, agent_name)
            hermes_health_details = hermes_result.details
            if hermes_result.passed:
                hermes_health_status = "passed"
                console.print(
                    "  [green]✓[/green] hermes --version OK, ~/.hermes/.env exists, /health returned 200"
                )
            else:
                hermes_health_status = "failed"
                console.print("  [red]✗[/red] hermes health check failed")
                for error in hermes_result.errors:
                    console.print(f"    [red]Error:[/red] {rich_escape(error)}")
                all_errors.extend(hermes_result.errors)

    console.print()
    if all_errors:
        console.print(f"[red]Validation failed with {len(all_errors)} error(s)[/red]")
        if all_warnings:
            console.print(f"[yellow]Warnings: {len(all_warnings)}[/yellow]")
        return False

    if all_warnings:
        console.print(
            f"[yellow]Validation passed with {len(all_warnings)} warning(s)[/yellow]"
        )
    else:
        console.print("[green]Validation passed[/green]")

    metadata = None
    if claw_type == "openclaw":
        metadata = {
            "gateway_health_checked": gateway_status == "passed",
            "gateway_health_status": gateway_status,
        }
        if gateway_reason:
            metadata["gateway_health_reason"] = gateway_reason
        if "gateway_url" in gateway_details:
            metadata["gateway_url"] = gateway_details["gateway_url"]
    elif claw_type == "hermes":
        metadata = {
            "hermes_health_checked": hermes_health_status == "passed",
            "hermes_health_status": hermes_health_status,
        }
        if hermes_health_reason:
            metadata["hermes_health_reason"] = hermes_health_reason
        if "health_status" in hermes_health_details:
            metadata["hermes_http_status"] = hermes_health_details["health_status"]

    try:
        complete_stage(
            host,
            installed_name or claw_type,
            "validate",
            StageStatus.COMPLETE,
            metadata,
        )
        return True
    except Exception as e:
        console.print(
            f"[red]Error:[/red] Failed to save validate stage: {rich_escape(str(e))}"
        )
        return False


def _resolve_editor(editor_option: Optional[str]) -> str:
    """Resolve editor command using precedence: option > VISUAL > EDITOR > vi.

    Args:
        editor_option: Editor specified via --editor option

    Returns:
        Editor command to use
    """
    if editor_option:
        return editor_option
    if os.environ.get("VISUAL"):
        return os.environ["VISUAL"]
    if os.environ.get("EDITOR"):
        return os.environ["EDITOR"]
    return "vi"


def _run_edit_config(
    hostname: str,
    host_data: dict,
    claw_type: str,
    installed_name: str,
    display_host: str,
    editor: Optional[str] = None,
) -> None:
    """Run the edit-config workflow for direct config file editing.

    Opens the agent's config file in an editor, validates changes,
    syncs to the remote host, and optionally restarts the agent.

    Args:
        hostname: Remote host hostname
        host_data: Host configuration data
        claw_type: Type of agent (e.g., "openclaw")
        installed_name: Agent instance name
        display_host: Display name for the host
        editor: Optional editor override (else uses VISUAL/EDITOR/vi)
    """
    from clawrium.core.lifecycle import configure_agent, restart_agent, LifecycleError

    # Get agent's existing config from host_data
    # Need to find the agent record by matching canonical name
    agents = host_data.get("agents", {})
    agent_record = None
    for agent_key, record in agents.items():
        canonical_name = record.get("agent_name") or record.get("name") or agent_key
        if canonical_name == installed_name:
            agent_record = record
            break

    existing_config = agent_record.get("config", {}) if agent_record else {}

    if not existing_config:
        console.print(
            f"[red]Error:[/red] No configuration found for '{rich_escape(installed_name)}' "
            f"on '{rich_escape(display_host)}'."
        )
        console.print(
            "\nRun the onboarding wizard first to create initial configuration:"
        )
        console.print(f"  clm agent configure {rich_escape(installed_name)}")
        raise typer.Exit(code=1)

    # Resolve editor
    editor_cmd = _resolve_editor(editor)

    # Create temp file with agent config
    temp_dir = tempfile.mkdtemp(prefix="clm-edit-")
    config_file = Path(temp_dir) / f"{installed_name}.json"
    preserve_temp_dir = False  # Track if we should preserve temp dir for error recovery

    try:
        # Write config to temp file (pretty-printed for readability)
        with open(config_file, "w") as f:
            json.dump(existing_config, f, indent=2)
            f.write("\n")

        # Store original content for change detection
        original_content = config_file.read_text()

        console.print(
            f"Opening config for '{rich_escape(installed_name)}' in {rich_escape(editor_cmd)}..."
        )

        # Launch editor
        try:
            result = subprocess.run(
                [editor_cmd, str(config_file)],
                check=False,
            )
            if result.returncode != 0:
                console.print(
                    f"[red]Error:[/red] Editor exited with code {result.returncode}"
                )
                raise typer.Exit(code=1)
        except FileNotFoundError:
            console.print(
                f"[red]Error:[/red] Editor '{rich_escape(editor_cmd)}' not found."
            )
            console.print("\nSpecify a different editor with --editor option:")
            console.print(
                f"  clm agent configure {rich_escape(installed_name)} --edit-config --editor nano"
            )
            raise typer.Exit(code=1)

        # Read edited content
        edited_content = config_file.read_text()

        # Check for changes
        if edited_content == original_content:
            console.print("\n[yellow]No changes detected.[/yellow] Nothing to sync.")
            return

        # Validate JSON
        try:
            edited_config = json.loads(edited_content)
        except json.JSONDecodeError as e:
            console.print(f"\n[red]Error:[/red] Invalid JSON: {e}")
            console.print("\nYour edited file has been preserved at:")
            console.print(f"  {config_file}")
            console.print("\nFix the JSON error and try again with:")
            console.print(
                f"  clm agent configure {rich_escape(installed_name)} --edit-config"
            )
            # Don't clean up temp dir so user can recover their edits
            preserve_temp_dir = True
            raise typer.Exit(code=1)

        # Sync to remote
        console.print("\nSyncing configuration to remote host...")

        success, error = configure_agent(
            hostname,
            claw_type,
            edited_config,
            agent_name=installed_name,
            on_event=_print_configure_warnings,
        )

        if not success:
            console.print(f"\n[red]Error:[/red] Sync failed: {error}")
            console.print("\nYour edited file has been preserved at:")
            console.print(f"  {config_file}")
            preserve_temp_dir = True
            raise typer.Exit(code=1)

        console.print(
            f"[green]✓[/green] Configuration synced for '{rich_escape(installed_name)}'"
        )

        # Prompt for restart
        if typer.confirm("\nRestart agent to apply changes?", default=True):
            console.print(f"Restarting '{rich_escape(installed_name)}'...")
            try:
                restart_result = restart_agent(
                    hostname,
                    claw_type,
                    agent_name=installed_name,
                )
                if restart_result["success"]:
                    console.print(
                        f"[green]✓[/green] Agent '{rich_escape(installed_name)}' restarted successfully"
                    )
                else:
                    console.print(
                        f"[red]Error:[/red] Restart failed: {restart_result['error']}"
                    )
                    raise typer.Exit(code=1)
            except LifecycleError as e:
                console.print(f"[red]Error:[/red] Restart failed: {e}")
                raise typer.Exit(code=1)
        else:
            console.print(
                "\nConfiguration synced but agent not restarted. "
                "Restart manually to apply changes:"
            )
            console.print(f"  clm agent restart {rich_escape(installed_name)}")

    finally:
        # Clean up temp directory only if we don't need to preserve it for error recovery
        if not preserve_temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


# Allowed identity file names for --file option
IDENTITY_FILE_ALLOWLIST = {"SOUL.md", "AGENTS.md", "TOOLS.md", "IDENTITY.md"}


@agent_app.command()
def configure(
    claw_name: str = typer.Argument(
        ..., help="Agent instance name to configure (generated or user-provided)"
    ),
    stage: Optional[str] = typer.Option(
        None,
        "--stage",
        "-s",
        help="Run single stage (providers, identity, channels, validate)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip prompts, use defaults"),
    skip_health: bool = typer.Option(
        False,
        "--skip-health",
        help="Skip agent health verification during validate (openclaw gateway probe or hermes /health probe)",
    ),
    file: Optional[list[Path]] = typer.Option(
        None,
        "--file",
        "-f",
        help="Import identity file (SOUL.md, AGENTS.md, TOOLS.md, IDENTITY.md). Repeatable. Only valid with --stage identity.",
        exists=True,
        readable=True,
    ),
    edit_config: bool = typer.Option(
        False,
        "--edit-config",
        help="Open agent config file in editor for direct editing. Cannot be combined with --stage, --file, or --skip-health.",
    ),
    editor: Optional[str] = typer.Option(
        None,
        "--editor",
        help="Editor command for --edit-config (e.g., vim, nano). If not specified, uses VISUAL, then EDITOR, then vi.",
    ),
) -> None:
    """Configure agent settings through an interactive wizard.

    Runs through onboarding stages: providers, identity, channels, validate.
    Use --stage to run a specific stage only.
    Use --edit-config to directly edit the agent's config file.

    Examples:
        clm agent configure wise-hypatia
        clm agent configure clever-einstein --stage providers
        clm agent configure work-assistant --yes
        clm agent configure wolf-i --stage identity --file ~/SOUL.md
        clm agent configure wolf-i --edit-config
        clm agent configure wolf-i --edit-config --editor nano
    """
    # Validate --edit-config incompatible options
    if edit_config:
        if stage:
            console.print(
                "[red]Error:[/red] --edit-config cannot be used with --stage. "
                "Use --edit-config alone to edit the config file."
            )
            raise typer.Exit(code=1)
        if file:
            console.print(
                "[red]Error:[/red] --edit-config cannot be used with --file. "
                "Use --edit-config alone to edit the config file."
            )
            raise typer.Exit(code=1)
        if skip_health:
            console.print(
                "[red]Error:[/red] --edit-config cannot be used with --skip-health. "
                "Use --edit-config alone to edit the config file."
            )
            raise typer.Exit(code=1)

    # Validate --editor requires --edit-config
    if editor and not edit_config:
        console.print("[red]Error:[/red] --editor can only be used with --edit-config")
        raise typer.Exit(code=1)

    # Validate --file is only used with --stage identity
    if file and stage != "identity":
        console.print("[red]Error:[/red] --file can only be used with --stage identity")
        raise typer.Exit(code=1)

    if skip_health and stage and stage != "validate":
        console.print(
            "[red]Error:[/red] --skip-health can only be used with --stage validate or full onboarding"
        )
        raise typer.Exit(code=1)

    # Validate file names are in allowlist
    if file:
        for f in file:
            if f.name not in IDENTITY_FILE_ALLOWLIST:
                console.print(
                    f"[red]Error:[/red] Invalid identity file '{rich_escape(f.name)}'"
                )
                console.print(
                    f"Allowed files: {', '.join(sorted(IDENTITY_FILE_ALLOWLIST))}"
                )
                raise typer.Exit(code=1)
    try:
        (
            hostname,
            host_data,
            claw_type,
            _,
            installed_name,
        ) = _resolve_agent_instance(claw_name)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except AgentNameResolutionError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(code=1)

    display_host = host_data.get("alias") or host_data["hostname"]

    # Route to edit-config flow if requested
    if edit_config:
        _run_edit_config(
            hostname=hostname,
            host_data=host_data,
            claw_type=claw_type,
            installed_name=installed_name,
            display_host=display_host,
            editor=editor,
        )
        raise typer.Exit(code=0)

    try:
        current_state = get_onboarding_state(hostname, installed_name)
    except OnboardingNotFoundError:
        try:
            initialize_onboarding(hostname, installed_name)
            current_state = get_onboarding_state(hostname, installed_name)
        except AgentNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)
    except AgentNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"[bold]Onboarding:[/bold] {rich_escape(installed_name)} on {rich_escape(display_host)}\n"
            f"[bold]Current state:[/bold] {current_state.value.upper()}",
            title="Agent Configuration",
            border_style="cyan",
        )
    )

    STAGES = [
        ("providers", "Assign inference provider to this agent"),
        ("identity", "Configure agent personality and behavior"),
        ("channels", "Configure communication channels"),
        ("validate", "Verify agent is properly configured"),
    ]

    stage_order = [s[0] for s in STAGES]
    stage_descriptions = dict(STAGES)

    if stage:
        if stage not in stage_order:
            console.print(f"[red]Error:[/red] Invalid stage '{rich_escape(stage)}'")
            console.print(f"Valid stages: {', '.join(stage_order)}")
            raise typer.Exit(code=1)

        _stage_header(
            stage, stage_order.index(stage) + 1, len(STAGES), stage_descriptions[stage]
        )

        stage_func = {
            "providers": _run_providers_stage,
            "identity": _run_identity_stage,
            "channels": _run_channels_stage,
            "validate": _run_validate_stage,
        }[stage]

        try:
            if stage == "identity":
                success = stage_func(hostname, claw_type, yes, installed_name, file)
            elif stage == "validate":
                success = stage_func(
                    hostname,
                    claw_type,
                    yes,
                    installed_name,
                    skip_health,
                )
            else:
                success = stage_func(hostname, claw_type, yes, installed_name)
        except KeyboardInterrupt:
            console.print("\nCancelled.")
            raise typer.Exit(code=1)

        if success:
            _stage_complete(stage)
        else:
            console.print(f"[red]Stage {rich_escape(stage)} failed.[/red]")
            raise typer.Exit(code=1)

        raise typer.Exit(code=0)

    total_stages = len(STAGES)
    start_idx = STATE_RESUME_IDX.get(current_state.value, 0)

    if start_idx >= len(stage_order):
        console.print("\n[green]Onboarding already complete![/green]")
        console.print(f"State: {current_state.value.upper()}")
        console.print(
            f"Run 'clm agent start {rich_escape(installed_name)}' to start your agent."
        )
        raise typer.Exit(code=0)

    console.print("\n[bold]Starting onboarding...[/bold]")

    stage_functions = {
        "providers": _run_providers_stage,
        "identity": _run_identity_stage,
        "channels": _run_channels_stage,
        "validate": _run_validate_stage,
    }

    try:
        for i, stage_name in enumerate(stage_order):
            if i < start_idx:
                continue

            if can_skip_stage(claw_type, stage_name):
                # Print a one-line breadcrumb so the user sees WHY a stage was
                # skipped rather than silently swallowed. The reason comes
                # from the manifest stage's `description` field (set by the
                # claw author), e.g. "Hermes manages SOUL.md/AGENTS.md
                # inside ~/.hermes/; clm does not push identity files in
                # this iteration".
                from clawrium.core.registry import load_manifest

                skip_reason = ""
                try:
                    _manifest = load_manifest(claw_type)
                    _stage_cfg = (
                        (_manifest.get("onboarding") or {})
                        .get("stages", {})
                        .get(stage_name, {})
                    )
                    skip_reason = _stage_cfg.get("description", "") or ""
                except Exception:
                    pass
                if skip_reason:
                    console.print(
                        f"[dim]Stage {i + 1}/{total_stages}: "
                        f"{rich_escape(stage_name.upper())} — auto-skipped "
                        f"({rich_escape(skip_reason)})[/dim]"
                    )
                else:
                    console.print(
                        f"[dim]Stage {i + 1}/{total_stages}: "
                        f"{rich_escape(stage_name.upper())} — auto-skipped[/dim]"
                    )
                try:
                    complete_stage(
                        hostname, installed_name, stage_name, StageStatus.SKIPPED
                    )
                except Exception as e:
                    console.print(
                        f"[red]Error:[/red] Failed to skip stage: {rich_escape(str(e))}"
                    )
                    raise typer.Exit(code=1)
                # Also advance the state pointer so the next required stage's
                # `transition_state(PENDING → providers/identity/...)` does not
                # InvalidTransitionError when 2+ consecutive stages auto-skip.
                next_state = STAGE_TO_NEXT_STATE.get(stage_name)
                if next_state is not None:
                    current_st = get_onboarding_state(hostname, installed_name)
                    # Only advance forward; don't revert e.g. validate→ready loop.
                    if current_st.value != next_state.value:
                        try:
                            transition_state(hostname, installed_name, next_state)
                        except InvalidTransitionError:
                            # Either the state already advanced past us or the
                            # caller is re-running. Either way, drop through.
                            pass
                continue

            _stage_header(
                stage_name, i + 1, total_stages, stage_descriptions[stage_name]
            )

            # Transition to the stage's state before running it
            current_stage_state = STAGE_TO_CURRENT_STATE.get(stage_name)
            current_state = get_onboarding_state(hostname, installed_name)
            if current_stage_state and current_state != current_stage_state:
                try:
                    transition_state(hostname, installed_name, current_stage_state)
                except InvalidTransitionError as e:
                    console.print(f"[red]Error:[/red] {e}")
                    raise typer.Exit(code=1)

            if stage_name == "validate":
                success = stage_functions[stage_name](
                    hostname,
                    claw_type,
                    yes,
                    installed_name,
                    skip_health,
                )
            else:
                success = stage_functions[stage_name](
                    hostname, claw_type, yes, installed_name
                )

            if not success:
                console.print(
                    f"[red]Onboarding failed at stage: {rich_escape(stage_name)}[/red]"
                )
                raise typer.Exit(code=1)

            next_state = STAGE_TO_NEXT_STATE[stage_name]
            try:
                transition_state(hostname, installed_name, next_state)
            except InvalidTransitionError as e:
                console.print(f"[red]Error:[/red] {e}")
                raise typer.Exit(code=1)

            _stage_complete(stage_name)

    except KeyboardInterrupt:
        console.print("\n[yellow]Onboarding cancelled.[/yellow]")
        raise typer.Exit(code=1)

    console.print()
    console.print("═" * 51)
    console.print(" [green]Onboarding Complete![/green]")
    console.print("═" * 51)
    console.print()
    console.print("State: [green]READY[/green]")
    console.print(
        f"Run 'clm agent start {rich_escape(installed_name)}' to start your agent."
    )


def _show_start_blocked_error(
    installed_name: str,
    current_state: OnboardingState,
    claw_record: dict,
) -> None:
    """Display error when start is blocked by incomplete onboarding."""
    STAGES = [
        ("providers", "Assign inference provider to this agent"),
        ("identity", "Configure agent personality and behavior"),
        ("channels", "Configure communication channels"),
        ("validate", "Verify agent is properly configured"),
    ]

    if current_state == OnboardingState.PENDING:
        console.print()
        console.print(
            f"[red]Error:[/red] Cannot start {rich_escape(installed_name)} - onboarding not started"
        )
        console.print()
        console.print(
            f"Run 'clm agent configure {rich_escape(installed_name)}' to begin onboarding."
        )
        console.print()
        return

    onboarding = claw_record.get("onboarding", {})
    stages_data = onboarding.get("stages", {})

    completed_count = sum(
        1
        for stage_name in [s[0] for s in STAGES]
        if stages_data.get(stage_name, {}).get("status") in ("complete", "skipped")
    )

    total_stages = len(STAGES)

    # Treat both "complete" and "skipped" as resolved — a skipped stage (e.g.
    # hermes' identity stage in Phase 4) is not something the user needs to
    # come back to.
    incomplete_stages = [
        (name, desc)
        for name, desc in STAGES
        if stages_data.get(name, {}).get("status") not in ("complete", "skipped")
    ]

    console.print()
    console.print(
        f"[red]Error:[/red] Cannot start {rich_escape(installed_name)} - onboarding incomplete"
    )
    console.print()
    console.print(
        f"Current state: {current_state.value.upper()} ({completed_count}/{total_stages})"
    )
    console.print()

    if incomplete_stages:
        console.print("Incomplete stages:")
        for stage_name, stage_desc in incomplete_stages:
            console.print(f"  ○ {stage_name:<10} - {stage_desc}")
        console.print()

    console.print(
        f"Run 'clm agent configure {rich_escape(installed_name)}' to complete onboarding."
    )
    console.print()
    console.print("To force start anyway (not recommended):")
    console.print(f"  clm agent start {rich_escape(installed_name)} --force")
    console.print()


@agent_app.command()
def remove(
    claw_name: str = typer.Argument(..., help="Agent name to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove an agent from a host.

    Stops the agent if running, removes all artifacts from the remote host,
    and removes the agent from local configuration.

    Examples:
        clm agent remove wise-hypatia
        clm agent remove work-assistant --force
    """
    from clawrium.core.lifecycle import remove_agent, LifecycleError

    try:
        hostname, host_data, claw_type, _, installed_name = _resolve_agent_instance(
            claw_name
        )
        display_host = host_data.get("alias") or host_data.get("hostname")
        if not display_host:
            display_host = hostname

        # Confirmation prompt (unless --force)
        if not force:
            confirmed = typer.confirm(
                f"Remove '{rich_escape(installed_name)}' from {rich_escape(display_host)}? This will delete all agent data and cannot be undone."
            )
            if not confirmed:
                console.print("Cancelled.")
                raise typer.Exit(code=0)

        console.print(
            f"[green]Removing agent:[/green] {rich_escape(installed_name)} from {rich_escape(display_host)}"
        )

        def on_event(stage: str, message: str) -> None:
            if stage == "validate":
                console.print(f"  [dim]{message}[/dim]")
            elif stage == "remove":
                console.print(f"  {message}")

        try:
            if installed_name in host_data.get("agents", {}):
                result = remove_agent(
                    hostname, claw_type, agent_name=installed_name, on_event=on_event
                )
            else:
                result = remove_agent(hostname, claw_type, on_event=on_event)
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            console.print("[green]✓[/green] Agent removed successfully")
        else:
            console.print(
                f"[red]✗[/red] Failed to remove agent: "
                f"{rich_escape(result['error'] or '')}"
            )
            raise typer.Exit(code=1)

    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except AgentNameResolutionError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(code=1)


@agent_app.command()
def start(
    claw_name: str = typer.Argument(..., help="Agent name to start"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force start even if onboarding incomplete"
    ),
) -> None:
    """Start an agent.

    Checks onboarding state before allowing start.
    Only agents in READY state can start normally.
    Use --force to bypass this check (not recommended).
    """
    from clawrium.core.lifecycle import start_agent, LifecycleError

    try:
        hostname, host_data, claw_type, claw_record, installed_name = (
            _resolve_agent_instance(claw_name)
        )
        display_host = host_data.get("alias") or host_data.get("hostname")
        if not display_host:
            display_host = hostname

        try:
            current_state = get_onboarding_state(hostname, installed_name)
        except OnboardingNotFoundError:
            try:
                initialize_onboarding(hostname, installed_name)
                current_state = get_onboarding_state(hostname, installed_name)
            except AgentNotFoundError as e:
                console.print(f"[red]Error:[/red] {e}")
                raise typer.Exit(code=1)

        if current_state != OnboardingState.READY and not force:
            _show_start_blocked_error(installed_name, current_state, claw_record)
            raise typer.Exit(code=1)

        if force and current_state != OnboardingState.READY:
            console.print(
                "[yellow]Warning: Starting agent with incomplete onboarding[/yellow]"
            )

        console.print(
            f"[green]Starting agent:[/green] {rich_escape(installed_name)} on {rich_escape(display_host)}"
        )

        def on_event(stage: str, message: str) -> None:
            if stage == "validate":
                console.print(f"  [dim]{message}[/dim]")
            elif stage == "start":
                console.print(f"  {message}")
            elif stage == "gateway_token_rotated":
                _print_configure_warnings(stage, message)

        try:
            if installed_name in host_data.get("agents", {}):
                result = start_agent(
                    hostname,
                    claw_type,
                    agent_name=installed_name,
                    force=force,
                    on_event=on_event,
                )
            else:
                result = start_agent(
                    hostname,
                    claw_type,
                    force=force,
                    on_event=on_event,
                )
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            console.print("[green]✓[/green] Agent started successfully")
            console.print("  Run 'clm agent ps' to check status")
        else:
            console.print(
                f"[red]✗[/red] Failed to start agent: "
                f"{rich_escape(result['error'] or '')}"
            )
            raise typer.Exit(code=1)

    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except AgentNameResolutionError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(code=1)


@agent_app.command()
def stop(
    claw_name: str = typer.Argument(..., help="Agent name to stop"),
    timeout: int = typer.Option(
        30, "--timeout", "-t", help="Seconds to wait for graceful shutdown"
    ),
) -> None:
    """Stop an agent.

    Gracefully shuts down the agent process. If the process doesn't
    stop within the timeout, it will be forcefully terminated.
    """
    from clawrium.core.lifecycle import stop_agent, LifecycleError

    try:
        hostname, host_data, claw_type, _, installed_name = _resolve_agent_instance(
            claw_name
        )
        display_host = host_data.get("alias") or host_data.get("hostname")
        if not display_host:
            display_host = hostname

        console.print(
            f"[green]Stopping agent:[/green] {rich_escape(installed_name)} on {rich_escape(display_host)}"
        )

        def on_event(stage: str, message: str) -> None:
            if stage == "validate":
                console.print(f"  [dim]{message}[/dim]")
            elif stage == "stop":
                console.print(f"  {message}")

        try:
            if installed_name in host_data.get("agents", {}):
                result = stop_agent(
                    hostname,
                    claw_type,
                    agent_name=installed_name,
                    timeout=timeout,
                    on_event=on_event,
                )
            else:
                result = stop_agent(
                    hostname,
                    claw_type,
                    timeout=timeout,
                    on_event=on_event,
                )
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            console.print("[green]✓[/green] Agent stopped successfully")
        else:
            console.print(
                f"[red]✗[/red] Failed to stop agent: "
                f"{rich_escape(result['error'] or '')}"
            )
            raise typer.Exit(code=1)

    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except AgentNameResolutionError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(code=1)


@agent_app.command()
def restart(
    claw_name: str = typer.Argument(..., help="Agent name to restart"),
) -> None:
    """Restart an agent.

    Stops and starts the agent. Useful after configuration changes.
    """
    from clawrium.core.lifecycle import restart_agent, LifecycleError

    try:
        hostname, host_data, claw_type, _, installed_name = _resolve_agent_instance(
            claw_name
        )
        display_host = host_data.get("alias") or host_data.get("hostname")
        if not display_host:
            display_host = hostname

        console.print(
            f"[green]Restarting agent:[/green] {rich_escape(installed_name)} on {rich_escape(display_host)}"
        )

        def on_event(stage: str, message: str) -> None:
            if stage in ("validate", "restart"):
                console.print(f"  [dim]{message}[/dim]")
            elif stage == "gateway_token_rotated":
                # ATX W3: route structured rotation events through the
                # shared renderer so the operator sees the yellow notice
                # documented in AGENTS.md instead of raw JSON.
                _print_configure_warnings(stage, message)
            else:
                console.print(f"  {message}")

        try:
            if installed_name in host_data.get("agents", {}):
                result = restart_agent(
                    hostname,
                    claw_type,
                    agent_name=installed_name,
                    on_event=on_event,
                )
            else:
                result = restart_agent(hostname, claw_type, on_event=on_event)
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            console.print("[green]✓[/green] Agent restarted successfully")
            console.print("  Run 'clm agent ps' to check status")
        else:
            console.print(
                f"[red]✗[/red] Failed to restart agent: "
                f"{rich_escape(result['error'] or '')}"
            )
            raise typer.Exit(code=1)

    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except AgentNameResolutionError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(code=1)


@agent_app.command()
def sync(
    claw_name: str = typer.Argument(
        ..., help="Agent instance name to sync (use 'clm agent ps' to list agents)"
    ),
    workspace: bool = typer.Option(
        False,
        "--workspace",
        "-w",
        help="Sync workspace files only (no restart)",
    ),
) -> None:
    """Sync configuration and optionally restart an agent.

    Pushes latest configuration to the agent host. By default, restarts
    the agent to apply changes. Use --workspace for workspace-only sync
    without restart.

    Examples:
        clm agent sync wise-hypatia
        clm agent sync work-assistant --workspace
    """
    from clawrium.core.lifecycle import sync_agent, LifecycleError

    try:
        hostname, host_data, claw_type, _, installed_name = _resolve_agent_instance(
            claw_name
        )
        display_host = host_data.get("alias") or host_data.get("hostname")
        if not display_host:
            display_host = hostname

        action = "Syncing workspace for" if workspace else "Syncing agent:"
        console.print(
            f"[green]{action}[/green] {rich_escape(installed_name)} on {rich_escape(display_host)}"
        )

        def on_event(stage: str, message: str) -> None:
            # configure stage gets dim, sync stage gets normal
            if stage == "configure":
                console.print(f"  [dim]{message}[/dim]")
            elif stage == "gateway_token_rotated":
                # ATX W3: structured rotation events get the yellow
                # notice from the shared renderer, not raw JSON.
                _print_configure_warnings(stage, message)
            else:
                # ATX iter-5 W1-NEW: rich-escape so an emit containing
                # `[Errno 13]`-style OSError text doesn't trigger
                # MarkupError mid-stream. Producers in core/ emit raw
                # strings; the rendering boundary is here.
                console.print(f"  {rich_escape(message)}")

        try:
            result = sync_agent(
                hostname,
                claw_type,
                agent_name=installed_name,
                workspace_only=workspace,
                on_event=on_event,
            )
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            # Issue #437 / ATX W9: sync no longer orchestrates a restart;
            # the daemon-side restart fires via the configure playbook's
            # notify handler only when config.toml or the systemd
            # drop-in actually changed. Drop the misleading "agent
            # restarted" string.
            console.print("[green]✓[/green] Configuration synced")
            console.print("  Run 'clm agent ps' to check status")
        else:
            console.print(
                f"[red]✗[/red] Failed to sync agent: "
                f"{rich_escape(result['error'] or '')}"
            )
            raise typer.Exit(code=1)

    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except AgentNameResolutionError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(code=1)


def _host_is_local(host: str) -> bool:
    """Heuristic: return True if ``host`` resolves to a loopback / local IP.

    Used by ``clm agent open`` to skip the SSH tunnel when the agent runs
    on the same machine as the CLI invocation. Conservative — anything we
    cannot definitively classify as loopback returns False so we err on
    the side of opening a tunnel.
    """
    import ipaddress

    if not host:
        return False
    candidate = host.strip().lower()
    if candidate in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


@agent_app.command(name="open")
def open_ui(
    claw_name: str = typer.Argument(..., help="Agent name to open the native UI for"),
    print_url: bool = typer.Option(
        False,
        "--print",
        help="Print the remote URL and exit; do not spawn a tunnel or open a browser.",
    ),
) -> None:
    """Open an agent's native web UI in your default browser.

    For remote agents this establishes an SSH local-port-forward tunnel to
    the agent's dashboard port (resolved to the remote loopback regardless
    of whether the agent itself binds 127.0.0.1 or 0.0.0.0) and points your
    browser at the local end of the tunnel. The tunnel runs until you
    Ctrl-C.

    Hermes, zeroclaw, and openclaw expose a native UI today; agents whose
    manifests do not declare `features.web_ui` print a hard-error.
    """
    import signal
    import webbrowser

    from clawrium.core.health import ClawStatus, check_claw_health
    from clawrium.core.web_ui import resolve as resolve_web_ui
    from clawrium.core.web_ui_tunnel import (
        TunnelError,
        close as close_tunnel,
        ensure as ensure_tunnel,
    )

    import threading

    try:
        hostname, host_data, claw_type, _, installed_name = _resolve_agent_instance(
            claw_name
        )
    except AgentNameResolutionError as e:
        err_console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)
    except HostsFileCorruptedError as e:
        err_console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)

    resolved = resolve_web_ui(installed_name)
    if resolved is None:
        err_console.print(
            f"[red]Error:[/red] Agent '{rich_escape(installed_name)}' does not "
            "declare a native web UI in its manifest."
        )
        raise typer.Exit(code=1)

    remote_url = f"http://{resolved.host}:{resolved.remote_port}/"

    if print_url:
        # Machine-readable: bypass Rich entirely so a crafted hostname can't
        # render markup, and stdout stays a clean URL for piping.
        print(remote_url)
        return

    try:
        health = check_claw_health(installed_name, host_data)
    except Exception as e:  # noqa: BLE001 — best-effort probe; surface but don't crash
        err_console.print(
            f"[yellow]Warning:[/yellow] Could not verify agent status "
            f"({rich_escape(str(e))}); proceeding."
        )
        health = None

    if health and health["status"] not in (ClawStatus.READY, ClawStatus.RUNNING):
        status_label = (
            health["status"].value
            if isinstance(health["status"], ClawStatus)
            else str(health["status"])
        )
        err_console.print(
            f"[red]Error:[/red] Agent '{rich_escape(installed_name)}' is not "
            f"running (status: {rich_escape(status_label)}). "
            f"Try: clm agent start {rich_escape(installed_name)}"
        )
        raise typer.Exit(code=1)

    if _host_is_local(resolved.host):
        local_url = f"http://127.0.0.1:{resolved.remote_port}/"
        console.print(
            f"[green]Opening native UI for[/green] {rich_escape(installed_name)} "
            f"(local agent, no tunnel needed)"
        )
        console.print(f"  URL: {rich_escape(local_url)}")
        webbrowser.open(local_url)
        return

    try:
        local_port = ensure_tunnel(installed_name)
    except TunnelError as e:
        err_console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)

    local_url = f"http://127.0.0.1:{local_port}/"
    console.print(f"[green]Opening native UI for[/green] {rich_escape(installed_name)}")
    console.print(f"  Local port: {local_port}")
    console.print(f"  URL: {rich_escape(local_url)}")
    console.print("  Press Ctrl-C to close the tunnel and exit.")
    webbrowser.open(local_url)

    # threading.Event is portable; signal.pause() is POSIX-only. SIGINT
    # (Ctrl-C) and SIGTERM both flip the event so SIGTERM-from-shell also
    # cleans up the tunnel instead of orphaning the ssh subprocess.
    stop_event = threading.Event()

    def _on_signal(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    prev_int = signal.signal(signal.SIGINT, _on_signal)
    prev_term = signal.signal(signal.SIGTERM, _on_signal)
    try:
        stop_event.wait()
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)
        close_tunnel(installed_name)
        console.print("\n[green]Tunnel closed.[/green]")


@agent_app.command()
def logs(
    claw_name: str = typer.Argument(..., help="Agent name to view logs for"),
) -> None:
    """View agent logs.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] logs '{rich_escape(claw_name)}'")
    console.print("This command will allow viewing agent logs in a future release.")
    raise typer.Exit(code=0)


secret_app = typer.Typer(
    name="secret",
    help="Manage secrets for agents",
    no_args_is_help=True,
    rich_markup_mode=None,
)


@secret_app.command(name="set")
def secret_set(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    key: str = typer.Argument(..., help="Secret key name (e.g., OPENAI_API_KEY)"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Description of the secret"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip overwrite confirmation"),
) -> None:
    """Set a secret value for an agent."""
    from clawrium.cli.secret import set_cmd

    set_cmd(claw_name=claw_name, key=key, description=description, yes=yes)


@secret_app.command(name="list")
def secret_list(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
) -> None:
    """List secrets for an agent."""
    from clawrium.cli.secret import list_cmd

    list_cmd(claw_name=claw_name)


@secret_app.command(name="remove")
def secret_remove(
    claw_name: str = typer.Argument(..., help="Agent name"),
    key: str = typer.Argument(..., help="Secret key to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove a secret from an agent."""
    from clawrium.cli.secret import remove_cmd

    remove_cmd(claw_name=claw_name, key=key, force=force)


@secret_app.command(name="import")
def secret_import(
    source_claw: str = typer.Argument(..., help="Source agent to import secrets from"),
    target_claw: str = typer.Argument(..., help="Target agent to import secrets to"),
) -> None:
    """Import secrets from another agent.

    [Not yet implemented]
    """
    console.print(
        f"[yellow]Not implemented:[/yellow] import secrets from '{rich_escape(source_claw)}' to '{rich_escape(target_claw)}'"
    )
    console.print(
        "This command will allow importing secrets between agents in a future release."
    )
    raise typer.Exit(code=0)


agent_app.add_typer(secret_app, name="secret")


# Memory inspection and management for agents
memory_app = typer.Typer(
    name="memory",
    help="Inspect and manage memory for memory-capable agents",
    no_args_is_help=True,
    rich_markup_mode=None,
)


@memory_app.command(name="show")
def memory_show(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
) -> None:
    """Show memory file paths and sizes for a memory-capable agent."""
    from clawrium.cli.memory import show_cmd

    show_cmd(claw_name=claw_name)


@memory_app.command(name="delete")
def memory_delete(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    file: Optional[str] = typer.Option(
        None,
        "--file",
        help="Single memory file to delete (e.g., SOUL.md or memory/2026-05-09.md).",
    ),
    all_files: bool = typer.Option(
        False,
        "--all",
        help="Delete every memory file. Requires --force and a typed confirmation.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip the per-file confirmation prompt; required gate for --all.",
    ),
) -> None:
    """Delete one memory file or every memory file for the agent."""
    from clawrium.cli.memory import delete_cmd

    delete_cmd(claw_name=claw_name, file=file, all_files=all_files, force=force)


@memory_app.command(name="edit")
def memory_edit(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    file: str = typer.Argument(
        ...,
        help="Workspace-relative file (e.g., SOUL.md or memory/2026-05-09.md).",
    ),
    editor: Optional[str] = typer.Option(
        None,
        "--editor",
        help="Editor command. Defaults to $VISUAL, then $EDITOR, then 'vi'.",
    ),
    no_restart: bool = typer.Option(
        False,
        "--no-restart",
        help="Save the edit but skip restarting the agent.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip the restart confirmation prompt.",
    ),
) -> None:
    """Edit a memory file in $EDITOR; sync changes back and restart agent."""
    from clawrium.cli.memory import edit_cmd

    edit_cmd(
        claw_name=claw_name,
        file=file,
        editor=editor,
        no_restart=no_restart,
        force=force,
    )


agent_app.add_typer(memory_app, name="memory")


# Integration management for agents
integration_app = typer.Typer(
    name="integration",
    help="Manage integrations assigned to agents",
    no_args_is_help=True,
    rich_markup_mode=None,
)


@integration_app.command(name="list")
def integrations_list(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
) -> None:
    """List integrations assigned to an agent."""
    from rich.table import Table

    from clawrium.core.integrations import (
        get_agent_integrations,
        load_integrations,
        IntegrationsFileCorruptedError,
    )
    from clawrium.core.secrets import AgentNotFoundError, get_installed_claw

    try:
        hostname, claw_type, name = get_installed_claw(claw_name)
    except AgentNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    assigned = get_agent_integrations(hostname, name)

    console.print(f"\n[bold]Agent:[/bold] {rich_escape(name)}")

    if not assigned:
        console.print("  No integrations assigned")
        console.print(
            "\n[dim]Use 'clm agent integration add <agent> <integration>' to assign integrations[/dim]"
        )
        return

    # Show assigned integrations with details
    table = Table(show_header=True, box=None)
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("Status", style="dim")

    try:
        all_integrations = {i["name"]: i for i in load_integrations()}
    except IntegrationsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    for integration_name in assigned:
        integration = all_integrations.get(integration_name)
        if integration:
            table.add_row(
                rich_escape(integration_name),
                rich_escape(integration.get("type", "?")),
                "[green]configured[/green]",
            )
        else:
            table.add_row(
                rich_escape(integration_name),
                "?",
                "[red]missing[/red]",
            )

    console.print(table)


@integration_app.command(name="add")
def integrations_add(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    integration_name: str = typer.Argument(..., help="Integration name to assign"),
) -> None:
    """Assign an integration to an agent.

    Examples:
        clm agent integration add my-agent work-github
        clm agent integration add my-agent work-atlassian
    """
    from clawrium.core.integrations import (
        add_agent_integration,
        get_integration,
        IntegrationsFileCorruptedError,
        IntegrationSingletonViolation,
    )
    from clawrium.core.secrets import AgentNotFoundError, get_installed_claw

    try:
        hostname, claw_type, name = get_installed_claw(claw_name)
    except AgentNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Verify integration exists
    try:
        integration = get_integration(integration_name)
    except IntegrationsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not integration:
        console.print(
            f"[red]Error:[/red] Integration '{rich_escape(integration_name)}' not found"
        )
        console.print("Use 'clm integration list' to see available integrations")
        raise typer.Exit(code=1)

    # Singleton enforcement happens atomically inside `add_agent_integration`'s
    # update_host closure (#534 iter-2 NB-1). The CLI just catches and renders
    # the exception. This closes both the TOCTOU window a CLI pre-check would
    # leave open AND the direct-API bypass path (e.g. hosts.json edits).
    try:
        added = add_agent_integration(hostname, name, integration_name)
    except IntegrationSingletonViolation as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            "[dim]Hint: detach the existing one first with "
            f"'clm agent integration remove {rich_escape(claw_name)} {rich_escape(e.existing_name)}'.[/dim]"
        )
        raise typer.Exit(code=1)

    if added:
        console.print(
            f"[green]Integration '{rich_escape(integration_name)}' assigned to '{rich_escape(name)}'[/green]"
        )
    else:
        console.print(
            f"[yellow]Integration '{rich_escape(integration_name)}' is already assigned to '{rich_escape(name)}'[/yellow]"
        )


@integration_app.command(name="remove")
def integrations_remove(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    integration_name: str = typer.Argument(..., help="Integration name to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Remove an integration from an agent.

    Examples:
        clm agent integration remove my-agent work-github
    """
    from clawrium.core.integrations import (
        get_agent_integrations,
        remove_agent_integration,
    )
    from clawrium.core.secrets import AgentNotFoundError, get_installed_claw

    try:
        hostname, claw_type, name = get_installed_claw(claw_name)
    except AgentNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Check if integration is assigned
    assigned = get_agent_integrations(hostname, name)
    if integration_name not in assigned:
        console.print(
            f"[red]Error:[/red] Integration '{rich_escape(integration_name)}' "
            f"is not assigned to '{rich_escape(name)}'"
        )
        raise typer.Exit(code=1)

    if not force:
        confirmed = typer.confirm(
            f"Unassign integration '{rich_escape(integration_name)}' from '{rich_escape(name)}'?"
        )
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    if remove_agent_integration(hostname, name, integration_name):
        console.print(
            f"[green]Integration '{rich_escape(integration_name)}' removed from '{rich_escape(name)}'[/green]"
        )
    else:
        console.print("[red]Error:[/red] Failed to remove integration")
        raise typer.Exit(code=1)


agent_app.add_typer(integration_app, name="integration")


registry_app = typer.Typer(
    name="registry",
    help="Browse available agent types",
    no_args_is_help=True,
    rich_markup_mode=None,
)


@registry_app.command(name="list")
def registry_list() -> None:
    """List available agent types in the registry."""
    from clawrium.cli.registry import list_registry

    list_registry()


@registry_app.command(name="show")
def registry_show(
    agent_type: str = typer.Argument(..., help="Name of the agent type to show"),
) -> None:
    """Show detailed information about an agent type."""
    from clawrium.cli.registry import show

    show(agent_type=agent_type)


agent_app.add_typer(registry_app, name="registry")
agent_app.add_typer(agent_skill_app, name="skill")
