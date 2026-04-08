"""Agent management commands for Clawrium.

This is the primary interface for managing AI assistants (claws).
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
from clawrium.core.hosts import get_host, HostsFileCorruptedError
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
    ClawNotFoundError,
)

__all__ = ["agent_app"]

console = Console()

VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")

ALIAS_GROUPS = [
    {"opc", "openclaw"},
    {"zc", "zeroclaw"},
    {"nc", "nemoclaw"},
]

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
    help="Manage AI assistants (claws) in your fleet",
    no_args_is_help=True,
)


@agent_app.command()
def install(
    claw: Optional[str] = typer.Option(
        None, "--claw", "-c", help="Claw type to install"
    ),
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Target host"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Install a claw on a host."""
    install_command(claw=claw, host=host, yes=yes)


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


def _parse_claw_name(claw_name: str) -> tuple[str, str]:
    """Parse claw name into host and claw type.

    Args:
        claw_name: Full claw name (e.g., "opc-work" or "openclaw-work")

    Returns:
        Tuple of (host_alias_or_name, claw_type)

    Raises:
        typer.Exit: If format is invalid or contains unsafe characters
    """
    if "-" not in claw_name:
        console.print(
            f"[red]Error:[/red] Invalid claw name format: '{rich_escape(claw_name)}'"
        )
        console.print(
            "Expected format: <claw-type>-<host> (e.g., 'opc-work', 'zc-kevin')"
        )
        raise typer.Exit(code=1)

    parts = claw_name.split("-", 1)
    if len(parts) != 2 or not all(parts):
        console.print(
            f"[red]Error:[/red] Invalid claw name format: '{rich_escape(claw_name)}'"
        )
        console.print(
            "Expected format: <claw-type>-<host> (e.g., 'opc-work', 'zc-kevin')"
        )
        raise typer.Exit(code=1)

    claw_type, host_alias = parts

    _validate_name_component(claw_type, "claw type")
    _validate_name_component(host_alias, "host alias")

    return host_alias, claw_type


def _resolve_alias_group(claw_type: str) -> set[str]:
    """Resolve claw type to its alias group.

    Args:
        claw_type: Claw type (e.g., "opc", "openclaw", "zc")

    Returns:
        Set of aliases for this claw type (e.g., {"opc", "openclaw"})
    """
    for group in ALIAS_GROUPS:
        if claw_type in group:
            return group
    return {claw_type}


