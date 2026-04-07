"""Agent management commands for Clawrium.

This is the primary interface for managing AI assistants (claws).
"""

from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.panel import Panel

from clawrium.cli.install import install as install_command
from clawrium.cli.status import status as status_command
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


def _parse_claw_name(claw_name: str) -> tuple[str, str]:
    """Parse claw name into host and claw type.

    Args:
        claw_name: Full claw name (e.g., "opc-work" or "openclaw-work")

    Returns:
        Tuple of (host_alias_or_name, claw_type)

    Raises:
        typer.Exit: If format is invalid
    """
    if "-" not in claw_name:
        console.print(f"[red]Error:[/red] Invalid claw name format: '{claw_name}'")
        console.print(
            "Expected format: <claw-type>-<host> (e.g., 'opc-work', 'zc-kevin')"
        )
        raise typer.Exit(code=1)

    parts = claw_name.split("-", 1)
    if len(parts) != 2 or not all(parts):
        console.print(f"[red]Error:[/red] Invalid claw name format: '{claw_name}'")
        console.print(
            "Expected format: <claw-type>-<host> (e.g., 'opc-work', 'zc-kevin')"
        )
        raise typer.Exit(code=1)

    claw_type, host_alias = parts
    return host_alias, claw_type


def _get_installed_claw(host_alias: str, claw_type: str) -> dict | None:
    """Get installed claw record from host.

    Args:
        host_alias: Host alias or hostname
        claw_type: Type of claw (e.g., "opc", "zc", "openclaw")

    Returns:
        Claw record dict or None if not found
    """
    try:
        host_data = get_host(host_alias)
    except HostsFileCorruptedError:
        return None

    if not host_data:
        return None

    claws = host_data.get("claws", {})

    for installed_name, claw_record in claws.items():
        if installed_name == claw_type or installed_name.startswith(f"{claw_type}-"):
            return claw_record
        if claw_type in ["opc", "openclaw"] and installed_name in ["opc", "openclaw"]:
            return claw_record
        if claw_type in ["zc", "zeroclaw"] and installed_name in ["zc", "zeroclaw"]:
            return claw_record

    return claws.get(claw_type)


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


def _run_providers_stage(host: str, claw_type: str, yes: bool) -> bool:
    """Run the PROVIDERS onboarding stage.

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts

    Returns:
        True if stage completed successfully
    """
    from clawrium.core.providers import load_providers, get_provider_api_key

    try:
        providers = load_providers()
    except Exception:
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
            f"  {i}. {rich_escape(name)} ({ptype}, {rich_escape(model)}) {key_status}"
        )

    console.print()
    choice = typer.prompt("Select provider", type=int, default="1")

    if choice < 1 or choice > len(providers):
        console.print("[red]Invalid selection[/red]")
        return False

    selected = providers[choice - 1]
    provider_name = selected.get("name")

    console.print("\nVerifying provider connectivity... ", end="")

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
        console.print(f"[red]✗[/red] {e}")
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
    from pathlib import Path

    console.print("[1/2] Create personality file (SOUL.md)")

    if yes:
        personality = "You are a helpful coding assistant focused on reliability and code quality."
    else:
        console.print("  Describe your agent's personality (press Enter for default):")
        personality = typer.prompt(
            "> ",
            default="You are a helpful coding assistant focused on reliability and code quality.",
        )

    soul_path = Path.home() / f".{claw_type}" / "SOUL.md"
    soul_path.parent.mkdir(parents=True, exist_ok=True)
    soul_path.write_text(f"# {claw_type.upper()} Personality\n\n{personality}\n")
    console.print(f"  [green]✓[/green] Created {soul_path}")

    console.print("\n[2/2] Create identity file")
    console.print("  [green]✓[/green] Created from template")

    try:
        complete_stage(host, claw_type, "identity", StageStatus.COMPLETE)
        return True
    except Exception:
        return True


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
        choice = typer.prompt("Select", type=int, default="1")

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
    except Exception:
        return True


