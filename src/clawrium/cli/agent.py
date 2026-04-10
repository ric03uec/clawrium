"""Agent management commands for Clawrium.

This is the primary interface for managing AI assistants.
"""

import os
import re
import tempfile
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.panel import Panel

from clawrium.cli.install import install as install_command
from clawrium.cli.status import status as status_command
from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host, load_hosts, HostsFileCorruptedError
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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Install an agent on a host."""
    install_command(claw=claw, host=host, name=name, yes=yes)


@agent_app.command()
def ps(
    host: Optional[str] = typer.Option(
        None, "--host", "-H", help="Filter to specific host"
    ),
) -> None:
    """Show status of agents across hosts."""
    status_command(host=host)


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

        for claw_type, claw_record in host_data.get("agents", {}).items():
            canonical_name = claw_record.get("agent_name") or claw_record.get("name")
            if not canonical_name:
                continue
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


def _sync_provider_config(host: str, claw_type: str, provider: dict) -> None:
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

    claw_record = host_data.get("agents", {}).get(claw_type)
    if not claw_record:
        raise RuntimeError(f"Agent '{claw_type}' not installed on '{host}'")
    installed_name = claw_record.get("agent_name") or claw_record.get("name") or claw_type

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
        gateway_config["auth"] = existing_gateway["auth"]

    # Build provider config
    provider_config = {
        "name": provider.get("name", ""),
        "type": provider.get("type", "ollama"),
        "endpoint": provider.get("endpoint", ""),
        "default_model": provider.get("default_model", ""),
    }

    # Build complete config data
    config_data = {"gateway": gateway_config, "provider": provider_config}

    # Call configure_agent to apply configuration via Ansible
    success, error = configure_agent(host, claw_type, config_data)

    if not success:
        raise RuntimeError(f"Failed to configure {claw_type}: {error}")


def _run_providers_stage(host: str, claw_type: str, yes: bool) -> bool:
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
        _sync_provider_config(host, claw_type, selected)
        console.print("[green]✓[/green]")
    except Exception as e:
        console.print(f"[red]✗[/red] {rich_escape(str(e))}")
        console.print(
            f"[red]Error:[/red] Failed to apply provider configuration. "
            f"Run 'clm agent configure {claw_type[:2]}-{host} --stage providers' to retry."
        )
        return False

    # Only complete stage after successful config sync
    console.print("Saving provider selection... ", end="")
    try:
        complete_stage(
            host,
            claw_type,
            "providers",
            StageStatus.COMPLETE,
            {"provider_id": provider_name},
        )
        console.print("[green]✓[/green]")
        return True
    except Exception as e:
        console.print(f"[red]✗[/red] {rich_escape(str(e))}")
        return False


def _run_identity_stage(host: str, claw_type: str, yes: bool) -> bool:
    """Run the IDENTITY onboarding stage.

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts

    Returns:
        True if stage completed successfully
    """
    console.print("[1/2] Create personality file (SOUL.md)")

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

    config_dir = get_config_dir()
    soul_dir = config_dir / "agents" / claw_type
    soul_dir.mkdir(parents=True, exist_ok=True)
    soul_path = soul_dir / "SOUL.md"

    try:
        _atomic_write_file(
            str(soul_path),
            f"# {claw_type.upper()} Personality\n\n{personality}\n",
        )
        console.print(f"  [green]✓[/green] Created {soul_path}")
    except Exception as e:
        console.print(
            f"[red]Error:[/red] Failed to write SOUL.md: {rich_escape(str(e))}"
        )
        return False

    console.print("\n[2/2] Create identity file")
    console.print("  [green]✓[/green] Using default identity configuration")

    try:
        complete_stage(host, claw_type, "identity", StageStatus.COMPLETE)
        return True
    except Exception as e:
        console.print(
            f"[red]Error:[/red] Failed to save identity stage: {rich_escape(str(e))}"
        )
        return False


def _run_channels_stage(host: str, claw_type: str, yes: bool) -> bool:
    """Run the CHANNELS onboarding stage.

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts

    Returns:
        True if stage completed successfully
    """
    channels = ["cli", "web", "whatsapp", "slack"]

    console.print("[bold]Select default channel:[/bold]")
    for i, ch in enumerate(channels, 1):
        recommended = " (recommended)" if ch == "cli" else ""
        console.print(f"  {i}. {ch}{recommended}")

    console.print()

    if yes:
        choice = 1
    else:
        choice = typer.prompt("Select", type=int, default=1)

    if choice < 1 or choice > len(channels):
        console.print("[red]Invalid selection[/red]")
        return False

    selected_channel = channels[choice - 1]
    console.print(f"[green]✓[/green] Default channel: {selected_channel}")

    try:
        complete_stage(
            host,
            claw_type,
            "channels",
            StageStatus.COMPLETE,
            {"default_channel": selected_channel},
        )
        return True
    except Exception as e:
        console.print(
            f"[red]Error:[/red] Failed to save channels stage: {rich_escape(str(e))}"
        )
        return False


def _run_validate_stage(host: str, claw_type: str, yes: bool) -> bool:
    """Run the VALIDATE onboarding stage.

    Performs comprehensive validation of agent configuration:
    1. Verify SOUL.md personality file exists
    2. Check provider is configured
    3. Validate API key exists
    4. Test provider connectivity

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts

    Returns:
        True if stage completed successfully
    """
    from clawrium.core.validation import (
        validate_soul_md,
        validate_provider_config,
        validate_provider_api_key,
        verify_provider_connectivity,
        validate_agent_installation,
    )

    all_errors = []
    all_warnings = []

    console.print("[1/4] Validating agent installation...")
    install_result = validate_agent_installation(host, claw_type)
    if install_result.passed:
        console.print("  [green]✓[/green] Agent installed")
    else:
        console.print("  [red]✗[/red] Agent installation check failed")
        for error in install_result.errors:
            console.print(f"    [red]Error:[/red] {rich_escape(error)}")
        all_errors.extend(install_result.errors)

    console.print("[2/4] Validating personality file (SOUL.md)...")
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

    console.print("[3/4] Validating provider configuration...")
    provider_result = validate_provider_config(host, claw_type)
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

    console.print("[4/4] Testing provider connectivity...")
    if provider_result.passed:
        provider_id = provider_result.details.get("provider_id")
        conn_result = verify_provider_connectivity(provider_id)
        if conn_result.passed:
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

    try:
        complete_stage(host, claw_type, "validate", StageStatus.COMPLETE)
        return True
    except Exception as e:
        console.print(
            f"[red]Error:[/red] Failed to save validate stage: {rich_escape(str(e))}"
        )
        return False


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
) -> None:
    """Configure agent settings through an interactive wizard.

    Runs through onboarding stages: providers, identity, channels, validate.
    Use --stage to run a specific stage only.

    Examples:
        clm agent configure wise-hypatia
        clm agent configure clever-einstein --stage providers
        clm agent configure work-assistant --yes
    """
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

    try:
        current_state = get_onboarding_state(hostname, claw_type)
    except OnboardingNotFoundError:
        try:
            initialize_onboarding(hostname, claw_type)
            current_state = get_onboarding_state(hostname, claw_type)
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
            success = stage_func(hostname, claw_type, yes)
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
                try:
                    complete_stage(hostname, claw_type, stage_name, StageStatus.SKIPPED)
                except Exception as e:
                    console.print(
                        f"[red]Error:[/red] Failed to skip stage: {rich_escape(str(e))}"
                    )
                    raise typer.Exit(code=1)
                continue

            _stage_header(
                stage_name, i + 1, total_stages, stage_descriptions[stage_name]
            )

            # Transition to the stage's state before running it
            current_stage_state = STAGE_TO_CURRENT_STATE.get(stage_name)
            current_state = get_onboarding_state(hostname, claw_type)
            if current_stage_state and current_state != current_stage_state:
                try:
                    transition_state(hostname, claw_type, current_stage_state)
                except InvalidTransitionError as e:
                    console.print(f"[red]Error:[/red] {e}")
                    raise typer.Exit(code=1)

            success = stage_functions[stage_name](hostname, claw_type, yes)

            if not success:
                console.print(
                    f"[red]Onboarding failed at stage: {rich_escape(stage_name)}[/red]"
                )
                raise typer.Exit(code=1)

            next_state = STAGE_TO_NEXT_STATE[stage_name]
            try:
                transition_state(hostname, claw_type, next_state)
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
        if stages_data.get(stage_name, {}).get("status") == "complete"
    )

    total_stages = len(STAGES)

    incomplete_stages = [
        (name, desc)
        for name, desc in STAGES
        if stages_data.get(name, {}).get("status") != "complete"
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
            result = remove_agent(hostname, claw_type, on_event=on_event)
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            console.print("[green]✓[/green] Agent removed successfully")
        else:
            console.print(f"[red]✗[/red] Failed to remove agent: {result['error']}")
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
            current_state = get_onboarding_state(hostname, claw_type)
        except OnboardingNotFoundError:
            try:
                initialize_onboarding(hostname, claw_type)
                current_state = get_onboarding_state(hostname, claw_type)
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

        try:
            result = start_agent(hostname, claw_type, force=force, on_event=on_event)
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            console.print("[green]✓[/green] Agent started successfully")
            console.print("  Run 'clm agent ps' to check status")
        else:
            console.print(f"[red]✗[/red] Failed to start agent: {result['error']}")
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
            result = stop_agent(hostname, claw_type, timeout=timeout, on_event=on_event)
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            console.print("[green]✓[/green] Agent stopped successfully")
        else:
            console.print(f"[red]✗[/red] Failed to stop agent: {result['error']}")
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
            else:
                console.print(f"  {message}")

        try:
            result = restart_agent(hostname, claw_type, on_event=on_event)
        except LifecycleError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if result["success"]:
            console.print("[green]✓[/green] Agent restarted successfully")
            console.print("  Run 'clm agent ps' to check status")
        else:
            console.print(f"[red]✗[/red] Failed to restart agent: {result['error']}")
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


registry_app = typer.Typer(
    name="registry",
    help="Browse available agent types",
    no_args_is_help=True,
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