def _get_installed_claw(host_alias: str, claw_type: str) -> tuple[str, dict] | None:
    """Get installed claw record from host.

    Args:
        host_alias: Host alias or hostname
        claw_type: Type of claw (e.g., "opc", "zc", "openclaw")

    Returns:
        Tuple of (installed_name, claw_record) or None if not found

    Raises:
        HostsFileCorruptedError: If hosts.json is corrupted
    """
    host_data = get_host(host_alias)
    if not host_data:
        return None

    claws = host_data.get("claws", {})
    alias_group = _resolve_alias_group(claw_type)

    for installed_name, claw_record in claws.items():
        base = installed_name.split("-")[0]
        if base in alias_group:
            return (installed_name, claw_record)

    return None


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

    console.print("\nSaving provider selection... ", end="")

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
    soul_dir = config_dir / "claws" / claw_type
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

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts

    Returns:
        True if stage completed successfully
    """
    console.print("[yellow]Validation not yet implemented - skipped[/yellow]")
    console.print()
    console.print(
        "Future validation will verify configuration files and run agent self-test."
    )

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
        ..., help="Claw name to configure (e.g., 'opc-work', 'zc-kevin')"
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
        clm agent configure opc-work
        clm agent configure zc-kevin --stage providers
        clm agent configure opc-work --yes
    """
    try:
        host_alias, claw_type = _parse_claw_name(claw_name)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(code=1)

    try:
        host_data = get_host(host_alias)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not host_data:
        console.print(f"[red]Error:[/red] Host '{rich_escape(host_alias)}' not found")
        console.print("Run 'clm host add' to register a host first.")
        raise typer.Exit(code=1)

    display_host = host_data.get("alias") or host_data["hostname"]

    try:
        result = _get_installed_claw(host_alias, claw_type)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] Hosts file corrupted: {e}")
        raise typer.Exit(code=1)

    if not result:
        console.print(
            f"[red]Error:[/red] Claw '{rich_escape(claw_type)}' not installed on '{rich_escape(display_host)}'"
        )
        console.print(
            f"Run 'clm agent install --claw {rich_escape(claw_type)} --host {rich_escape(host_alias)}' first."
        )
        raise typer.Exit(code=1)

    installed_name, _ = result

    try:
        current_state = get_onboarding_state(host_alias, installed_name)
    except OnboardingNotFoundError:
        try:
            initialize_onboarding(host_alias, installed_name)
            current_state = get_onboarding_state(host_alias, installed_name)
        except ClawNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)
    except ClawNotFoundError as e:
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
            success = stage_func(host_alias, installed_name, yes)
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
            f"Run 'clm agent start {rich_escape(claw_name)}' to start your agent."
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

            if can_skip_stage(installed_name, stage_name):
                try:
                    complete_stage(
                        host_alias, installed_name, stage_name, StageStatus.SKIPPED
                    )
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
            current_state = get_onboarding_state(host_alias, installed_name)
            if current_stage_state and current_state != current_stage_state:
                try:
                    transition_state(host_alias, installed_name, current_stage_state)
                except InvalidTransitionError as e:
                    console.print(f"[red]Error:[/red] {e}")
                    raise typer.Exit(code=1)

            success = stage_functions[stage_name](host_alias, installed_name, yes)

            if not success:
                console.print(
                    f"[red]Onboarding failed at stage: {rich_escape(stage_name)}[/red]"
                )
                raise typer.Exit(code=1)

            next_state = STAGE_TO_NEXT_STATE[stage_name]
            try:
                transition_state(host_alias, installed_name, next_state)
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
        f"Run 'clm agent start {rich_escape(claw_name)}' to start your agent."
    )


def _show_start_blocked_error(
    claw_name: str,
    host_alias: str,
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
            f"[red]Error:[/red] Cannot start {rich_escape(claw_name)} - onboarding not started"
        )
        console.print()
        console.print(
            f"Run 'clm agent configure {rich_escape(claw_name)}' to begin onboarding."
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
        f"[red]Error:[/red] Cannot start {rich_escape(claw_name)} - onboarding incomplete"
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
        f"Run 'clm agent configure {rich_escape(claw_name)}' to complete onboarding."
    )
    console.print()
    console.print("To force start anyway (not recommended):")
    console.print(f"  clm agent start {rich_escape(claw_name)} --force")
    console.print()


@agent_app.command()
def remove(
    claw_name: str = typer.Argument(..., help="Claw name to remove"),
) -> None:
    """Remove an agent from a host.

    [Not yet implemented]
    """
    console.print(
        f"[yellow]Not implemented:[/yellow] remove '{rich_escape(claw_name)}'"
    )
    console.print("This command will allow removing agents in a future release.")
    raise typer.Exit(code=1)