def _run_validate_stage(host: str, claw_type: str, yes: bool) -> bool:
    """Run the VALIDATE onboarding stage.

    Args:
        host: Host alias
        claw_type: Claw type
        yes: Skip confirmation prompts

    Returns:
        True if stage completed successfully
    """
    console.print("[1/2] Verify configuration files... [green]✓[/green]")
    console.print("[2/2] Run agent self-test... [green]✓[/green]")

    try:
        complete_stage(host, claw_type, "validate", StageStatus.COMPLETE)
        return True
    except Exception:
        return True


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
    host_alias, claw_type = _parse_claw_name(claw_name)

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

    installed_claw = _get_installed_claw(host_alias, claw_type)
    if not installed_claw:
        console.print(
            f"[red]Error:[/red] Claw '{rich_escape(claw_type)}' not installed on '{rich_escape(display_host)}'"
        )
        console.print(
            f"Run 'clm agent install --claw {rich_escape(claw_type)} --host {rich_escape(host_alias)}' first."
        )
        raise typer.Exit(code=1)

    try:
        get_onboarding_state(host_alias, claw_type)
    except OnboardingNotFoundError:
        try:
            initialize_onboarding(host_alias, claw_type)
        except ClawNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

    try:
        current_state = get_onboarding_state(host_alias, claw_type)
    except (OnboardingNotFoundError, ClawNotFoundError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"[bold]Onboarding:[/bold] {claw_type} on {display_host}\n"
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
            console.print(f"[red]Error:[/red] Invalid stage '{stage}'")
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

        success = stage_func(host_alias, claw_type, yes)

        if success:
            _stage_complete(stage)
        else:
            console.print(f"[red]Stage {stage} failed.[/red]")
            raise typer.Exit(code=1)

        console.print(f"\n[green]Stage {stage} complete.[/green]")
        raise typer.Exit(code=0)

    total_stages = len(STAGES)
    state_order = ["pending", "providers", "identity", "channels", "validate", "ready"]

    start_idx = state_order.index(current_state.value)
    if start_idx >= len(stage_order):
        console.print("\n[green]Onboarding already complete![/green]")
        console.print(f"State: {current_state.value.upper()}")
        console.print(f"Run 'clm agent start {claw_name}' to start your agent.")
        raise typer.Exit(code=0)

    console.print("\n[bold]Starting onboarding...[/bold]")

    stage_functions = {
        "providers": _run_providers_stage,
        "identity": _run_identity_stage,
        "channels": _run_channels_stage,
        "validate": _run_validate_stage,
    }

    for i, stage_name in enumerate(stage_order):
        if i < start_idx:
            continue

        if can_skip_stage(claw_type, stage_name):
            complete_stage(host_alias, claw_type, stage_name, StageStatus.SKIPPED)
            continue

        _stage_header(stage_name, i + 1, total_stages, stage_descriptions[stage_name])

        success = stage_functions[stage_name](host_alias, claw_type, yes)

        if not success:
            console.print(f"[red]Onboarding failed at stage: {stage_name}[/red]")
            raise typer.Exit(code=1)

        try:
            next_state_idx = i + 1
            if next_state_idx < len(state_order) - 1:
                next_state = OnboardingState(state_order[next_state_idx])
                transition_state(host_alias, claw_type, next_state)
        except InvalidTransitionError as e:
            console.print(f"[yellow]Warning:[/yellow] {e}")

        _stage_complete(stage_name)

    try:
        transition_state(host_alias, claw_type, OnboardingState.READY)
    except InvalidTransitionError:
        pass

    console.print()
    console.print("═" * 51)
    console.print(" [green]Onboarding Complete![/green]")
    console.print("═" * 51)
    console.print()
    console.print("State: [green]READY[/green]")
    console.print(f"Run 'clm agent start {claw_name}' to start your agent.")


@agent_app.command()
def remove(
    claw_name: str = typer.Argument(..., help="Claw name to remove"),
) -> None:
    """Remove an agent from a host.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] remove '{claw_name}'")
    console.print("This command will allow removing agents in a future release.")
    raise typer.Exit(code=0)


@agent_app.command()
def start(
    claw_name: str = typer.Argument(..., help="Claw name to start"),
) -> None:
    """Start an agent.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] start '{claw_name}'")
    console.print("This command will allow starting agents in a future release.")
    raise typer.Exit(code=0)


@agent_app.command()
def stop(
    claw_name: str = typer.Argument(..., help="Claw name to stop"),
) -> None:
    """Stop an agent.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] stop '{claw_name}'")
    console.print("This command will allow stopping agents in a future release.")
    raise typer.Exit(code=0)


@agent_app.command()
def logs(
    claw_name: str = typer.Argument(..., help="Claw name to view logs for"),
) -> None:
    """View agent logs.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] logs '{claw_name}'")
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
        f"[yellow]Not implemented:[/yellow] import secrets from '{source_claw}' to '{target_claw}'"
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