@agent_app.command()
def start(
    claw_name: str = typer.Argument(..., help="Claw name to start"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force start even if onboarding incomplete"
    ),
) -> None:
    """Start an agent.

    Checks onboarding state before allowing start.
    Only agents in READY state can start normally.
    Use --force to bypass this check (not recommended).
    """
    try:
        host_alias, claw_type = _parse_claw_name(claw_name)

        try:
            host_data = get_host(host_alias)
        except HostsFileCorruptedError as e:
            console.print(f"[red]Error:[/red] {e}")
            console.print("Run 'clm host list' to see if hosts.json can be read.")
            raise typer.Exit(code=1)

        if not host_data:
            console.print(
                f"[red]Error:[/red] Host '{rich_escape(host_alias)}' not found"
            )
            console.print("Run 'clm host add' to add a host first.")
            raise typer.Exit(code=1)

        display_host = host_data.get("alias", host_data.get("hostname", host_alias))

        result = _get_installed_claw(host_alias, claw_type)
        if not result:
            console.print(
                f"[red]Error:[/red] Claw '{rich_escape(claw_type)}' not installed on {rich_escape(display_host)}"
            )
            console.print(
                f"Run 'clm agent install --claw {rich_escape(claw_type)} --host {rich_escape(host_alias)}' to install it."
            )
            raise typer.Exit(code=1)

        installed_name, claw_record = result

        try:
            current_state = get_onboarding_state(host_alias, installed_name)
        except OnboardingNotFoundError:
            try:
                initialize_onboarding(host_alias, installed_name)
                current_state = get_onboarding_state(host_alias, installed_name)
            except ClawNotFoundError as e:
                console.print(f"[red]Error:[/red] {e}")
                raise typer.Exit(code=1)

        if current_state == OnboardingState.READY:
            console.print(
                f"[green]Starting agent:[/green] {rich_escape(installed_name)} on {rich_escape(display_host)}"
            )
            console.print("[dim]Agent start functionality coming soon.[/dim]")
            raise typer.Exit(code=0)

        if force:
            console.print(
                "[yellow]Warning: Starting agent with incomplete onboarding[/yellow]"
            )
            console.print(
                f"[green]Starting agent:[/green] {rich_escape(installed_name)} on {rich_escape(display_host)}"
            )
            console.print("[dim]Agent start functionality coming soon.[/dim]")
            raise typer.Exit(code=0)

        _show_start_blocked_error(
            claw_name, host_alias, installed_name, current_state, claw_record
        )
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        raise typer.Exit(code=1)


@agent_app.command()
def stop(
    claw_name: str = typer.Argument(..., help="Claw name to stop"),
) -> None:
    """Stop an agent.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] stop '{rich_escape(claw_name)}'")
    console.print("This command will allow stopping agents in a future release.")
    raise typer.Exit(code=0)


@agent_app.command()
def logs(
    claw_name: str = typer.Argument(..., help="Claw name to view logs for"),
) -> None:
    """View agent logs.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] logs '{rich_escape(claw_name)}'")
    console.print("This command will allow viewing agent logs in a future release.")
    raise typer.Exit(code=0)


secret_app = typer.Typer(
    name="secret",
    help="Manage secrets for agent instances",
    no_args_is_help=True,
)


@secret_app.command(name="set")
def secret_set(
    claw_name: str = typer.Argument(..., help="Claw name (e.g., opc-work)"),
    key: str = typer.Argument(..., help="Secret key name (e.g., OPENAI_API_KEY)"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Description of the secret"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip overwrite confirmation"),
) -> None:
    """Set a secret value for an agent instance."""
    from clawrium.cli.secret import set_cmd

    set_cmd(claw_name=claw_name, key=key, description=description, yes=yes)


@secret_app.command(name="list")
def secret_list(
    claw_name: str = typer.Argument(..., help="Claw name (e.g., zc-kevin)"),
) -> None:
    """List secrets for an agent instance."""
    from clawrium.cli.secret import list_cmd

    list_cmd(claw_name=claw_name)


@secret_app.command(name="remove")
def secret_remove(
    claw_name: str = typer.Argument(..., help="Claw name"),
    key: str = typer.Argument(..., help="Secret key to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove a secret from an agent instance."""
    from clawrium.cli.secret import remove_cmd

    remove_cmd(claw_name=claw_name, key=key, force=force)


@secret_app.command(name="import")
def secret_import(
    source_claw: str = typer.Argument(..., help="Source claw to import secrets from"),
    target_claw: str = typer.Argument(..., help="Target claw to import secrets to"),
) -> None:
    """Import secrets from another claw instance.

    [Not yet implemented]
    """
    console.print(
        f"[yellow]Not implemented:[/yellow] import secrets from '{rich_escape(source_claw)}' to '{rich_escape(target_claw)}'"
    )
    console.print(
        "This command will allow importing secrets between claws in a future release."
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
    claw_name: str = typer.Argument(..., help="Name of the claw to show"),
) -> None:
    """Show detailed information about an agent type."""
    from clawrium.cli.registry import show

    show(claw_name=claw_name)


agent_app.add_typer(registry_app, name="registry")
